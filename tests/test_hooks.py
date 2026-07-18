# SPDX-License-Identifier: MIT
# tests/test_hooks.py
"""Q17/D17 stage 1: the PostToolUse invocation logger and SessionEnd retro
queue must default to off, gate correctly on the feedback tier (env override,
then a ratified `.code-quality-atlas/preferences.md` line, ignoring commented-
out template examples), and degrade to a clean no-op on malformed input or a
missing `jq` — never block or crash the calling session."""
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_HOOK = REPO_ROOT / "hooks" / "log-skill-invocation.sh"
RETRO_HOOK = REPO_ROOT / "hooks" / "queue-session-retro.sh"

_SKILL_INPUT = json.dumps({
    "session_id": "s1",
    "hook_event_name": "PostToolUse",
    "tool_name": "Skill",
    "tool_input": {"skill": "checking-restraint"},
})
_SESSION_END_INPUT = json.dumps({
    "session_id": "s1",
    "hook_event_name": "SessionEnd",
    "transcript_path": "/tmp/some-transcript.jsonl",
    "reason": "clear",
})


def _run(hook, cwd, stdin, env_extra=None):
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd)}
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["bash", str(hook)], cwd=str(cwd), input=stdin,
        capture_output=True, text=True, timeout=10, env=env,
    )
    assert result.returncode == 0, f"{hook.name} must always exit 0: {result.stderr}"
    return result


def _learnings_dir(cwd):
    return cwd / ".code-quality-atlas" / "learnings"


def test_default_off_no_ops(tmp_path):
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT)
    _run(RETRO_HOOK, tmp_path, _SESSION_END_INPUT)
    assert not _learnings_dir(tmp_path).exists()


def test_env_override_enables_logging(tmp_path):
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[-1])
    assert record["session_id"] == "s1"
    assert record["tool_name"] == "Skill"
    assert record["tool_input"] == {"skill": "checking-restraint"}
    assert record["plugin_sha"]   # this repo is a git checkout; resolvable
    assert "ts" in record


def test_session_end_queues_retro_under_env_override(tmp_path):
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(RETRO_HOOK, tmp_path, _SESSION_END_INPUT, env_extra=env)
    queue = _learnings_dir(tmp_path) / "pending-retro.jsonl"
    assert queue.exists()
    record = json.loads(queue.read_text().strip().splitlines()[-1])
    assert record["transcript_path"] == "/tmp/some-transcript.jsonl"
    assert record["reason"] == "clear"


def test_invalid_env_tier_falls_back_to_off(tmp_path):
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "yolo"}
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    assert not _learnings_dir(tmp_path).exists()


def test_commented_out_template_example_does_not_activate(tmp_path):
    # The shipped preferences template ships every example, including a
    # feedback tier, commented out inside an HTML comment block; a repo that
    # copies it verbatim (never ratifying the line) must stay opted out.
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "## Feedback & learnings\n\n"
        "<!--\n"
        "feedback: local\n"
        "-->\n")
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT)
    assert not _learnings_dir(tmp_path).exists()


def test_earlier_single_line_comment_does_not_swallow_a_later_ratified_line(tmp_path):
    # Regression for the atlas's own round-1 self-review of this PR: the awk
    # comment-stripper's `incomment` flag previously never reset within a
    # single line (`/<!--/ { incomment=1; next }` short-circuited before the
    # same line's `-->` could be checked), so a self-contained one-line HTML
    # comment anywhere earlier in the file left every subsequent line —
    # including a validly-ratified `feedback:` line — treated as commented
    # out, silently resolving to "off".
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "# Team preferences\n"
        "<!-- ratified 2026-01-01, see PR #42 -->\n\n"
        "## Feedback & learnings\n\n"
        "feedback: local\n"
        "decided: 2026-07-18, @alice\n")
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)})
    assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_ratified_preferences_line_activates_logging(tmp_path):
    # An uncommented `feedback: local` line under the repo's own preferences
    # overlay must enable logging without any env var.
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "## Feedback & learnings\n\n"
        "feedback: local\n"
        "decided: 2026-07-18, @alice\n")
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)})
    assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_malformed_stdin_json_is_a_clean_no_op(tmp_path):
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(LOG_HOOK, tmp_path, "not json at all", env_extra=env)
    # Directory creation is allowed (mkdir -p happens before the jq parse
    # attempt); the file must simply gain no bogus line.
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    assert not log.exists() or log.read_text() == ""


def test_missing_jq_degrades_to_no_op(tmp_path):
    # A minimal PATH with every common coreutil except jq, so `command -v jq`
    # genuinely fails rather than skipping a real system jq via a fragile
    # env trick.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for tool in ("bash", "cat", "mkdir", "printf", "date", "git", "grep",
                 "sed", "awk", "dirname", "cd", "sh"):
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
           "PATH": str(fake_bin), "HOME": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(LOG_HOOK)], cwd=str(tmp_path), input=_SKILL_INPUT,
        capture_output=True, text=True, timeout=10, env=env,
    )
    assert result.returncode == 0
    assert not _learnings_dir(tmp_path).exists()


def test_hooks_registered_in_hooks_json():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())
    post_tool_use = hooks["hooks"]["PostToolUse"]
    assert any(h["matcher"] == "Skill" for h in post_tool_use)
    assert "SessionEnd" in hooks["hooks"]
    assert "SessionStart" in hooks["hooks"]   # the pre-existing router hook survives
