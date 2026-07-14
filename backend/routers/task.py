"""任务管理接口"""
import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from backend.config import settings
from backend.models.asset import AssetLibrary
from backend.models.clothing import SUPPORTED_CLOTHING_TYPES
from backend.models.task import Task
from backend.security.auth import AuthUser, current_user_from_request
from backend.security.rate_limit import (
    RateLimitExceeded,
    check_create_task_rate,
    identify_subject,
    raise_http_429,
)
from backend.services.task_queue import enqueue_task
from backend.storage.object_storage import get_object_storage
from backend.utils.image import resolve_upload_path

router = APIRouter(prefix="/api", tags=["任务"])

CUSTOM_SCENE_NAME = "自定义背景"
MAX_SCENE_PROMPT_LENGTH = 240
POSE_MODES = {"stable", "light", "experimental"}
STABLE_POSE = "保持原姿势"
LIGHT_POSES = {"正面站姿，双臂自然下垂", "轻微行走感，裙摆自然展开"}
CLOTHING_TYPES = SUPPORTED_CLOTHING_TYPES
EXPORT_NAME_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


def _is_inside(path: str, root: str) -> bool:
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
        return os.path.commonpath([path_abs, root_abs]) == root_abs
    except ValueError:
        return False


def _remove_file_if_safe(path: Optional[str], root: str) -> bool:
    if not path or not _is_inside(path, root) or not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def _remove_dir_if_safe(path: str, root: str) -> bool:
    if not _is_inside(path, root) or not os.path.isdir(path):
        return False
    shutil.rmtree(path)
    return True


