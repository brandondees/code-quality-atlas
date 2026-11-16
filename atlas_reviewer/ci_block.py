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
- Sized within D67's model-aware input-room budgeting: the caller passes
  what the conversation block left of the room, so the two blocks
  together cannot exceed it, and the prior rounds take what remains. A
  block whose content does not fit its cap is truncated with the marker
  and the cut is named; one whose bytes still overflow the room is
  omitted whole and named -- never silently truncated, never sent to
  overflow the per-call token check. Unlike the conversation block, which
  rebuilds once smaller on that overflow, this block omits whole:
  `build_conversation` can produce a smaller complete block by dropping
  the oldest remarks, while `render_evidence` has no refit, so a smaller
  build here would only be a shorter truncated table.

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
from atlas_reviewer.redact import (
    MIN_FIT_CHARS,
    TRUNCATION_MARKER_CHARS,
    RedactedText,
    Redactor,
)

SOURCE = "CI evidence"
LABEL = "ci-evidence"
CI_EVIDENCE_CHARS = 16_384
"""The block's own cap, the same size D52 gives the prior-round blocks:
a working default pending the owner. Under a model-named room the cap
shrinks to what the room holds, minus the truncation marker.

The sizing figures themselves live beside `redact.TRUNCATION_MARKER`
(`TRUNCATION_MARKER_CHARS`, `MIN_FIT_CHARS`), the one home both this
module and `cli`'s conversation sizing derive from."""


def ci_block(
    event: PrEvent,
    github: GitHubReader,
    redactor: Redactor,
    clock: Clock,
    room: int | None,
    config: IngestConfig | None = None,
    collected: Collected | None = None,
) -> tuple[UntrustedBlock | None, tuple[Omission, ...]]:
    """The head SHA's CI evidence block and every omission, for an agentic
    first turn.

    `room` is the characters of the model's input room the context blocks
    still hold after the conversation block is spent: the caller passes
    the fit minus the conversation block's UTF-8 bytes (D67's own figure,
    None-preserving), so the two blocks together cannot exceed the fit and
    the invariant holds by construction, the way D67's holds. A room below
    `MIN_FIT_CHARS` -- the conversation left almost nothing -- omits the
    block whole and names it. None: the model names no input room, so the
    fixed cap stands and the per-call token check stays the only bound.
    The gather runs first, so a failed or partial fetch is recorded even
    when no block is built.

    `collected`, when given, is the caller-owned `Collected` the gather
    fills (D73): the caller keeps the gathered items, failures and notes
    so the review's evidence-snapshot digest can be taken over them; None
    gathers into a private one and drops them, as before this parameter."""
    if config is None:
        config = IngestConfig()
    if collected is None:
        collected = Collected()
    gather_head_ci(event, github, clock.now, redactor, config, collected)
    # Every gather failure is an omission (D42), whatever else was read:
    # a check-run listing that could not be fetched is CI evidence nobody
    # saw, and the review cannot approve on a partial picture of the head.
    failures = tuple(
        Omission(SOURCE, "fetch failed", failure.reason)
        for failure in collected.failures
    )
    if room is not None and room < MIN_FIT_CHARS:
        return None, (*collected.omissions, *failures, _left_out(room))
    budget = (
        CI_EVIDENCE_CHARS
        if room is None
        else min(CI_EVIDENCE_CHARS, room - TRUNCATION_MARKER_CHARS)
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
