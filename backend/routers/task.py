"""任务管理接口"""
import os
import shutil
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.config import settings
from backend.models.task import Task
from backend.services.task_queue import enqueue_task
from backend.utils.image import resolve_upload_path

router = APIRouter(prefix="/api", tags=["任务"])


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


def _remaining_input_paths() -> set[str]:
    paths: set[str] = set()
    for task in Task.list_internal():
        for candidate in [task.model_file, task.dress_file, task.face_file]:
            if candidate:
                paths.add(os.path.abspath(candidate))
    return paths


def _cleanup_task_files(task: Task) -> dict:
    removed_files = 0
    removed_dirs = 0

    output_dir = os.path.join(settings.output_dir, task.task_id)
    if _remove_dir_if_safe(output_dir, settings.output_dir):
        removed_dirs += 1
    else:
        for path in task.output_files.values():
            if _remove_file_if_safe(path, settings.output_dir):
                removed_files += 1

    remaining_inputs = _remaining_input_paths()
    for path in [task.model_file, task.dress_file, task.face_file]:
        if path and os.path.abspath(path) not in remaining_inputs:
            if _remove_file_if_safe(path, settings.upload_dir):
                removed_files += 1

    return {"removed_files": removed_files, "removed_dirs": removed_dirs}


class CreateTaskRequest(BaseModel):
    name: Optional[str] = None
    model_file: str
    dress_file: str
    face_file: Optional[str] = None
    scene: str = "海边"
    resolution: str = "1k"
    face_swap: bool = False
    pose: str = "保持原姿势"
    preserve_face: bool = True
    generation_mode: str = "stable"


class BatchCreateRequest(BaseModel):
    tasks: list[CreateTaskRequest]


def _build_task(req: CreateTaskRequest) -> Task:
    if req.scene not in settings.scenes:
        valid = list(settings.scenes.keys())
        raise HTTPException(400, detail=f"不支持的场景: {req.scene}，可选: {valid}")

    if req.resolution not in {"1k", "2k"}:
        raise HTTPException(400, detail="分辨率只支持 1k 或 2k")

    if req.generation_mode not in {"stable", "creative"}:
        raise HTTPException(400, detail="生成模式只支持 stable 或 creative")

    try:
        model_file = resolve_upload_path(req.model_file)
        dress_file = resolve_upload_path(req.dress_file)
        face_file = resolve_upload_path(req.face_file) if req.face_file else None
    except FileNotFoundError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return Task(
        name=req.name,
        model_file=model_file,
        dress_file=dress_file,
        face_file=face_file,
        scene=req.scene,
        resolution=req.resolution,
        face_swap=req.face_swap,
        pose=req.pose,
        preserve_face=req.preserve_face,
        generation_mode=req.generation_mode,
    )


@router.post("/create-task")
async def create_task(req: CreateTaskRequest):
    """创建单个生成任务"""
    task = _build_task(req)
    task.save()

    # 提交到任务队列
    await enqueue_task(task.task_id)

    return {
        "success": True,
        "task_id": task.task_id,
        "status": task.status.value,
    }


@router.post("/batch-create")
async def batch_create(req: BatchCreateRequest):
    """批量创建任务"""
    task_ids = []
    for t in req.tasks:
        task = _build_task(t)
        task.save()
        await enqueue_task(task.task_id)
        task_ids.append(task.task_id)

    return {
        "success": True,
        "task_ids": task_ids,
        "count": len(task_ids),
    }


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    """查询任务状态"""
    task = Task.get(task_id)
    if not task:
        raise HTTPException(404, detail="任务不存在")
    return {"success": True, "task": task.to_public_dict()}


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """删除任务记录和本地文件"""
    task = Task.get(task_id)
    if not task:
        raise HTTPException(404, detail="任务不存在")

    if task.status.value == "processing":
        raise HTTPException(409, detail="任务正在生成中，请完成或失败后再删除")

    deleted_task = Task.delete(task_id)
    if not deleted_task:
        raise HTTPException(404, detail="任务不存在")

    cleanup = _cleanup_task_files(deleted_task)
    return {"success": True, "task_id": task_id, **cleanup}


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """任务列表"""
    tasks = Task.list_all()

    if status:
        tasks = [t for t in tasks if t.get("status") == status]

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
