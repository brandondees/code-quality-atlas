# SPDX-License-Identifier: MIT
import io
import json
import subprocess
import sys

import pytest

from atlas_reviewer import cli
from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.github_fixture import FixtureGitHub

from .helpers import FIXTURE, HEAD, fake_token

EVENT = str(FIXTURE / "event.json")


def run_cli(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), env=env or {}, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_dry_run_needs_no_credentials_and_prints_a_draft(tmp_path):
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run"
    )
    assert code == cli.EXIT_OK
    assert out.startswith("# Code Quality Atlas review -- DRAFT")
    assert "Mode | dry run" in out


def test_dry_run_can_write_the_draft_to_a_file(tmp_path):
    target = tmp_path / "draft.md"
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run", "--out", str(target),
        "--expect", "check_run:security-scan", "--include-issues",
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "written to" in out
    text = target.read_text()
    assert "security-scan" in text
    assert "Issue context: off" not in text
    assert "issue-7" in text


def test_module_entry_point_runs_offline(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "atlas_reviewer",
            "--state-dir",
            str(tmp_path),
            "review",
            "--event",
            EVENT,
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": ""},
        cwd=FIXTURE.parent.parent.parent,
    )
    assert result.returncode == 0, result.stderr
    assert "DRAFT" in result.stdout


@pytest.mark.parametrize(
    "payload,message",
    [
        ("not json", "cannot read event file"),
        ("[1]", "JSON object"),
        (
            json.dumps({"repo": "o/r", "pr_number": 1, "head_sha": "short"}),
            "invalid event",
        ),
    ],
)
def test_bad_event_files_are_usage_errors(tmp_path, payload, message):
    path = tmp_path / "event.json"
    path.write_text(payload)
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", str(path), "--dry-run"
    )
    assert code == cli.EXIT_USAGE
    assert message in err


def test_bad_expect_values_are_usage_errors(tmp_path):
    code, _, err = run_cli(
        "--state-dir",
        str(tmp_path),
        "review",
        "--event",
        EVENT,
        "--dry-run",
        "--expect",
        "nope",
    )
    assert code == cli.EXIT_USAGE
    assert "KIND:NAME" in err


def test_live_mode_names_the_missing_credential(tmp_path):
    code, _, err = run_cli("--state-dir", str(tmp_path), "review", "--event", EVENT)
    assert code == cli.EXIT_USAGE
    assert cli.ENV_GITHUB_TOKEN in err
    code, _, err = run_cli("--state-dir", str(tmp_path), "sweep")
    assert cli.ENV_SPRITES_TOKEN in err


def test_live_wiring_scrubs_its_own_credentials(tmp_path, monkeypatch):
    gh_token = fake_token("ghs_")
    seen = {}

    def github(transport, token):
        seen["github"] = token
        return FixtureGitHub(FIXTURE)

    def sprites(transport, token):
        seen["sprites"] = token
        script = json.loads((FIXTURE / "runner-script.json").read_text())
        return FakeSprites.from_script(script)

    monkeypatch.setattr(cli, "GitHubClient", github)
    monkeypatch.setattr(cli, "SpritesClient", sprites)
    env = {
        cli.ENV_GITHUB_TOKEN: gh_token,
        cli.ENV_SPRITES_TOKEN: "org/1/sprites-secret",
        cli.ENV_STATE_DIR: str(tmp_path),
    }
    code, out, _ = run_cli("review", "--event", EVENT, env=env)
    assert code == cli.EXIT_OK
    assert seen == {"github": gh_token, "sprites": "org/1/sprites-secret"}
    assert "Mode | live" in out
    assert (tmp_path / "runners.ledger").read_text() == ""


def test_sweep_destroys_ledgered_runners(tmp_path, monkeypatch):
    api = FakeSprites()
    api.create("cqa-rev-leftover")
    (tmp_path / "runners.ledger").write_text("cqa-rev-leftover\n")
    monkeypatch.setattr(cli, "SpritesClient", lambda transport, token: api)
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "sweep", env={cli.ENV_SPRITES_TOKEN: "t"}
    )
    assert code == cli.EXIT_OK
    assert "cqa-rev-leftover: destroyed (verified absent)" in out
    assert api.live_names() == ()


def test_boundary_errors_exit_nonzero(tmp_path, monkeypatch):
    class NoPull(FixtureGitHub):
        def get_pull(self, repo, number):
            from atlas_reviewer.ports import NotFoundError

            raise NotFoundError("GitHub 404")

    monkeypatch.setattr(cli, "FixtureGitHub", NoPull)
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run"
    )
    assert code == cli.EXIT_BOUNDARY
    assert "GitHub 404" in err
    assert HEAD not in err
