# SPDX-License-Identifier: MIT
import pytest

from atlas_reviewer.draft import DraftInput, render_draft
from atlas_reviewer.verdict import (
    UNDETERMINED,
    FileCoverage,
    ReviewEvent,
    Unreviewed,
    combine,
    decide,
    parse_status,
    proposed_event,
    status_line,
    warning,
)

A, C, R = ReviewEvent.APPROVE, ReviewEvent.COMMENT, ReviewEvent.REQUEST_CHANGES
SEEN = FileCoverage(3)
ONE_UNSEEN = FileCoverage(
    3, (Unreviewed("src/a.py", "never sent to any model call", 3),)
)


@pytest.mark.parametrize(
    ("text", "event"),
    [
        ("Fine.\n\nReview event: APPROVE", A),
        ("Fine.\n**Review event: REQUEST_CHANGES**\n\n", R),
        ("Review event: APPROVE\nBut one more thing.", None),
        ("Review event: APPROVE please", None),
        ("review event: approve", None),
        ("", None),
    ],
)
def test_only_an_exact_last_line_proposes_an_event(text, event):
    assert proposed_event(text) is event


@pytest.mark.parametrize(
    ("proposals", "event"),
    [([A, A], A), ([A, None], C), ([A, R], R), ([C, A], C), ([], C)],
)
def test_every_part_must_approve_and_any_request_changes_wins(proposals, event):
    assert combine(proposals) is event


@pytest.mark.parametrize(
    "coverage",
    [
        ONE_UNSEEN,
        FileCoverage(None, unknown="the diff was not fetched"),
        FileCoverage(None),
    ],
)
def test_incomplete_or_unknown_coverage_never_approves(coverage):
    verdict = decide(A, coverage)
    assert verdict.event is C and verdict.proposed is A
    assert not verdict.coverage_complete
    assert warning(verdict, 10).startswith("> **REVIEW INCOMPLETE -- not approvable.**")


def test_complete_coverage_keeps_the_proposal():
    assert decide(A, SEEN).event is A
    assert decide(R, ONE_UNSEEN).event is R


def test_the_status_line_round_trips_and_holds_no_path():
    verdict = decide(A, ONE_UNSEEN)
    line = status_line(verdict)
    assert "src/a.py" not in line
    assert parse_status(line + "\n# heading") == {
        "review_event": "COMMENT",
        "proposed_event": "APPROVE",
        "coverage_complete": False,
        "changed_files": 3,
        "unreviewed_files": 1,
    }
    assert parse_status("# heading\n" + line) is None


def test_the_warning_lists_paths_quoted_riskiest_first_up_to_the_limit():
    files = tuple(
        Unreviewed(f"docs/{i}.md", "never sent to any model call", 6) for i in range(3)
    ) + (Unreviewed("src/auth.py", "never sent to any model call", 0),)
    text = warning(decide(A, FileCoverage(9, files)), 2)
    assert "4 of 9 changed file(s)" in text
    assert (
        'never sent to any model call: `"src/auth.py"`, `"docs/0.md"`; and 2 more'
        in text
    )


def test_a_draft_without_a_verdict_renders_as_undetermined():
    from datetime import UTC, datetime

    from atlas_reviewer.domain import PrEvent

    draft = render_draft(
        DraftInput(
            PrEvent("o/r", 1, "a" * 40), "dry-run", "t", (), (), (), (), (), (), (), 0,
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    )  # fmt: skip
    assert UNDETERMINED.event is C
    assert parse_status(draft)["coverage_complete"] is False
    assert "File coverage could not be determined" in draft
