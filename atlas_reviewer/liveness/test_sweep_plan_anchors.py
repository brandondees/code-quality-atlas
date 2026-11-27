# SPDX-License-Identifier: MIT
"""The controller's sweep plan reaches the parity key's mutation-class
findings at their own anchors (the #846 gap's anchor pins).

The plan used to fill its cap alphabetically over added lines only, so
`640-m1` (a pre-existing cancel check a changed caller reaches) and
`661-m3`/`661-m4` (mid-file guards in an almost-wholly-new module, behind
the breadth-first walk's first picks) were unreachable no matter how the
lens aimed. These tests run the plan exactly as a review does -- the
anchor's own tree against the pull request's own diff, at the production
cap -- and pin each key mutant inside it, keyed off the committed parity
key so a re-anchor updates the pins instead of silently grading a plan
that can no longer reach its finding.

Like the parity-key liveness checks, the anchors are fetched from `origin`
by SHA (CI's checkout is shallow; the round-5 anchor is on no branch).
Unlike them, no anchor suite runs here -- the plan is a parse, so this
file costs seconds, but it still needs the anchors' objects, which is why
it lives beside the liveness checks in their own CI step."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atlas_reviewer.bridge import SWEEP_CAP, SweepSpec, sweep_specs
from atlas_reviewer.parity_key import KEY_DIR, load_key

_REPO = Path(__file__).resolve().parents[2]
_TREES: dict[str, dict[str, bytes]] = {}
_DIFFS: dict[tuple[str, str], str] = {}


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _ensure_commit(commit: str) -> None:
    """The anchor commit's objects are read from the local object store:
    CI's checkout is shallow (`fetch-depth: 2`), so a commit the store
    lacks is fetched from origin by SHA before anything reads against it,
    the same shape the parity-key liveness checks fetch theirs with."""
    missing = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=_REPO,
        capture_output=True,
        check=False,
    )
    if missing.returncode != 0:
        _git("fetch", "origin", commit)


def _tree(commit: str) -> dict[str, bytes]:
    if commit not in _TREES:
        files = _git("ls-tree", "-r", "--name-only", commit).splitlines()
        _TREES[commit] = {
            path: _git("show", f"{commit}:{path}").encode()
            for path in files
            if path.endswith(".py")
        }
    return _TREES[commit]


def _diff(base: str, head: str) -> str:
    key = (base, head)
    if key not in _DIFFS:
        _DIFFS[key] = _git("diff", "--find-renames", base, head)
    return _DIFFS[key]


# The commit each anchor's pull-request diff was served against. #640's
# base is the main head its branch forked from (the gap audit's base for
# the anchor); #661's is the merge base of the round-5 head with main,
# confirmed there against `git merge-base` and carried here explicitly so
# the pin cannot drift when main advances.
_BASES = {
    640: "771925a538d6744b6017175e8fe5f170abf27a6d",
    661: "f82b4bf18b252daf76759f21d2b09ed4f09d39c9",
}

# finding id -> (path, the guard's line, the operator, drop-operand's kept
# operand), read against the parity key's own span for the same finding so
# a span move and a pin move fail together rather than silently apart.
_PINS = {
    "640-m1": ("atlas_reviewer/service_queue.py", 329, "drop-operand", 2),
    "661-m3": ("atlas_reviewer/rounds.py", 182, "break-continue", None),
    "661-m4": ("atlas_reviewer/rounds.py", 207, "drop-operand", 2),
}


@pytest.mark.parametrize("finding_id", sorted(_PINS))
def test_the_sweep_plan_names_the_key_mutant_at_its_anchor(finding_id: str) -> None:
    finding = next(item for item in load_key(KEY_DIR) if item.id == finding_id)
    path, line, operator, operand = _PINS[finding_id]
    span = next(
        span
        for span in finding.spans
        if span.path == path and span.line_start is not None
    )
    end = span.line_end if span.line_end is not None else span.line_start
    assert span.line_start is not None and end is not None
    assert span.line_start <= line <= end, (
        f"{finding_id}: the pin's line {line} has drifted from the parity "
        f"key's span {span.line_start}-{span.line_end}; move them together"
    )
    anchor = finding.reviewed_commit
    base = _BASES[finding.pr]
    _ensure_commit(anchor)
    _ensure_commit(base)
    assert _git("merge-base", "--is-ancestor", base, anchor) == ""
    specs = sweep_specs(_diff(base, anchor), _tree(anchor), cap=SWEEP_CAP)
    pinned = SweepSpec(path, line, operator, operand)
    assert pinned in specs, (
        f"{finding_id}: the controller's sweep plan at {anchor[:8]} does not "
        f"reach {pinned} -- the mutation-class key Minor is unreachable again"
    )
