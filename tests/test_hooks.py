# SPDX-License-Identifier: MIT
# tests/test_hooks.py
"""Q17/D17 stage 1: the PostToolUse invocation logger and SessionEnd retro
queue must default to off, gate correctly on the feedback tier (env override,
then a ratified `.code-quality-atlas/preferences.md` line, ignoring commented-
out template examples), and degrade to a clean no-op on malformed input or a
missing `jq` — never block or crash the calling session."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_HOOK = REPO_ROOT / "hooks" / "log-skill-invocation.sh"
RETRO_HOOK = REPO_ROOT / "hooks" / "queue-session-retro.sh"
ROUTE_HOOK = REPO_ROOT / "hooks" / "route.sh"

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
        capture_output=True, text=True, timeout=10, env=env, check=False,
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
    assert record["plugin_sha"]   # this repo is a git checkout; resolvable
    assert "ts" in record
    # #364: the raw tool_input payload is never written — only its shape-
    # independent abstraction (byte length + digest of the compact JSON).
    assert "tool_input" not in record
    compact = json.dumps({"skill": "checking-restraint"}, separators=(",", ":"))
    # tool_input_len is a byte count (the hook computes it with `wc -c`), so
    # compare against the UTF-8 encoded length, not Python's codepoint count
    # (len(compact)) — they coincide for this ASCII fixture but would diverge
    # for a multi-byte payload, per test_env_override_byte_length_is_utf8_bytes.
    assert record["tool_input_len"] == len(compact.encode("utf-8"))
    assert record["tool_input_sha256"] == hashlib.sha256(compact.encode()).hexdigest()


def test_env_override_byte_length_is_utf8_bytes_not_codepoints(tmp_path):
    # Regression for Copilot's PR #397 finding: a codepoint-count assertion
    # would pass by coincidence on ASCII input and mask the hook computing
    # something other than a true byte count for multi-byte characters.
    skill_input = json.dumps({
        "session_id": "s1",
        "hook_event_name": "PostToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill": "café ☂"},
    })
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(LOG_HOOK, tmp_path, skill_input, env_extra=env)
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    record = json.loads(log.read_text().strip().splitlines()[-1])
    # jq's compact output keeps raw UTF-8 (no \uXXXX escaping), so the
    # expected serialization must be built the same way to match what the
    # hook actually hashes/measures.
    compact = json.dumps({"skill": "café ☂"}, separators=(",", ":"), ensure_ascii=False)
    assert len(compact.encode("utf-8")) != len(compact)   # the fixture must actually be multi-byte
    assert record["tool_input_len"] == len(compact.encode("utf-8"))
    assert record["tool_input_sha256"] == hashlib.sha256(compact.encode("utf-8")).hexdigest()


def test_env_override_hashes_with_sorted_keys_so_key_order_does_not_matter(tmp_path):
    # Regression for CodeRabbit's PR #397 finding: `jq -c` preserves the
    # original key order, so two logically-equivalent tool_input payloads
    # with differently ordered keys would hash differently — undermining
    # tool_input_sha256's use for future repeat-input analysis (§3.4). The
    # hook must serialize with sorted keys (jq -cS) before hashing.
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    ordered_a = json.dumps({
        "session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Skill",
        "tool_input": {"a": 1, "b": 2},
    })
    ordered_b = json.dumps({
        "session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Skill",
        "tool_input": {"b": 2, "a": 1},
    })
    _run(LOG_HOOK, tmp_path, ordered_a, env_extra=env)
    _run(LOG_HOOK, tmp_path, ordered_b, env_extra=env)
    lines = (_learnings_dir(tmp_path) / "invocations.jsonl").read_text().strip().splitlines()
    record_a, record_b = (json.loads(line) for line in lines[-2:])
    assert record_a["tool_input_sha256"] == record_b["tool_input_sha256"]
    assert record_a["tool_input_len"] == record_b["tool_input_len"]


def test_env_override_preserves_explicit_false_tool_input(tmp_path):
    # Regression for CodeRabbit's PR #397 finding: `.tool_input // null`
    # folds an explicitly-provided `false` (or any falsy-but-present JSON
    # value) into the same "no input" bucket as an absent/null tool_input,
    # via jq's `//` operator treating false as falsy too. The hook must
    # distinguish "tool_input is present and false" from "tool_input is
    # absent or null" so the recorded length/hash reflect what was sent.
    skill_input = json.dumps({
        "session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Skill",
        "tool_input": False,
    })
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(LOG_HOOK, tmp_path, skill_input, env_extra=env)
    record = json.loads((_learnings_dir(tmp_path) / "invocations.jsonl").read_text().strip().splitlines()[-1])
    assert record["tool_input_len"] == len("false")
    assert record["tool_input_sha256"] == hashlib.sha256(b"false").hexdigest()


def test_env_override_degrades_to_null_digest_without_a_hashing_tool(tmp_path):
    # Regression for the atlas reviewer's PR #397 finding: a PATH with `jq`
    # but neither `sha256sum` nor `shasum` must still log the invocation —
    # with a real tool_input_len and a null (not missing, not a crash)
    # tool_input_sha256 — rather than silently dropping the record or
    # producing an undocumented shape.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for tool in ("bash", "cat", "mkdir", "printf", "date", "git", "grep",
                 "sed", "awk", "dirname", "cd", "sh", "jq", "wc", "tr", "cut"):
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)
    assert not (fake_bin / "sha256sum").exists()
    assert not (fake_bin / "shasum").exists()
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
           "PATH": str(fake_bin), "HOME": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(LOG_HOOK)], cwd=str(tmp_path), input=_SKILL_INPUT,
        capture_output=True, text=True, timeout=10, env=env, check=False,
    )
    assert result.returncode == 0
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[-1])
    compact = json.dumps({"skill": "checking-restraint"}, separators=(",", ":"))
    assert record["tool_input_len"] == len(compact.encode("utf-8"))
    assert record["tool_input_sha256"] is None


def test_session_end_queues_retro_under_env_override(tmp_path):
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(RETRO_HOOK, tmp_path, _SESSION_END_INPUT, env_extra=env)
    queue = _learnings_dir(tmp_path) / "pending-retro.jsonl"
    assert queue.exists()
    record = json.loads(queue.read_text().strip().splitlines()[-1])
    # #364: never the full absolute transcript_path (leaks OS username,
    # $HOME, and project layout) — only its basename.
    assert "transcript_path" not in record
    assert record["transcript_basename"] == "some-transcript.jsonl"
    assert record["reason"] == "clear"


def test_session_end_basename_strips_windows_backslash_paths_too(tmp_path):
    # Regression for Copilot's PR #397 finding: splitting only on "/" left a
    # Windows-style transcript_path (backslash separators) un-reduced, so the
    # full absolute path — OS username, home directory, project layout —
    # would still leak into the committed pending-retro.jsonl.
    session_end_input = json.dumps({
        "session_id": "s1",
        "hook_event_name": "SessionEnd",
        "transcript_path": r"C:\Users\alice\.claude\projects\foo\abc-123.jsonl",
        "reason": "clear",
    })
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(RETRO_HOOK, tmp_path, session_end_input, env_extra=env)
    queue = _learnings_dir(tmp_path) / "pending-retro.jsonl"
    record = json.loads(queue.read_text().strip().splitlines()[-1])
    assert "transcript_path" not in record
    assert record["transcript_basename"] == "abc-123.jsonl"


def test_session_end_empty_transcript_path_yields_null_basename_not_empty_string(tmp_path):
    # Regression for the atlas reviewer's PR #397 finding: jq's `if` only
    # treats null/false as falsy, so `if .transcript_path then ...` alone
    # would turn an (unlikely but possible) empty-string transcript_path
    # into transcript_basename: "" instead of null, diverging from the
    # documented "basename or null" contract.
    session_end_input = json.dumps({
        "session_id": "s1",
        "hook_event_name": "SessionEnd",
        "transcript_path": "",
        "reason": "clear",
    })
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(RETRO_HOOK, tmp_path, session_end_input, env_extra=env)
    queue = _learnings_dir(tmp_path) / "pending-retro.jsonl"
    record = json.loads(queue.read_text().strip().splitlines()[-1])
    assert record["transcript_basename"] is None


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


def test_template_shaped_trailing_comment_still_activates_logging(tmp_path):
    # #251: templates/preferences-template.md:164 ships the ratified example
    # with a trailing inline comment on the same line as the value —
    # `feedback: local      # off (default, hooks no-op) | local (...` — which
    # is exactly what a team gets by editing the template's own shown `off`
    # to `local` in place. The old strict end-anchored match required the
    # value to be the last thing on the line and silently fell through to
    # "off" on this literal, template-shaped input.
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "## Feedback & learnings\n\n"
        "feedback: local      # off (default, hooks no-op) | local (invocation log +\n"
        "#                     a session-end retro queue land in\n"
        "#                     .code-quality-atlas/learnings/, read by this team's own\n"
        "#                     retro tooling — never transmitted anywhere by this\n"
        "#                     setting alone) | draft | auto (stages 2+, unbuilt)\n"
        "decided: 2026-01-01, @alice\n"
        "reason: local-only telemetry is safe by construction\n")
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


# --- #305: the collapsed plugin (code-quality-atlas-collapsed) shipped with no
# hooks/ directory at all, so a collapsed install got neither the SessionStart
# routing nudge nor the opt-in telemetry hooks. collapsed/hooks/ mirrors
# hooks/, except route.sh's steering message, which is intentionally NOT
# shared: the collapsed plugin's source ("./collapsed") ships none of the
# standalone plugin's 44 skills, router, or commands/ — only the 4 collapsed
# entrypoints — so the nudge must name what's actually installed.

COLLAPSED_HOOKS_DIR = REPO_ROOT / "collapsed" / "hooks"


def test_collapsed_hooks_json_matches_standalone():
    # hooks.json's structure (which hooks fire on which events) has no
    # collapsed-specific content, so it must stay byte-identical to the
    # standalone copy rather than silently drifting apart.
    standalone = (REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
    collapsed = (COLLAPSED_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8")
    assert collapsed == standalone


def test_collapsed_generic_hook_scripts_match_standalone():
    # log-skill-invocation.sh, queue-session-retro.sh, and lib/feedback-tier.sh
    # carry no skill-name-specific content (unlike route.sh), so they must
    # stay byte-identical between the two plugin forms.
    for rel in ("log-skill-invocation.sh", "queue-session-retro.sh", "lib/feedback-tier.sh"):
        standalone = (REPO_ROOT / "hooks" / rel).read_text(encoding="utf-8")
        collapsed = (COLLAPSED_HOOKS_DIR / rel).read_text(encoding="utf-8")
        assert collapsed == standalone, f"collapsed/hooks/{rel} has drifted from hooks/{rel}"


def test_collapsed_route_hook_names_collapsed_entrypoints_not_standalone_surface():
    result = subprocess.run(
        ["bash", str(COLLAPSED_HOOKS_DIR / "route.sh")],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    for entrypoint in ("reviewing-a-change", "auditing-a-repository",
                       "reviewing-a-decision", "reviewing-an-artifact"):
        assert entrypoint in context
    # Standalone-only surface (not shipped under collapsed/'s own plugin root)
    # must not be named — it doesn't exist in this install.
    for standalone_only in ("choosing-review-lenses", "grounding-review-in-tool-output",
                             "synthesizing-review-findings", "atlas-review-pr",
                             "atlas-code-review"):
        assert standalone_only not in context


def test_collapsed_log_hook_activates_under_its_own_plugin_root(tmp_path):
    # End-to-end: CLAUDE_PLUGIN_ROOT pointed at collapsed/ (as the real plugin
    # runtime sets it for a code-quality-atlas-collapsed install) must resolve
    # collapsed/hooks/lib/feedback-tier.sh, not the standalone copy.
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "collapsed")}
    _run(COLLAPSED_HOOKS_DIR / "log-skill-invocation.sh", tmp_path, _SKILL_INPUT, env_extra=env)
    assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_collapsed_retro_hook_activates_under_its_own_plugin_root(tmp_path):
    # dees-bot round-1 nit on PR #320: queue-session-retro.sh resolves its lib
    # via the identical CLAUDE_PLUGIN_ROOT pattern as log-skill-invocation.sh
    # above but only had a byte-identity check, not an equivalent end-to-end
    # activation test — a future edit that broke path resolution specifically
    # in this script would slip through undetected.
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "collapsed")}
    _run(COLLAPSED_HOOKS_DIR / "queue-session-retro.sh", tmp_path, _SESSION_END_INPUT, env_extra=env)
    assert (_learnings_dir(tmp_path) / "pending-retro.jsonl").exists()


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
        capture_output=True, text=True, timeout=10, env=env, check=False,
    )
    assert result.returncode == 0
    assert not _learnings_dir(tmp_path).exists()


# --- #310: route.sh was the one hook with real content (the SessionStart
# steering message) that no test ever executed — only that hooks.json
# *declares* the SessionStart key (test_hooks_registered_in_hooks_json
# below). A future edit to the heredoc (a stray quote, a missing key) would
# ship with CI green, since shellcheck only checks shell syntax, not the
# emitted JSON.

def test_route_hook_emits_valid_session_start_json_and_names_standalone_entrypoints():
    result = subprocess.run(
        ["bash", str(ROUTE_HOOK)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert isinstance(context, str) and context
    # The standalone plugin's full surface (44 skills + router + commands/),
    # distinct from the collapsed plugin's 4 entrypoints covered by
    # test_collapsed_route_hook_names_collapsed_entrypoints_not_standalone_surface.
    for surface in ("atlas-review-pr", "atlas-code-review", "choosing-review-lenses",
                    "grounding-review-in-tool-output", "synthesizing-review-findings"):
        assert surface in context


def test_hooks_registered_in_hooks_json():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())
    post_tool_use = hooks["hooks"]["PostToolUse"]
    assert any(h["matcher"] == "Skill" for h in post_tool_use)
    assert "SessionEnd" in hooks["hooks"]
    assert "SessionStart" in hooks["hooks"]   # the pre-existing router hook survives
