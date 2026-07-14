"""Retention cleanup for local files, known object keys, and soft-deleted records.

The service is intentionally storage-model neutral: it reads existing Task and
Asset records, computes a dry-run plan, then applies the same plan when cleanup
is explicitly enabled. Main application startup can call this module on a timer.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.config import settings
from backend.models.asset import AssetLibrary
from backend.models.task import Task, TaskStatus
from backend.storage.object_storage import get_object_storage, normalize_storage_key


ACTIVE_TASK_STATUSES = {TaskStatus.PENDING.value, TaskStatus.PROCESSING.value}


@dataclass(frozen=True)
class CleanupConfig:
    enabled: bool
    upload_retention_days: int
    output_retention_days: int
    deleted_record_retention_days: int
    upload_dir: str
    output_dir: str
    object_storage_mode: str

    @classmethod
    def from_settings(cls) -> "CleanupConfig":
        return cls(
            enabled=bool(settings.cleanup_enabled),
            upload_retention_days=max(0, int(settings.upload_retention_days)),
            output_retention_days=max(0, int(settings.output_retention_days)),
            deleted_record_retention_days=max(0, int(settings.deleted_record_retention_days)),
            upload_dir=settings.upload_dir,
            output_dir=settings.output_dir,
            object_storage_mode=(settings.object_storage_mode or "local").strip().lower(),
        )


class CleanupService:
    def __init__(
        self,
        config: Optional[CleanupConfig] = None,
        task_model: type[Task] = Task,
        asset_library: type[AssetLibrary] = AssetLibrary,
        object_storage: Any = None,
    ):
        self.config = config or CleanupConfig.from_settings()
        self.task_model = task_model
        self.asset_library = asset_library
        self.object_storage = object_storage
        self.upload_root = Path(self.config.upload_dir).resolve()
        self.output_root = Path(self.config.output_dir).resolve()

    def run(
        self,
        *,
        dry_run: bool = True,
        force: bool = False,
        now: Optional[datetime] = None,
    ) -> dict:
        now = _normalize_datetime(now or datetime.now())
        can_mutate = bool(not dry_run and (self.config.enabled or force))
        result = self._empty_result(dry_run=dry_run, can_mutate=can_mutate, now=now)

        try:
            tasks = self.task_model.list_internal()
            raw_asset_records = self._read_asset_records()
        except Exception as exc:
            result["errors"].append(f"failed to read cleanup inputs: {exc}")
            self._refresh_summary(result)
            return result

        asset_records_to_keep, purgeable_assets = self._split_purgeable_asset_records(
            raw_asset_records,
            _cutoff(now, self.config.deleted_record_retention_days),
        )
        referenced_uploads = self._referenced_upload_paths(tasks, asset_records_to_keep)
        protected_upload_keys = self._referenced_upload_keys(tasks, asset_records_to_keep)

        self._plan_deleted_asset_records(result, purgeable_assets, can_mutate)
        self._plan_upload_files(
            result,
            referenced_uploads,
            _cutoff(now, self.config.upload_retention_days),
            can_mutate,
        )
        self._plan_output_dirs(
            result,
            tasks,
            _cutoff(now, self.config.output_retention_days),
            can_mutate,
        )
        self._plan_known_object_deletes(
            result,
            tasks,
            purgeable_assets,
            protected_upload_keys,
            _cutoff(now, self.config.output_retention_days),
            can_mutate,
        )

        if can_mutate and purgeable_assets:
            self._purge_asset_records(asset_records_to_keep, purgeable_assets, result)

        if not dry_run and not can_mutate:
            result["skipped_reason"] = "cleanup disabled; set CLEANUP_ENABLED=true or pass force=True"

        self._refresh_summary(result)
        return result

    def _empty_result(self, *, dry_run: bool, can_mutate: bool, now: datetime) -> dict:
        return {
            "dry_run": dry_run,
            "enabled": self.config.enabled,
            "mutating": can_mutate,
            "skipped_reason": "",
            "started_at": now.isoformat(),
            "cutoffs": {
                "uploads": _cutoff(now, self.config.upload_retention_days).isoformat(),
                "outputs": _cutoff(now, self.config.output_retention_days).isoformat(),
                "deleted_records": _cutoff(
                    now,
                    self.config.deleted_record_retention_days,
                ).isoformat(),
            },
            "upload_files": [],
            "output_dirs": [],
            "object_keys": [],
            "asset_records": [],
            "errors": [],
            "summary": {},
        }

    def _read_asset_records(self) -> list[dict]:
        with self.asset_library._FILE_LOCK:
            try:
                records = self.asset_library._read_records(include_deleted=True)
            except TypeError:
                records = self.asset_library._read_records()
            return [dict(item) for item in records]

    def _purge_asset_records(
        self,
        records_to_keep: list[dict],
        purgeable_assets: list[dict],
        result: dict,
    ) -> None:
        try:
            with self.asset_library._FILE_LOCK:
                writer = getattr(self.asset_library, "_write_records", None)
                if writer is not None:
                    writer(records_to_keep)
                    return

                from backend.storage import database

                db_path = (
                    self.asset_library._database_path()
                    if hasattr(self.asset_library, "_database_path")
                    else None
                )
                for record in purgeable_assets:
                    asset_id = record.get("asset_id")
                    if asset_id:
                        database.delete_asset_record(asset_id, db_path=db_path)
        except Exception as exc:
            result["errors"].append(f"failed to purge asset records: {exc}")

    def _split_purgeable_asset_records(
        self,
        records: list[dict],
        cutoff_at: datetime,
    ) -> tuple[list[dict], list[dict]]:
        keep: list[dict] = []
        purge: list[dict] = []
        for record in records:
            deleted_at = _parse_datetime(record.get("deleted_at"))
            if deleted_at and deleted_at <= cutoff_at:
                purge.append(record)
            else:
                keep.append(record)
        return keep, purge

    def _referenced_upload_paths(self, tasks: list[Task], asset_records: list[dict]) -> set[str]:
        refs: set[str] = set()
        for task in tasks:
            for value in _task_input_paths(task):
                safe_path = self._safe_path(value, self.upload_root)
                if safe_path:
                    refs.add(_path_key(safe_path))
                    continue
                key = _object_key(value, default_prefix="uploads")
                keyed_path = _local_path_from_key(key, self.upload_root, "uploads")
                if keyed_path:
                    refs.add(_path_key(keyed_path))

        for record in asset_records:
            file_id = record.get("file_id")
            if not file_id:
                continue
            try:
                path = self.asset_library.resolve_file_path(file_id)
            except Exception:
                continue
            safe_path = self._safe_path(path, self.upload_root)
            if safe_path:
                refs.add(_path_key(safe_path))
        return refs

    def _referenced_upload_keys(self, tasks: list[Task], asset_records: list[dict]) -> set[str]:
        keys: set[str] = set()
        for task in tasks:
            for value in _task_input_paths(task):
                key = _object_key(value, default_prefix="uploads")
                if key and key.startswith("uploads/"):
                    keys.add(key)

        for record in asset_records:
            file_id = record.get("file_id")
            key = _object_key(file_id, default_prefix="uploads") if file_id else None
            if key and key.startswith("uploads/"):
                keys.add(key)
        return keys

    def _plan_deleted_asset_records(
        self,
        result: dict,
        purgeable_assets: list[dict],
        can_mutate: bool,
    ) -> None:
        for record in purgeable_assets:
            result["asset_records"].append(
                {
                    "asset_id": record.get("asset_id", ""),
                    "file_id": record.get("file_id", ""),
                    "deleted_at": record.get("deleted_at", ""),
                    "action": "purge_asset_record",
                    "deleted": can_mutate,
                }
            )

    def _plan_upload_files(
        self,
        result: dict,
        referenced_uploads: set[str],
        cutoff_at: datetime,
        can_mutate: bool,
    ) -> None:
        if not self.upload_root.exists():
            return

        cutoff_ts = cutoff_at.timestamp()
        for path in self._iter_files(self.upload_root):
            safe_path = self._safe_path(path, self.upload_root)
            if not safe_path or _path_key(safe_path) in referenced_uploads:
                continue
            try:
                stat = safe_path.stat()
            except OSError as exc:
                result["errors"].append(f"failed to stat upload file {safe_path}: {exc}")
                continue
            if stat.st_mtime > cutoff_ts:
                continue

            item = {
                "path": str(safe_path),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "action": "delete_upload_file",
                "deleted": False,
            }
            if can_mutate:
                item["deleted"] = self._delete_file(safe_path, self.upload_root, result)
            result["upload_files"].append(item)

    def _plan_output_dirs(
        self,
        result: dict,
        tasks: list[Task],
        cutoff_at: datetime,
        can_mutate: bool,
    ) -> None:
        if not self.output_root.exists():
            return

        active_dirs = self._active_output_dirs(tasks)
        cutoff_ts = cutoff_at.timestamp()
        for path in self.output_root.iterdir():
            safe_path = self._safe_path(path, self.output_root)
            if not safe_path or not safe_path.is_dir() or safe_path.is_symlink():
                continue
            if _path_key(safe_path) in active_dirs:
                continue
            newest_mtime = self._newest_mtime(safe_path)
            if newest_mtime is None or newest_mtime > cutoff_ts:
                continue

            item = {
                "path": str(safe_path),
                "task_id": safe_path.name,
                "modified_at": datetime.fromtimestamp(newest_mtime).isoformat(),
                "action": "delete_output_dir",
                "deleted": False,
            }
            if can_mutate:
                item["deleted"] = self._delete_dir(safe_path, self.output_root, result)
            result["output_dirs"].append(item)

    def _active_output_dirs(self, tasks: list[Task]) -> set[str]:
        active_dirs: set[str] = set()
        for task in tasks:
            status = getattr(task.status, "value", task.status)
            if status not in ACTIVE_TASK_STATUSES:
                continue
            output_dir = self._safe_path(self.output_root / task.task_id, self.output_root)
            if output_dir:
                active_dirs.add(_path_key(output_dir))
            for value in task.output_files.values():
                path = self._safe_path(value, self.output_root)
                if path:
                    active_dirs.add(_path_key(_first_child_under(path, self.output_root)))
        return active_dirs

    def _plan_known_object_deletes(
        self,
        result: dict,
        tasks: list[Task],
        purgeable_assets: list[dict],
        protected_upload_keys: set[str],
        output_cutoff_at: datetime,
        can_mutate: bool,
    ) -> None:
        if self.config.object_storage_mode != "oss" and self.object_storage is None:
            return

        keys: dict[str, str] = {}
        for record in purgeable_assets:
            key = _object_key(record.get("file_id"), default_prefix="uploads")
            if key and key.startswith("uploads/") and key not in protected_upload_keys:
                keys[key] = "delete_expired_asset_object"

        for task in tasks:
            status = getattr(task.status, "value", task.status)
            if status in ACTIVE_TASK_STATUSES:
                continue
            task_time = (
                _parse_datetime(getattr(task, "completed_at", ""))
                or _parse_datetime(getattr(task, "created_at", ""))
            )
            if task_time and task_time > output_cutoff_at:
                continue
            for value in task.output_files.values():
                key = _object_key(value, default_prefix="")
                if key and key.startswith("outputs/"):
                    keys[key] = "delete_expired_output_object"

        if not keys:
            return

        storage = self.object_storage
        if storage is None:
            try:
                storage = get_object_storage()
            except Exception as exc:
                result["errors"].append(f"failed to initialize object storage cleanup: {exc}")
                return

        for key, action in sorted(keys.items()):
            item = {"key": key, "action": action, "deleted": False}
            if can_mutate:
                try:
                    item["deleted"] = bool(storage.delete(key))
                except Exception as exc:
                    item["error"] = str(exc)
                    result["errors"].append(f"failed to delete object {key}: {exc}")
            result["object_keys"].append(item)

    def _iter_files(self, root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            yield path

    def _safe_path(self, value: Any, root: Path) -> Optional[Path]:
        if not value:
            return None
        try:
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            resolved = path.resolve()
            resolved.relative_to(root)
            return resolved
        except (OSError, RuntimeError, ValueError):
            return None

    def _delete_file(self, path: Path, root: Path, result: dict) -> bool:
        safe_path = self._safe_path(path, root)
        if not safe_path or not safe_path.is_file() or safe_path.is_symlink():
            return False
        try:
            safe_path.unlink()
            return True
        except OSError as exc:
            result["errors"].append(f"failed to delete file {safe_path}: {exc}")
            return False

    def _delete_dir(self, path: Path, root: Path, result: dict) -> bool:
        safe_path = self._safe_path(path, root)
        if not safe_path or safe_path == root or not safe_path.is_dir() or safe_path.is_symlink():
            return False
        try:
            shutil.rmtree(safe_path)
            return True
        except OSError as exc:
            result["errors"].append(f"failed to delete directory {safe_path}: {exc}")
            return False

    def _newest_mtime(self, root: Path) -> Optional[float]:
        try:
            newest = root.stat().st_mtime
        except OSError:
            return None
        for path in root.rglob("*"):
            if path.is_symlink():
                continue
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
        return newest

    def _refresh_summary(self, result: dict) -> None:
        result["summary"] = {
            "planned_upload_files": len(result["upload_files"]),
            "deleted_upload_files": sum(1 for item in result["upload_files"] if item.get("deleted")),
            "planned_output_dirs": len(result["output_dirs"]),
            "deleted_output_dirs": sum(1 for item in result["output_dirs"] if item.get("deleted")),
            "planned_object_keys": len(result["object_keys"]),
            "deleted_object_keys": sum(1 for item in result["object_keys"] if item.get("deleted")),
            "planned_asset_records": len(result["asset_records"]),
            "purged_asset_records": sum(1 for item in result["asset_records"] if item.get("deleted")),
            "errors": len(result["errors"]),
        }


def run_cleanup(
    *,
    dry_run: bool = True,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    return CleanupService().run(dry_run=dry_run, force=force, now=now)


def _task_input_paths(task: Task) -> list[Any]:
    return [
        getattr(task, "model_file", None),
        getattr(task, "dress_file", None),
        getattr(task, "face_file", None),
        getattr(task, "pose_reference_file", None),
    ]


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _first_child_under(path: Path, root: Path) -> Path:
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return path
    first = relative.parts[0] if relative.parts else path.name
    return (root / first).resolve()


def _object_key(value: Any, *, default_prefix: str) -> Optional[str]:
    if not value:
        return None
    try:
        storage_path = Task.to_storage_path(str(value))
        return normalize_storage_key(storage_path, default_prefix=default_prefix)
    except Exception:
        return None


def _local_path_from_key(key: Optional[str], root: Path, expected_prefix: str) -> Optional[Path]:
    if not key:
        return None
    parts = key.replace("\\", "/").split("/")
    if len(parts) < 2 or parts[0] != expected_prefix:
        return None
    try:
        path = (root / Path(*parts[1:])).resolve()
        path.relative_to(root)
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def _cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=max(0, days))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalize_datetime(parsed)
