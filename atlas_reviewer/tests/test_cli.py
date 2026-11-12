# SPDX-License-Identifier: MIT
import io
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_reviewer import cli
from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.interpreter import PYENV_VERSIONS, PYTHON_TAG
from atlas_reviewer.ports import BoundaryError, NotFoundError, StreamTimeoutError
from atlas_reviewer.runner import EGRESS_TAG, event_runner_name

from .helpers import FIXTURE, HEAD, SOURCE_TARBALL, FakeClock, fake_token

EVENT = str(FIXTURE / "event.json")


def run_cli(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), env=env or {}, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_agentic_limit_help_says_the_one_shot_review_does_not_apply_them(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(["review", "--help"], env={})
    assert raised.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "Validated only: the one-shot review does not apply it." in text


def test_a_bad_agentic_limit_is_refused_before_the_review(tmp_path):
    code, _out, err = run_cli(
        "--state-dir",
        str(tmp_path),
        "review",
        "--event",
        EVENT,
        "--dry-run",
        "--reservation-usd",
        "0",
    )
    assert code == cli.EXIT_USAGE
    assert "reservation_usd" in err
    code, _out, err = run_cli(
        "--state-dir",
        str(tmp_path),
        "review",
        "--event",
        EVENT,
        "--dry-run",
        env={"ATLAS_MAX_TURNS": "nope"},
    )
    assert code == cli.EXIT_USAGE
    assert "max_turns" in err


def test_dry_run_needs_no_credentials_and_prints_a_draft(tmp_path):
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run"
    )
    assert code == cli.EXIT_INCOMPLETE
    assert out.startswith("<!-- atlas-review-status: {")
    assert "\n# Code Quality Atlas review -- DRAFT\n" in out
    assert "Mode | dry run" in out


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        ("triage", "triage depth makes no picker call"),
        ("review", "the lens picker was not called"),
    ],
)
def test_depth_reaches_lens_selection(tmp_path, depth, expected):
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--depth", depth,
    )  # fmt: skip
    assert code == cli.EXIT_INCOMPLETE
    assert expected in out


def test_dry_run_can_write_the_draft_to_a_file(tmp_path):
    target = tmp_path / "draft.md"
    code, out, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run", "--out", str(target),
        "--expect", "check_run:security-scan", "--include-issues",
    )  # fmt: skip
    assert code == cli.EXIT_INCOMPLETE
    assert "written to" in out
    assert "review event: COMMENT; coverage_complete=false; unreviewed_files=2" in out
    text = target.read_text()
    assert "security-scan" in text
    assert "Issue context: off" not in text
    assert "issue-7" in text


def test_an_out_path_in_a_missing_directory_is_refused_before_the_review(tmp_path):
    target = tmp_path / "no-such-dir" / "draft.md"
    code, out, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run", "--out", str(target),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "not a file in an existing directory" in err
    assert out == ""


def test_an_unwritable_out_path_is_refused_before_the_review(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.os, "access", lambda path, mode: False)
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--out", str(tmp_path / "draft.md"),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "not writable" in err


def test_a_failed_draft_write_still_prints_the_draft(tmp_path, monkeypatch):
    target = tmp_path / "draft.md"
    real = cli.os.open

    def failing(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError("disk full")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(cli.os, "open", failing)
    code, out, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run", "--out", str(target),
    )  # fmt: skip
    assert code == cli.EXIT_INCOMPLETE
    assert "\n# Code Quality Atlas review -- DRAFT\n" in out
    assert "review event:" not in out
    assert "disk full" in err
    assert "the draft went to stdout" in err
    assert "review event: COMMENT; coverage_complete=false; unreviewed_files=2" in err


def test_without_out_the_summary_goes_to_stderr_and_stdout_is_only_the_draft(tmp_path):
    code, out, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run"
    )
    assert code == cli.EXIT_INCOMPLETE
    assert out.startswith("<!-- atlas-review-status: {")
    assert "review event:" not in out and "telemetry:" not in out
    assert "telemetry: " in err and "(not written)" in err
    assert "review event: COMMENT; coverage_complete=false" in err


