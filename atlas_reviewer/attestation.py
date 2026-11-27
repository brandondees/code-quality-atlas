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
is not run again for the same head and body. A settled lens keeps the
verified findings of its earlier attempts (#691): the last attempt's
outcome stands -- its attestation and causes, so a retry that still
failed is still partial or failed -- with the earlier attested attempts'
verified findings merged into it, deduplicated.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
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
from atlas_reviewer.limit_stop import LimitHit
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
    # Issue #664: a ZDR or pricing refusal the provider raised before any
    # request is a policy refusal, not a model failure, so a report can
    # tell them apart. Not retried, like a model error.
    MODEL_REFUSED = "a model call was refused"
    TRANSPORT_ERROR = "a model call failed on the transport"
    INPUT_CAP = "the per-call input cap was reached"
    OUTPUT_CAP = "the per-call output cap does not fit the model"
    REASONING_CAP = "the reasoning hint does not fit the output cap"
    CONTEXT = "the call does not fit the model's context"
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
_FAILING = frozenset(
    {
        Cause.UNPARSED,
        Cause.ABANDONED,
        Cause.MODEL_ERROR,
        Cause.MODEL_REFUSED,
        Cause.TRANSPORT_ERROR,
    }
)
_RETRYABLE_ATTESTATIONS = _FAILED_ATTESTATIONS
_RETRYABLE = frozenset(
    {Cause.UNPARSED, Cause.QUOTES_FAILED, Cause.ABANDONED, Cause.TRANSPORT_ERROR}
)


# --------------------------------------------------------------- outcomes


@dataclass(frozen=True)
class CheckedFinding:
    """A finding with its quote check: `source` when verified, `problem`
    when not. Exactly one is set. `drift` is a verified window match's
    line distance from the citation (D64), 0 otherwise."""

    finding: Finding
    source: QuoteSource | None = None
    problem: str = ""
    drift: int = 0

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
    # D80's execution counts, carried the way changed_files is: the
    # run_tests calls that came back with a run, and the mutants whose
    # verdict was survived. Zero on a ledger line from before the tools
    # existed, and on an attempt that executed nothing.
    test_runs: int = 0
    mutants_survived: int = 0
    # None when the attempt was not stopped by a configured limit.
    limit_hit: LimitHit | None = None
    # Findings left out of the reply, each naming the raw severity (D54).
    dropped: tuple[str, ...] = ()
    # The harness-injected turns this attempt answered, in order:
    # `unread-files`, `no-progress`, `duplicate-calls` (D58),
    # `quote-repair` (D64), `session-limit` (issue #693). Controller
    # labels, not model text.
    nudges: tuple[str, ...] = ()
    # The shared diff prefix's decision for this attempt (D65), controller
    # text: that the prefix was inlined and at what size, or why the diff
    # pages through `diff_file` instead. Empty when the prefix is off.
    diff_prefix: str = ""
    # The guarded-exec timeouts the timeout policy notes instead of
    # holding the lens partial (Brandon's Nov 26 decision): the names of
    # the model-chosen tools that ran past their own clock -- the draft
    # renders exactly this tuple, so the ledger carries the attestation's
    # whole truth about the note (round 1 of #867). Empty on a ledger
    # line from before the field existed.
    noted_tools: tuple[str, ...] = ()
    # The re-assessment's recorded references (D73), on a `#reassess` key's
    # outcome only: `withdrawn` is each `(prior label, stated reason)` the
    # reply withdrew, and `revises` each `(finding index from 1, prior
    # label, stated reason)` a `findings` entry revises. The labels name
    # the prior findings the re-assessment turn listed; `reassess.judge`
    # refuses a label that names none, and `reassess.effective_outcome`
    # resolves them against the effective set its replay reconstructs.
    withdrawn: tuple[tuple[str, str], ...] = ()
    revises: tuple[tuple[int, str, str], ...] = ()

    @property
    def state(self) -> LensState:
        if self.attestation in _FAILED_ATTESTATIONS or self.causes & _FAILING:
            return LensState.FAILED
        if self.attestation is not Attestation.ATTESTED or self.causes:
            return LensState.PARTIAL
        return LensState.CLEAN

    @property
    def retryable(self) -> bool:
        if Cause.FILES_UNREAD in self.causes and Cause.UNPARSED not in self.causes:
            # D42, narrowed by D58: an unread file vetoes a retry, but a
            # reply that also broke the finding contract is retried, since
            # the parse refusal is what threw the reply away.
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
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def attempts(self, key: LensKey) -> tuple[Attempt, ...]:
        with self._lock:
            return self._attempts(key)

    def _attempts(self, key: LensKey) -> tuple[Attempt, ...]:
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
        evidence_digest: str | None = None,
    ) -> None:
        """Record the finish. `evidence_digest` is the evidence snapshot
        (D73) the attempt was judged against, when the caller gathered
        one: the reuse path compares it against a later review's snapshot
        to tell newer evidence from unchanged evidence. None stores
        nothing, which reads as "cannot be shown to be current"."""
        self._append(key, attempt, "finished", outcome, scrub, evidence_digest)

    def evidence_digest(self, key: LensKey) -> str | None:
        """The evidence snapshot (D73) the key's last finished attempt was
        judged against, or None when none was recorded: a ledger line from
        before the digest was stored, a caller that passes no snapshot, or
        a re-assessment that never met the contract (its digest is
        withheld, so the next review re-runs the bounded call)."""
        with self._lock:
            found: tuple[int, str | None] | None = None
            for record in self._records():
                if record.get("key_id") != key.id or record["event"] != "finished":
                    continue
                if found is None or record["attempt"] > found[0]:
                    digest = record.get("evidence_digest")
                    found = (
                        record["attempt"],
                        digest if isinstance(digest, str) else None,
                    )
            return None if found is None else found[1]

    def _append(
        self,
        key: LensKey,
        attempt: int,
        event: str,
        outcome: AttemptOutcome | None,
        scrub: Callable[[str], str],
        evidence_digest: str | None = None,
    ) -> None:
        if attempt < 1:
            raise ValueError("attempts are numbered from 1")
        with self._lock:
            if any(_same(r, key, attempt, event) for r in self._records()):
                return
            self._write_record(key, attempt, event, outcome, scrub, evidence_digest)

    def _write_record(
        self,
        key: LensKey,
        attempt: int,
        event: str,
        outcome: AttemptOutcome | None,
        scrub: Callable[[str], str],
        evidence_digest: str | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "v": LEDGER_VERSION,
            "key_id": key.id,
            "key": _key_json(key),
            "attempt": attempt,
            "event": event,
            "at": self.clock.now().isoformat(),
        }
        if evidence_digest is not None:
            record["evidence_digest"] = evidence_digest
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
        "test_runs": outcome.test_runs,
        "mutants_survived": outcome.mutants_survived,
        "limit": _limit_json(outcome.limit_hit, scrub),
        "dropped": [scrub(note) for note in outcome.dropped],
        "nudges": [scrub(nudge) for nudge in outcome.nudges],
        "noted_tools": [scrub(name) for name in outcome.noted_tools],
        "diff_prefix": scrub(outcome.diff_prefix),
        "withdrawn": [
            [scrub(prior), scrub(reason)] for prior, reason in outcome.withdrawn
        ],
        "revises": [
            [index, scrub(prior), scrub(reason)]
            for index, prior, reason in outcome.revises
        ],
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
        "drift": checked.drift,
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
    test_runs = data.get("test_runs", 0)
    mutants_survived = data.get("mutants_survived", 0)
    for name, count in (
        ("test_runs", test_runs),
        ("mutants_survived", mutants_survived),
    ):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise TypeError(f"{name} must be a non-negative integer")
    nudges = data.get("nudges", [])
    if not isinstance(nudges, list) or not all(isinstance(n, str) for n in nudges):
        raise TypeError("nudges must be a list of strings")
    noted_tools = data.get("noted_tools", [])
    if not isinstance(noted_tools, list) or not all(
        isinstance(name, str) and name for name in noted_tools
    ):
        raise TypeError("noted_tools must be a list of non-empty strings")
    diff_prefix = data.get("diff_prefix", "")
    if not isinstance(diff_prefix, str):
        raise TypeError("diff_prefix must be a string")
    return AttemptOutcome(
        Attestation[data["attestation"]],
        frozenset(Cause[c] for c in data["causes"]),
        tuple(_checked_from(f) for f in data["findings"]),
        tuple(ToolUse(*map(_str, t)) for t in data["tools"]),
        turns,
        _str(data["detail"]),
        tuple(unread),
        changed,
        test_runs,
        mutants_survived,
        _limit_from(data.get("limit")),
        _dropped_from(data.get("dropped", ())),
        tuple(nudges),
        diff_prefix,
        tuple(noted_tools),
        _withdrawn_from(data.get("withdrawn", ())),
        _revises_from(data.get("revises", ())),
    )


