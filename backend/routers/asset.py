"""素材库接口"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.models.asset import AssetLibrary
from backend.models.task import Task
from backend.security.auth import AuthUser, current_user_from_request
from backend.utils.media import image_response

router = APIRouter(prefix="/api", tags=["素材库"])


def _backfill_assets_from_tasks(user: AuthUser) -> int:
    """Register historical task inputs that were uploaded before the asset library existed."""
    created = 0
    seen: set[tuple[str, str]] = set()
    task_fields = [
        ("model", "model_file"),
        ("dress", "dress_file"),
        ("face", "face_file"),
        ("pose_reference", "pose_reference_file"),
    ]

    existing = AssetLibrary.list_all(
        include_deleted=True,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
        include_shared=True,
    )
    for asset in existing:
        seen.add((asset["category"], asset["file_id"]))

    for task in Task.list_internal(
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    ):
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
                tenant_id=task.tenant_id,
                platform_user_id=task.platform_user_id,
                local_user_id=task.local_user_id,
                app_code=task.app_code,
            )
            seen.add(key)
            created += 1

    return created


@router.get("/assets")
async def list_assets(
    category: Optional[str] = Query(None),
    user: AuthUser = Depends(current_user_from_request),
):
    _backfill_assets_from_tasks(user)
    assets = AssetLibrary.list_all(
        category=category,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
        include_shared=True,
    )
    return {"success": True, "assets": assets, "total": len(assets)}


@router.get("/assets/{asset_id}/image")
async def get_asset_image(
    asset_id: str,
    user: AuthUser = Depends(current_user_from_request),
):
    asset = AssetLibrary.get(
        asset_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
        include_shared=True,
    )
    if not asset:
        raise HTTPException(404, detail="素材不存在")

    try:
        image_path = AssetLibrary.resolve_file_path(asset["file_id"])
    except (FileNotFoundError, ValueError):
        image_path = None
    return image_response(
        value=asset["file_id"],
        local_path=image_path,
        default_prefix="uploads",
        filename=asset["filename"],
        not_found_detail="素材文件不存在",
    )


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: str,
    user: AuthUser = Depends(current_user_from_request),
):
    asset = AssetLibrary.delete(
        asset_id,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
    )
    if not asset:
        raise HTTPException(404, detail="素材不存在")
    return {"success": True, "asset": asset}
