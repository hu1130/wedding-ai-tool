"""结果获取接口"""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.models.task import Task

router = APIRouter(prefix="/api", tags=["结果"])


def _image_media_type(path: str) -> str:
    with open(path, "rb") as f:
        header = f.read(12)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _download_name(task_id: str, label: str, media_type: str) -> str:
    extension = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(media_type, "img")
    return f"{task_id}_{label}.{extension}"


@router.get("/task/{task_id}/result")
async def get_result(task_id: str):
    """获取任务最终结果图片"""
    task = Task.get(task_id)
    if not task:
        raise HTTPException(404, detail="任务不存在")

    final_path = task.output_files.get("final")
    if not final_path or not os.path.exists(final_path):
        raise HTTPException(404, detail="结果图片尚未生成")

    media_type = _image_media_type(final_path)
    return FileResponse(final_path, media_type=media_type, filename=_download_name(task_id, "final", media_type))


@router.get("/task/{task_id}/step/{step_name}")
async def get_step_result(task_id: str, step_name: str):
    """
    获取某一步的结果图片
    step_name: dress / face / scene
    """
    task = Task.get(task_id)
    if not task:
        raise HTTPException(404, detail="任务不存在")

    step_path = task.output_files.get(step_name)
    if not step_path or not os.path.exists(step_path):
        raise HTTPException(404, detail=f"步骤 {step_name} 的结果图片不存在")

    media_type = _image_media_type(step_path)
    return FileResponse(step_path, media_type=media_type, filename=_download_name(task_id, step_name, media_type))
