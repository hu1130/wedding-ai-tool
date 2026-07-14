"""Object storage abstraction for local files and Alibaba Cloud OSS.

The default adapter stores objects under the project root so existing
``uploads/`` and ``outputs/`` paths keep working during local development.
OSS support is lazy-loaded; importing this module never requires ``oss2``.
"""

from __future__ import annotations

import io
import os
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from backend.config import PROJECT_ROOT, settings


DEFAULT_PRESIGNED_EXPIRES_SECONDS = 3600


class ObjectStorage(Protocol):
    def save_bytes(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        """Save bytes and return the normalized object key."""

    def get_bytes(self, key: str) -> bytes:
        """Read all bytes for a key."""

    def open(self, key: str) -> BinaryIO:
        """Open a key for binary reading."""

    def exists(self, key: str) -> bool:
        """Return whether a key exists."""

    def delete(self, key: str) -> bool:
        """Delete a key. Return True when an object was removed."""

    def public_url(self, key: str) -> str:
        """Return a stable public URL or local simulation URL."""

    def presigned_url(self, key: str, expires_seconds: int = DEFAULT_PRESIGNED_EXPIRES_SECONDS) -> str:
        """Return a temporary read URL or local simulation URL."""


@dataclass(frozen=True)
class ObjectStorageConfig:
    mode: str = "local"
    local_root: str = str(PROJECT_ROOT)
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_public_base_url: str = ""

    @classmethod
    def from_settings(cls) -> "ObjectStorageConfig":
        return cls(
            mode=settings.object_storage_mode,
            local_root=settings.object_storage_local_root,
            oss_endpoint=settings.oss_endpoint,
            oss_bucket=settings.oss_bucket,
            oss_access_key_id=settings.oss_access_key_id,
            oss_access_key_secret=settings.oss_access_key_secret,
            oss_public_base_url=settings.oss_public_base_url,
        )


def normalize_storage_key(key: str, default_prefix: str = "uploads") -> str:
    """Normalize an object key and reject absolute or traversal paths.

    Bare filenames map to ``uploads/<filename>`` to keep compatibility with
    the existing upload asset IDs. Explicit keys such as ``outputs/a/final.jpg``
    are preserved.
    """
    value = str(key or "").strip().replace("\\", "/")
    if not value:
        raise ValueError("storage key cannot be empty")
    if ":" in value.split("/", 1)[0]:
        raise ValueError("storage key must be relative")
    if value.startswith("/"):
        raise ValueError("storage key must be relative")

    parts = [part for part in value.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("storage key cannot contain traversal segments")

    if len(parts) == 1 and default_prefix:
        parts.insert(0, default_prefix.strip("/"))
    return posixpath.join(*parts)


def _content_type_headers(content_type: str) -> dict[str, str]:
    if not content_type:
        return {}
    return {"Content-Type": content_type}


class LocalObjectStorage:
    def __init__(self, root: str | os.PathLike[str] = PROJECT_ROOT, public_base_url: str = "/storage"):
        self.root = Path(root).resolve()
        self.public_base_url = public_base_url.rstrip("/") or "/storage"

    def _path_for_key(self, key: str) -> tuple[str, Path]:
        normalized = normalize_storage_key(key)
        path = (self.root / Path(*normalized.split("/"))).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("storage key escapes local root") from exc
        return normalized, path

    def save_bytes(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        normalized, path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        with open(tmp_path, "wb") as f:
            f.write(content)
        os.replace(tmp_path, path)
        return normalized

    def get_bytes(self, key: str) -> bytes:
        with self.open(key) as f:
            return f.read()

    def open(self, key: str) -> BinaryIO:
        _, path = self._path_for_key(key)
        return open(path, "rb")

    def exists(self, key: str) -> bool:
        _, path = self._path_for_key(key)
        return path.is_file()

    def delete(self, key: str) -> bool:
        _, path = self._path_for_key(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def public_url(self, key: str) -> str:
        normalized = normalize_storage_key(key)
        return f"{self.public_base_url}/{quote(normalized)}"

    def presigned_url(self, key: str, expires_seconds: int = DEFAULT_PRESIGNED_EXPIRES_SECONDS) -> str:
        return self.public_url(key)


class OssObjectStorage:
    def __init__(self, config: ObjectStorageConfig):
        self.config = _validate_oss_config(config)
        self._bucket = None

    @property
    def bucket(self):
        if self._bucket is None:
            try:
                import oss2
            except ImportError as exc:
                raise RuntimeError("oss2 is required when OBJECT_STORAGE_MODE=oss") from exc

            auth = oss2.Auth(
                self.config.oss_access_key_id,
                self.config.oss_access_key_secret,
            )
            self._bucket = oss2.Bucket(
                auth,
                self.config.oss_endpoint,
                self.config.oss_bucket,
            )
        return self._bucket

    def save_bytes(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        normalized = normalize_storage_key(key)
        self.bucket.put_object(normalized, content, headers=_content_type_headers(content_type))
        return normalized

    def get_bytes(self, key: str) -> bytes:
        normalized = normalize_storage_key(key)
        return self.bucket.get_object(normalized).read()

    def open(self, key: str) -> BinaryIO:
        return io.BytesIO(self.get_bytes(key))

    def exists(self, key: str) -> bool:
        normalized = normalize_storage_key(key)
        return bool(self.bucket.object_exists(normalized))

    def delete(self, key: str) -> bool:
        normalized = normalize_storage_key(key)
        existed = self.exists(normalized)
        self.bucket.delete_object(normalized)
        return existed

    def public_url(self, key: str) -> str:
        normalized = normalize_storage_key(key)
        if self.config.oss_public_base_url:
            return f"{self.config.oss_public_base_url.rstrip('/')}/{quote(normalized)}"

        endpoint = self.config.oss_endpoint.strip()
        split = urlsplit(endpoint if "://" in endpoint else f"https://{endpoint}")
        netloc = split.netloc or split.path
        scheme = split.scheme or "https"
        bucket_host = f"{self.config.oss_bucket}.{netloc.lstrip('/')}"
        return urlunsplit((scheme, bucket_host, quote(normalized), "", ""))

    def presigned_url(self, key: str, expires_seconds: int = DEFAULT_PRESIGNED_EXPIRES_SECONDS) -> str:
        normalized = normalize_storage_key(key)
        return self.bucket.sign_url("GET", normalized, expires_seconds)


def _validate_oss_config(config: ObjectStorageConfig) -> ObjectStorageConfig:
    missing = [
        name
        for name, value in {
            "OSS_ENDPOINT": config.oss_endpoint,
            "OSS_BUCKET": config.oss_bucket,
            "OSS_ACCESS_KEY_ID": config.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": config.oss_access_key_secret,
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise ValueError(f"missing OSS configuration: {', '.join(missing)}")
    return config


def create_object_storage(config: ObjectStorageConfig | None = None) -> ObjectStorage:
    config = config or ObjectStorageConfig.from_settings()
    mode = (config.mode or "local").strip().lower()
    if mode == "local":
        return LocalObjectStorage(root=config.local_root)
    if mode == "oss":
        return OssObjectStorage(config)
    raise ValueError("OBJECT_STORAGE_MODE must be 'local' or 'oss'")


_storage_instance: ObjectStorage | None = None


def get_object_storage() -> ObjectStorage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = create_object_storage()
    return _storage_instance
