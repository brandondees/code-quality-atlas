# SPDX-License-Identifier: MIT
"""The delta review: what a kept head's follow-up reviews (#702, D79).

When the keep side of the head-change decision holds a push back and the
running review finishes, the follow-up review is a **delta review**: it
reviews only what the commits between the reviewed head and the new head
changed, carries the earlier review's findings forward, and marks the
ones the new commits fixed as resolved.

Three pieces live here; the coordinator wires them.

- **The delta's scope.** A pull request's diff never contains
  merge-from-base content -- merging the base moves the merge base
  forward, so the base's changes drop out of `base...head` -- so the
  delta diff is simply the pull request's diff at the new head,
  restricted to the paths the range `delta_from..head` touched (the
  comparison's aggregate file list). A merge-only push yields an empty
  delta: the review then exists to carry the earlier findings forward
  and re-anchor them to the moved tree. A path the base merge and a
  delta commit both touched stays in scope -- over-inclusive is the safe
  direction, and the earlier hunks of such a file were worth re-reading
  anyway.
- **The prior findings.** They come from the round log, the one durable
  per-pull-request record (D74): the records at `delta_from`, their
  finding lines parsed back into findings. A line that does not parse is
  named, never dropped (D73's rule): it travels as raw text.
- **The carry-forward call.** One bounded, tool-less model call, built
  like D73's re-assessment: the prior findings labeled `P1`, `P2`, ...
  and the delta diff travel fenced; the reply re-states every prior
  finding that still applies (`revises`, with a re-anchored location and
  quote) and proposes the ones the new commits fixed (`withdrawn`, with
  the reason). Every re-statement is quote-checked against the new
  head's files exactly like an ordinary reply's -- through the
  re-assessment judge itself, so the two paths cannot drift apart. A
  resolution is accepted only when the prior finding's location is a
  path the delta touched: the new commits cannot have fixed a file they
  did not change, so a resolution proposed anywhere else is recorded as
  an annotation and the finding stands. Silence keeps the finding --
  carried in its original wording, re-offered to the next review -- so
  nothing is silently dropped.

The carry-forward call spends against the review's shared `Spend` (D68's
derived limits and dollar ceiling) like every other call, and its reply
shape is validated with the same finding-contract parsers the
re-assessment reply uses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from atlas_reviewer.attestation import CheckedFinding
from atlas_reviewer.diffs import diff_paths, scope_text
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.lens_contract import (
    _NO_OBJECT,
    MAX_FINDINGS,
    Attribution,
    ContractError,
    DesignRef,
    Finding,
    LineRange,
    Location,
    Route,
    Severity,
    Valence,
    WholeFile,
    _dropped,
    _last_fenced_object,
    _UnknownSeverity,
)
from atlas_reviewer.ports import BoundaryError, GitHubReader, Json
from atlas_reviewer.prompt import UntrustedBlock, _fence_rule, fence
from atlas_reviewer.quotes import QuoteSource, SourceText
from atlas_reviewer.reassess import (
    ReassessFinding,
    ReassessReply,
    _reassess_finding,
    _withdrawn_entry,
)
from atlas_reviewer.reassess import (
    judge as judge_reply,
)

CARRY_TARGET_PREFIX = "Carry-forward target (from the controller):"
"""The carry-forward turn's first line, controller-written. The scripted
dry-run reviewer tells this turn from an ordinary first turn and from a
D73 re-assessment turn by it."""

CARRY_INSTRUCTIONS = """\
You are the carry-forward assessor of an automated code review. The pull
request's head moved after an earlier review finished; you are reviewing
the delta -- only what the commits between the earlier review's head and
the current head changed, fenced below -- and deciding what becomes of
the earlier review's findings. Nothing you write is posted anywhere; the
operator reads the controller's draft first.

The earlier review's findings are listed in the first turn's
prior-findings block, each labeled P1, P2, ..., with its location. Judge
each against the delta:

- A prior finding the delta did not affect: re-state it in `findings`
  with a `revises` key naming its label, its location and evidence
  re-anchored to the current files, and a `reason` key stating what, if
  anything, moved. A re-statement is quote-checked against the current
  files exactly like an ordinary finding's quote; one that does not
  verify is not carried as verified.
