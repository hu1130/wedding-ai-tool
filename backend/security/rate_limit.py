"""In-process rate limits for cost-sensitive AI generation endpoints."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Deque, Iterable, Mapping

from fastapi import HTTPException, Request

from backend.config import settings


Clock = Callable[[], float]


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool = False
    max_create_tasks_per_hour: int = 60
    max_create_tasks_per_day: int = 200
    max_uploads_per_hour: int = 120

    @classmethod
    def from_settings(cls) -> "RateLimitConfig":
        return cls(
            enabled=settings.rate_limit_enabled,
            max_create_tasks_per_hour=settings.max_create_tasks_per_hour,
            max_create_tasks_per_day=settings.max_create_tasks_per_day,
            max_uploads_per_hour=settings.max_uploads_per_hour,
        )


@dataclass(frozen=True)
class LimitRule:
    name: str
    max_events: int
    window_seconds: int
    message: str


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    message: str
    retry_after_seconds: int
    rule_name: str


class InMemoryRateLimiter:
    """Single-process sliding-window limiter."""

    def __init__(self, clock: Clock | None = None):
        self._clock = clock or time.time
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def consume(self, subject: str, rules: Iterable[LimitRule], amount: int = 1) -> None:
        if amount < 1:
            raise ValueError("amount must be at least 1")

        now = self._clock()
        prepared_rules = list(rules)
        with self._lock:
            for rule in prepared_rules:
                key = self._key(subject, rule.name)
                events = self._events[key]
                self._prune(events, now, rule.window_seconds)

                if rule.max_events <= 0 or len(events) + amount > rule.max_events:
                    retry_after = self._retry_after(events, now, rule.window_seconds)
                    raise RateLimitExceeded(
                        message=rule.message,
                        retry_after_seconds=retry_after,
                        rule_name=rule.name,
                    )

            for rule in prepared_rules:
                events = self._events[self._key(subject, rule.name)]
                for _ in range(amount):
                    events.append(now)

    @staticmethod
    def _key(subject: str, rule_name: str) -> str:
        return f"{rule_name}:{subject}"

    @staticmethod
    def _prune(events: Deque[float], now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()

    @staticmethod
    def _retry_after(events: Deque[float], now: float, window_seconds: int) -> int:
        if not events:
            return window_seconds
        return max(1, int(math.ceil(events[0] + window_seconds - now)))


rate_limiter = InMemoryRateLimiter()


def identify_subject(request: Request, user_id: str | None = None) -> str:
    """Return a user key when available, otherwise fall back to client IP."""

    explicit_user = (user_id or "").strip()
    if explicit_user:
        return f"user:{explicit_user}"

    header_user = (request.headers.get("x-user-id") or "").strip()
    if header_user:
        return f"user:{header_user}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_ip = forwarded_for.split(",", 1)[0].strip()
        if first_ip:
            return f"ip:{first_ip}"

    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return f"ip:{real_ip}"

    if request.client and request.client.host:
        return f"ip:{request.client.host}"

    return "ip:unknown"


def check_upload_rate(
    subject: str,
    *,
    amount: int = 1,
    limiter: InMemoryRateLimiter | None = None,
    config: RateLimitConfig | None = None,
) -> None:
    active_config = config or RateLimitConfig.from_settings()
    if not active_config.enabled:
        return

    active_limiter = limiter or rate_limiter
    active_limiter.consume(
        subject,
        [
            LimitRule(
                name="uploads_per_hour",
                max_events=active_config.max_uploads_per_hour,
                window_seconds=3600,
                message="Too many uploads. Please wait before uploading another image.",
            )
        ],
        amount=amount,
    )


def check_create_task_rate(
    subject: str,
    *,
    amount: int = 1,
    limiter: InMemoryRateLimiter | None = None,
    config: RateLimitConfig | None = None,
) -> None:
    active_config = config or RateLimitConfig.from_settings()
    if not active_config.enabled:
        return

    active_limiter = limiter or rate_limiter
    active_limiter.consume(
        subject,
        [
            LimitRule(
                name="create_tasks_per_hour",
                max_events=active_config.max_create_tasks_per_hour,
                window_seconds=3600,
                message="Too many generation requests this hour. Please try again later.",
            ),
            LimitRule(
                name="create_tasks_per_day",
                max_events=active_config.max_create_tasks_per_day,
                window_seconds=86400,
                message="Daily generation limit reached. Please try again tomorrow.",
            ),
        ],
        amount=amount,
    )


def raise_http_429(exc: RateLimitExceeded) -> None:
    retry_after = max(1, exc.retry_after_seconds)
    raise HTTPException(
        status_code=429,
        detail=exc.message,
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Rule": exc.rule_name,
        },
    )


async def limit_upload_requests(request: Request) -> None:
    try:
        check_upload_rate(identify_subject(request))
    except RateLimitExceeded as exc:
        raise_http_429(exc)


async def limit_create_task_requests(request: Request) -> None:
    try:
        check_create_task_rate(identify_subject(request))
    except RateLimitExceeded as exc:
        raise_http_429(exc)


def make_upload_rate_limit_dependency(
    *,
    limiter: InMemoryRateLimiter,
    config: RateLimitConfig,
) -> Callable[[Request], object]:
    async def dependency(request: Request) -> None:
        try:
            check_upload_rate(identify_subject(request), limiter=limiter, config=config)
        except RateLimitExceeded as exc:
            raise_http_429(exc)

    return dependency


def make_create_task_rate_limit_dependency(
    *,
    limiter: InMemoryRateLimiter,
    config: RateLimitConfig,
) -> Callable[[Request], object]:
    async def dependency(request: Request) -> None:
        try:
            check_create_task_rate(identify_subject(request), limiter=limiter, config=config)
        except RateLimitExceeded as exc:
            raise_http_429(exc)

    return dependency


def rate_limit_summary(config: RateLimitConfig | None = None) -> Mapping[str, int | bool]:
    active_config = config or RateLimitConfig.from_settings()
    return {
        "enabled": active_config.enabled,
        "max_create_tasks_per_hour": active_config.max_create_tasks_per_hour,
        "max_create_tasks_per_day": active_config.max_create_tasks_per_day,
        "max_uploads_per_hour": active_config.max_uploads_per_hour,
    }
