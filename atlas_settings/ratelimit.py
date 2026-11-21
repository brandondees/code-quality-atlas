# SPDX-License-Identifier: MIT
"""The settings page's rate limiter (D90): a sliding-window log — one
list of hit timestamps per key, each hit expiring `window_s` after it
was made, which is stricter than a fixed window (no 2x burst across a
boundary) — refusing past the window's allowance with a fixed phrase.
A window or limit that cannot be evaluated (zero or negative) refuses:
a limit check that fails open is not a limit. The attempt is measured
against this call's `window_s`, and the key remembers the last window
it was measured under, which is what the at-cap walk reads. The table
is bounded, and a flood of distinct addresses cannot wedge it shut:
an IPv6 address aggregates by its /64 first — the standard allocation
boundary, so one customer's addresses are one allowance and an address
flood inside one /64 fills one row, not thousands — and past the key
cap the walk first drops the rows whose newest hit is already outside
their own window (freeing room without touching any live budget), and
only when the table is still full of live rows does the admission
evict the single least-recently-active row and serve the caller. The
cost is that the evicted key's remaining allowance is released and it
may re-burst within its window — the accepted trade now, because the
refusal it replaced locked out every new client for up to a whole
window, the worse failure by far; the caller's own row is never the
one evicted (it has none — the eviction only runs for a caller the
table does not know). The walk runs only on that rare path — the
common call filters its own key's hits and walks nothing else, so the
work per call is bounded by that key's hit list, not by the table.
In-process state only: the limits bound one page process's traffic,
which is the surface an attacker reaches directly."""

from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Callable

# The key table's bound: past it the walk drops the expired rows free,
# and a new key at a table still full of live rows evicts the single
# least-recently-active row and is served — the flood can cycle rows,
# never wedge the table.
_MAX_RATE_KEYS = 4096


def _aggregated_row(key: str) -> str:
    """The table row a key shares. An IPv6 address aggregates by its
    /64 — the standard allocation boundary — so distinct addresses of
    one customer share one allowance and a flood of distinct addresses
    inside one /64 fills one row, not thousands. IPv4 keys and keys
    that name no address (a session id's) stay per-key: IPv4 space is
    small and a session id is server-generated. An IPv4-mapped IPv6
    literal collapses to its IPv4 address, so the mapped and plain
    presentations of one client share a row instead of every mapped
    client sharing one giant row."""
    head, sep, tail = key.partition(":")
    if not sep or not head.endswith("-ip"):
        return key
    try:
        addr = ipaddress.ip_address(tail)
    except ValueError:
        return key
    if addr.version == 4:
        return key
    if addr.ipv4_mapped is not None:
        return f"{head}:{addr.ipv4_mapped}"
    return f"{head}:{ipaddress.ip_network(f'{tail}/64', strict=False).network_address}"


class RateLimiter:
    def __init__(
        self,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._now = now
        # key -> (the window the key was last measured under, its live
        # hit timestamps)
        self._hits: dict[str, tuple[float, list[float]]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        """One attempt against `<limit> per <window_s>` for `key`; True
        when the attempt is allowed, False when the window is spent — or
        when the limit or window is not a positive, evaluable number,
        because a limit check that fails open is not a limit."""
        if limit <= 0 or window_s <= 0:
            return False
        row = _aggregated_row(key)
        with self._lock:
            now = self._now()
            if len(self._hits) >= _MAX_RATE_KEYS:
                # The rare path: the table is at its cap, so the walk
                # runs — it first drops the rows whose newest hit is
                # already outside that row's own window, which frees
                # room without touching any live budget. The walk never
                # runs below the cap, so the common call filters its
                # own key's hits and walks nothing else.
                for other, (window, stamps) in list(self._hits.items()):
                    if other != row and stamps and now - max(stamps) >= window:
                        del self._hits[other]
            if len(self._hits) >= _MAX_RATE_KEYS and row not in self._hits:
                # The table is still full of live rows and the caller
                # has none: evict the single least-recently-active row
                # and serve the caller. A flood of distinct addresses
                # can cycle rows but can never wedge the table shut
                # against new clients; the price is the evicted key's
                # remaining allowance, which it may spend again.
                oldest = min(self._hits, key=lambda k: max(self._hits[k][1]))
                del self._hits[oldest]
            hits = [
                t for t in self._hits.get(row, (window_s, []))[1] if now - t < window_s
            ]
            if len(hits) >= limit:
                self._hits[row] = (window_s, hits)
                return False
            hits.append(now)
            self._hits[row] = (window_s, hits)
            return True
