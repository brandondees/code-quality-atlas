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
SELF_IMPROVEMENT_LOOP = (ROOT / "docs" / "self-improvement-loop.md").read_text(encoding="utf-8")
INSTALL = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
PREFS_TEMPLATE = (ROOT / "templates" / "preferences-template.md").read_text(encoding="utf-8")


def test_log_hook_never_emits_raw_tool_input():
    assert "tool_input: (.tool_input" not in LOG_HOOK
    assert "tool_input_sha256" in LOG_HOOK
    assert "tool_input_len" in LOG_HOOK


def test_retro_hook_never_emits_raw_transcript_path():
    assert "transcript_path: (.transcript_path" not in RETRO_HOOK
    assert "transcript_basename" in RETRO_HOOK


def test_design_doc_names_the_abstracted_fields():
    for needle in ("tool_input_len", "tool_input_sha256", "transcript_basename"):
        assert needle in SELF_IMPROVEMENT_LOOP, (
            f"self-improvement-loop.md no longer names {needle!r} — it must keep "
            "describing what the stage-1 hooks actually write (#364)."
        )
    assert "logging `tool_input` verbatim" not in SELF_IMPROVEMENT_LOOP


def test_design_doc_states_a_retention_rule():
    assert "Retention." in SELF_IMPROVEMENT_LOOP


def test_install_doc_does_not_claim_raw_capture():
    assert "raw tool-input payload" not in INSTALL
    assert "tool-input payload's byte length and SHA-256 digest" in INSTALL
    assert "transcript's basename" in INSTALL


def test_preferences_template_states_a_retention_rule():
    assert "Retention:" in PREFS_TEMPLATE
