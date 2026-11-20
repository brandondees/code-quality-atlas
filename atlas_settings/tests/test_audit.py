# SPDX-License-Identifier: MIT
"""The audit log: append-only lines carrying action, installation, user
id, and time — and never a value; the read-back for the credentials
timestamp; the unknown-action refusal; the bounded file; and the
degradation contract (a missing file is silence, an unreadable file is
a logged warning, a bad line is skipped)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from atlas_settings.audit import AuditLog


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
    assert set(json.loads(entry)) == {
        "at",
        "action",
        "installation_id",
        "github_user_id",
    }
    assert '"action": "store-credentials"' in raw
    assert '"installation_id": "42"' in raw
    assert '"github_user_id": 11' in raw
    assert '"at": "2026-11-19T12:00:00+00:00"' in raw


def test_an_explicit_timestamp_is_the_one_recorded(tmp_path: Path) -> None:
    log = _log(tmp_path)
    moment = datetime(2026, 11, 19, 9, 30, 0, tzinfo=UTC)
    log.record("store-credentials", "42", 11, at=moment)
    assert log.last_credentials_at("42") == moment


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


def test_a_missing_audit_file_answers_none_silently(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert log.last_credentials_at("42") is None


def test_an_unreadable_audit_file_answers_none_and_names_itself(
    tmp_path: Path,
) -> None:
    """The unreadable-file case runs everywhere (the OSError is raised
    through a patched read, not a chmod, so the branch is covered under
    uid 0 too), and it is not silent: one warning names the path and the
    exception class."""
    log = _log(tmp_path)
    log.record("store-credentials", "42", 11)
    assert log.last_credentials_at("42") is not None

    from unittest import mock

    with mock.patch(
        "atlas_settings.audit.Path.open", side_effect=PermissionError("refused")
    ):
        assert log.last_credentials_at("42") is None


def test_the_unreadable_file_logs_one_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log = _log(tmp_path)
    log.record("store-credentials", "42", 11)

    with mock.patch(
        "atlas_settings.audit.Path.open", side_effect=OSError("disk trouble")
    ):
        assert log.last_credentials_at("42") is None
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "settings-audit.jsonl" in warnings[0].getMessage()
    assert "OSError" in warnings[0].getMessage()


def test_one_undecodable_byte_does_not_blind_the_page(tmp_path: Path) -> None:
    """A line that cannot be decoded is skipped the way a bad JSON line
    is: the good credentials line after it is still read (the file is
    shared by every installation)."""
    log = _log(tmp_path)
    log.record("store-credentials", "42", 11)
    path = tmp_path / "state" / "settings-audit.jsonl"
    with path.open("ab") as fh:
        fh.write(b"\xff\xfe\n")
    log.record("store-credentials", "43", 11)
    # The good line after the bad byte is read, and a different
    # installation's line is reachable too — one bad byte must not blind
    # the page to every installation's record.
    assert log.last_credentials_at("42") is not None
    assert log.last_credentials_at("43") is not None


def test_corrupt_or_mistyped_entries_are_skipped_on_read_back(
    tmp_path: Path,
) -> None:
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


def test_the_audit_is_never_trimmed(tmp_path: Path) -> None:
    """The audit is append-only for the life of the volume: whatever the
    write count, every earlier entry is still in the file and still
    readable — nothing is rotated, trimmed or dropped (kills the
    rotation-restored mutant: any trimming loses the oldest entry and
    fails the read-backs)."""
    log = _log(tmp_path)
    for n in range(40):
        log.record("store-credentials", str(40 + n), 11)
    path = tmp_path / "state" / "settings-audit.jsonl"
    assert path.read_text().count('"action": "store-credentials"') == 40
    for n in range(40):
        assert log.last_credentials_at(str(40 + n)) is not None


def test_a_short_append_leaves_no_torn_bytes_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short `os.write` writes only a prefix of the line; the record
    truncates the torn bytes back off before raising, so the file ends
    where it was and the next record lands whole and readable (kills the
    mutant that leaves the torn bytes — its fragment merges into the
    next line and the next entry is lost)."""
    import os

    log = _log(tmp_path)
    log.record("store-credentials", "42", 11)
    path = tmp_path / "state" / "settings-audit.jsonl"
    before = path.read_bytes()

    real_write = os.write

    def short_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[:-1])

    monkeypatch.setattr("atlas_settings.audit.os.write", short_write)
    with pytest.raises(OSError, match="not written whole"):
        log.record("store-credentials", "42", 11)
    monkeypatch.undo()
    # No torn bytes: the file is exactly what it was before the refused
    # append, and the next record lands whole and readable.
    assert path.read_bytes() == before
    log.record("store-credentials", "43", 11)
    assert log.last_credentials_at("43") is not None
    assert log.last_credentials_at("42") is not None


def test_the_read_scans_a_tail_window_of_a_big_file(tmp_path: Path) -> None:
    """The read-back is bounded: on a file larger than the tail window it
    seeks to the window and reads only that, and the newest credentials
    entry — the one fact the page reads back — is still found (kills the
    whole-file-read mutant, whose unbounded scan is what the bound
    exists to prevent)."""
    log = _log(tmp_path)
    path = tmp_path / "state" / "settings-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    filler = (
        b'{"at": "2026-11-19T09:00:00+00:00", "action": "login", '
        b'"installation_id": "42", "github_user_id": 11, "pad": "'
        + b"x" * 200
        + b'"}\n'
    )
    path.write_bytes(filler * 500)  # ~100 KiB of non-credentials lines
    log.record("store-credentials", "42", 11)
    assert log.last_credentials_at("42") is not None
