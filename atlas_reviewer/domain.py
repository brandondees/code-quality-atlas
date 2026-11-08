# SPDX-License-Identifier: MIT
"""Closed domain types for one manual review. Pure: no I/O.

Evidence is a tagged union of exactly three shapes (`Matched`, `Stale`,
`Missing`). Only `Matched` evidence can ever produce a PASS or FAIL;
everything else is UNKNOWN by construction, so "no evidence" can never be
read as "passed".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from atlas_reviewer.redact import RedactedText

_SHA = re.compile(r"[0-9a-f]{40}")
# `.` and `..` would be path traversal once the name is put into an API path.
_REPO = re.compile(r"(?!\.\.?/)[A-Za-z0-9_.-]+/(?!\.\.?$)[A-Za-z0-9_.-]+")

UNREPORTED_VERSION = "unreported"


class InvalidEventError(ValueError):
    """A PR event that cannot name one exact commit of one PR."""


@dataclass(frozen=True)
class PrEvent:
    repo: str
    pr_number: int
    head_sha: str

    def __post_init__(self) -> None:
        if not isinstance(self.repo, str) or not _REPO.fullmatch(self.repo):
            raise InvalidEventError(f"repo must be owner/name, got {self.repo!r}")
        if isinstance(self.pr_number, bool) or not isinstance(self.pr_number, int):
            raise InvalidEventError("pr_number must be an integer")
        if self.pr_number < 1:
            raise InvalidEventError("pr_number must be positive")
        if not isinstance(self.head_sha, str) or not _SHA.fullmatch(self.head_sha):
            raise InvalidEventError("head_sha must be a full 40-hex commit SHA")


class SourceKind(Enum):
    CHECK_RUN = "check_run"
    WORKFLOW_RUN = "workflow_run"
    JOB = "job"
    WORKFLOW_LOG = "workflow_log"
    ARTIFACT = "artifact"
    RUNNER_TOOL = "runner_tool"


@dataclass(frozen=True)
class SourceKey:
    """What a piece of evidence is *about*, independent of which commit."""

    kind: SourceKind
    name: str


@dataclass(frozen=True)
class Provenance:
    key: SourceKey
    source_id: str


@dataclass(frozen=True)
class ToolInfo:
    name: str
    version: str


class Conclusion(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    NEUTRAL = "neutral"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    STALE = "stale"
    PENDING = "pending"
    UNREPORTED = "unreported"
    PRESENT = "present"


class Outcome(Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    INFO = "present, no verdict"


_CONCLUSION_OUTCOME = {
    Conclusion.SUCCESS: Outcome.PASS,
    Conclusion.FAILURE: Outcome.FAIL,
    Conclusion.TIMED_OUT: Outcome.FAIL,
    Conclusion.ACTION_REQUIRED: Outcome.FAIL,
    Conclusion.PRESENT: Outcome.INFO,
}


@dataclass(frozen=True)
class EvidenceItem:
    head_sha: str
    provenance: Provenance
    tool: ToolInfo
    fetched_at: datetime
    conclusion: Conclusion
    detail: RedactedText

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")


@dataclass(frozen=True)
class Matched:
    item: EvidenceItem
    expected_sha: str

    def __post_init__(self) -> None:
        if self.item.head_sha != self.expected_sha:
            raise ValueError("Matched evidence must carry the reviewed head SHA")


@dataclass(frozen=True)
class Stale:
    item: EvidenceItem
    expected_sha: str

    def __post_init__(self) -> None:
        if self.item.head_sha == self.expected_sha:
            raise ValueError("Stale evidence must carry a different SHA")


@dataclass(frozen=True)
class Missing:
    key: SourceKey
    reason: str


Evidence = Matched | Stale | Missing


@dataclass(frozen=True)
class Omission:
    """Something the controller deliberately did not read in full: a page
    cap, a size or archive limit, a per-review count cap. Every omission is
    listed in the draft; whatever it left unread is never counted as passing."""

    source: str
    limit: str
    detail: str


def outcome(evidence: Evidence) -> Outcome:
    match evidence:
        case Matched(item=item):
            return _CONCLUSION_OUTCOME.get(item.conclusion, Outcome.UNKNOWN)
        case _:
            return Outcome.UNKNOWN


def evidence_key(evidence: Evidence) -> SourceKey:
    match evidence:
        case Missing(key=key):
            return key
        case Matched(item=item) | Stale(item=item):
            return item.provenance.key
    raise TypeError(f"not evidence: {evidence!r}")  # pragma: no cover


class RunnerStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    SKIPPED = "skipped"


class CleanupStatus(Enum):
    DESTROYED_VERIFIED = "destroyed (verified absent)"
    DESTROY_UNVERIFIED = "destroy NOT verified -- run `sweep`"
    NOT_CREATED = "no runner was created"


@dataclass(frozen=True)
class RunnerReport:
    status: RunnerStatus
    cleanup: CleanupStatus
    runner_name: str | None
    note: str