@pytest.mark.parametrize(
    "script,message",
    [
        ("{not json", "cannot read runner script"),
        ("[1, 2]", "must hold a JSON object"),
        ('{"exec": [{"match": "x"}]}', "invalid runner script"),
    ],
)
def test_a_bad_runner_script_is_a_usage_error(tmp_path, script, message):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURE, fixtures)
    (fixtures / "runner-script.json").write_text(script)
    code, out, err = run_cli(
        "--state-dir", str(tmp_path / "state"), "review", "--event", EVENT,
        "--dry-run", "--fixtures", str(fixtures),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert message in err
    assert "Traceback" not in err
    assert out == ""


def test_a_missing_fixture_directory_is_a_usage_error(tmp_path):
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--fixtures", str(tmp_path / "nowhere"),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "fixture directory" in err


@pytest.mark.parametrize(
    "command", [("review", "--event", EVENT, "--dry-run"), ("sweep",)]
)
def test_a_state_dir_under_a_file_is_a_usage_error(tmp_path, command):
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    code, _, err = run_cli(
        "--state-dir", str(blocker / "state"), *command,
        env={cli.ENV_SPRITES_TOKEN: "org/1/sprites-secret"},
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "--state-dir" in err and "cannot be created" in err


def test_an_events_file_under_a_file_is_a_usage_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--events", str(blocker / "e.jsonl"),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "telemetry file" in err


def test_a_dangling_out_symlink_is_refused_before_the_review(tmp_path):
    link = tmp_path / "draft.md"
    link.symlink_to(tmp_path / "missing" / "target.md")
    code, out, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--out", str(link),
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "symlink to a missing target" in err
    assert out == ""


def test_drafts_telemetry_ledger_and_lock_are_private(tmp_path, monkeypatch):
    live_github(monkeypatch)
    state = tmp_path / "s1" / "s2" / "state"
    draft = tmp_path / "draft.md"
    code = cli.main(
        ["--state-dir", str(state), "review", "--event", EVENT, "--out", str(draft)],
        env=APP_ENV, out=io.StringIO(), err=io.StringIO(), sprites_factory=scripted_sprites,
    )  # fmt: skip
    assert code == cli.EXIT_INCOMPLETE
    events = tmp_path / "e1" / "e2" / "events.jsonl"
    code, _, _ = run_cli(
        "--state-dir", str(state), "review", "--event", EVENT, "--dry-run",
        "--events", str(events),
    )  # fmt: skip
    assert code == cli.EXIT_INCOMPLETE
    (default_events,) = (state / "telemetry").glob("review-*.jsonl")
    files = (draft, default_events, events, events.with_name("events.jsonl.lock"))
    for path in (*files, state / "runners.ledger", state / "review.lock"):
        assert path.stat().st_mode & 0o777 == 0o600, path
    created = (state.parent.parent, state.parent, state, state / "telemetry")
    for path in (*created, events.parent.parent, events.parent):
        assert path.stat().st_mode & 0o777 == 0o700, path


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
    assert result.returncode == cli.EXIT_INCOMPLETE, result.stderr
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
        (
            json.dumps({"repo": None, "pr_number": 1, "head_sha": [1]}),
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


@pytest.mark.parametrize("raw", ["12a", "0", "000", "\u00b2", "-5"])
def test_installation_id_must_be_numeric(tmp_path, raw):
    env = {**APP_ENV, cli.ENV_INSTALLATION_ID: raw}
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
    # No model ran (offline provider), so file coverage is incomplete.
    assert code == cli.EXIT_INCOMPLETE, err.getvalue()
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

    def __init__(self, key, refuse=False, reply="narrative from the stub"):
        self.key, self.refuse, self.preflighted = key, refuse, False
        self.reply = reply

    def preflight(self):
        if self.refuse:
            raise BoundaryError("key limit is unset (unlimited); refusing")
        self.preflighted = True

    def complete(self, prompt):
        assert self.preflighted
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

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
    assert "outbound connection: UNVERIFIED" in text
    assert api.live_names() == ()


def test_probe_runner_exits_nonzero_when_the_runner_can_connect_out(tmp_path):
    class OpenEgress(FakeSprites):
        def _answer(self, script, stdin):
            if EGRESS_TAG in script:
                return f"{EGRESS_TAG}:1.1.1.1:443:tried:connected:0", 0
            return super()._answer(script, stdin)

    api = OpenEgress()
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    assert "outbound connection: OPEN: 1.1.1.1:443 CONNECTED" in out.getvalue()
    assert "probe: FAILED" in out.getvalue()
    assert api.live_names() == ()


def test_probe_runner_exits_nonzero_when_the_stdin_check_mismatches(tmp_path):
    class ShortStdin(FakeSprites):
        def _answer(self, script, stdin):
            return ("12", 0) if "wc -c" in script else super()._answer(script, stdin)

    api = ShortStdin()
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    assert "stdin round-trip: MISMATCH" in out.getvalue()
    assert "probe: FAILED" in out.getvalue()


def test_probe_runner_exits_nonzero_when_the_runner_fails(tmp_path):
    tarball = tmp_path / "checkout.tar.gz"
    tarball.write_bytes(b"x")
    api = FakeSprites(fail_on={"create": BoundaryError("HTTP 500")})
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--tarball", str(tarball)],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    assert "status: failed" in out.getvalue()


def test_sweep_destroys_ledgered_runners(tmp_path):
    api = FakeSprites()
    api.create("cqa-rev-leftover")
    (tmp_path / "runners.ledger").write_text("cqa-rev-leftover\n")
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--force-live"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "cqa-rev-leftover: destroyed (verified absent)" in out.getvalue()
    assert api.live_names() == ()


EVENT_RUNNER = event_runner_name(cli.load_event(Path(EVENT)))


def _offline_live_review(tmp_path, monkeypatch, api):
    monkeypatch.setattr(
        cli,
        "AppInstallationTokens",
        lambda transport, clock, **kw: type("T", (), {"secrets": lambda self: ()})(),
    )
    monkeypatch.setattr(
        cli, "GitHubClient", lambda transport, t: FixtureGitHub(FIXTURE)
    )
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT],
        env=APP_ENV, out=out, err=err, sprites_factory=lambda env: api,
    )  # fmt: skip
    return code, out.getvalue(), err.getvalue()


_STOP_DURING_REVIEW = """\
import json, os, signal
from pathlib import Path
from atlas_reviewer import cli
from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.stops import install_interrupts

fixture = Path(os.environ["STOP_FIXTURE"])

class StopMidDelete(FakeSprites):
    def delete(self, name):
        os.kill(os.getpid(), signal.SIGTERM)
        super().delete(name)

api = StopMidDelete.from_script(
    json.loads((fixture / "runner-script.json").read_text())
)
cli.AppInstallationTokens = lambda *a, **k: type("T", (), {"secrets": lambda self: ()})()
cli.GitHubClient = lambda transport, tokens: FixtureGitHub(fixture)
install_interrupts()
raise SystemExit(cli.main(
    ["--state-dir", os.environ["STOP_STATE"], "review", "--event",
     str(fixture / "event.json"), "--out", os.environ["STOP_DRAFT"],
     "--events", os.environ["STOP_EVENTS"], "--depth", "triage"],
    env={
        "ATLAS_GITHUB_APP_ID": "5648875",
        "ATLAS_GITHUB_APP_PRIVATE_KEY": "not-a-real-key",
        "ATLAS_GITHUB_INSTALLATION_ID": "12345",
        "ATLAS_SPRITES_TOKEN": "org/1/sprites-secret",
    },
    sprites_factory=lambda env: api,
))
"""


def test_a_stop_during_the_final_delete_ends_the_review_before_later_work(
    tmp_path,
):
    """The delete finishes, then the stop ends the review. Conversation
    fetches, model calls, or a draft written after that signal are the
    over-deferral this catches."""
    draft = tmp_path / "draft.md"
    events_path = tmp_path / "events.jsonl"
    proc = subprocess.run(
        [sys.executable, "-c", _STOP_DURING_REVIEW],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "STOP_FIXTURE": str(FIXTURE),
            "STOP_STATE": str(tmp_path / "state"),
            "STOP_DRAFT": str(draft),
            "STOP_EVENTS": str(events_path),
        },
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    # An uncaught KeyboardInterrupt kills the process with SIGINT. A shell
    # reports that as 130; subprocess reports the signal as a negative code.
    assert proc.returncode == -signal.SIGINT, proc.stderr
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert any(e["phase"] == "destroy" and e["step"] == "outcome" for e in events)
    assert not any(e["phase"] == "conversation fetch" for e in events), events
    assert not any(e["phase"] == "model call" for e in events), events
    assert not draft.exists()


_STOP_THEN_ERROR = """\
import os, signal
from atlas_reviewer import cli
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.stops import held, install_interrupts

def boom(args, run):
    with held():
        os.kill(os.getpid(), signal.SIGTERM)
    if os.environ["STOP_ERROR"] == "boundary":
        raise BoundaryError("sprites down")
    raise OSError("disk")

cli._cmd_sweep = boom
install_interrupts()
raise SystemExit(cli.main(
    ["--state-dir", os.environ["STOP_STATE"], "sweep"],
    env={"ATLAS_SPRITES_TOKEN": "org/1/sprites-secret"},
    sprites_factory=lambda env: None,
))
"""


@pytest.mark.parametrize("kind", ["boundary", "oserror"])
def test_a_pending_stop_is_not_dropped_when_the_command_fails(tmp_path, kind):
    """A stop held before a mapped or unmapped error still ends the
    process. Returning the mapped code, or letting OSError propagate,
    would drop it."""
    proc = subprocess.run(
        [sys.executable, "-c", _STOP_THEN_ERROR],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "STOP_STATE": str(tmp_path / "state"),
            "STOP_ERROR": kind,
        },
        capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    assert proc.returncode == -signal.SIGINT, proc.stderr
    if kind == "boundary":
        assert "atlas_reviewer: sprites down" in proc.stderr


def test_a_live_review_prints_its_event_runner_name_before_creating_it(
    tmp_path, monkeypatch
):
    api = scripted_sprites({})
    code, _, err = _offline_live_review(tmp_path, monkeypatch, api)
    assert code == cli.EXIT_INCOMPLETE, err
    assert err.startswith(
        f"atlas_reviewer: runner Sprite for this review: {EVENT_RUNNER}\n"
    )
    assert api.calls.index(("exists", EVENT_RUNNER)) < api.calls.index(
        ("create", EVENT_RUNNER)
    )
    assert api.live_names() == ()


def test_a_live_review_refuses_a_sprite_that_already_holds_its_name(
    tmp_path, monkeypatch
):
    api = scripted_sprites({})
    api.create(EVENT_RUNNER)
    code, out, err = _offline_live_review(tmp_path, monkeypatch, api)
    assert code == cli.EXIT_BOUNDARY
    assert f"a Sprite named {EVENT_RUNNER} already exists" in err
    assert f"sweep --runner {EVENT_RUNNER} --force-live" in err
    assert out == ""
    assert [c[0] for c in api.calls] == ["create", "exists"]
    assert api.live_names() == (EVENT_RUNNER,)


def test_a_live_review_that_loses_the_create_race_stops_and_deletes_nothing(
    tmp_path, monkeypatch
):
    """Another review of the commit creates the runner between this one's
    existence check and its create: create is the claim, so this review
    exits 3 without touching the other review's Sprite."""
    api = scripted_sprites({})
    checked = api.exists

    def the_other_review_creates_it_next(name):
        found = checked(name)
        api.create(name)
        return found

    monkeypatch.setattr(api, "exists", the_other_review_creates_it_next)
    code, out, err = _offline_live_review(tmp_path, monkeypatch, api)
    assert code == cli.EXIT_BOUNDARY, err
    assert f"refused to create runner {EVENT_RUNNER}" in err
    assert "delete" not in [c[0] for c in api.calls]
    assert api.live_names() == (EVENT_RUNNER,)
    assert (tmp_path / "runners.ledger").read_text() == ""
    assert out == ""


def test_a_plain_sweep_cannot_delete_a_runner_another_review_created_after_a_lost_create(
    tmp_path, monkeypatch
):
    """This review's create times out and never lands, so its name stays in
    the ledger. A review of the same commit on another machine then creates
    that name. A plain sweep here must not delete the other review's Sprite."""
    api = scripted_sprites({})

    def create_times_out(name):
        api.calls.append(("create", name))
        raise StreamTimeoutError("create: no response within 30s")

    monkeypatch.setattr(api, "create", create_times_out)
    code, out, err = _offline_live_review(tmp_path, monkeypatch, api)
    assert code == cli.EXIT_INCOMPLETE, err
    assert "destroy was NOT verified" in out
    assert (tmp_path / "runners.ledger").read_text() == f"{EVENT_RUNNER}\n"

    FakeSprites.create(api, EVENT_RUNNER)
    err = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep"],
        env={}, out=io.StringIO(), err=err, sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "add --force-live" in err.getvalue()
    assert api.live_names() == (EVENT_RUNNER,)
    assert "delete" not in [c[0] for c in api.calls]


def test_a_plain_sweep_of_an_empty_ledger_needs_no_force_live(tmp_path):
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: FakeSprites(),
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert out.getvalue() == "0 runner(s) in the ledger\n"


def test_sweep_destroys_a_runner_named_on_the_command_line(tmp_path):
    api = FakeSprites()
    api.create("cqa-rev-left-on-another-machine")
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--runner", "cqa-rev-left-on-another-machine",
         "--force-live"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "cqa-rev-left-on-another-machine: destroyed (verified absent)" in (
        out.getvalue()
    )
    assert api.live_names() == ()
    assert (tmp_path / "runners.ledger").read_text() == ""


def test_sweep_derives_the_runner_name_from_an_event_file(tmp_path):
    api = FakeSprites()
    api.create(EVENT_RUNNER)
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--event", EVENT, "--force-live"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert f"{EVENT_RUNNER}: destroyed (verified absent)" in out.getvalue()
    assert api.live_names() == ()


@pytest.mark.parametrize(
    "named",
    [["--runner", "cqa-rev-maybe-live"], ["--event", EVENT]],
    ids=["runner", "event"],
)
def test_sweep_by_name_needs_force_live_because_no_lock_covers_it(tmp_path, named):
    api = FakeSprites()
    api.create("cqa-rev-maybe-live")
    api.create(EVENT_RUNNER)
    err = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", *named],
        env={}, out=io.StringIO(), err=err, sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "add --force-live" in err.getvalue()
    assert [c[0] for c in api.calls] == ["create", "create"]
    assert not (tmp_path / "runners.ledger").exists()


def test_sweep_says_when_a_named_runner_was_already_absent(tmp_path):
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--runner", "cqa-rev-mistyped", "--force-live"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: FakeSprites(),
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "cqa-rev-mistyped: already absent, nothing deleted" in out.getvalue()


def test_sweep_exits_nonzero_when_it_cannot_verify_cleanup(tmp_path):
    api = FakeSprites(fail_on={"delete": BoundaryError("Sprites HTTP 500")})
    api.create("cqa-rev-stuck")
    (tmp_path / "runners.ledger").write_text("cqa-rev-stuck\n")
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--force-live"],
        env={}, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    assert "cqa-rev-stuck: destroy NOT verified" in out.getvalue()
    assert (tmp_path / "runners.ledger").read_text() == "cqa-rev-stuck\n"


@pytest.mark.parametrize(
    "name", ["not-ours", "cqa-rev-UPPER", "cqa-rev-a\nb", "cqa-rev-"]
)
def test_sweep_refuses_a_runner_name_it_would_not_manage(tmp_path, name):
    api = FakeSprites()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--runner", name],
        env={}, out=io.StringIO(), err=(err := io.StringIO()),
        sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "--runner must be a cqa-rev-* name" in err.getvalue()
    assert not (tmp_path / "runners.ledger").exists()
    assert api.calls == []


def test_sweep_refuses_to_run_while_a_review_holds_the_lock(tmp_path):
    from atlas_reviewer.ledger import single_review_lock

    api = FakeSprites()
    api.create("cqa-rev-live-review")
    (tmp_path / "runners.ledger").write_text("cqa-rev-live-review\n")
    out, err = io.StringIO(), io.StringIO()
    with single_review_lock(tmp_path / "review.lock"):
        code = cli.main(
            ["--state-dir", str(tmp_path), "sweep", "--force-live"],
            env={}, out=out, err=err, sprites_factory=lambda env: api,
        )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert api.live_names() == ("cqa-rev-live-review",)
    assert "delete" not in [c[0] for c in api.calls]
    assert "another review holds" in err.getvalue()
    code = cli.main(
        ["--state-dir", str(tmp_path), "sweep", "--force-live"],
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
    assert code == cli.EXIT_INCOMPLETE
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


def minting_github(monkeypatch, minted, github=FixtureGitHub):
    monkeypatch.setattr(
        cli, "AppInstallationTokens",
        lambda transport, clock, **kw: type("T", (), {"secrets": lambda self: (minted,)})(),
    )  # fmt: skip
    monkeypatch.setattr(cli, "GitHubClient", lambda transport, t: github(FIXTURE))


def test_review_telemetry_files_never_collide_and_a_lock_loser_writes_none(
    tmp_path, monkeypatch
):
    from atlas_reviewer.ledger import single_review_lock

    live_github(monkeypatch)
    monkeypatch.setattr(cli, "SystemClock", FakeClock)
    argv = ["--state-dir", str(tmp_path), "review", "--event", EVENT]
    kw = {"env": APP_ENV, "out": io.StringIO(), "sprites_factory": scripted_sprites}
    with single_review_lock(tmp_path / "review.lock"):
        err = io.StringIO()
        assert cli.main(argv, err=err, **kw) == cli.EXIT_USAGE
    assert "another review holds" in err.getvalue()
    assert not (tmp_path / "telemetry").exists()
    errs = [io.StringIO(), io.StringIO()]
    for e in errs:
        cli.main(argv, err=e, **kw)
    files = set((tmp_path / "telemetry").glob("review-*.jsonl"))
    assert len(files) == 2
    printed = {
        Path(line.rsplit(", ", 1)[1])
        for e in errs
        for line in e.getvalue().splitlines()
        if line.startswith("telemetry: ")
    }
    assert printed == files


# Minted values here are deliberately not token-shaped: only the credential
# registry, not a pattern, can catch them.
MINTED = "minted-installation-value-0123456789"


def test_minted_installation_tokens_are_scrubbed_from_stderr_and_telemetry(
    tmp_path, monkeypatch
):
    minted = MINTED

    class LeakyPull(FixtureGitHub):
        def get_pull(self, repo, number):
            raise NotFoundError(
                f"GitHub 404 for {minted} and {APP_ENV[cli.ENV_SPRITES_TOKEN]}"
            )

    minting_github(monkeypatch, minted, LeakyPull)
    events = tmp_path / "e.jsonl"
    err = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT, "--events", str(events)],
        env=APP_ENV, out=io.StringIO(), err=err, sprites_factory=scripted_sprites,
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    assert "GitHub 404 for" in err.getvalue()
    for leaked in (err.getvalue(), events.read_text()):
        assert minted not in leaked
        assert APP_ENV[cli.ENV_SPRITES_TOKEN] not in leaked


def test_the_probe_report_scrubs_minted_tokens_and_environment_credentials(
    tmp_path, monkeypatch
):
    minted = MINTED
    leak = f"Python 3.13.7 {APP_ENV[cli.ENV_SPRITES_TOKEN]}"
    # A pyenv version directory may be named anything of this shape, and the
    # trusted-python line prints it unscrubbed until the report scrub.
    resolved = f"{PYTHON_TAG}:{PYENV_VERSIONS}/{minted}/bin/python3:3.13.7"

    class Leaky(FakeSprites):
        def _answer(self, script, stdin):
            if "timeout -k 2 15 python3" in script:
                return leak, 0
            if f'echo "{PYTHON_TAG}:' in script:
                return resolved, 0
            return super()._answer(script, stdin)

    minting_github(monkeypatch, minted)
    api = Leaky.from_script(json.loads((FIXTURE / "runner-script.json").read_text()))
    events = tmp_path / "e.jsonl"
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--event", EVENT, "--events", str(events)],
        env=APP_ENV, out=out, err=io.StringIO(), sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    text = out.getvalue()
    assert "diagnostic bare python3 in the checkout: exit 0: Python 3.13.7 " in text
    assert "trusted python: /" in text and "(3.13.7)" in text
    for leaked in (text, events.read_text()):
        assert minted not in leaked
        assert APP_ENV[cli.ENV_SPRITES_TOKEN] not in leaked


def test_a_boundary_error_still_names_the_telemetry_file(tmp_path, monkeypatch):
    class NoPull(FixtureGitHub):
        def get_pull(self, repo, number):
            raise NotFoundError("GitHub 404")

    minting_github(monkeypatch, MINTED, NoPull)
    err = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT],
        env=APP_ENV, out=io.StringIO(), err=err, sprites_factory=scripted_sprites,
    )  # fmt: skip
    assert code == cli.EXIT_BOUNDARY
    (events_file,) = (tmp_path / "telemetry").glob("review-*.jsonl")
    count = len(jsonl(events_file))
    assert count > 0
    assert f"telemetry: {count} event(s), {events_file}\n" in err.getvalue()


