from __future__ import annotations

from api.rate_limit import FixedWindowRateLimiter


def test_fixed_window_rate_limiter_blocks_after_limit():
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60)

    first = limiter.check("client", now=100.0)
    second = limiter.check("client", now=101.0)
    third = limiter.check("client", now=102.0)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.remaining == 0


def test_fixed_window_rate_limiter_resets_after_window():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=10)

    assert limiter.check("client", now=100.0).allowed is True
    assert limiter.check("client", now=101.0).allowed is False
    reset = limiter.check("client", now=111.0)

    assert reset.allowed is True
    assert reset.remaining == 0
