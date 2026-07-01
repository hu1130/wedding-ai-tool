import json
import os
import shutil
import tempfile
import unittest
import uuid

from backend.models.task import Task, TaskStatus


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


class TaskStorageTest(unittest.TestCase):
    def setUp(self):
        self.original_data_file = Task.DATA_FILE
        self.data_dir = tempfile.TemporaryDirectory()
        Task.DATA_FILE = os.path.join(self.data_dir.name, "tasks.json")
        self.project_root = Task.project_root()
        self.test_id = uuid.uuid4().hex[:10]
        self.created_files: list[str] = []
        self.created_dirs: list[str] = []

    def tearDown(self):
        Task.DATA_FILE = self.original_data_file
        for path in self.created_files:
            if os.path.exists(path):
                os.remove(path)
        for path in sorted(self.created_dirs, key=len, reverse=True):
            if os.path.isdir(path):
                shutil.rmtree(path)
        self.data_dir.cleanup()

    def _project_file(self, relative_path: str, content: bytes = PNG_BYTES) -> str:
        path = os.path.join(self.project_root, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        self.created_files.append(path)
        return path

    def _project_dir(self, relative_path: str) -> str:
        path = os.path.join(self.project_root, relative_path)
        os.makedirs(path, exist_ok=True)
        self.created_dirs.append(path)
        return path

    def test_normalizes_historical_wrapped_records(self):
        raw = [
            {
                "value": [
                    {"task_id": "wrapped1", "name": "wrapped task"},
                    {"name": "missing id"},
                ],
                "Count": 2,
            },
            {"task_id": "top1", "name": "top task"},
            {"value": "invalid wrapper"},
        ]
        with open(Task.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f)

        tasks = Task.list_internal()

        self.assertEqual({"wrapped1", "top1"}, {task.task_id for task in tasks})
        self.assertIsNotNone(Task.get("wrapped1"))
        self.assertIsNotNone(Task.get("top1"))
        self.assertIsNone(Task.get("missing"))

    def test_from_dict_rejects_missing_task_id(self):
        with self.assertRaises(ValueError):
            Task.from_dict({"name": "bad record"})

    def test_save_writes_relative_paths_and_delete_keeps_file_clean(self):
        output_dir = self._project_dir(f"outputs/test_task_storage_{self.test_id}")
        model = self._project_file(f"uploads/test_model_{self.test_id}.png")
        dress = self._project_file(f"uploads/test_dress_{self.test_id}.png")
        pose = self._project_file(f"uploads/test_pose_{self.test_id}.png")
        final = os.path.join(output_dir, "final.png")
        with open(final, "wb") as f:
            f.write(PNG_BYTES)
        self.created_files.append(final)

        task = Task(
            task_id=f"storage_{self.test_id}",
            model_file=model,
            dress_file=dress,
            pose_reference_file=pose,
        )
        task.status = TaskStatus.COMPLETED
        task.output_files["final"] = final
        task.save()

        with open(Task.DATA_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)

        self.assertEqual(1, len(saved))
        saved_task = saved[0]
        self.assertEqual(f"uploads/test_model_{self.test_id}.png", saved_task["model_file"])
        self.assertEqual(f"uploads/test_dress_{self.test_id}.png", saved_task["dress_file"])
        self.assertEqual(f"uploads/test_pose_{self.test_id}.png", saved_task["pose_reference_file"])
        self.assertEqual(
            f"outputs/test_task_storage_{self.test_id}/final.png",
            saved_task["output_files"]["final"],
        )
        self.assertFalse(os.path.isabs(os.path.normpath(saved_task["model_file"])))
        self.assertFalse(os.path.isabs(os.path.normpath(saved_task["output_files"]["final"])))

        loaded = Task.get(task.task_id)
        self.assertIsNotNone(loaded)
        self.assertTrue(os.path.isabs(loaded.model_file))
        self.assertTrue(os.path.isabs(loaded.output_files["final"]))

        deleted = Task.delete(task.task_id)
        self.assertIsNotNone(deleted)
        with open(Task.DATA_FILE, "r", encoding="utf-8") as f:
            self.assertEqual([], json.load(f))


if __name__ == "__main__":
    unittest.main()
