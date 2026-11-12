# SPDX-License-Identifier: MIT
"""Lens-body attestation and the durable attempt ledger (D34 (2), D31).

A lens counts as run on a head SHA only when the controller can show, for
one body identified by its SHA-256:

- **delivery**: the system prompt handed to the model port carries the
  whole body between the controller's markers, and the text between them
  hashes to that digest (`check_delivery`);
- **acknowledgement**: the lens's final reply names that lens and that
  digest (`check_acknowledgement`).

Each attempt is written to `AttemptLedger` when it starts, before its first
model call, and again when it ends, with its attestation, what cut it
short, and its checked findings. The retry policy (`next_step`) reads only
the ledger: an attempt that started and never finished is abandoned, and
counts as used, so a crashed or restarted controller resumes the same
attempt count instead of starting over, and a lens that already finished
is not run again for the same head and body.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from atlas_reviewer.domain import PrEvent
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.lens_contract import (
    DIGEST,
    Attribution,
    ContractError,
    Finding,
    LensReply,
    Route,
    Severity,
    Valence,
    parse_location,
)
from atlas_reviewer.ports import Clock
from atlas_reviewer.quotes import QuoteSource

LEDGER_VERSION = 1
RETRIES = 1


def body_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ------------------------------------------------------------ attestation


def body_markers(lens: str, digest: str) -> tuple[str, str]:
    """The lines the controller writes around an injected lens body."""
    return (
        f"=== lens body begins: {lens} (sha256 {digest}) ===",
        f"=== lens body ends: {lens} (sha256 {digest}) ===",
    )


def inject_body(lens: str, body: str) -> str:
    """The whole body between its markers. Nothing is cut."""
    begin, end = body_markers(lens, body_digest(body))
    return f"{begin}\n{body}\n{end}"


def check_delivery(system: str, lens: str, digest: str) -> bool:
    """Whether `system` carries, between this lens's markers, text whose
    SHA-256 is `digest`: the whole body, unaltered."""
    begin, end = body_markers(lens, digest)
    _, opened, rest = system.partition(f"{begin}\n")
    body, closed, _ = rest.partition(f"\n{end}")
    return bool(opened and closed) and body_digest(body) == digest


def check_acknowledgement(reply: LensReply, lens: str, digest: str) -> bool:
    return reply.lens == lens and reply.body_sha256 == digest


class Attestation(StrEnum):
    ATTESTED = "attested"
    UNACKNOWLEDGED = "body delivered; no final reply acknowledged it"
    NOT_DELIVERED = "body not delivered whole"
    MISACKNOWLEDGED = "the reply named another lens or body"
    UNRECORDED = "not recorded: the attempt never finished"


class Cause(StrEnum):
    """What kept an attempt from being clean. The values are controller
    text, shown in the draft."""

    UNPARSED = "the reply did not meet the finding contract"
    QUOTES_FAILED = "a finding's quote was not found at the head SHA"
    ABANDONED = "the attempt never finished (the controller stopped mid-attempt)"
    MODEL_ERROR = "a model call failed"
    TURN_CAP = "the per-lens turn cap was reached"
    CALL_CAP = "the review's model-call cap was reached"
    BUDGET = "the review's dollar reservation was reached"
    LENS_CLOCK = "the per-lens wall clock ran out"
    REVIEW_CLOCK = "the review wall clock ran out"
    TOOL_GAP = "a tool call timed out, was unavailable or hit a session limit"
    NO_SOURCE_READ = "no findings, and no diff page or changed file was read"
    FILES_UNREAD = "a changed file's diff was not read in full"


class LensState(StrEnum):
    """`CLEAN`: attested, finished, and every check passed (it may still
    have findings). `PARTIAL`: it ran with its body but something cut it
    short. `FAILED`: it cannot be shown to have run its body, or its
    output was unusable. `NOT_RUN`: no attempt was made."""

    CLEAN = "clean"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_RUN = "NOT RUN"


_FAILED_ATTESTATIONS = frozenset(
    {Attestation.NOT_DELIVERED, Attestation.MISACKNOWLEDGED, Attestation.UNRECORDED}
)
_FAILING = frozenset({Cause.UNPARSED, Cause.ABANDONED, Cause.MODEL_ERROR})
_RETRYABLE_ATTESTATIONS = _FAILED_ATTESTATIONS
_RETRYABLE = frozenset({Cause.UNPARSED, Cause.QUOTES_FAILED, Cause.ABANDONED})


# --------------------------------------------------------------- outcomes


@dataclass(frozen=True)
class CheckedFinding:
    """A finding with its quote check: `source` when verified, `problem`
    when not. Exactly one is set."""

    finding: Finding
    source: QuoteSource | None = None
    problem: str = ""

    def __post_init__(self) -> None:
        if (self.source is None) == (not self.problem):
            raise ValueError("a checked finding is verified or unverified, not both")

    @property
    def verified(self) -> bool:
        return self.source is not None


@dataclass(frozen=True)
class ToolUse:
    """One bridge call as the ledger keeps it: no content."""

    tool: str
    args: str
    status: str


@dataclass(frozen=True)
class AttemptOutcome:
    attestation: Attestation
    causes: frozenset[Cause] = frozenset()
    findings: tuple[CheckedFinding, ...] = ()
    tools: tuple[ToolUse, ...] = ()
    turns: int = 0
    detail: str = ""
    unread: tuple[str, ...] = ()
    # None on a ledger line from before the per-file gate recorded a count.
    changed_files: int | None = None

    @property
    def state(self) -> LensState:
        if self.attestation in _FAILED_ATTESTATIONS or self.causes & _FAILING:
            return LensState.FAILED
        if self.attestation is not Attestation.ATTESTED or self.causes:
            return LensState.PARTIAL
        return LensState.CLEAN

    @property
    def retryable(self) -> bool:
        if Cause.FILES_UNREAD in self.causes:
            return False
        return bool(
            self.attestation in _RETRYABLE_ATTESTATIONS or self.causes & _RETRYABLE
        )


ABANDONED = AttemptOutcome(Attestation.UNRECORDED, frozenset({Cause.ABANDONED}))


# ------------------------------------------------------------- the ledger


@dataclass(frozen=True)
class LensKey:
    """One lens body on one PR head: what an attestation is about."""

    repo: str
    pr_number: int
    head_sha: str
    lens: str
    body_sha256: str

    def __post_init__(self) -> None:
        PrEvent(self.repo, self.pr_number, self.head_sha)
        if not DIGEST.fullmatch(self.body_sha256):
            raise ValueError("body_sha256 must be 64 lowercase hex characters")
        if not self.lens or any(c in self.lens for c in "/\n\0"):
            raise ValueError("lens must be a lens name")

    @property
    def id(self) -> str:
        canonical = json.dumps(_key_json(self), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Attempt:
    number: int
    outcome: AttemptOutcome


@dataclass
class AttemptLedger:
    """Append-only JSON lines, one per event, each fsynced before the call
    returns. A record is identified by key, attempt and event, so writing
    it again is a no-op and the first finish of an attempt is the one that
    counts. A line that does not parse (a write torn by a crash) is
    skipped and counted in `damaged`; the attempt it would have finished
    then reads as abandoned, which fails closed. Values written are passed
    through `scrub` first, so flagged secrets never reach the file."""

    path: Path
    clock: Clock
    damaged: int = field(default=0, init=False)

    def attempts(self, key: LensKey) -> tuple[Attempt, ...]:
        started: dict[int, AttemptOutcome] = {}
        for record in self._records():
            if record.get("key_id") != key.id:
                continue
            number = record["attempt"]
            if record["event"] == "started":
                started.setdefault(number, ABANDONED)
            elif started.get(number, ABANDONED) is ABANDONED:
                started[number] = record["outcome"]
        return tuple(Attempt(n, started[n]) for n in sorted(started))

    def start(self, key: LensKey, attempt: int) -> None:
        self._append(key, attempt, "started", None, str)

    def finish(
        self,
        key: LensKey,
        attempt: int,
        outcome: AttemptOutcome,
        *,
        scrub: Callable[[str], str],
    ) -> None:
        self._append(key, attempt, "finished", outcome, scrub)

    def _append(
        self,
        key: LensKey,
        attempt: int,
        event: str,
        outcome: AttemptOutcome | None,
        scrub: Callable[[str], str],
    ) -> None:
        if attempt < 1:
            raise ValueError("attempts are numbered from 1")
        if any(_same(r, key, attempt, event) for r in self._records()):
            return
        record: dict[str, Any] = {
            "v": LEDGER_VERSION,
            "key_id": key.id,
            "key": _key_json(key),
            "attempt": attempt,
            "event": event,
            "at": self.clock.now().isoformat(),
        }
        if outcome is not None:
            record["outcome"] = _outcome_json(outcome, scrub)
        self._write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")

    def _write(self, line: str) -> None:
        created = make_private_dirs(self.path.parent)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            size = os.fstat(fd).st_size
            torn = size > 0 and os.pread(fd, 1, size - 1) != b"\n"
            os.write(fd, (("\n" if torn else "") + line).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        for directory in (self.path.parent, *(c.parent for c in created)):
            _sync_dir(directory)

    def _records(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return ()
        records, damaged = [], 0
        for line in self.path.read_bytes().split(b"\n"):
            if not line:
                continue
            record = _parse_record(line)
            if record is None:
                damaged += 1
            else:
                records.append(record)
        self.damaged = damaged
        return records


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _same(record: Mapping[str, Any], key: LensKey, attempt: int, event: str) -> bool:
    return (
        record.get("key_id") == key.id
        and record["attempt"] == attempt
        and record["event"] == event
    )


def _key_json(key: LensKey) -> dict[str, Any]:
    return {
        "repo": key.repo,
        "pr_number": key.pr_number,
        "head_sha": key.head_sha,
        "lens": key.lens,
        "body_sha256": key.body_sha256,
    }


def _parse_record(line: bytes) -> dict[str, Any] | None:
    """A ledger line as written by this version, or None."""
    try:
        data = json.loads(line)
        if not isinstance(data, dict) or data.get("v") != LEDGER_VERSION:
            return None
        attempt, event = data["attempt"], data["event"]
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            return None
        if not isinstance(data["key_id"], str) or event not in ("started", "finished"):
            return None
        if event == "finished":
            data["outcome"] = _outcome_from(data["outcome"])
        return data
    except (ValueError, KeyError, TypeError, ContractError):
        return None


def _outcome_json(
    outcome: AttemptOutcome, scrub: Callable[[str], str]
) -> dict[str, Any]:
    return {
        "attestation": outcome.attestation.name,
        "causes": sorted(c.name for c in outcome.causes),
        "findings": [_checked_json(c, scrub) for c in outcome.findings],
        "tools": [[t.tool, scrub(t.args), t.status] for t in outcome.tools],
        "turns": outcome.turns,
        "detail": scrub(outcome.detail),
        "unread": [scrub(path) for path in outcome.unread],
        "changed_files": outcome.changed_files,
    }


def _checked_json(
    checked: CheckedFinding, scrub: Callable[[str], str]
) -> dict[str, Any]:
    f = checked.finding
    return {
        "location": scrub(str(f.location)),
        "severity": f.severity.value,
        "valence": f.valence.value,
        "route": f.route.value,
        "attribution": f.attribution.value,
        "finding": scrub(f.finding),
        "fix": scrub(f.fix),
        "evidence": scrub(f.evidence),
        "siblings": scrub(f.siblings),
        "source": None if checked.source is None else checked.source.name,
        "problem": scrub(checked.problem),
    }


def _outcome_from(data: Mapping[str, Any]) -> AttemptOutcome:
    turns = data["turns"]
    if isinstance(turns, bool) or not isinstance(turns, int):
        raise TypeError("turns must be an integer")
    unread = data.get("unread", [])
    if not isinstance(unread, list) or not all(
        isinstance(path, str) for path in unread
    ):
        raise TypeError("unread must be a list of strings")
    changed = data.get("changed_files", None)
    if changed is not None and (
        isinstance(changed, bool) or not isinstance(changed, int)
    ):
        raise TypeError("changed_files must be an integer")
    if isinstance(changed, int) and changed < 0:
        raise TypeError("changed_files must be an integer")
    return AttemptOutcome(
        Attestation[data["attestation"]],
        frozenset(Cause[c] for c in data["causes"]),
        tuple(_checked_from(f) for f in data["findings"]),
        tuple(ToolUse(*map(_str, t)) for t in data["tools"]),
        turns,
        _str(data["detail"]),
        tuple(unread),
        changed,
    )


def _checked_from(data: Mapping[str, Any]) -> CheckedFinding:
    source = data["source"]
    return CheckedFinding(
        Finding(
            parse_location(_str(data["location"])),
            Severity(data["severity"]),
            Valence(data["valence"]),
            Route(data["route"]),
            Attribution(data["attribution"]),
            _str(data["finding"]),
            _str(data["fix"]),
            _str(data["evidence"]),
            _str(data["siblings"]),
        ),
        None if source is None else QuoteSource[source],
        _str(data["problem"]),
    )


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


# --------------------------------------------------------- retry policy


@dataclass(frozen=True)
class RunAttempt:
    """Run attempt `number`; `forced` means a retry with the body forced."""

    number: int

    @property
    def forced(self) -> bool:
        return self.number > 1


@dataclass(frozen=True)
class Settled:
    """No attempt is left to run. `escalated` means the last attempt was
    retryable and the retries ran out, so its outcome stands as partial
    or failed."""

    outcome: AttemptOutcome
    attempts: int
    escalated: bool


Step = RunAttempt | Settled


def next_step(attempts: tuple[Attempt, ...], retries: int = RETRIES) -> Step:
    """From the ledger alone: run the first attempt; after a retryable
    outcome, run another while fewer than `1 + retries` were made; else
    the last outcome stands."""
    if not attempts:
        return RunAttempt(1)
    last = attempts[-1].outcome
    if not last.retryable:
        return Settled(last, len(attempts), escalated=False)
    if len(attempts) >= 1 + retries:
        return Settled(last, len(attempts), escalated=True)
    return RunAttempt(attempts[-1].number + 1)