@pytest.mark.parametrize("fails", [False, True])
def test_the_printed_telemetry_path_is_scrubbed(tmp_path, fails):
    secret = "sprites-secret-value-0123456789"
    target = tmp_path / f"run-{secret}" / "events.jsonl"
    broken = ["--fixtures", str(tmp_path / "missing")] if fails else []
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--events", str(target), *broken,
        env={cli.ENV_SPRITES_TOKEN: secret},
    )  # fmt: skip
    assert code == (cli.EXIT_USAGE if fails else cli.EXIT_INCOMPLETE)
    assert "telemetry: " in err
    assert secret not in err


def test_an_error_before_telemetry_starts_names_no_telemetry_file(tmp_path):
    _, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--max-model-calls", "9",
    )  # fmt: skip
    assert "telemetry:" not in err


def test_an_events_file_another_run_holds_is_refused_and_reusable_after(tmp_path):
    target = tmp_path / "shared.jsonl"
    argv = ("review", "--event", EVENT, "--dry-run", "--events", str(target))
    with cli._claimed(target):
        code, out, err = run_cli("--state-dir", str(tmp_path / "a"), *argv)
    assert code == cli.EXIT_USAGE
    assert "is in use by another run" in err
    assert not target.exists()
    assert out == ""
    for state in ("b", "c"):
        code, _, _ = run_cli("--state-dir", str(tmp_path / state), *argv)
        assert code == cli.EXIT_INCOMPLETE
    assert jsonl(target)


