# SPDX-License-Identifier: MIT
"""The dry-run lens script: the canned reviewer `agentic-review --dry-run`
replays.

A dry run must reach and run the lenses end to end with no network, no
Sprites and no model key. Everything around the model already runs as real
code: the runner lifecycle, the bridge staging, the tool calls, the quote
checks, the attestation ledger, the synthesis, the verdict and the draft.
This module is only the part that stands in for the model. Its reading
behavior is fixed — the order the lens instructions themselves ask for,
every changed file's diff page by page, then the head files the findings
cite — and everything that varies comes from a JSON script in the fixture
directory, so a new scenario is a new file, not new code:

```json
{
  "findings": {
    "<lens name>": [{"location": "calc.py:4", "evidence": "...", ...}]
  },
  "unread": ["settings.ini"],
  "reassessment": {
    "findings": {
      "<lens name>": [{"location": "calc.py:4", "revises": "P1", "reason": "...", ...}]
    },
    "withdrawn": {"<lens name>": [{"id": "P1", "reason": "..."}]}
  }
}
```

`findings` maps a lens name to the finding objects that lens reports, in
the finding contract's shape (each entry is validated with the real
parser at load, so a malformed scenario is refused before a run rather
than discovered as a contract refusal mid-run). `unread` names changed
files no lens ever reads, for a scenario that must end with a coverage
gap. A lens with no entry here reports no findings.

`reassessment` is the scenario's D73 re-assessment reply, answered when a
review reuses a settled lens and finds newer evidence: `findings` maps a
lens name to the findings it reports then -- an entry's optional
`revises` names the prior-finding label the entry revises and its
`reason` states what in the new evidence changed the judgment -- and
`withdrawn` maps a lens name to the prior labels it withdraws, each with
its reason. Every entry is validated with the real re-assessment parser
at load. A lens with no entry here confirms every prior finding by
silence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from atlas_reviewer.delta import (
    CARRY_TARGET_PREFIX,
    DECISION_TARGET_PREFIX,
    parse_carry_reply,
    validated_decision,
)
from atlas_reviewer.lens_contract import ContractError, parse_reply
from atlas_reviewer.lens_loop import (
    AssistantCalls,
    FinalReply,
    ModelTurn,
    ToolCalls,
    ToolRequest,
    ToolResults,
    TurnRequest,
    UserText,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.reassess import REASSESS_TARGET_PREFIX, parse_reassess_reply

COST_PER_TURN = Decimal("0.01")

_BODY_MARKER = re.compile(r"=== lens body begins: (\S+) \(sha256 ([0-9a-f]{64})\) ===")
_LISTING_BLOCK = re.compile(
    r'label="changed-files">\n(.*?)\n</untrusted-data', re.DOTALL
)
_LISTING_LINE = re.compile(r"^\[[^\]]+\] (.+) \(\+\d+ -\d+\)$", re.MULTILINE)
_NEXT_PAGE = re.compile(r"next page at offset (\d+)")
_RANGE = re.compile(r"^(.+):[1-9][0-9]*(?:-[1-9][0-9]*)?$")
_FENCE_TAIL = "\n</untrusted-data"
_OK = ": ok"


class LensScriptError(ValueError):
    """The lens script cannot be loaded: the file is missing, unreadable,
    or holds a shape this loader does not accept."""


@dataclass(frozen=True)
class ReassessScript:
    """The scenario's D73 re-assessment reply: per lens, the findings it
    reports (each optionally revising a prior label) and the prior labels
    it withdraws."""

    findings: Mapping[str, tuple[Mapping[str, str], ...]]
    withdrawn: Mapping[str, tuple[Mapping[str, str], ...]]


@dataclass(frozen=True)
class CarryScript:
    """The scenario's delta carry-forward reply (#702): the findings the
    assessor re-states (each `revises`-ing a prior label with its
    reason) and the prior labels it proposes resolving, each with its
    reason. The carry-forward assessor is the controller's own, not a
    lens, so there is no per-lens mapping."""

    findings: tuple[Mapping[str, str], ...] = ()
    withdrawn: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True)
class DecisionScript:
    """The scenario's coordinator-decision reply (D83): one entry per
    lens the decision turn offers, each with its `lens`, `decision`
    (`rerun` or `reuse`) and `reason`. The controller-level reply is
    validated entry by entry at load; the lens names resolve at run
    time, when the turn names the lenses a reuse is available for."""

    entries: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True)
class LensScript:
    """`findings` maps a lens name to the finding objects it reports, in
    reply order. `unread` names changed files no lens ever reads.
    `reassessment` is the reply a reused lens's D73 re-assessment earns."""

    findings: Mapping[str, tuple[Mapping[str, str], ...]]
    unread: frozenset[str]
    reassessment: ReassessScript = ReassessScript(
        MappingProxyType({}), MappingProxyType({})
    )
    carryforward: CarryScript = CarryScript()
    decisions: DecisionScript = DecisionScript()

    def findings_for(self, lens: str) -> tuple[Mapping[str, str], ...]:
        return self.findings.get(lens, ())

    def reassessment_for(self, lens: str) -> tuple[Mapping[str, str], ...]:
        return self.reassessment.findings.get(lens, ())

    def withdrawn_for(self, lens: str) -> tuple[Mapping[str, str], ...]:
        return self.reassessment.withdrawn.get(lens, ())


