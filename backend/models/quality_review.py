"""Quality review storage for generated wedding images."""
import os
from datetime import datetime
from typing import Optional

from backend.storage import database


SCORE_FIELDS = ("face_score", "dress_score", "pose_score", "background_score", "overall_score")


class QualityReview:
    """Database-backed review store, keyed by tenant_id + task_id."""

    DATA_FILE = ""

    @classmethod
    def _data_path(cls) -> str:
        if not cls.DATA_FILE:
            cls.DATA_FILE = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "quality_reviews.json"
            )
        return cls.DATA_FILE

    @classmethod
    def _default_data_path(cls) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "quality_reviews.json")

    @classmethod
    def _database_path(cls) -> Optional[str]:
        if database.has_configured_database() or not cls.DATA_FILE:
            return None

        data_path = os.path.abspath(cls.DATA_FILE)
        default_path = os.path.abspath(cls._default_data_path())
        if data_path == default_path:
            return None
        return os.path.join(os.path.dirname(data_path), "app.db")

    @staticmethod
    def normalize_score(value: Optional[int], field_name: str) -> int:
        if value is None:
            raise ValueError(f"{field_name} is required")
        try:
            score = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer") from exc
        if score < 1 or score > 5:
            raise ValueError(f"{field_name} must be between 1 and 5")
        return score

    @classmethod
    def to_public_dict(cls, record: dict) -> dict:
        return {
            "task_id": record.get("task_id", ""),
            "tenant_id": record.get("tenant_id", database.DEFAULT_TENANT_ID),
            "platform_user_id": record.get("platform_user_id", database.DEFAULT_PLATFORM_USER_ID),
            "local_user_id": record.get("local_user_id", database.DEFAULT_LOCAL_USER_ID),
            "face_score": record.get("face_score"),
            "dress_score": record.get("dress_score"),
            "pose_score": record.get("pose_score"),
            "background_score": record.get("background_score"),
            "overall_score": record.get("overall_score"),
            "pass_result": bool(record.get("pass_result", False)),
            "notes": record.get("notes", ""),
            "reviewer": record.get("reviewer", ""),
            "created_at": record.get("created_at", ""),
            "updated_at": record.get("updated_at", ""),
        }

    @classmethod
    def get(
        cls,
        task_id: str,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> Optional[dict]:
        item = database.get_quality_review_record(
            task_id,
            tenant_id=tenant_id,
            platform_user_id=platform_user_id,
            db_path=cls._database_path(),
        )
        return cls.to_public_dict(item) if item else None

    @classmethod
    def list_all(
        cls,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> list[dict]:
        return [
            cls.to_public_dict(item)
            for item in database.list_quality_review_records(
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
                db_path=cls._database_path(),
            )
        ]

    @classmethod
    def upsert(
        cls,
        task_id: str,
        *,
        face_score: int,
        dress_score: int,
        pose_score: int,
        background_score: int,
        overall_score: Optional[int] = None,
        pass_result: Optional[bool] = None,
        notes: str = "",
        reviewer: str = "",
        tenant_id: str = "",
        platform_user_id: str = "",
        local_user_id: str = "",
        app_code: str = "",
    ) -> dict:
        normalized = {
            "face_score": cls.normalize_score(face_score, "face_score"),
            "dress_score": cls.normalize_score(dress_score, "dress_score"),
            "pose_score": cls.normalize_score(pose_score, "pose_score"),
            "background_score": cls.normalize_score(background_score, "background_score"),
        }
        if overall_score is None:
            normalized["overall_score"] = round(sum(normalized.values()) / len(normalized))
        else:
            normalized["overall_score"] = cls.normalize_score(overall_score, "overall_score")

        if pass_result is None:
            pass_result = (
                normalized["face_score"] >= 4
                and normalized["dress_score"] >= 4
                and normalized["pose_score"] >= 3
                and normalized["background_score"] >= 3
                and normalized["overall_score"] >= 4
            )

        existing = cls.get(task_id, tenant_id=tenant_id or None)
        if (
            existing
            and platform_user_id
            and existing.get("platform_user_id") != platform_user_id
        ):
            raise ValueError("Quality review does not belong to this user")

        now = datetime.now().isoformat()
        record = {
            "task_id": task_id,
            "tenant_id": tenant_id or database.DEFAULT_TENANT_ID,
            "platform_user_id": platform_user_id or database.DEFAULT_PLATFORM_USER_ID,
            "local_user_id": local_user_id or database.DEFAULT_LOCAL_USER_ID,
            "app_code": app_code or database.DEFAULT_APP_CODE,
            **normalized,
            "pass_result": bool(pass_result),
            "notes": notes.strip(),
            "reviewer": reviewer.strip(),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        database.upsert_quality_review_record(record, db_path=cls._database_path())
        return cls.to_public_dict(record)