def test_a_dry_run_writes_telemetry_only_when_asked(tmp_path):
    run_cli("--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run")
    assert not (tmp_path / "telemetry").exists()
    target = tmp_path / "events.jsonl"
    code, _, _ = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--events", str(target),
    )  # fmt: skip
    assert code == cli.EXIT_INCOMPLETE
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


def test_probe_runner_redacts_its_report(tmp_path):
    tarball = tmp_path / "checkout.tar.gz"
    tarball.write_bytes(FixtureGitHub(FIXTURE).get_tarball("o/r", HEAD))
    credential = "sprites-token-value-0123456789"
    leak = f"3 {credential} AKIAIOSFODNN7EXAMPLE"
    api = FakeSprites.from_script(
        {"exec": [{"match": "tar -xzf", "stdout": "", "exit_code": 0},
                  {"match": "echo posix-sh", "stdout": "posix-sh", "exit_code": 0},
                  {"match": "find .", "stdout": leak, "exit_code": 0}]}
    )  # fmt: skip
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "probe-runner", "--sequence", "review",
         "--tarball", str(tarball)],
        env={cli.ENV_SPRITES_TOKEN: credential}, out=out, err=io.StringIO(),
        sprites_factory=lambda env: api,
    )  # fmt: skip
    assert code == cli.EXIT_OK
    text = out.getvalue()
    assert "tool source-file-count (posix-sh): exit 0" in text
    assert credential not in text
    assert "AKIAIOSFODNN7EXAMPLE" not in text


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
    tarball.write_bytes(SOURCE_TARBALL)
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


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
@pytest.mark.parametrize(
    "command,flag",
    [
        (("review", "--event", EVENT, "--dry-run"), "--first-frame-seconds"),
        (("review", "--event", EVENT, "--dry-run"), "--deadline-seconds"),
        (("probe-runner",), "--first-frame-seconds"),
        (("probe-runner",), "--deadline-seconds"),
    ],
)
def test_runner_timings_must_be_positive_and_finite(
    tmp_path, value, command, flag, capsys
):
    with pytest.raises(SystemExit) as info:
        cli.main(
            ["--state-dir", str(tmp_path), *command, flag, value],
            env={}, out=io.StringIO(), err=io.StringIO(),
        )  # fmt: skip
    assert info.value.code == 2
    assert "positive number of seconds" in capsys.readouterr().err


