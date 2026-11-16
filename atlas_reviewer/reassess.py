# SPDX-License-Identifier: MIT
"""The reused settled lens's re-assessment on newer evidence (D73, #726).

A lens already settled for this head and body is reused without a runner,
and until D73's follow-up that reuse never looked at evidence again: a
check still pending when the lens settled and failing afterwards, or a
comment posted after settlement, was invisible to the reused verdict. The
owner's decision (Brandon, 2026-11-15 8:32 PM CT, recorded in D73): a
reused result **keeps its findings** -- newer evidence never discards them
-- and, when newer CI evidence or comments exist since the result was
produced, the lens **re-assesses** its judgment with that new information
and adds, revises or follows up on findings where it changes anything.

This module is that re-assessment, as one bounded model call:

- **Detection is a digest, not a clock.** The reuse path compares the
  evidence snapshot this review gathered against the digest stored with
  the settled result in the attestation ledger
  (`AttemptLedger.evidence_digest`). The snapshot covers the head SHA's
  CI evidence and the pull request's conversation -- the same gathered
  data the first turn's blocks were built from, minus each item's fetch
  time, which differs on every review -- so a digest that moved means
  *something* in that evidence changed: a new check result, a new
  comment, an edited one, a listing that now fails or now succeeds. A
  timestamp comparison against the controller's own clock would be
  skew-sensitive and would miss an edit to an old comment; a digest is
  neither. No stored digest -- a settled result from before this
  mechanism, or a caller that passes no snapshot -- reads as "cannot be
  shown to be current", and earns the one bounded re-assessment; the
  attested reply records a digest, so the next review of unchanged
  evidence makes no extra call.
- **The delta is the current evidence, not a diff of it.** The digest
  says that something changed, not what; the re-assessment turn therefore
  carries the prior findings plus the review's own context blocks -- the
  conversation and CI-evidence blocks this review's first turn would have
  carried, which hold the newer comments and the current CI state. They
  are bounded by the same D38/D52/D67/D73 budgets the first turn is, and
  they are a superset of the delta, which is the direction a judgment
  needs: the lens sees the complete current picture, not a fragment it
  must guess the rest of.
- **One call, no tools.** The head SHA is unchanged -- the code the prior
  findings cite is the code that is there -- so the call offers no tools
  and reads nothing; it sees the prior findings and the evidence blocks
  and answers once. It counts against the run's derived limits and dollar
  ceiling (D68) through the review's shared `Spend`, and it introduces no
  lens-count bound (D69): the only caps it can hit are the shared call
  and dollar ones.
- **Prior findings are never silently dropped — and a withdrawal never
  removes one.** A prior finding the reply does not mention is kept as it
  stands; a withdrawal is an annotation, not a deletion: the finding
  stays in the effective set the verdict is computed over, and the
  draft's withdrawn section shows it with its stated reason, so an
  injected comment can lower a finding's visibility but never flip a
  Blocker review to approve (round-1 review of #731, M2). A revision
  replaces the prior finding when it does not lower its severity; a
  revision that lowers a Blocker's or a Major's severity is
  annotation-only too, so the higher severity still counts. Only
  **verified** prior findings take part — they are the ones the review
  reports, and the only ones a label can name; an unverified prior
  survives under "Not verified" with no path to withdrawal or revision
  (round-1 review of #731, N1). A re-assessment reply that never met the
  contract is recorded as the failed attempt it is, keeps every prior
  finding, and stores no digest, so the next review of this head re-runs
  the bounded call instead of freezing the failure in.
- **Everything model-written is data.** The prior findings and the
  evidence blocks travel inside the review's one nonce fence, and the
  reply's new and revised findings are quote-verified against the head
  files exactly as an ordinary reply's are; a quote that does not verify
  is not reported.

The re-assessment is recorded as attempts on the lens's own `#reassess`
ledger key, never as attempts on the lens key itself: the lens's settled
state -- the attestation, the causes, the coverage its own run earned --
is the full run's, and a garbled supplementary reply must not turn a
clean lens partial. The reuse path composes the effective result from the
settled outcome and every recorded re-assessment, in order, on every
review, so the composition is durable and reproducible from the ledger
alone.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from atlas_reviewer.attestation import (
    Attempt,
    AttemptOutcome,
    Attestation,
    Cause,
    CheckedFinding,
    _finding_key,
    inject_body,
)
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.evidence import Remark
from atlas_reviewer.gather import Collected
from atlas_reviewer.lens_contract import (
    _NO_OBJECT,
    DIGEST,
    MAX_FINDINGS,
    MAX_LENS_CHARS,
    MAX_TEXT_CHARS,
    ContractError,
    Finding,
    LineRange,
    Severity,
    WholeFile,
    _dropped,
    _last_fenced_object,
    _parse_finding,
    _UnknownSeverity,
)
from atlas_reviewer.lens_loop import retry_reasons
from atlas_reviewer.prompt import RepoText, UntrustedBlock, _fence_rule, fence
from atlas_reviewer.quotes import (
    SourceText,
    Verified,
    check_all,
    with_head_files,
)

REASSESS_TARGET_PREFIX = "Re-assessment target (from the controller):"
"""The re-assessment turn's first line, controller-written. The dry-run
scripted reviewer tells this turn from an ordinary first turn by it: a
normal first turn opens `Review target (from the operator):`, and no
PR-written text can be the first line of the controller's own message."""

