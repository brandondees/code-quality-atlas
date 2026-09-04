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

Deliberately excluded from the comparison: `.atlas-vendored` and `NOTICE.md`,
which both embed the vendoring commit's own SHA. For a normal consumer repo
that SHA is stable — it names a fixed upstream commit. Here the "source" and
the "target" are the same repo, so the SHA recorded at vendor time is always
one commit behind the commit that carries it (a commit's own hash isn't known
until after it's made) — expected staleness in metadata, not drift in the
load-bearing skill content this test actually guards.

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
