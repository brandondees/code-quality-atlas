# SPDX-License-Identifier: MIT
"""File-backed runner ledger and single-review lock (controller-local state).

POSIX only: the lock is `fcntl.flock`, and directory fsync is not portable.
Files are created 0600 and directories 0700: runner names and the lock
are the operator's state, not anyone else's on the machine.
"""

from __future__ import annotations

import fcntl
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ReviewInProgressError(RuntimeError):
    pass


class FileLedger:
    """One runner name per line. `record` is fsynced, file and directory,
    before the caller creates anything remotely, so a crash leaves a
    sweepable trail; `clear` syncs its replacement the same way, so a
    crash mid-clear cannot leave an empty ledger. `clear` rewrites the
    file from what it read, so `record` and `clear` share one lock: lenses
    run in parallel threads, and an append landing between that read and
    the replace would drop a live runner from the record."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def record(self, name: str) -> None:
        with self._lock:
            _make_dirs_synced(self._path.parent)
            _write_synced(self._path, "a", name + "\n")
            _sync_dir(self._path.parent)

    def clear(self, name: str) -> None:
        with self._lock:
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
    """Write `text` and fsync it. The file is mode 0600 on every write,
    including when it already existed with a wider mode."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "a" else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, mode, encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def make_private_dirs(path: Path) -> tuple[Path, ...]:
    """Create `path` and each missing ancestor at 0700, outermost first,
    and return the ones created. `Path.mkdir(mode=..., parents=True)`
    applies the mode to the leaf only."""
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for created in reversed(missing):
        created.mkdir(mode=0o700, exist_ok=True)
    return tuple(reversed(missing))


def _make_dirs_synced(path: Path) -> None:
    """A new directory's entry lives in its parent, so each one created here
    is synced there too, or a crash could lose the ledger's directory."""
    for created in make_private_dirs(path):
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
    make_private_dirs(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReviewInProgressError(f"another review holds {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