def load_lens_script(path: Path) -> LensScript:
    """The script at `path`, validated: every finding must parse under the
    real finding contract (an unknown severity loads — dropping it is a
    scenario — but any other contract problem is refused here), and every
    re-assessment entry must parse under the re-assessment reply's shape."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LensScriptError(f"cannot read lens script {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LensScriptError(f"lens script {path} must hold a JSON object")
    unknown = set(raw) - {
        "findings",
        "unread",
        "reassessment",
        "carryforward",
        "decisions",
    }
    if unknown:
        raise LensScriptError(
            f"lens script {path} has keys outside findings, unread, "
            f"reassessment, carryforward and decisions: "
            f"{', '.join(sorted(unknown))}"
        )
    return LensScript(
        _findings(path, raw.get("findings", {})),
        _unread(path, raw),
        _reassessment(path, raw.get("reassessment", {})),
        _carryforward(path, raw.get("carryforward", {})),
        _decisions(path, raw.get("decisions", [])),
    )


def _findings(path: Path, raw: object) -> Mapping[str, tuple[Mapping[str, str], ...]]:
    if not isinstance(raw, dict):
        raise LensScriptError(f"lens script {path}: findings must be an object")
    parsed: dict[str, tuple[Mapping[str, str], ...]] = {}
    for lens, entries in raw.items():
        if not isinstance(lens, str) or not isinstance(entries, list):
            raise LensScriptError(
                f"lens script {path}: each findings value must be a list of "
                "finding objects"
            )
        parsed[lens] = tuple(
            _entry(path, lens, i, entry) for i, entry in enumerate(entries, 1)
        )
    return MappingProxyType(parsed)


def _entry(path: Path, lens: str, index: int, raw: object) -> Mapping[str, str]:
    if not isinstance(raw, dict) or not all(
        isinstance(value, str) for value in raw.values()
    ):
        raise LensScriptError(
            f"lens script {path}: finding {index} for {lens!r} must be an "
            "object of strings"
        )
    reply = json.dumps({"lens": lens, "body_sha256": "0" * 64, "findings": [raw]})
    try:
        parse_reply(reply)
    except ContractError as exc:
        raise LensScriptError(
            f"lens script {path}: finding {index} for {lens!r} breaks the "
            f"finding contract: {exc}"
        ) from exc
    return MappingProxyType(dict(raw))


def _unread(path: Path, raw: Mapping[str, object]) -> frozenset[str]:
    unread = raw.get("unread", [])
    if not isinstance(unread, list) or not all(isinstance(p, str) for p in unread):
        raise LensScriptError(f"lens script {path}: unread must be a list of paths")
    return frozenset(unread)


def _reassessment(path: Path, raw: object) -> ReassessScript:
    """The scenario's D73 re-assessment reply, validated entry by entry
    with the real re-assessment parser: an entry that breaks the reply's
    shape is refused at load, not discovered as a contract refusal
    mid-run. The prior-finding labels an entry names are not resolved
    here -- they resolve against the prior findings the run composes --
    only the shape is checked."""
    if not isinstance(raw, dict):
        raise LensScriptError(f"lens script {path}: reassessment must be an object")
    unknown = set(raw) - {"findings", "withdrawn"}
    if unknown:
        raise LensScriptError(
            f"lens script {path}: reassessment has keys outside findings "
            f"and withdrawn: {', '.join(sorted(unknown))}"
        )
    return ReassessScript(
        _reassess_findings(path, raw.get("findings", {})),
        _reassess_withdrawn(path, raw.get("withdrawn", {})),
    )


def _reassess_findings(
    path: Path, raw: object
) -> Mapping[str, tuple[Mapping[str, str], ...]]:
    if not isinstance(raw, dict):
        raise LensScriptError(
            f"lens script {path}: reassessment findings must be an object"
        )
    parsed: dict[str, tuple[Mapping[str, str], ...]] = {}
    for lens, entries in raw.items():
        if not isinstance(lens, str) or not isinstance(entries, list):
            raise LensScriptError(
                f"lens script {path}: each reassessment findings value must "
                "be a list of finding objects"
            )
        parsed[lens] = tuple(
            _reassess_entry(path, lens, i, entry) for i, entry in enumerate(entries, 1)
        )
    return MappingProxyType(parsed)


def _reassess_entry(
    path: Path, lens: str, index: int, raw: object
) -> Mapping[str, str]:
    if not isinstance(raw, dict) or not all(
        isinstance(value, str) for value in raw.values()
    ):
        raise LensScriptError(
            f"lens script {path}: reassessment finding {index} for {lens!r} "
            "must be an object of strings"
        )
    reply = json.dumps(
        {"lens": lens, "body_sha256": "0" * 64, "findings": [raw], "withdrawn": []}
    )
    try:
        parse_reassess_reply(reply)
    except ContractError as exc:
        raise LensScriptError(
            f"lens script {path}: reassessment finding {index} for {lens!r} "
            f"breaks the re-assessment reply's shape: {exc}"
        ) from exc
    return MappingProxyType(dict(raw))


def _reassess_withdrawn(
    path: Path, raw: object
) -> Mapping[str, tuple[Mapping[str, str], ...]]:
    if not isinstance(raw, dict):
        raise LensScriptError(
            f"lens script {path}: reassessment withdrawn must be an object"
        )
    parsed: dict[str, tuple[Mapping[str, str], ...]] = {}
    for lens, entries in raw.items():
        if not isinstance(lens, str) or not isinstance(entries, list):
            raise LensScriptError(
                f"lens script {path}: each reassessment withdrawn value must "
                "be a list of {id, reason} objects"
            )
        for i, entry in enumerate(entries, 1):
            reply = json.dumps(
                {
                    "lens": lens,
                    "body_sha256": "0" * 64,
                    "findings": [],
                    "withdrawn": [entry],
                }
            )
            try:
                parse_reassess_reply(reply)
            except ContractError as exc:
                raise LensScriptError(
                    f"lens script {path}: reassessment withdrawal {i} for "
                    f"{lens!r} breaks the re-assessment reply's shape: {exc}"
                ) from exc
        parsed[lens] = tuple(MappingProxyType(dict(entry)) for entry in entries)
    return MappingProxyType(parsed)


def _carryforward(path: Path, raw: object) -> CarryScript:
    """The scenario's delta carry-forward reply (#702), validated entry
    by entry with the real carry-forward parser: an entry that breaks
    the reply's shape is refused at load, not discovered as a contract
    refusal mid-run. The reply is controller-level, so the entries are
    not mapped by lens."""
    if not isinstance(raw, dict):
        raise LensScriptError(f"lens script {path}: carryforward must be an object")
    unknown = set(raw) - {"findings", "withdrawn"}
    if unknown:
        raise LensScriptError(
            f"lens script {path}: carryforward has keys outside findings "
            f"and withdrawn: {', '.join(sorted(unknown))}"
        )
    findings = raw.get("findings", [])
    withdrawn = raw.get("withdrawn", [])
    if not isinstance(findings, list) or not isinstance(withdrawn, list):
        raise LensScriptError(
            f"lens script {path}: carryforward findings and withdrawn must be lists"
        )
    for i, entry in enumerate((*findings, *withdrawn), 1):
        reply = json.dumps(
            {
                "findings": [entry] if i <= len(findings) else [],
                "withdrawn": [] if i <= len(findings) else [entry],
            }
        )
        try:
            parse_carry_reply(reply)
        except ContractError as exc:
            raise LensScriptError(
                f"lens script {path}: carryforward entry {i} breaks the "
                f"carry-forward reply's shape: {exc}"
            ) from exc
    try:
        # The complete reply too (round-5 review of #748): the caps are
        # reply-level, so a scenario whose entries are each valid but
        # number over the reply's cap loads per entry and then fails at
        # parse time mid-run, silently carrying every prior finding.
        parse_carry_reply(json.dumps({"findings": findings, "withdrawn": withdrawn}))
    except ContractError as exc:
        raise LensScriptError(
            f"lens script {path}: carryforward breaks the carry-forward "
            f"reply's shape: {exc}"
        ) from exc
    return CarryScript(
        tuple(MappingProxyType(dict(entry)) for entry in findings),
        tuple(MappingProxyType(dict(entry)) for entry in withdrawn),
    )


def _decisions(path: Path, raw: object) -> DecisionScript:
    """The scenario's coordinator-decision reply (D83), validated entry
    by entry with the real decision parser's entry validator. The
    offered lens names resolve at run time, so each entry is checked
    against a known-set of its own name: the membership rule cannot
    refuse a scenario's own lens, and every other rule -- keys, types,
    the decision value, the reason -- is refused at load, not discovered
    as a contract refusal mid-run."""
    if not isinstance(raw, list):
        raise LensScriptError(f"lens script {path}: decisions must be a list")
    for i, entry in enumerate(raw, 1):
        try:
            validated_decision(
                i, entry, {entry["lens"]} if isinstance(entry, dict) else set()
            )
        except (ContractError, TypeError, KeyError) as exc:
            raise LensScriptError(
                f"lens script {path}: decisions entry {i} breaks the "
                f"decision reply's shape: {exc}"
            ) from exc
    return DecisionScript(tuple(MappingProxyType(dict(entry)) for entry in raw))


class LensScriptModel:
    """The scripted reviewer one lens run talks to. Each run gets a fresh
    instance, so a continuation starts with its own coverage state and
    re-derives it from the turn it is handed.

    The turns follow the lens instructions' own order: every changed
    file's diff (a `diff_file` page at a time, following each truncated
    page's next offset), then a `read_file` at HEAD of every file a
    finding cites, then the final reply. A changed file named in the
    script's `unread` is never diffed, and the loop's one unread-list
    nudge is answered by finalizing again with the same findings — the
    scenario keeps its gap. The reply's quotes are the script's, and the
    controller verifies them against the head tree the way it verifies a
    live model's."""

    name = "lens-script"

    def __init__(self, script: LensScript, cost_usd: Decimal = COST_PER_TURN) -> None:
        self._script = script
        self._cost = cost_usd
        self._pages: dict[str, int | None] = {}
        self._read: set[str] = set()

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        return self._cost

    def output_tokens_within(self, request: TurnRequest, budget_usd: Decimal) -> int:
        """A fixed worst case: no smaller cap ever fits better."""
        return 0

    def turn(self, request: TurnRequest) -> ModelTurn:
        if _is_decision(request.messages):
            # The delta review's coordinator-decision turn (D83): the
            # controller offers no tools and asks for one reply, which
            # the scenario's `decisions` section holds (an empty section
            # replies with no decisions, which the controller's
            # validation refuses -- every lens re-runs). Checked first:
            # the decision system prompt carries no lens body, because
            # the deciding coordinator is the controller's own.
            return self._decision_final()
        if _is_carryforward(request.messages):
            # The delta review's carry-forward turn (#702): the controller
            # offers no tools and asks for one reply, which the scenario's
            # `carryforward` section holds (silence keeps every prior
            # finding as the record stored it). Checked before the body
            # markers: the carry-forward system prompt carries no lens
            # body, because the assessor is the controller's own.
            return self._carry_final()
        lens, digest = _markers(request.system)
        if _is_reassessment(request.messages):
            # D73's re-assessment turn: the reuse path offers no tools and
            # asks for one reply, which the scenario's `reassessment`
            # section holds (silence confirms every prior finding).
            return self._reassess_final(lens, digest)
        if len(request.messages) == 1:
            # A conversation restart (a retry attempt reuses this instance):
            # the coverage state is the old attempt's, so start over.
            self._pages.clear()
            self._read.clear()
        self._note_results(request.messages)
        if _after_first_turn(request.messages):
            # A controller nudge (the unread list, or finalize now): the
            # scenario holds, so finalize with what we have.
            return self._final(lens, digest)
        paths = _changed_paths(request.messages)
        if paths is None:
            raise BoundaryError("the changed-file list is missing from the first turn")
        for path in paths:
            self._pages.setdefault(path, 0)
        pending = sorted(
            (path, offset)
            for path, offset in self._pages.items()
            if offset is not None and path not in self._script.unread
        )
        if pending:
            return ToolCalls(
                tuple(
                    ToolRequest("diff_file", {"path": path, "offset": offset})
                    for path, offset in pending
                ),
                self._cost,
            )
        cited: set[str] = set()
        for finding in self._script.findings_for(lens):
            cited_path = _cited_path(finding)
            if (
                cited_path is not None
                and cited_path in paths
                and cited_path not in self._read
            ):
                cited.add(cited_path)
        ordered = sorted(cited)
        if ordered:
            return ToolCalls(
                tuple(ToolRequest("read_file", {"path": path}) for path in ordered),
                self._cost,
            )
        return self._final(lens, digest)

    def _final(self, lens: str, digest: str) -> FinalReply:
        payload = {
            "lens": lens,
            "body_sha256": digest,
            "findings": [dict(finding) for finding in self._script.findings_for(lens)],
        }
        return FinalReply(json.dumps(payload), self._cost)

    def _decision_final(self) -> FinalReply:
        """The scenario's coordinator-decision reply (D83): the entries
        the scenario holds, verbatim."""
        payload = {
            "decisions": [dict(entry) for entry in self._script.decisions.entries],
        }
        return FinalReply(json.dumps(payload), self._cost)

    def _carry_final(self) -> FinalReply:
        """The scenario's carry-forward reply (#702): the prior labels it
        re-states, each with its re-anchored location, and the prior
        labels it proposes resolving, each with its reason."""
        payload = {
            "findings": [
                dict(finding) for finding in self._script.carryforward.findings
            ],
            "withdrawn": [dict(entry) for entry in self._script.carryforward.withdrawn],
        }
        return FinalReply(json.dumps(payload), self._cost)

    def _reassess_final(self, lens: str, digest: str) -> FinalReply:
        """The scenario's re-assessment reply: the findings it reports --
        each optionally revising a prior label -- and the prior labels it
        withdraws, each with its reason."""
        payload = {
            "lens": lens,
            "body_sha256": digest,
            "findings": [
                dict(finding) for finding in self._script.reassessment_for(lens)
            ],
            "withdrawn": [dict(entry) for entry in self._script.withdrawn_for(lens)],
        }
        return FinalReply(json.dumps(payload), self._cost)

    def _note_results(self, messages: tuple[object, ...]) -> None:
        """Reconcile the coverage state with the tool results already in
        the conversation. A failed or refused call stops its file's page
        chain: the attempt ends partial on the tool gap, not looping."""
        calls: tuple[ToolRequest, ...] | None = None
        for message in messages:
            if isinstance(message, AssistantCalls):
                calls = message.calls
            elif isinstance(message, ToolResults) and calls is not None:
                for call, result in zip(calls, message.results, strict=True):
                    self._note_result(call, result)
                calls = None

    def _note_result(self, call: ToolRequest, result: object) -> None:
        body = str(result)
        if body.startswith("<untrusted-data"):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.split(_FENCE_TAIL, 1)[0]
        first = body.split("\n", 1)[0]
        args = dict(call.args) if isinstance(call.args, Mapping) else {}
        path = args.get("path")
        if not isinstance(path, str):
            return
        if call.tool == "diff_file":
            if _OK not in first:
                self._pages[path] = None
                return
            page = _NEXT_PAGE.search(first)
            self._pages[path] = int(page.group(1)) if page is not None else None
        elif call.tool == "read_file" and _OK in first:
            self._read.add(path)


