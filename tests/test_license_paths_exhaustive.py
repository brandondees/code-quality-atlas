# SPDX-License-Identifier: MIT
# tests/test_license_paths_exhaustive.py
"""LICENSE splits the repo's content into CC BY 4.0 vs. MIT buckets by
top-level directory. That enumeration went stale once already: `commands/`,
`templates/`, and `collapsed/` were added after LICENSE was last touched and
went unmentioned in either bucket, leaving `collapsed/` (generated CC BY
content) implicitly caught by the "everything else is MIT" catch-all
(issue #147). This test fails the build whenever a new top-level directory
is added without being named in LICENSE, so the split can't silently go
stale again.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that aren't content or code shipped under either license bucket
# (VCS internals, editor/tool state, CI/plugin manifests already covered by
# LICENSE's "CI and configuration files" MIT catch-all).
_EXEMPT = {
    ".git",
    ".github",
    ".claude",
    ".claude-plugin",
    ".serena",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
}

# Directories LICENSE names in prose rather than as a literal `name/` path.
_PROSE_ALIASES = {
    "tests": "the tests",
}


def _top_level_dirs() -> list[str]:
    return sorted(
        p.name
        for p in ROOT.iterdir()
        if p.is_dir() and p.name not in _EXEMPT
    )


def test_every_top_level_directory_is_named_in_license():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    missing = [
        name
        for name in _top_level_dirs()
        if f"`{name}/`" not in license_text
        and (name not in _PROSE_ALIASES or _PROSE_ALIASES[name] not in license_text)
    ]
    assert not missing, (
        f"Top-level director{'y' if len(missing) == 1 else 'ies'} "
        f"{missing} not classified in LICENSE's CC BY / MIT split. Add "
        f"each to the appropriate bucket (or to _EXEMPT above if it isn't "
        f"shipped content/code)."
    )
