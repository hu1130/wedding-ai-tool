"""Media response helpers for local files and object storage."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Iterable, Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from backend.config import PROJECT_ROOT
from backend.storage.object_storage import get_object_storage, normalize_storage_key


def image_media_type_from_header(header: bytes) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def image_media_type_from_path(path: str) -> str:
    with open(path, "rb") as f:
        return image_media_type_from_header(f.read(12))


def _content_disposition(filename: str) -> str:
    safe_name = os.path.basename(filename or "image")
    return f'inline; filename="{safe_name}"'


def _storage_key_candidates(value: Optional[str], default_prefix: str) -> Iterable[str]:
    if not value:
        return []

    raw = str(value).strip()
    candidates: list[str] = []

    try:
        path = Path(raw)
        if path.is_absolute():
            try:
                relative = path.resolve().relative_to(PROJECT_ROOT.resolve())
                candidates.append(relative.as_posix())
            except ValueError:
                pass
        else:
            candidates.append(normalize_storage_key(raw, default_prefix=default_prefix))
            if default_prefix and "/" not in raw.replace("\\", "/"):
                candidates.append(normalize_storage_key(raw, default_prefix=default_prefix))
    except (OSError, RuntimeError, ValueError):
        pass

    seen: set[str] = set()
    return [key for key in candidates if not (key in seen or seen.add(key))]


def image_response(
    *,
    value: Optional[str],
    filename: str,
    default_prefix: str,
    local_path: Optional[str] = None,
    not_found_detail: str = "图片不存在",
):
    """Return an image response from local cache or configured object storage."""

    if local_path and os.path.isfile(local_path):
        media_type = image_media_type_from_path(local_path)
        return FileResponse(
            local_path,
            media_type=media_type,
            filename=filename,
        )

    storage = get_object_storage()
    for key in _storage_key_candidates(value, default_prefix=default_prefix):
        try:
            if not storage.exists(key):
                continue
            content = storage.get_bytes(key)
        except (FileNotFoundError, ValueError):
            continue
        media_type = image_media_type_from_header(content[:12])
        return StreamingResponse(
            io.BytesIO(content),
            media_type=media_type,
            headers={"Content-Disposition": _content_disposition(filename)},
        )

    raise HTTPException(404, detail=not_found_detail)
