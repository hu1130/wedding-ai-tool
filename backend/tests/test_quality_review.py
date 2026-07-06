import os
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

from backend.models.quality_review import QualityReview
from backend.models.task import Task


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class QualityReviewApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_task_data_file = Task.DATA_FILE
        self.old_review_data_file = QualityReview.DATA_FILE
        Task.DATA_FILE = os.path.join(self.temp_dir.name, "tasks.json")
        QualityReview.DATA_FILE = os.path.join(self.temp_dir.name, "quality_reviews.json")

        self.task = Task(
            task_id="review_task",
            name="review task",
            model_file="model.png",
            dress_file="dress.png",
        )
        self.task.save()

        from backend.routers import quality_review as quality_review_router

        app = FastAPI()
        app.include_router(quality_review_router.router)
        self.client = TestClient(app)

    def tearDown(self):
        Task.DATA_FILE = self.old_task_data_file
        QualityReview.DATA_FILE = self.old_review_data_file
        self.temp_dir.cleanup()

    def test_creates_and_updates_quality_review(self):
        response = self.client.put(
            f"/api/task/{self.task.task_id}/quality-review",
            json={
                "face_score": 4,
                "dress_score": 5,
                "pose_score": 3,
                "background_score": 4,
                "notes": "good demo candidate",
            },
        )
        self.assertEqual(200, response.status_code)
        review = response.json()["review"]
        self.assertEqual(4, review["overall_score"])
        self.assertTrue(review["pass_result"])

        get_response = self.client.get(f"/api/task/{self.task.task_id}/quality-review")
        self.assertEqual(200, get_response.status_code)
        self.assertEqual("good demo candidate", get_response.json()["review"]["notes"])

        update_response = self.client.put(
            f"/api/task/{self.task.task_id}/quality-review",
            json={
                "face_score": 2,
                "dress_score": 5,
                "pose_score": 3,
                "background_score": 4,
                "overall_score": 3,
                "notes": "face changed",
            },
        )
        self.assertEqual(200, update_response.status_code)
        updated = update_response.json()["review"]
        self.assertEqual(3, updated["overall_score"])
        self.assertFalse(updated["pass_result"])

        list_response = self.client.get("/api/quality-reviews")
        self.assertEqual(1, list_response.json()["total"])

    def test_rejects_missing_task_and_invalid_score(self):
        missing_response = self.client.put(
            "/api/task/missing/quality-review",
            json={
                "face_score": 4,
                "dress_score": 4,
                "pose_score": 4,
                "background_score": 4,
            },
        )
        self.assertEqual(404, missing_response.status_code)

        invalid_response = self.client.put(
            f"/api/task/{self.task.task_id}/quality-review",
            json={
                "face_score": 6,
                "dress_score": 4,
                "pose_score": 4,
                "background_score": 4,
            },
        )
        self.assertEqual(400, invalid_response.status_code)


if __name__ == "__main__":
    unittest.main()
