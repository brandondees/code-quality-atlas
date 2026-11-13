# SPDX-License-Identifier: MIT
"""The webhook Fly app is a second, always-on service. The one-off fly.toml
stays without an HTTP service. These checks read the files; they do not
call Fly."""

import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

from atlas_reviewer.service import config_from_env

ROOT = Path(__file__).resolve().parents[2]
SERVICE = tomllib.loads((ROOT / "fly.service.toml").read_text(encoding="utf-8"))
ONE_OFF = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))
RUNBOOK = (ROOT / "atlas_reviewer" / "deploy-service.md").read_text(encoding="utf-8")
ENTRYPOINT = ROOT / "atlas_reviewer" / "docker-entrypoint.sh"


def test_the_service_app_stays_up_and_the_one_off_publishes_nothing():
    assert SERVICE["app"] == "atlas-reviewer-service"
    assert SERVICE["primary_region"] == "iad"
    http = SERVICE["http_service"]
    assert http["internal_port"] == 8080
    assert http["force_https"] is True
    assert http["auto_stop_machines"] == "off"
    assert http["auto_start_machines"] is False
    assert http["processes"] == ["app"]
    assert SERVICE["processes"] == {"app": "serve"}
    vm = SERVICE["vm"][0]
    assert vm["size"] == "shared-cpu-1x"
    assert vm["memory"] == "1024mb"
    assert SERVICE["env"]["ATLAS_REVIEWER_STATE_DIR"] == "/data"
    assert SERVICE["env"]["ATLAS_SERVICE_HOST"] == "0.0.0.0"
    assert "ATLAS_SERVICE_PORT" not in SERVICE["env"]
    assert http["internal_port"] == 8080
    mounts = SERVICE["mounts"]
    assert mounts["source"] == "atlas_reviewer_state"
    assert mounts["destination"] == "/data"
    assert mounts["initial_size"] == "1gb"
    assert mounts["processes"] == ["app"]
    check = SERVICE["http_service"]["checks"][0]
    assert check["path"] == "/health"
    assert check["method"] == "GET"
    assert "http_service" not in ONE_OFF
    assert "services" not in ONE_OFF
    assert ONE_OFF["app"] == "atlas-reviewer"
    assert SERVICE["kill_signal"] == "SIGINT"
    assert SERVICE["kill_timeout"] == "30s"


def _fenced(text: str) -> str:
    blocks: list[str] = []
    current: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("```"):
            if inside:
                blocks.append("\n".join(current))
                current = []
            inside = not inside
            continue
        if inside:
            current.append(line)
    return "\n".join(blocks)


def test_the_org_and_the_single_machine_flag_are_on_the_commands():
    """The org and ``--ha=false`` have to be on the fenced commands.
    Prose that names them does not count."""
    commands = _fenced(RUNBOOK)
    assert "ORG=personal" in commands.splitlines()
    assert 'flyp apps list --org "$ORG" --quiet | grep -qx "$APP" ||' in commands
    assert 'flyp apps create "$APP" --org "$ORG"' in commands
    deploys = [line.strip() for line in commands.splitlines() if "flyp deploy" in line]
    assert deploys == ['flyp deploy -c fly.service.toml --app "$APP" --ha=false']
    assert 'flyp ssh console --app "$APP" -C "tail -n 200 /data/service.jsonl"' in commands
    assert 'flyp machine restart <id> --app "$APP"' in commands
    assert "ATLAS_GITHUB_APP_SLUG=" in commands


def test_the_runbook_names_the_secret_the_org_and_the_webhook():
    flat = " ".join(RUNBOOK.split())
    for text in (
        "ATLAS_GITHUB_WEBHOOK_SECRET",
        "org `personal`",
        "Do not run `fly secrets deploy`",
        "flyp secrets import --stage --app",
        "flyp deploy -c fly.service.toml --app",
        "--ha=false",
        "/webhook",
        "Pull requests",
        "brandondees/code-quality-atlas",
        "COMMENT",
        "auto_stop_machines",
        "$6.70",
        "atlas_reviewer_state",
        "chowns that directory to uid 10001",
        "leave `app` in `fly.service.toml` unchanged",
        "deletes the app's volumes",
        "Do not `fly deploy` it for the webhook",
    ):
        assert text in flat, text


def test_serve_runs_the_service_module_and_not_the_one_off_cli(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    recorded = tmp_path / "argv"
    program = bindir / "python"
    program.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$RECORD"\n',
        encoding="utf-8",
    )
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    subprocess.run(["sh", "-n", str(ENTRYPOINT)], check=True)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["RECORD"] = str(recorded)
    subprocess.run(["sh", str(ENTRYPOINT), "serve"], check=True, env=env)
    assert recorded.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "atlas_reviewer.service",
    ]


