import json
import os
import tempfile
import unittest

from backend.models.asset import AssetLibrary
from backend.models.task import Task
from backend.storage import database


class DatabaseStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_task_data_file = Task.DATA_FILE
        self.old_asset_data_file = AssetLibrary.DATA_FILE
        self.old_database_url = os.environ.get("DATABASE_URL")
        self.old_sqlite_db_path = os.environ.get("SQLITE_DB_PATH")
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("SQLITE_DB_PATH", None)

    def tearDown(self):
        Task.DATA_FILE = self.old_task_data_file
        AssetLibrary.DATA_FILE = self.old_asset_data_file
        if self.old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.old_database_url
        if self.old_sqlite_db_path is None:
            os.environ.pop("SQLITE_DB_PATH", None)
        else:
            os.environ["SQLITE_DB_PATH"] = self.old_sqlite_db_path
        database.reset_engine_cache()
        self.temp_dir.cleanup()

    def test_sqlite_db_path_env_drives_task_storage(self):
        db_path = os.path.join(self.temp_dir.name, "custom.db")
        os.environ["SQLITE_DB_PATH"] = db_path
        Task.DATA_FILE = os.path.join(self.temp_dir.name, "tasks.json")

        task = Task(task_id="env_task", name="env task")
        task.save()

        self.assertTrue(os.path.exists(db_path))
        self.assertFalse(os.path.exists(Task.DATA_FILE))
        self.assertEqual("env_task", database.get_task_record("env_task", db_path=db_path)["task_id"])
        self.assertIsNotNone(Task.get("env_task"))

    def test_database_url_sqlite_path_is_supported(self):
        db_path = os.path.join(self.temp_dir.name, "url.db")
        os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace("\\", "/")
        Task.DATA_FILE = os.path.join(self.temp_dir.name, "tasks.json")

        Task(task_id="url_task", name="url task").save()

        self.assertTrue(os.path.exists(db_path))
        self.assertEqual("url_task", Task.get("url_task").task_id)

    def test_migrates_legacy_assets_once_and_preserves_soft_delete(self):
        db_path = os.path.join(self.temp_dir.name, "assets.db")
        os.environ["SQLITE_DB_PATH"] = db_path
        AssetLibrary.DATA_FILE = os.path.join(self.temp_dir.name, "assets.json")
        with open(AssetLibrary.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "asset_id": "legacy_asset",
                        "category": "dress",
                        "file_id": "legacy.png",
                        "filename": "legacy.png",
                        "created_at": "2026-01-01T00:00:00",
                    }
                ],
                f,
            )

        self.assertEqual(1, len(AssetLibrary.list_all(category="dress")))
        self.assertIsNotNone(AssetLibrary.delete("legacy_asset"))

        self.assertEqual([], AssetLibrary.list_all(category="dress"))
        deleted_records = database.list_asset_records(include_deleted=True, db_path=db_path)
        self.assertEqual(1, len(deleted_records))
        self.assertTrue(deleted_records[0].get("deleted_at"))

        self.assertEqual([], AssetLibrary.list_all(category="dress"))

    def test_schema_status_reports_business_tables(self):
        db_path = os.path.join(self.temp_dir.name, "schema.db")
        os.environ["SQLITE_DB_PATH"] = db_path
        database.reset_engine_cache()

        status = database.schema_status()

        self.assertTrue(status["ok"])
        self.assertEqual("sqlite", status["database"])
        for table_name in [
            "storage_meta",
            "terminal_user_binding",
            "tool_sessions",
            "tasks",
            "assets",
            "quality_reviews",
            "business_logs",
        ]:
            self.assertIn(table_name, status["expected_tables"])
            self.assertIn(table_name, status["actual_tables"])


if __name__ == "__main__":
    unittest.main()
