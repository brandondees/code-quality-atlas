# SPDX-License-Identifier: MIT
# tests/test_review_template_sync.py
"""REVIEW.md at the repo root is this repo's own dogfood copy of
templates/REVIEW.md (the template the suite ships for consumers). The two
are held equal except for the two machine-setting lines (#778, round-1
review M1; issue #819, D95): the template ships each line commented out
inside a fenced code block — inert for its parser and the unsupported scan
(both anchor the key at the line start, and a `#`-prefixed line matches
neither; the fence is safe only because the line inside it carries that
comment), and kept out of markdownlint's single-H1 rule's sight by the
fence — while the root copy carries the live values this repo decided on
(D91's `review_ceiling_usd: 25`, and D95's `review_setup_commands:`).
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
# The second allowed difference (issue #819, D95): the setup-commands line,
# live in the root copy, commented out inside its own fenced example in the
# template — the same shape as the ceiling line's, normalized the same way.
_SETUP_LINE = re.compile(r"^[ \t]*#?[ \t]*review_setup_commands:.*$", re.MULTILINE)
_SETUP_EXAMPLE_BLOCK = re.compile(
    r"^```[^\n]*\n#[^\n]*review_setup_commands:[^\n]*\n```$", re.MULTILINE
)
_NORMALIZED = "<configured line>"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    text = _CEILING_LINE.sub(_NORMALIZED, _CEILING_EXAMPLE_BLOCK.sub(_NORMALIZED, text))
    return _SETUP_LINE.sub(_NORMALIZED, _SETUP_EXAMPLE_BLOCK.sub(_NORMALIZED, text))


def test_review_md_matches_template():
    assert _normalized(_read("REVIEW.md")) == _normalized(
        _read("templates/REVIEW.md")
    ), (
        "REVIEW.md has drifted from templates/REVIEW.md outside the two "
        "allowed differences (the per-review ceiling line and the "
        "setup-commands line: live in the root copy, commented out in the "
        "template — round-1 review of #778, M1; issue #819, D95). "
        "Re-sync the two."
    )


def test_each_copy_carries_exactly_one_ceiling_line():
    """The normalization must never hide the line itself: a dropped or
    duplicated ceiling line in either copy fails here, so the live root
    setting and the template's inert example both stay pinned."""
    for rel in ("REVIEW.md", "templates/REVIEW.md"):
        assert len(_CEILING_LINE.findall(_read(rel))) == 1, rel


def test_each_copy_carries_exactly_one_setup_line():
    """The same pin for the setup-commands line (issue #819, D95): a
    dropped or duplicated line in either copy fails, so the live root
    setting and the template's inert example both stay pinned."""
    for rel in ("REVIEW.md", "templates/REVIEW.md"):
        assert len(_SETUP_LINE.findall(_read(rel))) == 1, rel