def test_review_config_refuses_a_non_positive_first_frame_window():
    from atlas_reviewer.controller import ReviewConfig

    with pytest.raises(ValueError, match="first-frame"):
        ReviewConfig(first_frame_s=0)


def test_a_github_list_cannot_be_named_as_expected_evidence(tmp_path):
    code, _, err = run_cli(
        "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run",
        "--expect", "listing:(all check runs)",
    )  # fmt: skip
    assert code == cli.EXIT_USAGE
    assert "--expect must be KIND:NAME" in err
    assert "'listing'" not in err.split("KIND in", 1)[1]


def openrouter_review(tmp_path, monkeypatch, reply, *extra):
    monkeypatch.setattr(
        cli, "AppInstallationTokens",
        lambda transport, clock, **kw: type("T", (), {"secrets": lambda self: ()})(),
    )  # fmt: skip
    monkeypatch.setattr(
        cli, "GitHubClient", lambda transport, t: FixtureGitHub(FIXTURE)
    )
    out = io.StringIO()
    code = cli.main(
        ["--state-dir", str(tmp_path), "review", "--event", EVENT,
         "--provider", "openrouter", "--allow-live-inference", *extra],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"}, out=out, err=io.StringIO(),
        sprites_factory=scripted_sprites,
        openrouter_factory=lambda key, limits: StubOpenRouter(key, reply=reply),
    )  # fmt: skip
    return code, out.getvalue()


