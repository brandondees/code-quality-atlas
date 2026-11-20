# SPDX-License-Identifier: MIT
"""The settings page's append-only audit (D90): one JSONL line per write
the page accepted — which action, which installation, which GitHub user
id, and when. It never records a value: no key, no endpoint, no model,
no cap figure, no consent text. The file lives at
`<state dir>/settings-audit.jsonl`, outside the installation store's
directory, appended with `O_APPEND` under a thread lock — the lock serializes
this process's threads; the cross-process safety of a small append is
`O_APPEND`'s own atomicity. The file is bounded: past the byte cap the
oldest half is rotated away under the same lock, so the audit grows no
further than its cap for the life of the volume while the newest
entries — the ones the page reads back — always survive; the rotation
never touches another process's append, because this process is the
file's only writer. The page reads it back for
exactly one fact: when this installation's credentials were last saved,
which the page shows instead of a key. A line that cannot be decoded or
parsed is skipped, never fatal — one bad byte must not blind the page
to every installation's record."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

AUDIT_FILE_NAME = "settings-audit.jsonl"
# The read-back's tail window: the newest entries are the ones the page
# reads back, so the read scans at most this many bytes from the end of
# the file instead of the whole append-only history.
_AUDIT_READ_TAIL_BYTES = 65_536
ACTIONS = (
    "store-credentials",
    "record-consent",
    "revoke-credentials",
    "set-cap",
    "delete-installation",
    "login",
)
# The file's bound: past this many bytes the oldest half of the audit is
# rotated away on the next write, under the append lock.
_MAX_AUDIT_BYTES = 1_048_576

_log = logging.getLogger(__name__)


class AuditLog:
    def __init__(
        self,
        path: Path,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = path
        self._now = now
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        installation_id: str,
        github_user_id: int,
        at: datetime | None = None,
    ) -> None:
        """One append-only line. The action must be one of the known
        ones, so the audit cannot grow an unlisted shape; the values the
        write carried are not parameters here at all, which is what makes
        "never records values" structural."""
        if action not in ACTIONS:
            raise ValueError(f"unknown audit action {action!r}")
        moment = at if at is not None else self._now()
        line = (
            json.dumps(
                {
                    "at": moment.isoformat(),
                    "action": action,
                    "installation_id": installation_id,
                    "github_user_id": github_user_id,
                },
                sort_keys=True,
            )
            + "\n"
        )
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            pre_size = self._path.stat().st_size if self._path.exists() else 0
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                data = line.encode("utf-8")
                written = os.write(fd, data)
                if written < len(data):
                    # A short append leaves torn bytes that would swallow
                    # the next entry's parse: truncate them back off
                    # before raising, so the file ends where it was.
                    os.truncate(self._path, pre_size)
                    raise OSError("the audit line was not written whole")
            finally:
                os.close(fd)

    def entries(self, installation_id: str, action: str) -> list[dict[str, object]]:
        """The installation's recorded entries for one action, oldest
        first, read from a bounded tail window of the file — the newest
        entries are the ones the page reads back, and the append-only
        history is never trimmed to make the read cheaper. A file that
        cannot be read is an empty list — the page shows the record's
        own `updated_at` fallback when the audit cannot answer, never a
        wrong time — and a line that cannot be decoded or parsed is
        skipped, so one bad byte cannot blind the page to every
        installation's record."""
        try:
            size = self._path.stat().st_size
            with self._path.open("rb") as fh:
                if size > _AUDIT_READ_TAIL_BYTES:
                    fh.seek(size - _AUDIT_READ_TAIL_BYTES)
                    fh.readline()  # drop the partial line the seek lands in
                raw = fh.read()
        except FileNotFoundError:
            return []
        except OSError as exc:
            _log.warning(
                "the settings audit could not be read: %s (%s)",
                self._path,
                type(exc).__name__,
            )
            return []
        found: list[dict[str, object]] = []
        for raw_line in raw.split(b"\n"):
            try:
                line = raw_line.decode("utf-8")
                entry = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(entry, dict)
                and entry.get("installation_id") == installation_id
                and entry.get("action") == action
            ):
                found.append(entry)
        return found

    def last_credentials_at(self, installation_id: str) -> datetime | None:
        """When this installation's credentials were last saved
        (store-credentials, rotation included), from the audit; None when
        the audit has no entry — a lost audit line loses only the shown
        time, never the credential state, which the store holds. A line
        that cannot be parsed is skipped, not fatal: the timestamp is a
        display fact, and an entry that mistypes it must not erase the
        good one before it."""
        entries = self.entries(installation_id, "store-credentials")
        for entry in reversed(entries):
            raw = entry.get("at")
            if not isinstance(raw, str):
                continue
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                continue
        return None
