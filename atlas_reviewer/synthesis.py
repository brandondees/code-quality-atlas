# SPDX-License-Identifier: MIT
"""The per-review merge/verify call (the plan's step 7, issues #822 and
#823): one bounded, tool-less model call after the lenses settle, that
merges, reconciles and verifies the deduped findings the way the Claude
Code protocol's coordinator synthesis does.

The controller-side dedupe (`atlas_reviewer/dedupe.py`) collapses only
what it can prove identical -- the same target and the same claim, word
for word. What it cannot prove is judgment: two lenses reporting one
defect in different words, two lenses pulling opposite ways on the same
lines, a finding whose line-numbered evidence does not hold up, a
finding the pull request's conversation already disputes or an earlier
round already settled. This call makes those judgments, over the
findings the controller already holds, with the review's own context
beside them.

The reply is untrusted model output proposing dispositions; the
controller reconciles every one of them against the findings it holds,
and the composition fails closed (D31, D54):

- A **cluster** (`ids` plus a reason) merges two or more findings into
  one: the cluster's strongest finding represents it, and every lens
  attribution in it travels on the representative. The merged-away ids
  are named on the representative's draft line, so nothing leaves the
  record silently.
- A **downgrade** (a strictly lower severity, with a reason) and a
  **drop** (with a reason) are recorded as proposals, exactly the D73
  re-assessment rule: the finding stays reported at its recorded
  severity and shape, annotated with the proposal and its reason, and
  the verdict is computed over the full verified set -- model output
  can lower a finding's visibility but never lower the verdict, and
  nothing is deleted on model say-so.
- A reply that cites an unknown finding id, names a finding twice,
  downgrades to a severity that is not strictly lower, drops or
  downgrades without a stated reason, or clusters findings that do not
  share the claim's shape -- the same verification standing, valence
  and attribution the mechanical dedupe requires -- is refused whole:
  the merge is then **not applied**, the review fails closed with
  REVIEW INCOMPLETE, and the draft keeps the unmerged findings with the
  refusal named.

The call spends against the review's shared `Spend` (D68's derived
limits and dollar ceiling) like every other call, reserved at its worst
case before it is sent and settled like any turn. A review with no
minted findings runs no merge call: there is nothing to merge, verify
or reconcile.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from atlas_reviewer.dedupe import stronger
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.findings import MintedFinding
from atlas_reviewer.lens_contract import (
    MAX_FINDINGS,
    NO_OBJECT,
    ContractError,
    Severity,
    last_fenced_object,
)
from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence, fence_rule

MERGE_TARGET_PREFIX = "Merge target (from the controller):"
"""The merge turn's first line. The controller writes the turn's first
message, so no PR-written text can open with it; the scripted models
key their answer on it."""

MERGE_REASON_CHARS = 600
"""A merge reason's cap, matched to the draft's quoting default: a
reason the model cannot state in one sentence is not one sentence, and
the draft quotes it with the same bound."""

MERGE_EVIDENCE_CHARS = 600
"""How much of a finding's quoted evidence the merge turn carries: the
call judges whether the quoted line-numbered evidence supports the
claim, not whether the quote verifies (the quote gate already did
that), so the quote itself, cut to the draft's quoting bound, is the
material."""

MERGE_PRIORS_CHARS = 8_192
"""The prior rounds' block cap in the merge turn: the recorded findings
the call checks disputes and repeat findings against, cut with the
truncation marker when a long history outgrows it -- a cut block still
judges safely, because every proposal stays an annotation the
controller reconciles either way."""

MERGE_INSTRUCTIONS = """\
You are the coordinator of an automated code review. Several review
lenses ran in isolation -- none saw another's findings -- and each
reported findings, which the controller quote-checked, deduplicated on
an exact match, minted IDs for and now hands to you. Nothing you write
is posted anywhere; the operator reads the controller's draft first.
The first turn carries the findings fenced as data, then the review's
context -- the pull request's conversation and CI evidence -- and the
prior review rounds recorded for this pull request, all fenced.

Judge the findings against each other and the context, and reply with
your dispositions:

- To merge findings that describe one defect in different words, add a
  `clusters` entry: `ids` naming two or more finding IDs that are one
  defect, and a `reason` naming what makes them one. The controller
  keeps the strongest of them and names the rest on it. Merge on a
  shared root cause, never on file proximity alone: two findings at
  nearby lines that describe different defects stay apart. The
  controller refuses a cluster whose findings do not share the same
  verification standing, valence and attribution -- a verified finding
  and one whose quote failed, an introduced defect and a pre-existing
  one -- so only restatements of the same claim can merge.
