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


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        ("triage", "triage depth runs the critical tier"),
        ("review", "the lens picker gave no usable lens list"),
    ],
)
def test_depth_reaches_lens_selection(tmp_path, depth, expected):
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--depth", depth,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert expected in out


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
        openrouter_factory=lambda key, limits: made.append(key) or StubOpenRouter(key),
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
        openrouter_factory=lambda key, limits: StubOpenRouter(key, refuse=True),
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
        openrouter_factory=lambda key, limits: made.append(StubOpenRouter(key)) or made[-1],
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
    assert "raw exec response sample:" in text
    assert f"stdin round-trip: ok: sent {3 * 1024 * 1024} bytes" in text
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


def test_sweep_refuses_to_run_while_a_review_holds_the_lock(tmp_path):
    from atlas_reviewer.ledger import single_review_lock

    api = FakeSprites()
    api.create("cqa-rev-live-review")
    (tmp_path / "runners.ledger").write_text("cqa-rev-live-review\n")
    out, err = io.StringIO(), io.StringIO()
    with single_review_lock(tmp_path / "review.lock"):
        code = cli.main(
            ["--state-dir", str(tmp_path), "sweep"],
            env={}, out=out, err=err, sprites_factory=lambda env: api,
        )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert api.live_names() == ("cqa-rev-live-review",)
    assert "delete" not in [c[0] for c in api.calls]
    assert "another review holds" in err.getvalue()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep"],
        env={}, out=io.StringIO(), err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
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


# --- telemetry, call config and the review-sequence probe -------------------


def live_github(monkeypatch):
    monkeypatch.setattr(
        cli, "AppInstallationTokens",
        lambda transport, clock, **kw: type("T", (), {"secrets": lambda self: ()})(),
    )  # fmt: skip
    monkeypatch.setattr(
        cli, "GitHubClient", lambda transport, t: FixtureGitHub(FIXTURE)
    )


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_live_review_writes_secret_free_jsonl_telemetry_by_default(
    tmp_path, monkeypatch
):
    live_github(monkeypatch)
    draft_path = tmp_path / "draft.md"
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT, "--out", str(draft_path)],
        env=APP_ENV, out=out, err=io.StringIO(), sprites_factory=scripted_sprites,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    (events_file,) = (tmp_path / "telemetry").glob("review-*.jsonl")
    raw = events_file.read_text()
    for secret in (APP_ENV[cli.ENV_SPRITES_TOKEN], "not-a-real-key"):
        assert secret not in raw
    phases = [e["phase"] for e in jsonl(events_file)]
    for phase in ("evidence fetch", "create", "egress", "exec", "upload", "unpack",
                  "tool", "destroy", "verify", "model call"):  # fmt: skip
        assert phase in phases, phase
    assert f"telemetry: {len(phases)} event(s), {events_file}" in out.getvalue()
    assert "## Lifecycle telemetry" in draft_path.read_text()


def test_a_dry_run_writes_telemetry_only_when_asked(tmp_path):
    run_cli("--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run")
    assert not (tmp_path / "telemetry").exists()
    target = tmp_path / "events.jsonl"
    code, _, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--events", str(target),
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert any(e["phase"] == "model call" for e in jsonl(target))


@pytest.mark.parametrize(
    "flags,message",
    [
        (("--max-model-calls", "4"), "model calls must be 1 to 3"),
        (("--max-model-calls", "0"), "model calls must be 1 to 3"),
        (("--diff-chars-per-call", "10"), "at least 1000"),
    ],
)
def test_the_call_cap_and_per_call_budget_flags_are_validated(tmp_path, flags, message):
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run", *flags
    )
    assert code == cli.EXIT_USAGE
    assert message in err


def test_the_provider_gets_the_configured_call_cap_and_preflight_is_timed(
    tmp_path, monkeypatch
):
    live_github(monkeypatch)
    limits_seen = []

    def factory(key, limits):
        limits_seen.append(limits)
        return StubOpenRouter(key)

    events = tmp_path / "e.jsonl"
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT, "--provider", "openrouter",
         "--allow-live-inference", "--max-model-calls", "2", "--events", str(events)],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"}, out=io.StringIO(),
        err=io.StringIO(), sprites_factory=scripted_sprites, openrouter_factory=factory,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert limits_seen[0].max_calls == 2
    first = jsonl(events)[0]
    assert (first["phase"], first["step"], first["status"]) == (
        "model preflight", "key status", "ok",
    )  # fmt: skip


def test_a_preflight_refusal_is_labelled(tmp_path):
    err = io.StringIO()
    cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT,
         "--provider", "openrouter", "--allow-live-inference"],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"}, out=io.StringIO(), err=err,
        openrouter_factory=lambda key, limits: StubOpenRouter(key, refuse=True),
    )  # fmt: skip
    assert "model preflight / key status failed after" in err.getvalue()


