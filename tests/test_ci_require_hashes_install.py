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
GitHub-hosted runners, which removes the cross-job accumulation the venv
existed for -- but the install now targets the image-baked setup-python
tool-cache interpreter, whose contents GitHub controls, so an image refresh
shipping a package matching one of this repo's pins at the pinned version
could reopen the same skip (round-1 review of #746, Minor 2). The
mechanical fix is `--ignore-installed`: pip resolves and downloads every
pin regardless of what the interpreter already holds, so every hash is
checked whatever the image ships -- and that flag is what this guard pins,
because a checkout cannot observe interpreter freshness directly.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _find_require_hashes_steps() -> list[str]:
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    # The install lives in every job that needs the dependency set since the
    # gate split, so scan every job's steps rather than one named job -- and
    # return them all, so a duplicated install can't drop the flag in one
    # copy while another keeps it.
    runs = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            # Line-anchored, not a substring: the requirements-sync step's
            # own comment *mentions* `pip install --require-hashes` in
            # prose, and a substring match would hold its run block to the
            # same flag it only describes.
            if any(
                line.strip().startswith("pip install --require-hashes")
                for line in run.splitlines()
            ):
                runs.append(run)
    return runs


def test_require_hashes_install_exists_and_ignores_installed():
    runs = _find_require_hashes_steps()
    assert runs, (
        "no step in ci.yml runs `pip install --require-hashes` "
        "any more -- has the hash-pin gate been removed or renamed? Update "
        "this test (and re-check #366's hash-verification guarantee still "
        "holds however the install is now shaped) either way."
    )
    for run in runs:
        assert "--ignore-installed" in run, (
            "a --require-hashes install no longer passes --ignore-installed. "
            "Without it, a pin already satisfied by the hosted image's own "
            'tool-cache interpreter reports "Requirement already satisfied" '
            "and skips its hash check -- the #366 failure mode, triggered by an "
            "image refresh rather than cross-job accumulation."
        )
