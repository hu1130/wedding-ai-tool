"""上传接口"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from backend.config import settings
from backend.models.asset import AssetLibrary
from backend.security.auth import AuthUser, current_user_from_request
from backend.security.rate_limit import (
    RateLimitExceeded,
    check_upload_rate,
    identify_subject,
    raise_http_429,
)
from backend.utils.image import save_upload, validate_image

router = APIRouter(prefix="/api", tags=["上传"])


@router.post("/upload")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form("uncategorized"),
    user: AuthUser = Depends(current_user_from_request),
):
    """
    上传图片素材
    支持: jpg, jpeg, png, webp
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, detail="只支持图片文件")

    try:
        check_upload_rate(
            identify_subject(request, user.user_id if user.is_authenticated else None)
        )
    except RateLimitExceeded as exc:
        raise_http_429(exc)

    content = await file.read()

    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(400, detail=f"图片不能超过 {settings.max_upload_size_mb}MB")

    if not validate_image(content):
        raise HTTPException(400, detail="无效的图片文件")

    try:
        file_id = await save_upload(content, file.filename, content_type=file.content_type)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    asset = AssetLibrary.create(
        file_id=file_id,
        filename=file.filename,
        category=category,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
        local_user_id=user.local_user_id,
        app_code=user.app_code,
    )

    return {
        "success": True,
        "file_id": file_id,
        "file_path": file_id,
        "filename": file.filename,
        "asset": asset,
    }
