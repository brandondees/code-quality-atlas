# SPDX-License-Identifier: MIT
"""The decision log's append-only rule, where a review can actually catch a
violation: every D-entry present on the base must carry the base's whole text
as a byte-identical prefix, with any update appended after it, and a branch
that leaves an entry alone passes unchanged. A stray edit inside a frozen
body -- a lost bold marker, a reworded sentence -- fails here, not only in
review.

The base, per trigger:

- a pull request's merge ref: the merge commit's first parent (`HEAD^1`),
  the pull request's base tip (`fetch-depth: 2` keeps it); `origin/main`
  when the checkout has it names the same base tip;
- a `push` or `schedule` run of `main`: `HEAD^1`, main's previous tip, so a
  merge or squash commit is compared with what main was before it; a rebase
  merge of several commits compares only with the last commit's parent --
  the earlier commits of the series were already gated by the pull
  request's own merge-ref run, and a later push run compares from the new
  tip;
- a developer checkout: `origin/main`.

Under CI a missing base is a failure, not a skip: the guard must run where
the gate runs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = "docs/open-questions.md"
_FETCH_HINT = "if the base looks stale, run `git fetch origin main` and re-run"


def _under_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _read() -> str:
    return (ROOT / DOC).read_text(encoding="utf-8")


def _entries(doc: str) -> dict[str, str]:
    """Every decision entry of the log, by id, as its full line. An entry
    is a bullet whose first bold token is `D<digits>`."""
    out: dict[str, str] = {}
    for line in doc.split("\n"):
        if not line.startswith("- **D"):
            continue
        parts = line.split(" ", 2)
        token = parts[1].removeprefix("**") if len(parts) > 1 else ""
        did = token.removeprefix("D").strip()
        if did.isdigit():
            out[f"D{did}"] = line
    return out


def _base_doc() -> str | None:
    """The base branch's decision log, or None when no base is readable
    and the run is not under CI. Under CI the merge commit's first parent
    (`HEAD^1`) is preferred: on a `push` or `schedule` checkout,
    `origin/main` names the commit being pushed (the checkout's own HEAD),
    which would compare the log with itself."""
    if not (ROOT / ".git").exists():
        return None
    refs = ["HEAD^1", "origin/main"] if _under_ci() else ["origin/main"]
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


def _violation(frozen: str, current: str) -> str | None:
    """Why `current` breaks the append-only rule against `frozen`, or None.
    An unchanged entry is fine: after this PR merges, most branches leave
    most entries alone."""
    if not current.startswith(frozen):
        return (
            "the frozen body was edited: the base entry must be a "
            "byte-identical prefix, with any update appended after it"
        )
    appended = current[len(frozen) :]
    if appended and not appended.startswith((" ", "\n")):
        return "the update is spliced into the frozen text, not appended as text"
    return None


def test_every_decision_entry_appends_to_its_frozen_body() -> None:
    """The guard itself: every entry the base has, the branch carries as a
    byte-identical prefix plus at most appended text; an unchanged entry
    passes (review round 6, B1)."""
    base = _base_doc()
    if base is None:
        if _under_ci():
            pytest.fail(
                "no readable base for the decision-log append-only guard; "
                "the guard must run where the gate runs"
            )
        pytest.skip("no base branch text is readable here")
    base_entries = _entries(base)
    current_entries = _entries(_read())
    failures = []
    for did, frozen in sorted(base_entries.items()):
        current = current_entries.get(did)
        if current is None:
            failures.append(f"{did}: the entry exists on the base and was removed")
            continue
        problem = _violation(frozen, current)
        if problem is not None:
            failures.append(f"{did}: {problem}")
    message = (
        "the append-only rule is violated:\n" + "\n".join(failures)
        if failures
        else ""
    )  # fmt: skip
    if failures and not _under_ci():
        message += f"\n({_FETCH_HINT}.)"
    assert not failures, message


def test_an_unchanged_entry_passes_and_an_edited_one_fails() -> None:
    """Review round 6, B1, at the rule's own level: an unchanged entry
    passes, an appended update passes, and an edit anywhere in the frozen
    body -- truncated, reworded, or a lost bold marker -- fails."""
    entry = _entries(_read())["D42"]
    assert _violation(entry, entry) is None
    assert _violation(entry, entry + " **Update (later):** more.") is None
    assert _violation(entry, entry[:-2]) is not None
    assert _violation(entry, "reworded. " + entry) is not None
    assert _violation(entry, entry + "Update (later): no space.") is not None


def test_the_d58_entry_grows_only_at_the_end() -> None:
    """D58 while it is not yet on the base: its updates must still be
    append-only paragraphs in order -- the adoption update first, then
    corrections, with room for later legitimate appends (review round 5,
    n1). Once D58 is on the base, the general guard watches its frozen
    body too."""
    line = _entries(_read())["D58"]
    update = line.index("**Update (2026-11-14")
    first_correction = line.index("**Correction (2026-11-14")
    assert update < first_correction, "the updates are out of order"
    assert line.count("**Update (2026-11-14") >= 1
    assert line.count("**Correction (2026-11-14") >= 2
    # Later corrections must keep the append order: the last one sits
    # after the first.
    assert line.rindex("**Correction (2026-11-14") >= first_correction
