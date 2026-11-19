# SPDX-License-Identifier: MIT
"""The rate limiter: the fixed window's allowance and its refusal, and
the window's reset."""

import pytest

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


def test_a_spent_key_is_evicted_when_the_walk_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key whose newest hit is older than its own window is dropped
    from the table when the eviction walk runs (the walk is amortized to
    the cap, per the round-2 advisory; below the cap a spent key's stale
    list lingers until its own next call filters it). The table's
    interior is read directly here because eviction has no behavioral
    observable: the refused-or-allowed answer is identical either way."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 1)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("spent", 3, 60.0)
    ticks[0] = 61.0
    assert limiter.allow("other", 3, 60.0)
    assert "spent" not in limiter._hits
    assert "other" in limiter._hits


def test_the_window_is_this_call_s_window() -> None:
    """The attempt is measured against this call's `window_s`, not
    whatever window the key's first hit was stored under (kills the
    stored-window mutant: five hits under a 300s window, then a call
    with a 60s window at t=120 is allowed, not refused by the stale
    300s measurement)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    for _ in range(5):
        assert limiter.allow("key", 5, 300.0)
    ticks[0] = 120.0
    assert limiter.allow("key", 1, 60.0)


def test_two_hits_inside_one_window_kill_the_boundary_mutant() -> None:
    """With two hits at t=0 and t=30 under a 60s window and limit 2, the
    call at t=60 is allowed: the exactly-window-old hit is out (`<`) while
    the newer one stands. The `<=` mutant keeps both and refuses — this
    test is what kills it (the single-hit version cannot, because the
    eviction drops the whole key before the filter runs)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("key", 2, 60.0)
    ticks[0] = 30.0
    assert limiter.allow("key", 2, 60.0)
    ticks[0] = 60.0
    assert limiter.allow("key", 2, 60.0)


def test_the_key_table_evicts_the_oldest_key_past_its_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key table is bounded: past the cap the key with the oldest
    newest-hit is evicted, and the full-table walk runs only on that
    rare path — a call below the cap neither evicts nor walks, so the
    work per call is bounded by the call's own key (the advisory's
    bound). The table's interior is read for the eviction assertion
    because eviction has no behavioral observable."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 3)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    for name in ("k1", "k2", "k3"):
        assert limiter.allow(name, 3, 60.0)
    ticks[0] = 1.0
    assert limiter.allow("k4", 3, 60.0)
    assert "k1" not in limiter._hits
    assert "k4" in limiter._hits
    # The next call at the cap gives up the next-oldest key; the table
    # never grows past it.
    assert limiter.allow("k5", 3, 60.0) is True
    assert "k2" not in limiter._hits
    assert {"k3", "k4", "k5"} <= set(limiter._hits)
    assert limiter.allow("k6", 3, 60.0) is True
    assert {"k4", "k5", "k6"} <= set(limiter._hits)
    assert len(limiter._hits) <= 3