def _withdrawn_from(data: object) -> tuple[tuple[str, str], ...]:
    """A recorded re-assessment's withdrawals (D73): each a
    `[prior label, reason]` pair, written back as a tuple of strings."""
    if isinstance(data, tuple):
        data = list(data)
    if not isinstance(data, list) or not all(
        isinstance(entry, list)
        and len(entry) == 2
        and all(isinstance(value, str) for value in entry)
        for entry in data
    ):
        raise TypeError("withdrawn must be a list of [prior label, reason] pairs")
    return tuple((str(prior), str(reason)) for prior, reason in data)


def _revises_from(data: object) -> tuple[tuple[int, str, str], ...]:
    """A recorded re-assessment's revisions (D73): each a
    `[finding index, prior label, reason]` triple, the index the 1-based
    position of the revising finding in the same outcome's `findings`."""
    if isinstance(data, tuple):
        data = list(data)
    if not isinstance(data, list):
        raise TypeError(
            "revises must be a list of [index, prior label, reason] triples"
        )
    refs = []
    for entry in data:
        if (
            not isinstance(entry, list)
            or len(entry) != 3
            or isinstance(entry[0], bool)
            or not isinstance(entry[0], int)
            or entry[0] < 1
            or not all(isinstance(value, str) for value in entry[1:])
        ):
            raise TypeError(
                "revises must be a list of [index, prior label, reason] triples"
            )
        refs.append((int(entry[0]), str(entry[1]), str(entry[2])))
    return tuple(refs)