- When two findings conflict -- they read the same lines opposite ways
  -- judge which reading the evidence supports and downgrade or drop
  the one that does not hold, with the conflict named in the reason.
- Check the conversation and the prior rounds before judging: a defect
  the conversation already disputes, or that an earlier round already
  reported and had answered, is context your reasons must name, not a
  discovery.
- To downgrade a finding whose evidence does not support its severity,
  add a `dispositions` entry with `action` "downgrade", the `severity`
  you judge supported, and the `reason`. To propose dropping a finding
  whose line-numbered evidence does not hold up, add an entry with
  `action` "drop" and the `reason`. Every downgrade and drop carries
  its stated reason; one without is refused.
- Every disposition you name is recorded as your proposal: the finding
  stays reported with your reason attached, and the controller computes
  the verdict from its own verified findings. Never invent a finding no
  ID names, and never raise a severity.

Findings you say nothing about stand exactly as the controller holds
them. When you are done, reply with exactly one JSON object and nothing
else:
{"clusters": [{"ids": [...], "reason": "..."}],
 "dispositions": [{"id": "...", "action": "downgrade", "severity": "nit",
 "reason": "..."}]}. Both keys are optional and each list may be empty;
`action` is exactly "downgrade" or "drop", and a "downgrade" entry
carries `severity`, exactly one of "blocker", "major", "minor" or
"nit", strictly below the finding's own. Do not call a tool; this turn
has none."""


@dataclass(frozen=True)
class MergeCluster:
    """One reply cluster: two or more finding IDs that are one defect."""

    ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class MergeDisposition:
    """One reply disposition: a downgrade or a drop, with its reason."""

    id: str
    action: str
    reason: str
    severity: Severity | None = None


@dataclass(frozen=True)
class MergeReply:
    clusters: tuple[MergeCluster, ...]
    dispositions: tuple[MergeDisposition, ...]


@dataclass(frozen=True)
class MergeResult:
    """What the merge call did, as the draft and the status line read it.

    `applied` is False when the call could not run or its reply did not
    reconcile; the review then fails closed (REVIEW INCOMPLETE) with the
    cause named in `note`. `merged` maps each representative's id to the
    ids merged away under it, and `proposals` carries the downgrade and
    drop annotations as `(id, text)` pairs the draft appends to the
    finding's line."""

    applied: bool
    note: str = ""
    clusters: int = 0
    merged: tuple[tuple[str, tuple[str, ...]], ...] = ()
    proposals: tuple[tuple[str, str], ...] = ()
    downgrades: int = 0
    drops: int = 0


def merge_system(nonce: str) -> str:
    """The merge call's system prompt: the instructions and the fence
    rule for the review's one nonce. There is no lens body to attest:
    the coordinator is the controller's own."""
    return "\n\n".join((MERGE_INSTRUCTIONS, fence_rule(nonce)))


def merge_turn(
    event: PrEvent,
    findings: UntrustedBlock,
    priors: UntrustedBlock | None,
    context: Sequence[UntrustedBlock],
    nonce: str,
) -> str:
    """The merge call's one user turn: the controller's subject, the
    findings block and the prior rounds, then the review's context --
    the conversation and CI blocks the lenses saw -- each fenced with
    the review's one nonce."""
    subject = f"{event.repo}#{event.pr_number} at {event.head_sha}"
    parts = [f"{MERGE_TARGET_PREFIX}{subject}", fence(findings, nonce)]
    if priors is not None:
        parts.append(fence(priors, nonce))
    parts.extend(fence(block, nonce) for block in context)
    return "\n\n".join(parts)


def findings_block(findings: Sequence[MintedFinding]) -> UntrustedBlock:
    """The deduped findings as the merge turn's first data block: one
    line per finding -- its ID, severity, location, lens attributions,
    verification standing and statement, with its quoted evidence cut to
    `MERGE_EVIDENCE_CHARS` -- in the order the controller holds them.
    The IDs are the reply's only addresses; an unverified finding is
    named as such, because a proposal against it judges a finding the
    quote gate already refused."""
    lines = []
    for f in findings:
        x = f.finding
        lenses = ", ".join(f.lenses) if f.lenses else f.lens
        standing = "verified" if f.verified else f"NOT verified ({f.problem})"
        line = (
            f"{f.id} [{x.severity.value} {x.valence.value} "
            f"{x.attribution.value}] {x.location} (lens {lenses}, {standing}): "
            f"{x.finding}"
        )
        if x.evidence:
            line += f"\n    evidence: {_cut(x.evidence, MERGE_EVIDENCE_CHARS)}"
        lines.append(line)
    return UntrustedBlock("findings", RepoText("\n".join(lines)))


