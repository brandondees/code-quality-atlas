# SPDX-License-Identifier: MIT
"""The delta review: what a kept head's follow-up reviews (#702, D79, D83).

When the keep side of the head-change decision holds a push back and the
running review finishes, the follow-up review is a **delta review**. Its
subject is still the whole pull request at the new head -- the earlier
review's verdict covered the whole changeset, and so does this one's --
but the payload carries only the **incremental diff**: what the commits
between the reviewed head (`delta_from`) and the new head changed, the
new material since the earlier review. Context the earlier review
already established is not re-sent, which keeps D68's cost goals.

Five pieces live here; the coordinator wires them.

- **The delta's scope.** `DeltaScope` is what is new and what a
  resolution may be accepted for -- not a lens scope. The review's
  lenses run on the whole pull request's diff at the new head; the
  range's own per-file patches (`range_diff`) are the incremental diff
  the payload highlights. A merge-only push yields an empty delta: the
  review then exists to carry the earlier findings forward and re-anchor
  them to the moved tree.
- **The coordinator's per-lens decision (D83).** For each planned lens
  the coordinator judges, from the incoming changes, whether to re-run
  the lens or reuse the earlier review's settled result. The decision is
  the coordinator's judgment -- one bounded, tool-less call over the
  incremental diff and the lens names -- not a fixed path-intersection
  rule. A re-run lens sees the whole pull request through its tools and
  may report findings anywhere in it, including on content the
  incremental diff does not touch. A reused lens does not run: its
  earlier findings stand, carried forward and re-assessed against the
  new evidence (D73), and its files still count as covered.
- **The highlight block.** `delta_block` renders the incremental diff
  as one bounded block of a re-run lens's first turn -- the new
  material, highlighted ahead of the whole diff the lens reads through
  its tools, sized like the CI block within D67's input-room budgeting.
- **The prior findings.** They come from the round log, the one durable
  per-pull-request record (D74): the records at `delta_from`, their
  finding lines parsed back into findings. A line that does not parse is
  never dropped (D73's rule): it is carried as the record's raw text,
  shown in the draft and re-recorded, so the next review re-offers it.
- **The carry-forward call.** One bounded, tool-less model call, built
  like D73's re-assessment: the prior findings labeled `P1`, `P2`, ...
  and the incremental diff travel fenced; the reply re-states every prior
  finding that still applies (`revises`, with a re-anchored location and
  quote) and proposes the ones the new commits fixed (`withdrawn`, with
  the reason and the evidence). Every re-statement is quote-checked
  against the new head's files exactly like an ordinary reply's --
  through the re-assessment judge itself, so the two paths cannot drift
  apart. A resolution is accepted only on all three of: the model's
  proposal with its reason; the prior finding's file being one the
  established delta touched (`DeltaScope.resolution_paths` -- empty
  whenever the delta could not actually be established, so the gate
  fails closed); and evidence the new commits removed the cited code --
  every quoted line among `DeltaScope.removed` (the range patches'
  removed lines, the ones the turn's `range_diff` shows) for that file,
  within the finding's cited span. Without any one of the three the
  finding stays carried, and the refusal is named. A re-statement may
  not lower the recorded severity or trade the defect-introduced shape
  on model say-so (the D73 rule; round-3 Major C). Silence keeps the
  finding -- carried in its original wording, re-offered to the next
  review -- so nothing is silently dropped.

Both calls -- the coordinator's decision and the carry-forward -- spend
against the review's shared `Spend` (D68's derived limits and dollar
ceiling) like every other call. The carry-forward's reply shape is
validated with the same finding-contract parsers the re-assessment reply
uses; the decision's reply shape is validated against the planned lens
names, and any contract failure falls back to re-running every lens --
the safe direction, never a silent reuse.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from atlas_reviewer.attestation import CheckedFinding
from atlas_reviewer.domain import Omission, PrEvent
from atlas_reviewer.lens_contract import (
    MAX_FINDINGS,
    MAX_TEXT_CHARS,
    NO_OBJECT,
    Attribution,
    ContractError,
    DesignRef,
    Finding,
    LineRange,
    Location,
    Route,
    Severity,
    UnknownSeverity,
    Valence,
    WholeFile,
    dropped_note,
    last_fenced_object,
)
from atlas_reviewer.ports import BoundaryError, GitHubReader, Json
from atlas_reviewer.prompt import UntrustedBlock, fence, fence_rule
from atlas_reviewer.quotes import QuoteSource, SourceText
from atlas_reviewer.reassess import (
    PRIOR_LABEL_CHARS,
    ReassessFinding,
    ReassessReply,
    Withdrawn,
    reassess_finding,
)
from atlas_reviewer.reassess import (
    judge as judge_reply,
)
from atlas_reviewer.redact import (
    MIN_FIT_CHARS,
    TRUNCATION_MARKER,
    TRUNCATION_MARKER_CHARS,
    RedactedText,
    Redactor,
)

CARRY_TARGET_PREFIX = "Carry-forward target (from the controller):"
"""The carry-forward turn's first line, controller-written. The scripted
dry-run reviewer tells this turn from an ordinary first turn and from a
D73 re-assessment turn by it."""

CARRY_INSTRUCTIONS = """\
You are the carry-forward assessor of an automated code review. The pull
request's head moved after an earlier review finished; this review's
subject is the whole pull request at the current head, and the
incremental diff -- what the commits between the earlier review's head
and the current head changed -- is fenced below as the new material.
You are deciding what becomes of the earlier review's findings. Nothing
you write is posted anywhere; the operator reads the controller's draft
first.

