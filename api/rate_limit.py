from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from fastapi import Request


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    reset_seconds: int


class FixedWindowRateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int):
        self._max_requests = max_requests
        self._window_seconds = max(1, window_seconds)
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str, now: float | None = None) -> RateLimitDecision:
        if self._max_requests <= 0:
            return RateLimitDecision(allowed=True, remaining=0, reset_seconds=0)

        current_time = time.monotonic() if now is None else now
        with self._lock:
            window_start, count = self._windows.get(client_id, (current_time, 0))
            elapsed = current_time - window_start
            if elapsed >= self._window_seconds:
                window_start = current_time
                count = 0

            reset_seconds = max(1, int(self._window_seconds - (current_time - window_start)))
            if count >= self._max_requests:
                return RateLimitDecision(
                    allowed=False,
                    remaining=0,
                    reset_seconds=reset_seconds,
                )

            count += 1
            self._windows[client_id] = (window_start, count)
            return RateLimitDecision(
                allowed=True,
                remaining=max(0, self._max_requests - count),
                reset_seconds=reset_seconds,
            )


def client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
