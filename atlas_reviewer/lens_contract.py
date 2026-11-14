# SPDX-License-Identifier: MIT
"""The finding contract a lens worker's final reply must meet, parsed at
the boundary. Pure.

The fields are `synthesis.md`'s *Finding contract* (location, evidence,
severity, valence, route, attribution, siblings, finding, fix). The reply
is untrusted model output, so `parse_reply` accepts exactly one JSON
object of the documented shape and raises `ContractError` naming the
first problem with the object itself. `lens` is capped and `body_sha256`
must be 64 lowercase hex characters, the shape a lens-body digest has, so
a reply is refused before any acknowledgement comparison. Severity is
matched after case, surrounding whitespace and a closed set of aliases (`critical` is
a Blocker, `low` is a nit). A finding that meets the contract except for a
severity string outside the four names and those aliases is dropped and
named with its raw severity; the other findings stand. Any other problem
in any finding refuses the whole reply. Nothing else is repaired or
guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from atlas_reviewer.bridge_args import path_problem

MAX_FINDINGS = 100
MAX_TEXT_CHARS = 4_000
MAX_LOCATION_CHARS = 600
MAX_EVIDENCE_LINES = 40
MAX_LINE = 10_000_000
# The longest lens name in the suite is 44 characters.
MAX_LENS_CHARS = 80
DIGEST = re.compile(r"[0-9a-f]{64}")
_FENCED = re.compile(r"\A```(?:json)?\n(.*)\n```\Z", re.DOTALL)
_RANGE = re.compile(r"(?P<path>.+):(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?")
_DESIGN = re.compile(r"(?:boundary|component):\S.*")
_REPLY_KEYS = frozenset({"lens", "body_sha256", "findings"})
_REQUIRED = (
    "location",
    "severity",
    "valence",
    "route",
    "attribution",
    "finding",
    "fix",
)
_OPTIONAL = ("evidence", "siblings")


class ContractError(ValueError):
    """The reply does not meet the finding contract; the message says where."""


class _UnknownSeverity(ContractError):
    """The one finding problem that drops the finding instead of refusing
    the reply."""


class Severity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"

    @property
    def rank(self) -> int:
        """0 for a Blocker; a lower rank is more severe."""
        return list(Severity).index(self)


class Valence(StrEnum):
    DEFECT = "defect"
    IMPROVEMENT = "improvement"


class Route(StrEnum):
    ENG = "eng"
    IMPLEMENTER = "implementer"
    PRODUCT = "product"
    DESIGN = "design"
    LEGAL = "legal"
    LEADERSHIP = "leadership"


class Attribution(StrEnum):
    INTRODUCED = "introduced"
    PRE_EXISTING = "pre-existing"


@dataclass(frozen=True)
class LineRange:
    """`path:start` or `path:start-end`, 1-based and inclusive."""

    path: str
    start: int
    end: int

    def __str__(self) -> str:
        span = str(self.start) if self.end == self.start else f"{self.start}-{self.end}"
        return f"{self.path}:{span}"


@dataclass(frozen=True)
class WholeFile:
    path: str

    def __str__(self) -> str:
        return self.path


@dataclass(frozen=True)
class DesignRef:
    """A `boundary:<from>→<to>` or `component:<name>` location."""

    ref: str

    def __str__(self) -> str:
        return self.ref


Location = LineRange | WholeFile | DesignRef


@dataclass(frozen=True)
class Finding:
    """One lens finding. `evidence` is the quoted source a `LineRange`
    finding rests on; the other locations have no single line to quote."""

    location: Location
    severity: Severity
    valence: Valence
    route: Route
    attribution: Attribution
    finding: str
    fix: str
    evidence: str = ""
    siblings: str = ""

    @property
    def sets_verdict(self) -> bool:
        """Only an introduced defect sets the verdict (synthesis.md)."""
        return (
            self.valence is Valence.DEFECT
            and self.attribution is Attribution.INTRODUCED
        )


@dataclass(frozen=True)
class LensReply:
    lens: str
    body_sha256: str
    findings: tuple[Finding, ...]
    # One line per finding that was left out, naming the raw severity.
    dropped: tuple[str, ...] = ()


def parse_reply(text: str) -> LensReply:
    """The reply as one JSON object `{"lens", "body_sha256", "findings"}`,
    optionally inside one ```json fence and nothing else."""
    stripped = text.strip()
    fenced = _FENCED.fullmatch(stripped)
    try:
        data = json.loads(fenced.group(1) if fenced else stripped)
    except json.JSONDecodeError:
        raise ContractError("the reply is not one JSON object") from None
    if not isinstance(data, dict) or set(data) != _REPLY_KEYS:
        raise ContractError(
            "the reply must be an object with exactly the keys "
            "lens, body_sha256 and findings"
        )
    lens, digest, findings = data["lens"], data["body_sha256"], data["findings"]
    if not isinstance(lens, str) or not isinstance(digest, str):
        raise ContractError("lens and body_sha256 must be strings")
    if len(lens) > MAX_LENS_CHARS:
        raise ContractError(f"lens is over {MAX_LENS_CHARS} characters")
    if DIGEST.fullmatch(digest) is None:
        raise ContractError("body_sha256 must be 64 lowercase hex characters")
    if not isinstance(findings, list):
        raise ContractError("findings must be a list")
    if len(findings) > MAX_FINDINGS:
        raise ContractError(f"more than {MAX_FINDINGS} findings")
    kept: list[Finding] = []
    dropped: list[str] = []
    for index, raw in enumerate(findings, 1):
        try:
            kept.append(_finding(index, raw))
        except _UnknownSeverity as exc:
            dropped.append(_dropped(exc, raw))
    return LensReply(lens, digest, tuple(kept), tuple(dropped))


def _finding(index: int, raw: Any) -> Finding:
    try:
        return _parse_finding(raw)
    except ContractError as exc:
        raise type(exc)(f"finding {index}: {exc}") from None


def _parse_finding(raw: Any) -> Finding:
    if not isinstance(raw, dict):
        raise ContractError("must be an object")
    unknown = set(raw) - set(_REQUIRED) - set(_OPTIONAL)
    missing = [k for k in _REQUIRED if k not in raw]
    if unknown:
        raise ContractError(f"has keys outside the contract ({len(unknown)})")
    if missing:
        raise ContractError(f"is missing {', '.join(missing)}")
    text = {k: _text(k, raw.get(k, "")) for k in (*_REQUIRED, *_OPTIONAL)}
    location = parse_location(text["location"])
    severity = _severity(text["severity"])
    valence = _member(Valence, "valence", text["valence"])
    route = _member(Route, "route", text["route"])
    attribution = _member(Attribution, "attribution", text["attribution"])
    body = _nonblank("finding", text["finding"])
    fix = _nonblank("fix", text["fix"])
    evidence = _evidence(location, text["evidence"])
    _check_axes(severity, valence, route, attribution)
    # Last, so a finding with an unknown severity and any other problem
    # refuses the reply rather than being dropped.
    if severity is None:
        raise _UnknownSeverity("severity must be one of blocker, major, minor, nit")
    return Finding(
        location,
        severity,
        valence,
        route,
        attribution,
        body,
        fix,
        evidence,
        text["siblings"],
    )


def _text(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{key} must be a string")
    if len(value) > MAX_TEXT_CHARS:
        raise ContractError(f"{key} is over {MAX_TEXT_CHARS} characters")
    return value


def _nonblank(key: str, value: str) -> str:
    if not value.strip():
        raise ContractError(f"{key} is empty")
    return value


# Closed. A string outside this set and the four severity names drops the
# finding.
_SEVERITY_ALIASES = {
    "critical": Severity.BLOCKER,
    "crit": Severity.BLOCKER,
    "blocking": Severity.BLOCKER,
    "high": Severity.MAJOR,
    "medium": Severity.MINOR,
    "moderate": Severity.MINOR,
    "low": Severity.NIT,
    "trivial": Severity.NIT,
}
_RAW_SEVERITY_CHARS = 80


def _severity(value: str) -> Severity | None:
    """Case, surrounding whitespace and the closed alias set, then the
    four names, or None. The raw text is not rewritten into the finding."""
    key = value.strip().lower()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "'\"":
        key = key[1:-1].strip()
    key = key.strip(".,:;!")
    try:
        return Severity(key)
    except ValueError:
        return _SEVERITY_ALIASES.get(key)


def _dropped(exc: _UnknownSeverity, raw: dict[str, str]) -> str:
    """The contract message plus the raw severity, so a later log can
    show the value that was refused."""
    shown = " ".join(raw["severity"].split())[:_RAW_SEVERITY_CHARS]
    return f"{exc}; raw severity {shown!r}"


def _member[E: StrEnum](enum: type[E], key: str, value: str) -> E:
    try:
        return enum(value.strip().lower())
    except ValueError:
        allowed = ", ".join(m.value for m in enum)
        raise ContractError(f"{key} must be one of {allowed}") from None


def parse_location(text: str) -> Location:
    """A design reference, a line range (a location ending `:<n>` or
    `:<n>-<m>`), or a whole file. Paths follow the bridge's path rules."""
    if len(text) > MAX_LOCATION_CHARS:
        raise ContractError(f"location is over {MAX_LOCATION_CHARS} characters")
    if _DESIGN.fullmatch(text):
        return DesignRef(text)
    lines = _RANGE.fullmatch(text)
    path = lines.group("path") if lines else text
    problem = path_problem(path)
    if problem is not None:
        raise ContractError(f"location path {problem}")
    if lines is None:
        return WholeFile(path)
    start = int(lines.group("start"))
    end = int(lines.group("end") or start)
    if end < start or end > MAX_LINE:
        raise ContractError("location line range must run forward, within the file")
    return LineRange(path, start, end)


def _evidence(location: Location, evidence: str) -> str:
    if not isinstance(location, LineRange):
        return evidence
    if not evidence.strip():
        raise ContractError("a file:line finding must quote its evidence")
    if len(evidence.splitlines()) > MAX_EVIDENCE_LINES:
        raise ContractError(f"evidence is over {MAX_EVIDENCE_LINES} lines")
    return evidence


def _check_axes(
    severity: Severity | None,
    valence: Valence,
    route: Route,
    attribution: Attribution,
) -> None:
    """The contract's own rules: an improvement is a nit for the
    implementer, and a pre-existing finding goes to the implementer. An
    unknown severity (None) is checked by the caller."""
    if valence is Valence.IMPROVEMENT and (
        severity not in (None, Severity.NIT) or route is not Route.IMPLEMENTER
    ):
        raise ContractError("an improvement must be severity nit, route implementer")
    if attribution is Attribution.PRE_EXISTING and route is not Route.IMPLEMENTER:
        raise ContractError("a pre-existing finding must be route implementer")