def test_a_complete_approving_review_exits_ok_and_reports_its_event(
    tmp_path, monkeypatch
):
    draft_path = tmp_path / "draft.md"
    code, out = openrouter_review(
        tmp_path, monkeypatch, "Fine.\n\nReview event: APPROVE",
        "--out", str(draft_path),
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert "review event: APPROVE; coverage_complete=true; unreviewed_files=0" in out
    first = draft_path.read_text().split("\n", 1)[0]
    assert '"review_event": "APPROVE"' in first
    assert '"coverage_complete": true' in first


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("APPROVE", cli.EXIT_OK),
        ("COMMENT", cli.EXIT_OK),
        ("REQUEST_CHANGES", cli.EXIT_CHANGES_REQUESTED),
    ],
)
def test_a_complete_review_exits_by_its_event(tmp_path, monkeypatch, event, expected):
    code, out = openrouter_review(
        tmp_path, monkeypatch, f"Notes.\n\nReview event: {event}",
        "--out", str(tmp_path / "draft.md"),
    )  # fmt: skip
    assert code == expected
    assert f"review event: {event}; coverage_complete=true" in out


def test_requested_changes_with_incomplete_coverage_exit_incomplete():
    from atlas_reviewer.verdict import FileCoverage, ReviewEvent, decide

    incomplete = FileCoverage(
        2, unknown="the diff names 1 file(s) but GitHub reports 2"
    )
    verdict = decide(ReviewEvent.REQUEST_CHANGES, incomplete)
    assert cli.review_exit(verdict) == cli.EXIT_INCOMPLETE
    assert cli.review_exit(decide(ReviewEvent.REQUEST_CHANGES, FileCoverage(1))) == (
        cli.EXIT_CHANGES_REQUESTED
    )


