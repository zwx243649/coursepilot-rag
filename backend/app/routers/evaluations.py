from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Course
from app.schemas import EvaluationRequest, EvaluationResponse
from app.services.evaluation import run_evaluation


router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.post("/run", response_model=EvaluationResponse)
def execute_evaluation(
    payload: EvaluationRequest,
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    if db.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return run_evaluation(payload.course_id, payload.cases, payload.top_k)

