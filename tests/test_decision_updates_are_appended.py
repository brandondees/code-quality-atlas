# SPDX-License-Identifier: MIT
"""The decision log's append-only rule, where a review can actually catch a
violation: a D-entry this PR updates must carry the base branch's whole text
as a byte-identical prefix, with the update appended after it. A stray edit
inside the frozen body -- a lost bold marker, a reworded sentence -- fails
here, not only in review."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = "docs/open-questions.md"
UPDATED = ("D42", "D43")


def _entry_lines(doc: str, decision: str) -> str:
    lines = [line for line in doc.split("\n") if line.startswith(f"- **{decision} ")]
    assert len(lines) == 1, f"expected exactly one {decision} entry, got {len(lines)}"
    return lines[0]


def _main_doc() -> str | None:
    """The base branch's decision log, or None where git or the ref is
    unavailable (a mutation copy without `.git`)."""
    if not (ROOT / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "show", "origin/main:docs/open-questions.md"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


@pytest.mark.parametrize("decision", UPDATED)
def test_an_updated_decision_appends_to_the_frozen_body(decision: str) -> None:
    main = _main_doc()
    if main is None:
        pytest.skip("origin/main is not readable here")
    frozen = _entry_lines(main, decision)
    current = _entry_lines(_read(), decision)
    assert current.startswith(frozen), (
        f"{decision}'s frozen body was edited: the base branch's entry must "
        "be a byte-identical prefix, with the update appended after it"
    )
    appended = current[len(frozen) :]
    assert appended.startswith((" ", "\n")), (
        f"{decision}'s update must be appended as text, not spliced in"
    )


def _read() -> str:
    return (ROOT / DOC).read_text(encoding="utf-8")


def test_the_d58_entry_grows_only_at_the_end() -> None:
    """D58 is new on this branch, so it has no frozen base text; its
    updates must still be append-only paragraphs in order: the adoption
    update, then the corrections, each exactly once."""
    line = _entry_lines(_read(), "D58")
    update = line.index("**Update (2026-11-14")
    first_correction = line.index("**Correction (2026-11-14")
    assert update < first_correction, "the updates are out of order"
    assert line.count("**Update (2026-11-14") == 1
    assert line.count("**Correction (2026-11-14") == 2
