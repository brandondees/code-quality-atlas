# SPDX-License-Identifier: MIT
"""The decision log's append-only rule, where a review can actually catch a
violation: a D-entry this PR updates must carry the base branch's whole text
as a byte-identical prefix, with the update appended after it. A stray edit
inside the frozen body -- a lost bold marker, a reworded sentence -- fails
here, not only in review.

The base is `origin/main` where that ref exists (a developer checkout). A CI
run checks out the pull request's merge ref with `fetch-depth: 2` and no
remote-tracking ref, so there the base is the merge commit's first parent,
which is exactly the pull request's base tip. Under CI a missing base is a
failure, not a skip: the guard must run where the gate runs."""

from __future__ import annotations

import os
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


def _under_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _base_doc() -> str | None:
    """The base branch's decision log, or None when no base is readable
    and the run is not under CI. `origin/main` first where it exists. On
    a CI checkout, `HEAD^1` as the fallback: on a pull request's merge
    ref that is the base tip (`fetch-depth: 2` keeps the parent), and on
    a `push` or `schedule` run of `main` it is `main`'s own previous
    commit, so a frozen-body edit made directly on the base fails too."""
    if not (ROOT / ".git").exists():
        return None
    refs = ["origin/main"]
    if _under_ci():
        refs.append("HEAD^1")
    for ref in refs:
        result = subprocess.run(
            ["git", "show", f"{ref}:{DOC}"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    return None


def _read() -> str:
    return (ROOT / DOC).read_text(encoding="utf-8")


@pytest.mark.parametrize("decision", UPDATED)
def test_an_updated_decision_appends_to_the_frozen_body(decision: str) -> None:
    base = _base_doc()
    if base is None:
        if _under_ci():
            pytest.fail(
                "no readable base for the decision-log append-only guard; "
                "the guard must run where the gate runs"
            )
        pytest.skip("no base branch text is readable here")
    frozen = _entry_lines(base, decision)
    current = _entry_lines(_read(), decision)
    assert current.startswith(frozen), (
        f"{decision}'s frozen body was edited: the base branch's entry must "
        "be a byte-identical prefix, with the update appended after it"
    )
    appended = current[len(frozen) :]
    assert appended.startswith((" ", "\n")), (
        f"{decision}'s update must be appended as text, not spliced in"
    )


def test_the_d58_entry_grows_only_at_the_end() -> None:
    """D58 is new on this branch, so it has no frozen base text; its
    updates must still be append-only paragraphs in order: the adoption
    update first, then corrections, with room for later legitimate
    appends (review round 5, n1)."""
    line = _entry_lines(_read(), "D58")
    update = line.index("**Update (2026-11-14")
    first_correction = line.index("**Correction (2026-11-14")
    assert update < first_correction, "the updates are out of order"
    assert line.count("**Update (2026-11-14") >= 1
    assert line.count("**Correction (2026-11-14") >= 2
    # Later corrections must keep the append order: the last one sits
    # after the first.
    assert line.rindex("**Correction (2026-11-14") >= first_correction
