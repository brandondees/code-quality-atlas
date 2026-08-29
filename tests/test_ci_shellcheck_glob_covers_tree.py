# SPDX-License-Identifier: MIT
# tests/test_ci_shellcheck_glob_covers_tree.py
"""The `shellcheck` step in .github/workflows/ci.yml runs only when the
`shell:` paths-filter (`tooling/**/*.sh`, `hooks/**`, `collapsed/hooks/**` --
all recursive) reports a change, but the step's own shellcheck invocation
previously used one-level-deep globs (`tooling/*.sh`, `hooks/lib/*.sh`, ...).
A `.sh` file added under a new subdirectory (e.g. `tooling/lib/helper.sh`)
would correctly trigger the step via the filter, then be silently skipped by
the step's own glob -- CI reports green with no scan having actually
happened on the new script (#342).

Mirrors test_ci_python_filter_covers_known_reads.py's approach: rather than
trusting a manual glob-depth audit, assert mechanically that the shellcheck
command's own globs, evaluated against bash's `**` (globstar) semantics,
match every `*.sh` file actually present under the three covered trees.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_COVERED_TREES = ("tooling", "hooks", "collapsed/hooks")


def _extract_shellcheck_globs() -> list[str]:
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # The step's `run: |` block is a plain literal block scalar, not
    # re-parseable YAML flow content -- pull out the shellcheck invocation
    # line directly rather than parsing the whole `run:` string generically.
    match = re.search(
        r'^\s*"\$HOME/\.local/bin/shellcheck" --source-path=SCRIPTDIR -x (.+)$',
        ci_text,
        re.MULTILINE,
    )
    assert match, (
        "could not find the shellcheck invocation line in "
        ".github/workflows/ci.yml -- did the step's shape change? "
        "Update this test's extraction regex to match."
    )
    return match.group(1).split()


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a bash globstar-enabled glob to a regex. `**/` matches zero
    or more path segments (each followed by `/`); a bare `*` matches within
    one segment only, never crossing `/` -- real bash globstar semantics,
    not Python's fnmatch (which has no notion of `/` as a separator)."""
    pattern = re.escape(glob)
    pattern = pattern.replace(re.escape("**/"), "(?:[^/]+/)*")
    pattern = pattern.replace(re.escape("*"), "[^/]*")
    return re.compile(f"^{pattern}$")


def _matches_any_glob(rel_path: str, globs: list[str]) -> bool:
    return any(_glob_to_regex(g).match(rel_path) for g in globs)


def test_glob_to_regex_treats_globstar_and_star_correctly():
    assert _matches_any_glob("hooks/foo.sh", ["hooks/**/*.sh"]) is True
    assert _matches_any_glob("hooks/lib/foo.sh", ["hooks/**/*.sh"]) is True
    assert _matches_any_glob("hooks/lib/deep/foo.sh", ["hooks/**/*.sh"]) is True
    assert _matches_any_glob("hooks-other/foo.sh", ["hooks/**/*.sh"]) is False
    assert _matches_any_glob("tooling/foo.py", ["tooling/**/*.sh"]) is False


def test_shellcheck_globs_cover_every_sh_file_under_the_filtered_trees():
    globs = _extract_shellcheck_globs()
    uncovered = []
    for tree in _COVERED_TREES:
        tree_dir = ROOT / tree
        if not tree_dir.is_dir():
            continue
        for sh_file in tree_dir.rglob("*.sh"):
            rel = sh_file.relative_to(ROOT).as_posix()
            if not _matches_any_glob(rel, globs):
                uncovered.append(rel)
    assert not uncovered, (
        "the following *.sh file(s) exist under a tree the `shell:` "
        "paths-filter covers, but the shellcheck step's own globs would "
        f"not scan them: {uncovered} -- widen the glob(s) in the "
        "shellcheck step of .github/workflows/ci.yml"
    )
