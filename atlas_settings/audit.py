# SPDX-License-Identifier: MIT
"""The settings page's append-only audit (D90): one JSONL line per write
the page accepted — which action, which installation, which GitHub user
id, and when. It never records a value: no key, no endpoint, no model,
no cap figure, no consent text. The file lives at
`<state dir>/settings-audit.jsonl`, outside the installation store's
directory, appended with `O_APPEND` under a process lock (small lines
append atomically; the store's per-record `flock` covers the records
themselves). The page reads it back for exactly one fact: when this
installation's credentials were last saved, which the page shows instead
of a key."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

AUDIT_FILE_NAME = "settings-audit.jsonl"
ACTIONS = (
    "store-credentials",
    "record-consent",
    "revoke-credentials",
    "set-cap",
    "delete-installation",
    "login",
)


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
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)

    def entries(self, installation_id: str, action: str) -> list[dict[str, object]]:
        """The installation's recorded entries for one action, oldest
        last. A file that cannot be read is an empty list — the page
        shows the record's own `updated_at` fallback when the audit
        cannot answer, never a wrong time."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            return []
        found: list[dict[str, object]] = []
        for line in raw.splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
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
