import unittest

try:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency guard for bare Python envs
    Depends = None
    FastAPI = None
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from backend.security.rate_limit import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimitExceeded,
    check_create_task_rate,
    check_upload_rate,
    make_upload_rate_limit_dependency,
)


class FakeClock:
    def __init__(self, start: float = 0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RateLimitCoreTest(unittest.TestCase):
    def test_disabled_config_allows_requests(self):
        clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=clock)
        config = RateLimitConfig(
            enabled=False,
            max_create_tasks_per_hour=1,
            max_create_tasks_per_day=1,
            max_uploads_per_hour=1,
        )

        for _ in range(5):
            check_upload_rate("ip:127.0.0.1", limiter=limiter, config=config)
            check_create_task_rate("ip:127.0.0.1", limiter=limiter, config=config)

    def test_upload_limit_resets_after_hour_window(self):
        clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=clock)
        config = RateLimitConfig(
            enabled=True,
            max_create_tasks_per_hour=10,
            max_create_tasks_per_day=10,
            max_uploads_per_hour=2,
        )

        check_upload_rate("ip:127.0.0.1", limiter=limiter, config=config)
        check_upload_rate("ip:127.0.0.1", limiter=limiter, config=config)
        with self.assertRaises(RateLimitExceeded) as raised:
            check_upload_rate("ip:127.0.0.1", limiter=limiter, config=config)

        self.assertEqual("uploads_per_hour", raised.exception.rule_name)
        self.assertGreaterEqual(raised.exception.retry_after_seconds, 1)

        clock.advance(3601)
        check_upload_rate("ip:127.0.0.1", limiter=limiter, config=config)

    def test_create_task_checks_hour_and_daily_generation_limits(self):
        clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=clock)
        config = RateLimitConfig(
            enabled=True,
            max_create_tasks_per_hour=10,
            max_create_tasks_per_day=2,
            max_uploads_per_hour=10,
        )

        check_create_task_rate("user:alice", limiter=limiter, config=config)
        clock.advance(3601)
        check_create_task_rate("user:alice", limiter=limiter, config=config)

        with self.assertRaises(RateLimitExceeded) as raised:
            check_create_task_rate("user:alice", limiter=limiter, config=config)

        self.assertEqual("create_tasks_per_day", raised.exception.rule_name)
        self.assertIn("Daily generation limit", raised.exception.message)

    def test_create_task_amount_counts_batch_requests(self):
        clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=clock)
        config = RateLimitConfig(
            enabled=True,
            max_create_tasks_per_hour=3,
            max_create_tasks_per_day=10,
            max_uploads_per_hour=10,
        )

        check_create_task_rate("ip:127.0.0.1", amount=2, limiter=limiter, config=config)

        with self.assertRaises(RateLimitExceeded) as raised:
            check_create_task_rate("ip:127.0.0.1", amount=2, limiter=limiter, config=config)

        self.assertEqual("create_tasks_per_hour", raised.exception.rule_name)

    def test_subjects_are_limited_independently(self):
        clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=clock)
        config = RateLimitConfig(
            enabled=True,
            max_create_tasks_per_hour=1,
            max_create_tasks_per_day=1,
            max_uploads_per_hour=1,
        )

        check_upload_rate("ip:one", limiter=limiter, config=config)
        check_upload_rate("ip:two", limiter=limiter, config=config)


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class RateLimitDependencyTest(unittest.TestCase):
    def test_dependency_returns_429_with_retry_after(self):
        clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=clock)
        config = RateLimitConfig(
            enabled=True,
            max_create_tasks_per_hour=10,
            max_create_tasks_per_day=10,
            max_uploads_per_hour=1,
        )

        app = FastAPI()
        dependency = make_upload_rate_limit_dependency(limiter=limiter, config=config)

        @app.post("/upload-check", dependencies=[Depends(dependency)])
        async def upload_check():
            return {"ok": True}

        client = TestClient(app)

        first = client.post("/upload-check", headers={"x-forwarded-for": "203.0.113.10"})
        second = client.post("/upload-check", headers={"x-forwarded-for": "203.0.113.10"})

        self.assertEqual(200, first.status_code)
        self.assertEqual(429, second.status_code)
        self.assertEqual(
            "Too many uploads. Please wait before uploading another image.",
            second.json()["detail"],
        )
        self.assertEqual("uploads_per_hour", second.headers["x-ratelimit-rule"])
        self.assertTrue(second.headers["retry-after"])


if __name__ == "__main__":
    unittest.main()
