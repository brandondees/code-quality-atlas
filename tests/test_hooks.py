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
TRACK_HOOK = REPO_ROOT / "hooks" / "lens-coverage" / "track-lens-reads.sh"
GATE_HOOK = REPO_ROOT / "hooks" / "lens-coverage" / "gate-lens-coverage.sh"

_SKILL_INPUT = json.dumps(
    {
        "session_id": "s1",
        "hook_event_name": "PostToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill": "checking-restraint"},
    }
)
_SESSION_END_INPUT = json.dumps(
    {
        "session_id": "s1",
        "hook_event_name": "SessionEnd",
        "transcript_path": "/tmp/some-transcript.jsonl",
        "reason": "clear",
    }
)

# Every external tool a hook script under test might shell out to.
_COMMON_TOOLS = (
    "bash",
    "sh",
    "cat",
    "mkdir",
    "printf",
    "date",
    "git",
    "grep",
    "sed",
    "awk",
    "dirname",
    "jq",
    "wc",
    "tr",
    "cut",
    "sha256sum",
    "shasum",
)


def _resolved_path() -> str:
    """A PATH built from `shutil.which` for the tools above, not a hardcoded
    FHS-shaped guess (`/usr/bin:/bin:/usr/local/bin`). A fixed guess silently
    makes a genuinely-installed tool invisible to the subprocess on any
    non-FHS system (Homebrew, Nix, ...) — and worse, a test meant to exercise
    a hook's *own* fallback logic (e.g. an invalid feedback tier) would then
    pass for the wrong reason: jq being merely unreachable via the hardcoded
    PATH trips the hook's *own* "no jq" no-op branch instead of the logic
    actually under test (#390)."""
    seen: list[str] = []
    for tool in _COMMON_TOOLS:
        found = shutil.which(tool)
        if found:
            directory = str(Path(found).parent)
            if directory not in seen:
                seen.append(directory)
    return ":".join(seen) if seen else "/usr/bin:/bin:/usr/local/bin"


def _run(hook, cwd, stdin, env_extra=None):
    env = {"PATH": _resolved_path(), "HOME": str(cwd)}
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["bash", str(hook)],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=False,
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
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[-1])
    assert record["session_id"] == "s1"
    assert record["tool_name"] == "Skill"
    assert record["plugin_sha"]  # this repo is a git checkout; resolvable
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
    skill_input = json.dumps(
        {
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Skill",
            "tool_input": {"skill": "café ☂"},
        }
    )
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, skill_input, env_extra=env)
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    record = json.loads(log.read_text().strip().splitlines()[-1])
    # jq's compact output keeps raw UTF-8 (no \uXXXX escaping), so the
    # expected serialization must be built the same way to match what the
    # hook actually hashes/measures.
    compact = json.dumps({"skill": "café ☂"}, separators=(",", ":"), ensure_ascii=False)
    assert len(compact.encode("utf-8")) != len(
        compact
    )  # the fixture must actually be multi-byte
    assert record["tool_input_len"] == len(compact.encode("utf-8"))
    assert (
        record["tool_input_sha256"]
        == hashlib.sha256(compact.encode("utf-8")).hexdigest()
    )


