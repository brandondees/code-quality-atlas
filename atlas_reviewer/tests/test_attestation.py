# SPDX-License-Identifier: MIT
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from atlas_reviewer.attestation import (
    ABANDONED,
    Attempt,
    AttemptLedger,
    AttemptOutcome,
    Attestation,
    Cause,
    CheckedFinding,
    LensKey,
    LensState,
    RunAttempt,
    Settled,
    ToolUse,
    body_digest,
    check_acknowledgement,
    check_delivery,
    inject_body,
    next_step,
)
from atlas_reviewer.lens_contract import (
    Attribution,
    Finding,
    LensReply,
    LineRange,
    Route,
    Severity,
    Valence,
)
from atlas_reviewer.quotes import QuoteSource

from .helpers import HEAD, FakeClock

LENS = "sweeping-for-security"
BODY = "# Sweeping for security\n\nCheck every input.\n"
DIGEST = body_digest(BODY)
KEY = LensKey("example-org/example-app", 7, HEAD, LENS, DIGEST)


def system_with(section):
    return f"controller instructions\n\n{section}\n\nfinding contract"


# ------------------------------------------------------------ delivery


def test_a_body_injected_whole_is_delivered():
    assert check_delivery(system_with(inject_body(LENS, BODY)), LENS, DIGEST)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda s: s.replace("Check every input.", "Check every input"),
        lambda s: s.replace("Check every input.\n", ""),
        lambda s: s.replace("=== lens body ends", "=== lens body ended"),
        lambda s: s.replace(LENS, "tracing-correctness-and-invariants"),
        lambda s: "controller instructions only",
    ],
    ids=["altered", "cut", "unclosed", "another-lens", "absent"],
)
def test_a_body_cut_altered_or_missing_is_not_delivered(tamper):
    sent = tamper(system_with(inject_body(LENS, BODY)))
    assert not check_delivery(sent, LENS, DIGEST)


def test_a_reply_acknowledges_only_its_own_lens_and_body():
    assert check_acknowledgement(LensReply(LENS, DIGEST, ()), LENS, DIGEST)
    assert not check_acknowledgement(LensReply("other", DIGEST, ()), LENS, DIGEST)
    assert not check_acknowledgement(LensReply(LENS, "b" * 64, ()), LENS, DIGEST)


# ------------------------------------------------------------- states


@pytest.mark.parametrize(
    ("attestation", "causes", "state", "retryable"),
    [
        (Attestation.ATTESTED, set(), LensState.CLEAN, False),
        (Attestation.ATTESTED, {Cause.QUOTES_FAILED}, LensState.PARTIAL, True),
        (Attestation.ATTESTED, {Cause.TOOL_GAP}, LensState.PARTIAL, False),
        (Attestation.ATTESTED, {Cause.NO_SOURCE_READ}, LensState.PARTIAL, False),
        (Attestation.ATTESTED, {Cause.FILES_UNREAD}, LensState.PARTIAL, False),
        (
            Attestation.UNACKNOWLEDGED,
            {Cause.UNPARSED, Cause.FILES_UNREAD},
            LensState.FAILED,
            False,
        ),
        (Attestation.MISACKNOWLEDGED, {Cause.FILES_UNREAD}, LensState.FAILED, False),
        (Attestation.UNACKNOWLEDGED, {Cause.TURN_CAP}, LensState.PARTIAL, False),
        (Attestation.UNACKNOWLEDGED, {Cause.LENS_CLOCK}, LensState.PARTIAL, False),
        (Attestation.UNACKNOWLEDGED, {Cause.UNPARSED}, LensState.FAILED, True),
        (Attestation.UNACKNOWLEDGED, {Cause.MODEL_ERROR}, LensState.FAILED, False),
        (Attestation.NOT_DELIVERED, set(), LensState.FAILED, True),
        (Attestation.MISACKNOWLEDGED, set(), LensState.FAILED, True),
        (Attestation.UNRECORDED, {Cause.ABANDONED}, LensState.FAILED, True),
    ],
)
def test_an_attempt_is_clean_only_when_attested_with_nothing_cut_short(
    attestation, causes, state, retryable
):
    outcome = AttemptOutcome(attestation, frozenset(causes))
    assert outcome.state is state
    assert outcome.retryable is retryable


def test_a_checked_finding_is_verified_or_unverified_never_both():
    f = finding()
    assert CheckedFinding(f, QuoteSource.HEAD).verified
    assert not CheckedFinding(f, problem="not found").verified
    with pytest.raises(ValueError):
        CheckedFinding(f)
    with pytest.raises(ValueError):
        CheckedFinding(f, QuoteSource.HEAD, "not found")