REASSESS_SUFFIX = "#reassess"
"""The ledger-key suffix that separates a lens's re-assessment attempts
from the lens's own: the lens key stays settled whatever a re-assessment
reply does, and a continuation's `#<digest>` scope suffix cannot collide
with a suffix that is not hex."""

PRIOR_LABEL_CHARS = 32
"""The longest prior-finding label a withdrawn or revising entry may name;
the controller labels prior findings `P1`, `P2`, ..., so this is slack, not
a size the content reaches."""

REASSESS_INSTRUCTIONS = """\
You are one review lens in an automated code review, re-assessing an
earlier result of yours for the same head SHA. Nothing you write is posted
anywhere; the operator reads the controller's draft first. The code at
this head has not changed since your earlier review; what may have changed
is the evidence around it -- newer CI results, or newer reviews and
comments on the pull request -- which the first turn carries fenced as
data.

Your earlier findings are listed in the first turn's prior-findings block,
each labeled P1, P2, ... with its quote. Judge the new evidence against
them:

- A prior finding the new evidence does not change needs no reply; it is
  kept as it stands. Do not restate a prior finding you confirm.
- To revise a prior finding, report the revised finding in `findings` with
  a `revises` key naming the prior label, and a `reason` key stating what
  in the new evidence changed your judgment. The revision takes the
  prior's place -- except one that would lower a Blocker's or a Major's
  severity, which is recorded as your proposal instead: the finding stays
  reported at its higher severity, annotated with your reason and your
  revised copy.
- To propose withdrawing a prior finding the new evidence shows is wrong,
  name its label in `withdrawn` with a `reason` key stating that evidence.
  A withdrawal is recorded as your proposal: the finding stays reported,
  annotated with your reason; it is never deleted. Never propose a
  withdrawal without a reason.
- To add a finding the new evidence reveals, report it in `findings` with
  no `revises` key.

Every finding you report meets the Finding contract below and is quoted
from the head files exactly as an ordinary reply's are; a quote that does
not verify is not reported.

When you are done, reply with exactly one JSON object and nothing else:
{"lens": <the lens name in the body markers>, "body_sha256": <the sha256
in the body markers>, "findings": [...], "withdrawn": [...]}. Each entry
of `findings` has the keys location, evidence, severity, valence, route,
attribution, finding and fix, and optionally siblings, with the values the
Finding contract below defines, plus the optional `revises` and `reason`
keys this preamble defines. Each entry of `withdrawn` is an object with
exactly the keys `id` and `reason`. Severity is exactly one of "blocker",
"major", "minor" or "nit"; a finding whose severity cannot be read as one
of those names is dropped, and the other findings stand. Do not call a
tool; this turn has none."""