The earlier review's findings are listed in the first turn's
prior-findings block, each labeled P1, P2, ..., with its location. Judge
each against the incremental diff:

- A prior finding the new commits did not affect: re-state it in
  `findings` with a `revises` key naming its label, its location and
  evidence re-anchored to the current files, and a `reason` key stating
  what, if anything, moved. A re-statement is quote-checked against the
  current files exactly like an ordinary finding's quote; one that does
  not verify is not carried as verified. A re-statement cannot lower the
  recorded severity, or move the finding off defect-introduced: the
  controller keeps the recorded severity and shape, with your
  re-anchored location and wording, and names what you proposed.
- A prior finding the new commits fixed: name its label in `withdrawn`
  with a `reason` key stating what fixed it, and an `evidence` key
  quoting the line or lines of the prior finding's code that the
  commits between the two heads removed -- the `-` lines of the
  incremental diff's patches for that file, at a position within the
  finding's cited lines. The controller accepts a resolution only when
  every line you quote is among those removed lines, near where the
  finding cited: that is the evidence the new commits took the cited
  code out. Anywhere else -- a file the new commits never touched, a
  quote that is not among the removed lines or not near the citation --
  the resolution is recorded as your proposal and the finding stands.
- A prior finding you cannot judge: say nothing about it. It is carried
  in its original wording, never silently dropped.

Report nothing else in `findings`: new findings are the lenses' work,
not yours, and an entry with no `revises` key is not a re-statement.

