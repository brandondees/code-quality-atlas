# SPDX-License-Identifier: MIT
# tests/test_review_template_sync.py
"""REVIEW.md at the repo root is this repo's own dogfood copy of
templates/REVIEW.md (the template the suite ships for consumers). Nothing
mechanically tied the two together, so a template edit could silently leave
the dogfood copy stale — the same class of drift test_routing_snippet_sync.py
guards for templates/agents-routing-snippet.md (issue #134, Improvements).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_review_md_matches_template():
    root_copy = (ROOT / "REVIEW.md").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "REVIEW.md").read_text(encoding="utf-8")
    assert root_copy == template, (
        "REVIEW.md has drifted from templates/REVIEW.md (the source of truth "
        "for what the suite ships to consumers). Re-sync the two."
    )