# --------------------------------------------------------------- the reply


@dataclass(frozen=True)
class ReassessFinding:
    """One finding of a re-assessment reply: the Finding contract's object,
    plus the prior label it revises and the stated reason for the
    revision, both empty on an added finding."""

    finding: Finding
    revises: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ReassessReply:
    lens: str
    body_sha256: str
    findings: tuple[ReassessFinding, ...]
    withdrawn: tuple[tuple[str, str], ...] = ()
    # One line per finding left out for an unknown severity, naming the
    # raw severity, as the ordinary reply's dropped list does.
    dropped: tuple[str, ...] = ()


_REPLY_KEYS = frozenset({"lens", "body_sha256", "findings", "withdrawn"})


def parse_reassess_reply(text: str) -> ReassessReply:
    """The re-assessment reply as one JSON object
    `{"lens", "body_sha256", "findings", "withdrawn"}` -- `withdrawn`
    optional, the rest required -- bare, or as the last fenced JSON object
    when prose surrounds it, exactly as `parse_reply` reads an ordinary
    reply. A finding entry may carry `revises` and, with it, a `reason`;
    a withdrawn entry is `{"id", "reason"}`, and a withdrawal without a
    reason is refused, because the reason is the output a reader relies
    on."""
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = _last_fenced_object(stripped)
        if data is _NO_OBJECT:
            raise ContractError("the reply is not one JSON object") from None
    if not isinstance(data, dict) or not _REPLY_KEYS >= set(data):
        raise ContractError(
            "the reply must be an object with the keys "
            "lens, body_sha256, findings and withdrawn"
        )
    missing = {"lens", "body_sha256", "findings"} - set(data)
    if missing:
        raise ContractError(f"the reply is missing {', '.join(sorted(missing))}")
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
    withdrawn = data.get("withdrawn", ())
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
    return ReassessReply(
        lens,
        digest,
        tuple(parsed),
        tuple(_withdrawn_entry(i, raw) for i, raw in enumerate(withdrawn, 1)),
        tuple(dropped),
    )


def _reassess_finding(index: int, raw: Any) -> ReassessFinding:
    if not isinstance(raw, dict):
        raise ContractError(f"finding {index}: must be an object")
    revises = raw.get("revises", "")
    reason = raw.get("reason", "")
    if not isinstance(revises, str) or not isinstance(reason, str):
        raise ContractError(f"finding {index}: revises and reason must be strings")
    if reason and not revises:
        raise ContractError(
            f"finding {index}: a reason names the prior finding it revises"
        )
    if revises and not reason.strip():
        raise ContractError(
            f"finding {index}: a revision carries the reason the new "
            "evidence changed the judgment"
        )
    if len(revises) > PRIOR_LABEL_CHARS:
        raise ContractError(
            f"finding {index}: revises is over {PRIOR_LABEL_CHARS} characters"
        )
    if len(reason) > MAX_TEXT_CHARS:
        raise ContractError(
            f"finding {index}: reason is over {MAX_TEXT_CHARS} characters"
        )
    rest = {k: v for k, v in raw.items() if k not in ("revises", "reason")}
    try:
        finding = _parse_finding(rest)
    except ContractError as exc:
        raise type(exc)(f"finding {index}: {exc}") from None
    return ReassessFinding(finding, revises, reason)


