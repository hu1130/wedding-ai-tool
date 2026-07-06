"""Quality review API."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.quality_review import QualityReview
from backend.models.task import Task

router = APIRouter(prefix="/api", tags=["quality-review"])


class QualityReviewRequest(BaseModel):
    face_score: int
    dress_score: int
    pose_score: int
    background_score: int
    overall_score: Optional[int] = None
    pass_result: Optional[bool] = None
    notes: str = ""
    reviewer: str = ""


@router.get("/quality-reviews")
async def list_quality_reviews():
    """List all saved quality reviews."""
    reviews = QualityReview.list_all()
    return {"success": True, "reviews": reviews, "total": len(reviews)}


@router.get("/task/{task_id}/quality-review")
async def get_quality_review(task_id: str):
    """Get one task's quality review."""
    task = Task.get(task_id)
    if not task:
        raise HTTPException(404, detail="任务不存在")

    review = QualityReview.get(task_id)
    return {"success": True, "review": review}


@router.put("/task/{task_id}/quality-review")
async def upsert_quality_review(task_id: str, req: QualityReviewRequest):
    """Create or update one task's quality review."""
    task = Task.get(task_id)
    if not task:
        raise HTTPException(404, detail="任务不存在")

    try:
        review = QualityReview.upsert(
            task_id,
            face_score=req.face_score,
            dress_score=req.dress_score,
            pose_score=req.pose_score,
            background_score=req.background_score,
            overall_score=req.overall_score,
            pass_result=req.pass_result,
            notes=req.notes,
            reviewer=req.reviewer,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return {"success": True, "review": review}
