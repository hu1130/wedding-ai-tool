"""任务数据模型"""
import json
import os
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from backend.config import settings

from backend.storage import database
from backend.storage.object_storage import get_object_storage


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


INTERRUPTED_TASK_MESSAGE = "服务重启后发现任务仍处于生成中，已自动标记为失败，请重跑一版。"
STEP_LABELS = {
    "dress": "AI试衣",
    "face": "人脸处理",
    "scene": "场景生成",
    "upscale": "整理输出",
}


def _non_negative_int(value, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class Task:
    """任务模型，使用 SQLite 持久化并兼容旧 JSON 迁移。"""

    DATA_FILE = ""
    _FILE_LOCK = threading.Lock()
    _PATH_ROOT_NAMES = ("uploads", "outputs")

    def __init__(
        self,
        task_id: Optional[str] = None,
        name: str = "",
        model_file: str = "",
        dress_file: str = "",
        face_file: Optional[str] = None,
        pose_reference_file: Optional[str] = None,
        clothing_type: str = "wedding_gown",
        scene: str = "海边",
        scene_prompt: str = "",
        resolution: str = "1k",
        face_swap: bool = False,
        pose: str = "保持原姿势",
        pose_mode: str = "stable",
        preserve_face: bool = True,
        generation_mode: str = "stable",
        parent_task_id: Optional[str] = None,
        rerun_index: int = 1,
        is_deliverable: bool = False,
        deliverable_at: str = "",
        retry_count: int = 0,
        max_retries: Optional[int] = None,
        last_error_at: str = "",
        last_error_stage: str = "",
        next_retry_at: str = "",
        tenant_id: str = "",
        platform_user_id: str = "",
        local_user_id: str = "",
        app_code: str = "",
    ):
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.name = name or f"任务_{self.task_id}"
        self.status = TaskStatus.PENDING
        self.progress = 0.0
        self.model_file = model_file
        self.dress_file = dress_file
        self.face_file = face_file
        self.pose_reference_file = pose_reference_file
        self.clothing_type = clothing_type
        self.scene = scene
        self.scene_prompt = scene_prompt
        self.resolution = resolution
        self.face_swap = face_swap
        self.pose = pose
        self.pose_mode = pose_mode
        self.preserve_face = preserve_face
        self.generation_mode = generation_mode
        self.parent_task_id = parent_task_id
        self.rerun_index = rerun_index
        self.is_deliverable = is_deliverable
        self.deliverable_at = deliverable_at
        self.retry_count = _non_negative_int(retry_count, 0)
        self.max_retries = (
            settings.max_task_retries
            if max_retries is None
            else _non_negative_int(max_retries, settings.max_task_retries)
        )
        self.last_error_at = last_error_at
        self.last_error_stage = last_error_stage
        self.next_retry_at = next_retry_at
        self.tenant_id = tenant_id or database.DEFAULT_TENANT_ID
        self.platform_user_id = platform_user_id or database.DEFAULT_PLATFORM_USER_ID
        self.local_user_id = local_user_id or database.DEFAULT_LOCAL_USER_ID
        self.app_code = app_code or settings.app_code
        self.output_files = {}
        self.error_message = ""
        self.created_at = datetime.now().isoformat()
        self.completed_at = ""
        self.steps = {
            "dress": StepStatus.PENDING,
            "face": StepStatus.PENDING,
            "scene": StepStatus.PENDING,
            "upscale": StepStatus.PENDING,
        }

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "platform_user_id": self.platform_user_id,
            "local_user_id": self.local_user_id,
            "app_code": self.app_code,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "model_file": self.to_storage_path(self.model_file),
            "dress_file": self.to_storage_path(self.dress_file),
            "face_file": self.to_storage_path(self.face_file),
            "pose_reference_file": self.to_storage_path(self.pose_reference_file),
            "clothing_type": self.clothing_type,
            "scene": self.scene,
            "scene_prompt": self.scene_prompt,
            "resolution": self.resolution,
            "face_swap": self.face_swap,
            "pose": self.pose,
            "pose_mode": self.pose_mode,
            "preserve_face": self.preserve_face,
            "generation_mode": self.generation_mode,
            "parent_task_id": self.parent_task_id,
            "rerun_index": self.rerun_index,
            "is_deliverable": self.is_deliverable,
            "deliverable_at": self.deliverable_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_error_at": self.last_error_at,
            "last_error_stage": self.last_error_stage,
            "next_retry_at": self.next_retry_at,
            "output_files": {
                key: self.to_storage_path(path)
                for key, path in self.output_files.items()
            },
            "error_message": self.error_message,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "steps": {key: value.value for key, value in self.steps.items()},
        }

    def to_public_dict(self) -> dict:
        data = self.to_dict()
        current_step, current_step_label = self.current_step()
        data["current_step"] = current_step
        data["current_step_label"] = current_step_label
        for key in ["model_file", "dress_file", "face_file", "pose_reference_file"]:
            if data.get(key):
                data[key] = os.path.basename(data[key])
        data["output_files"] = {
            key: True
            for key, path in self.output_files.items()
            if path and self.output_exists(path)
        }
        return data

    @classmethod
    def output_exists(cls, path: Optional[str]) -> bool:
        if not path:
            return False
        resolved = cls.resolve_storage_path(path)
        if resolved and os.path.exists(resolved):
            return True
        try:
            storage_key = cls.to_storage_path(path)
            return bool(storage_key and get_object_storage().exists(storage_key))
        except Exception:
            return False

    def current_step(self) -> tuple[str, str]:
        ordered_steps = ("dress", "face", "scene", "upscale")

        if self.status == TaskStatus.PROCESSING:
            for step_name in ordered_steps:
                if self.steps.get(step_name) == StepStatus.PROCESSING:
                    return step_name, STEP_LABELS.get(step_name, step_name)
            return "processing", "生成中"

        if self.status == TaskStatus.PENDING:
            return "queued", "等待队列"

        if self.status == TaskStatus.COMPLETED:
            return "completed", "已完成"

        if self.status == TaskStatus.FAILED:
            for step_name in ordered_steps:
                if self.steps.get(step_name) == StepStatus.FAILED:
                    return step_name, f"{STEP_LABELS.get(step_name, step_name)}失败"
            return "failed", "生成失败"

        return self.status.value, self.status.value

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        if not isinstance(data, dict) or not data.get("task_id"):
            raise ValueError("Invalid task record: missing task_id")

        try:
            rerun_index = int(data.get("rerun_index", 1) or 1)
        except (TypeError, ValueError):
            rerun_index = 1

        task = cls(
            task_id=data.get("task_id"),
            name=data.get("name", ""),
            model_file=cls.resolve_storage_path(data.get("model_file", "")),
            dress_file=cls.resolve_storage_path(data.get("dress_file", "")),
            face_file=cls.resolve_storage_path(data.get("face_file")),
            pose_reference_file=cls.resolve_storage_path(data.get("pose_reference_file")),
            clothing_type=data.get("clothing_type", "wedding_gown"),
            scene=data.get("scene", "海边"),
            scene_prompt=data.get("scene_prompt", ""),
            resolution=data.get("resolution", "1k"),
            face_swap=data.get("face_swap", False),
            pose=data.get("pose", "保持原姿势"),
            pose_mode=data.get("pose_mode", "stable"),
            preserve_face=data.get("preserve_face", True),
            generation_mode=data.get("generation_mode", "stable"),
            parent_task_id=data.get("parent_task_id"),
            rerun_index=rerun_index,
            is_deliverable=bool(data.get("is_deliverable", False)),
            deliverable_at=data.get("deliverable_at", ""),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", settings.max_task_retries),
            last_error_at=data.get("last_error_at", ""),
            last_error_stage=data.get("last_error_stage", ""),
            next_retry_at=data.get("next_retry_at", ""),
            tenant_id=data.get("tenant_id", database.DEFAULT_TENANT_ID),
            platform_user_id=data.get("platform_user_id", database.DEFAULT_PLATFORM_USER_ID),
            local_user_id=data.get("local_user_id", database.DEFAULT_LOCAL_USER_ID),
            app_code=data.get("app_code", settings.app_code),
        )

        try:
            task.status = TaskStatus(data.get("status", "pending"))
        except ValueError:
            task.status = TaskStatus.PENDING
        task.progress = data.get("progress", 0)
        task.output_files = {
            key: cls.resolve_storage_path(path)
            for key, path in data.get("output_files", {}).items()
            if path
        }
        task.error_message = data.get("error_message", "")
        task.created_at = data.get("created_at", datetime.now().isoformat())
        task.completed_at = data.get("completed_at", "")

        raw_steps = data.get("steps", {})
        if isinstance(raw_steps, dict):
            for key, value in raw_steps.items():
                if key not in task.steps:
                    continue
                try:
                    task.steps[key] = StepStatus(value)
                except ValueError:
                    task.steps[key] = StepStatus.PENDING
        return task

    @classmethod
    def _data_path(cls) -> str:
        if not cls.DATA_FILE:
            cls.DATA_FILE = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "tasks.json"
            )
        return cls.DATA_FILE

    @classmethod
    def _default_data_path(cls) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "tasks.json")

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
    def project_root(cls) -> str:
        return os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    @classmethod
    def _relative_from_known_root(cls, path: str) -> Optional[str]:
        if not path:
            return None
        parts = os.path.normpath(path).split(os.sep)
        lowered = [part.lower() for part in parts]
        for root_name in cls._PATH_ROOT_NAMES:
            if root_name in lowered:
                index = lowered.index(root_name)
                return "/".join(parts[index:])
        return None

    @classmethod
    def to_storage_path(cls, path: Optional[str]) -> Optional[str]:
        if not path:
            return path

        normalized = os.path.normpath(path)
        if not os.path.isabs(normalized):
            return normalized.replace(os.sep, "/")

        project_root = cls.project_root()
        try:
            relative = os.path.relpath(normalized, project_root)
            if not relative.startswith("..") and not os.path.isabs(relative):
                return relative.replace(os.sep, "/")
        except ValueError:
            pass

        known_relative = cls._relative_from_known_root(normalized)
        if known_relative:
            return known_relative.replace(os.sep, "/")

        return normalized

    @classmethod
    def resolve_storage_path(cls, path: Optional[str]) -> Optional[str]:
        if not path:
            return path

        normalized = os.path.normpath(path)
        if os.path.isabs(normalized):
            if os.path.exists(normalized):
                return normalized
            known_relative = cls._relative_from_known_root(normalized)
            if known_relative:
                return os.path.abspath(os.path.join(cls.project_root(), known_relative))
            return normalized

        project_root = cls.project_root()
        candidate = os.path.join(project_root, normalized)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

        if os.sep not in normalized and "/" not in normalized:
            upload_candidate = os.path.join(project_root, "uploads", normalized)
            if os.path.exists(upload_candidate):
                return os.path.abspath(upload_candidate)

        return os.path.abspath(candidate)

    @classmethod
    def _normalize_task_records(cls, raw_tasks) -> list[dict]:
        if not isinstance(raw_tasks, list):
            return []

        normalized: list[dict] = []
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            if item.get("task_id"):
                normalized.append(item)
                continue
            wrapped = item.get("value")
            if isinstance(wrapped, list):
                normalized.extend(
                    task for task in wrapped
                    if isinstance(task, dict) and task.get("task_id")
                )
        return normalized

    @classmethod
    def _read_legacy_task_records(cls) -> list[dict]:
        path = cls._data_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return cls._normalize_task_records(json.load(f))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as exc:
            raise RuntimeError("Task data file is corrupted; repair tasks.json first") from exc

    @classmethod
    def _legacy_migration_key(cls) -> str:
        return f"legacy_tasks_migrated:{os.path.abspath(cls._data_path())}"

    @classmethod
    def _migrate_legacy_json_once(cls) -> None:
        path = cls._data_path()
        if not os.path.exists(path):
            return

        db_path = cls._database_path()
        migration_key = cls._legacy_migration_key()
        if database.get_metadata(migration_key, db_path=db_path) == "1":
            return

        for record in cls._read_legacy_task_records():
            database.upsert_task_record(record, db_path=db_path)
        database.set_metadata(migration_key, "1", db_path=db_path)

    @classmethod
    def _read_task_records(
        cls,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> list[dict]:
        cls._migrate_legacy_json_once()
        return database.list_task_records(
            tenant_id=tenant_id,
            platform_user_id=platform_user_id,
            db_path=cls._database_path(),
        )

    def save(self):
        with self._FILE_LOCK:
            self._migrate_legacy_json_once()
            database.upsert_task_record(self.to_dict(), db_path=self._database_path())

    @classmethod
    def get(
        cls,
        task_id: str,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> Optional["Task"]:
        with cls._FILE_LOCK:
            tasks = cls._read_task_records(
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
            )
        for item in tasks:
            if item.get("task_id") == task_id:
                return cls.from_dict(item)
        return None

    @classmethod
    def list_all(
        cls,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> list[dict]:
        with cls._FILE_LOCK:
            tasks = cls._read_task_records(
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
            )
        public_tasks = [cls.from_dict(item).to_public_dict() for item in tasks]
        return sorted(public_tasks, key=lambda item: item.get("created_at", ""), reverse=True)

    @classmethod
    def list_internal(
        cls,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> list["Task"]:
        with cls._FILE_LOCK:
            tasks = cls._read_task_records(
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
            )
        return [cls.from_dict(item) for item in tasks]

    @classmethod
    def delete(
        cls,
        task_id: str,
        tenant_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> Optional["Task"]:
        with cls._FILE_LOCK:
            cls._migrate_legacy_json_once()
            deleted = database.delete_task_record(
                task_id,
                tenant_id=tenant_id,
                platform_user_id=platform_user_id,
                db_path=cls._database_path(),
            )
            if deleted is None:
                return None

        return cls.from_dict(deleted)

    @classmethod
    def recover_interrupted_processing_tasks(cls) -> int:
        """Mark tasks left processing by a previous server run as failed."""
        recovered = 0
        for task in cls.list_internal():
            if task.status != TaskStatus.PROCESSING:
                continue

            task.status = TaskStatus.FAILED
            task.error_message = task.error_message or INTERRUPTED_TASK_MESSAGE
            for step_name, step_status in task.steps.items():
                if step_status == StepStatus.PROCESSING:
                    task.steps[step_name] = StepStatus.FAILED
            task.save()
            recovered += 1
        return recovered
