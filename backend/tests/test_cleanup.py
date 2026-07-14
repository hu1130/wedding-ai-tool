import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend.config import settings
from backend.models.asset import AssetLibrary
from backend.models.task import Task, TaskStatus
from backend.services.cleanup import CleanupConfig, CleanupService


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


class FakeObjectStorage:
    def __init__(self):
        self.deleted_keys: list[str] = []

    def delete(self, key: str) -> bool:
        self.deleted_keys.append(key)
        return True


class CleanupServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.upload_dir = self.root / "uploads"
        self.output_dir = self.root / "outputs"
        self.upload_dir.mkdir()
        self.output_dir.mkdir()

        self.old_upload_dir = settings.upload_dir
        self.old_output_dir = settings.output_dir
        self.old_cleanup_enabled = settings.cleanup_enabled
        self.old_upload_retention_days = settings.upload_retention_days
        self.old_output_retention_days = settings.output_retention_days
        self.old_deleted_record_retention_days = settings.deleted_record_retention_days
        self.old_object_storage_mode = settings.object_storage_mode
        self.old_task_data_file = Task.DATA_FILE
        self.old_asset_data_file = AssetLibrary.DATA_FILE

        settings.upload_dir = str(self.upload_dir)
        settings.output_dir = str(self.output_dir)
        settings.cleanup_enabled = True
        settings.upload_retention_days = 7
        settings.output_retention_days = 7
        settings.deleted_record_retention_days = 7
        settings.object_storage_mode = "local"
        Task.DATA_FILE = str(self.root / "tasks.json")
        AssetLibrary.DATA_FILE = str(self.root / "assets.json")

    def tearDown(self):
        settings.upload_dir = self.old_upload_dir
        settings.output_dir = self.old_output_dir
        settings.cleanup_enabled = self.old_cleanup_enabled
        settings.upload_retention_days = self.old_upload_retention_days
        settings.output_retention_days = self.old_output_retention_days
        settings.deleted_record_retention_days = self.old_deleted_record_retention_days
        settings.object_storage_mode = self.old_object_storage_mode
        Task.DATA_FILE = self.old_task_data_file
        AssetLibrary.DATA_FILE = self.old_asset_data_file
        self.temp_dir.cleanup()

    def test_dry_run_then_real_cleanup_keeps_referenced_files_and_active_outputs(self):
        now = datetime(2026, 7, 7, 12, 0, 0)
        old = now - timedelta(days=30)
        recent = now - timedelta(days=1)

        active_upload = self._upload_file("active_model.png", old)
        kept_asset_file = self._upload_file("kept_asset.png", old)
        recent_deleted_file = self._upload_file("recent_deleted.png", old)
        old_deleted_file = self._upload_file("old_deleted.png", old)
        orphan_old = self._upload_file("orphan_old.png", old)
        orphan_recent = self._upload_file("orphan_recent.png", recent)

        active_output = self._output_dir("active_task", old)
        old_completed_output = self._output_dir("completed_task", old)
        old_orphan_output = self._output_dir("orphan_task", old)
        recent_orphan_output = self._output_dir("recent_task", recent)

        active_task = Task(task_id="active_task", model_file=str(active_upload))
        active_task.status = TaskStatus.PROCESSING
        active_task.output_files["final"] = str(active_output / "final.png")
        active_task.save()

        completed_task = Task(task_id="completed_task")
        completed_task.status = TaskStatus.COMPLETED
        completed_task.created_at = old.isoformat()
        completed_task.completed_at = old.isoformat()
        completed_task.output_files["final"] = str(old_completed_output / "final.png")
        completed_task.save()

        self._write_asset_records(
            [
                self._asset("kept_asset", "kept_asset.png", created_at=old),
                self._asset(
                    "recent_deleted",
                    "recent_deleted.png",
                    created_at=old,
                    deleted_at=recent,
                ),
                self._asset(
                    "old_deleted",
                    "old_deleted.png",
                    created_at=old,
                    deleted_at=old,
                ),
            ]
        )

        service = CleanupService()
        dry_result = service.run(dry_run=True, now=now)

        self.assertEqual(0, dry_result["summary"]["errors"])
        self.assertEqual(2, dry_result["summary"]["planned_upload_files"])
        self.assertEqual(0, dry_result["summary"]["deleted_upload_files"])
        self.assertEqual(2, dry_result["summary"]["planned_output_dirs"])
        self.assertEqual(1, dry_result["summary"]["planned_asset_records"])
        self.assertTrue(old_deleted_file.exists())
        self.assertTrue(orphan_old.exists())
        self.assertTrue(old_completed_output.exists())

        real_result = service.run(dry_run=False, now=now)

        self.assertEqual(0, real_result["summary"]["errors"])
        self.assertEqual(2, real_result["summary"]["deleted_upload_files"])
        self.assertEqual(2, real_result["summary"]["deleted_output_dirs"])
        self.assertEqual(1, real_result["summary"]["purged_asset_records"])

        self.assertTrue(active_upload.exists())
        self.assertTrue(kept_asset_file.exists())
        self.assertTrue(recent_deleted_file.exists())
        self.assertFalse(old_deleted_file.exists())
        self.assertFalse(orphan_old.exists())
        self.assertTrue(orphan_recent.exists())
        self.assertTrue(active_output.exists())
        self.assertFalse(old_completed_output.exists())
        self.assertFalse(old_orphan_output.exists())
        self.assertTrue(recent_orphan_output.exists())

        remaining_asset_ids = {record["asset_id"] for record in self._read_asset_records()}
        self.assertEqual({"kept_asset", "recent_deleted"}, remaining_asset_ids)

    def test_real_cleanup_is_blocked_when_disabled_unless_forced(self):
        now = datetime(2026, 7, 7, 12, 0, 0)
        old_upload = self._upload_file("disabled_old.png", now - timedelta(days=30))
        settings.cleanup_enabled = False

        disabled_result = CleanupService().run(dry_run=False, now=now)

        self.assertTrue(old_upload.exists())
        self.assertIn("cleanup disabled", disabled_result["skipped_reason"])
        self.assertEqual(0, disabled_result["summary"]["deleted_upload_files"])

        forced_result = CleanupService().run(dry_run=False, force=True, now=now)

        self.assertFalse(old_upload.exists())
        self.assertEqual(1, forced_result["summary"]["deleted_upload_files"])

    def test_delete_helpers_reject_paths_outside_safe_roots(self):
        outside_file = self.root / "outside.png"
        outside_file.write_bytes(PNG_BYTES)
        outside_dir = self.root / "outside_dir"
        outside_dir.mkdir()
        (outside_dir / "final.png").write_bytes(PNG_BYTES)

        service = CleanupService()
        result = {"errors": []}

        self.assertFalse(service._delete_file(outside_file, service.upload_root, result))
        self.assertFalse(service._delete_dir(outside_dir, service.output_root, result))
        self.assertTrue(outside_file.exists())
        self.assertTrue(outside_dir.exists())

    def test_oss_cleanup_uses_known_record_keys_without_network(self):
        now = datetime(2026, 7, 7, 12, 0, 0)
        old = now - timedelta(days=30)
        fake_storage = FakeObjectStorage()
        settings.object_storage_mode = "oss"

        task = Task(task_id="old_oss_task")
        task.status = TaskStatus.COMPLETED
        task.created_at = old.isoformat()
        task.completed_at = old.isoformat()
        task.output_files["final"] = "outputs/old_oss_task/final.jpg"
        task.save()
        self._write_asset_records(
            [
                self._asset(
                    "old_oss_asset",
                    "old_oss_asset.png",
                    created_at=old,
                    deleted_at=old,
                )
            ]
        )

        config = CleanupConfig.from_settings()
        service = CleanupService(config=config, object_storage=fake_storage)
        dry_result = service.run(dry_run=True, now=now)

        self.assertEqual(
            {"outputs/old_oss_task/final.jpg", "uploads/old_oss_asset.png"},
            {item["key"] for item in dry_result["object_keys"]},
        )
        self.assertEqual([], fake_storage.deleted_keys)

        real_result = service.run(dry_run=False, now=now)

        self.assertEqual(2, real_result["summary"]["deleted_object_keys"])
        self.assertEqual(
            ["outputs/old_oss_task/final.jpg", "uploads/old_oss_asset.png"],
            sorted(fake_storage.deleted_keys),
        )

    def _upload_file(self, name: str, modified_at: datetime) -> Path:
        path = self.upload_dir / name
        path.write_bytes(PNG_BYTES)
        self._set_mtime(path, modified_at)
        return path

    def _output_dir(self, name: str, modified_at: datetime) -> Path:
        path = self.output_dir / name
        path.mkdir()
        final_path = path / "final.png"
        final_path.write_bytes(PNG_BYTES)
        self._set_mtime(final_path, modified_at)
        self._set_mtime(path, modified_at)
        return path

    def _asset(
        self,
        asset_id: str,
        file_id: str,
        *,
        created_at: datetime,
        deleted_at: datetime | None = None,
    ) -> dict:
        return {
            "asset_id": asset_id,
            "category": "dress",
            "file_id": file_id,
            "filename": file_id,
            "created_at": created_at.isoformat(),
            "deleted_at": deleted_at.isoformat() if deleted_at else "",
        }

    def _write_asset_records(self, records: list[dict]) -> None:
        with AssetLibrary._FILE_LOCK:
            writer = getattr(AssetLibrary, "_write_records", None)
            if writer is not None:
                writer(records)
                return

            from backend.storage import database

            for record in records:
                database.upsert_asset_record(record, db_path=AssetLibrary._database_path())

    def _read_asset_records(self) -> list[dict]:
        with AssetLibrary._FILE_LOCK:
            try:
                return AssetLibrary._read_records(include_deleted=True)
            except TypeError:
                with open(AssetLibrary.DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)

    def _set_mtime(self, path: Path, modified_at: datetime) -> None:
        timestamp = modified_at.timestamp()
        os.utime(path, (timestamp, timestamp))


if __name__ == "__main__":
    unittest.main()
