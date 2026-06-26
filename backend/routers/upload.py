"""上传接口"""
from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.utils.image import save_upload, validate_image

router = APIRouter(prefix="/api", tags=["上传"])


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """
    上传图片素材
    支持: jpg, jpeg, png, webp
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, detail="只支持图片文件")

    content = await file.read()

    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, detail="图片不能超过 20MB")

    if not validate_image(content):
        raise HTTPException(400, detail="无效的图片文件")

    try:
        file_id = await save_upload(content, file.filename)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return {
        "success": True,
        "file_id": file_id,
        "file_path": file_id,
        "filename": file.filename,
    }