def test_env_override_hashes_with_sorted_keys_so_key_order_does_not_matter(tmp_path):
    # Regression for CodeRabbit's PR #397 finding: `jq -c` preserves the
    # original key order, so two logically-equivalent tool_input payloads
    # with differently ordered keys would hash differently — undermining
    # tool_input_sha256's use for future repeat-input analysis (§3.4). The
    # hook must serialize with sorted keys (jq -cS) before hashing.
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    ordered_a = json.dumps(
        {
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Skill",
            "tool_input": {"a": 1, "b": 2},
        }
    )
    ordered_b = json.dumps(
        {
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Skill",
            "tool_input": {"b": 2, "a": 1},
        }
    )
    _run(LOG_HOOK, tmp_path, ordered_a, env_extra=env)
    _run(LOG_HOOK, tmp_path, ordered_b, env_extra=env)
    lines = (
        (_learnings_dir(tmp_path) / "invocations.jsonl")
        .read_text()
        .strip()
        .splitlines()
    )
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
    skill_input = json.dumps(
        {
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Skill",
            "tool_input": False,
        }
    )
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, skill_input, env_extra=env)
    record = json.loads(
        (_learnings_dir(tmp_path) / "invocations.jsonl")
        .read_text()
        .strip()
        .splitlines()[-1]
    )
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
    for tool in (
        "bash",
        "cat",
        "mkdir",
        "printf",
        "date",
        "git",
        "grep",
        "sed",
        "awk",
        "dirname",
        "cd",
        "sh",
        "jq",
        "wc",
        "tr",
        "cut",
    ):
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)
    assert not (fake_bin / "sha256sum").exists()
    assert not (fake_bin / "shasum").exists()
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "PATH": str(fake_bin),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(LOG_HOOK)],
        cwd=str(tmp_path),
        input=_SKILL_INPUT,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    log = _learnings_dir(tmp_path) / "invocations.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[-1])
    compact = json.dumps({"skill": "checking-restraint"}, separators=(",", ":"))
    assert record["tool_input_len"] == len(compact.encode("utf-8"))
    assert record["tool_input_sha256"] is None


def test_session_end_queues_retro_under_env_override(tmp_path):
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
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
    session_end_input = json.dumps(
        {
            "session_id": "s1",
            "hook_event_name": "SessionEnd",
            "transcript_path": r"C:\Users\alice\.claude\projects\foo\abc-123.jsonl",
            "reason": "clear",
        }
    )
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(RETRO_HOOK, tmp_path, session_end_input, env_extra=env)
    queue = _learnings_dir(tmp_path) / "pending-retro.jsonl"
    record = json.loads(queue.read_text().strip().splitlines()[-1])
    assert "transcript_path" not in record
    assert record["transcript_basename"] == "abc-123.jsonl"


def test_session_end_empty_transcript_path_yields_null_basename_not_empty_string(
    tmp_path,
):
    # Regression for the atlas reviewer's PR #397 finding: jq's `if` only
    # treats null/false as falsy, so `if .transcript_path then ...` alone
    # would turn an (unlikely but possible) empty-string transcript_path
    # into transcript_basename: "" instead of null, diverging from the
    # documented "basename or null" contract.
    session_end_input = json.dumps(
        {
            "session_id": "s1",
            "hook_event_name": "SessionEnd",
            "transcript_path": "",
            "reason": "clear",
        }
    )
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(RETRO_HOOK, tmp_path, session_end_input, env_extra=env)
    queue = _learnings_dir(tmp_path) / "pending-retro.jsonl"
    record = json.loads(queue.read_text().strip().splitlines()[-1])
    assert record["transcript_basename"] is None


def test_invalid_env_tier_falls_back_to_off(tmp_path):
    env = {"CODE_QUALITY_ATLAS_FEEDBACK_TIER": "yolo"}
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    assert not _learnings_dir(tmp_path).exists()


def test_invalid_env_tier_is_terminal_even_with_a_ratified_preferences_line(tmp_path):
    # Regression (#365): a *set* but invalid env override previously fell
    # through to check .code-quality-atlas/preferences.md instead of
    # resolving to "off" outright — so CODE_QUALITY_ATLAS_FEEDBACK_TIER=nope
    # with a ratified `feedback: local` still activated logging. The prior
    # test above never caught this: with no preferences.md at all, an
    # invalid env value and a correctly-terminal one produce the same
    # observable result (off), by coincidence rather than by testing the
    # actual precedence rule.
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "## Feedback & learnings\n\nfeedback: local\ndecided: 2026-07-18, @alice\n"
    )
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "nope",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    assert not _learnings_dir(tmp_path).exists()