- A prior finding the new commits fixed: name its label in `withdrawn`
  with a `reason` key stating what fixed it. The controller accepts a
  resolution only for a finding whose file the delta touched; anywhere
  else it is recorded as your proposal and the finding stands.
- A prior finding you cannot judge: say nothing about it. It is carried
  in its original wording, never silently dropped.

To add a finding the delta reveals, report it in `findings` with no
`revises` key. Every finding you report meets the Finding contract below
and is quoted from the current files.

When you are done, reply with exactly one JSON object and nothing else:
{"findings": [...], "withdrawn": [...]}. Each entry of `findings` has
the keys location, evidence, severity, valence, route, attribution,
finding and fix, and optionally siblings, with the values the Finding
contract below defines, plus the optional `revises` and `reason` keys
this preamble defines. Each entry of `withdrawn` is an object with
exactly the keys `id` and `reason`. Severity is exactly one of
"blocker", "major", "minor" or "nit"; a finding whose severity cannot
be read as one of those names is dropped, and the other findings stand.
Do not call a tool; this turn has none."""

PRIOR_ID = re.compile(r"^(?:L\d+-F\d+|P\d+)$")
_SEVERITIES = {severity.value: severity for severity in Severity}
_DESIGN_PREFIXES = ("boundary:", "component:")


def carry_system(contract: str, nonce: str) -> str:
    """The carry-forward call's system prompt: the instructions, the fence
    rule for the review's one nonce, and the Finding contract. There is
    no lens body to attest: the assessor is the controller's own, not a
    lens."""
    return "\n\n".join((CARRY_INSTRUCTIONS, _fence_rule(nonce), contract))


def carry_turn(
    event: PrEvent,
    prior: UntrustedBlock,
    delta: UntrustedBlock | None,
    nonce: str,
) -> str:
    """The carry-forward call's one user turn: the controller's subject,
    then the prior findings and -- when the delta is not empty -- the
    delta diff, each fenced with the review's one nonce."""
    subject = f"{event.repo}#{event.pr_number} at {event.head_sha}"
    parts = [f"{CARRY_TARGET_PREFIX}{subject}", fence(prior, nonce)]
    if delta is not None:
        parts.append(fence(delta, nonce))
    return "\n\n".join(parts)


# ------------------------------------------------------- the prior lines


def parse_prior_line(line: str) -> tuple[str, Finding] | None:
    """One round-record finding line parsed back into `(id, finding)`.

    A record's finding line is `{id} {severity} {location} {finding}` --
    the shape the controller writes -- so this parse is its exact
    inverse: the id and severity are validated against their closed
    sets, the location parses into one of its three shapes, and the rest
    of the line is the finding text. A carried finding is reconstructed
    defect-introduced (it set the earlier review's verdict once), with
    no fix or evidence text, because the record stores neither. None
    when the line is not that shape; the caller names it, never drops
    it."""
    parts = line.split(" ", 3)
    if len(parts) != 4:
        return None
    identifier, severity, location, text = parts
    if PRIOR_ID.fullmatch(identifier) is None:
        return None
    known = _SEVERITIES.get(severity)
    if known is None:
        return None
    place = _parse_location(location)
    if place is None:
        return None
    return identifier, Finding(
        place,
        known,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        text,
        "",
    )


def _parse_location(text: str) -> Location | None:
    """A location as the Finding contract accepts it: `path:span`, a
    whole file's path, or a `boundary:`/`component:` reference."""
    if text.startswith(_DESIGN_PREFIXES):
        return DesignRef(text)
    span = re.fullmatch(r"(.+):([1-9][0-9]*)(?:-([1-9][0-9]*))?", text)
    if span is not None:
        end = span.group(3)
        return LineRange(
            span.group(1), int(span.group(2)), int(end) if end else int(span.group(2))
        )
    return WholeFile(text)


