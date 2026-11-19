# SPDX-License-Identifier: MIT
"""The settings page's rate limiter (D90): a sliding-window log — one
list of hit timestamps per key, each hit expiring `window_s` after it
was made, which is stricter than a fixed window (no 2x burst across a
boundary) — refusing past the window's allowance with a fixed phrase.
A window or limit that cannot be evaluated (zero or negative) refuses:
a limit check that fails open is not a limit. The attempt is measured
against this call's `window_s`, and the key remembers the last window
it was measured under, which is what the eviction sweep reads. The
table is bounded: past the key cap the oldest key is evicted, and the
full-table sweep runs only on that rare path — the common call filters
its own key's hits and walks nothing else, so the work per call is
bounded by that key's hit list, not by the table. In-process state
only: the limits bound one page process's traffic, which is the surface
an attacker reaches directly."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# The key table's bound: past it the oldest key (the one whose newest
# hit is furthest back) is evicted on the next call, and the one full
# sweep that eviction needs runs then — a burst of distinct addresses
# costs bounded memory and bounded per-call work, not an unbounded walk.
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
                # runs — the stale keys drop first, and any that still
                # fill the table give up the oldest (the key whose
                # newest hit is furthest back). The walk never runs
                # below the cap, so the common call filters its own
                # key's hits and walks nothing else.
                for other, (window, stamps) in list(self._hits.items()):
                    if not stamps or now - max(stamps) >= window:
                        del self._hits[other]
                while len(self._hits) >= _MAX_RATE_KEYS:
                    oldest = min(self._hits, key=lambda k: max(self._hits[k][1]))
                    del self._hits[oldest]
            hits = [
                t for t in self._hits.get(key, (window_s, []))[1] if now - t < window_s
            ]
            if len(hits) >= limit:
                self._hits[key] = (window_s, hits)
                return False
            hits.append(now)
            self._hits[key] = (window_s, hits)
            return True
