# SPDX-License-Identifier: MIT
"""The rate limiter: the sliding window's allowance and its refusal,
the window's expiry, the fail-closed guards, and the at-cap eviction
that never spends a live budget."""

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


def test_the_key_table_never_grows_past_its_cap_by_spending_live_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key table is bounded, and the bound never spends a live
    budget: with three keys each holding one hit under limit 3, a new
    key at the cap is refused (the walk dropped nothing — every key is
    inside its own window), and the table stays at three keys. The walk
    runs only on this rare path, so the work per call is bounded by the
    call's own key elsewhere (the round-2 advisory's bound). The table's
    interior is read for the no-eviction assertion because refusal has
    no other observable."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 3)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    for name in ("k1", "k2", "k3"):
        assert limiter.allow(name, 3, 60.0)
    ticks[0] = 1.0
    assert not limiter.allow("k4", 3, 60.0)
    assert set(limiter._hits) == {"k1", "k2", "k3"}


def test_a_spent_key_stays_refused_at_the_key_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the key cap the eviction drops only keys whose newest hit is
    outside that key's own window: a live key's hit log is its budget,
    and deleting it would hand the caller a fresh allowance. With the
    cap at 2 and limit 1, alternating two keys inside the window stays
    refused, a third key is refused while those two are live, and a key
    whose window has passed is dropped and allowed again (kills the
    evict-the-oldest-live-key mutant)."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 2)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("a", 1, 60.0)
    assert limiter.allow("b", 1, 60.0)
    # Both keys are live and spent: nothing is evicted, nobody passes.
    ticks[0] = 1.0
    assert not limiter.allow("a", 1, 60.0)
    assert not limiter.allow("b", 1, 60.0)
    # A brand-new key is refused too: the table is full of live budgets.
    assert not limiter.allow("c", 1, 60.0)
    assert "a" in limiter._hits and "b" in limiter._hits
    # Once a key's window has passed, it is the drop the walk exists for.
    ticks[0] = 61.0
    assert limiter.allow("a", 1, 60.0)
