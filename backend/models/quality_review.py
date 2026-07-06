"""Quality review storage for generated wedding images."""
import json
import os
import threading
from datetime import datetime
from typing import Optional


SCORE_FIELDS = ("face_score", "dress_score", "pose_score", "background_score", "overall_score")


class QualityReview:
    """Small JSON-backed review store, keyed by task_id."""

    DATA_FILE = ""
    _FILE_LOCK = threading.Lock()

    @classmethod
    def _data_path(cls) -> str:
        if not cls.DATA_FILE:
            cls.DATA_FILE = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "quality_reviews.json"
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
            raise RuntimeError("Quality review data file is corrupted") from exc

        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("task_id")]

    @classmethod
    def _write_records(cls, records: list[dict]) -> None:
        path = cls._data_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

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
    def get(cls, task_id: str) -> Optional[dict]:
        with cls._FILE_LOCK:
            records = cls._read_records()
        for item in records:
            if item.get("task_id") == task_id:
                return cls.to_public_dict(item)
        return None

    @classmethod
    def list_all(cls) -> list[dict]:
        with cls._FILE_LOCK:
            records = cls._read_records()
        return [
            cls.to_public_dict(item)
            for item in sorted(records, key=lambda item: item.get("updated_at", ""), reverse=True)
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

        now = datetime.now().isoformat()
        with cls._FILE_LOCK:
            records = cls._read_records()
            for index, item in enumerate(records):
                if item.get("task_id") == task_id:
                    record = {
                        **item,
                        **normalized,
                        "pass_result": bool(pass_result),
                        "notes": notes.strip(),
                        "reviewer": reviewer.strip(),
                        "updated_at": now,
                    }
                    records[index] = record
                    cls._write_records(records)
                    return cls.to_public_dict(record)

            record = {
                "task_id": task_id,
                **normalized,
                "pass_result": bool(pass_result),
                "notes": notes.strip(),
                "reviewer": reviewer.strip(),
                "created_at": now,
                "updated_at": now,
            }
            records.append(record)
            cls._write_records(records)
            return cls.to_public_dict(record)
