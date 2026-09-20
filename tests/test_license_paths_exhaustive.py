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

Two escape hatches found in review (#390) are closed here:
1. The original check only asked whether `` `name/` `` occurred *anywhere*
   in LICENSE, so moving a name from the CC BY bullet to the MIT bullet
   (a real re-licensing change) still passed. This version knows which
   bucket each name is expected to be in (`_EXPECTED_BUCKET`, itself the
   ground truth this test enforces LICENSE against — a deliberate
   re-bucketing means updating both files together, which is the point)
   and checks the name appears in *that* bucket's paragraph, not the other.
   Known limitation: a bare substring search still can't tell a bucket
   declaration from an incidental cross-reference elsewhere in the same
   paragraph — e.g. `skills/` is also named in the CC BY bullet's own prose
   describing `collapsed/` ("a generated, byte-derived repackaging of
   `skills/`"), so removing `skills/` from the CC BY bullet's declared list
   alone would not be caught while that aside still mentions it. This
   version catches a directory dropped from its bucket paragraph
   *entirely* (the class of bug the issue this fixes actually named), not
   every partial edit that leaves an incidental same-paragraph mention.
2. The original check enumerated the live filesystem, so an untracked
   top-level directory the repo doesn't own (a build artifact like the
   packaging script's gitignored default `dist/` output) could spuriously
   demand a LICENSE classification just for existing on disk. This version
   enumerates git-tracked paths instead.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that aren't content or code shipped under either license bucket
# (editor/tool state, CI/plugin manifests already covered by LICENSE's "CI
# and configuration files" MIT catch-all). `.claude` is deliberately NOT here
# (issue #375) -- it's real vendored content (CC BY, one third-party MIT
# exception), not editor/tool state, so it's classified below instead.
_EXEMPT = {
    ".github",
    ".claude-plugin",
    ".serena",
}

# Directories LICENSE names in prose rather than as a literal `name/` path.
_PROSE_ALIASES = {
    "tests": "the tests",
}

# The bucket each top-level directory is expected to be declared under in
# LICENSE. This is the ground truth the test checks LICENSE against — adding
# a directory or changing a bucket means updating this dict AND LICENSE
# together, not just one of them.
_EXPECTED_BUCKET = {
    "docs": "cc_by",
    "skills": "cc_by",
    "collapsed": "cc_by",
    "commands": "cc_by",
    "templates": "cc_by",
    ".claude": "cc_by",
    "tooling": "mit",
    "hooks": "mit",
    "tests": "mit",
}

_MIT_BUCKET_MARKER = "**Code — MIT.**"


def _top_level_dirs() -> list[str]:
    """Derived from git-tracked paths, not the live filesystem: an untracked
    top-level directory (e.g. a build artifact) must never spuriously
    require a LICENSE classification just for existing on disk."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    names = {
        line.split("/", 1)[0] for line in result.stdout.splitlines() if "/" in line
    }
    return sorted(names - _EXEMPT)


def _split_license_buckets(license_text: str) -> tuple[str, str]:
    idx = license_text.index(_MIT_BUCKET_MARKER)
    return license_text[:idx], license_text[idx:]


def _names_in(text: str, name: str) -> bool:
    alias = _PROSE_ALIASES.get(name)
    return f"`{name}/`" in text or (alias is not None and alias in text)


def _tracked_files_under(prefix: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", prefix],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def test_nested_mit_exceptions_still_hold():
    """LICENSE's CC BY paragraph carries two nested MIT exceptions the
    top-level, per-directory check above can't see: `.claude/skills/
    icm-architect/` within the otherwise-CC-BY `.claude/` bucket, and
    `collapsed/hooks/` + `collapsed/.claude-plugin/` within the otherwise-
    CC-BY `collapsed/` bucket (#518). This asserts each still carries the
    MIT marker LICENSE promises, so a re-vendor or regeneration that
    silently drops it doesn't go unnoticed."""
    icm_license = ROOT / ".claude/skills/icm-architect/LICENSE"
    assert icm_license.is_file(), (
        f"{icm_license} is missing -- LICENSE's own text names this path as "
        "a vendored third-party MIT exception; either restore the file or "
        "update LICENSE if the vendoring changed."
    )
    icm_license_text = icm_license.read_text(encoding="utf-8")
    assert "MIT License" in icm_license_text, (
        f"{icm_license} no longer reads as an MIT license text -- LICENSE's "
        "top-level prose promises this directory is MIT-licensed."
    )
    assert "Jake Van Clief" in icm_license_text, (
        f"{icm_license} no longer names the upstream copyright holder LICENSE "
        "attributes this vendored skill to."
    )

    icm_notice = ROOT / ".claude/skills/icm-architect/NOTICE.md"
    assert icm_notice.is_file(), f"{icm_notice} is missing -- see #375/D15."
    assert "MIT" in icm_notice.read_text(encoding="utf-8"), (
        f"{icm_notice} no longer states this vendored skill is MIT licensed."
    )

    collapsed_hooks_scripts = [
        p
        for p in _tracked_files_under("collapsed/hooks")
        if p.suffix in (".sh", "") and p.is_file()
    ]
    assert collapsed_hooks_scripts, (
        "No tracked files found under collapsed/hooks/ -- has it been "
        "renamed or removed? Update this test's path (and LICENSE) either way."
    )
    missing_spdx = [
        p.relative_to(ROOT).as_posix()
        for p in collapsed_hooks_scripts
        if "SPDX-License-Identifier: MIT" not in p.read_text(encoding="utf-8")
    ]
    assert not missing_spdx, (
        f"{missing_spdx} under collapsed/hooks/ no longer carry the "
        "'SPDX-License-Identifier: MIT' header LICENSE promises for this "
        "nested exception to the otherwise-CC-BY collapsed/ bucket."
    )

    collapsed_manifest = ROOT / "collapsed/.claude-plugin/plugin.json"
    assert collapsed_manifest.is_file(), f"{collapsed_manifest} is missing."
    assert '"license": "MIT AND CC-BY-4.0"' in collapsed_manifest.read_text(
        encoding="utf-8"
    ), (
        f"{collapsed_manifest} no longer declares the 'MIT AND CC-BY-4.0' "
        "SPDX expression LICENSE says this manifest carries."
    )


def test_every_top_level_directory_is_named_in_license():
    dirs = _top_level_dirs()
    unclassified = [name for name in dirs if name not in _EXPECTED_BUCKET]
    assert not unclassified, (
        f"Top-level director{'y' if len(unclassified) == 1 else 'ies'} "
        f"{unclassified} has no entry in this test's own _EXPECTED_BUCKET. "
        "Add it there and to LICENSE's CC BY / MIT split (or to _EXEMPT "
        "above if it isn't shipped content/code)."
    )

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    cc_by_text, mit_text = _split_license_buckets(license_text)
    wrong_bucket = []
    for name in dirs:
        expected = _EXPECTED_BUCKET[name]
        bucket_text = cc_by_text if expected == "cc_by" else mit_text
        if not _names_in(bucket_text, name):
            wrong_bucket.append((name, expected))
    assert not wrong_bucket, (
        f"LICENSE does not declare the expected bucket for: {wrong_bucket} "
        "— either LICENSE drifted from _EXPECTED_BUCKET above, or the "
        "directory's license was deliberately changed and _EXPECTED_BUCKET "
        "needs updating to match."
    )