@pytest.mark.parametrize(
    "fields",
    [
        {"head_sha": "abc"},
        {"body_sha256": "A" * 64},
        {"lens": "../x"},
        {"lens": ""},
        {"pr_number": 0},
    ],
)
def test_a_lens_key_names_one_body_on_one_head(fields):
    values = {
        "repo": KEY.repo,
        "pr_number": KEY.pr_number,
        "head_sha": KEY.head_sha,
        "lens": KEY.lens,
        "body_sha256": KEY.body_sha256,
        **fields,
    }
    with pytest.raises(ValueError):
        LensKey(**values)


# ------------------------------------------------------------- ledger


def finding(evidence="return sum(xs)"):
    return Finding(
        LineRange("calc.py", 2, 2),
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "sums without rounding",
        "round",
        evidence,
    )


def outcome(**kw):
    base = {
        "attestation": Attestation.ATTESTED,
        "findings": (
            CheckedFinding(finding(), QuoteSource.REMOVED),
            CheckedFinding(
                finding("nowhere"), problem="the quote is not at that range"
            ),
        ),
        "tools": (ToolUse("diff_file", '{"offset": 0, "path": "calc.py"}', "ok"),),
        "turns": 3,
    }
    return AttemptOutcome(**{**base, **kw})


def ledger(tmp_path):
    return AttemptLedger(tmp_path / "state" / "attestations.jsonl", FakeClock())


def test_a_finished_attempt_reads_back_exactly(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome(causes=frozenset({Cause.TOOL_GAP})), scrub=str)
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert attempt == Attempt(1, outcome(causes=frozenset({Cause.TOOL_GAP})))


def test_a_ledger_line_from_before_the_file_gate_has_no_unread_list(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome(), scrub=str)
    lines = book.path.read_text().splitlines()
    finished = json.loads(lines[-1])
    del finished["outcome"]["unread"]
    del finished["outcome"]["changed_files"]
    lines[-1] = json.dumps(finished)
    book.path.write_text("\n".join(lines) + "\n")
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert attempt.outcome.unread == ()
    assert attempt.outcome.changed_files is None
    assert attempt.outcome.state is LensState.CLEAN


def test_a_ledger_line_with_a_bad_unread_list_is_abandoned(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome(), scrub=str)
    lines = book.path.read_text().splitlines()
    finished = json.loads(lines[-1])
    finished["outcome"]["unread"] = "calc.py"
    lines[-1] = json.dumps(finished)
    book.path.write_text("\n".join(lines) + "\n")
    again = ledger(tmp_path)
    (attempt,) = again.attempts(KEY)
    assert attempt.outcome is ABANDONED
    assert again.damaged == 1


