"""素材库数据模型"""
import json
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from backend.config import settings


ASSET_CATEGORIES = {"model", "dress", "face", "pose_reference", "uncategorized"}


class AssetLibrary:
    """轻量素材库，用 JSON 记录上传素材。"""

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
    def _read_records(cls) -> list[dict]:
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
    def _write_records(cls, records: list[dict]) -> None:
        path = cls._data_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    @classmethod
    def normalize_category(cls, category: Optional[str]) -> str:
        value = (category or "uncategorized").strip()
        return value if value in ASSET_CATEGORIES else "uncategorized"

    @classmethod
    def create(cls, file_id: str, filename: Optional[str], category: Optional[str]) -> dict:
        record = {
            "asset_id": uuid.uuid4().hex[:12],
            "category": cls.normalize_category(category),
            "file_id": os.path.basename(file_id),
            "filename": filename or os.path.basename(file_id),
            "created_at": datetime.now().isoformat(),
        }
        with cls._FILE_LOCK:
            records = cls._read_records()
            records.append(record)
            cls._write_records(records)
        return cls.to_public_dict(record)

    @classmethod
    def ensure(
        cls,
        file_id: str,
        filename: Optional[str],
        category: Optional[str],
        created_at: Optional[str] = None,
    ) -> dict:
        normalized_category = cls.normalize_category(category)
        normalized_file_id = os.path.basename(file_id or "")
        if not normalized_file_id:
            raise ValueError("素材文件 ID 不能为空")

        with cls._FILE_LOCK:
            records = cls._read_records()
            for item in records:
                if (
                    os.path.basename(item.get("file_id", "")) == normalized_file_id
                    and cls.normalize_category(item.get("category")) == normalized_category
                ):
                    return cls.to_public_dict(item)

            record = {
                "asset_id": uuid.uuid4().hex[:12],
                "category": normalized_category,
                "file_id": normalized_file_id,
                "filename": filename or normalized_file_id,
                "created_at": created_at or datetime.now().isoformat(),
            }
            records.append(record)
            cls._write_records(records)
        return cls.to_public_dict(record)

    @classmethod
    def list_all(cls, category: Optional[str] = None) -> list[dict]:
        normalized_category = cls.normalize_category(category) if category else None
        with cls._FILE_LOCK:
            records = cls._read_records()
        if normalized_category:
            records = [item for item in records if item.get("category") == normalized_category]
        return [
            cls.to_public_dict(item)
            for item in sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)
        ]

    @classmethod
    def get(cls, asset_id: str) -> Optional[dict]:
        with cls._FILE_LOCK:
            records = cls._read_records()
        for item in records:
            if item.get("asset_id") == asset_id:
                return cls.to_public_dict(item)
        return None

    @classmethod
    def delete(cls, asset_id: str) -> Optional[dict]:
        with cls._FILE_LOCK:
            records = cls._read_records()
            deleted = None
            remaining = []
            for item in records:
                if item.get("asset_id") == asset_id:
                    deleted = item
                else:
                    remaining.append(item)
            if deleted is None:
                return None
            cls._write_records(remaining)
        return cls.to_public_dict(deleted)

    @classmethod
    def resolve_file_path(cls, file_id: str) -> str:
        filename = os.path.basename(file_id or "")
        upload_root = os.path.abspath(settings.upload_dir)
        path = os.path.abspath(os.path.join(upload_root, filename))
        if os.path.commonpath([upload_root, path]) != upload_root:
            raise ValueError("非法素材路径")
        return path

    @classmethod
    def to_public_dict(cls, record: dict) -> dict:
        asset_id = record.get("asset_id", "")
        file_id = os.path.basename(record.get("file_id", ""))
        return {
            "asset_id": asset_id,
            "category": cls.normalize_category(record.get("category")),
            "file_id": file_id,
            "filename": record.get("filename") or file_id,
            "created_at": record.get("created_at", ""),
            "image_url": f"/api/assets/{asset_id}/image",
        }
