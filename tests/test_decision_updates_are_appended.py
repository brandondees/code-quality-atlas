# SPDX-License-Identifier: MIT
"""The decision log's append-only rule, where a review can actually catch a
violation: every decision entry present on the base must carry the base's
whole text -- its first line plus its continuation lines -- as a
byte-identical prefix, with any update appended after it, and a branch that
leaves an entry alone passes unchanged. A stray edit inside a frozen body -- a
lost bold marker, a reworded sentence, a changed sub-bullet -- fails here, not
only in review.

An entry is a bullet in the house heading shape `- **D<n> — ` (the later
sections use other bullet shapes, such as `- **D7 portability.**`, which are
not decision entries and do not shadow one), plus every following line up to
the next top-level bullet or heading: indented sub-bullets, and blank-line
separated paragraphs that keep the indent. Two entries claiming one id fail
rather than letting the later line win.

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
the gate runs. A `git revert` of a merged append fails the guard by design:
record the reversal as an appended update, never by unwriting the entry.
(Reverting the change that added this guard passes, because the revert
deletes the test with it.)"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = "docs/open-questions.md"
_FETCH_HINT = "if the base looks stale, run `git fetch origin main` and re-run"
_ENTRY_HEADING = re.compile(r"^- \*\*D(?P<id>\d+) — ")


def _under_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _read() -> str:
    return (ROOT / DOC).read_text(encoding="utf-8")


def _base_refs(under_ci: bool) -> list[str]:
    """The git refs to try for the base, in order. Under CI `HEAD^1` comes
    first: on a push or schedule checkout, `origin/main` names the commit
    being pushed (the checkout's own HEAD), which would compare the log
    with itself."""
    return ["HEAD^1", "origin/main"] if under_ci else ["origin/main"]


def _base_doc() -> str | None:
    """The base branch's decision log, or None when no base is readable
    and the run is not under CI."""
    if not (ROOT / ".git").exists():
        return None
    for ref in _base_refs(_under_ci()):
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


def _is_toplevel_boundary(line: str) -> bool:
    """Whether `line` ends an entry's block: a top-level bullet, a heading,
    or any other non-indented text. A blank line is not a boundary on its
    own; the block stays open while indented lines keep coming."""
    return bool(line) and not line.startswith((" ", "\t"))


def _entries(doc: str) -> tuple[dict[str, str], list[str]]:
    """Every decision entry of the log, by id, as its whole block: the
    heading line (`- **D<n> — `) plus its continuation lines, up to the
    next top-level bullet or heading. Returns the entries and the ids two
    or more blocks claim, which the caller fails on."""
    entries: dict[str, str] = {}
    duplicates: list[str] = []
    lines = doc.split("\n")
    i = 0
    while i < len(lines):
        match = _ENTRY_HEADING.match(lines[i])
        if match is None:
            i += 1
            continue
        did = f"D{match.group('id')}"
        block = [lines[i]]
        i += 1
        while i < len(lines):
            line = lines[i]
            if _is_toplevel_boundary(line):
                break
            if not line:
                # A blank line stays in the block only while the next
                # non-blank line keeps the indent (D31's paragraph); a
                # blank before a top-level bullet or heading ends it.
                following = next(
                    (candidate for candidate in lines[i + 1 :] if candidate.strip()),
                    "",
                )
                if not following or _is_toplevel_boundary(following):
                    break
            block.append(line)
            i += 1
        text = "\n".join(block)
        if did in entries:
            duplicates.append(did)
        else:
            entries[did] = text
    return entries, duplicates


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
    if appended and not appended.startswith(("\n", " ")):
        return (
            "the update is spliced into the frozen text, not appended as "
            "text after the entry's last line"
        )
    return None


def _failures(base_doc: str, current_doc: str) -> list[str]:
    """Every append-only violation of `current_doc` against `base_doc`."""
    base_entries, base_duplicates = _entries(base_doc)
    current_entries, current_duplicates = _entries(current_doc)
    failures = [
        f"{did}: two entries claim this id"
        for did in sorted(set(base_duplicates) | set(current_duplicates))
    ]
    for did, frozen in sorted(base_entries.items()):
        current = current_entries.get(did)
        if current is None:
            failures.append(f"{did}: the entry exists on the base and was removed")
            continue
        problem = _violation(frozen, current)
        if problem is not None:
            failures.append(f"{did}: {problem}")
    return failures


def test_every_decision_entry_appends_to_its_frozen_body() -> None:
    """The guard itself: every entry the base has -- first line and
    continuation lines -- the branch carries as a byte-identical prefix
    plus at most appended text; an unchanged entry passes (review round 6,
    B1)."""
    base = _base_doc()
    if base is None:
        if _under_ci():
            pytest.fail(
                "no readable base for the decision-log append-only guard; "
                "the guard must run where the gate runs"
            )
        pytest.skip("no base branch text is readable here")
    failures = _failures(base, _read())
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
    entries, _duplicates = _entries(_read())
    entry = entries["D42"]
    assert _violation(entry, entry) is None
    assert _violation(entry, entry + " **Update (later):** more.") is None
    assert _violation(entry, entry[:-2]) is not None
    assert _violation(entry, "reworded. " + entry) is not None
    assert _violation(entry, entry + "Update (later): no space.") is not None


def test_the_ci_base_order_pins_the_merge_parent_first() -> None:
    """Review round 7, m4: under CI the merge commit's first parent is the
    base tried first (a push or schedule checkout's `origin/main` names
    the commit being pushed, which would compare the log with itself); a
    developer checkout uses `origin/main` alone."""
    assert _base_refs(True) == ["HEAD^1", "origin/main"]
    assert _base_refs(False) == ["origin/main"]


def test_a_removed_entry_fails_the_guard() -> None:
    """Review round 7, m4: an entry the base has and the branch dropped is
    a violation, not silence."""
    base = "- **D7 — Real entry.** Text.\n- **D8 — Another.** Text.\n"
    current = "- **D8 — Another.** Text.\n"
    problems = _failures(base, current)
    assert problems == ["D7: the entry exists on the base and was removed"]


def test_a_missing_base_fails_closed_under_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 7, m4; hardened round 8, m5: under CI a base that
    cannot be read fails the guard instead of skipping it (round 5, m1's
    regression is pinned). A `pytest.skip` escaping as a Skipped outcome
    would leave the suite green, so the outcome's exact type is asserted:
    it must be a failure, with the guard's message."""
    import sys

    guard = sys.modules[__name__]

    monkeypatch.setattr(guard, "_base_doc", lambda: None)
    monkeypatch.setattr(guard, "_under_ci", lambda: True)
    with pytest.raises(BaseException) as raised:
        guard.test_every_decision_entry_appends_to_its_frozen_body()
    # A skip-instead-of-fail regression raises Skipped, which pytest would
    # report as a skip and the suite would stay green; assert it is a
    # failure and that it is this rule's failure.
    assert raised.type is pytest.fail.Exception, f"the guard raised {raised.type}"
    assert "the guard must run" in str(raised.value)


def test_a_shadow_bullet_does_not_shadow_the_real_entry() -> None:
    """Review round 7, m3: a later section's `- **D7 portability.**` bullet
    is not a decision entry (no ` — ` heading), so it cannot shadow the
    real D7, and editing the real D7 fails."""
    base = "- **D7 — Real entry.** The frozen text.\n"
    current = (
        "- **D7 — Real entry.** The frozen text.\n"
        "A heading between sections.\n"
        "- **D7 portability.** A later-section bullet.\n"
        "  its own continuation line\n"
    )
    assert _failures(base, current) == []
    reworded = current.replace("The frozen text.", "The edited text.")
    problems = _failures(base, reworded)
    assert len(problems) == 1 and problems[0].startswith("D7: the frozen body")


def test_a_continuation_line_edit_fails_the_guard() -> None:
    """Review round 7, m3: an entry is its heading plus its continuation
    lines (indented sub-bullets and blank-separated paragraphs), so an
    edit inside a sub-bullet fails, and the unchanged block -- blank
    separators included -- passes."""
    base = (
        "- **D31 — An entry.** The frozen text.\n"
        "  - sub-bullet one\n"
        "  - sub-bullet two\n"
        "\n"
        "  A paragraph after the blank line.\n"
    )
    assert _failures(base, base) == []
    edited = base.replace("sub-bullet one", "sub-bullet ONE")
    problems = _failures(base, edited)
    assert len(problems) == 1 and problems[0].startswith("D31: the frozen body")
    # Review round 8, m6: the paragraph after the blank line is part of
    # the block too, so an edit inside it fails; a parser that ends the
    # block at the blank line would pass it and unguard the paragraph.
    edited_paragraph = base.replace(
        "A paragraph after the blank line.", "A paragraph EDITED."
    )
    problems = _failures(base, edited_paragraph)
    assert len(problems) == 1 and problems[0].startswith("D31: the frozen body")


def test_a_duplicate_id_fails_the_guard() -> None:
    """Review round 7, m3: two blocks claiming one id fail, rather than
    the later block silently winning."""
    base = "- **D7 — Real.** Text.\n"
    current = "- **D7 — Real.** Text.\n- **D7 — A second block.** More.\n"
    problems = _failures(base, current)
    assert problems == ["D7: two entries claim this id"]


def test_the_d58_entry_grows_only_at_the_end() -> None:
    """D58 while it is not yet on the base: its updates must still be
    append-only paragraphs in order -- the adoption update first, then
    corrections, with room for later legitimate appends (review round 5,
    n1). Once D58 is on the base, the general guard watches its frozen
    body too."""
    line = _entries(_read())[0]["D58"]
    update = line.index("**Update (2026-11-14")
    first_correction = line.index("**Correction (2026-11-14")
    assert update < first_correction, "the updates are out of order"
    assert line.count("**Update (2026-11-14") >= 1
    assert line.count("**Correction (2026-11-14") >= 2
    # Later corrections must keep the append order: the last one sits
    # after the first.
    assert line.rindex("**Correction (2026-11-14") >= first_correction