def prior_findings(records: Sequence[Any]) -> tuple[tuple[str, Finding], ...]:
    """Every finding line of the given round records, in record order,
    as `(id, finding)` pairs. Lines that do not parse are skipped here
    and named by the caller, which has the raw line."""
    parsed: list[tuple[str, Finding]] = []
    for record in records:
        for line in record.findings:
            found = parse_prior_line(line)
            if found is not None:
                parsed.append(found)
    return tuple(parsed)


# ---------------------------------------------------------------- scope


def delta_paths(github: GitHubReader, event: PrEvent, pr_diff: str) -> tuple[str, ...]:
    """The paths the delta review covers: the paths the range
    `delta_from..head` touched that the pull request's diff at the new
    head still shows.

    The pull request's diff never carries merge-from-base content (the
    merge moves the base forward and the base's changes drop out of the
    three-dot diff), so restricting it to the range's touched paths is
    the range diff with that content excluded, with no per-commit reads.
    A path the range touched that the pull request's diff no longer
    shows was changed and changed back, or its change came and went with
    the base merge; there is nothing left on it to review."""
    compare = github.get_compare(event.repo, event.delta_from, event.head_sha)
    names = _range_paths(compare)
    shown = set(diff_paths(pr_diff))
    return tuple(path for path in names if path in shown)


def _range_paths(compare: Json) -> tuple[str, ...]:
    files = compare.get("files")
    if files is None:
        return ()
    if not isinstance(files, list):
        raise BoundaryError("the comparison has no files array")
    paths = []
    for item in files:
        name = item.get("filename") if isinstance(item, dict) else None
        if isinstance(name, str) and name:
            paths.append(name)
    return tuple(paths)


# ------------------------------------------------- the reply and its judge


@dataclass(frozen=True)
class CarryReply:
    findings: tuple[ReassessFinding, ...]
    withdrawn: tuple[tuple[str, str], ...]
    dropped: tuple[str, ...] = ()


def parse_carry_reply(text: str) -> CarryReply:
    """The carry-forward reply: one JSON object `{"findings",
    "withdrawn"}` -- `withdrawn` optional -- bare or as the last fenced
    object, with each entry validated exactly as the re-assessment
    reply's are (`revises` with its `reason` on a finding; `id` with its
    `reason` on a withdrawal). There is no lens or body acknowledgement:
    the assessor is the controller's own, not a lens."""
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = _last_fenced_object(stripped)
        if data is _NO_OBJECT:
            raise ContractError("the reply is not one JSON object") from None
    if not isinstance(data, dict) or not {"findings", "withdrawn"} >= set(data):
        raise ContractError(
            "the reply must be an object with the keys findings and withdrawn"
        )
    if "findings" not in data:
        raise ContractError("the reply is missing findings")
    findings = data["findings"]
    if not isinstance(findings, list):
        raise ContractError("findings must be a list")
    if len(findings) > MAX_FINDINGS:
        raise ContractError(f"more than {MAX_FINDINGS} findings")
    withdrawn = data.get("withdrawn", [])
    if not isinstance(withdrawn, list):
        raise ContractError("withdrawn must be a list")
    if len(withdrawn) > MAX_FINDINGS:
        raise ContractError(f"more than {MAX_FINDINGS} withdrawn entries")
    parsed: list[ReassessFinding] = []
    dropped: list[str] = []
    for index, raw in enumerate(findings, 1):
        try:
            parsed.append(_reassess_finding(index, raw))
        except _UnknownSeverity as exc:
            dropped.append(_dropped(exc, raw))
    return CarryReply(
        tuple(parsed),
        tuple(_withdrawn_entry(i, raw) for i, raw in enumerate(withdrawn, 1)),
        tuple(dropped),
    )


