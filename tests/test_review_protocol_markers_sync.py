# SPDX-License-Identifier: MIT
# tests/test_review_protocol_markers_sync.py
"""The atlas review loop's ACK/round-state protocol -- the invisible
`<!-- atlas-review-ack -->`/`<!-- atlas-review round:N -->` markers and their
visible-heading fallbacks -- is restated in prose across six files rather than
defined once: the three review-driving commands, the poll/rebase runbook, and
REVIEW.md/templates/REVIEW.md (kept byte-identical by test_review_template_sync.py).

Nothing mechanically tied these restatements together. PR #359's first commit
edited four of the six sites and needed four follow-up commits, twice missing
a site it had already edited elsewhere in the same file -- the signature of a
protocol spelled out from memory at each site rather than checked against a
single source (issue #373). Every other cross-file convention in this repo
already has a sync guard (test_routing_snippet_sync, test_review_template_sync,
test_map_twins_sync, test_self_vendored_skills_sync); this is the missing one
for the four literal tokens the protocol depends on.

Deliberately narrow: this only asserts the four tokens are spelled identically
everywhere they appear, matching issue #373's own minimal fix. It does not
extract the protocol into one shared fragment (the issue's own "better,"
larger alternative) -- that is a bigger content restructuring left for a
follow-up if wanted, not a prerequisite for closing the drift gap here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every file that states the ACK/round protocol in prose. Add a new site here
# the moment a new command/runbook/template starts describing the protocol --
# an unlisted site is exactly how #373's original drift happened.
_SITES = [
    "commands/atlas-review-pr.md",
    "commands/atlas-poll-and-review.md",
    "commands/atlas-rebase-stale.md",
    "docs/runbooks/pr-review-automation.md",
    "REVIEW.md",
    "templates/REVIEW.md",
]

# The four literal tokens the protocol's round/ACK detection depends on.
# `N` stands for the literal placeholder digit position, not a regex group --
# these are checked as exact substrings, not patterns.
_PROTOCOL_TOKENS = [
    "<!-- atlas-review-ack -->",
    "👀 atlas reviewer engaged",
    "<!-- atlas-review round:N -->",
    "## Round N — ",
]


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace (including line-wrap newlines) to a single
    space. Prose in these files hard-wraps at ~80 columns, so a token like
    "👀 atlas reviewer engaged" can have a literal newline in the middle of it
    without that being a spelling drift -- comparing on unwrapped text is what
    actually matches what a reader (or a rendered Markdown view) sees."""
    return re.sub(r"\s+", " ", text)


def _missing_tokens(
    site_texts: dict[str, str], tokens: list[str]
) -> dict[str, list[str]]:
    """For each token, the sites (by name) whose (already-normalized) text
    doesn't contain it. Empty dict means every token is present everywhere."""
    normalized = {
        site: _normalize_whitespace(text) for site, text in site_texts.items()
    }
    missing: dict[str, list[str]] = {}
    for token in tokens:
        normalized_token = _normalize_whitespace(token)
        absent_from = [
            site for site, text in normalized.items() if normalized_token not in text
        ]
        if absent_from:
            missing[token] = absent_from
    return missing


def test_protocol_tokens_spelled_identically_across_sites():
    site_texts = {site: (ROOT / site).read_text(encoding="utf-8") for site in _SITES}
    missing = _missing_tokens(site_texts, _PROTOCOL_TOKENS)
    assert not missing, (
        "one or more protocol tokens are missing or misspelled at a site that "
        "should carry them -- a spelling drift here is exactly how issue #373's "
        f"round-marker bugs happened: {missing}"
    )


# --- the guard must fail on drift, not merely pass on a fixed tree ----------


def test_missing_tokens_catches_a_spelling_drift():
    """A token dropped or typo'd at one site must show up as missing for that
    site specifically -- not silently pass because most sites still have it."""
    clean = {
        "a.md": "carries <!-- atlas-review-ack --> and 👀 atlas reviewer engaged",
        "b.md": "carries <!-- atlas-review-ack --> and 👀 atlas reviewer engaged",
    }
    assert _missing_tokens(clean, ["<!-- atlas-review-ack -->"]) == {}

    typo = dict(clean)
    typo["b.md"] = "carries <!-- atlas-reviw-ack --> and 👀 atlas reviewer engaged"
    assert _missing_tokens(typo, ["<!-- atlas-review-ack -->"]) == {
        "<!-- atlas-review-ack -->": ["b.md"]
    }

    dropped = dict(clean)
    dropped["a.md"] = "no marker here at all"
    result = _missing_tokens(
        dropped, ["<!-- atlas-review-ack -->", "👀 atlas reviewer engaged"]
    )
    assert result == {
        "<!-- atlas-review-ack -->": ["a.md"],
        "👀 atlas reviewer engaged": ["a.md"],
    }


def test_missing_tokens_normalizes_line_wrapping():
    """A token split across a hard-wrapped line boundary is not a drift --
    matches this file's own `## Contents`-ToC-style guard discipline."""
    wrapped = {"a.md": 'the phrase "👀 atlas\n  reviewer engaged" appears here'}
    assert _missing_tokens(wrapped, ["👀 atlas reviewer engaged"]) == {}