When you are done, reply with exactly one JSON object and nothing else:
{"findings": [...], "withdrawn": [...]}. Each entry of `findings` has
the keys location, evidence, severity, valence, route, attribution,
finding and fix, and optionally siblings, with the values the Finding
contract below defines, plus the `revises` and `reason` keys this
preamble defines. Each entry of `withdrawn` is an object with exactly
the keys `id`, `reason` and `evidence`. Severity is exactly one of
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
    return "\n\n".join((CARRY_INSTRUCTIONS, fence_rule(nonce), contract))


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

    A record's finding line is `{id} {severity} "{location}" {finding}` --
    the shape the controller writes, the location quoted so a path that
    contains a space cannot be misread as the finding's first word. The
    unquoted legacy form (`{id} {severity} {location} {finding}`) is
    still read, for records written before the quote; its location token
    is one space-free token by construction, and a line whose third
    token cannot be a location is refused rather than guessed, so a
    garbled line is named and carried as raw text, never mis-parsed.
    A carried finding is reconstructed defect-introduced (it set the
    earlier review's verdict once), with no fix or evidence text,
    because the record stores neither. None when the line is not that
    shape; the caller carries it as raw text and names it, never drops
    it."""
    parts = line.split(" ", 2)
    if len(parts) != 3:
        return None
    identifier, severity, rest = parts
    if PRIOR_ID.fullmatch(identifier) is None:
        return None
    known = _SEVERITIES.get(severity)
    if known is None:
        return None
    if rest.startswith('"'):
        # The quoted form: the location may contain spaces, so it ends at
        # its closing quote, not at the next space.
        end = rest.find('"', 1)
        if end < 0 or not rest[end + 1 :].startswith(" "):
            return None
        location = rest[1:end]
        text = rest[end + 2 :]
        place = _parse_location(location)
    else:
        # The legacy form's location is one space-free token, so only a
        # line-range location is unambiguous: a bare token could equally
        # be the first word of a location that contains a space, and
        # guessing a whole-file path out of it would corrupt the finding
        # silently. Such a line is refused here, so the caller names it
        # and carries it as raw text.
        location, _, text = rest.partition(" ")
        place = (
            _line_range(location)
            if not location.startswith(_DESIGN_PREFIXES) and '"' not in location
            else None
        )
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


def _line_range(text: str) -> LineRange | None:
    span = re.fullmatch(r"(.+):([1-9][0-9]*)(?:-([1-9][0-9]*))?", text)
    if span is None:
        return None
    end = span.group(3)
    return LineRange(
        span.group(1), int(span.group(2)), int(end) if end else int(span.group(2))
    )


def _parse_location(text: str) -> Location | None:
    """A location as the Finding contract accepts it: `path:span`, a
    whole file's path, or a `boundary:`/`component:` reference."""
    if text.startswith(_DESIGN_PREFIXES):
        return DesignRef(text)
    span = _line_range(text)
    if span is not None:
        return span
    return WholeFile(text)


# ---------------------------------------------------------------- scope


@dataclass(frozen=True)
class DeltaScope:
    """What is new since the earlier review, and what a resolution may
    be accepted for -- not a lens scope (D83).

    The review's lenses run on the whole pull request's diff at the new
    head; the scope never narrows them. `resolution_paths` is the set of
    paths a resolution proposal may be accepted for -- empty whenever
    the delta could not actually be established (an unfetchable range,
    a diverged history, a cut or malformed comparison), because the
    resolution gate must fail closed, never open: with no established
    delta there is no evidence the new commits changed anything, so
    nothing is resolvable and every prior finding is carried. `note` is
    controller text naming the fallback or gap, empty when the delta is
    the real delta; `gate_reason` is the clause a refused resolution is
    named with, empty when the ordinary "the delta did not touch the
    file it cites" applies."""

    delta_from: str
    resolution_paths: frozenset[str]
    note: str = ""
    gate_reason: str = ""
    removed: Mapping[str, tuple[tuple[int, str], ...]] = field(default_factory=dict)
    """The range's own removed lines, per file, as ``(old-side line
    number, text)`` pairs read from the comparison's per-file patches --
    the `delta_from..head` range's deletions, not the pull request's
    `base...head` net diff. This is the pool a resolution's evidence is
    checked against, so evidence always means "the new commits removed
    this code": a line the PR removed before `delta_from` is not here,
    and a delta commit's deletion of PR-added code is (round-2 review of
    #748, Major A). Empty whenever the delta is not established."""
    range_diff: str = ""
    """The range's own per-file patches, rendered: what the commits
    between the heads actually changed -- the incremental diff the
    payload highlights and the carry-forward turn carries, which the
    pull request's net diff cannot show (a delta commit deleting
    PR-added code is invisible in a net diff where the line exists at
    neither end). Empty when the delta is not established, and when it
    is established but its comparison carried no readable patch."""


def delta_scope(github: GitHubReader, event: PrEvent) -> DeltaScope:
    """The delta review's scope, from one range comparison.

    The scope is what is new (`delta_from..head`'s touched paths, the
    range's own removed lines and per-file patches) and what a
    resolution may be accepted for. It is not the review's diff: the
    lenses run on the whole pull request's diff at the new head, whose
    three-dot form never carries merge-from-base content anyway (the
    merge moves the base forward and the base's changes drop out of it),
    so the whole-changeset subject and the incremental payload need no
    per-commit reads to reconcile.

    Three conditions refuse the delta as the resolution gate's evidence,
    each named on the scope's note and each leaving `resolution_paths`
    empty: a range that cannot be fetched at all; a comparison whose
    merge base is not `delta_from` -- a rebase or a force-push, after
    which the comparison's file list is measured from the wrong base and
    is not the range's; and a file list that is missing, malformed, or
    cut at GitHub's comparison cap, which cannot prove what the range
    touched. On any of the three the review is an ordinary full review
    of the pull request -- there is no incremental diff to carry, so no
    lens payload narrows and no lens is reused (D83) -- and no resolution
    is accepted."""
    try:
        compare = github.get_compare(event.repo, event.delta_from, event.head_sha)
        names, complete = _range_paths(compare)
    except BoundaryError as exc:
        return DeltaScope(
            event.delta_from,
            frozenset(),
            f"the delta range could not be fetched ({type(exc).__name__}); "
            "the review ran on the full pull request diff, and no "
            "resolution is accepted",
            "the delta range could not be established",
        )
    if _diverged(compare, event.delta_from):
        # A wrong-base list cannot prove what the range touched, so it
        # bounds nothing: the review runs on the whole pull request and
        # no lens is reused on evidence it cannot back (round-5 review
        # of #748; D83).
        return DeltaScope(
            event.delta_from,
            frozenset(),
            "the range comparison shows the histories diverged (a rebase or "
            "a force-push); the review ran on the full pull request diff, "
            "and no resolution is accepted",
            "the delta could not be established: the histories diverged",
        )
    if not complete:
        # Same rule as the diverged case: a cut or malformed list cannot
        # prove what the range touched, so nothing narrows to it -- the
        # files past the cap would reach no lens while the coverage read
        # complete (round-5 review of #748).
        return DeltaScope(
            event.delta_from,
            frozenset(),
            "the range comparison's file list was cut or malformed, so the "
            "delta's touched paths are not fully known; the review ran on "
            "the full pull request diff, and no resolution is accepted",
            "the delta's touched paths are not fully known",
        )
    removed, range_diff = _range_removals(compare)
    return DeltaScope(
        event.delta_from,
        # The gate is the range's own touched paths: a follow-up that
        # DELETES a file the earlier head added takes that file out of
        # the pull request's net diff entirely, while the range's patch
        # holds the cited removal -- the one case where the resolution
        # is real (round-5 review of #748). A path the range touched
        # without a patch still refuses on evidence, the safe direction.
        frozenset(names),
        removed=removed,
        range_diff=range_diff,
    )


def _range_removals(
    compare: Json,
) -> tuple[Mapping[str, tuple[tuple[int, str], ...]], str]:
    """The range's own removed lines, from the comparison's per-file
    patches, and the patches rendered as one diff for the carry-forward
    turn.

    The comparison of `delta_from..head` measures its patches from the
    old head, so a removed line's old-side number is a line of the head
    the earlier review verified -- the coordinates the prior findings'
    locations cite. A file whose patch is absent (an empty or binary
    change, or a patch GitHub declined to serve) contributes no pool
    entries: a resolution for it then finds no evidence and is refused,
    the safe direction, without touching the scope's own trustworthiness
    (the paths are still known from the file list)."""
    files = compare.get("files")
    if not isinstance(files, list):
        return {}, ""
    removed: dict[str, tuple[tuple[int, str], ...]] = {}
    rendered: list[str] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        name = item.get("filename")
        patch = item.get("patch")
        if not isinstance(name, str) or not name or not isinstance(patch, str):
            continue
        entries = _patch_removed(patch)
        if name not in seen:
            seen.add(name)
            header = f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n"
            rendered.append(header + patch)
        if entries:
            # A rename's patch measures its old-side lines from the file
            # the patch removes from -- `previous_filename` -- which is
            # the path the earlier review's finding cites; keyed by the
            # new name alone, a withdrawal of code the rename's commit
            # deleted could never find its evidence (round-5 review of
            # #748). The rendered turn keeps the new name, the lens
            # scope's.
            evidence_path = item.get("previous_filename")
            key = (
                evidence_path
                if isinstance(evidence_path, str) and evidence_path
                else name
            )
            removed[key] = entries
    return removed, "\n".join(rendered)


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+")


def _patch_removed(patch: str) -> tuple[tuple[int, str], ...]:
    """A unified-diff patch's removed lines with their old-side line
    numbers: each `@@ -a,b` hunk header sets the old side's counter, and
    each `-` line (the `---` header is not a hunk line) consumes one.
    The patch is split on LF only: a U+2028 or vertical tab inside a
    patch line is content, not a record boundary, and splitting on it
    would shift every later number in the hunk (round-5 review of
    #748)."""
    removed: list[tuple[int, str]] = []
    old_side = 0
    for line in patch.split("\n"):
        header = _HUNK.match(line)
        if header is not None:
            old_side = int(header.group(1))
            continue
        if line.startswith("\\"):
            # `\ No newline at end of file`: a marker about the
            # neighboring line, not content on either side -- it moves
            # no counter (round-3 review of #748, a7: without this, a
            # trailing marker shifted every later number in the hunk).
            continue
        if old_side == 0 and (line == "---" or line.startswith("--- ")):
            # A `---` FILE HEADER can only sit before the first hunk;
            # past it, a `---`-shaped line is removed content -- a SQL
            # or Lua comment -- and counts (round-3 review of #748,
            # a7: the blanket exclusion ate those).
            continue
        if old_side and line.startswith("-"):
            removed.append((old_side, line[1:]))
            old_side += 1
        elif old_side and not line.startswith("+"):
            old_side += 1
    return tuple(removed)


_COMPARE_FILES_CAP = 300
"""GitHub's comparison response caps its `files` array; a list at the cap
may be cut, and a cut list cannot prove what the range touched."""


def _range_paths(compare: Json) -> tuple[tuple[str, ...], bool]:
    """The comparison's changed paths, and whether the list is complete.

    A missing or non-array `files` raises: a comparison reply without one
    is not a comparison reply this reader can trust. Entries that are not
    objects, or that name no path, make the list incomplete -- what they
    would have named is unknown -- and a list at the comparison cap may
    be cut, which is incomplete the same way."""
    files = compare.get("files")
    if not isinstance(files, list):
        raise BoundaryError("the comparison has no files array")
    paths: list[str] = []
    complete = len(files) < _COMPARE_FILES_CAP
    for item in files:
        name = item.get("filename") if isinstance(item, dict) else None
        if isinstance(name, str) and name:
            paths.append(name)
            # A rename touches both its names: the prior findings cite
            # the old path, the lens scope and the rendered diff use the
            # new one, and the resolution gate must accept the path the
            # finding actually cites (round-5 review of #748).
            previous = item.get("previous_filename")
            if isinstance(previous, str) and previous:
                paths.append(previous)
        else:
            complete = False
    return tuple(paths), complete


def _diverged(compare: Json, delta_from: str) -> bool:
    """True unless the comparison proves its own base: a merge base that
    is missing, malformed, or not `delta_from` all read as diverged --
    the one malformed shape the fail-closed rework missed read as
    trusted, and benign kinds are claimed on evidence, never by default
    (round-2 review of #748, a1)."""
    base = compare.get("merge_base_commit")
    sha = base.get("sha") if isinstance(base, dict) else None
    return not (isinstance(sha, str) and sha == delta_from)


DELTA_DIFF_CHARS = 32_768
"""The incremental diff's cap, wherever it travels: the coordinator's
decision turn, the lenses' delta highlight block and the carry-forward
turn all carry the range's own per-file patches cut to this size with
the truncation marker, rather than costing the call or the first turn
its evidence to the per-call token check (#702, D83)."""

# ------------------------------------------ the coordinator's decision (D83)


DECISION_TARGET_PREFIX = "Lens decisions target (from the controller):"
"""The coordinator-decision turn's first line, controller-written. The
   scripted dry-run reviewer tells this turn from an ordinary first turn,
   from a D73 re-assessment turn and from the carry-forward turn by it."""

DECISION_INSTRUCTIONS = """\
You are the coordinator of an automated code review's follow-up round.
The pull request's head moved after an earlier review finished; this
follow-up's subject is the whole pull request at the current head, and
the incremental diff -- what the commits between the earlier review's
head and the current head changed -- is fenced below as the new
material, next to the fresh evidence around the pull request (newer CI
results, newer comments) that the lenses this round will also see. You
are deciding, for each lens named below, whether this follow-up re-runs
it or reuses the earlier review's settled result. Nothing you write is
posted anywhere; the operator reads the controller's draft first.

- Re-run the lens when the incoming changes could affect its concern:
  it runs again on the whole pull request, with the incremental diff
  highlighted, and may report findings anywhere in the pull request,
  including on content the incremental diff does not touch.
- Reuse the earlier result when the incoming changes could not affect
  its concern: the lens does not run; its earlier findings stand,
  carried forward and re-assessed against the new evidence, and a
  resolution of one of them still needs the controller's evidence gate.

The decision is your judgment over the incoming changes -- there is no
fixed rule tying it to which files the incremental diff touched. Judge
each lens on its own concern -- the one-line concern summary under each
name -- and say in the reason what in the incoming changes drove the
call. A lens marked as citing the incremental diff is the highest-
stakes reuse: its earlier findings sit on code the new commits touched.

When you are uncertain, re-run. A reuse the incoming changes would have
contradicted silently shrinks this round's evaluation; an unnecessary
re-run costs bounded calls under the review's ceiling, and a missed
defect does not.

When you are done, reply with exactly one JSON object and nothing else:
{"decisions": [{"lens": ..., "decision": ..., "reason": ...}, ...]}.
Cover every lens named below exactly once. `decision` is exactly
"rerun" or "reuse". The reason is one sentence. Do not call a tool;
this turn has none."""


@dataclass(frozen=True)
class LensDecision:
    """The coordinator's decision for one planned lens of a delta review
    (D83): re-run it on the whole pull request, or reuse the earlier
    review's settled result. Every planned lens has exactly one.

    `flagged` marks a reuse-eligible lens whose earlier findings cite
    files the incremental diff touches -- the signal the decision turn
    carries so the judgment weighs it, recorded with the decision. The
    re-assessment fields (D73, round-1 review of #760) record what the
    reused lens's bounded re-assessment against the newer CI and
    conversation evidence decided: `reassessed` whether one ran,
    `reassess_note` the controller note, `withdrawn` the annotations --
    a withdrawal removes nothing, and a revision that would lower a
    Blocker's or a Major's severity is annotation-only, exactly as the
    ledger-reuse path's re-assessments compose."""

    lens: str
    reuse: bool
    reason: str
    flagged: bool = False
    reassessed: bool = False
    reassess_note: str = ""
    withdrawn: tuple[Withdrawn, ...] = ()
    gained_findings: bool = False
    """True when the reused lens's D73 re-assessment ADDED findings this
    round (round-2 review of #760): its settled result changed, so it is
    not recorded in the round record's `clean_lenses` and the next delta
    re-runs it. A reused lens the re-assessment left unchanged stays
    recorded, and the reuse chain does not decay."""


def decision_system(nonce: str) -> str:
    """The decision call's system prompt: the instructions and the fence
    rule for the review's one nonce. There is no finding contract to
    attest: the reply names decisions, not findings."""
    return "\n\n".join((DECISION_INSTRUCTIONS, fence_rule(nonce)))


def decision_turn(
    event: PrEvent,
    offered: Sequence[tuple[str, str | None, bool]],
    delta: UntrustedBlock | None,
    context: Sequence[UntrustedBlock],
    nonce: str,
) -> str:
    """The decision call's one user turn: the controller's subject, the
    lenses a reuse is available for -- each with its one-line concern
    summary from the bundle, so the judgment weighs the concern and not
    the name alone, and flagged when its earlier findings cite files the
    incremental diff touches (D83, round-1 review of #760) -- then the
    incremental diff and the fresh evidence around the pull request (the
    conversation and CI blocks the lenses get, D73), each fenced with
    the review's one nonce."""
    subject = f"{event.repo}#{event.pr_number} at {event.head_sha}"
    lines = []
    for name, concern, flagged in offered:
        line = f"- {name}"
        if concern:
            line += f" -- {concern}"
        if flagged:
            line += " (its earlier findings cite files the incremental diff touches)"
        lines.append(line)
    parts = [
        f"{DECISION_TARGET_PREFIX}{subject}",
        ("Lenses with a settled result from the earlier review, each to be decided:"),
        "\n".join(lines),
    ]
    if delta is not None:
        parts.append(fence(delta, nonce))
    parts.extend(fence(block, nonce) for block in context)
    return "\n\n".join(parts)


DECISION_REASON_CHARS = 600
"""A decision reason's cap, matched to the draft's quoting default: a
reason the model cannot state in one sentence is not one sentence, and
the draft quotes it with the same bound."""


def validated_decision(index: int, raw: Any, known: set[str]) -> LensDecision:
    """One decision entry, validated: an object with exactly the keys
    `lens`, `decision` and `reason`, all strings; a lens the offered set
    holds; a decision of exactly `rerun` or `reuse`; a non-blank reason
    within `DECISION_REASON_CHARS`. Shared by the reply's parser and the
    scenario loader, so a scripted scenario cannot load a reply shape
    the live parser would refuse mid-run."""
    if not isinstance(raw, dict) or set(raw) != {"lens", "decision", "reason"}:
        raise ContractError(
            f"decision entry {index}: must be an object with exactly "
            "the keys lens, decision and reason"
        )
    lens, decision, reason = raw["lens"], raw["decision"], raw["reason"]
    if not all(isinstance(value, str) for value in (lens, decision, reason)):
        raise ContractError(
            f"decision entry {index}: lens, decision and reason must be strings"
        )
    if len(lens) > MAX_LENS_CHARS or lens not in known:
        raise ContractError(
            f"decision entry {index}: the lens named is not one the earlier review ran"
        )
    if decision not in ("rerun", "reuse"):
        raise ContractError(
            f"decision entry {index}: decision must be exactly 'rerun' or 'reuse'"
        )
    if not reason.strip():
        raise ContractError(
            f"decision entry {index}: a decision states what in the "
            "incoming changes drove it"
        )
    if len(reason) > DECISION_REASON_CHARS:
        raise ContractError(
            f"decision entry {index}: the reason is over "
            f"{DECISION_REASON_CHARS} characters"
        )
    return LensDecision(lens, decision == "reuse", reason)


def parse_decision_reply(text: str, offered: Sequence[str]) -> tuple[LensDecision, ...]:
    """The decision reply: one JSON object `{"decisions": [...]}`, bare
    or as the last fenced object, covering every offered lens exactly
    once.

    The reply is judged strictly: an entry whose keys, decision value,
    reason or lens name breaks the contract, a lens named twice, a lens
    never offered -- a name the plan does not hold -- and a lens left
    out all raise `ContractError`, and the caller falls back to
    re-running every lens, the safe direction (D83). A reuse can never
    be invented: only a lens the earlier review actually ran is offered,
    and the offer itself is the controller's, read from the round
    record."""
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = last_fenced_object(stripped)
        if data is NO_OBJECT:
            raise ContractError("the reply is not one JSON object") from None
    if not isinstance(data, dict) or set(data) != {"decisions"}:
        raise ContractError("the reply must be an object with the key decisions")
    entries = data["decisions"]
    if not isinstance(entries, list):
        raise ContractError("decisions must be a list")
    known = set(offered)
    decided: dict[str, LensDecision] = {}
    for index, raw in enumerate(entries, 1):
        decision = validated_decision(index, raw, known)
        if decision.lens in decided:
            raise ContractError(
                f"decision entry {index}: {decision.lens!r} is decided twice"
            )
        decided[decision.lens] = decision
    missing = sorted(known - set(decided))
    if missing:
        raise ContractError("the reply left undecided: " + ", ".join(missing))
    return tuple(decided[lens] for lens in offered)


MAX_LENS_CHARS = 200
"""A decision entry's lens-name bound: a name longer than any bundled
lens's name is not a lens, and capping before the membership test keeps
an oversized injected string out of the refusal's text."""


def fallback_decisions(offered: Sequence[str], why: str) -> tuple[LensDecision, ...]:
    """The decision call's fallback (D83): every offered lens re-runs.
    Re-running is the safe direction -- a reuse the incoming changes
    would have contradicted never happens on a failed or refused
    judgment; the only cost is the calls the reuse would have saved."""
    return tuple(LensDecision(lens, False, why) for lens in offered)


def capped(text: str, cap: int) -> str:
    """The incremental diff as a turn or block carries it: cut with the
    truncation marker when it is over the cap, the marker inside the cap,
    so the per-call token check is never the reason a call loses its
    evidence. A truncated delta still judges resolutions safely: the
    evidence pool is the scope's own structured record, and an assessor
    that cannot see a removed line cannot quote it, so its resolution is
    refused either way (round-2 a4)."""
    if len(text) <= cap:
        return text
    return text[: cap - TRUNCATION_MARKER_CHARS] + TRUNCATION_MARKER


# ------------------------------------------------------ the highlight block


DELTA_BLOCK_SOURCE = "delta diff"
DELTA_BLOCK_LABEL = "delta-diff"


def delta_block(
    delta: DeltaScope, room: int | None, redactor: Redactor
) -> tuple[UntrustedBlock | None, tuple[Omission, ...]]:
    """The incremental diff as one bounded block for an agentic first
    turn (D83): what the commits between the reviewed head and this head
    changed -- the new material -- highlighted ahead of the whole pull
    request's diff the lens reads through its tools.

    Sized like the CI block (D73) within D67's input-room budgeting: the
    caller passes what the conversation and CI blocks left of the room,
    so the context blocks together cannot exceed the fit. A block over
    its cap is truncated with the marker and the cut named; one whose
    bytes still overflow the room is omitted whole and named -- never
    silently truncated, never sent to overflow the per-call token check.
    An empty delta -- a merge-only push, or an established comparison
    whose files carry no readable patch -- builds no block: there is no
    new material to highlight, and the changed-files listing already
    shows the whole pull request. So does a delta that could not be
    established: the review is then an ordinary full review, with no
    incremental payload to send."""
    if delta.note or not delta.range_diff:
        return None, ()
    if room is not None and room < MIN_FIT_CHARS:
        return None, (_left_out(room),)
    budget = (
        DELTA_DIFF_CHARS
        if room is None
        else min(DELTA_DIFF_CHARS, room - TRUNCATION_MARKER_CHARS)
    )
    # The one controller-written line in the block: which base the
    # incremental diff is measured from (D25's tag), so the block cannot
    # be read against another commit later in the same conversation.
    text = (
        f"The incremental diff: what the commits between the earlier "
        f"review's head {delta.delta_from} and the reviewed head changed:\n\n"
        f"{delta.range_diff}"
    )
    content = redactor(text, budget)
    if room is not None and len(content.text.encode("utf-8")) > room:
        return None, (_left_out(room),)
    return UntrustedBlock(DELTA_BLOCK_LABEL, content), _truncation_omissions(
        content, budget
    )


def _left_out(room: int) -> Omission:
    return Omission(
        DELTA_BLOCK_SOURCE,
        "model input room",
        f"the model's input room cannot hold the delta-diff block ({room} "
        "characters left for the context blocks), so it was left out",
    )


def _truncation_omissions(content: RedactedText, cap: int) -> tuple[Omission, ...]:
    if content.truncated_from is None:
        return ()
    return (
        Omission(
            DELTA_BLOCK_SOURCE,
            f"{cap}-character cap",
            f"kept {cap} of {content.truncated_from} characters",
        ),
    )


# ------------------------------------------------- the reply and its judge


@dataclass(frozen=True)
class CarryReply:
    findings: tuple[ReassessFinding, ...]
    withdrawn: tuple[tuple[str, str, str], ...]
    dropped: tuple[str, ...] = ()


def parse_carry_reply(text: str) -> CarryReply:
    """The carry-forward reply: one JSON object `{"findings",
    "withdrawn"}` -- `withdrawn` optional -- bare or as the last fenced
    object, with each finding entry validated exactly as the
    re-assessment reply's are (`revises` with its `reason`). A withdrawn
    entry is `{"id", "reason", "evidence"}`: the resolution's stated
    reason and the quoted line or lines of the prior finding's code that
    the delta removed -- a withdrawal without either is refused, because
    the reason and the evidence are what a reader and the controller's
    own check rely on. There is no lens or body acknowledgement: the
    assessor is the controller's own, not a lens."""
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = last_fenced_object(stripped)
        if data is NO_OBJECT:
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
            parsed.append(reassess_finding(index, raw))
        except UnknownSeverity as exc:
            dropped.append(dropped_note(exc, raw))
    return CarryReply(
        tuple(parsed),
        tuple(_resolution_entry(i, raw) for i, raw in enumerate(withdrawn, 1)),
        tuple(dropped),
    )


def _resolution_entry(index: int, raw: Any) -> tuple[str, str, str]:
    if not isinstance(raw, dict) or set(raw) != {"id", "reason", "evidence"}:
        raise ContractError(
            f"withdrawn entry {index}: must be an object with exactly the "
            "keys id, reason and evidence"
        )
    prior, reason, evidence = raw["id"], raw["reason"], raw["evidence"]
    if (
        not isinstance(prior, str)
        or not isinstance(reason, str)
        or not isinstance(evidence, str)
    ):
        raise ContractError(
            f"withdrawn entry {index}: id, reason and evidence must be strings"
        )
    if not prior.strip() or not reason.strip() or not evidence.strip():
        raise ContractError(
            f"withdrawn entry {index}: a resolution carries the reason the "
            "new commits fixed the finding and the quoted code they removed"
        )
    if len(prior) > PRIOR_LABEL_CHARS:
        raise ContractError(
            f"withdrawn entry {index}: id is over {PRIOR_LABEL_CHARS} characters"
        )
    for value in (reason, evidence):
        if len(value) > MAX_TEXT_CHARS:
            raise ContractError(
                f"withdrawn entry {index}: a resolution's reason and evidence "
                f"are each over {MAX_TEXT_CHARS} characters"
            )
    return prior, reason, evidence


def judged_carry(
    reply: CarryReply,
    prior: Sequence[tuple[str, Finding]],
    sources: SourceText,
    head_tree: bytes,
    tolerance: int,
) -> tuple[tuple[CheckedFinding, ...], tuple[tuple[int, str, str], ...]]:
    """The reply's findings quote-checked and its resolution labels
    resolved, through the re-assessment judge itself (the finding shape
    is the same minus the lens acknowledgement), so the two paths' quote
    checks cannot drift apart. The prior findings all take part: each was
    a verified finding of the review it came from, and the labels the
    reply names resolve against all of them. A resolution's evidence is
    not the judge's to check: it is checked against the delta's removed
    lines, which the judge never sees."""
    checked_prior = [
        CheckedFinding(finding, QuoteSource.HEAD) for _id, finding in prior
    ]
    shim = ReassessReply(
        "",
        "0" * 64,
        reply.findings,
        tuple(
            (identifier, reason) for identifier, reason, _evidence in reply.withdrawn
        ),
        reply.dropped,
    )
    judged = judge_reply(shim, checked_prior, sources, head_tree, tolerance)
    return judged.checked, judged.revises


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
    there, on evidence the new commits removed its cited code. `notes`
    is controller text for the draft."""

    carried: tuple[tuple[str, CheckedFinding], ...]
    unanchored: tuple[tuple[str, Finding], ...]
    resolved: tuple[tuple[str, str, Finding], ...]
    notes: tuple[str, ...] = ()


def apply_carry(
    prior: Sequence[tuple[str, Finding]],
    checked: Sequence[CheckedFinding],
    revises: Sequence[tuple[int, str, str]],
    withdrawn: Sequence[tuple[str, str, str]],
    resolution_paths: frozenset[str],
    removed_lines: Mapping[str, tuple[tuple[int, str], ...]],
    gate_reason: str = "",
    tolerance: int = 0,
) -> CarryResult:
    """The reply's judgment composed over the prior findings.

    `checked` is the reply's quote-checked findings in reply order,
    `revises` their `(index, label, reason)` references, `withdrawn` the
    resolution proposals as `(label, reason, evidence)`. Every prior
    finding ends in exactly one of the three buckets; nothing is dropped.

    A resolution is accepted only on all three of: the model's proposal
    with its stated reason; the prior finding's file being one the
    established delta touched (`resolution_paths` -- empty whenever the
    delta could not be established, which refuses every resolution); and
    real evidence that the new commits removed the cited code -- every
    non-blank line of the proposal's `evidence` quoting a line among the
    RANGE's own removed lines for that file (`delta_from..head`, the
    comparison's per-file patches -- not the pull request's net diff,
    where a delta commit's deletion of PR-added code is invisible and a
    pre-delta removal sits in the pool; round-2 review of #748, Major
    A), and each quoted line's old-side position within the finding's
    cited span widened by `tolerance` (round-2 a2: any removed line in
    the file, down to a one-line brace, used to clear the gate).
    Without any one of the three the finding stays carried, and the
    refusal is named.

    An entry with no `revises` key is not a re-statement and is not a
    prior disposition; it is dropped from the buckets and named in the
    notes, because new findings on the delta are the lenses' work."""

    restated: dict[str, CheckedFinding] = {}
    for index, label, _reason in revises:
        if 1 <= index <= len(checked) and checked[index - 1].verified:
            restated[label] = checked[index - 1]
    carried: list[tuple[str, CheckedFinding]] = []
    unanchored: list[tuple[str, Finding]] = []
    resolved: list[tuple[str, str, Finding]] = []
    notes: list[str] = []
    added = len(checked) - len(revises)
    if added > 0:
        notes.append(
            f"the carry-forward reply added {added} finding(s) with no "
            "revises label; they are not carried -- new findings on the "
            "delta are the lenses' work"
        )
    withdrawn_labels = {label for label, _reason, _evidence in withdrawn}
    for identifier, finding in prior:
        if identifier in restated:
            replacement = restated[identifier]
            if _weakens(replacement.finding, finding):
                # A re-statement may re-anchor and revise wording, but it
                # cannot lower the recorded severity, or trade the
                # defect-introduced shape for one that leaves the
                # verdict-setting set, on model say-so -- the D73
                # re-assessment path's own rule (round-3 review of #748,
                # Major C): the composed finding carries the recorded
                # severity, valence and attribution with the re-anchored
                # location, evidence and wording, and the proposed
                # weakening is named. Mutant: the guard dropped -- a
                # carried Blocker restated as a nit flips the verdict to
                # approve.
                composed = replace(
                    replacement.finding,
                    severity=finding.severity,
                    valence=finding.valence,
                    attribution=finding.attribution,
                )
                carried.append(
                    (
                        identifier,
                        CheckedFinding(
                            composed,
                            replacement.source,
                            drift=replacement.drift,
                        ),
                    )
                )
                notes.append(
                    f"{identifier}: a re-statement proposed "
                    f"{_weakened_as(finding, replacement.finding)}; the "
                    "recorded severity and shape stand"
                )
            else:
                carried.append((identifier, replacement))
            continue
        if identifier in withdrawn_labels:
            proposal = next(
                (label, reason, evidence)
                for label, reason, evidence in withdrawn
                if label == identifier
            )
            _label, reason, evidence = proposal
            path = _cited_path(finding.location)
            quoted = _quoted_removed(
                evidence, finding.location, path, removed_lines, tolerance
            )
            if path is not None and path in resolution_paths and quoted:
                resolved.append((identifier, reason, finding))
                continue
            unanchored.append((identifier, finding))
            if path is None or path not in resolution_paths:
                why = gate_reason or "the delta did not touch the file it cites"
                notes.append(
                    f"{identifier}: a resolution was proposed, but {why}, so it stands"
                )
            else:
                notes.append(
                    f"{identifier}: a resolution was proposed, but its quoted "
                    "code is not among the lines the delta removed, so it "
                    "stands"
                )
            continue
        unanchored.append((identifier, finding))
    for label, _reason, _evidence in withdrawn:
        if label not in {identifier for identifier, _finding in prior}:
            notes.append(f"{label}: the resolution named no prior finding")
    return CarryResult(tuple(carried), tuple(unanchored), tuple(resolved), tuple(notes))


