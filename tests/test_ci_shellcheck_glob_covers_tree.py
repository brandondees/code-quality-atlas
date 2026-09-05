# SPDX-License-Identifier: MIT
# tests/test_ci_shellcheck_glob_covers_tree.py
"""The `shellcheck` step in .github/workflows/ci.yml runs only when the
`shell:` paths-filter (`tooling/**/*.sh`, `hooks/**`, `collapsed/hooks/**` --
all recursive, and dorny/paths-filter@v4.0.3 matches dot-prefixed paths too)
reports a change, but the step's own shellcheck invocation previously used
one-level-deep, non-dotglob globs (`tooling/*.sh`, `hooks/lib/*.sh`, ...). A
`.sh` file added under a new subdirectory (e.g. `tooling/lib/helper.sh`) or
with a dot-prefixed name/directory would correctly trigger the step via the
filter, then be silently skipped by the step's own glob -- CI reports green
with no scan having actually happened on the new script (#342).

Mirrors test_ci_python_filter_covers_known_reads.py's approach: rather than
trusting a manual glob-depth audit, assert mechanically that the shellcheck
command's own globs, evaluated against bash's `**`+`dotglob` semantics,
match every `*.sh` file actually present under the trees the `shell:`
filter itself declares (derived from the filter's own YAML, not a
hand-maintained parallel list -- round-1 review finding).
"""

import re
from pathlib import Path

from tests.test_ci_python_filter_covers_known_reads import _load_filter_globs

ROOT = Path(__file__).resolve().parent.parent


def _extract_shellcheck_globs() -> list[str]:
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # The step's `run: |` block is a plain literal block scalar, not
    # re-parseable YAML flow content -- pull out the shellcheck invocation
    # line directly rather than parsing the whole `run:` string generically.
    match = re.search(
        r'^\s*"\$RUNNER_TEMP/bin/shellcheck" --source-path=SCRIPTDIR -x (.+)$',
        ci_text,
        re.MULTILINE,
    )
    assert match, (
        "could not find the shellcheck invocation line in "
        ".github/workflows/ci.yml -- did the step's shape change? "
        "Update this test's extraction regex to match."
    )
    _assert_shopt_covers(ci_text, {"nullglob", "globstar", "dotglob"})
    return match.group(1).split()


def _assert_shopt_covers(ci_text: str, required: set[str]) -> None:
    """The globs alone don't prove coverage: `_glob_to_regex` translates
    `*`/`**` purely syntactically (a bare `*` already matches a leading
    dot as a plain regex character class, with no notion of bash's
    dotglob/globstar runtime options), so this test's simulation would
    stay green even if a future edit dropped `dotglob` or `globstar` from
    the step's `shopt -s ...` line -- exactly the silent-regression shape
    #342 itself was about, just one layer up. Assert the real flags are
    still there so that class of regression fails loudly instead."""
    match = re.search(r"^\s*shopt -s (.+)$", ci_text, re.MULTILINE)
    assert match, (
        "could not find the shellcheck step's `shopt -s ...` line in "
        ".github/workflows/ci.yml -- did the step's shape change? "
        "Update this test's extraction regex to match."
    )
    present = set(match.group(1).split())
    missing = required - present
    assert not missing, (
        f"the shellcheck step's `shopt -s` line is missing {sorted(missing)} "
        "-- without them the globs this test checks no longer match what "
        "bash actually expands at runtime (nullglob: don't literal-match an "
        "empty glob; globstar: recursive `**`; dotglob: match dot-prefixed "
        "paths, which dorny/paths-filter@v4.0.3's `dot: true` already does)"
    )


def _covered_tree_roots() -> list[str]:
    """Derive the real directory trees to search for *.sh files from the
    `shell:` filter's own globs (the literal path segments before the
    first wildcard), instead of hand-maintaining a parallel list that can
    silently drift from the filter it's meant to mirror (round-1 review
    finding: a future tree added to the filter but not here would keep
    this test green while reintroducing the exact gap #342 closes)."""
    roots = []
    for pattern in _load_filter_globs()["shell"]:
        prefix_segments = []
        for seg in pattern.split("/"):
            if "*" in seg:
                break
            prefix_segments.append(seg)
        if prefix_segments:
            roots.append("/".join(prefix_segments))
    return roots


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a bash globstar-enabled glob to a regex, one path segment
    at a time. A segment that is *exactly* `**` matches zero or more whole
    path segments (bash's real globstar semantics for an isolated `**`
    component, wherever it falls -- leading, trailing, or in the middle,
    not just when followed by `/`, per round-1 review). Any other `*`
    matches within its own segment only, never crossing `/` -- real bash
    semantics, not Python's fnmatch (which has no notion of `/` as a
    separator)."""
    segments = glob.split("/")
    parts = [
        "**" if seg == "**" else re.escape(seg).replace(r"\*", "[^/]*")
        for seg in segments
    ]
    pattern = "/".join(parts)
    pattern = pattern.replace("/**/", "/(?:[^/]+/)*")
    if pattern == "**":
        pattern = ".*"
    elif pattern.startswith("**/"):
        pattern = "(?:[^/]+/)*" + pattern[3:]
    elif pattern.endswith("/**"):
        pattern = pattern[:-3] + "(?:/[^/]+)*"
    return re.compile(f"^{pattern}$")


def _matches_any_glob(rel_path: str, globs: list[str]) -> bool:
    return any(_glob_to_regex(g).match(rel_path) for g in globs)


def test_glob_to_regex_treats_globstar_and_star_correctly():
    assert _matches_any_glob("hooks/foo.sh", ["hooks/**/*.sh"]) is True
    assert _matches_any_glob("hooks/lib/foo.sh", ["hooks/**/*.sh"]) is True
    assert _matches_any_glob("hooks/lib/deep/foo.sh", ["hooks/**/*.sh"]) is True
    assert _matches_any_glob("hooks-other/foo.sh", ["hooks/**/*.sh"]) is False
    assert _matches_any_glob("tooling/foo.py", ["tooling/**/*.sh"]) is False
    # Hidden paths are matched too: dorny/paths-filter@v4.0.3 sets
    # picomatch's `dot: true`, and the shellcheck step now sets `dotglob`
    # to match -- both sides of the filter/scan pair now agree.
    assert _matches_any_glob("tooling/.foo.sh", ["tooling/**/*.sh"]) is True
    assert _matches_any_glob("tooling/.hidden/foo.sh", ["tooling/**/*.sh"]) is True


def test_glob_to_regex_handles_a_bare_trailing_globstar():
    """Regression for a round-1 review Nit: a `**` segment not followed by
    `/` (e.g. a hypothetical `tooling/**`, as opposed to today's
    `tooling/**/*.sh`) previously fell through to plain `*` handling and
    lost its recursive-directory semantics. A trailing bare `**` must match
    the root itself (zero segments) and any depth beneath it."""
    assert _matches_any_glob("tooling", ["tooling/**"]) is True
    assert _matches_any_glob("tooling/foo.sh", ["tooling/**"]) is True
    assert _matches_any_glob("tooling/lib/foo.sh", ["tooling/**"]) is True
    assert _matches_any_glob("tooling-other/foo.sh", ["tooling/**"]) is False


def test_shellcheck_globs_cover_every_sh_file_under_the_filtered_trees():
    globs = _extract_shellcheck_globs()
    uncovered = []
    for tree in _covered_tree_roots():
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