def _withdrawn_entry(index: int, raw: Any) -> tuple[str, str]:
    if not isinstance(raw, dict) or set(raw) != {"id", "reason"}:
        raise ContractError(
            f"withdrawn entry {index}: must be an object with exactly the "
            "keys id and reason"
        )
    prior, reason = raw["id"], raw["reason"]
    if not isinstance(prior, str) or not isinstance(reason, str):
        raise ContractError(f"withdrawn entry {index}: id and reason must be strings")
    if not prior.strip() or not reason.strip():
        raise ContractError(
            f"withdrawn entry {index}: a withdrawal carries the reason the "
            "new evidence shows the finding wrong"
        )
    if len(prior) > PRIOR_LABEL_CHARS:
        raise ContractError(
            f"withdrawn entry {index}: id is over {PRIOR_LABEL_CHARS} characters"
        )
    if len(reason) > MAX_TEXT_CHARS:
        raise ContractError(
            f"withdrawn entry {index}: reason is over {MAX_TEXT_CHARS} characters"
        )
    return prior, reason


# ---------------------------------------------------------------- prompts


def prior_findings_block(prior: Sequence[CheckedFinding]) -> UntrustedBlock:
    """The prior findings as the re-assessment turn's first data block,
    each labeled `P<n>` in the order the reply's `revises` and `withdrawn`
    labels resolve against (`judge` labels the same list the same way).
    The findings' text is the ledger's own scrubbed record; it is still
    model-written text from an earlier conversation, so it travels inside
    the fence like every other block."""
    lines = []
    for n, checked in enumerate(prior, 1):
        f = checked.finding
        lines.append(
            f"P{n} [{f.severity.value} {f.valence.value} {f.attribution.value}] "
            f"{f.location}: {f.finding}"
        )
        if f.evidence:
            lines.append(f"    evidence: {f.evidence}")
    return UntrustedBlock("prior-findings", RepoText("\n".join(lines)))


def reassess_turn(
    event: PrEvent,
    prior: UntrustedBlock,
    context: Sequence[UntrustedBlock],
    nonce: str,
) -> str:
    """The re-assessment call's one user turn: the controller's subject,
    then the prior findings and the review's own context blocks -- the
    conversation and CI evidence the reused lens never saw -- each fenced
    with the review's one nonce."""
    subject = f"{event.repo}#{event.pr_number} at {event.head_sha}"
    return "\n\n".join(
        (
            f"{REASSESS_TARGET_PREFIX}{subject}",
            fence(prior, nonce),
            *(fence(block, nonce) for block in context),
        )
    )


def reassess_system(lens: str, body: str, contract: str, nonce: str) -> str:
    """The re-assessment call's system prompt: the re-assessment
    instructions, the fence rule for the review's one nonce, the lens body
    whole between its attested markers, and the Finding contract."""
    return "\n\n".join(
        (REASSESS_INSTRUCTIONS, _fence_rule(nonce), inject_body(lens, body), contract)
    )


# ---------------------------------------------------------------- judging


@dataclass(frozen=True)
class JudgedReassess:
    """A re-assessment reply judged: the reply's findings quote-checked
    like an ordinary reply's, and the withdrawal and revision references
    resolved against the prior findings they name -- a reference that
    names no prior finding refuses the whole reply, the way any other
    contract problem does."""

    checked: tuple[CheckedFinding, ...]
    withdrawn: tuple[tuple[str, str], ...]
    revises: tuple[tuple[int, str, str], ...]
    causes: frozenset[Cause]


