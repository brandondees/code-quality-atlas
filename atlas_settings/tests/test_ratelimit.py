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


def test_a_zero_or_negative_window_refuses_fail_closed() -> None:
    """A limit check that cannot be evaluated refuses (kills the
    fail-open mutant where a non-positive window emptied the list and
    allowed everything)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert not limiter.allow("key", 3, 0)
    assert not limiter.allow("key", 3, -5)
    assert not limiter.allow("key", 0, 60)


def test_a_hit_at_exactly_the_window_has_expired() -> None:
    """At exactly `window_s` the hit is out of the window and the attempt
    is allowed; one tick earlier it is not (kills the `now - t < window`
    → `<=` mutant at the boundary)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("key", 1, 60.0)
    ticks[0] = 59.999
    assert not limiter.allow("key", 1, 60.0)
    ticks[0] = 60.0
    assert limiter.allow("key", 1, 60.0)


def test_a_spent_key_is_evicted_by_the_next_call() -> None:
    """A key whose newest hit is older than its own window is dropped
    from the table by the next `allow` call on any key — an address that
    stops knocking does not linger until the process restarts. The table's
    interior is read directly here because eviction has no behavioral
    observable: the refused-or-allowed answer is identical either way."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("spent", 3, 60.0)
    ticks[0] = 61.0
    assert limiter.allow("other", 3, 60.0)
    assert "spent" not in limiter._hits
    assert "other" in limiter._hits