def _remove_object_if_safe(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        storage_key = Task.to_storage_path(path)
        return bool(storage_key and get_object_storage().delete(storage_key))
    except Exception:
        return False


def _remaining_input_paths() -> set[str]:
    paths: set[str] = set()
    for task in Task.list_internal():
        for candidate in [task.model_file, task.dress_file, task.face_file, task.pose_reference_file]:
            if candidate:
                paths.add(os.path.abspath(candidate))
    for asset in AssetLibrary.list_all():
        if asset.get("file_id"):
            paths.add(os.path.abspath(AssetLibrary.resolve_file_path(asset["file_id"])))
    return paths


def _cleanup_task_files(task: Task) -> dict:
    removed_files = 0
    removed_dirs = 0
    removed_objects = 0

    output_dir = os.path.join(settings.output_dir, task.task_id)
    if _remove_dir_if_safe(output_dir, settings.output_dir):
        removed_dirs += 1
        removed_objects += 1 if _remove_object_if_safe(f"outputs/{task.task_id}") else 0
    else:
        for path in task.output_files.values():
            if _remove_file_if_safe(path, settings.output_dir):
                removed_files += 1
            if _remove_object_if_safe(path):
                removed_objects += 1

    remaining_inputs = _remaining_input_paths()
    for path in [task.model_file, task.dress_file, task.face_file, task.pose_reference_file]:
        if path and os.path.abspath(path) not in remaining_inputs:
            if _remove_file_if_safe(path, settings.upload_dir):
                removed_files += 1
            if _remove_object_if_safe(path):
                removed_objects += 1

    return {
        "removed_files": removed_files,
        "removed_dirs": removed_dirs,
        "removed_objects": removed_objects,
    }


def _check_generation_rate(request: Request, user: AuthUser, amount: int = 1) -> None:
    try:
        check_create_task_rate(
            identify_subject(request, user.user_id if user.is_authenticated else None),
            amount=amount,
        )
    except RateLimitExceeded as exc:
        raise_http_429(exc)


def _task_series_root(task: Task) -> str:
    return task.parent_task_id or task.task_id


def _next_rerun_index(
    root_task_id: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
) -> int:
    series = [
        task for task in Task.list_internal(
            tenant_id=tenant_id,
            platform_user_id=platform_user_id,
        )
        if task.task_id == root_task_id or task.parent_task_id == root_task_id
    ]
    if not series:
        return 2
    return max((getattr(task, "rerun_index", 1) or 1 for task in series), default=1) + 1


def _clone_task_for_rerun(source: Task) -> Task:
    root_task_id = _task_series_root(source)
    next_index = _next_rerun_index(
        root_task_id,
        tenant_id=source.tenant_id,
        platform_user_id=source.platform_user_id,
    )
    root_task = Task.get(
        root_task_id,
        tenant_id=source.tenant_id,
        platform_user_id=source.platform_user_id,
    )
    base_name = (root_task.name if root_task else source.name) or f"任务_{root_task_id}"

    return Task(
        name=f"{base_name} V{next_index}",
        model_file=source.model_file,
        dress_file=source.dress_file,
        face_file=source.face_file,
        pose_reference_file=source.pose_reference_file,
        clothing_type=source.clothing_type,
        scene=source.scene,
        scene_prompt=source.scene_prompt,
        resolution=source.resolution,
        face_swap=source.face_swap,
        pose=source.pose,
        pose_mode=source.pose_mode,
        preserve_face=source.preserve_face,
        generation_mode=source.generation_mode,
        parent_task_id=root_task_id,
        rerun_index=next_index,
        tenant_id=source.tenant_id,
        platform_user_id=source.platform_user_id,
        local_user_id=source.local_user_id,
        app_code=source.app_code,
    )


def _safe_export_name(value: str) -> str:
    cleaned = EXPORT_NAME_PATTERN.sub("_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned[:48] or "deliverable"


def _exportable_deliverables(
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
) -> list[tuple[Task, str]]:
    deliverables: list[tuple[Task, str]] = []
    for task in Task.list_internal(
        tenant_id=tenant_id,
        platform_user_id=platform_user_id,
    ):
        if not task.is_deliverable or task.status.value != "completed":
            continue
        final_path = task.output_files.get("final")
        if final_path and Task.output_exists(final_path):
            deliverables.append((task, final_path))

    return sorted(
        deliverables,
        key=lambda item: item[0].deliverable_at or item[0].completed_at or item[0].created_at,
    )


def _read_output_bytes(path: str) -> bytes:
    resolved_path = Task.resolve_storage_path(path)
    if resolved_path and os.path.isfile(resolved_path):
        with open(resolved_path, "rb") as f:
            return f.read()
    storage_key = Task.to_storage_path(path)
    return get_object_storage().get_bytes(storage_key)


class CreateTaskRequest(BaseModel):
    name: Optional[str] = None
    model_file: str
    dress_file: str
    face_file: Optional[str] = None
    pose_reference_file: Optional[str] = None
    clothing_type: str = "wedding_gown"
    scene: str = "海边"
    scene_prompt: Optional[str] = None
    resolution: str = "1k"
    face_swap: bool = False
    pose: str = "保持原姿势"
    pose_mode: str = "stable"
    preserve_face: bool = True
    generation_mode: str = "stable"


class BatchCreateRequest(BaseModel):
    tasks: list[CreateTaskRequest]


class DeliverableRequest(BaseModel):
    is_deliverable: bool = True


def _build_task(req: CreateTaskRequest, user: AuthUser) -> Task:
    scene_prompt = (req.scene_prompt or "").strip()
    pose = (req.pose or STABLE_POSE).strip() or STABLE_POSE
    pose_mode = req.pose_mode

    if len(scene_prompt) > MAX_SCENE_PROMPT_LENGTH:
        raise HTTPException(400, detail=f"自定义背景描述不能超过 {MAX_SCENE_PROMPT_LENGTH} 个字符")

    if req.scene == CUSTOM_SCENE_NAME:
        if not scene_prompt:
            raise HTTPException(400, detail="请选择预设背景，或填写自定义背景描述")
    elif req.scene not in settings.scenes:
        valid = list(settings.scenes.keys())
        raise HTTPException(400, detail=f"不支持的场景: {req.scene}，可选: {valid} 或 {CUSTOM_SCENE_NAME}")

    if req.resolution not in {"1k", "2k"}:
        raise HTTPException(400, detail="分辨率只支持 1k 或 2k")

    if req.generation_mode not in {"stable", "creative"}:
        raise HTTPException(400, detail="生成模式只支持 stable 或 creative")

    if req.clothing_type not in CLOTHING_TYPES:
        valid = ", ".join(sorted(CLOTHING_TYPES))
        raise HTTPException(400, detail=f"Unsupported clothing_type. Supported values: {valid}")

    if pose_mode not in POSE_MODES:
        raise HTTPException(400, detail="动作模式只支持 stable、light 或 experimental")

    if pose_mode == "stable" and pose != STABLE_POSE:
        pose_mode = "light" if pose in LIGHT_POSES else "experimental"

    try:
        model_file = resolve_upload_path(req.model_file)
        dress_file = resolve_upload_path(req.dress_file)
        face_file = resolve_upload_path(req.face_file) if req.face_file else None
        pose_reference_file = (
            resolve_upload_path(req.pose_reference_file) if req.pose_reference_file else None
        )
    except FileNotFoundError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return Task(
        name=req.name,
        model_file=model_file,
        dress_file=dress_file,
        face_file=face_file,
        pose_reference_file=pose_reference_file,
        clothing_type=req.clothing_type,
        scene=req.scene,
        scene_prompt=scene_prompt,
        resolution=req.resolution,
        face_swap=req.face_swap,
        pose=pose,
        pose_mode=pose_mode,
        preserve_face=req.preserve_face,
        generation_mode=req.generation_mode,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
        local_user_id=user.local_user_id,
        app_code=user.app_code,
    )


@router.post("/create-task")
async def create_task(
    req: CreateTaskRequest,
    request: Request,
    user: AuthUser = Depends(current_user_from_request),
):
    """创建单个生成任务"""
    _check_generation_rate(request, user)
    task = _build_task(req, user)
    task.save()

    # 提交到任务队列
    await enqueue_task(task.task_id)

    return {
        "success": True,
        "task_id": task.task_id,
        "status": task.status.value,
    }


@router.post("/batch-create")
async def batch_create(
    req: BatchCreateRequest,
    request: Request,
    user: AuthUser = Depends(current_user_from_request),
):
    """批量创建任务"""
    _check_generation_rate(request, user, amount=len(req.tasks))
    task_ids = []
    for t in req.tasks:
        task = _build_task(t, user)
        task.save()
        await enqueue_task(task.task_id)
        task_ids.append(task.task_id)

    return {
        "success": True,
        "task_ids": task_ids,
        "count": len(task_ids),
    }


@router.get("/task/{task_id}")
async def get_task(task_id: str, user: AuthUser = Depends(current_user_from_request)):
    """查询任务状态"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")
    return {"success": True, "task": task.to_public_dict()}


@router.get("/deliverables/export")
async def export_deliverables(user: AuthUser = Depends(current_user_from_request)):
    """导出所有已标记可交付的最终图。"""
    deliverables = _exportable_deliverables(
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not deliverables:
        raise HTTPException(404, detail="还没有可导出的可交付成品")

    manifest = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (task, final_path) in enumerate(deliverables, start=1):
            _, extension = os.path.splitext(final_path)
            extension = extension if extension else ".png"
            safe_name = _safe_export_name(task.name or task.task_id)
            archive_name = f"images/{index:03d}_{safe_name}_{task.task_id}{extension.lower()}"

            archive.writestr(archive_name, _read_output_bytes(final_path))
            manifest.append(
                {
                    "index": index,
                    "task_id": task.task_id,
                    "name": task.name,
                    "scene": task.scene,
                    "scene_prompt": task.scene_prompt,
                    "pose": task.pose,
                    "resolution": task.resolution,
                    "version": task.rerun_index,
                    "deliverable_at": task.deliverable_at,
                    "file": archive_name,
                }
            )

        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "exported_at": datetime.now().isoformat(),
                    "count": len(manifest),
                    "items": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    filename = f"wedding-deliverables-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/task/{task_id}/deliverable")
async def update_task_deliverable(
    task_id: str,
    req: DeliverableRequest,
    user: AuthUser = Depends(current_user_from_request),
):
    """标记或取消标记最终图是否可交付。"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    if req.is_deliverable:
        final_path = task.output_files.get("final")
        final_exists = bool(final_path and Task.output_exists(final_path))
        if task.status.value != "completed" or not final_exists:
            raise HTTPException(409, detail="只有已完成且最终图文件存在的任务可以标记为可交付")

    task.is_deliverable = req.is_deliverable
    task.deliverable_at = datetime.now().isoformat() if req.is_deliverable else ""
    task.save()

    return {"success": True, "task": task.to_public_dict()}


@router.post("/task/{task_id}/rerun")
async def rerun_task(
    task_id: str,
    request: Request,
    user: AuthUser = Depends(current_user_from_request),
):
    """基于同一组素材和参数重跑一个新版本"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    if task.status.value == "processing":
        raise HTTPException(409, detail="任务正在生成中，请完成或失败后再重跑")

    _check_generation_rate(request, user)
    rerun = _clone_task_for_rerun(task)
    rerun.save()
    await enqueue_task(rerun.task_id)

    return {
        "success": True,
        "task_id": rerun.task_id,
        "status": rerun.status.value,
        "parent_task_id": rerun.parent_task_id,
        "rerun_index": rerun.rerun_index,
    }


@router.delete("/task/{task_id}")
async def delete_task(task_id: str, user: AuthUser = Depends(current_user_from_request)):
    """删除任务记录和本地文件"""
    task = Task.get(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not task:
        raise HTTPException(404, detail="任务不存在")

    if task.status.value == "processing":
        raise HTTPException(409, detail="任务正在生成中，请完成或失败后再删除")

    deleted_task = Task.delete(
        task_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not deleted_task:
        raise HTTPException(404, detail="任务不存在")

    cleanup = _cleanup_task_files(deleted_task)
    return {"success": True, "task_id": task_id, **cleanup}


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    deliverable: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthUser = Depends(current_user_from_request),
):
    """任务列表"""
    tasks = Task.list_all(
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )

    if status:
        tasks = [t for t in tasks if t.get("status") == status]

    if deliverable is not None:
        tasks = [t for t in tasks if bool(t.get("is_deliverable")) == deliverable]

    total = len(tasks)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "success": True,
        "tasks": tasks[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
