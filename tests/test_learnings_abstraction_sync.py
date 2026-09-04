# SPDX-License-Identifier: MIT
# tests/test_learnings_abstraction_sync.py
"""#364: the design doc, the template, and install.md all promise the tier-1
learnings log is "abstracted at creation" — but nothing mechanically tied
that prose to what `hooks/log-skill-invocation.sh` and
`hooks/queue-session-retro.sh` actually write, and for a while the promise
was false (raw `tool_input`, an absolute `transcript_path`). This guards
against that gap reopening: the hook scripts must never regain a raw field,
and the docs that describe the written shape must keep naming the abstracted
one — the same drift-prevention shape as test_review_template_sync.py.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOG_HOOK = (ROOT / "hooks" / "log-skill-invocation.sh").read_text(encoding="utf-8")
RETRO_HOOK = (ROOT / "hooks" / "queue-session-retro.sh").read_text(encoding="utf-8")
SELF_IMPROVEMENT_LOOP = (ROOT / "docs" / "self-improvement-loop.md").read_text(
    encoding="utf-8"
)
INSTALL = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
PREFS_TEMPLATE = (ROOT / "templates" / "preferences-template.md").read_text(
    encoding="utf-8"
)


def test_log_hook_never_emits_raw_tool_input():
    assert "tool_input: (.tool_input" not in LOG_HOOK
    assert "tool_input_sha256" in LOG_HOOK
    assert "tool_input_len" in LOG_HOOK


def test_retro_hook_never_emits_raw_transcript_path():
    assert "transcript_path: (.transcript_path" not in RETRO_HOOK
    assert "transcript_basename" in RETRO_HOOK


def test_retro_hook_basename_split_handles_backslash_paths():
    # #397 review (Copilot): splitting only on "/" left a Windows-style
    # transcript_path un-reduced. The jq filter must normalize backslashes
    # before splitting on "/".
    assert "gsub(" in RETRO_HOOK, (
        "queue-session-retro.sh must normalize backslash separators before "
        "splitting transcript_path into a basename (#397 review)."
    )


def test_design_doc_names_the_abstracted_fields():
    for needle in ("tool_input_len", "tool_input_sha256", "transcript_basename"):
        assert needle in SELF_IMPROVEMENT_LOOP, (
            f"self-improvement-loop.md no longer names {needle!r} — it must keep "
            "describing what the stage-1 hooks actually write (#364)."
        )
    assert "logging `tool_input` verbatim" not in SELF_IMPROVEMENT_LOOP


def test_design_doc_states_a_retention_rule():
    # CodeRabbit's PR #397 finding: match on the concrete guidance, not just
    # the "Retention." heading, so deleting the actual rule can't slip past
    # this check while the heading survives.
    assert "grows without bound" in SELF_IMPROVEMENT_LOOP
    assert "prune or archive old lines" in SELF_IMPROVEMENT_LOOP
    # Pruning the working file doesn't purge Git history/clones/backups —
    # a real gap CodeRabbit caught in the first version of this note.
    assert (
        "doesn't purge" in SELF_IMPROVEMENT_LOOP
        or "stay reachable through Git history" in SELF_IMPROVEMENT_LOOP
    )


def test_install_doc_does_not_claim_raw_capture():
    assert "raw tool-input payload" not in INSTALL
    assert "tool-input payload's byte length" in INSTALL
    assert "transcript's basename" in INSTALL
    # #397 review: the digest isn't guaranteed (no hashing tool on PATH -> null)
    # — the doc must say so rather than implying it's always present.
    assert "null otherwise" in INSTALL or "null" in INSTALL


def test_preferences_template_states_a_retention_rule():
    assert "Retention:" in PREFS_TEMPLATE
    assert "grows without bound" in PREFS_TEMPLATE
    assert "doesn't purge" in PREFS_TEMPLATE


def test_design_doc_and_template_note_digest_is_not_a_hard_privacy_guarantee():
    # CodeRabbit's PR #397 finding: tool_input_sha256 is unkeyed, so a
    # low-entropy tool_input could be recovered offline by hashing
    # candidates and comparing. "Abstracted" must not read as "unrecoverable."
    assert "unkeyed" in SELF_IMPROVEMENT_LOOP
    assert "unkeyed" in PREFS_TEMPLATE
