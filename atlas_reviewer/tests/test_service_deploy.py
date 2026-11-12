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
        "chown 10001:10001 /data",
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
