# SPDX-License-Identifier: MIT
"""The synthesis's finding type, shared by the coordinator and the
dedupe pass (issue #822). Pure.

`MintedFinding` is one attested lens finding as the controller holds it
through synthesis: minted with its `L<lens>-F<n>` id, quote-checked,
and -- when the dedupe pass collapsed cross-lens duplicates -- the
representative of a cluster that names every lens attribution on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_reviewer.lens_contract import Finding


@dataclass(frozen=True)
class MintedFinding:
    id: str
    lens: str
    finding: Finding
    verified: bool
    source: str
    problem: str = ""
    # A verified window match's line distance from the citation (D64); 0
    # otherwise. The draft builds the source tag from it.
    drift: int = 0
    carried: bool = False
    """True for a prior finding the delta review carried forward (#702):
    `id` is the carry-forward label (`P1`, ...), `lens` is the earlier
    record's lens attribution, and the finding was quote-verified against
    this head like any other."""
    lenses: tuple[str, ...] = ()
    """Every lens the finding is attributed to, first attributed first,
    `lens` among them: a cross-lens duplicate cluster's representative
    carries the whole cluster's attributions (issue #822), so a defect
    two lenses reported still reads as reported by two. Empty when the
    finding stands alone under its own `lens`."""
