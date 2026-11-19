# SPDX-License-Identifier: MIT
"""The guard against a committed git conflict marker (the round-3 re-check
of #775, F-R3-1's guard): the rebase's fixture-docstring resolution left a
literal `<<<<<<< HEAD` line inside a module docstring -- syntactically
invisible, so the gate, ruff, mypy and every suite stayed green -- and
this guard fails on any tracked file that carries one, so an unfinished
conflict resolution cannot merge again.

The shapes, kept narrow -- a line that starts with seven `<` or seven `>`
followed by a space (git's own `<<<<<<< HEAD` and `>>>>>>> label` shapes),
or a line that is exactly seven `=`. The divider's one legitimate look is
a setext heading's underline, which directly follows the heading text --
markdown's, and the same shape RST section underlines take -- so in a
markdown or RST file a `=======` is flagged only when the line above is
blank (or the file starts with it), while in every other tracked file a
line-exactly-seven-`=` is flagged outright, because no shape a source
file, a fixture or a workflow legitimately carries is that. Nothing else
is flagged: an indented line is not a conflict marker, and longer runs of
`<`, `>` or `=` are not the shapes git writes."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_OPEN = "<<<<<<< "
_CLOSE = ">>>>>>> "
_DIVIDER = "======="
# The suffixes whose text a line-exactly-`=======` can legitimately
# underline; everywhere else the divider is a marker full stop.
_SETEXT_SUFFIXES = (".md", ".rst")


def _markers(lines: list[str], *, setext_ok: bool) -> tuple[int, ...]:
    """The 1-based line numbers carrying a conflict marker: the two
    conflict-edge shapes wherever they start a line, and the divider
    everywhere except a setext underline -- in a markdown or RST file, a
    `=======` directly after text is the underline and is not flagged;
    after a blank line (or at the file's start) it is the divider."""
    found: list[int] = []
    previous_blank = True
    for number, line in enumerate(lines, start=1):
        if line.startswith((_OPEN, _CLOSE)) or (
            line == _DIVIDER and not (setext_ok and not previous_blank)
        ):
            found.append(number)
        previous_blank = line.strip() == ""
    return tuple(found)


def _tracked() -> list[str]:
    """Every path git tracks, the population the guard walks."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def test_the_edge_shapes_are_flagged_wherever_they_start_a_line() -> None:
    lines = [
        "prose before",
        "<<<<<<< HEAD",
        "ours",
        "=======",
        "theirs",
        ">>>>>>> feature-branch",
        "prose after",
    ]
    assert _markers(lines, setext_ok=False) == (2, 4, 6)


def test_a_seven_marker_needs_its_trailing_space() -> None:
    """Exactly seven, then a space: git's shape. Eight markers, no space,
    or six are not the shapes the guard flags."""
    assert _markers(["<<<<<<< HEAD"], setext_ok=False) == (1,)
    assert _markers(["<<<<<<<HEAD"], setext_ok=False) == ()
    assert _markers(["<<<<<<<< HEAD"], setext_ok=False) == ()
    assert _markers([">>>>>>> origin/main"], setext_ok=False) == (1,)
    assert _markers([">>>>>>>main"], setext_ok=False) == ()
    assert _markers(["<<<<<< HEAD"], setext_ok=False) == ()


def test_the_divider_is_flagged_in_source_and_underline_shaped_in_prose() -> None:
    """A source file's line-exactly-`=======` is a marker whatever it
    follows -- the fixture-docstring blocker sat exactly there -- while a
    markdown or RST file keeps its setext underline and still flags a
    divider after a blank line."""
    assert _markers(["x = 1", "=======", "y = 2"], setext_ok=False) == (2,)
    assert _markers(["A setext heading", "======="], setext_ok=True) == ()
    assert _markers(["An RST section", "======="], setext_ok=True) == ()
    assert _markers(["prose", "", "=======", "more"], setext_ok=True) == (3,)
    assert _markers(["=======", "text"], setext_ok=True) == (1,)


def test_an_indented_or_longer_line_is_not_a_marker() -> None:
    assert _markers(["  =======", "text"], setext_ok=False) == ()
    assert _markers(["text", "========", "more"], setext_ok=False) == ()
    assert _markers(["text", "=========", "more"], setext_ok=False) == ()


def test_the_guard_walks_the_real_tracked_tree() -> None:
    """The walk's population is the repo's own: the files the blocker sat
    in and the docs the decisions live in are in it, so a marker in any
    of them is walked -- a guard whose population silently emptied would
    fail here rather than guard nothing."""
    tracked = _tracked()
    assert "atlas_reviewer/github_fixture.py" in tracked
    assert len(tracked) > 100
    assert "README.md" in tracked
    assert "docs/open-questions.md" in tracked


SAMPLE = "tests/fixtures/conflict-marker-sample.txt"


def _offenders() -> list[str]:
    """The walk the two guards share: every tracked file read and
    scanned, its markers reported as `path:line`."""
    offenders: list[str] = []
    for path in _tracked():
        text = (ROOT / path).read_bytes().decode("utf-8", errors="replace")
        setext_ok = path.endswith(_SETEXT_SUFFIXES)
        for number in _markers(text.split("\n"), setext_ok=setext_ok):
            offenders.append(f"{path}:{number}")
    return offenders


def test_the_walk_finds_the_seeded_sample() -> None:
    """The walk works end to end: the tracked sample conflict is found,
    whole -- both edges and the divider -- so a dropped walk loop or a
    broken read cannot hide behind a clean tree. The sample is the one
    tracked file allowed to carry markers; the next test holds the rest
    of the tree to none."""
    assert _offenders() == [
        f"{SAMPLE}:1",
        f"{SAMPLE}:3",
        f"{SAMPLE}:5",
    ]


def test_no_tracked_file_but_the_sample_carries_a_conflict_marker() -> None:
    """The guard itself: every tracked file but the seeded sample walks
    marker-free. The fixture-docstring marker this guard exists for was
    invisible to every other gate because it sat inside a docstring;
    this walk is what catches the next one."""
    offenders = [o for o in _offenders() if not o.startswith(SAMPLE + ":")]
    assert not offenders, (
        "committed git conflict markers:\n" + "\n".join(offenders)
    )  # fmt: skip
