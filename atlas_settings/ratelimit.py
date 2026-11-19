# SPDX-License-Identifier: MIT
"""The settings page's rate limiter (D90): a sliding-window log — one
list of hit timestamps per key, each hit expiring `window_s` after it
was made, which is stricter than a fixed window (no 2x burst across a
boundary) — refusing past the window's allowance with a fixed phrase.
A window or limit that cannot be evaluated (zero or negative) refuses:
a limit check that fails open is not a limit. Each key records its own
window, and an `allow` call opportunistically drops any key whose
newest hit is older than that key's own window, so an address that
stops knocking does not linger in the table until the process restarts.
In-process state only: the limits bound one page process's traffic,
which is the surface an attacker reaches directly."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._now = now
        # key -> (the key's own window, its live hit timestamps)
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
            for other, (window, stamps) in list(self._hits.items()):
                if stamps and now - max(stamps) >= window:
                    del self._hits[other]
            stored_window, hits = self._hits.get(key, (window_s, []))
            hits = [t for t in hits if now - t < stored_window]
            if len(hits) >= limit:
                self._hits[key] = (stored_window, hits)
                return False
            hits.append(now)
            self._hits[key] = (stored_window, hits)
            return True