def test_symlinked_log_destination_is_refused(tmp_path):
    # Regression (#365): a cloned repo with `feedback: local` ratified and
    # .code-quality-atlas/learnings/invocations.jsonl committed as a symlink
    # must not have this hook write through it — the symlink can point
    # anywhere, including outside the repo entirely. Covers the actual
    # attack shape: the symlink's target need not exist yet ([ -e ] on a
    # symlink follows it and reports on the target, so a naive existence
    # check misses a dangling symlink like this one).
    learnings_dir = _learnings_dir(tmp_path)
    learnings_dir.mkdir(parents=True)
    outside = tmp_path.parent / "outside-the-repo.jsonl"
    (learnings_dir / "invocations.jsonl").symlink_to(outside)
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    assert not outside.exists()
    # The symlink itself must be left alone too, not replaced or deleted.
    assert (learnings_dir / "invocations.jsonl").is_symlink()


def test_feedback_tier_resolves_preferences_against_claude_project_dir(tmp_path):
    # Regression (#365): the hooks previously resolved
    # .code-quality-atlas/preferences.md (and the log destination) relative
    # to CWD only, ignoring CLAUDE_PROJECT_DIR — so a ratified opt-in
    # silently resolved to "off" whenever the hook ran from a subdirectory
    # of the project, matching the CLAUDE_PROJECT_DIR-over-cwd precedent
    # already established for lens-coverage/track-lens-reads.sh.
    project_dir = tmp_path / "project"
    other_cwd = tmp_path / "elsewhere"
    (project_dir / ".code-quality-atlas").mkdir(parents=True)
    other_cwd.mkdir()
    (project_dir / ".code-quality-atlas" / "preferences.md").write_text(
        "feedback: local\n"
    )
    env = {"CLAUDE_PROJECT_DIR": str(project_dir), "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    _run(LOG_HOOK, other_cwd, _SKILL_INPUT, env_extra=env)
    assert (
        project_dir / ".code-quality-atlas" / "learnings" / "invocations.jsonl"
    ).exists()
    assert not (other_cwd / ".code-quality-atlas").exists()


def test_commented_out_template_example_does_not_activate(tmp_path):
    # The shipped preferences template ships every example, including a
    # feedback tier, commented out inside an HTML comment block; a repo that
    # copies it verbatim (never ratifying the line) must stay opted out.
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "## Feedback & learnings\n\n<!--\nfeedback: local\n-->\n"
    )
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
        "decided: 2026-07-18, @alice\n"
    )
    _run(
        LOG_HOOK,
        tmp_path,
        _SKILL_INPUT,
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)},
    )
    assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_ratified_preferences_line_activates_logging(tmp_path):
    # An uncommented `feedback: local` line under the repo's own preferences
    # overlay must enable logging without any env var.
    prefs_dir = tmp_path / ".code-quality-atlas"
    prefs_dir.mkdir()
    (prefs_dir / "preferences.md").write_text(
        "## Feedback & learnings\n\nfeedback: local\ndecided: 2026-07-18, @alice\n"
    )
    _run(
        LOG_HOOK,
        tmp_path,
        _SKILL_INPUT,
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)},
    )
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
        "reason: local-only telemetry is safe by construction\n"
    )
    _run(
        LOG_HOOK,
        tmp_path,
        _SKILL_INPUT,
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)},
    )
    assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_malformed_stdin_json_is_a_clean_no_op(tmp_path):
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
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
    # log-skill-invocation.sh, queue-session-retro.sh, lib/feedback-tier.sh,
    # and the lens-coverage/ pair carry no skill-name-specific content (unlike
    # route.sh), so they must stay byte-identical between the two plugin forms.
    for rel in (
        "log-skill-invocation.sh",
        "queue-session-retro.sh",
        "lib/feedback-tier.sh",
        "lens-coverage/track-lens-reads.sh",
        "lens-coverage/gate-lens-coverage.sh",
    ):
        standalone = (REPO_ROOT / "hooks" / rel).read_text(encoding="utf-8")
        collapsed = (COLLAPSED_HOOKS_DIR / rel).read_text(encoding="utf-8")
        assert collapsed == standalone, (
            f"collapsed/hooks/{rel} has drifted from hooks/{rel}"
        )