def test_a_held_review_lock_exits_with_the_usage_code(tmp_path):
    from atlas_reviewer.ledger import single_review_lock

    with single_review_lock(tmp_path / "review.lock"):
        code, out, err = run_cli(
            "--state-dir", str(tmp_path), "review", "--event", EVENT, "--dry-run"
        )
    assert code == cli.EXIT_USAGE == 2
    assert "another review holds" in err
    assert out == ""


def test_the_exit_codes_are_the_documented_numbers():
    assert (
        cli.EXIT_OK, cli.EXIT_USAGE, cli.EXIT_BOUNDARY, cli.EXIT_INCOMPLETE,
        cli.EXIT_CHANGES_REQUESTED,
    ) == (0, 2, 3, 4, 5)  # fmt: skip


def _stopped_no_byok_review(tmp_path, monkeypatch, usage, *, first=None):
    """A two-part diff. The first response is the one under test; a second
    reply is queued and must not be sent. `first` replaces the completion
    built from `usage`."""
    from atlas_reviewer.openrouter import OpenRouterProvider

    from .test_openrouter import OpenRouterFake, completion, key_status, reply

    body = "+line\n" * 400
    wide = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,400 @@\n"
        + body
        + "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1,400 @@\n"
        + body
    )

    class WideDiff(FixtureGitHub):
        def get_pull_diff(self, repo, number):
            self.calls.append(("get_pull_diff", repo, str(number)))
            return wide

    held = {}

    def factory(key, limits):
        opening = (
            first
            if first is not None
            else reply(completion("Reviewed.\n\nReview event: APPROVE", usage=usage))
        )
        # The queued reply is an explicit non-BYOK completion, so a refusal
        # that is swallowed becomes a second model call and a written draft.
        continued = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cost": "0.01",
            "is_byok": False,
        }
        fake = OpenRouterFake(
            opening,
            reply(completion("Reviewed.\n\nReview event: APPROVE", usage=continued)),
            key=reply(key_status(include_byok_in_limit=False)),
        )
        held["provider"] = OpenRouterProvider(fake, key, limits=limits)
        held["fake"] = fake
        return held["provider"]

    monkeypatch.setattr(
        cli,
        "AppInstallationTokens",
        lambda transport, clock, **kw: type("T", (), {"secrets": lambda self: ()})(),
    )
    monkeypatch.setattr(cli, "GitHubClient", lambda transport, t: WideDiff(FIXTURE))
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path),
            "review",
            "--event",
            EVENT,
            "--provider",
            "openrouter",
            "--allow-live-inference",
            "--depth",
            "triage",
            "--max-model-calls",
            "2",
            "--diff-chars-per-call",
            "1000",
        ],
        env={**APP_ENV, cli.ENV_OPENROUTER_KEY: "sk-or-v1-x"},
        out=out,
        err=err,
        sprites_factory=scripted_sprites,
        openrouter_factory=factory,
    )
    return code, out.getvalue(), err.getvalue(), held


