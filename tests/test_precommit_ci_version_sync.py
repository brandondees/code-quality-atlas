# SPDX-License-Identifier: MIT
# tests/test_precommit_ci_version_sync.py
"""`.pre-commit-config.yaml`'s markdownlint-cli2 hook is meant to run the same
engine version as CI's `markdownlint-cli2-action` (see that file's own
comment). Nothing mechanically enforced this — dependabot only tracks the
github-actions/pip ecosystems, not the pre-commit repo — so a CI action bump
(PR #119) silently drifted the two out of sync for a month before a manual
audit caught it (#134, fixed by #135). This test closes that gap: it fails
the build whenever either half of the claimed alignment goes stale again.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ACTION_PIN_RE = re.compile(
    r"DavidAnson/markdownlint-cli2-action@[0-9a-f]{40}\s*#\s*(v[\d.]+)"
)
_PRECOMMIT_COMMENT_RE = re.compile(
    r"action\s+(v[\d.]+)\s+bundles\s+markdownlint-cli2\n#\s*(v[\d.]+)"
)
_PRECOMMIT_REV_RE = re.compile(r"rev:\s*(v[\d.]+)")


def test_precommit_markdownlint_rev_matches_ci_claimed_version():
    ci_text = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    action_match = _ACTION_PIN_RE.search(ci_text)
    assert action_match, (
        "Could not find a SHA-pinned DavidAnson/markdownlint-cli2-action step "
        "in .github/workflows/ci.yml — has the pin format changed?"
    )
    ci_action_version = action_match.group(1)

    precommit_text = (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    comment_match = _PRECOMMIT_COMMENT_RE.search(precommit_text)
    assert comment_match, (
        "Could not find the 'action vX.Y.Z bundles markdownlint-cli2 vA.B.C' "
        "comment in .pre-commit-config.yaml — has its wording changed?"
    )
    claimed_action_version, claimed_bundled_version = comment_match.groups()

    rev_match = _PRECOMMIT_REV_RE.search(precommit_text)
    assert rev_match, "Could not find 'rev: vX.Y.Z' in .pre-commit-config.yaml"
    actual_rev = rev_match.group(1)

    assert claimed_action_version == ci_action_version, (
        f".pre-commit-config.yaml's comment claims CI pins "
        f"markdownlint-cli2-action {claimed_action_version}, but ci.yml "
        f"actually pins {ci_action_version}. Update the comment (and re-check "
        f"the bundled markdownlint-cli2 version it names) to match."
    )
    assert claimed_bundled_version == actual_rev, (
        f".pre-commit-config.yaml's comment claims the bundled markdownlint-cli2 "
        f"version is {claimed_bundled_version}, but the hook's 'rev:' is pinned "
        f"to {actual_rev}. Keep the comment and the rev in sync."
    )
