# SPDX-License-Identifier: MIT
"""Classify raw evidence against the one head SHA under review. Pure.

A source is *expected* at the head SHA if the operator named it, or if it
was observed on any other commit of the same PR: a check that ran on an
earlier push and is absent now is reported Missing (UNKNOWN), never
silently dropped.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from atlas_reviewer.domain import (
    Evidence,
    EvidenceItem,
    Matched,
    Missing,
    Outcome,
    SourceKey,
    Stale,
)
from atlas_reviewer.groups import Link, group_checks

REASON_ONLY_OTHER_SHAS = (
    "observed only on other commits of this PR, not on the reviewed head SHA"
)
REASON_EXPECTED_ABSENT = (
    "expected by the operator but not found for the reviewed head SHA"
)


def classify(
    head_sha: str,
    items: Iterable[EvidenceItem],
    expected: Iterable[SourceKey] = (),
    failures: Sequence[Missing] = (),
) -> tuple[Evidence, ...]:
    items = tuple(items)
    matched = tuple(Matched(i, head_sha) for i in items if i.head_sha == head_sha)
    stale = tuple(Stale(i, head_sha) for i in items if i.head_sha != head_sha)
    covered = {m.item.provenance.key for m in matched} | {f.key for f in failures}
    missing = _missing(covered, stale, tuple(expected))
    return (*matched, *stale, *failures, *missing)


def _missing(
    covered: set[SourceKey],
    stale: tuple[Stale, ...],
    expected: tuple[SourceKey, ...],
) -> tuple[Missing, ...]:
    reasons: dict[SourceKey, str] = {}
    for s in stale:
        reasons.setdefault(s.item.provenance.key, REASON_ONLY_OTHER_SHAS)
    for key in expected:
        reasons.setdefault(key, REASON_EXPECTED_ABSENT)
    return tuple(Missing(k, r) for k, r in reasons.items() if k not in covered)


@dataclass(frozen=True)
class Tally:
    """Counts independent checks at the head SHA: a check run, its job, the
    job's log and the workflow run holding it count once (`supporting` says
    how many further views were folded in). `unknown` counts checks with no
    usable result (missing, or present but inconclusive); `stale` counts items
    from other commits, which are UNKNOWN too but say nothing about the head
    SHA."""

    passed: int
    failed: int
    unknown: int
    stale: int
    present: int
    supporting: int = 0


def tally(evidence: Iterable[Evidence], links: Iterable[Link] = ()) -> Tally:
    evidence = tuple(evidence)
    groups = group_checks(evidence, links)
    counts = Counter(g.outcome for g in groups)
    folded = {
        m.item.provenance.source_id for g in groups for m in (*g.supporting, *g.context)
    }
    return Tally(
        passed=counts[Outcome.PASS],
        failed=counts[Outcome.FAIL],
        unknown=counts[Outcome.UNKNOWN] + sum(isinstance(e, Missing) for e in evidence),
        stale=sum(isinstance(e, Stale) for e in evidence),
        present=counts[Outcome.INFO],
        supporting=len(folded),
    )