def test_collapsed_route_hook_names_collapsed_entrypoints_not_standalone_surface():
    result = subprocess.run(
        ["bash", str(COLLAPSED_HOOKS_DIR / "route.sh")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    for entrypoint in (
        "reviewing-a-change",
        "auditing-a-repository",
        "reviewing-a-decision",
        "reviewing-an-artifact",
    ):
        assert entrypoint in context
    # Standalone-only surface (not shipped under collapsed/'s own plugin root)
    # must not be named — it doesn't exist in this install.
    for standalone_only in (
        "choosing-review-lenses",
        "grounding-review-in-tool-output",
        "synthesizing-review-findings",
        "atlas-review-pr",
        "atlas-code-review",
    ):
        assert standalone_only not in context


def test_collapsed_log_hook_activates_under_its_own_plugin_root(tmp_path):
    # End-to-end: CLAUDE_PLUGIN_ROOT pointed at collapsed/ (as the real plugin
    # runtime sets it for a code-quality-atlas-collapsed install) must resolve
    # collapsed/hooks/lib/feedback-tier.sh, not the standalone copy.
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "collapsed"),
    }
    _run(
        COLLAPSED_HOOKS_DIR / "log-skill-invocation.sh",
        tmp_path,
        _SKILL_INPUT,
        env_extra=env,
    )
    assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_collapsed_retro_hook_activates_under_its_own_plugin_root(tmp_path):
    # dees-bot round-1 nit on PR #320: queue-session-retro.sh resolves its lib
    # via the identical CLAUDE_PLUGIN_ROOT pattern as log-skill-invocation.sh
    # above but only had a byte-identity check, not an equivalent end-to-end
    # activation test — a future edit that broke path resolution specifically
    # in this script would slip through undetected.
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "collapsed"),
    }
    _run(
        COLLAPSED_HOOKS_DIR / "queue-session-retro.sh",
        tmp_path,
        _SESSION_END_INPUT,
        env_extra=env,
    )
    assert (_learnings_dir(tmp_path) / "pending-retro.jsonl").exists()


def test_missing_jq_degrades_to_no_op(tmp_path):
    # A minimal PATH with every common coreutil except jq, so `command -v jq`
    # genuinely fails rather than skipping a real system jq via a fragile
    # env trick.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for tool in (
        "bash",
        "cat",
        "mkdir",
        "printf",
        "date",
        "git",
        "grep",
        "sed",
        "awk",
        "dirname",
        "cd",
        "sh",
    ):
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "PATH": str(fake_bin),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(LOG_HOOK)],
        cwd=str(tmp_path),
        input=_SKILL_INPUT,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert not _learnings_dir(tmp_path).exists()