def test_the_entrypoint_chowns_the_volume_before_dropping_root(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    recorded = tmp_path / "argv"
    chowned = tmp_path / "chown"
    dropped = tmp_path / "setpriv"

    def write(name: str, body: str) -> None:
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    write("id", "#!/bin/sh\necho 0\n")
    write("chown", '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$CHOWN"\n')
    write(
        "setpriv",
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SETPRIV\"\n"
        'shift 4\nPATH="${PATH#*:}"\nexec "$@"\n',
    )
    pybin = tmp_path / "pybin"
    pybin.mkdir()
    python = pybin / "python"
    python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$RECORD"\n', encoding="utf-8")
    python.chmod(python.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{pybin}{os.pathsep}{env.get('PATH', '')}"
    env["RECORD"] = str(recorded)
    env["CHOWN"] = str(chowned)
    env["SETPRIV"] = str(dropped)
    state = tmp_path / "data"
    env["ATLAS_REVIEWER_STATE_DIR"] = str(state)
    subprocess.run(["sh", str(ENTRYPOINT), "serve"], check=True, env=env)
    assert chowned.read_text(encoding="utf-8").splitlines() == [
        "10001:10001",
        str(state),
    ]
    assert "--reuid=10001" in dropped.read_text(encoding="utf-8")
    assert recorded.read_text(encoding="utf-8").splitlines()[:2] == [
        "-m",
        "atlas_reviewer.service",
    ]


def test_serve_exits_2_when_the_state_dir_is_not_writable(tmp_path):
    from atlas_reviewer.service import serve

    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    env = {
        "ATLAS_GITHUB_WEBHOOK_SECRET": "x" * 16,
        "ATLAS_SERVICE_PROVIDER": "offline",
        "ATLAS_REVIEWER_STATE_DIR": str(blocked),
    }
    lines: list[str] = []
    assert serve(config_from_env(env), env, log=lines.append) == 2
    assert any("not writable" in line for line in lines)


def test_the_real_module_exits_2_when_no_atlas_env_is_set():
    """Runs the real module, not a stub interpreter. Without the
    ``__main__`` guard, ``python -m atlas_reviewer.service`` exits 0 and
    never reaches the webhook-secret check."""
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("ATLAS_")
    }
    proc = subprocess.run(
        [sys.executable, "-m", "atlas_reviewer.service"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 2
    assert b"webhook secret" in proc.stderr


def test_d49_counts_every_active_job_state():
    text = (ROOT / "docs/open-questions.md").read_text(encoding="utf-8")
    start = text.index("- **D49")
    entry = text[start:].splitlines()[0]
    runbook = (ROOT / "atlas_reviewer/deploy-service.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs/plans/2026-11-12-webhook-service-mode.md").read_text(
        encoding="utf-8"
    )
    states = "(`queued`, `running`, `post_pending`, `posting`)"
    for document in (entry, runbook, plan):
        assert states in document
        assert "already queued or running" not in document
        assert "2,000 plus those superseded jobs" in document
        assert "at most the worker concurrency" in document
    assert "**Reversibility.**" in entry
    assert "entrypoint chowns" in entry


def test_the_fly_host_is_what_config_from_env_binds():
    """A hardcoded loopback would still match the TOML string and leave
    the proxy with nothing to reach."""
    assert SERVICE["env"]["ATLAS_SERVICE_HOST"] == "0.0.0.0"
    config = config_from_env(
        {
            "ATLAS_GITHUB_WEBHOOK_SECRET": "x" * 16,
            "ATLAS_SERVICE_PROVIDER": "offline",
            "ATLAS_SERVICE_HOST": "0.0.0.0",
        }
    )
    assert config.host == "0.0.0.0"
    loopback = config_from_env(
        {
            "ATLAS_GITHUB_WEBHOOK_SECRET": "x" * 16,
            "ATLAS_SERVICE_PROVIDER": "offline",
        }
    )
    assert loopback.host == "127.0.0.1"


def test_a_non_8080_port_is_refused_and_the_toml_checks_8080():
    """The Fly health check and ``internal_port`` are read from the file.
    A process told to listen elsewhere exits before it binds."""
    assert SERVICE["http_service"]["internal_port"] == 8080
    assert SERVICE["http_service"]["checks"][0]["path"] == "/health"
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("ATLAS_")
    }
    env["ATLAS_GITHUB_WEBHOOK_SECRET"] = "x" * 16
    env["ATLAS_SERVICE_PROVIDER"] = "offline"
    env["ATLAS_SERVICE_PORT"] = "9090"
    proc = subprocess.run(
        [sys.executable, "-m", "atlas_reviewer.service"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 2
    assert b"8080" in proc.stderr
