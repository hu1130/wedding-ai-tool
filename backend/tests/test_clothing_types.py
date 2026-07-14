import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency guard for bare Python envs
    FastAPI = None
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from backend.config import settings
from backend.models.clothing import SUPPORTED_CLOTHING_TYPES
from backend.models.task import Task
from backend.services.wanx_scene import (
    WanxSceneService,
    build_clothing_negative_prompt,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


class ClothingPromptTest(unittest.TestCase):
    def setUp(self):
        self.service = WanxSceneService.__new__(WanxSceneService)

    def test_supported_clothing_types_include_wedding_first_extensions(self):
        self.assertIn("wedding_gown", SUPPORTED_CLOTHING_TYPES)
        self.assertIn("evening_dress", SUPPORTED_CLOTHING_TYPES)
        self.assertIn("suit", SUPPORTED_CLOTHING_TYPES)
        self.assertIn("hanfu", SUPPORTED_CLOTHING_TYPES)
        self.assertIn("cheongsam", SUPPORTED_CLOTHING_TYPES)
        self.assertIn("casual_outfit", SUPPORTED_CLOTHING_TYPES)

    def test_generic_scene_prompt_uses_requested_clothing_type(self):
        prompt = self.service.build_clothing_scene_prompt(
            scene_name="影棚",
            clothing_type="suit",
            pose="自然站立",
            preserve_face=True,
            scene_prompt="clean studio light",
        )

        self.assertIn("tailored suit", prompt)
        self.assertIn("suit jacket structure", prompt)
        self.assertIn("clean studio light", prompt)
        self.assertIn("Keep the exact face identity", prompt)
        self.assertNotIn("白色婚纱", prompt)
        self.assertNotIn("真实婚纱照", prompt)

    def test_reference_prompt_supports_non_wedding_pose_reference(self):
        prompt = self.service.build_reference_clothing_prompt(
            scene_name="影棚",
            clothing_type="cheongsam",
            pose="轻微侧身",
            pose_mode="light",
            preserve_face=True,
            scene_prompt="quiet studio",
            has_pose_reference=True,
        )

        self.assertIn("three references", prompt)
        self.assertIn("cheongsam", prompt)
        self.assertIn("The third reference image is only for body direction", prompt)
        self.assertIn("quiet studio", prompt)
        self.assertNotIn("婚纱款式", prompt)

    def test_generic_negative_prompt_includes_face_artifact_guards(self):
        prompt = build_clothing_negative_prompt("suit", reference_mode=True)

        self.assertIn("wrong lapel", prompt)
        self.assertIn("incomplete outfit transfer", prompt)
        self.assertIn("sticker face", prompt)
        self.assertIn("mismatched skin tone", prompt)


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class ClothingTypeApiTest(unittest.TestCase):
    def setUp(self):
        self.original_data_file = Task.DATA_FILE
        self.original_upload_dir = settings.upload_dir
        self.data_dir = tempfile.TemporaryDirectory()
        self.upload_dir = tempfile.TemporaryDirectory()
        Task.DATA_FILE = os.path.join(self.data_dir.name, "tasks.json")
        settings.upload_dir = self.upload_dir.name

        from backend.routers import task as task_router

        app = FastAPI()
        app.include_router(task_router.router)
        self.client = TestClient(app)

        self.model_file = self._upload_file("model.png")
        self.dress_file = self._upload_file("garment.png")

    def tearDown(self):
        Task.DATA_FILE = self.original_data_file
        settings.upload_dir = self.original_upload_dir
        self.upload_dir.cleanup()
        self.data_dir.cleanup()

    def _upload_file(self, filename: str) -> str:
        path = os.path.join(self.upload_dir.name, filename)
        with open(path, "wb") as f:
            f.write(PNG_BYTES)
        return filename

    def _payload(self, clothing_type: str) -> dict:
        return {
            "name": f"{clothing_type} test",
            "model_file": self.model_file,
            "dress_file": self.dress_file,
            "clothing_type": clothing_type,
            "scene": "影棚",
            "pose": "保持原姿势",
        }

    def test_create_task_accepts_non_wedding_clothing_type(self):
        with patch("backend.routers.task.enqueue_task", new=AsyncMock()) as enqueue_task:
            response = self.client.post("/api/create-task", json=self._payload("suit"))

        self.assertEqual(200, response.status_code, response.text)
        task_id = response.json()["task_id"]
        task = Task.get(task_id)
        self.assertIsNotNone(task)
        self.assertEqual("suit", task.clothing_type)
        enqueue_task.assert_awaited_once_with(task_id)

    def test_create_task_rejects_unknown_clothing_type(self):
        response = self.client.post("/api/create-task", json=self._payload("space_suit"))

        self.assertEqual(400, response.status_code)
        self.assertIn("Unsupported clothing_type", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
