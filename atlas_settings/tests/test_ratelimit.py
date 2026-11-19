# SPDX-License-Identifier: MIT
"""The rate limiter: the fixed window's allowance and its refusal, and
the window's reset."""

from atlas_settings.ratelimit import RateLimiter


def test_the_window_allows_up_to_the_limit_then_refuses() -> None:
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    for _ in range(3):
        assert limiter.allow("key", 3, 60.0)
    assert not limiter.allow("key", 3, 60.0)
    # Another key keeps its own window.
    assert limiter.allow("other", 3, 60.0)


def test_the_window_resets_after_it_passes() -> None:
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    for _ in range(2):
        assert limiter.allow("key", 2, 60.0)
    assert not limiter.allow("key", 2, 60.0)
    ticks[0] = 61.0
    assert limiter.allow("key", 2, 60.0)