def judge(
    reply: ReassessReply,
    prior: Sequence[CheckedFinding],
    sources: SourceText,
    head_tree: bytes,
    tolerance: int,
) -> JudgedReassess:
    """Quote-check the reply's findings against the head files and resolve
    every `revises` and `withdrawn` label against `prior` -- the verified
    prior findings, labeled `P1`, `P2`, ... in `prior_findings_block`'s
    order; only verified prior findings take part, because they are the
    ones the review reports and the only ones a label can name.

    The quote check reads the head lines of every path the reply's and the
    prior findings' locations cite, not only the changed files the diff
    holds: a verified prior finding can cite an unchanged file (the
    ordinary run's lens read it there), and the re-assessment's revision
    of it must be able to verify the same quote (round-2 review of #731,
    the open Major). A reply whose labels name nothing, or that both
    revises and withdraws the same label (round-1 review of #731, N2), is
    refused before anything is recorded."""
    labels = {f"P{n}": c for n, c in enumerate(_verified(prior), 1)}
    cited = _cited_paths(rf.finding for rf in reply.findings) | _cited_paths(
        c.finding for c in _verified(prior)
    )
    checked = tuple(
        CheckedFinding(q.finding, q.source, drift=q.drift)
        if isinstance(q, Verified)
        else CheckedFinding(q.finding, problem=q.reason)
        for q in check_all(
            (rf.finding for rf in reply.findings),
            with_head_files(sources, head_tree, cited),
            tolerance,
        )
    )
    revises = []
    for i, rf in enumerate(reply.findings, 1):
        if not rf.revises:
            continue
        if rf.revises not in labels:
            raise ContractError(
                f"finding {i} revises {rf.revises}, which names no prior finding"
            )
        revises.append((i, rf.revises, rf.reason))
    withdrawn = []
    for prior_id, reason in reply.withdrawn:
        if prior_id not in labels:
            raise ContractError(f"withdrawn entry {prior_id!r} names no prior finding")
        if any(prior_id == revised for _, revised, _ in revises):
            raise ContractError(
                f"withdrawn entry {prior_id!r} names a finding the same reply "
                "also revises"
            )
        withdrawn.append((prior_id, reason))
    causes = (
        frozenset({Cause.QUOTES_FAILED})
        if any(not c.verified for c in checked)
        else frozenset()
    )
    return JudgedReassess(checked, tuple(withdrawn), tuple(revises), causes)


def _verified(prior: Sequence[CheckedFinding]) -> list[CheckedFinding]:
    return [checked for checked in prior if checked.verified]


def _cited_paths(findings: Iterable[Finding]) -> frozenset[str]:
    """The head files the findings' locations cite: a line range's or a
    whole file's path; a design reference cites no file."""
    paths = set()
    for finding in findings:
        location = finding.location
        if isinstance(location, LineRange | WholeFile):
            paths.add(location.path)
    return frozenset(paths)


# ------------------------------------------------------- the effective set


@dataclass(frozen=True)
class Withdrawn:
    """A prior finding a recorded re-assessment annotated, with its stated
    reason and, for a revision, the checked finding that revises it. Since
    the round-1 review of #731 (M2) a withdrawal is an annotation, not a
    deletion: the prior finding stays in the effective set the verdict is
    computed over -- and so does a revision that lowers a Blocker's or a
    Major's severity, or one whose replacement did not verify (round-2
    review of #731, the open Major) -- and the draft's withdrawn section
    shows what was proposed and why, so a reader can tell a finding was
    re-judged and not lost. `replaced` is True only when the revision
    actually took the prior finding's place in the findings set."""

    finding: Finding
    reason: str
    replacement: CheckedFinding | None = None
    replaced: bool = False


