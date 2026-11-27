# SPDX-License-Identifier: MIT
"""Controller-side dedupe of findings across lenses (issue #822).

The lenses run isolated -- one lens never sees another's findings -- so
the same defect routinely reaches the synthesis several times, once per
lens that saw it. `mint` numbers every lens's findings independently, so
before the mechanical rank the controller clusters the minted findings
that describe one defect and keeps a single representative, carrying
every lens attribution on it (D31's synthesis, as
`synthesizing-review-findings` dedupes on location plus root cause).

A cluster is findings that name the same target and the same claim:

- the same **target**: both locations cite the same path, and their
  line ranges overlap or sit within `SPAN_PROXIMITY_LINES` lines of
  each other -- two lenses rarely anchor the same defect on the same
  line, but they anchor it in the same few lines. A whole-file
  location overlaps any range in that file, and a `boundary:`/
  `component:` reference or the pull request body overlaps only its
  own string;
- the same **claim**: the finding statements match after case-folding,
  whitespace collapsing and trailing-punctuation stripping, and the two
  findings agree on valence and attribution. The key is deliberately
  exact, not a similarity score: a threshold that merges paraphrases
  also merges distinct findings that word alike, and the controller has
  no basis to prefer one reading. An introduced defect and a
  pre-existing one never merge, because the verdict treats them
  differently (D55); restatements the key cannot catch are the
  per-review merge call's judgment (the plan's step 7), not this
  pass's. A verified finding and an unverified one never merge either:
  the quote gate's own verdict is evidence the controller holds, and a
  duplicate's failed quote must not displace a finding that verified
  (#691) -- the unverified copy stays named, at its own id.

The representative is the cluster's strongest finding -- a
verdict-setting one over one that is not, then the more severe, ties
keeping the first minted -- and every lens in the cluster stays
attributed on it, so a defect two lenses reported is still reported by
two lenses. The representative's own id is unchanged, so the round
record's per-line attribution and the delta citation rules keep
resolving exactly as they did.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from atlas_reviewer.findings import MintedFinding
from atlas_reviewer.lens_contract import Finding, LineRange, Location, WholeFile

SPAN_PROXIMITY_LINES = 10
"""How far apart two line ranges may sit and still name one defect: the
same defect reported from a function's body and from its header, or
from two reads of a block, lands within a few lines; a real second
finding on the same path rarely does. A wider window starts merging
distinct findings that share wording; a narrower one starts splitting
one defect across two entries."""

_TRAILING = re.compile(r"[\s.!,;:`\"']+$")


def claim_key(text: str) -> str:
    """The finding statement's comparison key: case-folded, whitespace
    collapsed, trailing punctuation and quote marks stripped. An empty
    statement never matches, so a degenerate finding cannot collect
    others."""
    return _TRAILING.sub("", " ".join(text.split())).casefold()


def _overlap(one: Location, other: Location) -> bool:
    """Whether two locations could name the same spot: the same path
    with overlapping (or proximity-window) ranges, one whole file and
    anything in it, or -- for a design reference and the pull request
    body, which cite no path -- the identical location string."""
    if isinstance(one, LineRange) and isinstance(other, LineRange):
        return one.path == other.path and _near(one, other)
    if isinstance(one, WholeFile) and isinstance(other, WholeFile):
        return one.path == other.path
    if isinstance(one, WholeFile) and isinstance(other, LineRange):
        return one.path == other.path
    if isinstance(one, LineRange) and isinstance(other, WholeFile):
        return one.path == other.path
    return str(one) == str(other)


def _near(one: LineRange, other: LineRange) -> bool:
    return (
        one.start <= other.end + SPAN_PROXIMITY_LINES
        and other.start <= one.end + SPAN_PROXIMITY_LINES
    )


def same_target(one: MintedFinding, other: MintedFinding) -> bool:
    """Whether two findings name the same defect closely enough that the
    controller may keep one: the same claim -- statement, valence and
    attribution, and the same verification standing -- about the same
    spot."""
    return (
        bool(claim_key(one.finding.finding))
        and _claim(one.finding) == _claim(other.finding)
        and one.verified == other.verified
        and _overlap(one.finding.location, other.finding.location)
    )


def _claim(finding: Finding) -> tuple[str, str, str]:
    return (
        finding.valence.value,
        finding.attribution.value,
        claim_key(finding.finding),
    )


def dedupe(findings: Sequence[MintedFinding]) -> tuple[MintedFinding, ...]:
    """The findings with cross-lens duplicates collapsed into their
    clusters' representatives, in mint order.

    A finding joins the first earlier finding it names the same defect
    as; clusters never chain through a member, only through their
    representative, so A matching B and B matching C does not merge A
    into C unless A also matches C's representative. The representative
    is the cluster's strongest finding, and its `lenses` list carries
    every distinct lens attribution in the cluster, first seen first."""
    representatives: list[MintedFinding] = []
    clusters: list[list[MintedFinding]] = []
    for finding in findings:
        for cluster in clusters:
            if same_target(cluster[0], finding):
                cluster.append(finding)
                break
        else:
            clusters.append([finding])
            representatives.append(finding)
    return tuple(
        _representative(cluster, index) for index, cluster in enumerate(clusters)
    )


def _representative(cluster: list[MintedFinding], _index: int) -> MintedFinding:
    kept = cluster[0]
    for candidate in cluster[1:]:
        kept = stronger(kept, candidate)
    lenses = tuple(dict.fromkeys(item.lens for item in cluster))
    if len(lenses) > 1:
        kept = _with_lenses(kept, lenses)
    return kept


def stronger(kept: MintedFinding, candidate: MintedFinding) -> MintedFinding:
    """The stronger of two findings, on the synthesis's rule (round-5
    review of #748): verdict-setting over not, then the more severe,
    ties keeping the incumbent. The dedupe's representatives and the
    merge call's cluster representatives resolve through this, so the
    two passes cannot pick different findings for the same defect."""
    if candidate.finding.sets_verdict != kept.finding.sets_verdict:
        return candidate if candidate.finding.sets_verdict else kept
    if candidate.finding.severity.rank < kept.finding.severity.rank:
        return candidate
    return kept


def _with_lenses(finding: MintedFinding, lenses: tuple[str, ...]) -> MintedFinding:
    return replace(finding, lenses=lenses)
