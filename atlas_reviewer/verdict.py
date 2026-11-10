# SPDX-License-Identifier: MIT
"""The review event a draft recommends, gated on file coverage (D36). Pure.

The model proposes a GitHub review event at the end of each diff part's
review; the controller decides. A review that did not cover every changed
file in full never approves: APPROVE becomes COMMENT, marked review
incomplete. Coverage that cannot be determined counts as incomplete. Lens
NOT RUN status plays no part: this gate is about files only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from atlas_reviewer.notes import quote_untrusted


class ReviewEvent(StrEnum):
    APPROVE = "APPROVE"
    COMMENT = "COMMENT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


EVENT_LINE = "Review event: "
_EVENT_LINE = re.compile(
    rf"{EVENT_LINE}({'|'.join(e.value for e in ReviewEvent)})\**\s*$"
)
STATUS_PREFIX = "<!-- atlas-review-status: "


def proposed_event(text: str) -> ReviewEvent | None:
    """The event named on the reply's last non-blank line, which must be
    exactly `Review event: <EVENT>` (optionally bolded); model output is
    untrusted, so anything else is no proposal."""
    lines = [line.strip().lstrip("*").strip() for line in text.splitlines()]
    last = next((line for line in reversed(lines) if line), "")
    match = _EVENT_LINE.fullmatch(last)
    return ReviewEvent(match.group(1)) if match else None


def combine(proposals: Sequence[ReviewEvent | None]) -> ReviewEvent:
    """APPROVE only if every part proposed it; any REQUEST_CHANGES wins."""
    if ReviewEvent.REQUEST_CHANGES in proposals:
        return ReviewEvent.REQUEST_CHANGES
    if proposals and all(p is ReviewEvent.APPROVE for p in proposals):
        return ReviewEvent.APPROVE
    return ReviewEvent.COMMENT


@dataclass(frozen=True)
class Unreviewed:
    """`rank` is the file's risk tier rank (lower is riskier)."""

    path: str
    why: str
    rank: int


@dataclass(frozen=True)
class FileCoverage:
    """`changed` is the number of changed files when known; `unknown` says
    why coverage could not be determined, and makes it incomplete."""

    changed: int | None
    unreviewed: tuple[Unreviewed, ...] = ()
    unknown: str = ""

    @property
    def complete(self) -> bool:
        return not self.unknown and self.changed is not None and not self.unreviewed


@dataclass(frozen=True)
class Verdict:
    event: ReviewEvent
    proposed: ReviewEvent
    coverage: FileCoverage

    @property
    def coverage_complete(self) -> bool:
        return self.coverage.complete


def decide(proposed: ReviewEvent, coverage: FileCoverage) -> Verdict:
    blocked = proposed is ReviewEvent.APPROVE and not coverage.complete
    return Verdict(ReviewEvent.COMMENT if blocked else proposed, proposed, coverage)


UNDETERMINED = decide(
    ReviewEvent.COMMENT, FileCoverage(None, unknown="no coverage was recorded")
)


def status_line(v: Verdict) -> str:
    """One HTML comment for pipelines to gate on. It holds only
    controller-made values (no paths), so PR text cannot end it early."""
    fields = {
        "review_event": v.event.value,
        "proposed_event": v.proposed.value,
        "coverage_complete": v.coverage_complete,
        "changed_files": v.coverage.changed,
        "unreviewed_files": len(v.coverage.unreviewed),
    }
    return f"{STATUS_PREFIX}{json.dumps(fields)} -->"


def parse_status(draft: str) -> dict[str, object] | None:
    """The status fields from a draft's first line, or None."""
    first = draft.split("\n", 1)[0]
    if not (first.startswith(STATUS_PREFIX) and first.endswith(" -->")):
        return None
    value = json.loads(first[len(STATUS_PREFIX) : -len(" -->")])
    return value if isinstance(value, dict) else None


def warning(v: Verdict, limit: int) -> str:
    """The block at the top of the review body. Paths are chosen by the PR
    author, so each is quoted as data; at most `limit` are listed."""
    if v.coverage_complete:
        return (
            f"**Review event: {v.event.value}.** Every changed file "
            f"({v.coverage.changed}) was reviewed in full by a model call."
        )
    proposed = (
        f" (the model proposed {v.proposed.value})" if v.proposed is not v.event else ""
    )
    head = (
        "> **REVIEW INCOMPLETE -- not approvable.** "
        f"Review event: {v.event.value}{proposed}."
    )
    if v.coverage.unknown:
        return (
            f"{head} File coverage could not be determined "
            f"({v.coverage.unknown}), so it counts as incomplete."
        )
    count = len(v.coverage.unreviewed)
    return (
        f"{head} {count} of {v.coverage.changed} changed file(s) were not "
        f"reviewed in full, so this review cannot approve. Not reviewed, "
        f"highest risk first: {_listed(v.coverage.unreviewed, limit)}."
    )


def _listed(files: tuple[Unreviewed, ...], limit: int) -> str:
    shown = sorted(files, key=lambda f: f.rank)[:limit]
    groups = (
        f"{why}: " + ", ".join(quote_untrusted(f.path) for f in shown if f.why == why)
        for why in dict.fromkeys(f.why for f in shown)
    )
    more = len(files) - len(shown)
    return "; ".join(groups) + (f"; and {more} more" if more > 0 else "")