def judged_carry(
    reply: CarryReply,
    prior: Sequence[tuple[str, Finding]],
    sources: SourceText,
    head_tree: bytes,
    tolerance: int,
) -> tuple[
    tuple[CheckedFinding, ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[int, str, str], ...],
]:
    """The reply quote-checked and its labels resolved, through the
    re-assessment judge itself (the reply shape is the same minus the
    lens acknowledgement), so the two paths' quote checks cannot drift
    apart. The prior findings all take part: each was a verified finding
    of the review it came from, and the labels the reply names resolve
    against all of them."""
    checked_prior = [
        CheckedFinding(finding, QuoteSource.HEAD) for _id, finding in prior
    ]
    shim = ReassessReply("", "0" * 64, reply.findings, reply.withdrawn, reply.dropped)
    judged = judge_reply(shim, checked_prior, sources, head_tree, tolerance)
    return judged.checked, judged.withdrawn, judged.revises


def delta_review_diff(
    github: GitHubReader, event: PrEvent, pr_diff: str
) -> tuple[str, str]:
    """The diff a delta review runs on, and the controller note when it
    could not be the delta's.

    The delta's diff is the pull request's diff at the new head,
    restricted to the paths the range `delta_from..head` touched
    (`delta_paths`). When the range itself cannot be fetched -- the delta
    base force-pushed away, a transport failure -- the review runs on the
    full pull request diff rather than skipping the push, and the note
    records the fallback; the carry-forward still applies, because the
    earlier review's findings do not depend on the range being
    readable."""
    try:
        return scope_text(pr_diff, delta_paths(github, event, pr_diff)), ""
    except BoundaryError as exc:
        return pr_diff, (
            "the delta range could not be fetched "
            f"({type(exc).__name__}); the review ran on the full pull "
            "request diff"
        )


# ---------------------------------------------------------- composition


@dataclass(frozen=True)
class CarryResult:
    """What the carry-forward leaves of the prior findings.

    `carried` pairs each prior label with its re-anchored, verified
    finding. `unanchored` pairs each prior label with the finding as the
    record stored it -- carried in its original wording when the reply
    was silent, when its re-statement did not verify, or when a proposed
    resolution was refused -- and travels back into the round record, so
    the next review re-offers it. `resolved` pairs each accepted
    resolution with its stated reason; the finding leaves the chain
    there, by a stated reason the post shows. `notes` is controller
    text for the draft."""

    carried: tuple[tuple[str, CheckedFinding], ...]
    unanchored: tuple[tuple[str, Finding], ...]
    resolved: tuple[tuple[str, str, Finding], ...]
    notes: tuple[str, ...] = ()


def apply_carry(
    prior: Sequence[tuple[str, Finding]],
    checked: Sequence[CheckedFinding],
    revises: Sequence[tuple[int, str, str]],
    withdrawn: Sequence[tuple[str, str]],
    delta_paths: frozenset[str],
) -> CarryResult:
    """The reply's judgment composed over the prior findings.

    `checked` is the reply's quote-checked findings in reply order,
    `revises` their `(index, label, reason)` references, `withdrawn` the
    resolution proposals. Every prior finding ends in exactly one of the
    three buckets; nothing is dropped."""
    restated: dict[str, CheckedFinding] = {}
    for index, label, _reason in revises:
        if 1 <= index <= len(checked) and checked[index - 1].verified:
            restated[label] = checked[index - 1]
    carried: list[tuple[str, CheckedFinding]] = []
    unanchored: list[tuple[str, Finding]] = []
    resolved: list[tuple[str, str, Finding]] = []
    notes: list[str] = []
    withdrawn_labels = {label for label, _reason in withdrawn}
    for identifier, finding in prior:
        if identifier in restated:
            carried.append((identifier, restated[identifier]))
            continue
        if identifier in withdrawn_labels:
            reason = next(reason for label, reason in withdrawn if label == identifier)
            path = _cited_path(finding.location)
            if path is not None and path in delta_paths:
                resolved.append((identifier, reason, finding))
                continue
            unanchored.append((identifier, finding))
            notes.append(
                f"{identifier}: a resolution was proposed, but the delta did "
                "not touch the file it cites, so it stands"
            )
            continue
        unanchored.append((identifier, finding))
    return CarryResult(tuple(carried), tuple(unanchored), tuple(resolved), tuple(notes))


def _cited_path(location: Location) -> str | None:
    if isinstance(location, LineRange | WholeFile):
        return location.path
    return None