def test_missing_lib_degrades_to_no_op_instead_of_a_failed_source(tmp_path):
    # Regression (#365): CLAUDE_PLUGIN_ROOT pointing at a directory with no
    # hooks/lib/feedback-tier.sh previously still reached `source "$_lib"`,
    # which fails loudly under `set -u` with no functions defined afterward
    # — the script happened to still exit 0 overall (the empty
    # `feedback_tier` call falls through the case statement's `*` branch),
    # but only by accident, with a raw "No such file or directory" on
    # stderr. An explicit `[ -f "$_lib" ] || exit 0` makes this a clean,
    # intentional no-op instead.
    fake_plugin_root = tmp_path / "fake-plugin-root"
    fake_plugin_root.mkdir()
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(fake_plugin_root),
    }
    result = subprocess.run(
        ["bash", str(LOG_HOOK)],
        cwd=str(tmp_path),
        input=_SKILL_INPUT,
        capture_output=True,
        text=True,
        timeout=10,
        env={**env, "PATH": _resolved_path(), "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert not _learnings_dir(tmp_path).exists()


def test_draft_and_auto_tiers_log_like_local_with_a_stderr_note(tmp_path):
    # Regression (#365): `draft`/`auto` are accepted and silently treated
    # exactly like `local` (stages 2+ are unbuilt) — an operator who
    # deliberately opted into one of them should see a note saying so on
    # stderr, not silence indistinguishable from "local" was requested.
    for tier in ("draft", "auto"):
        env = {
            "CODE_QUALITY_ATLAS_FEEDBACK_TIER": tier,
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        }
        result = subprocess.run(
            ["bash", str(LOG_HOOK)],
            cwd=str(tmp_path),
            input=_SKILL_INPUT,
            capture_output=True,
            text=True,
            timeout=10,
            env={**env, "PATH": _resolved_path(), "HOME": str(tmp_path)},
            check=False,
        )
        assert result.returncode == 0
        assert tier in result.stderr
        assert (_learnings_dir(tmp_path) / "invocations.jsonl").exists()


def test_log_destination_size_cap_stops_further_appends(tmp_path):
    # Regression (#365): nothing rotates or caps the log file's growth —
    # this hook must at least refuse to keep appending to one that has
    # already grown past a size cap rather than let it grow unbounded.
    learnings_dir = _learnings_dir(tmp_path)
    learnings_dir.mkdir(parents=True)
    log = learnings_dir / "invocations.jsonl"
    log.write_bytes(b"x" * (6 * 1024 * 1024))
    size_before = log.stat().st_size
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    assert log.stat().st_size == size_before


def test_append_falls_through_to_unlocked_write_when_lock_is_contended(tmp_path):
    # Regression (dees-bot review, PR #413): the sixth named fix (writer
    # serialization via a bounded mkdir-based lock) had no test exercising
    # the lock itself — pre-creating <target>.lock forces the bounded-retry-
    # then-degrade branch, and the line must still land (not silently drop)
    # once the retries are exhausted, since this hook must never block the
    # calling tool call indefinitely.
    learnings_dir = _learnings_dir(tmp_path)
    learnings_dir.mkdir(parents=True)
    (learnings_dir / "invocations.jsonl.lock").mkdir()
    env = {
        "CODE_QUALITY_ATLAS_FEEDBACK_TIER": "local",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
    }
    _run(LOG_HOOK, tmp_path, _SKILL_INPUT, env_extra=env)
    log = learnings_dir / "invocations.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[-1])
    assert record["session_id"] == "s1"
    # The pre-existing lock (held by someone else, in this scenario) must be
    # left alone — this hook only ever removes a lock directory it created.
    assert (learnings_dir / "invocations.jsonl.lock").is_dir()


# --- #310: route.sh was the one hook with real content (the SessionStart
# steering message) that no test ever executed — only that hooks.json
# *declares* the SessionStart key (test_hooks_registered_in_hooks_json
# below). A future edit to the heredoc (a stray quote, a missing key) would
# ship with CI green, since shellcheck only checks shell syntax, not the
# emitted JSON.


def test_route_hook_emits_valid_session_start_json_and_names_standalone_entrypoints():
    result = subprocess.run(
        ["bash", str(ROUTE_HOOK)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert isinstance(context, str) and context
    # The standalone plugin's full surface (44 skills + router + commands/),
    # distinct from the collapsed plugin's 4 entrypoints covered by
    # test_collapsed_route_hook_names_collapsed_entrypoints_not_standalone_surface.
    for surface in (
        "atlas-review-pr",
        "atlas-code-review",
        "choosing-review-lenses",
        "grounding-review-in-tool-output",
        "synthesizing-review-findings",
    ):
        assert surface in context


def test_hooks_registered_in_hooks_json():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())
    post_tool_use = hooks["hooks"]["PostToolUse"]
    assert any(h["matcher"] == "Skill" for h in post_tool_use)
    assert "SessionEnd" in hooks["hooks"]
    assert "SessionStart" in hooks["hooks"]  # the pre-existing router hook survives


# --- #357/Q23 lens-coverage hooks: track-lens-reads.sh (PostToolUse Read|Skill)
# records which lens bundles were actually loaded; gate-lens-coverage.sh
# (PreToolUse) blocks a review post that attributes a finding to one that
# wasn't. Round-1 review on PR #398 found two Major bugs neither had a
# regression test for — the tracker never matched the Skill tool at all (this
# repo's own primary resolution path), and (claimed, not reproduced against
# the pushed fix — kept here as a regression lock either way) the gate's
# opt-in check could mis-parse a template-shaped preferences.md line. These
# tests cover both, plus the core pass/block behavior.


def _lens_coverage_hooks_registered_for(matcher, hooks_json_path):
    hooks = json.loads(hooks_json_path.read_text())
    return [h for h in hooks["hooks"].get("PostToolUse", []) if h["matcher"] == matcher]


def test_track_lens_reads_registered_under_both_read_and_skill_matchers():
    # Regression for the Major finding: a script wired under only "Read"
    # never fires for a lens loaded via the Skill tool at all — this asserts
    # the wiring itself, independent of the script's own tool_name branching
    # tested below.
    for matcher in ("Read", "Skill"):
        entries = _lens_coverage_hooks_registered_for(
            matcher, REPO_ROOT / "hooks" / "hooks.json"
        )
        assert any(
            "lens-coverage/track-lens-reads.sh" in h["command"]
            for entry in entries
            for h in entry["hooks"]
        ), f"track-lens-reads.sh not registered under PostToolUse matcher {matcher!r}"


def _lens_coverage_state(cwd, session_id="s1"):
    return cwd / ".claude" / ".atlas-lens-coverage" / f"{session_id}.txt"


def test_track_records_a_skill_tool_invocation_of_a_lens(tmp_path):
    # The Major finding itself: a lens invoked via Skill (tool_input.skill),
    # not Read, must still be recorded.
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Skill",
            "tool_input": {"skill": "hunting-silent-failures", "args": ""},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert _lens_coverage_state(tmp_path).read_text().splitlines() == [
        "hunting-silent-failures"
    ]


def test_track_records_a_standalone_skill_md_read(tmp_path):
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "skills/checking-restraint/SKILL.md"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert _lens_coverage_state(tmp_path).read_text().splitlines() == [
        "checking-restraint"
    ]


def test_track_records_a_collapsed_entrypoint_lens_body_read(tmp_path):
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {
                "file_path": "collapsed/skills/reviewing-a-change/reference/lenses/checking-restraint/body.md"
            },
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert _lens_coverage_state(tmp_path).read_text().splitlines() == [
        "checking-restraint"
    ]


def test_track_ignores_an_unrelated_read(tmp_path):
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert not _lens_coverage_state(tmp_path).exists()


def test_track_dedupes_repeat_reads_of_the_same_lens(tmp_path):
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Skill",
            "tool_input": {"skill": "hunting-silent-failures"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    _run(TRACK_HOOK, tmp_path, stdin)
    assert _lens_coverage_state(tmp_path).read_text().splitlines() == [
        "hunting-silent-failures"
    ]


def test_track_rejects_a_path_traversal_shaped_session_id(tmp_path):
    # Copilot review, PR #398: session_id is interpolated straight into a
    # filesystem path -- confirm a hostile-shaped value is rejected rather
    # than escaping the intended state directory.
    stdin = json.dumps(
        {
            "session_id": "../../../../tmp/evil",
            "tool_name": "Skill",
            "tool_input": {"skill": "hunting-silent-failures"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert not (tmp_path / ".claude" / ".atlas-lens-coverage").exists()


def _run_gate(cwd, stdin, env_extra=None):
    env = {"PATH": _resolved_path(), "HOME": str(cwd)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(GATE_HOOK)],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=False,
    )


def _gate_body(finding_lens):
    return json.dumps(
        {
            "session_id": "s1",
            "tool_input": {"body": f"Major\n- x.py:1 ({finding_lens})"},
        }
    )


def _enable_gate(cwd, prefs_text="lens-coverage-gate: on\n"):
    prefs_dir = cwd / ".code-quality-atlas"
    prefs_dir.mkdir(exist_ok=True)
    (prefs_dir / "preferences.md").write_text(prefs_text)


def _make_known_lens(cwd, name):
    lens_dir = cwd / "skills" / name
    lens_dir.mkdir(parents=True, exist_ok=True)
    (lens_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n")


def _record_prior_read(cwd, lens, session_id="s1"):
    # Writes the state file directly rather than via track-lens-reads.sh --
    # these gate tests exercise gate-lens-coverage.sh in isolation (the
    # tracker/gate integration itself is covered separately by
    # test_gate_passes_when_the_cited_lens_was_actually_read). A state file
    # must exist with *some* content, or the gate's own state_file-missing
    # check (tested by test_gate_fails_open_when_no_state_file_exists_yet_
    # for_this_session) would fail these tests open for the wrong reason
    # before ever reaching the logic each of these actually means to test.
    state = _lens_coverage_state(cwd, session_id)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(lens + "\n")


def test_gate_off_by_default_even_with_a_missing_lens_citation(tmp_path):
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    _record_prior_read(tmp_path, "some-other-lens")
    result = _run_gate(tmp_path, _gate_body("tracing-correctness-and-invariants"))
    assert result.returncode == 0


def test_gate_commented_out_template_example_stays_inert(tmp_path):
    # Same shape as the shipped preferences template: the whole example lives
    # inside an HTML comment block. A gate line in there must never activate.
    _enable_gate(tmp_path, "<!--\nlens-coverage-gate: on\n-->\n")
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    _record_prior_read(tmp_path, "some-other-lens")
    result = _run_gate(tmp_path, _gate_body("tracing-correctness-and-invariants"))
    assert result.returncode == 0


def test_gate_ratified_line_blocks_a_missing_lens_citation(tmp_path):
    _enable_gate(tmp_path)
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    _record_prior_read(tmp_path, "some-other-lens")
    result = _run_gate(tmp_path, _gate_body("tracing-correctness-and-invariants"))
    assert result.returncode == 2
    assert "tracing-correctness-and-invariants" in result.stderr


def test_gate_template_shaped_trailing_comment_still_activates(tmp_path):
    # Regression lock for the round-1 review's claimed (not reproduced
    # against the pushed fix, but worth locking in either way) false
    # negative: the exact multi-line trailing-comment shape
    # templates/preferences-template.md ships for every ratified key.
    _enable_gate(
        tmp_path,
        "lens-coverage-gate: on      # off (default) | on (blocks a review\n"
        "#                     post that attributes a finding to an unread\n"
        "#                     lens)\n"
        "decided: 2026-01-01, @alice\n",
    )
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    _record_prior_read(tmp_path, "some-other-lens")
    result = _run_gate(tmp_path, _gate_body("tracing-correctness-and-invariants"))
    assert result.returncode == 2


def test_gate_passes_when_the_cited_lens_was_actually_read(tmp_path):
    _enable_gate(tmp_path)
    _make_known_lens(tmp_path, "hunting-silent-failures")
    _run(
        TRACK_HOOK,
        tmp_path,
        json.dumps(
            {
                "session_id": "s1",
                "tool_name": "Skill",
                "tool_input": {"skill": "hunting-silent-failures"},
            }
        ),
    )
    result = _run_gate(tmp_path, _gate_body("hunting-silent-failures"))
    assert result.returncode == 0


def test_gate_ignores_a_benign_parenthetical_that_is_not_a_known_lens(tmp_path):
    _enable_gate(tmp_path)
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    _record_prior_read(tmp_path, "some-other-lens")
    result = _run_gate(
        tmp_path,
        json.dumps(
            {
                "session_id": "s1",
                "tool_input": {
                    "body": "See the summary above (see below) for details."
                },
            }
        ),
    )
    assert result.returncode == 0


def test_gate_ignores_a_skills_directory_with_no_skill_md_marker(tmp_path):
    # Copilot review, PR #398: known_lenses must be built from the marker
    # FILE each lens shape actually carries (SKILL.md/body.md), not just the
    # containing directory -- otherwise an unrelated skills/<name>/ a
    # consumer repo happens to have (no SKILL.md at all, e.g. a non-atlas
    # skills/todo/) is misread as a "known lens," and a benign "(todo)"
    # parenthetical in review prose falsely trips the gate.
    _enable_gate(tmp_path)
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    (tmp_path / "skills" / "todo").mkdir(parents=True)
    _record_prior_read(tmp_path, "some-other-lens")
    result = _run_gate(
        tmp_path,
        json.dumps(
            {
                "session_id": "s1",
                "tool_input": {"body": "See the todo list (todo) for details."},
            }
        ),
    )
    assert result.returncode == 0


def test_gate_fails_open_when_no_state_file_exists_yet_for_this_session(tmp_path):
    # Distinct code path from test_gate_ratified_line_blocks_a_missing_lens_citation:
    # there, a state file exists (created by _make_known_lens's session having
    # tracked something) but doesn't list the cited lens, and the gate
    # correctly blocks. Here, track-lens-reads.sh has never run at all for
    # this session_id -- no state file on disk -- and the gate must fail
    # open rather than block, per its own stated design (the common case for
    # a repo where the suite isn't vendored/available locally at all).
    _enable_gate(tmp_path)
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    assert not _lens_coverage_state(tmp_path).exists()
    result = _run_gate(tmp_path, _gate_body("tracing-correctness-and-invariants"))
    assert result.returncode == 0


def test_gate_rejects_a_path_traversal_shaped_session_id(tmp_path):
    # Copilot review, PR #398: same interpolation-into-a-path pattern as the
    # tracker's own regression test above. A hostile-shaped session_id must
    # fail open (harmlessly), never touch a path outside the state directory.
    _enable_gate(tmp_path)
    _make_known_lens(tmp_path, "tracing-correctness-and-invariants")
    result = _run_gate(
        tmp_path,
        json.dumps(
            {
                "session_id": "../../../../tmp/evil",
                "tool_input": {
                    "body": "Major\n- x.py:1 (tracing-correctness-and-invariants)"
                },
            }
        ),
    )
    assert result.returncode == 0


# --- Round-4 CodeRabbit review, PR #398: a plugin-installed lens's Skill
# invocation carries a `<plugin>:` prefix, a Read path can carry a stray
# "./" segment, and neither the tracker nor the gate anchored their state
# path to the project root -- a hook invoked with a working directory other
# than the project root would silently disagree with itself about where the
# state file lives.


def test_track_strips_plugin_prefix_from_a_skill_invocation(tmp_path):
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Skill",
            "tool_input": {"skill": "code-quality-atlas:hunting-silent-failures"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert _lens_coverage_state(tmp_path).read_text().splitlines() == [
        "hunting-silent-failures"
    ]


def test_track_collapses_a_stray_dot_slash_path_segment(tmp_path):
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "skills/./checking-restraint/SKILL.md"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert _lens_coverage_state(tmp_path).read_text().splitlines() == [
        "checking-restraint"
    ]


def test_track_rejects_a_lens_value_shaped_like_an_injection_attempt(tmp_path):
    # An embedded newline in tool_input.skill could otherwise let a crafted
    # value inject an extra, fabricated "line" into the state file gate-
    # lens-coverage.sh trusts as a record of what was actually read.
    stdin = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Skill",
            "tool_input": {"skill": "evil\nfake-lens"},
        }
    )
    _run(TRACK_HOOK, tmp_path, stdin)
    assert not _lens_coverage_state(tmp_path).exists()


def test_track_and_gate_agree_on_claude_project_dir_over_cwd(tmp_path):
    # The tracker and gate must resolve the SAME state path even when
    # invoked with a working directory other than the project root -- CWD
    # is where the hook happens to run, CLAUDE_PROJECT_DIR (when set) is
    # where the project actually is.
    project_dir = tmp_path / "project"
    other_cwd = tmp_path / "elsewhere"
    project_dir.mkdir()
    other_cwd.mkdir()
    (project_dir / "skills" / "hunting-silent-failures").mkdir(parents=True)
    env = {"CLAUDE_PROJECT_DIR": str(project_dir)}

    _run(
        TRACK_HOOK,
        other_cwd,
        json.dumps(
            {
                "session_id": "s1",
                "tool_name": "Skill",
                "tool_input": {"skill": "hunting-silent-failures"},
            }
        ),
        env_extra=env,
    )

    # Landed under the project dir, not a cwd-relative .claude/ in other_cwd.
    assert (
        project_dir / ".claude" / ".atlas-lens-coverage" / "s1.txt"
    ).read_text().strip() == "hunting-silent-failures"
    assert not (other_cwd / ".claude").exists()

    _enable_gate(project_dir)
    result = _run_gate(other_cwd, _gate_body("hunting-silent-failures"), env_extra=env)
    assert result.returncode == 0