def effective_outcome(
    settled: AttemptOutcome, reassessments: Sequence[Attempt]
) -> tuple[AttemptOutcome, tuple[Withdrawn, ...], str]:
    """The reused result as D73 leaves it: the settled outcome's findings
    with every recorded re-assessment applied in order, the annotations
    the reader is shown, and the controller note for the lens line.

    The composition replays from the ledger alone, so every review of
    this head composes the same effective set: each re-assessment is
    applied against the set its own reply was labeled against -- the
    effective set before it -- which the replay reproduces by applying the
    recorded re-assessments in order over the verified findings, the set
    the labels were issued over.

    A prior finding is never removed by a withdrawal: a withdrawal is an
    annotation, and the finding stays in the set `decide` sees (round-1
    review of #731, M2). A revision replaces the prior finding unless it
    lowers a Blocker's or a Major's severity, or unless its replacement
    did not verify -- a revision whose quote check failed cannot be the
    evidence for removing a verified finding, so it too is annotation-only
    and the prior stands (round-2 review of #731, the open Major); a
    revision of a lower-severity prior that verifies may lower it, and its
    replacement stands. One the reply is silent on is kept as it stands,
    which is the "never silently dropped" rule. A recorded label that
    resolves against nothing -- possible only on a hand-corrupted ledger
    line, since `judge` refuses unresolvable labels at record time -- is
    skipped and named in the note, never applied half-way.

    `dropped` is composed from the settled run plus only the latest
    re-assessment's notes (round-1 review of #731, M3): an earlier
    attempt's malformed-severity entry is superseded by the later reply
    that re-lists it or stays silent, so one malformed reply cannot
    accumulate into every later review of the head -- and when the latest
    attempt is abandoned (a crash mid-call, which records no notes), the
    earlier notes are not carried either; the lens line's "not accepted"
    note and the next review's re-run of the bounded call cover the gap.
    The latest re-assessment's own limit stop (a refused reservation, a
    spent-out call cap) is carried onto the composed outcome, so the
    status line's `limit_stop` names it (round-1 review of #731, N4)."""
    findings = list(settled.findings)
    withdrawn: list[Withdrawn] = []
    unresolved: list[str] = []
    added = revised = annotated = proposed = 0
    for attempt in reassessments:
        outcome = attempt.outcome
        labels = {f"P{n}": c for n, c in enumerate(_verified(findings), 1)}
        gone: set[tuple[str, str, str, str, str, str]] = set()
        superseded: set[int] = set()
        resolved: set[int] = set()
        for index, prior_id, reason in outcome.revises:
            held = labels.get(prior_id)
            if held is None or not 1 <= index <= len(outcome.findings):
                unresolved.append(prior_id)
                continue
            resolved.add(index)
            replacement = outcome.findings[index - 1]
            lowered_from_blocker_or_major = (
                held.finding.severity.rank <= Severity.MAJOR.rank
                and replacement.finding.severity.rank > held.finding.severity.rank
            )
            if lowered_from_blocker_or_major or not replacement.verified:
                # Annotation-only: a proposed downgrade, or a revision
                # whose replacement did not verify -- the prior finding
                # stays in the set, verified, and still counts.
                superseded.add(index)
                withdrawn.append(Withdrawn(held.finding, reason, replacement))
                annotated += 1
            else:
                gone.add(_finding_key(held.finding))
                withdrawn.append(Withdrawn(held.finding, reason, replacement, True))
                revised += 1
        for prior_id, reason in outcome.withdrawn:
            held = labels.get(prior_id)
            if held is None:
                unresolved.append(prior_id)
                continue
            withdrawn.append(Withdrawn(held.finding, reason))
            proposed += 1
        if gone:
            findings = [
                checked
                for checked in findings
                if _finding_key(checked.finding) not in gone
            ]
        findings.extend(
            checked
            for i, checked in enumerate(outcome.findings, 1)
            if i not in superseded
        )
        added += sum(
            1 for i in range(1, len(outcome.findings) + 1) if i not in resolved
        )
    dropped = list(settled.dropped)
    if reassessments:
        dropped.extend(reassessments[-1].outcome.dropped)
    limit_hit = (
        reassessments[-1].outcome.limit_hit
        if reassessments and reassessments[-1].outcome.limit_hit is not None
        else settled.limit_hit
    )
    effective = (
        settled
        if not reassessments
        else replace(
            settled,
            findings=tuple(findings),
            dropped=tuple(dropped),
            limit_hit=limit_hit,
        )
    )
    return (
        effective,
        tuple(withdrawn),
        _note(reassessments, added, revised, annotated, proposed, unresolved),
    )


