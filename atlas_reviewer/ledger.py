# SPDX-License-Identifier: MIT
"""File-backed runner ledger and single-review lock (controller-local state)."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ReviewInProgressError(RuntimeError):
    pass


class FileLedger:
    """One runner name per line. `record` is fsynced before the caller
    creates anything remotely, so a crash leaves a sweepable trail."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, name: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(name + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def clear(self, name: str) -> None:
        remaining = [n for n in self.pending() if n != name]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text("".join(n + "\n" for n in remaining), encoding="utf-8")
        tmp.replace(self._path)

    def pending(self) -> tuple[str, ...]:
        if not self._path.exists():
            return ()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return tuple(dict.fromkeys(n.strip() for n in lines if n.strip()))


@contextmanager
def single_review_lock(path: Path) -> Iterator[None]:
    """One review at a time per state directory (operator-funded runs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReviewInProgressError(f"another review holds {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
