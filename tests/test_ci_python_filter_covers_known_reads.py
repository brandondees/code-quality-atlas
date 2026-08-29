# SPDX-License-Identifier: MIT
# tests/test_ci_python_filter_covers_known_reads.py
"""Three review rounds on the PR that added per-step CI gating (#340) each
found the `python:` path filter in .github/workflows/ci.yml missing paths
that tests/*.py actually read -- the audit that produced a fix each round
checked only part of the picture (round 1: `tooling/*.py` only; round 2: a
partial `tests/*.py` sweep) and missed the rest. This test closes the loop:
it asserts every path this file knows tests/*.py actually reads resolves
under the `python`/`requirements` filter globs that gate the `tests` step,
so a future gap is a failing test here rather than a fourth review round.

This is NOT a fully automatic static-analysis guard (extracting every
Path(...).read_text()/open() call from every test file via AST would be more
robust, but far more work to get right without false positives on computed
or fixture paths) -- it's a maintained inventory of the *known* external
reads, cross-checked mechanically against the filter. Widen
_KNOWN_EXTERNAL_READS when a new test starts reading a new repo path outside
skills/**, collapsed/**, tooling/**, tests/**, docs/research/**, and *.py
(already covered by the filter's broad directory/extension globs and not
itemized here).
"""
import fnmatch
from pathlib import Path

import yaml

from tests.test_doc_counts import _LIVING_COUNT_FILES

ROOT = Path(__file__).resolve().parent.parent

_KNOWN_EXTERNAL_READS = (
    *_LIVING_COUNT_FILES,  # test_doc_counts.py's own inventory -- imported, not copied
    "commands/atlas-init.md",       # test_routing_snippet_sync.py
    "templates/agents-routing-snippet.md",
    "templates/REVIEW.md",          # test_review_template_sync.py
    "REVIEW.md",
    "AGENTS.md",                    # test_routing_snippet_sync.py
    "CLAUDE.md",
    "docs/map/CLAUDE.md",           # test_map_twins_sync.py
    "docs/map/AGENTS.md",
    "docs/map/routing.md",
    "docs/map/_templates/process.md",
    "LICENSE",                      # test_license_paths_exhaustive.py
    ".pre-commit-config.yaml",      # test_precommit_ci_version_sync.py
    ".github/workflows/ci.yml",
    "hooks/hooks.json",             # test_hooks.py
    "hooks/log-skill-invocation.sh",
    "hooks/queue-session-retro.sh",
    "hooks/route.sh",
    "hooks/lib/feedback-tier.sh",
    ".claude-plugin/plugin.json",   # test_doc_counts.py
    ".claude-plugin/marketplace.json",
    ".claude/skills/**",            # test_self_vendored_skills_sync.py, test_map_twins_sync.py
)


def _load_filter_globs() -> dict:
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ci = yaml.safe_load(ci_text)
    filter_step = next(
        s for s in ci["jobs"]["gate"]["steps"]
        if s.get("uses", "").startswith("dorny/paths-filter@")
    )
    # dorny/paths-filter's `filters:` input is itself a YAML document
    # embedded as a string -- parse it a second time to get the real list.
    return yaml.safe_load(filter_step["with"]["filters"])


def _matches_any_glob(rel_path: str, globs: list) -> bool:
    for pattern in globs:
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if rel_path == prefix or rel_path.startswith(prefix + "/"):
                return True
            continue
        # dorny/paths-filter (minimatch-backed) matches segment-by-segment:
        # a pattern with no "**" must have the same number of "/"-separated
        # segments as the path, and each segment matches independently -- a
        # bare "*" never crosses a "/". Plain fnmatch.fnmatch on the whole
        # string would get this wrong: Python's fnmatch has no notion of "/"
        # as a separator, so "*.py" would (incorrectly) report a match
        # against "src/foo.py" too, when the real filter -- and this repo's
        # actual `*.py` entry, which is deliberately root-level-only per its
        # neighboring skills/**/tooling/**/tests/**/etc. globs -- would not.
        # (CodeRabbit finding, PR #340 round 4.)
        pattern_segs = pattern.split("/")
        path_segs = rel_path.split("/")
        if len(pattern_segs) != len(path_segs):
            continue
        if all(fnmatch.fnmatch(p, seg) for p, seg in zip(path_segs, pattern_segs)):
            return True
    return False


def test_matches_any_glob_does_not_let_a_bare_wildcard_cross_a_directory_boundary():
    """Regression for a CodeRabbit finding (round 4): a bare `*` in a
    filter pattern never crosses a `/`, matching dorny/paths-filter's real
    (minimatch-backed) semantics -- unlike Python's fnmatch, whose `*` has
    no notion of `/` as a separator and would incorrectly treat `*.py` as
    matching a nested path like `src/foo.py` too."""
    assert _matches_any_glob("conftest.py", ["*.py"]) is True
    assert _matches_any_glob("src/foo.py", ["*.py"]) is False
    # A directory glob ("dir/**") is unaffected -- it's still meant to match
    # at any depth beneath it.
    assert _matches_any_glob("skills/foo/SKILL.md", ["skills/**"]) is True


def test_python_filter_covers_every_known_external_read():
    filters = _load_filter_globs()
    # Only `python`/`requirements` gate the `tests` step (see the `if:` on
    # that step in ci.yml) -- `shell` and `markdown` gate their own
    # independent steps and do NOT make `tests` run, so a path covered only
    # by those doesn't count here even if it's also read by a test (e.g.
    # hooks/** is in `shell` for shellcheck, but tests/test_hooks.py needs
    # `python` specifically to make the `tests` step itself run).
    covering_globs = filters["python"] + filters.get("requirements", [])
    uncovered = [
        rel for rel in _KNOWN_EXTERNAL_READS
        if not _matches_any_glob(rel, covering_globs)
    ]
    assert not uncovered, (
        "the following path(s) are read by tests/*.py but aren't covered "
        "by ci.yml's `python`/`requirements` path filters (a PR touching "
        f"only one would silently skip the `tests` step): {uncovered} -- "
        "add them to the `python` filter in .github/workflows/ci.yml"
    )