def _note(
    reassessments: Sequence[Attempt],
    added: int,
    revised: int,
    annotated: int,
    proposed: int,
    unresolved: Sequence[str],
) -> str:
    """The lens line's controller note. The counts cover only references
    that resolved (round-2 review of #731, the open Nit): `added` the
    reply's own findings, `revised` the revisions that took a prior
    finding's place, `annotated` the annotation-only ones -- a proposed
    downgrade, or a revision whose replacement did not verify -- and
    `proposed` the withdrawals, which remove nothing."""
    if not reassessments:
        return ""
    counts = ", ".join(
        f"{count} {label}"
        for label, count in (
            ("added", added),
            ("revised", revised),
            ("annotated", annotated),
            ("withdrawn", proposed),
        )
        if count
    )
    note = "re-assessed with newer CI evidence or comments"
    if counts:
        note += f": {counts}"
    latest = reassessments[-1].outcome
    if latest.attestation is not Attestation.ATTESTED:
        reasons = "; ".join(retry_reasons(latest))
        note += f"; the latest re-assessment was not accepted ({reasons})"
    if unresolved:
        note += (
            f"; {len(unresolved)} recorded re-assessment reference(s) "
            "resolved against nothing and were not applied"
        )
    return note


# --------------------------------------------------------------- the digest

SNAPSHOT_VERSION = 1


def snapshot_digest(
    ci: Collected, remarks: Sequence[Remark], remark_gather: Collected
) -> str:
    """The evidence snapshot's digest, stored with a settled result so the
    reuse path can tell newer evidence from unchanged evidence (D73).

    The snapshot is the gathered head-SHA CI evidence -- each item's
    source id, head SHA, tool, conclusion and redacted detail -- and the
    pull request's conversation as fetched -- each remark's source id,
    GitHub timestamp, author, controller context and body -- plus the
    gathers' omissions, failures and notes, so a listing that now fails or
    now succeeds moves the digest too: what could not be read is part of
    what was judged, and its return is newer evidence. Each item's fetch
    time is left out: it differs on every review of unchanged evidence,
    and it says when *we* read, not what *they* did. The digest is over
    the gathered data, never over a rendered block, so a change in the
    model's input room or the lens plan cannot read as newer evidence.

    Not digested, on purpose: the pull request's title, body, labels,
    commit subjects and remark-derived block sizing. The block that
    renders them is D38's assembly, and the commit list is effectively
    covered by the head-SHA reuse key -- but an edited body changes what
    the re-assessment turn's conversation block carries without moving
    this digest, so "the conversation" here means the remarks, not the
    whole block (round-1 review of #731, N3)."""
    payload = {
        "v": SNAPSHOT_VERSION,
        "items": sorted(_item(entry) for entry in ci.items),
        "omissions": sorted(
            _omission(o) for o in (*ci.omissions, *remark_gather.omissions)
        ),
        "failures": sorted(
            _failure(f) for f in (*ci.failures, *remark_gather.failures)
        ),
        "notes": sorted((*ci.notes, *remark_gather.notes)),
        "remarks": sorted(_remark(r) for r in remarks),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _item(item: Any) -> str:
    return json.dumps(
        {
            "kind": item.provenance.key.kind.value,
            "about": item.provenance.key.name,
            "id": item.provenance.source_id,
            "head_sha": item.head_sha,
            "tool": f"{item.tool.name}@{item.tool.version}",
            "conclusion": item.conclusion.value,
            "detail": item.detail.text,
        },
        sort_keys=True,
        ensure_ascii=True,
    )


def _remark(remark: Remark) -> str:
    return json.dumps(
        {
            "id": remark.source_id,
            "at": remark.at,
            "author": remark.author,
            "context": remark.context,
            "body": remark.body,
        },
        sort_keys=True,
        ensure_ascii=True,
    )


def _omission(omission: Any) -> str:
    return json.dumps(
        [omission.source, omission.limit, omission.detail], ensure_ascii=True
    )


def _failure(failure: Any) -> str:
    return json.dumps(
        [failure.key.kind.value, failure.key.name, failure.reason],
        ensure_ascii=True,
    )