def _cut(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[: cap - 3] + "..."


def parse_merge_reply(text: str) -> MergeReply:
    """The merge reply: one JSON object `{"clusters": [...],
    "dispositions": [...]}` -- both keys optional -- bare or as the last
    fenced object. Every id, action, severity and reason is validated
    against the shape here; whether the ids name findings the review
    holds is the caller's check (`reconcile`), which knows the minted
    set."""
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = last_fenced_object(stripped)
        if data is NO_OBJECT:
            raise ContractError("the reply is not one JSON object") from None
    if not isinstance(data, dict) or not {"clusters", "dispositions"} >= set(data):
        raise ContractError(
            "the reply must be an object with the keys clusters and dispositions"
        )
    clusters = tuple(
        _cluster(index, raw) for index, raw in enumerate(data.get("clusters", []), 1)
    )
    dispositions = tuple(
        _disposition(index, raw)
        for index, raw in enumerate(data.get("dispositions", []), 1)
    )
    return MergeReply(clusters, dispositions)


def _cluster(index: int, raw: Any) -> MergeCluster:
    if not isinstance(raw, dict) or set(raw) != {"ids", "reason"}:
        raise ContractError(
            f"cluster {index}: must be an object with exactly the keys ids and reason"
        )
    ids, reason = raw["ids"], raw["reason"]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ContractError(f"cluster {index}: ids must be a list of strings")
    if len(ids) < 2:
        raise ContractError(
            f"cluster {index}: a cluster merges two or more findings; "
            "a finding alone needs no entry"
        )
    if len(set(ids)) != len(ids) or len(ids) > MAX_FINDINGS:
        raise ContractError(
            f"cluster {index}: ids must name distinct findings, at most {MAX_FINDINGS}"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise ContractError(
            f"cluster {index}: a merge carries the reason the findings are one defect"
        )
    if len(reason) > MERGE_REASON_CHARS:
        raise ContractError(
            f"cluster {index}: reason is over {MERGE_REASON_CHARS} characters"
        )
    return MergeCluster(tuple(ids), reason)


def _disposition(index: int, raw: Any) -> MergeDisposition:
    if not isinstance(raw, dict) or not {"id", "action", "reason"} <= set(raw):
        raise ContractError(
            f"disposition {index}: must be an object with the keys id, "
            "action and reason"
        )
    unknown = set(raw) - {"id", "action", "reason", "severity"}
    if unknown:
        raise ContractError(
            f"disposition {index}: unknown key(s) {', '.join(sorted(unknown))}"
        )
    identifier, action, reason = raw["id"], raw["action"], raw["reason"]
    if not all(isinstance(value, str) for value in (identifier, action, reason)):
        raise ContractError(
            f"disposition {index}: id, action and reason must be strings"
        )
    if action not in ("downgrade", "drop"):
        raise ContractError(
            f"disposition {index}: action must be exactly 'downgrade' or 'drop'"
        )
    if not identifier.strip() or not reason.strip():
        raise ContractError(
            f"disposition {index}: a downgrade or drop carries the stated "
            "reason the evidence does not support the finding"
        )
    if len(reason) > MERGE_REASON_CHARS:
        raise ContractError(
            f"disposition {index}: reason is over {MERGE_REASON_CHARS} characters"
        )
    severity = raw.get("severity")
    if action == "downgrade":
        if not isinstance(severity, str):
            raise ContractError(
                f"disposition {index}: a downgrade names the severity its "
                "evidence supports"
            )
        if severity not in {s.value for s in Severity}:
            raise ContractError(
                f"disposition {index}: severity is not one of blocker, "
                "major, minor or nit"
            )
        return MergeDisposition(identifier, action, reason, Severity(severity))
    if severity is not None:
        raise ContractError(f"disposition {index}: a drop carries no severity")
    return MergeDisposition(identifier, action, reason)


def reconcile(
    reply: MergeReply, findings: Sequence[MintedFinding]
) -> tuple[tuple[MintedFinding, ...], MergeResult]:
    """The reply reconciled against the findings the controller holds,
    or the contract error that refuses it whole.

    Every id a cluster or disposition names must be one the review
    holds, and a finding may be named at most once across all of them.
    A downgrade must be strictly below the finding's own severity --
    never a raise. The reply's clusters and dispositions are PROPOSALS
    the controller composes: a cluster replaces its members with the
    strongest of them, every lens attribution carried; a downgrade or
    drop stays an annotation on the finding, and the verdict the
    controller computes over the full verified set is never lowered by
    model output (D73's rule)."""
    held = {f.id: f for f in findings}
    named: dict[str, str] = {}
    for cluster in reply.clusters:
        for identifier in cluster.ids:
            _named_once(held, named, identifier, "a cluster")
        # A cluster's members must share the claim's shape -- the same
        # verification standing, valence and attribution -- exactly what
        # the mechanical dedupe requires before it clusters. Without the
        # check, `stronger`'s severity-only ranking can seat an
        # unverified member over a verified one (or a pre-existing or
        # improvement member over the defect it claims to duplicate),
        # and the verified finding the verdict reads is merged away on
        # model say-so. The refusal is the whole reply, fail closed.
        first = held[cluster.ids[0]]
        for identifier in cluster.ids[1:]:
            member = held[identifier]
            if (
                member.verified != first.verified
                or member.finding.valence is not first.finding.valence
                or member.finding.attribution is not first.finding.attribution
            ):
                raise ContractError(
                    f"cluster ids {first.id} and {identifier} do not share "
                    "the claim's shape -- the same verification standing, "
                    "valence and attribution -- so the controller cannot "
                    "tell which reading the reply merged"
                )
    for disposition in reply.dispositions:
        _named_once(held, named, disposition.id, "a disposition")
        if disposition.severity is not None:
            current = held[disposition.id].finding.severity
            if disposition.severity.rank <= current.rank:
                raise ContractError(
                    f"a downgrade of {disposition.id} is not below its own "
                    f"{current.value}"
                )
    merged: list[tuple[str, tuple[str, ...]]] = []
    away: set[str] = set()
    for cluster in reply.clusters:
        representative = held[cluster.ids[0]]
        for identifier in cluster.ids[1:]:
            representative = stronger(representative, held[identifier])
        lenses: list[str] = []
        for identifier in cluster.ids:
            member = held[identifier]
            lenses.extend(member.lenses or (member.lens,))
        held[representative.id] = replace(
            representative, lenses=tuple(dict.fromkeys(lenses))
        )
        merged.append(
            (
                representative.id,
                tuple(i for i in cluster.ids if i != representative.id),
            )
        )
        away.update(i for i in cluster.ids if i != representative.id)
    kept = tuple(held[f.id] for f in findings if f.id not in away)
    proposals: list[tuple[str, str]] = []
    downgrades = 0
    drops = 0
    for disposition in reply.dispositions:
        if disposition.action == "downgrade" and disposition.severity is not None:
            downgrades += 1
            text = (
                f"merge proposal: downgrade to {disposition.severity.value} -- "
                f"{disposition.reason}"
            )
        else:
            drops += 1
            text = f"merge proposal: drop -- {disposition.reason}"
        proposals.append((disposition.id, text))
    return kept, MergeResult(
        True,
        clusters=len(reply.clusters),
        merged=tuple(merged),
        proposals=tuple(proposals),
        downgrades=downgrades,
        drops=drops,
    )


def _named_once(
    held: dict[str, MintedFinding], named: dict[str, str], identifier: str, what: str
) -> None:
    if identifier not in held:
        raise ContractError(
            f"{what} names {identifier}, which names no finding this review holds"
        )
    if identifier in named:
        raise ContractError(
            f"a cluster or disposition names {identifier} a second time"
        )
    named[identifier] = what


def merged_away(f: MintedFinding, merge: MergeResult) -> tuple[str, ...] | None:
    """The ids the reply merged away under this finding, when it
    represents one of the reply's clusters."""
    for representative, members in merge.merged:
        if representative == f.id:
            return members
    return None


def proposals_on(f: MintedFinding, merge: MergeResult) -> tuple[str, ...]:
    """The merge proposals recorded against one finding, as the draft
    appends them to its line: every downgrade or drop the reply
    proposed, with its stated reason."""
    return tuple(text for identifier, text in merge.proposals if identifier == f.id)
