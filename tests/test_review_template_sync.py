# SPDX-License-Identifier: MIT
# tests/test_review_template_sync.py
"""REVIEW.md at the repo root is this repo's own dogfood copy of
templates/REVIEW.md (the template the suite ships for consumers). The two
are held equal except for the one per-review ceiling line (#778, round-1
review M1): the template ships that line commented out inside a fenced code
block — inert for the ceiling parser and the unsupported scan (both anchor
the key at the line start, and a `#`-prefixed line matches neither; the
fence is safe only because the line inside it carries that comment), and
kept out of markdownlint's single-H1 rule's sight by the fence — while the
root copy carries the live `review_ceiling_usd: 25`
this repo decided on (D91).
Everything else is still compared byte-for-byte, so the dogfood-drift
protection that motivated this test (issue #134, Improvements) survives the
relaxation."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The one line the two copies may differ on: the live ceiling line in the
# root copy, or the commented-out example in the template (packaged inside
# a fenced code block, which is what keeps markdownlint's single-H1 rule
# from reading the comment as a heading). Anchored at the line's first
# non-space token so nothing else can be normalized away.
_CEILING_LINE = re.compile(r"^[ \t]*#?[ \t]*review_ceiling_usd:.*$", re.MULTILINE)
# The template's fenced packaging of that line: an opening fence, the one
# commented example line, and the closing fence — normalized as a unit, so
# the fence markers (which exist only to package the line) do not read as
# drift.
_CEILING_EXAMPLE_BLOCK = re.compile(
    r"^```[^\n]*\n#[^\n]*review_ceiling_usd:[^\n]*\n```$", re.MULTILINE
)
_NORMALIZED = "<review_ceiling_usd line>"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return _CEILING_LINE.sub(_NORMALIZED, _CEILING_EXAMPLE_BLOCK.sub(_NORMALIZED, text))


def test_review_md_matches_template():
    assert _normalized(_read("REVIEW.md")) == _normalized(
        _read("templates/REVIEW.md")
    ), (
        "REVIEW.md has drifted from templates/REVIEW.md outside the one "
        "allowed difference (the per-review ceiling line: live in the root "
        "copy, commented out in the template — round-1 review of #778, M1). "
        "Re-sync the two."
    )


def test_each_copy_carries_exactly_one_ceiling_line():
    """The normalization must never hide the line itself: a dropped or
    duplicated ceiling line in either copy fails here, so the live root
    setting and the template's inert example both stay pinned."""
    for rel in ("REVIEW.md", "templates/REVIEW.md"):
        assert len(_CEILING_LINE.findall(_read(rel))) == 1, rel