def test_the_ledger_file_is_private_and_holds_the_key_and_head(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    assert stat.S_IMODE(book.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(book.path.parent.stat().st_mode) == 0o700
    (line,) = book.path.read_text().splitlines()
    record = json.loads(line)
    assert record["key"]["head_sha"] == HEAD
    assert record["key"]["body_sha256"] == DIGEST
    assert record["event"] == "started"


def test_writing_a_record_again_changes_nothing_and_the_first_finish_counts(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome(), scrub=str)
    book.finish(KEY, 1, outcome(attestation=Attestation.MISACKNOWLEDGED), scrub=str)
    assert len(book.path.read_text().splitlines()) == 2
    assert book.attempts(KEY) == (Attempt(1, outcome()),)


def test_a_second_finish_already_in_the_file_does_not_replace_the_first(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome(attestation=Attestation.MISACKNOWLEDGED), scrub=str)
    other = ledger(tmp_path / "other")
    other.finish(KEY, 1, outcome(), scrub=str)
    with book.path.open("a") as fh:
        fh.write(other.path.read_text())
    (attempt,) = book.attempts(KEY)
    assert attempt.outcome.attestation is Attestation.MISACKNOWLEDGED


def test_an_attempt_that_started_and_never_finished_is_abandoned(tmp_path):
    ledger(tmp_path).start(KEY, 1)
    assert ledger(tmp_path).attempts(KEY) == (Attempt(1, ABANDONED),)


def test_a_torn_last_line_is_skipped_counted_and_does_not_spoil_the_next(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    with book.path.open("a") as fh:
        fh.write('{"v": 1, "key_id": "' + KEY.id + '", "attempt": 1, "event": "fin')
    book.start(KEY, 2)
    assert book.attempts(KEY) == (Attempt(1, ABANDONED), Attempt(2, ABANDONED))
    assert book.damaged == 1


def test_a_record_from_another_version_or_shape_is_damaged_not_trusted(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    good = json.loads(book.path.read_text())
    finished = {**good, "event": "finished", "outcome": {"attestation": "ATTESTED"}}
    with book.path.open("a") as fh:
        for bad in ({**good, "v": 2}, {**good, "attempt": True}, finished):
            fh.write(json.dumps(bad) + "\n")
    assert book.attempts(KEY) == (Attempt(1, ABANDONED),)
    assert book.damaged == 3


@pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="/proc/self/fd is how this test maps an fsynced fd to a path",
)
def test_the_file_is_written_before_it_is_synced(tmp_path, monkeypatch):
    events: list[tuple[str, Path]] = []
    real_write, real_fsync = os.write, os.fsync

    def write(fd, data):
        events.append(("write", Path(os.readlink(f"/proc/self/fd/{fd}"))))
        return real_write(fd, data)

    def fsync(fd):
        events.append(("fsync", Path(os.readlink(f"/proc/self/fd/{fd}"))))
        return real_fsync(fd)

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", fsync)
    book = ledger(tmp_path)
    book.start(KEY, 1)
    file_ops = [op for op, path in events if path == book.path]
    assert file_ops.index("write") < file_ops.index("fsync")


@pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="/proc/self/fd is how this test maps an fsynced fd to a path",
)
def test_created_parent_directories_are_synced(tmp_path, monkeypatch):
    synced: list[Path] = []
    real_fsync = os.fsync

    def fsync(fd):
        synced.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    path = tmp_path / "outer" / "inner" / "attestations.jsonl"
    AttemptLedger(path, FakeClock()).start(KEY, 1)
    assert path in synced
    assert path.parent in synced
    assert path.parent.parent in synced
    assert tmp_path in synced


def test_start_and_finish_sync_the_file_and_its_directory(tmp_path, monkeypatch):
    synced = []
    real_fsync = os.fsync

    def spy(fd):
        synced.append(os.fstat(fd).st_ino)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    book = ledger(tmp_path)
    book.start(KEY, 1)
    file_ino, dir_ino = book.path.stat().st_ino, book.path.parent.stat().st_ino
    assert file_ino in synced
    assert dir_ino in synced
    synced.clear()
    book.finish(KEY, 1, outcome(), scrub=str)
    assert file_ino in synced
    assert dir_ino in synced


def test_an_unattested_attempt_read_back_through_the_ledger_is_never_clean(tmp_path):
    book = ledger(tmp_path)
    written = AttemptOutcome(
        Attestation.UNACKNOWLEDGED,
        findings=(CheckedFinding(finding(), QuoteSource.HEAD),),
    )
    book.finish(KEY, 1, written, scrub=str)
    (attempt,) = ledger(tmp_path).attempts(KEY)
    assert attempt.outcome.attestation is Attestation.UNACKNOWLEDGED
    assert attempt.outcome.state is LensState.PARTIAL
    assert attempt.outcome.findings


@pytest.mark.parametrize(
    "field",
    [
        "finding",
        "fix",
        "evidence",
        "siblings",
        "location",
        "problem",
        "detail",
        "args",
    ],
)
def test_every_text_field_is_scrubbed_before_it_reaches_the_file(tmp_path, field):
    flagged = "ghp_" + "Ab1" * 12
    found = finding()
    source: QuoteSource | None = QuoteSource.HEAD
    problem = ""
    detail = ""
    args = '{"offset": 0, "path": "calc.py"}'
    if field == "finding":
        found = replace(found, finding=f"leaks {flagged}")
    elif field == "fix":
        found = replace(found, fix=flagged)
    elif field == "evidence":
        found = replace(found, evidence=flagged)
    elif field == "siblings":
        found = replace(found, siblings=flagged)
    elif field == "location":
        found = replace(found, location=LineRange(f"{flagged}.py", 2, 2))
    elif field == "problem":
        source, problem = None, f"saw {flagged}"
    elif field == "detail":
        detail = f"saw {flagged}"
    elif field == "args":
        args = f'{{"path": "{flagged}"}}'
    checked = (
        CheckedFinding(found, source)
        if source is not None
        else CheckedFinding(found, problem=problem)
    )
    ledger(tmp_path).finish(
        KEY,
        1,
        AttemptOutcome(
            Attestation.ATTESTED,
            findings=(checked,),
            tools=(ToolUse("diff_file", args, "ok"),),
            detail=detail,
        ),
        scrub=lambda text: text.replace(flagged, "[flagged]"),
    )
    raw = (tmp_path / "state" / "attestations.jsonl").read_text()
    assert flagged not in raw
    assert "[flagged]" in raw


def test_a_findings_text_is_scrubbed_before_it_reaches_the_file(tmp_path):
    flagged = "ghp_" + "Ab1" * 12
    book = ledger(tmp_path)
    book.finish(
        KEY,
        1,
        outcome(
            findings=(
                CheckedFinding(
                    replace(finding(), finding=f"leaks {flagged}"), QuoteSource.HEAD
                ),
            ),
            detail="",
        ),
        scrub=lambda text: text.replace(flagged, "[flagged]"),
    )
    raw = book.path.read_text()
    assert flagged not in raw
    assert "[flagged]" in raw


def test_values_are_scrubbed_before_they_reach_the_file(tmp_path):
    flagged = "ghp_" + "Ab1" * 12
    book = ledger(tmp_path)
    book.finish(
        KEY,
        1,
        outcome(
            findings=(
                CheckedFinding(finding(f'token = "{flagged}"'), QuoteSource.HEAD),
            ),
            detail=f"saw {flagged}",
        ),
        scrub=lambda text: text.replace(flagged, "[flagged]"),
    )
    raw = book.path.read_text()
    assert flagged not in raw
    assert "[flagged]" in raw


def test_attempts_are_kept_per_lens_body_and_head(tmp_path):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    other_body = LensKey(KEY.repo, KEY.pr_number, KEY.head_sha, LENS, body_digest("v2"))
    other_head = LensKey(KEY.repo, KEY.pr_number, "f" * 40, LENS, DIGEST)
    assert book.attempts(other_body) == ()
    assert book.attempts(other_head) == ()


def test_attempts_are_numbered_from_one(tmp_path):
    with pytest.raises(ValueError):
        ledger(tmp_path).start(KEY, 0)


# -------------------------------------------------------- retry policy

RETRYABLE = AttemptOutcome(Attestation.MISACKNOWLEDGED)
QUOTES = AttemptOutcome(Attestation.ATTESTED, frozenset({Cause.QUOTES_FAILED}))
CLEAN = AttemptOutcome(Attestation.ATTESTED)
CUT = AttemptOutcome(Attestation.UNACKNOWLEDGED, frozenset({Cause.TURN_CAP}))


def test_the_first_attempt_runs_unforced():
    step = next_step(())
    assert step == RunAttempt(1)
    assert not step.forced


@pytest.mark.parametrize("last", [CLEAN, CUT])
def test_an_outcome_that_is_not_retryable_settles_at_once(last):
    assert next_step((Attempt(1, last),)) == Settled(last, 1, escalated=False)


@pytest.mark.parametrize("first", [RETRYABLE, QUOTES, ABANDONED])
def test_a_retryable_outcome_is_retried_once_with_the_body_forced(first):
    step = next_step((Attempt(1, first),))
    assert step == RunAttempt(2)
    assert step.forced


@pytest.mark.parametrize("second", [RETRYABLE, QUOTES, ABANDONED])
def test_a_second_retryable_outcome_escalates_and_is_never_clean(second):
    step = next_step((Attempt(1, RETRYABLE), Attempt(2, second)))
    assert step == Settled(second, 2, escalated=True)
    assert step.outcome.state in (LensState.PARTIAL, LensState.FAILED)


def test_a_retry_that_comes_back_clean_settles_clean():
    step = next_step((Attempt(1, QUOTES), Attempt(2, CLEAN)))
    assert step == Settled(CLEAN, 2, escalated=False)


def test_with_no_retries_the_first_retryable_outcome_escalates():
    assert next_step((Attempt(1, RETRYABLE),), retries=0) == Settled(RETRYABLE, 1, True)


def test_a_controller_that_crashed_mid_attempt_resumes_the_count_not_a_fresh_one(
    tmp_path,
):
    ledger(tmp_path).start(KEY, 1)
    restarted = ledger(tmp_path)
    assert next_step(restarted.attempts(KEY)) == RunAttempt(2)
    restarted.start(KEY, 2)
    again = ledger(tmp_path)
    assert next_step(again.attempts(KEY)) == Settled(ABANDONED, 2, escalated=True)


def test_a_lens_that_already_finished_is_not_run_again_for_the_same_head_and_body(
    tmp_path,
):
    book = ledger(tmp_path)
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome(), scrub=str)
    step = next_step(ledger(tmp_path).attempts(KEY))
    assert step == Settled(outcome(), 1, escalated=False)
