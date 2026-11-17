# SPDX-License-Identifier: MIT
# tests/test_ci_require_hashes_install.py
"""#366: `.github/workflows/ci.yml`'s hash-verified `requirements.txt`
install is the artifact that makes the hash-pin gate real -- pip only
verifies a pin's hash(es) when it actually resolves and downloads that
artifact, so the install step must keep using `--require-hashes`.

The original #366 defect lived on the persistent self-hosted runner: the
install went straight into a shared interpreter where an already-installed
pin reported "Requirement already satisfied" and its hash was never
checked (reproduced with a forged hash of 64 zeros, exit 0). The fix routed
the install through a fresh `--clear`ed per-job venv, and
`test_ci_require_hashes_targets_fresh_venv.py` (removed in the same change
as D78) guarded that venv shape. D78 moved every event onto ephemeral
GitHub-hosted runners, which dissolves #366's precondition -- each run gets
a fresh VM and a clean setup-python interpreter, so nothing is ever
already-satisfied -- and the venv went with it. What remains worth guarding
mechanically is only that the `--require-hashes` install step still exists
at all; a checkout cannot observe interpreter freshness on a hosted VM.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _find_require_hashes_step():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["gate"]["steps"]:
        run = step.get("run", "")
        if "--require-hashes" in run:
            return run
    return None


def test_require_hashes_step_exists():
    assert _find_require_hashes_step() is not None, (
        "no step in ci.yml's gate job runs `pip install --require-hashes` "
        "any more -- has the hash-pin gate been removed or renamed? Update "
        "this test (and re-check #366's hash-verification guarantee still "
        "holds however the install is now shaped) either way."
    )