def _quoted_removed(
    evidence: str,
    location: Location,
    path: str | None,
    removed_lines: Mapping[str, tuple[tuple[int, str], ...]],
    tolerance: int,
) -> bool:
    """Whether every non-blank line of a resolution's quoted evidence is a
    line the delta's range removed from the finding's file, at a position
    within the finding's cited span widened by `tolerance` -- the same
    slack the quote checker reads citations with. Whitespace is ignored
    on both sides: the model quotes the code, the diff holds it with its
    indentation. A whole-file location has no span to bound, so any
    removed line of the file is in bounds; a design reference cites no
    file and is refused by the caller's path check."""
    if path is None or not evidence.strip():
        return False
    entries = removed_lines.get(path, ())
    if not entries:
        return False
    quoted = [line.strip() for line in evidence.splitlines() if line.strip()]
    for line in quoted:
        if not any(
            text.strip() == line and _in_span(number, location, tolerance)
            for number, text in entries
        ):
            return False
    return True


def _in_span(number: int, location: Location, tolerance: int) -> bool:
    if isinstance(location, LineRange):
        return location.start - tolerance <= number <= location.end + tolerance
    return isinstance(location, WholeFile)


def _weakens(replacement: Finding, prior: Finding) -> bool:
    """Whether a re-statement would leave the verdict-setting set weaker
    than the recorded finding: a lower severity, or a valence or
    attribution moved off defect-introduced. A restatement may raise --
    the conservative direction takes it -- and may revise wording,
    location and evidence freely."""
    if replacement.severity.rank > prior.severity.rank:
        return True
    return (
        prior.valence is Valence.DEFECT and replacement.valence is not Valence.DEFECT
    ) or (
        prior.attribution is Attribution.INTRODUCED
        and replacement.attribution is not Attribution.INTRODUCED
    )


def _weakened_as(prior: Finding, replacement: Finding) -> str:
    """The weakening, named: the recorded value and the proposed one,
    for the note the draft carries."""
    if replacement.severity.rank > prior.severity.rank:
        return f"lowering {prior.severity.value} to {replacement.severity.value}"
    if prior.valence is not replacement.valence:
        return f"making it {replacement.valence.value}"
    return f"making it {replacement.attribution.value}"


def _cited_path(location: Location) -> str | None:
    if isinstance(location, LineRange | WholeFile):
        return location.path
    return None