def _dropped_from(data: object) -> tuple[str, ...]:
    if isinstance(data, tuple):
        data = list(data)
    if not isinstance(data, list) or not all(isinstance(note, str) for note in data):
        raise TypeError("dropped must be a list of strings")
    return tuple(data)


def _limit_json(
    found: LimitHit | None, scrub: Callable[[str], str]
) -> dict[str, str] | None:
    if found is None:
        return None
    return {key: scrub(value) for key, value in found.as_dict().items()}


def _limit_from(data: object) -> LimitHit | None:
    if data is None:
        return None
    if not isinstance(data, Mapping):
        raise TypeError("limit must be an object")
    values = {
        key: data.get(key) for key in ("limit", "configured", "observed", "setting")
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise TypeError("limit must name the limit, both values, and the setting")
    return LimitHit(
        str(values["limit"]),
        str(values["configured"]),
        str(values["observed"]),
        str(values["setting"]),
    )


def _checked_from(data: Mapping[str, Any]) -> CheckedFinding:
    source = data["source"]
    drift = data.get("drift", 0)
    if isinstance(drift, bool) or not isinstance(drift, int) or drift < 0:
        raise TypeError("drift must be a non-negative integer")
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
        drift,
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
    retryable and the retries ran out. `outcome` is the last attempt's,
    with every earlier attested attempt's verified findings merged into
    it (#691); its attestation and causes stay the last attempt's, so a
    retry that still failed is still partial or failed, never clean."""

    outcome: AttemptOutcome
    attempts: int
    escalated: bool


Step = RunAttempt | Settled


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _finding_key(finding: Finding) -> tuple[str, str, str, str, str, str]:
    """What makes two findings the same one restated: the location, the
    closed values that shape it, and the normalized finding and evidence
    text. The route and the fix are not the identity: a retry may refile
    the same issue with either changed."""
    return (
        str(finding.location),
        finding.severity.value,
        finding.valence.value,
        finding.attribution.value,
        _norm(finding.finding),
        _norm(finding.evidence),
    )


def _merged_findings(attempts: tuple[Attempt, ...]) -> tuple[CheckedFinding, ...]:
    """The last attempt's findings with the verified findings of every
    earlier attested attempt kept and merged in, deduplicated (#691). The
    retry's reply is the one that counts: a finding it restates stays its
    copy, at its own place in the order. An earlier verified finding the
    retry could not verify replaces the retry's unverified copy at the
    same citation. An earlier verified finding the retry does not restate
    is appended. Only verified findings are carried forward, and only
    from an attested attempt; the last attempt's own duplicates are kept
    as its reply reported them."""
    last = attempts[-1].outcome
    if len(attempts) == 1:
        return last.findings
    merged = list(last.findings)
    for attempt in attempts[:-1]:
        if attempt.outcome.attestation is not Attestation.ATTESTED:
            continue
        for checked in attempt.outcome.findings:
            if not checked.verified:
                continue
            key = _finding_key(checked.finding)
            for i, held in enumerate(merged):
                if _finding_key(held.finding) == key:
                    if not held.verified:
                        merged[i] = checked
                    break
            else:
                merged.append(checked)
    return tuple(merged)


def next_step(attempts: tuple[Attempt, ...], retries: int = RETRIES) -> Step:
    """From the ledger alone: run the first attempt; after a retryable
    outcome, run another while fewer than `1 + retries` were made; else
    the last outcome stands with the earlier verified findings merged in
    (#691): the retry re-verifies or replaces what failed, it does not
    throw away what was already verified."""
    if not attempts:
        return RunAttempt(1)
    last = attempts[-1].outcome
    if not last.retryable:
        return Settled(
            replace(last, findings=_merged_findings(attempts)), len(attempts),
            escalated=False,
        )  # fmt: skip
    if len(attempts) >= 1 + retries:
        return Settled(
            replace(last, findings=_merged_findings(attempts)), len(attempts),
            escalated=True,
        )  # fmt: skip
    return RunAttempt(attempts[-1].number + 1)