def _is_decision(messages: tuple[object, ...]) -> bool:
    """Whether the turn to answer is the delta review's coordinator
    decision turn (D83): its first message opens with the controller's
    own decision subject, which no PR-written text can be the first line
    of. Checked before the carry-forward and re-assessment turns,
    because all three are one-message, tool-less turns."""
    return bool(
        messages
        and isinstance(messages[0], UserText)
        and messages[0].text.startswith(DECISION_TARGET_PREFIX)
    )


def _is_carryforward(messages: tuple[object, ...]) -> bool:
    """Whether the turn to answer is the delta review's carry-forward
    turn (#702): its first message opens with the controller's own
    carry-forward subject, which no PR-written text can be the first
    line of. Checked before the re-assessment turn's, because both are
    one-message, tool-less turns."""
    return bool(
        messages
        and isinstance(messages[0], UserText)
        and messages[0].text.startswith(CARRY_TARGET_PREFIX)
    )


def _is_reassessment(messages: tuple[object, ...]) -> bool:
    """Whether the turn to answer is the reuse path's re-assessment turn
    (D73): its first message opens with the controller's own re-assessment
    subject, which no PR-written text can be the first line of."""
    return bool(
        messages
        and isinstance(messages[0], UserText)
        and messages[0].text.startswith(REASSESS_TARGET_PREFIX)
    )


def _after_first_turn(messages: tuple[object, ...]) -> bool:
    """Whether the turn to answer is a controller nudge rather than tool
    results: any UserText after the first turn is one (the repair turn,
    the unread list, or finalize now)."""
    return len(messages) > 1 and isinstance(messages[-1], UserText)


def _markers(system: str) -> tuple[str, str]:
    match = _BODY_MARKER.search(system)
    if match is None:
        raise BoundaryError("the lens body markers are missing from the system prompt")
    return match.group(1), match.group(2)


def _changed_paths(messages: tuple[object, ...]) -> tuple[str, ...] | None:
    """The changed paths the first turn's `changed-files` block lists, in
    its risk order. That block is controller-assembled, so its shape is
    the controller's; the paths inside it are PR data."""
    first = messages[0].text if isinstance(messages[0], UserText) else ""
    block = _LISTING_BLOCK.search(first)
    if block is None:
        return None
    return tuple(match.group(1) for match in _LISTING_LINE.finditer(block.group(1)))


def _cited_path(finding: Mapping[str, str]) -> str | None:
    """The head file a `file:line` finding cites; a whole-file or design
    location cites no line to read."""
    location = finding.get("location", "")
    match = _RANGE.match(location)
    return match.group(1) if match is not None else None
