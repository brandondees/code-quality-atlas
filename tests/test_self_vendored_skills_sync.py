# SPDX-License-Identifier: MIT
# tests/test_self_vendored_skills_sync.py
"""This repo vendors its own lenses into `.claude/skills/` (via
`tooling/vendor-skills.sh .`) so that reviewing code-quality-atlas itself
resolves lens content through the same `Skill`-tool -> vendored-`.claude/skills/`
path any consuming repo gets from vendoring the suite — not a bespoke,
repo-special-cased fallback (see commands/atlas-review-pr.md step 4, and
docs/distribution.md's Channel B).

Nothing mechanically ties the vendored copy to its skills/ source, so an edit
to a lens's SKILL.md/reference/examples.md could silently leave the vendored
copy stale — the same drift class test_review_template_sync.py guards for
REVIEW.md vs. templates/REVIEW.md.

`.atlas-vendored` and `NOTICE.md` are excluded from the byte-identity walk
below, but not left unchecked: `tooling/vendor-skills.sh` stamps them with a
`<self>` sentinel instead of a literal commit SHA when the vendoring source
and target are the same repo (as they are here) — a real SHA would be false
the instant it's written (a commit's own hash isn't known until after it's
made) and, worse, nothing previously caught it drifting further once
vendoring was simply skipped for several commits (#382, where the marker
named a commit 12 revisions stale). `test_self_vendor_marker_uses_self_sentinel`
below asserts the sentinel is actually there, rather than silently excluding
both files from any check at all.

Also accounted for: both vendored runtime files an agent is likely to open
and hand-edit directly — `SKILL.md` (exactly what the `Skill` tool resolves
and loads) and `examples.md` — carry a trailing do-not-edit marker
(`append_generated_marker` in `vendor-skills.sh`) their `skills/` source
doesn't (#374: initially only `SKILL.md` carried this, `examples.md` was
still compared as plain byte-identity). `reference/*.md` doesn't get the
marker (assembled output with no realistic hand-edit target), so it's still
compared as plain byte-identity.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "skills"
VENDORED = ROOT / ".claude" / "skills"
_RUNTIME_FILES = ("SKILL.md", "examples.md")
# Vendored directories under .claude/skills/ that are NOT sourced from
# skills/ and must not be flagged as orphans by the reverse walk below --
# icm-architect is this repo's own ICM-methodology skill for its cloud
# sessions (docs/distribution.md's Channel B), vendored directly rather than
# generated from skills/manifest.yaml (issue #375 tracks documenting this
# exception properly; until then, this is where a reviewer would otherwise
# rediscover it as "drift").
_NON_SUITE_VENDORED_DIRS = frozenset({"icm-architect"})
# Must match the marker `append_generated_marker` in tooling/vendor-skills.sh
# writes — only the start is asserted, not the full wording, so a rewording
# doesn't require touching this test too.
_GENERATED_MARKER_START = "\n<!-- GENERATED — do not hand-edit this file."


def _skill_names():
    return sorted(
        p.name for p in SRC.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    )


def _marked_runtime_file_matches_source(dest_file, src_text):
    """SKILL.md and examples.md both get a trailing generated-marker their
    source doesn't have — strip it before comparing, and treat a missing
    marker as staleness rather than silently accepting a vendored copy from
    before this marker existed on that file."""
    dest_text = dest_file.read_text(encoding="utf-8")
    idx = dest_text.find(_GENERATED_MARKER_START)
    if idx == -1:
        return False
    return dest_text[:idx] == src_text


def test_every_skill_is_vendored_into_dot_claude_skills():
    missing = [
        name for name in _skill_names() if not (VENDORED / name / "SKILL.md").exists()
    ]
    assert not missing, (
        f"skill(s) missing from .claude/skills/: {missing} — run "
        "`tooling/vendor-skills.sh .` from the repo root and commit the result "
        "(see commands/atlas-review-pr.md step 4 for why this repo self-vendors)."
    )


def test_vendored_skills_match_their_source():
    stale = []
    for name in _skill_names():
        src_dir = SRC / name
        dest_dir = VENDORED / name

        # Both _RUNTIME_FILES carry the trailing generated-marker (#374), so
        # every iteration here uses the marker-aware comparison; only
        # reference/*.md (handled separately below) is plain byte-identity.
        for fname in _RUNTIME_FILES:
            src_file = src_dir / fname
            if not src_file.exists():
                continue  # not every skill ships examples.md
            dest_file = dest_dir / fname
            if not dest_file.exists() or not _marked_runtime_file_matches_source(
                dest_file, src_file.read_text(encoding="utf-8")
            ):
                stale.append(str((dest_dir / fname).relative_to(ROOT)))

        src_ref = src_dir / "reference"
        if not src_ref.is_dir():
            continue
        dest_ref = dest_dir / "reference"
        for src_file in src_ref.rglob("*"):
            if src_file.is_dir():
                continue
            dest_file = dest_ref / src_file.relative_to(src_ref)
            if (
                not dest_file.exists()
                or dest_file.read_bytes() != src_file.read_bytes()
            ):
                stale.append(str(dest_file.relative_to(ROOT)))

    assert not stale, (
        "the following vendored file(s) under .claude/skills/ have drifted from "
        f"their skills/ source: {stale} — re-run `tooling/vendor-skills.sh .` "
        "from the repo root and commit the refreshed .claude/skills/."
    )


def test_no_orphaned_vendored_skill_directories():
    """The forward walk above (skills/ -> .claude/skills/) can never catch an
    orphan on the *other* side: a vendored directory with no skills/ source at
    all (a withdrawn lens vendor-skills.sh --prune never ran for, or a stray
    directory the `Skill` tool would still happily load) passes it silently
    since the forward walk only ever iterates skills/ names (#382). Walk
    .claude/skills/ itself instead, allowlisting the one legitimate
    non-suite directory."""
    source_names = set(_skill_names())
    vendored_dirs = {p.name for p in VENDORED.iterdir() if p.is_dir()}
    orphans = vendored_dirs - source_names - _NON_SUITE_VENDORED_DIRS
    assert not orphans, (
        f"{sorted(orphans)} under .claude/skills/ have no corresponding "
        "skills/ source and aren't in _NON_SUITE_VENDORED_DIRS -- either "
        "re-run `tooling/vendor-skills.sh . --prune` to remove a genuinely "
        "withdrawn lens, or add a deliberate non-suite directory to the "
        "allowlist above with a reason."
    )


def test_vendored_license_matches_source():
    """`.claude/skills/LICENSE-CC-BY-4.0` is vendored alongside the skills
    (write_attribution in tooling/vendor-skills.sh) so a diverged copy would
    ship terms that don't match what this repo actually licenses its content
    under -- not caught by the skills/-keyed forward walk above, since the
    license lives at the repo root, not under skills/ (#382)."""
    vendored_license = VENDORED / "LICENSE-CC-BY-4.0"
    assert vendored_license.is_file(), "expected a vendored LICENSE-CC-BY-4.0"
    assert vendored_license.read_bytes() == (ROOT / "LICENSE-CC-BY-4.0").read_bytes(), (
        ".claude/skills/LICENSE-CC-BY-4.0 has diverged from the repo root's "
        "LICENSE-CC-BY-4.0 -- re-run `tooling/vendor-skills.sh .` and commit "
        "the refresh."
    )


def test_self_vendor_marker_uses_self_sentinel():
    """`vendor-skills.sh` must recognize this as a self-vendor run (source ==
    target) and stamp `<self>` rather than a literal SHA -- a real SHA in
    these two files would be false the moment it's written and, unlike the
    sentinel, gives no signal at all if vendoring is skipped for several
    commits while skills/ keeps changing (#382)."""
    marker = (VENDORED / ".atlas-vendored").read_text(encoding="utf-8")
    assert "@<self>" in marker, (
        "the vendored marker's source= line should read "
        f"'...code-quality-atlas@<self>', not a literal commit SHA: {marker!r}"
    )
    notice = (VENDORED / "NOTICE.md").read_text(encoding="utf-8")
    assert "self-vendored copy" in notice, (
        "NOTICE.md should describe this as a self-vendored copy rather than "
        f"naming a specific upstream commit: {notice!r}"
    )
