"""素材库数据模型"""
import json
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from backend.storage import database
from backend.utils.image import resolve_upload_path


ASSET_CATEGORIES = {"model", "dress", "face", "pose_reference", "uncategorized"}


class AssetLibrary:
    """素材库模型，使用 SQLite 持久化并兼容旧 JSON 迁移。"""

    DATA_FILE = ""
    _FILE_LOCK = threading.Lock()

    @classmethod
    def _data_path(cls) -> str:
        if not cls.DATA_FILE:
            cls.DATA_FILE = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "assets.json"
            )
        return cls.DATA_FILE

    @classmethod
    def _default_data_path(cls) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets.json")

    @classmethod
    def _database_path(cls) -> Optional[str]:
        if database.has_configured_database() or not cls.DATA_FILE:
            return None

        data_path = os.path.abspath(cls.DATA_FILE)
        default_path = os.path.abspath(cls._default_data_path())
        if data_path == default_path:
            return None
        return os.path.join(os.path.dirname(data_path), "app.db")

    @classmethod
    def _read_legacy_records(cls) -> list[dict]:
        path = cls._data_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as exc:
            raise RuntimeError("Asset data file is corrupted; repair assets.json first") from exc

        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("asset_id")]

    @classmethod
    def _legacy_migration_key(cls) -> str:
        return f"legacy_assets_migrated:{os.path.abspath(cls._data_path())}"

    @classmethod
    def _migrate_legacy_json_once(cls) -> None:
        path = cls._data_path()
        if not os.path.exists(path):
            return

        db_path = cls._database_path()
        migration_key = cls._legacy_migration_key()
        if database.get_metadata(migration_key, db_path=db_path) == "1":
            return

        for record in cls._read_legacy_records():
            database.upsert_asset_record(record, db_path=db_path)
        database.set_metadata(migration_key, "1", db_path=db_path)

    @classmethod
    def _read_records(
        cls,
        category: Optional[str] = None,
        include_deleted: bool = True,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
        include_shared: bool = False,
    ) -> list[dict]:
        cls._migrate_legacy_json_once()
        return database.list_asset_records(
            category=category,
            include_deleted=include_deleted,
            tenant_id=tenant_id,
            platform_user_id=platform_user_id,
            include_shared=include_shared,
            db_path=cls._database_path(),
        )

    @classmethod
    def normalize_category(cls, category: Optional[str]) -> str:
        value = (category or "uncategorized").strip()
        return value if value in ASSET_CATEGORIES else "uncategorized"

    @classmethod
    def create(
        cls,
        file_id: str,
        filename: Optional[str],
        category: Optional[str],
        *,
        tenant_id: str = "",
        platform_user_id: str = "",
        local_user_id: str = "",
        app_code: str = "",
        visibility: str = "personal",
    ) -> dict:
        record = {
            "asset_id": uuid.uuid4().hex[:12],
            "tenant_id": tenant_id or database.DEFAULT_TENANT_ID,
            "platform_user_id": platform_user_id or database.DEFAULT_PLATFORM_USER_ID,
            "local_user_id": local_user_id or database.DEFAULT_LOCAL_USER_ID,
            "app_code": app_code or database.DEFAULT_APP_CODE,
            "category": cls.normalize_category(category),
            "file_id": os.path.basename(file_id),
            "filename": filename or os.path.basename(file_id),
            "visibility": visibility or "personal",
            "created_at": datetime.now().isoformat(),
        }
        with cls._FILE_LOCK:
            cls._migrate_legacy_json_once()
            database.upsert_asset_record(record, db_path=cls._database_path())
        return cls.to_public_dict(record)

    @classmethod
    def ensure(
        cls,
        file_id: str,
        filename: Optional[str],
        category: Optional[str],
        created_at: Optional[str] = None,
        tenant_id: str = "",
        platform_user_id: str = "",
        local_user_id: str = "",
        app_code: str = "",
        visibility: str = "personal",
    ) -> dict:
        normalized_category = cls.normalize_category(category)
        normalized_file_id = os.path.basename(file_id or "")
        if not normalized_file_id:
            raise ValueError("素材文件 ID 不能为空")

        with cls._FILE_LOCK:
            records = cls._read_records(
                tenant_id=tenant_id or None,
                platform_user_id=platform_user_id or None,
                include_shared=True,
            )
            for item in records:
                if (
                    os.path.basename(item.get("file_id", "")) == normalized_file_id
                    and cls.normalize_category(item.get("category")) == normalized_category
                ):
                    return cls.to_public_dict(item)

            record = {
                "asset_id": uuid.uuid4().hex[:12],
                "tenant_id": tenant_id or database.DEFAULT_TENANT_ID,
                "platform_user_id": platform_user_id or database.DEFAULT_PLATFORM_USER_ID,
                "local_user_id": local_user_id or database.DEFAULT_LOCAL_USER_ID,
                "app_code": app_code or database.DEFAULT_APP_CODE,
                "category": normalized_category,
                "file_id": normalized_file_id,
                "filename": filename or normalized_file_id,
                "visibility": visibility or "personal",
                "created_at": created_at or datetime.now().isoformat(),
            }
            database.upsert_asset_record(record, db_path=cls._database_path())
        return cls.to_public_dict(record)

    @classmethod
    def list_all(
        cls,
        category: Optional[str] = None,
        include_deleted: bool = False,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
        include_shared: bool = False,
    ) -> list[dict]:
        normalized_category = cls.normalize_category(category) if category else None
        with cls._FILE_LOCK:
            records = cls._read_records(
                category=normalized_category,
                include_deleted=include_deleted,
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
                include_shared=include_shared,
            )
        return [
            cls.to_public_dict(item)
            for item in sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)
        ]

    @classmethod
    def get(
        cls,
        asset_id: str,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
        include_shared: bool = False,
    ) -> Optional[dict]:
        with cls._FILE_LOCK:
            cls._migrate_legacy_json_once()
            item = database.get_asset_record(
                asset_id,
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
                include_shared=include_shared,
                db_path=cls._database_path(),
            )
        if item and not item.get("deleted_at"):
            return cls.to_public_dict(item)
        return None

    @classmethod
    def delete(
        cls,
        asset_id: str,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> Optional[dict]:
        with cls._FILE_LOCK:
            cls._migrate_legacy_json_once()
            deleted = database.soft_delete_asset_record(
                asset_id,
                datetime.now().isoformat(),
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
                db_path=cls._database_path(),
            )
            if deleted is None:
                return None
        return cls.to_public_dict(deleted)

    @classmethod
    def resolve_file_path(cls, file_id: str) -> str:
        return resolve_upload_path(os.path.basename(file_id or ""))

    @classmethod
    def to_public_dict(cls, record: dict) -> dict:
        asset_id = record.get("asset_id", "")
        file_id = os.path.basename(record.get("file_id", ""))
        return {
            "asset_id": asset_id,
            "tenant_id": record.get("tenant_id", database.DEFAULT_TENANT_ID),
            "platform_user_id": record.get("platform_user_id", database.DEFAULT_PLATFORM_USER_ID),
            "local_user_id": record.get("local_user_id", database.DEFAULT_LOCAL_USER_ID),
            "category": cls.normalize_category(record.get("category")),
            "file_id": file_id,
            "filename": record.get("filename") or file_id,
            "visibility": record.get("visibility", "personal"),
            "created_at": record.get("created_at", ""),
            "image_url": f"/api/assets/{asset_id}/image",
        }
