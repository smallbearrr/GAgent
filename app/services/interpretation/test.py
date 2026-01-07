import sys
import os
import json
import logging
import uuid
from typing import List

logging.basicConfig(level=logging.INFO)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from app.services.interpretation.result_interpreter import interpreter

def test_analysis_with_files(file_paths: List[str], data_description: str):
    """
    通用测试函数：使用指定的文件列表和数据描述进行分析测试
    :param file_paths: 数据文件路径列表
    :param data_description: 数据来源或生成方式的描述 (Context Description)
    """
    print(f"\n{'='*20} Test Analysis with Files {'='*20}")
    print(f"Description: {data_description}")
    
    # Check files
    valid_files = []
    print("Files check:")
    for fp in file_paths:
        abs_fp = os.path.abspath(fp)
        if os.path.exists(abs_fp):
            valid_files.append(abs_fp)
            print(f"  [OK] {abs_fp}")
        else:
            print(f"  [MISSING] {abs_fp}")
            
    if not valid_files:
        print("No valid files found. Aborting.")
        return

    output_name = f"custom_run_{uuid.uuid4().hex[:6]}"
    
    try:
        print(f"\nRunning interpreter (output_name={output_name})...")
        # 对于基于文件的分析，result_content 可以是一个简短的引导语，主体数据都在文件中
        result = interpreter.interpret(
            result_content=f"Data provided in attached files for analysis. Context: {data_description}", 
            context_description=data_description, 
            file_paths=valid_files,
            output_name=output_name
        )

        results_dir = os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(results_dir, exist_ok=True)
        
        # Save analysis
        md_file = os.path.join(results_dir, f"{output_name}.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(result.get("analysis", ""))
        
        print(f"\n[Analysis Completed]")
        print(f"Analysis Report: {md_file}")
        
        charts = result.get("charts", [])
        if charts:
            print(f"Charts Generated ({len(charts)}):")
            for c in charts:
                print(f"  - {c}")
        else:
            print("No charts generated.")
            
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()

def test_basic_functionality():
    context_description = "Web Server Load Test Results"
    result_content = """
    Test Summary:
    Total requests: 10,000
    Concurrency Level: 50
    Time taken for tests: 15.2 seconds

    Performance metrics:
    - Average Response Time: 120ms
    - Min Response Time: 45ms
    - Max Response Time: 580ms
    - 95th Percentile: 250ms
    - 99th Percentile: 450ms

    Requests per second: 658.21 [#/sec] (mean)
    Transfer rate: 450.5 [Kbytes/sec] received

    Error distribution:
    - 200 OK: 9950 (99.5%)
    - 500 Internal Server Error: 30 (0.3%)
    - 502 Bad Gateway: 20 (0.2%)

    Conclusion:
    The server handled the load well, with 99.5% success rate. 
    However, the 99th percentile latency spike indicates some instability under peak load.
    The error rate is acceptable but database connection pool settings should be reviewed.
    """

    print(f"\n{'='*20} 开始测试结果解读功能 {'='*20}")
    print(f"上下文描述: {context_description}")
    print(f"输入内容摘要:\n{result_content.strip()}\n")
    print(f"{'-'*60}")

    data_file_path = os.path.join(os.path.dirname(__file__), "test_server_metrics.csv")
    with open(data_file_path, "w", encoding="utf-8") as f:
        f.write("Time,CPU_Usage,Memory_Usage,Requests_Per_Sec\n")
        f.write("00:00,15,40,200\n")
        f.write("00:15,20,42,250\n")
        f.write("00:30,45,60,800\n")
        f.write("00:45,85,80,1200\n")
        f.write("01:00,30,50,400\n")
    print(f"Created temporary test file for analysis: {data_file_path}")

    try:
        # 调用解读服务
        output_name = "test_analysis_plan"
        print(f"Calling interpreter (saving to results/{output_name}*)...")
        
        result = interpreter.interpret(
            result_content=result_content, 
            context_description=context_description, 
            file_paths=[data_file_path],
            output_name=output_name
        )
        
        # Manually save MD file (aggregating plan results)
        results_dir = os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(results_dir, exist_ok=True)
        md_path = os.path.join(results_dir, f"{output_name}_analysis.md")
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(result["analysis"])
            print(f"Analysis text saved to: {md_path}")
        except Exception as e:
            print(f"Failed to save analysis text: {e}")
        
        print("\n[1] 文本分析结果 (Analysis):")
        print("Preview:")
        print(result.get("analysis")[:200] + "...")
        
        print(f"\n[Plan ID]: {result.get('plan_id')}")

        print("\n[2] 生成的图表 (Charts):")
        charts = result.get("charts", [])
        if charts:
            for chart in charts:
                print(f" - Generated chart: {chart}")
        else:
            print("未生成图表 (No charts generated or found).")

    except Exception as e:
        print(f"测试过程中发生错误: {e}")

    except Exception as e:
        print(f"测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 清理测试文件
        if os.path.exists(data_file_path):
            try:
                os.remove(data_file_path)
                print(f"Removed temporary test file: {data_file_path}")
            except Exception as e:
                print(f"Error removing temporary file: {e}")



if __name__ == "__main__":
    test_analysis_with_files(
        file_paths=[
            "D:\\AI Agent\\Metagenomics\\Metagenomics\\metaphlan_original\\Functional Annotation\\KEGG_pathway_expression_matrix.tsv"
        ],
        data_description="基于宏基因组测序数据，首先对原始测序数据进行去接头、去低质量序列及宿主序列去除等预处理，获得用于后续分析的有效数据（CleanData）。随后使用 MEGAHIT 对每个样本的有效数据进行 de novo 组装，并基于组装得到的 contigs 采用 prodigal 软件进行基因预测，通过 CD-HIT 去冗余获得非冗余的 Unigenes 集。基于 Unigene 的蛋白序列，采用 Diamond 软件与 KEGG（Kyoto Encyclopedia of Genes and Genomes）数据库进行比对注释，获得各 Unigene 对应的 KEGG 注释信息。根据比对上 reads 的数目及各 Unigene 的长度，计算各 Unigene 在每个样本中的丰度信息，并在功能注释层面对 KEGG 通路进行丰度统计与比较分析，从而获得各样本在不同 KEGG Pathway 水平上的丰度矩阵，用于后续的统计分析与可视化展示。"
    )
    # test_basic_functionality()
