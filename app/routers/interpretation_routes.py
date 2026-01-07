from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.services.interpretation.result_interpreter import interpreter
from .registry import register_router

router = APIRouter(prefix="/interpretation", tags=["interpretation"])

class InterpretationRequest(BaseModel):
    result_content: str
    context_description: str
    
class InterpretationResponse(BaseModel):
    analysis: str
    charts: List[Dict[str, Any]]
    original_context: str

@router.post("/analyze", response_model=InterpretationResponse)
async def analyze_result(request: InterpretationRequest):
    """
    Analyze a result file/text and provide interpretation and charts.
    """
    try:
        result = interpreter.interpret(
            result_content=request.result_content,
            context_description=request.context_description
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

register_router(
    router,
    "app.routers.interpretation_routes",
    "Interpretation",
    tags=["interpretation"]
)
