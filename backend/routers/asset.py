"""素材库接口"""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.models.asset import AssetLibrary
from backend.models.task import Task

router = APIRouter(prefix="/api", tags=["素材库"])


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


def _backfill_assets_from_tasks() -> int:
    """Register historical task inputs that were uploaded before the asset library existed."""
    created = 0
    seen: set[tuple[str, str]] = set()
    task_fields = [
        ("model", "model_file"),
        ("dress", "dress_file"),
        ("face", "face_file"),
        ("pose_reference", "pose_reference_file"),
    ]

    existing = AssetLibrary.list_all()
    for asset in existing:
        seen.add((asset["category"], asset["file_id"]))

    for task in Task.list_internal():
        for category, field_name in task_fields:
            file_path = getattr(task, field_name, None)
            if not file_path:
                continue

            resolved_path = Task.resolve_storage_path(file_path)
            if not resolved_path or not os.path.isfile(resolved_path):
                try:
                    resolved_path = AssetLibrary.resolve_file_path(os.path.basename(file_path))
                except ValueError:
                    continue
            if not resolved_path or not os.path.isfile(resolved_path):
                continue

            file_id = os.path.basename(resolved_path)
            key = (category, file_id)
            if key in seen:
                continue

            AssetLibrary.ensure(
                file_id=file_id,
                filename=file_id,
                category=category,
                created_at=task.created_at,
            )
            seen.add(key)
            created += 1

    return created


@router.get("/assets")
async def list_assets(category: Optional[str] = Query(None)):
    _backfill_assets_from_tasks()
    assets = AssetLibrary.list_all(category=category)
    return {"success": True, "assets": assets, "total": len(assets)}


@router.get("/assets/{asset_id}/image")
async def get_asset_image(asset_id: str):
    asset = AssetLibrary.get(asset_id)
    if not asset:
        raise HTTPException(404, detail="素材不存在")

    image_path = AssetLibrary.resolve_file_path(asset["file_id"])
    if not os.path.exists(image_path):
        raise HTTPException(404, detail="素材文件不存在")

    return FileResponse(
        image_path,
        media_type=_image_media_type(image_path),
        filename=asset["filename"],
    )


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str):
    asset = AssetLibrary.delete(asset_id)
    if not asset:
        raise HTTPException(404, detail="素材不存在")
    return {"success": True, "asset": asset}
