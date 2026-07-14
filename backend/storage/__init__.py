"""Storage adapters for user uploads and generated images."""

from backend.storage import database
from backend.storage.object_storage import (
    LocalObjectStorage,
    ObjectStorageConfig,
    OssObjectStorage,
    create_object_storage,
    get_object_storage,
    normalize_storage_key,
)

__all__ = [
    "database",
    "LocalObjectStorage",
    "ObjectStorageConfig",
    "OssObjectStorage",
    "create_object_storage",
    "get_object_storage",
    "normalize_storage_key",
]