def test_probe_runner_review_sequence_runs_the_real_exec_order_on_a_tarball(tmp_path):
    tarball = tmp_path / "checkout.tar.gz"
    tarball.write_bytes(FixtureGitHub(FIXTURE).get_tarball("o/r", HEAD))
    api = FakeSprites.from_script(
        {"exec": [{"match": "tar -xzf", "stdout": "", "exit_code": 0},
                  {"match": "echo posix-sh", "stdout": "posix-sh", "exit_code": 0},
                  {"match": "find .", "stdout": "3", "exit_code": 0}]}
    )  # fmt: skip
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--tarball", str(tarball)],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    text = out.getvalue()
    assert "status: completed" in text
    assert "cleanup: destroyed (verified absent)" in text
    assert f"source tarball: {tarball.stat().st_size} bytes" in text
    assert "tool source-file-count (posix-sh): exit 0; output: '3'" in text
    assert (
        "trusted python: /.sprite/languages/python/pyenv/versions/3.13.7/bin/python3 "
        "(3.13.7)" in text
    )
    assert "diagnostic bare python3 in the checkout: exit " in text
    assert "[expected: expected-may-hang: exit 124 after 15s" in text
    assert "## Lifecycle telemetry" in text
    scripts = [c[2] for c in api.calls if c[0] == "exec"]
    steps = [
        "for b in", "atlas-python:", "readlink -f", "ls -1", "head -c", "tar -xzf",
        "echo posix-sh", "find .", "-I --version", "PYENV_VERSION=3.13.7",
        "timeout -k 2 15 python3 --version",
    ]  # fmt: skip
    assert [step in s for step, s in zip(steps, scripts, strict=True)] == [True] * 11
    sprite_env = [a[0] == "/bin/sh" for a in api.argv_seen]
    assert sprite_env == [False] * 9 + [True] * 2
    (events_file,) = (tmp_path / "telemetry").glob("probe-review-*.jsonl")
    steps = [(e["phase"], e["step"]) for e in jsonl(events_file)]
    assert ("upload", f"{tarball.stat().st_size}-byte tarball") in steps
    assert ("unpack", "tar -xzf") in steps
    assert "model call" not in {p for p, _ in steps}
    assert api.live_names() == ()


def test_probe_runner_review_sequence_can_fetch_the_tarball_and_run_review_tools(
    tmp_path, monkeypatch
):
    live_github(monkeypatch)
    api = scripted_sprites({})
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--event", EVENT, "--tools", "review", "--events", str(tmp_path / "e.jsonl")],
        env=APP_ENV, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "tool python-compileall (Python 3.13.5): exit 0" in out.getvalue()
    assert jsonl(tmp_path / "e.jsonl")[0]["phase"] == "source fetch"


@pytest.mark.parametrize(
    "extra,message",
    [
        ((), "needs --tarball FILE or --event FILE"),
        (("--tarball", "/nonexistent/x.tgz"), "cannot read tarball"),
    ],
)
def test_probe_runner_review_sequence_needs_a_readable_source(tmp_path, extra, message):
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "probe-runner", "--sequence", "review", *extra
    )
    assert code == cli.EXIT_USAGE
    assert message in err


def test_probe_runner_review_sequence_refuses_an_oversized_tarball(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "MAX_TARBALL_BYTES", 3)
    tarball = tmp_path / "big.tgz"
    tarball.write_bytes(b"0123456789")
    api = FakeSprites()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--tarball", str(tarball)],
        env={}, out=io.StringIO(), err=(err := io.StringIO()),
        sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "over 3" in err.getvalue()
    assert api.calls == []


def test_probe_runner_review_sequence_reports_a_missing_tool(tmp_path):
    tarball = tmp_path / "checkout.tar.gz"
    tarball.write_bytes(b"not really gzip")
    api = FakeSprites.from_script(
        {"installed": [], "exec": [{"match": "tar -xzf", "stdout": "", "exit_code": 0}]}
    )
    out = io.StringIO()
    cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--tarball", str(tarball)],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert "tool source-file-count: not run -- `sh` not found" in out.getvalue()


def test_the_first_frame_window_flag_reaches_every_exec_without_input(tmp_path):
    tarball = tmp_path / "checkout.tar.gz"
    tarball.write_bytes(FixtureGitHub(FIXTURE).get_tarball("o/r", HEAD))
    api = FakeSprites.from_script(
        {"exec": [{"match": "tar -xzf", "stdout": "", "exit_code": 0},
                  {"match": "echo posix-sh", "stdout": "posix-sh", "exit_code": 0},
                  {"match": "find .", "stdout": "3", "exit_code": 0}]}
    )  # fmt: skip
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--tarball", str(tarball), "--first-frame-seconds", "7"],
        env={}, out=io.StringIO(), err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert api.first_bytes_seen == [7.0] * 4 + [None] + [7.0] * 6


@pytest.mark.parametrize("value", ["0", "-1"])
def test_the_first_frame_window_must_be_positive(tmp_path, value, capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(
            ["--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
             "--first-frame-seconds", value],
            env={}, out=io.StringIO(), err=io.StringIO(),
        )  # fmt: skip
    assert info.value.code == 2
    assert "positive number of seconds" in capsys.readouterr().err


def test_review_config_refuses_a_non_positive_first_frame_window():
    from atlas_reviewer.controller import ReviewConfig

    with pytest.raises(ValueError, match="first-frame"):
        ReviewConfig(first_frame_s=0)
