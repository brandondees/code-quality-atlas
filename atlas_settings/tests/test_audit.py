# SPDX-License-Identifier: MIT
"""The audit log: append-only lines carrying action, installation, user
id, and time — and never a value; the read-back for the credentials
timestamp; the unknown-action refusal."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from atlas_settings.audit import ACTIONS, AuditLog


def _log(tmp_path: Path) -> AuditLog:
    moment = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
    return AuditLog(tmp_path / "state" / "settings-audit.jsonl", lambda: moment)


def test_a_recorded_write_carries_no_value(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.record("store-credentials", "42", 11)
    raw = (tmp_path / "state" / "settings-audit.jsonl").read_text()
    entry = raw.splitlines()[0]
    # The line's shape: time, action, installation, user id — nothing
    # else, and no key, endpoint, model or cap figure could be present
    # because `record` takes none of them.
    parsed = raw
    assert '"action": "store-credentials"' in parsed
    assert '"installation_id": "42"' in parsed
    assert '"github_user_id": 11' in parsed
    assert '"at": "2026-11-19T12:00:00+00:00"' in parsed
    assert entry.count(",") == 3


def test_an_unknown_action_refuses() -> None:
    log = _log(Path("/tmp/unused-audit"))
    with pytest.raises(ValueError, match="unknown audit action"):
        log.record("not-an-action", "42", 11)


def test_the_credentials_timestamp_comes_from_the_last_save(
    tmp_path: Path,
) -> None:
    moments = iter(
        [
            datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC),
            datetime(2026, 11, 19, 13, 0, 0, tzinfo=UTC),
        ]
    )
    log = AuditLog(
        tmp_path / "state" / "settings-audit.jsonl",
        lambda: next(moments),
    )
    log.record("store-credentials", "42", 11)
    log.record("store-credentials", "42", 11)
    assert log.last_credentials_at("42") == datetime(2026, 11, 19, 13, 0, 0, tzinfo=UTC)


def test_other_actions_do_not_answer_the_credentials_timestamp(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    log.record("set-cap", "42", 11)
    assert log.last_credentials_at("42") is None


def test_a_missing_or_unreadable_audit_file_answers_none(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert log.last_credentials_at("42") is None
    log.record("store-credentials", "42", 11)
    path = tmp_path / "state" / "settings-audit.jsonl"
    path.chmod(0o000)
    try:
        import os

        if os.geteuid() == 0:  # root reads anything; skip the unreadable case
            return
        assert log.last_credentials_at("42") is None
    finally:
        path.chmod(0o600)


def test_every_action_name_is_listed() -> None:
    assert set(ACTIONS) == {
        "store-credentials",
        "record-consent",
        "revoke-credentials",
        "set-cap",
        "delete-installation",
        "login",
    }


def test_corrupt_or_mistyped_entries_are_skipped_on_read_back(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime

    path = tmp_path / "state" / "settings-audit.jsonl"
    log = AuditLog(path, lambda: datetime(2026, 11, 19, 12, 0, tzinfo=UTC))
    log.record("store-credentials", "42", 11)
    with path.open("a") as fh:
        fh.write("not json\n")
        fh.write(
            json.dumps(
                {
                    "at": 12,
                    "installation_id": "42",
                    "action": "store-credentials",
                    "github_user_id": 11,
                }
            )
            + "\n"
        )
        fh.write(
            json.dumps(
                {
                    "at": "not-a-time",
                    "installation_id": "42",
                    "action": "store-credentials",
                    "github_user_id": 11,
                }
            )
            + "\n"
        )
    assert log.last_credentials_at("42") == datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
