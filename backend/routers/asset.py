"""素材库接口"""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.models.asset import AssetLibrary

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


@router.get("/assets")
async def list_assets(category: Optional[str] = Query(None)):
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
