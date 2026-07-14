"""Quality review API."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.models.quality_review import QualityReview
from backend.models.task import Task
from backend.security.auth import AuthUser, current_user_from_request

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
async def list_quality_reviews(user: AuthUser = Depends(current_user_from_request)):
    """List all saved quality reviews."""
    reviews = QualityReview.list_all(
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    return {"success": True, "reviews": reviews, "total": len(reviews)}


@router.get("/task/{task_id}/quality-review")
async def get_quality_review(
    task_id: str,
    user: AuthUser = Depends(current_user_from_request),
):
    """Get one task's quality review."""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    review = QualityReview.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    return {"success": True, "review": review}


@router.put("/task/{task_id}/quality-review")
async def upsert_quality_review(
    task_id: str,
    req: QualityReviewRequest,
    user: AuthUser = Depends(current_user_from_request),
):
    """Create or update one task's quality review."""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
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
            tenant_id=user.tenant_id,
            platform_user_id=user.platform_user_id,
            local_user_id=user.local_user_id,
            app_code=user.app_code,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return {"success": True, "review": review}
