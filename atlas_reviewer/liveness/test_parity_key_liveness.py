# SPDX-License-Identifier: MIT
"""CI-checked liveness for the parity key's anchors (D71's re-anchor update).

Every key record that carries `liveness` specs is checked against its own
`reviewed_commit` -- the anchor the protocol review actually scored -- so a
span that drifts from the anchor tree, or a defect a later commit fixed,
fails here instead of grading a finding a reviewer cannot honestly raise.
A `mutant` splice must survive the anchor's own full test suite: the
anchor's environmental failures (a ruff-version pin, the session-log
currency date) belong to the baseline, and only a failing test the mutant
introduces kills it. A `quote` text must be present in the file at the
anchor; an `absent` text must not be. A body record's fixture is checked
in beside the key and read from this checkout, because a pull-request body
is review metadata, not anchor content.

The round-5 anchor is not on any branch, so a commit the local object
store lacks is fetched from `origin` by SHA. Each anchor suite run costs
minutes, which is why these checks run in their own CI step
(`pytest atlas_reviewer/liveness`) rather than inside the coverage steps.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_reviewer.parity_key import BODY, KEY_DIR, KeyFinding, load_key

_REPO = Path(__file__).resolve().parents[2]
_FAILURE = re.compile(r"^(?:FAILED|ERROR) (.+)$", re.MULTILINE)
_SUITE_TIMEOUT_S = 1200
_BASELINES: dict[str, frozenset[str]] = {}
_WORKTREES: dict[str, Path] = {}


def _git(*args: str, cwd: Path = _REPO) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _worktree(commit: str) -> Path:
    if commit in _WORKTREES:
        return _WORKTREES[commit]
    missing = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=_REPO,
        capture_output=True,
        check=False,
    )
    if missing.returncode != 0:
        _git("fetch", "origin", commit)
    target = _REPO / ".git" / "liveness-worktrees" / commit[:12]
    target.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--quiet", str(target), commit, "--detach")
    _WORKTREES[commit] = target
    return target


def _suite(worktree: Path) -> frozenset[str]:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
        timeout=_SUITE_TIMEOUT_S,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return frozenset(_FAILURE.findall(done.stdout + done.stderr))


def _baseline(commit: str) -> frozenset[str]:
    if commit not in _BASELINES:
        _BASELINES[commit] = _suite(_worktree(commit))
    return _BASELINES[commit]


def _anchored_text(commit: str, path: str) -> str:
    return _git("show", f"{commit}:{path}")


def _live_file(finding: KeyFinding, spec_file: str) -> Path:
    if finding.spans[0].path == BODY:
        return _REPO / spec_file
    return _worktree(finding.reviewed_commit) / spec_file


def _ids_with_liveness() -> list[tuple[KeyFinding, int]]:
    pairs: list[tuple[KeyFinding, int]] = []
    for finding in load_key(KEY_DIR):
        for index in range(len(finding.liveness)):
            pairs.append((finding, index))
    return pairs


def _label(pair: tuple[KeyFinding, int]) -> str:
    finding, index = pair
    spec = finding.liveness[index]
    return f"{finding.id}-{spec.kind}-{index}"


@pytest.mark.parametrize("pair", _ids_with_liveness(), ids=_label)
def test_the_key_finding_is_still_live_at_its_anchor(
    pair: tuple[KeyFinding, int],
) -> None:
    finding, index = pair
    spec = finding.liveness[index]
    if spec.kind == "mutant":
        worktree = _worktree(finding.reviewed_commit)
        target = worktree / spec.file
        current = target.read_text(encoding="utf-8")
        assert current.count(spec.old) == 1, (
            f"{finding.id}: the mutant's old text is not unique at "
            f"{finding.reviewed_commit} in {spec.file}"
        )
        try:
            target.write_text(current.replace(spec.old, spec.new), encoding="utf-8")
            failures = _suite(worktree)
        finally:
            _git("checkout", "--", spec.file, cwd=worktree)
        introduced = failures - _baseline(finding.reviewed_commit)
        assert not introduced, (
            f"{finding.id}: the liveness mutant was killed at "
            f"{finding.reviewed_commit}; these tests fail only under the "
            f"mutant, so the defect is pinned and the span is stale: "
            f"{sorted(introduced)}"
        )
        return
    content = (
        _anchored_text(finding.reviewed_commit, spec.file)
        if finding.spans[0].path != BODY
        else _live_file(finding, spec.file).read_text(encoding="utf-8")
    )
    if spec.kind == "quote":
        assert spec.text in content, (
            f"{finding.id}: the defect text is not in {spec.file} at "
            f"{finding.reviewed_commit}; the span no longer names the defect"
        )
        return
    assert spec.text not in content, (
        f"{finding.id}: {spec.text!r} is already in {spec.file} at "
        f"{finding.reviewed_commit}; the defect the absent check guards is fixed"
    )


def teardown_module() -> None:
    for target in _WORKTREES.values():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=_REPO,
            capture_output=True,
            check=False,
        )
    subprocess.run(
        ["git", "worktree", "prune"], cwd=_REPO, capture_output=True, check=False
    )
    _WORKTREES.clear()
    _BASELINES.clear()
