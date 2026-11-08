# SPDX-License-Identifier: MIT
"""File-backed runner ledger and single-review lock (controller-local state).

POSIX only: the lock is `fcntl.flock`, and directory fsync is not portable.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ReviewInProgressError(RuntimeError):
    pass


class FileLedger:
    """One runner name per line. `record` is fsynced, file and directory,
    before the caller creates anything remotely, so a crash leaves a
    sweepable trail; `clear` syncs its replacement the same way, so a
    crash mid-clear cannot leave an empty ledger."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, name: str) -> None:
        _make_dirs_synced(self._path.parent)
        _write_synced(self._path, "a", name + "\n")
        _sync_dir(self._path.parent)

    def clear(self, name: str) -> None:
        remaining = [n for n in self.pending() if n != name]
        tmp = self._path.with_name(self._path.name + ".clearing")
        _write_synced(tmp, "w", "".join(n + "\n" for n in remaining))
        tmp.replace(self._path)
        _sync_dir(self._path.parent)

    def pending(self) -> tuple[str, ...]:
        if not self._path.exists():
            return ()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return tuple(dict.fromkeys(n.strip() for n in lines if n.strip()))


def _write_synced(path: Path, mode: str, text: str) -> None:
    with path.open(mode, encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def _make_dirs_synced(path: Path) -> None:
    """A new directory's entry lives in its parent, so each one created here
    is synced there too, or a crash could lose the ledger's directory."""
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for created in reversed(missing):
        created.mkdir(exist_ok=True)
        _sync_dir(created.parent)


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
