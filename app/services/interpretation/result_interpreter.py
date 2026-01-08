import json
import logging
import os
import re
import uuid
import tempfile
import shutil
from typing import Any, Dict, List, Optional

try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from app.llm import LLMClient as LLM
from app.services.llm.llm_service import LLMService
from app.services.interpretation.data_process import DataProcessor
from app.services.interpretation.prompts import (
    INTERACTIVE_ANALYSIS_SYSTEM_PROMPT,
)
from app.database import init_db
from app.repository.plan_repository import PlanRepository

logger = logging.getLogger(__name__)

class DockerExecutor:
    def __init__(self, image: str = "agent-plotter", timeout_s: int = 30):
        self.image = image
        self.timeout_s = timeout_s
        if DOCKER_AVAILABLE:
            try:
                self.client = docker.from_env()
            except Exception as e:
                logger.warning(f"Failed to initialize Docker client: {e}")
                self.client = None
        else:
            self.client = None
            logger.warning("Docker python client not installed.")

    def execute(self, code: str, output_path: str, data_files: List[str] = []) -> Any:
        if not self.client:
            return False, "Docker client not available."

        output_dir = os.path.dirname(output_path)
        output_prefix = os.path.basename(output_path)

        code = self._instrument_code(code, autosave=True)

        with tempfile.TemporaryDirectory() as temp_dir:
            in_dir = os.path.join(temp_dir, "in")
            out_dir = os.path.join(temp_dir, "out")
            data_dir = os.path.join(temp_dir, "data")
            os.makedirs(in_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            # Copy data files to data directory to be mounted
            for fp in data_files:
                if os.path.exists(fp):
                    try:
                        shutil.copy(fp, data_dir)
                    except Exception as e:
                        logger.warning(f"Failed to copy data file {fp} to container context: {e}")
            
            script_path = os.path.join(in_dir, "run.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            container = None
            try:
                container = self.client.containers.run(
                    image=self.image,
                    command="python /in/run.py",
                    volumes={
                        os.path.abspath(in_dir): {"bind": "/in", "mode": "ro"},
                        os.path.abspath(out_dir): {"bind": "/out", "mode": "rw"},
                        os.path.abspath(data_dir): {"bind": "/data", "mode": "ro"},
                    },
                    working_dir="/out",
                    network_mode="none",
                    read_only=True,
                    detach=True,
                    stderr=True,
                    stdout=True,
                    mem_limit="4g",
                    pids_limit=128,
                    nano_cpus=2_000_000_000,  # 2 CPUs
                )

                # Wait with timeout
                res = container.wait(timeout=self.timeout_s)
                status = res.get("StatusCode", 1)

                logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

                if status != 0:
                    logger.error(f"Docker execution failed (exit={status}). Logs:\n{logs}")
                    return False, f"Execution failed (exit={status}). Logs:\n{logs}"

            except Exception as e:
                if container is not None:
                    try:
                        container.kill()
                    except Exception:
                        pass
                logger.error(f"Docker execution error: {e}")
                return False, f"Execution error: {str(e)}"
            finally:
                if container is not None:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass

            # Collect outputs
            generated_images = []
            saved = sorted([f for f in os.listdir(out_dir) if f.startswith("output_") and f.endswith(".png")])

            os.makedirs(output_dir, exist_ok=True)
            for idx, fname in enumerate(saved, start=1):
                src = os.path.join(out_dir, fname)
                dest = os.path.join(output_dir, f"{output_prefix}_{idx}.png")
                shutil.move(src, dest)
                generated_images.append(dest)

            return True, generated_images

    def execute_compute(self, code: str, data_files: List[str] = []) -> Any:
        if not self.client:
            return False, "Docker client not available."

        code = self._instrument_code(code, autosave=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            in_dir = os.path.join(temp_dir, "in")
            out_dir = os.path.join(temp_dir, "out")
            data_dir = os.path.join(temp_dir, "data")
            os.makedirs(in_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            for fp in data_files:
                if os.path.exists(fp):
                    try:
                        shutil.copy(fp, data_dir)
                    except Exception as e:
                        logger.warning(f"Failed to copy data file {fp} to container context: {e}")

            script_path = os.path.join(in_dir, "run.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            container = None
            try:
                container = self.client.containers.run(
                    image=self.image,
                    command="python /in/run.py",
                    volumes={
                        os.path.abspath(in_dir): {"bind": "/in", "mode": "ro"},
                        os.path.abspath(out_dir): {"bind": "/out", "mode": "rw"},
                        os.path.abspath(data_dir): {"bind": "/data", "mode": "ro"},
                    },
                    working_dir="/out",
                    network_mode="none",
                    read_only=True,
                    detach=True,
                    stderr=True,
                    stdout=True,
                    mem_limit="4g",
                    pids_limit=128,
                    nano_cpus=2_000_000_000,
                )

                res = container.wait(timeout=self.timeout_s)
                status = res.get("StatusCode", 1)
                logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

                if status != 0:
                    logger.error(f"Docker compute failed (exit={status}). Logs:\n{logs}")
                    return False, f"Execution failed (exit={status}). Logs:\n{logs}"
                return True, logs.strip()

            except Exception as e:
                if container is not None:
                    try:
                        container.kill()
                    except Exception:
                        pass
                logger.error(f"Docker compute error: {e}")
                return False, f"Execution error: {str(e)}"
            finally:
                if container is not None:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass

    def _instrument_code(self, code: str, *, autosave: bool) -> str:
        header = (
            "import os\n"
            "os.makedirs('/out/mplconfig', exist_ok=True)\n"
            "os.makedirs('/out/.cache', exist_ok=True)\n"
            "os.environ['MPLCONFIGDIR'] = '/out/mplconfig'\n"
            "os.environ['XDG_CACHE_HOME'] = '/out/.cache'\n"
            "os.environ['HOME'] = '/out'\n"
            "os.environ.setdefault('FONTCONFIG_PATH', '/etc/fonts')\n"
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
        )

        if not autosave:
            return header + "\n" + code + "\n"

        footer = (
            "\n"
            "# Auto-save figures to /out (Appended by DockerExecutor)\n"
            "try:\n"
            "    figs = [plt.figure(n) for n in plt.get_fignums()]\n"
            "    for i, fig in enumerate(figs, start=1):\n"
            "        fig.savefig(f'/out/output_{i}.png', dpi=150, bbox_inches='tight')\n"
            "except Exception as e:\n"
            "    print(f\"Failed to auto-save plots: {e}\")\n"
        )
        return header + "\n" + code + "\n" + footer

class ResultInterpreter:
    def __init__(self):
        init_db()
        self.max_retries = 2
        self.plan_repo = PlanRepository()
        
        qwen_client = LLM(provider="qwen", model="qwen-max")
        base_llm = LLMService(client=qwen_client)
        self.docker_executor = DockerExecutor(image="agent-plotter")
        self.interactive_llm = base_llm
        self.max_interactive_turns = 4

    def interpret(self, result_content: str, context_description: str, file_paths: Optional[List[str]] = None, output_name: Optional[str] = None) -> Dict[str, Any]:
        logger.info(f"Interpreting result for: {context_description}")

        file_content = ""
        if file_paths:
            file_content = self._process_files(file_paths)

        full_content = result_content
        if file_content:
            full_content += "\n\n" + file_content

        if not output_name:
            import uuid
            output_name = f"analysis_{uuid.uuid4().hex[:8]}"

        return self._interactive_interpret(
            result_content=full_content,
            context_description=context_description,
            file_paths=file_paths or [],
            output_name=output_name,
        )

    def _interactive_interpret(
        self,
        *,
        result_content: str,
        context_description: str,
        file_paths: List[str],
        output_name: Optional[str],
    ) -> Dict[str, Any]:
        plan_tree = self.plan_repo.create_plan(
            title=f"Analysis of {context_description}",
            description=f"Interactive analysis for {context_description}",
            metadata={"data": result_content},
        )

        if not output_name:
            output_name = f"analysis_{uuid.uuid4().hex[:8]}"

        results_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "results"))
        os.makedirs(results_dir, exist_ok=True)

        messages = [
            {"role": "system", "content": INTERACTIVE_ANALYSIS_SYSTEM_PROMPT.strip()},
            {
                "role": "user",
                "content": (
                    f"Context Description: {context_description}\n\n"
                    f"Result Content and Metadata:\n{result_content}"
                ),
            },
        ]

        for turn in range(1, self.max_interactive_turns + 1):
            response_text = self.interactive_llm.chat("", messages=messages)
            payload = self._parse_json(response_text)
            action = (payload.get("action") or "").strip().lower()

            if action == "compute":
                code = self._extract_code(payload.get("code", ""))
                if not code:
                    raise ValueError("LLM compute response missing python code.")
                success, output = self.docker_executor.execute_compute(code, file_paths)
                output_text = output if success else f"ERROR: {output}"
                output_text = self._truncate_output(output_text)
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Computation output (turn {turn}):\n{output_text}\n"
                            "If more data is needed, request another computation."
                        ),
                    }
                )
                continue

            if action == "final":
                chart_code = self._extract_code(payload.get("chart_code", ""))
                if not chart_code:
                    raise ValueError("LLM final response missing chart code.")
                success, images = self._execute_code(
                    chart_code,
                    os.path.join(results_dir, output_name),
                    file_paths,
                )
                if not success:
                    raise RuntimeError(f"Chart code execution failed: {images}")
                analysis_md = self._build_analysis_markdown(
                    summary_md=payload.get("summary_md", ""),
                    figures=payload.get("figures", []),
                    images=images,
                )
                return {
                    "analysis": analysis_md,
                    "charts": images,
                    "original_context": context_description,
                    "plan_id": plan_tree.id,
                }

            messages.append({"role": "assistant", "content": response_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The response was not valid. "
                        "Please return JSON with action compute or final."
                    ),
                }
            )

        raise RuntimeError("Interactive analysis did not complete within turn limit.")

    def _process_files(self, file_paths: List[str]) -> str:
        processed_data: List[str] = []
        for file_path in file_paths:
            if not os.path.exists(file_path):
                processed_data.append(f"### File: {os.path.basename(file_path)}\nStatus: File not found: {file_path}")
                continue

            file_name = os.path.basename(file_path)
            docker_path = f"/data/{file_name}"
            ext = os.path.splitext(file_name)[1].lower()

            # We pass metadata (not raw data previews) to LLM to keep context small and structured.
            if ext in [".csv", ".tsv", ".mat"]:
                try:
                    metadata = DataProcessor.get_metadata(file_path)
                    metadata_json = metadata.model_dump_json(indent=2)
                    processed_data.append(
                        f"### File Metadata: {file_name}\n"
                        f"- **Docker Path**: `{docker_path}`\n"
                        f"- **Metadata (JSON)**:\n"
                        f"```json\n{metadata_json}\n```\n"
                        f"(Note: The full file is available at `{docker_path}`. "
                        f"If you need raw data for charts, read it inside code using pandas/scipy.)"
                    )
                except Exception as e:
                    processed_data.append(
                        f"### File Metadata: {file_name}\n"
                        f"- **Docker Path**: `{docker_path}`\n"
                        f"Status: Error generating metadata: {str(e)}"
                    )
            else:
                processed_data.append(
                    f"### File: {file_name}\n"
                    f"- **Docker Path**: `{docker_path}`\n"
                    f"(Unsupported for metadata extraction; please read content from `{docker_path}` if needed.)"
                )

        return "\n\n".join(processed_data)

    def _extract_code(self, text: str) -> Optional[str]:
        """Extracts python code from markdown code blocks."""
        pattern = r"```python(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return self._normalize_code_newlines(match.group(1).strip())
        pattern_generic = r"```(.*?)```"
        match_generic = re.search(pattern_generic, text, re.DOTALL)
        if match_generic:
             return self._normalize_code_newlines(match_generic.group(1).strip())
        return None

    def _normalize_code_newlines(self, code: str) -> str:
        """Fix cases where the model returns escaped newlines instead of real ones."""
        if code.count("\n") <= 1 and "\\n" in code:
            candidate = code.replace("\\n", "\n")
            if candidate.count("\n") > code.count("\n"):
                return candidate
        return code

    def _extract_description(self, text: str) -> str:
        """Extract non-code text as description for logging."""
        # Remove code blocks
        cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        return cleaned.strip()

    def _execute_code(self, code: str, output_prefix: str, data_files: List[str] = []) -> Any:
        """Execute chart code using DockerExecutor."""
        return self.docker_executor.execute(code, output_prefix, data_files)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            while lines and lines[-1].strip().startswith("```"):
                lines.pop()
            cleaned = "\n".join(lines).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse JSON from LLM: %s", text)
            raise ValueError(f"Invalid JSON from LLM: {exc}") from exc

    def _truncate_output(self, text: str, limit: int = 6000) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...<truncated>..."

    def _build_analysis_markdown(
        self,
        *,
        summary_md: str,
        figures: List[Dict[str, Any]],
        images: List[str],
    ) -> str:
        sections = []
        if summary_md:
            sections.append(summary_md.strip())
        pairs = min(len(figures), len(images))
        for idx in range(pairs):
            fig = figures[idx] or {}
            title = fig.get("title") or f"Figure {idx + 1}"
            description = fig.get("description_md") or ""
            sections.append(f"### {title}\n")
            sections.append(f"![{title}]({images[idx]})\n")
            if description:
                sections.append(description.strip())
        if len(figures) > pairs:
            for idx in range(pairs, len(figures)):
                fig = figures[idx] or {}
                title = fig.get("title") or f"Figure {idx + 1}"
                description = fig.get("description_md") or ""
                sections.append(f"### {title}\n")
                if description:
                    sections.append(description.strip())
        return "\n\n".join(section for section in sections if section)

interpreter = ResultInterpreter()
