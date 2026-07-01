import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
import zipfile

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency guard for bare Python envs
    FastAPI = None
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from backend.models.task import Task, TaskStatus


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class ApiSmokeTest(unittest.TestCase):
    def setUp(self):
        self.original_data_file = Task.DATA_FILE
        self.data_dir = tempfile.TemporaryDirectory()
        Task.DATA_FILE = os.path.join(self.data_dir.name, "tasks.json")
        self.project_root = Task.project_root()
        self.test_id = uuid.uuid4().hex[:10]
        self.created_files: list[str] = []
        self.created_dirs: list[str] = []

        self.model = self._project_file(f"uploads/api_model_{self.test_id}.png")
        self.dress = self._project_file(f"uploads/api_dress_{self.test_id}.png")
        output_dir = self._project_dir(f"outputs/api_task_{self.test_id}")
        self.final = os.path.join(output_dir, "final.png")
        with open(self.final, "wb") as f:
            f.write(PNG_BYTES)
        self.created_files.append(self.final)

        task = Task(
            task_id=f"api_{self.test_id}",
            name="api smoke",
            model_file=self.model,
            dress_file=self.dress,
        )
        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.output_files["final"] = self.final
        task.save()

        from backend.routers import result as result_router
        from backend.routers import task as task_router

        app = FastAPI()
        app.include_router(task_router.router)
        app.include_router(result_router.router)
        self.client = TestClient(app)
        self.task_id = task.task_id

    def tearDown(self):
        Task.DATA_FILE = self.original_data_file
        for path in self.created_files:
            if os.path.exists(path):
                os.remove(path)
        for path in sorted(self.created_dirs, key=len, reverse=True):
            if os.path.isdir(path):
                shutil.rmtree(path)
        self.data_dir.cleanup()

    def _project_file(self, relative_path: str) -> str:
        path = os.path.join(self.project_root, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(PNG_BYTES)
        self.created_files.append(path)
        return path

    def _project_dir(self, relative_path: str) -> str:
        path = os.path.join(self.project_root, relative_path)
        os.makedirs(path, exist_ok=True)
        self.created_dirs.append(path)
        return path

    def test_tasks_and_image_endpoints(self):
        tasks_response = self.client.get("/api/tasks")
        self.assertEqual(200, tasks_response.status_code)
        tasks_payload = tasks_response.json()
        self.assertEqual(1, tasks_payload["total"])
        self.assertTrue(tasks_payload["tasks"][0]["output_files"]["final"])
        self.assertEqual("completed", tasks_payload["tasks"][0]["current_step"])
        self.assertEqual("已完成", tasks_payload["tasks"][0]["current_step_label"])

        detail_response = self.client.get(f"/api/task/{self.task_id}")
        self.assertEqual(200, detail_response.status_code)
        self.assertEqual(self.task_id, detail_response.json()["task"]["task_id"])

        result_response = self.client.get(f"/api/task/{self.task_id}/result")
        self.assertEqual(200, result_response.status_code)
        self.assertEqual("image/png", result_response.headers["content-type"])

        input_response = self.client.get(f"/api/task/{self.task_id}/input/model")
        self.assertEqual(200, input_response.status_code)
        self.assertEqual("image/png", input_response.headers["content-type"])

    def test_mark_and_unmark_deliverable(self):
        mark_response = self.client.patch(
            f"/api/task/{self.task_id}/deliverable",
            json={"is_deliverable": True},
        )
        self.assertEqual(200, mark_response.status_code)
        marked_task = mark_response.json()["task"]
        self.assertTrue(marked_task["is_deliverable"])
        self.assertTrue(marked_task["deliverable_at"])

        tasks_response = self.client.get("/api/tasks")
        self.assertTrue(tasks_response.json()["tasks"][0]["is_deliverable"])

        unmark_response = self.client.patch(
            f"/api/task/{self.task_id}/deliverable",
            json={"is_deliverable": False},
        )
        self.assertEqual(200, unmark_response.status_code)
        unmarked_task = unmark_response.json()["task"]
        self.assertFalse(unmarked_task["is_deliverable"])
        self.assertEqual("", unmarked_task["deliverable_at"])

    def test_rejects_deliverable_without_final_output(self):
        task = Task(
            task_id=f"draft_{self.test_id}",
            name="draft",
            model_file=self.model,
            dress_file=self.dress,
        )
        task.save()

        response = self.client.patch(
            f"/api/task/{task.task_id}/deliverable",
            json={"is_deliverable": True},
        )
        self.assertEqual(409, response.status_code)

    def test_filters_and_exports_deliverables(self):
        empty_filter_response = self.client.get("/api/tasks?deliverable=true")
        self.assertEqual(200, empty_filter_response.status_code)
        self.assertEqual(0, empty_filter_response.json()["total"])

        self.client.patch(
            f"/api/task/{self.task_id}/deliverable",
            json={"is_deliverable": True},
        )

        filter_response = self.client.get("/api/tasks?deliverable=true")
        self.assertEqual(200, filter_response.status_code)
        self.assertEqual(1, filter_response.json()["total"])

        export_response = self.client.get("/api/deliverables/export")
        self.assertEqual(200, export_response.status_code)
        self.assertEqual("application/zip", export_response.headers["content-type"])
        self.assertIn("wedding-deliverables-", export_response.headers["content-disposition"])

        with zipfile.ZipFile(io.BytesIO(export_response.content)) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            image_names = [name for name in names if name.startswith("images/")]
            self.assertEqual(1, len(image_names))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        self.assertEqual(1, manifest["count"])
        self.assertEqual(self.task_id, manifest["items"][0]["task_id"])

    def test_export_deliverables_requires_marked_outputs(self):
        export_response = self.client.get("/api/deliverables/export")
        self.assertEqual(404, export_response.status_code)


if __name__ == "__main__":
    unittest.main()
