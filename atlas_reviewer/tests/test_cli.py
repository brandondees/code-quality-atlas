# SPDX-License-Identifier: MIT
import io
import json
import subprocess
import sys

import pytest

from atlas_reviewer import cli
from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.ports import BoundaryError, NotFoundError

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


APP_ENV = {
    cli.ENV_APP_ID: "5648875",
    cli.ENV_APP_KEY: "-----BEGIN PRIVATE KEY-----\\nnot-a-real-key\\n-----END PRIVATE KEY-----",
    cli.ENV_INSTALLATION_ID: "12345",
    cli.ENV_SPRITES_TOKEN: "org/1/sprites-secret",
}


def scripted_sprites(env):
    return FakeSprites.from_script(
        json.loads((FIXTURE / "runner-script.json").read_text())
    )


@pytest.mark.parametrize(
    "dropped",
    [cli.ENV_APP_ID, cli.ENV_APP_KEY, cli.ENV_INSTALLATION_ID, cli.ENV_SPRITES_TOKEN],
)
def test_live_mode_names_the_missing_credential(tmp_path, dropped):
    env = {k: v for k, v in APP_ENV.items() if k != dropped}
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, env=env
    )
    assert code == cli.EXIT_USAGE
    assert dropped in err


def test_installation_id_must_be_numeric(tmp_path):
    env = {**APP_ENV, cli.ENV_INSTALLATION_ID: "12a"}
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, env=env
    )
    assert code == cli.EXIT_USAGE
    assert "must be a positive integer" in err


def test_sweep_needs_the_sprites_token(tmp_path):
    code, _, err = run_cli("--state-dir", str(tmp_path), "sweep")
    assert code == cli.EXIT_USAGE
    assert cli.ENV_SPRITES_TOKEN in err


def test_live_wiring_mints_scoped_read_only_tokens_and_scrubs_credentials(
    tmp_path, monkeypatch
):
    seen = {}

    class Tokens:
        def __init__(self, transport, clock, **kwargs):
            seen.update(kwargs)

        def secrets(self):
            return (fake_token("ghs_"),)

    def github(transport, tokens):
        seen["tokens"] = tokens
        return FixtureGitHub(FIXTURE)

    monkeypatch.setattr(cli, "AppInstallationTokens", Tokens)
    monkeypatch.setattr(cli, "GitHubClient", github)
    env = {**APP_ENV, cli.ENV_STATE_DIR: str(tmp_path)}
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["review", "--event", EVENT, "--include-issues"],
        env=env, out=out, err=err, sprites_factory=scripted_sprites,
    )  # fmt: skip
    assert code == cli.EXIT_OK, err.getvalue()
    assert seen["app_id"] == "5648875"
    assert seen["installation_id"] == 12345
    assert seen["private_key"].count("\n") == 2
    assert seen["repositories"] == ("example-app",)
    assert set(seen["permissions"].values()) == {"read"}
    assert seen["permissions"]["issues"] == "read"
    assert isinstance(seen["tokens"], Tokens)
    draft = out.getvalue()
    assert "Mode | live" in draft
    assert "not-a-real-key" not in draft
    assert (tmp_path / "runners.ledger").read_text() == ""


def test_issues_permission_is_only_requested_when_opted_in(tmp_path, monkeypatch):
    seen = {}

    def tokens(transport, clock, **kwargs):
        seen.update(kwargs)
        return type("T", (), {"secrets": lambda self: ()})()

    monkeypatch.setattr(cli, "AppInstallationTokens", tokens)
    monkeypatch.setattr(
        cli, "GitHubClient", lambda transport, t: FixtureGitHub(FIXTURE)
    )
    cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT],
        env=APP_ENV, out=io.StringIO(), err=io.StringIO(), sprites_factory=scripted_sprites,
    )  # fmt: skip
    assert "issues" not in seen["permissions"]


class StubOpenRouter:
    name = "openrouter:anthropic/claude-sonnet-5.5"

    def __init__(self, key, refuse=False):
        self.key, self.refuse, self.preflighted = key, refuse, False

    def preflight(self):
        if self.refuse:
            raise BoundaryError("key limit is unset (unlimited); refusing")
        self.preflighted = True

    def complete(self, prompt):
        assert self.preflighted
        return "narrative from the stub"

    def usage_lines(self):
        return ("call 1: ok; $0.0100",)


@pytest.mark.parametrize(
    "extra,message",
    [
        ((), "live inference is off"),
        (("--allow-live-inference", "--dry-run"), "--dry-run is offline-only"),
    ],
)
def test_openrouter_needs_the_explicit_flag_and_never_runs_in_dry_run(
    tmp_path, extra, message
):
    made = []
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT, "--provider", "openrouter", *extra],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"},
        out=io.StringIO(), err=(err := io.StringIO()),
        openrouter_factory=lambda key: made.append(key) or StubOpenRouter(key),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert message in err.getvalue()
    assert made == []


def test_openrouter_needs_its_key(tmp_path):
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT,
        "--provider", "openrouter", "--allow-live-inference", env=APP_ENV,
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert cli.ENV_OPENROUTER_KEY in err


def test_openrouter_preflight_refusal_stops_before_any_review(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "AppInstallationTokens", lambda *a, **k: pytest.fail("wired")
    )
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT,
         "--provider", "openrouter", "--allow-live-inference"],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"}, out=out, err=err,
        openrouter_factory=lambda key: StubOpenRouter(key, refuse=True),
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    assert "unlimited" in err.getvalue()
    assert out.getvalue() == ""


def test_openrouter_review_reports_model_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "AppInstallationTokens",
        lambda transport, clock, **kw: type("T", (), {"secrets": lambda self: ()})(),
    )  # fmt: skip
    monkeypatch.setattr(
        cli, "GitHubClient", lambda transport, t: FixtureGitHub(FIXTURE)
    )
    made = []
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT,
         "--provider", "openrouter", "--allow-live-inference"],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"}, out=out, err=io.StringIO(),
        sprites_factory=scripted_sprites,
        openrouter_factory=lambda key: made.append(StubOpenRouter(key)) or made[-1],
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert made[0].key == "sk-or-v1-x"
    draft = out.getvalue()
    assert "- call 1: ok; $0.0100" in draft
    assert "sk-or-v1-x" not in draft


def test_probe_runner_reports_tool_availability_and_destroys(tmp_path):
    api = scripted_sprites({})
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    text = out.getvalue()
    assert "status: completed" in text
    assert "cleanup: destroyed (verified absent)" in text
    assert "tool python3: present" in text
    assert "tool shellcheck: ABSENT" in text
    assert "raw exec response sample:" in text
    assert api.live_names() == ()


def test_sweep_destroys_ledgered_runners(tmp_path):
    api = FakeSprites()
    api.create("cqa-rev-leftover")
    (tmp_path / "runners.ledger").write_text("cqa-rev-leftover\n")
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "cqa-rev-leftover: destroyed (verified absent)" in out.getvalue()
    assert api.live_names() == ()


def test_boundary_errors_exit_nonzero(tmp_path, monkeypatch):
    class NoPull(FixtureGitHub):
        def get_pull(self, repo, number):
            raise NotFoundError("GitHub 404")

    monkeypatch.setattr(cli, "FixtureGitHub", NoPull)
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run"
    )
    assert code == cli.EXIT_BOUNDARY
    assert "GitHub 404" in err
    assert HEAD not in err
