# SPDX-License-Identifier: MIT
"""The head SHA's CI evidence as one bounded block for an agentic first
turn (D73).

`gather.py` has collected check runs, workflow runs and jobs since the
one-shot path was built, but only that path consumed them; the agentic
lenses' first turn carried none, so no lens could name a real CI run.
This module builds the summary the agentic path passes: the one-shot
path's own evidence rendering (`render_evidence` over `classify`), scoped
to the head SHA's own results, fenced as one more untrusted block next to
the pull-request, conversation and round-log blocks (D52's assembly,
wired by D67).

The design points carried over from D52's rules:

- The block is DATA. Job names, check-run summaries and workflow paths
  can hold injected text; every PR-written value stays inside the fence
  the first turn puts around it, and the fence and nonce are the review's
  one fence (`first_turn`), never a second one built here.
- A failed or partial fetch is an omission. The gather's failures become
  omissions here, so `coverage_complete` goes false and the review holds
  at COMMENT (D42) -- CI evidence can never make a review approvable
  that the omission gate would not.
- Only the head SHA's own results are fetched (D25's scoping), paginated
  to the one-shot path's hard caps (`IngestConfig`).
- Sized within D67's model-aware input-room budgeting: the block takes
  what the conversation block left of the room, before the prior rounds
  take their share. A block whose content does not fit its cap is
  truncated with the marker and the cut is named; one whose bytes still
  overflow the room is omitted whole and named -- never silently
  truncated, never sent to overflow the per-call token check.

Nothing here reaches the draft except through the existing paths: the
omissions travel as `context_omissions`, and anything a lens reports
about the block goes through the finding contract's quote verification.
"""

from __future__ import annotations

from atlas_reviewer.classify import classify
from atlas_reviewer.domain import Omission, PrEvent
from atlas_reviewer.draft import render_evidence
from atlas_reviewer.gather import Collected, IngestConfig, gather_head_ci
from atlas_reviewer.ports import Clock, GitHubReader
from atlas_reviewer.prompt import UntrustedBlock
from atlas_reviewer.redact import TRUNCATION_MARKER, RedactedText, Redactor

SOURCE = "CI evidence"
LABEL = "ci-evidence"
CI_EVIDENCE_CHARS = 16_384
"""The block's own cap, the same size D52 gives the prior-round blocks:
a working default pending the owner. Under a model-named room the cap
shrinks to what the room holds, minus the truncation marker."""

_MARKER_CHARS = len(TRUNCATION_MARKER)
"""The characters a truncated build appends after its cap (`_truncate`),
which the byte bound below must count."""

_MIN_FIT_CHARS = 4 + _MARKER_CHARS
"""The smallest input room a provably-fitting block can fill: one
worst-case UTF-8 character (four bytes) plus the truncation marker. A
room below this cannot hold any block, and the omit-whole gate fires."""


def ci_block(
    event: PrEvent,
    github: GitHubReader,
    redactor: Redactor,
    clock: Clock,
    room: int | None,
    config: IngestConfig | None = None,
) -> tuple[UntrustedBlock | None, tuple[Omission, ...]]:
    """The head SHA's CI evidence block and every omission, for an agentic
    first turn.

    `room` is the characters the model's input room holds for the context
    blocks -- the same figure `_conversation_block` was sized against
    (D67), from which the conversation block is already spent. None: the
    model names no input room, so the fixed cap stands and the per-call
    token check stays the only bound. The gather runs first, so a failed
    or partial fetch is recorded even when no block is built."""
    if config is None:
        config = IngestConfig()
    collected = Collected()
    gather_head_ci(event, github, clock.now, redactor, config, collected)
    # Every gather failure is an omission (D42), whatever else was read:
    # a check-run listing that could not be fetched is CI evidence nobody
    # saw, and the review cannot approve on a partial picture of the head.
    failures = tuple(
        Omission(SOURCE, "fetch failed", failure.reason)
        for failure in collected.failures
    )
    if room is not None and room < _MIN_FIT_CHARS:
        return None, (*collected.omissions, *failures, _left_out(room))
    budget = (
        CI_EVIDENCE_CHARS
        if room is None
        else min(CI_EVIDENCE_CHARS, room - _MARKER_CHARS)
    )
    evidence = classify(event.head_sha, collected.items, (), collected.failures)
    text = render_evidence(
        evidence, tuple(collected.omissions), tuple(collected.links), ()
    )
    # The one controller-written line in the block: which head SHA this
    # evidence was gathered at (D25's tag), so the block cannot be read
    # against another commit later in the same conversation.
    text = f"CI evidence for the reviewed head SHA {event.head_sha}:\n\n{text}"
    content = redactor(text, budget)
    if room is not None and len(content.text.encode("utf-8")) > room:
        return None, (*collected.omissions, *failures, _left_out(room))
    return UntrustedBlock(LABEL, content), (
        *collected.omissions,
        *failures,
        *_truncation_omissions(content, budget),
    )


def _left_out(room: int) -> Omission:
    return Omission(
        SOURCE,
        "model input room",
        f"the model's input room cannot hold the CI evidence block ({room} "
        "characters left for the context blocks), so it was left out",
    )


def _truncation_omissions(content: RedactedText, cap: int) -> tuple[Omission, ...]:
    if content.truncated_from is None:
        return ()
    return (
        Omission(
            SOURCE,
            f"{cap}-character cap",
            f"kept {cap} of {content.truncated_from} characters",
        ),
    )
