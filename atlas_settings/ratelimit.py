# SPDX-License-Identifier: MIT
"""The settings page's rate limiter (D90): a sliding-window log — one
list of hit timestamps per key, each hit expiring `window_s` after it
was made, which is stricter than a fixed window (no 2x burst across a
boundary) — refusing past the window's allowance with a fixed phrase.
A window or limit that cannot be evaluated (zero or negative) refuses:
a limit check that fails open is not a limit. The attempt is measured
against this call's `window_s`, and the key remembers the last window
it was measured under, which is what the at-cap walk reads. The table
is bounded, and the bound never spends a live budget: past the key cap
the walk drops only keys whose newest hit is already outside their own
window, the caller's own row is never dropped, and a new key arriving
at a table full of in-window keys is **refused** rather than evicting
someone's allowance — the accepted tradeoff (D90's rate limits are the
first line, the refusal is fail-closed and expires with the window, and
the sign-in route's per-client limiter bounds how fast one address can
fill the table). The walk runs only on that rare path — the common
call filters its own key's hits and walks nothing else, so the work per
call is bounded by that key's hit list, not by the table. In-process
state only: the limits bound one page process's traffic, which is the
surface an attacker reaches directly."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# The key table's bound: past it the walk drops only keys whose newest
# hit is outside their own window (a live key's hit log is its budget
# and is never deleted), and a new key at a table full of in-window keys
# is refused — the accepted lockout tradeoff, bounded by the window.
_MAX_RATE_KEYS = 4096


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
        with self._lock:
            now = self._now()
            if len(self._hits) >= _MAX_RATE_KEYS:
                # The rare path: the table is at its cap, so the walk
                # runs — but it drops only keys whose newest hit is
                # already outside that key's own window. A live key's
                # hit log is its budget; deleting it would hand the
                # caller a fresh allowance, so a key inside its window
                # is never deleted, whatever pressure the table is
                # under. The walk never runs below the cap, so the
                # common call filters its own key's hits and walks
                # nothing else.
                for other, (window, stamps) in list(self._hits.items()):
                    if other != key and stamps and now - max(stamps) >= window:
                        del self._hits[other]
                if len(self._hits) >= _MAX_RATE_KEYS and key not in self._hits:
                    # The table is full of in-window keys and the caller
                    # has no row of its own: refuse, rather than delete
                    # someone's live budget to make room.
                    return False
            hits = [
                t for t in self._hits.get(key, (window_s, []))[1] if now - t < window_s
            ]
            if len(hits) >= limit:
                self._hits[key] = (window_s, hits)
                return False
            hits.append(now)
            self._hits[key] = (window_s, hits)
            return True
