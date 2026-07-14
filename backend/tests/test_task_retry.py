import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.config import settings
from backend.models.task import Task, TaskStatus
from backend.services.task_queue import TaskPipeline


class TaskRetryTest(unittest.TestCase):
    def setUp(self):
        self.original_data_file = Task.DATA_FILE
        self.original_output_dir = settings.output_dir
        self.original_max_retries = settings.max_task_retries
        self.original_retry_delay = settings.task_retry_delay_seconds
        self.data_dir = tempfile.TemporaryDirectory()
        self.output_dir = tempfile.TemporaryDirectory()
        Task.DATA_FILE = os.path.join(self.data_dir.name, "tasks.json")
        settings.output_dir = self.output_dir.name
        settings.max_task_retries = 2
        settings.task_retry_delay_seconds = 0

    def tearDown(self):
        Task.DATA_FILE = self.original_data_file
        settings.output_dir = self.original_output_dir
        settings.max_task_retries = self.original_max_retries
        settings.task_retry_delay_seconds = self.original_retry_delay
        self.output_dir.cleanup()
        self.data_dir.cleanup()

    def _pipeline_failing_tryon(self, make_error) -> TaskPipeline:
        pipeline = TaskPipeline.__new__(TaskPipeline)

        async def fail_tryon(task, output_dir):
            raise make_error()

        pipeline._step_tryon = fail_tryon
        return pipeline

    def test_old_task_records_get_retry_defaults(self):
        with open(Task.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump([{"task_id": "old_task", "status": "pending"}], f)

        task = Task.get("old_task")

        self.assertIsNotNone(task)
        self.assertEqual(0, task.retry_count)
        self.assertEqual(settings.max_task_retries, task.max_retries)
        self.assertEqual("", task.last_error_at)
        self.assertEqual("", task.last_error_stage)
        self.assertEqual("", task.next_retry_at)
        saved = task.to_dict()
        self.assertIn("retry_count", saved)
        self.assertIn("max_retries", saved)
        self.assertIn("last_error_at", saved)

    def test_retryable_failure_is_requeued_then_fails_after_limit(self):
        task = Task(
            task_id="retryable_task",
            model_file="uploads/model.png",
            dress_file="uploads/dress.png",
            max_retries=1,
        )
        task.save()
        pipeline = self._pipeline_failing_tryon(
            lambda: RuntimeError("temporary DashScope outage")
        )

        with patch("backend.services.task_queue.is_floor_length_gown", return_value=False):
            should_retry = asyncio.run(pipeline.run_task(task.task_id))
            retried = Task.get(task.task_id)
            should_retry_again = asyncio.run(pipeline.run_task(task.task_id))
            failed = Task.get(task.task_id)

        self.assertTrue(should_retry)
        self.assertEqual(TaskStatus.PENDING, retried.status)
        self.assertEqual(1, retried.retry_count)
        self.assertEqual("dress", retried.last_error_stage)
        self.assertTrue(retried.last_error_at)
        self.assertIn("temporary DashScope outage", retried.error_message)

        self.assertFalse(should_retry_again)
        self.assertEqual(TaskStatus.FAILED, failed.status)
        self.assertEqual(1, failed.retry_count)
        self.assertEqual("dress", failed.last_error_stage)

    def test_non_retryable_failure_does_not_requeue(self):
        task = Task(
            task_id="non_retryable_task",
            model_file="uploads/missing-model.png",
            dress_file="uploads/missing-dress.png",
            max_retries=2,
        )
        task.save()
        pipeline = self._pipeline_failing_tryon(
            lambda: FileNotFoundError("missing local upload")
        )

        with patch("backend.services.task_queue.is_floor_length_gown", return_value=False):
            should_retry = asyncio.run(pipeline.run_task(task.task_id))
        failed = Task.get(task.task_id)

        self.assertFalse(should_retry)
        self.assertEqual(TaskStatus.FAILED, failed.status)
        self.assertEqual(0, failed.retry_count)
        self.assertEqual("dress", failed.last_error_stage)
        self.assertIn("missing local upload", failed.error_message)


if __name__ == "__main__":
    unittest.main()
