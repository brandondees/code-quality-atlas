# SPDX-License-Identifier: MIT
"""The finding contract a lens worker's final reply must meet, parsed at
the boundary. Pure.

The fields are `synthesis.md`'s *Finding contract* (location, evidence,
severity, valence, route, attribution, siblings, finding, fix). The reply
is untrusted model output, so `parse_reply` accepts exactly one JSON
object of the documented shape and raises `ContractError` naming the
first problem. `lens` is capped and `body_sha256` must be 64 lowercase
hex characters, the shape a lens-body digest has, so a reply is refused
before any acknowledgement comparison. Nothing is repaired, guessed or
cut: a reply that breaks the contract is not partly used.
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
_ANY_FENCE = re.compile(r"```(?:json)?\n(.*?)\n```", re.DOTALL)
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
# The Finding contract's per-finding `lens` field names the lens that raised
# the finding. The reply's top-level `lens` already does that, so the parser
# accepts the key and drops it rather than refusing the whole finding: the
# contract text lists it, and a reply that follows that text must parse.
_IGNORED = frozenset({"lens"})


class ContractError(ValueError):
    """The reply does not meet the finding contract; the message says where."""


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


def parse_reply(text: str) -> LensReply:
    """The reply as one JSON object `{"lens", "body_sha256", "findings"}`,
    bare, as the whole reply inside one ```json fence, or as the last
    fenced JSON object after prose."""
    stripped = text.strip()
    fenced = _FENCED.fullmatch(stripped)
    try:
        data = json.loads(fenced.group(1) if fenced else stripped)
    except json.JSONDecodeError:
        data = _last_fenced_object(stripped)
        if data is _NO_OBJECT:
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
    return LensReply(
        lens,
        digest,
        tuple(_finding(i, f) for i, f in enumerate(findings, 1)),
    )


def _last_fenced_object(text: str) -> Any:
    """The last ```-fenced block's JSON, or `_NO_OBJECT` when there is no
    closed fence or its content does not parse. A model often writes prose
    before the JSON it meant as the reply; the last block is that JSON."""
    blocks = _ANY_FENCE.findall(text)
    if not blocks:
        return _NO_OBJECT
    try:
        return json.loads(blocks[-1])
    except (json.JSONDecodeError, RecursionError):
        return _NO_OBJECT


_NO_OBJECT: Any = object()


def _finding(index: int, raw: Any) -> Finding:
    try:
        return _parse_finding(raw)
    except ContractError as exc:
        raise ContractError(f"finding {index}: {exc}") from None


def _parse_finding(raw: Any) -> Finding:
    if not isinstance(raw, dict):
        raise ContractError("must be an object")
    unknown = set(raw) - set(_REQUIRED) - set(_OPTIONAL) - _IGNORED
    missing = [k for k in _REQUIRED if k not in raw]
    if unknown:
        raise ContractError(f"has keys outside the contract ({len(unknown)})")
    if missing:
        raise ContractError(f"is missing {', '.join(missing)}")
    text = {k: _text(k, raw.get(k, "")) for k in (*_REQUIRED, *_OPTIONAL)}
    location = parse_location(text["location"])
    finding = Finding(
        location,
        _member(Severity, "severity", text["severity"]),
        _member(Valence, "valence", text["valence"]),
        _member(Route, "route", text["route"]),
        _member(Attribution, "attribution", text["attribution"]),
        _nonblank("finding", text["finding"]),
        _nonblank("fix", text["fix"]),
        _evidence(location, text["evidence"]),
        text["siblings"],
    )
    _check_axes(finding)
    return finding


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


def _check_axes(finding: Finding) -> None:
    """The contract's own rules: an improvement is a nit for the
    implementer, and a pre-existing finding goes to the implementer."""
    if finding.valence is Valence.IMPROVEMENT and (
        finding.severity is not Severity.NIT or finding.route is not Route.IMPLEMENTER
    ):
        raise ContractError("an improvement must be severity nit, route implementer")
    if (
        finding.attribution is Attribution.PRE_EXISTING
        and finding.route is not Route.IMPLEMENTER
    ):
        raise ContractError("a pre-existing finding must be route implementer")
