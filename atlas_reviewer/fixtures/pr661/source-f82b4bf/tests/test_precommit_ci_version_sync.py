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

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
_ACTION_PIN_RE = re.compile(
    r"DavidAnson/markdownlint-cli2-action@[0-9a-f]{40}\s*#\s*(v[\d.]+)"
)
_PRECOMMIT_COMMENT_RE = re.compile(
    r"action\s+(v[\d.]+)\s+bundles\s+markdownlint-cli2\n#\s*(v[\d.]+)"
)
_MARKDOWNLINT_REPO_URL = "https://github.com/DavidAnson/markdownlint-cli2"


def _markdownlint_hook_rev(precommit_text: str) -> str:
    """The hook's own `rev:`, selected by matching `repo:` — not the first
    `rev:` line the file happens to contain. A regex search for a bare
    `rev:\\s*(v[\\d.]+)` matches whichever repo entry comes first in the
    file, so adding a second hook repo above this one would silently
    retarget the claimed version at the new entry's rev instead (#390).

    `rev:` is a SHA, not a mutable tag (#378/#379) -- a tag can be moved to
    point at different content after the fact, defeating the whole point of
    pinning it, while a commit SHA can't. The human-readable version lives
    only in the trailing `# vX.Y.Z` comment on that same line."""
    config = yaml.safe_load(precommit_text)
    for repo in config.get("repos", []):
        if repo.get("repo") == _MARKDOWNLINT_REPO_URL:
            sha = repo["rev"]
            assert re.fullmatch(r"[0-9a-f]{40}", sha), (
                f".pre-commit-config.yaml pins markdownlint-cli2's rev to "
                f"{sha!r}, which isn't a 40-character commit SHA -- a "
                "mutable tag here can be moved to point at different "
                "content after the fact (#378/#379)."
            )
            # (?m) + `^`/`$` + horizontal-whitespace-only classes, not a bare
            # `\s*`: the latter matches across newlines too, so a comment on
            # the *next* line ("rev: <sha>\n# v0.23.2") would satisfy this
            # search even though it isn't the trailing same-line comment the
            # docstring above promises (CodeRabbit review finding on #379).
            comment_match = re.search(
                rf"(?m)^[ \t]*rev:[ \t]*{re.escape(sha)}"
                rf"[ \t]*#[ \t]*(v\d+\.\d+\.\d+)[ \t]*$",
                precommit_text,
            )
            assert comment_match, (
                f".pre-commit-config.yaml's rev ({sha}) has no trailing, "
                "same-line '# vX.Y.Z' comment recording which release that "
                "SHA is -- add one, e.g. 'rev: <sha> # v0.23.2'."
            )
            return comment_match.group(1)
    raise AssertionError(
        f"No {_MARKDOWNLINT_REPO_URL} entry found in .pre-commit-config.yaml"
    )


def _precommit_yaml(rev_and_comment: str) -> str:
    return (
        "repos:\n"
        "  - repo: https://github.com/DavidAnson/markdownlint-cli2\n"
        f"    {rev_and_comment}\n"
        "    hooks:\n"
        "      - id: markdownlint-cli2\n"
    )


def test_markdownlint_hook_rev_requires_same_line_comment():
    """CodeRabbit review finding on #379: a bare `\\s*` between the SHA and
    the `#` comment matches across newlines too, so a comment on the line
    *after* `rev:` would previously satisfy the search even though it isn't
    the trailing same-line comment the function's own contract promises."""
    sha = "b82a6c8896e491b9cb377a99ff3412131920681b"
    precommit_text = _precommit_yaml(f"rev: {sha}\n    # v0.23.2")

    with pytest.raises(AssertionError, match="no trailing, same-line"):
        _markdownlint_hook_rev(precommit_text)


def test_markdownlint_hook_rev_accepts_same_line_comment():
    sha = "b82a6c8896e491b9cb377a99ff3412131920681b"
    precommit_text = _precommit_yaml(f"rev: {sha} # v0.23.2")

    assert _markdownlint_hook_rev(precommit_text) == "v0.23.2"


def test_precommit_markdownlint_rev_matches_ci_claimed_version():
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    action_match = _ACTION_PIN_RE.search(ci_text)
    assert action_match, (
        "Could not find a SHA-pinned DavidAnson/markdownlint-cli2-action step "
        "in .github/workflows/ci.yml — has the pin format changed?"
    )
    ci_action_version = action_match.group(1)

    precommit_text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    comment_match = _PRECOMMIT_COMMENT_RE.search(precommit_text)
    assert comment_match, (
        "Could not find the 'action vX.Y.Z bundles markdownlint-cli2 vA.B.C' "
        "comment in .pre-commit-config.yaml — has its wording changed?"
    )
    claimed_action_version, claimed_bundled_version = comment_match.groups()

    actual_rev_version = _markdownlint_hook_rev(precommit_text)

    assert claimed_action_version == ci_action_version, (
        f".pre-commit-config.yaml's comment claims CI pins "
        f"markdownlint-cli2-action {claimed_action_version}, but ci.yml "
        f"actually pins {ci_action_version}. Update the comment (and re-check "
        f"the bundled markdownlint-cli2 version it names) to match."
    )
    assert claimed_bundled_version == actual_rev_version, (
        f".pre-commit-config.yaml's comment claims the bundled markdownlint-cli2 "
        f"version is {claimed_bundled_version}, but the hook's 'rev:' SHA is "
        f"tagged {actual_rev_version} in its own trailing comment. Keep the "
        "comment above and the rev's own version comment in sync."
    )
