# SPDX-License-Identifier: MIT
"""The rate limiter: the sliding window's allowance and its refusal,
the window's expiry, the fail-closed guards, the /64 aggregation that
collapses an IPv6 address flood to one row, and the at-cap eviction
that admits a new client instead of locking the table shut."""

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


def test_the_key_table_stays_bounded_under_a_flood_of_distinct_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key table is bounded, and the bound never refuses a new
    client: with three live rows each holding a hit inside its window,
    a new key at the cap is served — the least-recently-active row is
    evicted to admit it — and the table stays at three keys. The walk
    runs only on this rare path, so the work per call is bounded by the
    call's own key elsewhere (the round-2 advisory's bound). The
    table's interior is read for the boundedness assertion."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 3)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("k1", 3, 60.0)
    ticks[0] = 1.0
    assert limiter.allow("k2", 3, 60.0)
    ticks[0] = 2.0
    assert limiter.allow("k3", 3, 60.0)
    ticks[0] = 3.0
    # The new key is served, evicting the least-recently-active row.
    assert limiter.allow("k4", 3, 60.0)
    assert set(limiter._hits) == {"k2", "k3", "k4"}
    assert len(limiter._hits) == 3


def test_at_a_full_table_of_live_rows_the_new_key_evicts_the_oldest_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At a table full of live rows the admission evicts the single
    least-recently-active row — never the most recent, and never by
    insertion order: `b` was inserted first but re-hit last, so the
    eviction lands on `a` (kills the evict-the-newest and evict-the-
    first-inserted mutants alike). The price is pinned too: the evicted
    key's remaining allowance is released, so its next attempt inside
    the same window is served again."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 2)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    # `b` is inserted first (t=0) but re-hit last (t=30).
    assert limiter.allow("b", 2, 60.0)
    ticks[0] = 10.0
    assert limiter.allow("a", 1, 60.0)
    ticks[0] = 30.0
    assert limiter.allow("b", 2, 60.0)
    # The table is full of live rows; the new key is served anyway.
    assert limiter.allow("incoming", 1, 60.0)
    assert "a" not in limiter._hits
    assert "b" in limiter._hits and "incoming" in limiter._hits
    # The evicted row's budget was released: `a` is served again even
    # though its window (from t=10) has not passed.
    assert limiter.allow("a", 1, 60.0)


def test_a_flood_of_distinct_addresses_cannot_lock_out_a_new_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flood the round-4 refusal locked out: the table fills with
    live rows — here a hundred distinct IPv6 addresses that collapse to
    one /64 row plus enough distinct IPv4 rows to reach the cap — and a
    brand-new client is still served at once (kills the
    keep-the-refusal mutant, which answered False at the full table)."""
    from atlas_settings import ratelimit as ratelimit_module

    monkeypatch.setattr(ratelimit_module, "_MAX_RATE_KEYS", 4096)
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    # A hundred distinct addresses inside one /64: one row, one
    # allowance — the first address spends it, the rest are refused
    # into the same row instead of filling the table.
    assert limiter.allow("login-ip:2001:db8:aaaa:bbbb:1:2:3:4", 1, 60.0)
    for i in range(1, 100):
        assert not limiter.allow(f"login-ip:2001:db8:aaaa:bbbb::{i:x}", 1, 60.0)
    shared = [k for k in limiter._hits if "2001:db8:aaaa:bbbb" in k]
    assert len(shared) == 1
    # The rest of the table: distinct rows up to the cap.
    for i in range(4095):
        octet_a, rest = divmod(i, 256)
        assert limiter.allow(f"login-ip:10.{octet_a}.{rest}.7", 1, 60.0)
    assert len(limiter._hits) == 4096
    # The flood is at the cap and every row is live — and the fresh
    # client is served immediately, not after waiting out a window.
    assert limiter.allow("login-ip:10.99.99.99", 1, 60.0)
    assert len(limiter._hits) == 4096


def test_distinct_ipv6_addresses_in_one_slash64_share_one_row() -> None:
    """An IPv6 address aggregates by its /64: a second address in the
    same /64 shares the first one's row — and its already-spent
    allowance, so one /64 is one client — while a different /64 keeps
    its own row (kills the skip-the-aggregation mutant, which gave
    every address its own row and its own allowance)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("login-ip:2001:db8:aaaa:bbbb:1:2:3:4", 1, 60.0)
    # Same /64: shares the spent row, refused.
    assert not limiter.allow("login-ip:2001:db8:aaaa:bbbb:ffff::1", 1, 60.0)
    # A different /64: its own row, served.
    assert limiter.allow("login-ip:2001:db8:aaaa:cccc::1", 1, 60.0)
    assert len(limiter._hits) == 2
    assert all("/" not in k for k in limiter._hits)


def test_an_ipv4_mapped_address_keeps_its_own_allowance() -> None:
    """An IPv4-mapped IPv6 literal collapses to its IPv4 address — the
    mapped and plain presentations of one client share a row — while
    distinct mapped clients keep distinct rows (kills the
    aggregate-every-IPv6 mutant, which would have folded every mapped
    client into one giant row, and the skip-the-mapping mutant, which
    would have given the mapped and plain presentations of one client
    two rows and two allowances)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("login-ip:::ffff:1.2.3.4", 1, 60.0)
    # A distinct mapped client: its own row, served.
    assert limiter.allow("login-ip:::ffff:5.6.7.8", 1, 60.0)
    # The plain IPv4 presentation of the first client: the same row,
    # already spent.
    assert not limiter.allow("login-ip:1.2.3.4", 1, 60.0)
    assert len(limiter._hits) == 2


def test_a_non_address_key_is_not_mangled() -> None:
    """A session key stays exactly as composed — the /64 aggregation is
    for keys that name an address (kills the mangle-everything
    mutant)."""
    ticks = [0.0]

    def now() -> float:
        return ticks[0]

    limiter = RateLimiter(now=now)
    assert limiter.allow("write-session:abc123::not-an-address", 1, 60.0)
    assert set(limiter._hits) == {"write-session:abc123::not-an-address"}
