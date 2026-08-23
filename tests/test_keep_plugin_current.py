# SPDX-License-Identifier: MIT
# tests/test_keep_plugin_current.py
"""Regression tests for #310: tooling/keep-plugin-current.sh had no test
file, unlike every other script in tooling/ with real branching logic
(arg parsing, plugin@marketplace split-and-validate, a jq-driven walk over
every project scope, per-scope failure tracking that must not `set -e`-
abort). Covers arg parsing, the missing-claude/missing-jq failure paths,
and the per-scope update walk (including a failing scope not aborting the
rest)."""
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tooling" / "keep-plugin-current.sh"

DEFAULT_PLUGIN = "code-quality-atlas@code-quality-atlas"


def _run(args, env, timeout=10):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=timeout, env=env, check=False,
    )


def _minimal_path_env(tmp_path, include=("bash", "jq", "awk", "cat", "cd", "sh")):
    """A PATH containing only the named real coreutils, symlinked into a
    fresh directory -- so a command's absence (e.g. no `claude`) is genuine,
    not just shadowed by a fuller ambient PATH."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in include:
        found = shutil.which(tool)
        if found:
            (fake_bin / tool).symlink_to(found)
    return str(fake_bin)


def _fake_claude(tmp_path, fake_bin_dir, log_path):
    """A stand-in `claude` CLI that records every invocation (cwd + args) to
    log_path, and fails only when run from a project directory containing a
    `.should_fail` marker file -- so tests can control which scope fails
    without needing the real `claude` binary or network access."""
    script = fake_bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$PWD|$*" >> "{log_path}"\n'
        '[ -f ".should_fail" ] && exit 1\n'
        "exit 0\n"
    )
    script.chmod(0o755)


def _read_log(log_path):
    if not log_path.exists():
        return []
    return [line for line in log_path.read_text().splitlines() if line]


def test_help_prints_header_and_exits_0_without_claude_or_jq(tmp_path):
    # --help must work even before check_requirements ever runs, since a
    # user checking usage shouldn't need claude/jq installed first.
    env = {"PATH": _minimal_path_env(tmp_path, include=("bash", "awk", "cat")),
           "HOME": str(tmp_path)}
    result = _run(["--help"], env)
    assert result.returncode == 0
    assert "keep-plugin-current.sh" in result.stdout
    assert "--user-only" in result.stdout


def test_unknown_option_fails_with_exit_2(tmp_path):
    env = {"PATH": _minimal_path_env(tmp_path), "HOME": str(tmp_path)}
    result = _run(["--bogus"], env)
    assert result.returncode == 2
    assert "unknown option: --bogus" in result.stderr


def test_plugin_arg_missing_marketplace_fails_with_exit_2(tmp_path):
    env = {"PATH": _minimal_path_env(tmp_path), "HOME": str(tmp_path)}
    result = _run(["just-a-plugin-name"], env)
    assert result.returncode == 2
    assert "expected <plugin@marketplace>, got: just-a-plugin-name" in result.stderr


def test_missing_claude_binary_exits_1(tmp_path):
    # jq present, claude absent -- the exact "operator hasn't installed the
    # CLI yet" case check_requirements exists to catch.
    env = {"PATH": _minimal_path_env(tmp_path), "HOME": str(tmp_path)}
    result = _run([], env)
    assert result.returncode == 1
    assert "required command not found: claude" in result.stderr


def test_missing_jq_exits_1(tmp_path):
    fake_bin_dir = Path(_minimal_path_env(tmp_path, include=("bash", "cat", "cd", "sh")))
    log_path = tmp_path / "claude.log"
    _fake_claude(tmp_path, fake_bin_dir, log_path)
    env = {"PATH": str(fake_bin_dir), "HOME": str(tmp_path)}
    result = _run([], env)
    assert result.returncode == 1
    assert "required command not found: jq" in result.stderr
    # Must fail before ever invoking claude.
    assert _read_log(log_path) == []


def test_user_only_skips_project_scope_and_uses_default_plugin(tmp_path):
    fake_bin_dir = Path(_minimal_path_env(tmp_path))
    log_path = tmp_path / "claude.log"
    _fake_claude(tmp_path, fake_bin_dir, log_path)

    claude_config_dir = tmp_path / "dot-claude"
    (claude_config_dir / "plugins").mkdir(parents=True)
    proj = tmp_path / "some-project"
    proj.mkdir()
    (claude_config_dir / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "plugins": {DEFAULT_PLUGIN: [
            {"scope": "project", "projectPath": str(proj)},
        ]}
    }))

    env = {"PATH": str(fake_bin_dir), "HOME": str(tmp_path),
           "CLAUDE_CONFIG_DIR": str(claude_config_dir)}
    result = _run(["--user-only"], env)

    assert result.returncode == 0, result.stderr
    calls = _read_log(log_path)
    assert len(calls) == 2  # marketplace update + user-scope update, no project scope
    assert any(f"marketplace update {DEFAULT_PLUGIN.split('@')[1]}" in c for c in calls)
    assert any("--scope user" in c for c in calls)
    assert not any("--scope project" in c for c in calls)


def test_walks_every_project_scope_from_installed_plugins_json(tmp_path):
    fake_bin_dir = Path(_minimal_path_env(tmp_path))
    log_path = tmp_path / "claude.log"
    _fake_claude(tmp_path, fake_bin_dir, log_path)

    claude_config_dir = tmp_path / "dot-claude"
    (claude_config_dir / "plugins").mkdir(parents=True)
    proj_a = tmp_path / "proj-a"
    proj_a.mkdir()
    proj_b = tmp_path / "proj-b"
    proj_b.mkdir()
    missing_proj = tmp_path / "does-not-exist"
    (claude_config_dir / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "plugins": {DEFAULT_PLUGIN: [
            {"scope": "project", "projectPath": str(proj_a)},
            {"scope": "project", "projectPath": str(proj_b)},
            {"scope": "project", "projectPath": str(missing_proj)},
            {"scope": "user"},  # not a project scope -- must be ignored here
        ]}
    }))

    env = {"PATH": str(fake_bin_dir), "HOME": str(tmp_path),
           "CLAUDE_CONFIG_DIR": str(claude_config_dir)}
    result = _run([], env)

    assert result.returncode == 0, result.stderr
    calls = _read_log(log_path)
    project_calls = [c for c in calls if "--scope project" in c]
    assert len(project_calls) == 2
    assert any(c.startswith(f"{proj_a}|") for c in project_calls)
    assert any(c.startswith(f"{proj_b}|") for c in project_calls)
    assert f"skipped (project path missing): {missing_proj}" in result.stderr


def test_one_failing_project_scope_does_not_abort_remaining_updates(tmp_path):
    fake_bin_dir = Path(_minimal_path_env(tmp_path))
    log_path = tmp_path / "claude.log"
    _fake_claude(tmp_path, fake_bin_dir, log_path)

    claude_config_dir = tmp_path / "dot-claude"
    (claude_config_dir / "plugins").mkdir(parents=True)
    failing_proj = tmp_path / "failing-proj"
    failing_proj.mkdir()
    (failing_proj / ".should_fail").touch()
    ok_proj = tmp_path / "ok-proj"
    ok_proj.mkdir()
    (claude_config_dir / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "plugins": {DEFAULT_PLUGIN: [
            {"scope": "project", "projectPath": str(failing_proj)},
            {"scope": "project", "projectPath": str(ok_proj)},
        ]}
    }))

    env = {"PATH": str(fake_bin_dir), "HOME": str(tmp_path),
           "CLAUDE_CONFIG_DIR": str(claude_config_dir)}
    result = _run([], env)

    # set -u only; the script deliberately avoids set -e so one failing
    # scope must not stop the loop -- both scopes get attempted.
    calls = _read_log(log_path)
    project_calls = [c for c in calls if "--scope project" in c]
    assert len(project_calls) == 2
    assert any(c.startswith(f"{ok_proj}|") for c in project_calls)
    # The overall run reports failure so an operator doesn't think every
    # scope is current when one genuinely isn't.
    assert result.returncode == 1
    assert "One or more updates FAILED" in result.stderr


def test_missing_installed_plugins_json_is_tolerated(tmp_path):
    # No project scopes recorded anywhere yet (e.g. a fresh machine) --
    # marketplace + user-scope updates must still succeed rather than the
    # script erroring out on a missing file.
    fake_bin_dir = Path(_minimal_path_env(tmp_path))
    log_path = tmp_path / "claude.log"
    _fake_claude(tmp_path, fake_bin_dir, log_path)

    claude_config_dir = tmp_path / "dot-claude"
    claude_config_dir.mkdir()

    env = {"PATH": str(fake_bin_dir), "HOME": str(tmp_path),
           "CLAUDE_CONFIG_DIR": str(claude_config_dir)}
    result = _run([], env)

    assert result.returncode == 0, result.stderr
    assert "Done." in result.stdout


def test_explicit_plugin_argument_overrides_default(tmp_path):
    fake_bin_dir = Path(_minimal_path_env(tmp_path))
    log_path = tmp_path / "claude.log"
    _fake_claude(tmp_path, fake_bin_dir, log_path)

    claude_config_dir = tmp_path / "dot-claude"
    claude_config_dir.mkdir()

    env = {"PATH": str(fake_bin_dir), "HOME": str(tmp_path),
           "CLAUDE_CONFIG_DIR": str(claude_config_dir)}
    result = _run(["some-other-plugin@some-other-marketplace", "--user-only"], env)

    assert result.returncode == 0, result.stderr
    calls = _read_log(log_path)
    assert any("some-other-plugin@some-other-marketplace" in c for c in calls)
    assert not any(DEFAULT_PLUGIN in c for c in calls)
