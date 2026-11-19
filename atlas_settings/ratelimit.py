# SPDX-License-Identifier: MIT
"""Simple fixed-window rate limits (D90): one counter per key — an IP
address on sign-in, a session id and an IP address on writes — inside a
sliding list of timestamps, refused past the window's allowance with a
fixed phrase. In-process state only: the limits bound one page process's
traffic, which is the surface an attacker reaches directly."""

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
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        """One attempt against `<limit> per <window_s>` for `key`; True
        when the attempt is allowed, False when the window is spent."""
        with self._lock:
            now = self._now()
            hits = [t for t in self._hits.get(key, ()) if now - t < window_s]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True
