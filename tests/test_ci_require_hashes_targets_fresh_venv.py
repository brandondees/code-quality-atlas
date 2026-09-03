# SPDX-License-Identifier: MIT
# tests/test_ci_require_hashes_targets_fresh_venv.py
"""#366: `.github/workflows/ci.yml`'s `pip install --require-hashes -r
requirements.txt` ran directly against the persistent self-hosted runner's
own interpreter, so any pin already sitting in a prior job's site-packages
was "Requirement already satisfied" and its hash never checked -- silently
defeating the hash-pin gate. Reproduced: with a package already installed, a
requirements file pinning it with a forged hash still made `pip install
--require-hashes` exit 0.

Fixed by installing into a fresh, `--clear`ed per-job venv instead. Nothing
mechanically stopped that shape from regressing -- e.g. a future edit
"simplifying" this back to a bare `pip install --require-hashes -r
requirements.txt`, or dropping the venv's `--clear` -- and CI would stay
green either way, since no existing test reads this specific step (this
repo's own atlas reviewer flagged the gap on the PR that fixed #366). This
guard mirrors the established `test_ci_*.py` pattern (e.g.
test_ci_shellcheck_glob_covers_tree.py, test_precommit_ci_version_sync.py):
it doesn't exercise pip at all, just asserts the step's shape can't quietly
regress to the vulnerable one.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _gate_steps():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    return workflow["jobs"]["gate"]["steps"]


def _find_require_hashes_step():
    for step in _gate_steps():
        run = step.get("run", "")
        if "--require-hashes" in run:
            return run
    return None


def test_require_hashes_step_exists():
    assert _find_require_hashes_step() is not None, (
        "no step in ci.yml's gate job runs `pip install --require-hashes` "
        "any more -- has the hash-pin gate been removed or renamed? Update "
        "this test (and re-check #366 hasn't quietly regressed) either way."
    )


def test_require_hashes_install_targets_a_fresh_clear_venv():
    run = _find_require_hashes_step()
    assert "python -m venv" in run, (
        "the --require-hashes install no longer creates a venv first -- "
        "this is the #366 regression: on the persistent self-hosted runner, "
        "installing straight into the shared interpreter means an "
        "already-installed pin's hash is never checked."
    )
    assert "--clear" in run, (
        "`python -m venv` here must pass --clear -- without it, a leftover "
        "venv directory from a prior job (if the runner's $RUNNER_TEMP is "
        "ever not wiped between jobs) could carry an already-installed pin "
        "forward and reopen the #366 bypass."
    )


def test_require_hashes_line_targets_the_venv_not_the_bare_interpreter():
    run = _find_require_hashes_step()
    require_hashes_lines = [
        line for line in run.splitlines() if "--require-hashes" in line
    ]
    assert len(require_hashes_lines) == 1, (
        f"expected exactly one --require-hashes line in the install step, "
        f"found {len(require_hashes_lines)}: {require_hashes_lines!r}"
    )
    line = require_hashes_lines[0]
    assert "venv" in line, (
        f"the --require-hashes install line ({line!r}) doesn't reference a "
        "venv path -- it must invoke the fresh venv's own pip (e.g. "
        '`"$RUNNER_TEMP/venv/bin/pip"`), not a bare `pip` that resolves to '
        "the persistent runner's shared interpreter (the exact #366 bypass)."
    )


def test_venv_bin_exported_to_github_path_for_later_steps():
    run = _find_require_hashes_step()
    assert "GITHUB_PATH" in run, (
        "the install step no longer exports the venv's bin/ onto "
        "$GITHUB_PATH -- without it, later steps (pip-tools, pip-audit, "
        "ruff, pytest, tooling.cli) stop resolving into the fresh venv and "
        "fall back to the persistent runner's shared interpreter, "
        "reopening the #366 bypass for everything after the first step."
    )
