import os
import io
import tempfile
import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    FastAPI = None
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from backend.config import settings
from backend.models.asset import AssetLibrary
from backend.models.task import Task
from PIL import Image


def make_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class AssetLibraryApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_upload_dir = settings.upload_dir
        self.old_data_file = AssetLibrary.DATA_FILE
        self.old_task_data_file = Task.DATA_FILE
        settings.upload_dir = os.path.join(self.temp_dir.name, "uploads")
        AssetLibrary.DATA_FILE = os.path.join(self.temp_dir.name, "assets.json")
        Task.DATA_FILE = os.path.join(self.temp_dir.name, "tasks.json")

        from backend.routers import asset as asset_router
        from backend.routers import upload as upload_router

        app = FastAPI()
        app.include_router(upload_router.router)
        app.include_router(asset_router.router)
        self.client = TestClient(app)

    def tearDown(self):
        settings.upload_dir = self.old_upload_dir
        AssetLibrary.DATA_FILE = self.old_data_file
        Task.DATA_FILE = self.old_task_data_file
        self.temp_dir.cleanup()

    def test_upload_registers_asset_and_serves_image(self):
        response = self.client.post(
            "/api/upload",
            data={"category": "dress"},
            files={"file": ("dress.png", make_png_bytes(), "image/png")},
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()
        asset = payload["asset"]
        self.assertEqual("dress", asset["category"])
        self.assertEqual(payload["file_id"], asset["file_id"])

        list_response = self.client.get("/api/assets?category=dress")
        self.assertEqual(200, list_response.status_code)
        assets = list_response.json()["assets"]
        self.assertEqual(1, len(assets))
        self.assertEqual(asset["asset_id"], assets[0]["asset_id"])

        image_response = self.client.get(f"/api/assets/{asset['asset_id']}/image")
        self.assertEqual(200, image_response.status_code)
        self.assertEqual("image/png", image_response.headers["content-type"])

        delete_response = self.client.delete(f"/api/assets/{asset['asset_id']}")
        self.assertEqual(200, delete_response.status_code)
        self.assertEqual([], self.client.get("/api/assets?category=dress").json()["assets"])

        uploaded_path = os.path.join(settings.upload_dir, payload["file_id"])
        self.assertTrue(os.path.exists(uploaded_path))

    def test_asset_list_backfills_historical_task_uploads(self):
        os.makedirs(settings.upload_dir, exist_ok=True)
        model_path = os.path.join(settings.upload_dir, "legacy_model.png")
        dress_path = os.path.join(settings.upload_dir, "legacy_dress.png")
        with open(model_path, "wb") as f:
            f.write(make_png_bytes())
        with open(dress_path, "wb") as f:
            f.write(make_png_bytes())

        task = Task(
            task_id="legacy_assets",
            name="legacy assets",
            model_file=model_path,
            dress_file=dress_path,
        )
        task.save()

        model_response = self.client.get("/api/assets?category=model")
        self.assertEqual(200, model_response.status_code)
        model_assets = model_response.json()["assets"]
        self.assertEqual(1, len(model_assets))
        self.assertEqual("legacy_model.png", model_assets[0]["file_id"])

        dress_response = self.client.get("/api/assets?category=dress")
        self.assertEqual(200, dress_response.status_code)
        dress_assets = dress_response.json()["assets"]
        self.assertEqual(1, len(dress_assets))
        self.assertEqual("legacy_dress.png", dress_assets[0]["file_id"])

        second_response = self.client.get("/api/assets")
        self.assertEqual(2, second_response.json()["total"])

    def test_deleted_backfilled_asset_stays_hidden(self):
        os.makedirs(settings.upload_dir, exist_ok=True)
        model_path = os.path.join(settings.upload_dir, "legacy_model.png")
        with open(model_path, "wb") as f:
            f.write(make_png_bytes())

        task = Task(
            task_id="legacy_deleted_asset",
            name="legacy deleted asset",
            model_file=model_path,
            dress_file=model_path,
        )
        task.save()

        first_response = self.client.get("/api/assets?category=model")
        self.assertEqual(200, first_response.status_code)
        model_assets = first_response.json()["assets"]
        self.assertEqual(1, len(model_assets))
        asset_id = model_assets[0]["asset_id"]

        delete_response = self.client.delete(f"/api/assets/{asset_id}")
        self.assertEqual(200, delete_response.status_code)

        second_response = self.client.get("/api/assets?category=model")
        self.assertEqual(200, second_response.status_code)
        self.assertEqual([], second_response.json()["assets"])

        image_response = self.client.get(f"/api/assets/{asset_id}/image")
        self.assertEqual(404, image_response.status_code)


if __name__ == "__main__":
    unittest.main()
