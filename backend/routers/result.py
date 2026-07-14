"""结果获取接口"""

import os

from fastapi import APIRouter, Depends, HTTPException

from backend.models.task import Task
from backend.security.auth import AuthUser, current_user_from_request
from backend.utils.media import image_media_type_from_path, image_response

router = APIRouter(prefix="/api", tags=["结果"])


def _download_name(task_id: str, label: str, media_type: str) -> str:
    extension = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(media_type, "img")
    return f"{task_id}_{label}.{extension}"


def _media_type_for(value: str | None, local_path: str | None) -> str:
    if local_path and os.path.isfile(local_path):
        return image_media_type_from_path(local_path)
    return "image/jpeg"


@router.get("/task/{task_id}/result")
async def get_result(task_id: str, user: AuthUser = Depends(current_user_from_request)):
    """获取任务最终结果图片"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    final_value = task.output_files.get("final")
    local_path = Task.resolve_storage_path(final_value)
    media_type = _media_type_for(final_value, local_path)
    return image_response(
        value=final_value,
        local_path=local_path,
        default_prefix="",
        filename=_download_name(task_id, "final", media_type),
        not_found_detail="结果图片尚未生成",
    )


@router.get("/task/{task_id}/step/{step_name}")
async def get_step_result(
    task_id: str,
    step_name: str,
    user: AuthUser = Depends(current_user_from_request),
):
    """获取某一步的结果图片。step_name: dress / face / scene / composite"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    step_value = task.output_files.get(step_name)
    step_path = Task.resolve_storage_path(step_value)
    media_type = _media_type_for(step_value, step_path)
    return image_response(
        value=step_value,
        local_path=step_path,
        default_prefix="",
        filename=_download_name(task_id, step_name, media_type),
        not_found_detail=f"步骤 {step_name} 的结果图片不存在",
    )


@router.get("/task/{task_id}/input/{input_name}")
async def get_input_image(
    task_id: str,
    input_name: str,
    user: AuthUser = Depends(current_user_from_request),
):
    """获取任务输入素材图片。input_name: model / dress / face / pose_reference"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    input_paths = {
        "model": task.model_file,
        "dress": task.dress_file,
        "face": task.face_file,
        "pose_reference": task.pose_reference_file,
    }
    if input_name not in input_paths:
        raise HTTPException(404, detail="输入素材不存在")

    input_value = input_paths[input_name]
    image_path = Task.resolve_storage_path(input_value)
    media_type = _media_type_for(input_value, image_path)
    return image_response(
        value=input_value,
        local_path=image_path,
        default_prefix="uploads",
        filename=_download_name(task_id, input_name, media_type),
        not_found_detail="输入素材不存在",
    )