def test_a_byok_response_in_no_byok_mode_stops_the_review(tmp_path, monkeypatch):
    """The first response is BYOK, so the review exits 3 and the second
    model call is never sent. A swallowed error would send it and exit 4.
    The reported upstream charge is still counted."""
    from decimal import Decimal

    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": True,
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    code, out, err, held = _stopped_no_byok_review(tmp_path, monkeypatch, usage)
    assert code == cli.EXIT_BOUNDARY == 3
    assert out == ""
    assert "does not count BYOK spend" in err
    assert "usage.is_byok is true" in err
    assert len(held["fake"].chat_requests()) == 1
    assert held["provider"].budget.committed_usd() == Decimal("1.31")


def test_an_unparseable_response_in_no_byok_mode_stops_the_review(
    tmp_path, monkeypatch
):
    """An HTTP 200 that cannot be parsed does not say the call was non-BYOK.
    The review exits 3 after that one request. A plain boundary error would
    continue to the next part."""
    from .test_openrouter import reply

    code, out, err, held = _stopped_no_byok_review(
        tmp_path, monkeypatch, None, first=reply(b"<html>")
    )
    assert code == cli.EXIT_BOUNDARY == 3
    assert out == ""
    assert "could not be parsed, so is_byok could not be checked" in err
    assert len(held["fake"].chat_requests()) == 1
    assert held["provider"].budget.calls[0].actual_usd is None


def test_a_missing_is_byok_field_stops_the_review(tmp_path, monkeypatch):
    """Fail closed: a response that does not say whether it was BYOK is not
    a review. The upstream charge is unknown, so the reservation stands."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": "0.05"}
    code, out, err, held = _stopped_no_byok_review(tmp_path, monkeypatch, usage)
    assert code == cli.EXIT_BOUNDARY == 3
    assert out == ""
    assert "no is_byok field" in err
    assert len(held["fake"].chat_requests()) == 1
    assert held["provider"].budget.calls[0].actual_usd is None


def test_a_review_whose_model_call_failed_exits_incomplete_and_never_approves(
    tmp_path, monkeypatch
):
    code, out = openrouter_review(
        tmp_path, monkeypatch, BoundaryError("HTTP 503 after retries")
    )
    assert code == cli.EXIT_INCOMPLETE
    first = out.split("\n", 1)[0]
    assert '"review_event": "COMMENT"' in first
    assert '"coverage_complete": false' in first
    assert "> **REVIEW INCOMPLETE -- not approvable.**" in out
