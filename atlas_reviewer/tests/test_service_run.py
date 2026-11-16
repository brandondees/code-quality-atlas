# SPDX-License-Identifier: MIT
"""The service runs the selected mode's review command and reads its draft."""

import io
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from atlas_reviewer import cli
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.service_post import comment_payload, post_key, render_comment
from atlas_reviewer.service_run import (
    APP_KEY_ENV,
    CLEANUP_WAIT_S,
    MODE_AGENTIC,
    MODE_ONESHOT,
    READ_TOKEN_ENV,
    REVIEW_DEADLINE_S,
    SERVICE_DEADLINE_ENV,
    SERVICE_MODE_ENV,
    WEBHOOK_SECRET_ENV,
    ReviewRun,
    RunConfig,
    _stop,
    child_env,
    make_runner,
    review_argv,
    run_dir,
    run_process,
    section,
    service_deadline,
    service_mode,
    summarize_draft,
)

from .helpers import FIXTURE
from .helpers import HEAD as FIXTURE_HEAD

SECRET = "webhook-secret-value"
SHA = "c" * 40
REPO = "brandondees/code-quality-atlas"
DRAFT = """\
<!-- atlas-review-status: {"review_event": "APPROVE", "proposed_event": "APPROVE", "coverage_complete": false, "changed_files": 2, "unreviewed_files": 1} -->
Not reviewed in full: `"src/a.py"`

## Review lenses

| Lens | Status | Characters | Chosen as | Why not run |
| --- | --- | --- | --- | --- |
| tracing-correctness-and-invariants | run whole | 10 | critical |  |
| reviewing-concurrency-and-async | NOT RUN | 10 | critical | over the character budget |

## Controller notes

- Diff coverage after the model calls: PARTIAL. 1 of 1 file(s) in full.

## Omissions and limits hit

| Source | Limit | Detail |
| --- | --- | --- |
| pull request diff | too large for one review pass | kept 1 |

## Model usage

- reserved $1.00 actual $0.10
"""


def test_the_run_directory_names_the_repository():
    path = run_dir(Path("state"), PrEvent("alice/widgets", 7, "a" * 40))
    assert path.name.startswith("alice-widgets-7-")


def test_the_child_does_not_receive_root_as_home():
    env = child_env({"HOME": "/root", "PATH": "/usr/bin"})
    assert env["HOME"] == "/home/atlas"
    assert "/root" not in env.values()


def test_the_child_receives_only_the_allowlist():
    env = child_env(
        {
            WEBHOOK_SECRET_ENV: "s" * 16,
            APP_KEY_ENV: "pem-secret-value",
            "ATLAS_SPRITES_TOKEN": "sprite",
            "ATLAS_OPENROUTER_API_KEY": "sk-or",
            "FLY_API_TOKEN": "fly-token-value",
            "ATLAS_GITHUB_APP_ID": "5648875",
            "PATH": "/usr/bin",
        },
        token="ghs_read",
    )
    assert env == {
        "ATLAS_SPRITES_TOKEN": "sprite",
        "ATLAS_OPENROUTER_API_KEY": "sk-or",
        "PATH": "/usr/bin",
        READ_TOKEN_ENV: "ghs_read",
    }


def test_the_child_process_starts_without_the_app_key(tmp_path):
    seen: dict[str, dict[str, str]] = {}

    def popen(argv, env, stdout, stderr):
        seen["env"] = dict(env)
        return _Proc(3)

    parent = {
        APP_KEY_ENV: "pem-secret-value",
        "ATLAS_OPENROUTER_API_KEY": "sk-or-secret",
        "ATLAS_SPRITES_TOKEN": "sprite-secret",
        WEBHOOK_SECRET_ENV: "webhook-secret-value",
        "FLY_API_TOKEN": "fly-token-value",
    }
    runner = make_runner(
        RunConfig("offline", False, tmp_path),
        parent,
        popen=popen,
        read_token=lambda _env, _event: ("ghs_read", ""),
    )
    result = runner(PrEvent(REPO, 7, SHA), threading.Event())
    assert result.ok is False
    child = seen["env"]
    assert APP_KEY_ENV not in child
    assert "pem-secret-value" not in child.values()
    assert WEBHOOK_SECRET_ENV not in child
    assert child["ATLAS_OPENROUTER_API_KEY"] == "sk-or-secret"
    assert child["ATLAS_SPRITES_TOKEN"] == "sprite-secret"
    assert child[READ_TOKEN_ENV] == "ghs_read"
    assert "FLY_API_TOKEN" not in child


def test_the_child_receives_the_route_settings_and_the_agentic_limits():
    from atlas_reviewer.agentic_config import ENV as LIMIT_ENV
    from atlas_reviewer.openrouter import (
        ENV_ALLOW_SAFETY_RETENTION,
        ENV_KEY_CEILING_USD,
        ENV_MODEL,
        ENV_PROVIDERS,
        ENV_REQUIRE_ZDR,
    )

    parent = {
        ENV_MODEL: "z-ai/glm-5.3",
        ENV_PROVIDERS: "amazon-bedrock",
        ENV_ALLOW_SAFETY_RETENTION: "true",
        ENV_REQUIRE_ZDR: "false",
        ENV_KEY_CEILING_USD: "4",
        "ATLAS_MAX_CALLS": "4",
        "ATLAS_MAX_TURNS": "4",
        "ATLAS_MAX_INPUT_TOKENS": "8000",
        "ATLAS_MAX_OUTPUT_TOKENS": "65536",
        "ATLAS_REASONING_MAX_TOKENS": "1000",
        "ATLAS_RESERVATION_USD": "1",
        "ATLAS_LENS_WALL_S": "60",
        "ATLAS_REVIEW_WALL_S": "120",
        "ATLAS_PER_LENS_CALLS": "50",
        "ATLAS_PER_LENS_USD": "5",
        "ATLAS_REVIEW_CEILING_USD": "10",
        "ATLAS_NOT_A_CHILD_SETTING": "dropped",
        "FLY_API_TOKEN": "fly-token-value",
        APP_KEY_ENV: "pem-secret-value",
        WEBHOOK_SECRET_ENV: "s" * 16,
        "PATH": "/usr/bin",
    }
    env = child_env(parent, token="ghs_read")
    assert env[ENV_MODEL] == "z-ai/glm-5.3"
    assert env[ENV_PROVIDERS] == "amazon-bedrock"
    assert env[ENV_ALLOW_SAFETY_RETENTION] == "true"
    assert env[ENV_REQUIRE_ZDR] == "false"
    assert env[ENV_KEY_CEILING_USD] == "4"
    for name in LIMIT_ENV.values():
        assert env.get(name) == parent.get(name)
    assert env["ATLAS_PER_LENS_CALLS"] == "50"
    assert env["ATLAS_PER_LENS_USD"] == "5"
    assert env["ATLAS_REVIEW_CEILING_USD"] == "10"
    assert "ATLAS_NOT_A_CHILD_SETTING" not in env
    assert "FLY_API_TOKEN" not in env
    assert APP_KEY_ENV not in env
    assert WEBHOOK_SECRET_ENV not in env
    assert env["PATH"] == "/usr/bin"
    assert env[READ_TOKEN_ENV] == "ghs_read"


def test_a_stop_waits_out_sprite_cleanup_before_sigkill():
    import inspect

    from atlas_reviewer.runner import CLEANUP_BUDGET_S
    from atlas_reviewer.sprites_api import SpritesClient

    window = inspect.signature(SpritesClient.__init__).parameters["timeout_s"].default
    assert CLEANUP_WAIT_S >= CLEANUP_BUDGET_S + window

    class Proc:
        def __init__(self) -> None:
            self.killed = False
            self.waits: list[float] = []
            self._done = False

        def poll(self) -> int | None:
            return 0 if self._done else None

        def send_signal(self, _sig: int) -> None:
            return None

        def wait(self, timeout: float) -> int:
            self.waits.append(timeout)
            if not self._done and timeout < CLEANUP_BUDGET_S + window:
                raise subprocess.TimeoutExpired("review", timeout)
            self._done = True
            return 0

        def kill(self) -> None:
            self.killed = True
            self._done = True

    proc = Proc()
    _stop(proc)  # type: ignore[arg-type]
    assert proc.killed is False
    assert proc.waits[0] >= CLEANUP_BUDGET_S + window


def test_the_child_does_not_receive_the_app_private_key():
    env = child_env(
        {
            WEBHOOK_SECRET_ENV: "s" * 16,
            APP_KEY_ENV: "pem-secret-value",
            "ATLAS_SPRITES_TOKEN": "sprite",
        },
        token="ghs_read",
    )
    assert APP_KEY_ENV not in env
    assert WEBHOOK_SECRET_ENV not in env
    assert env[READ_TOKEN_ENV] == "ghs_read"
    assert env["ATLAS_SPRITES_TOKEN"] == "sprite"


def test_a_bad_app_id_does_not_start_the_child_or_echo_the_key(tmp_path):
    started: list[object] = []

    def popen(*_args, **_kwargs):
        started.append(True)
        return _Proc(0)

    runner = make_runner(
        RunConfig("offline", False, tmp_path),
        {APP_KEY_ENV: "super-secret-pem", "ATLAS_GITHUB_APP_ID": "nope"},
        popen=popen,
    )
    result = runner(PrEvent(REPO, 7, SHA), threading.Event())
    assert started == []
    assert result.ok is False
    assert "super-secret-pem" not in result.error


def test_the_mode_selects_the_child_command(tmp_path):
    oneshot = review_argv(
        RunConfig("offline", False, tmp_path, MODE_ONESHOT), tmp_path / "run"
    )
    agentic = review_argv(
        RunConfig("offline", False, tmp_path, MODE_AGENTIC), tmp_path / "run"
    )
    for argv in (oneshot, agentic):
        assert argv[1:4] == ["-m", "atlas_reviewer", "--state-dir"]
        assert "--provider" in argv and "offline" in argv
        assert "APPROVE" not in argv and "REQUEST_CHANGES" not in argv
    assert "review" in oneshot and "agentic-review" not in oneshot
    assert "agentic-review" in agentic and "review" not in agentic
    event_at = oneshot.index("--event")
    out_at = oneshot.index("--out")
    events_at = oneshot.index("--events")
    assert agentic[event_at + 1] == oneshot[event_at + 1]
    assert agentic[out_at + 1] == oneshot[out_at + 1]
    assert agentic[events_at + 1] == oneshot[events_at + 1]
    live = review_argv(
        RunConfig("openrouter", True, tmp_path, MODE_ONESHOT), tmp_path / "run"
    )
    assert live[-1] == "--allow-live-inference"
    live_agentic = review_argv(
        RunConfig("openrouter", True, tmp_path, MODE_AGENTIC), tmp_path / "run"
    )
    assert live_agentic[-1] == "--allow-live-inference"
    env = child_env({WEBHOOK_SECRET_ENV: SECRET, "ATLAS_SPRITES_TOKEN": "sprite"})
    assert WEBHOOK_SECRET_ENV not in env
    assert env["ATLAS_SPRITES_TOKEN"] == "sprite"


def test_the_default_mode_is_agentic_and_an_unknown_mode_fails_closed():
    assert service_mode({}) == MODE_AGENTIC
    assert service_mode({SERVICE_MODE_ENV: "oneshot"}) == MODE_ONESHOT
    assert service_mode({SERVICE_MODE_ENV: "agentic"}) == MODE_AGENTIC
    with pytest.raises(ValueError) as refused:
        service_mode({SERVICE_MODE_ENV: "fast"})
    assert "ATLAS_SERVICE_MODE" in str(refused.value)
    assert "fast" in str(refused.value)
    with pytest.raises(ValueError):
        RunConfig("offline", False, Path("state"), "fast")


def test_the_service_deadline_is_configurable_and_bounded():
    assert service_deadline({}) == REVIEW_DEADLINE_S
    assert service_deadline({SERVICE_DEADLINE_ENV: "3600"}) == 3600.0
    for raw in ("0", "-5", "30", "abc", "20000", "nan", "inf"):
        with pytest.raises(ValueError) as refused:
            service_deadline({SERVICE_DEADLINE_ENV: raw})
    assert SERVICE_DEADLINE_ENV in str(refused.value)


def test_the_agentic_runner_runs_the_agentic_command_with_the_limits(tmp_path):
    seen: dict[str, object] = {}

    def popen(argv, env, stdout, stderr):
        seen["argv"] = list(argv)
        seen["env"] = dict(env)
        Path(argv[argv.index("--out") + 1]).write_text(DRAFT, encoding="utf-8")
        return _Proc(0)

    parent = {
        "ATLAS_PER_LENS_CALLS": "50",
        "ATLAS_PER_LENS_USD": "5",
        "ATLAS_REVIEW_CEILING_USD": "10",
        WEBHOOK_SECRET_ENV: SECRET,
    }
    runner = make_runner(
        RunConfig("offline", False, tmp_path, MODE_AGENTIC),
        parent,
        popen=popen,
        read_token=lambda _env, _event: ("", ""),
    )
    result = runner(PrEvent(REPO, 7, SHA), threading.Event())
    assert result.ok
    argv = seen["argv"]
    assert isinstance(argv, list)
    assert "agentic-review" in argv and "review" not in argv
    child = seen["env"]
    assert isinstance(child, dict)
    assert child["ATLAS_REVIEW_CEILING_USD"] == "10"
    assert child["ATLAS_PER_LENS_CALLS"] == "50"
    assert WEBHOOK_SECRET_ENV not in child


def test_an_agentic_fixture_run_posts_a_comment_listing_the_planned_lenses(
    tmp_path, monkeypatch
):
    """The parity gate, on fakes: the shipped fixture PR reviewed by the
    real agentic dry run. The posted COMMENT lists every planned lens as
    run, no unexpected NOT RUN, and the coverage note; no live model
    call, no network, no secret."""
    event = PrEvent("example-org/example-app", 42, FIXTURE_HEAD)

    def popen(argv, env, stdout, stderr):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(
            [*argv[3:], "--dry-run", "--fixtures", str(FIXTURE)],
            env={},
            out=out,
            err=err,
        )
        return _Proc(code)

    # The dry run binds a Unix socket under the state directory; a
    # relative state root keeps that path inside the 108-character
    # AF_UNIX bound that the pytest tmp path alone would blow.
    monkeypatch.chdir(tmp_path)
    runner = make_runner(
        RunConfig("offline", False, Path("."), MODE_AGENTIC),
        {},
        popen=popen,
    )
    result = runner(event, threading.Event())
    assert result.ok, result.error
    report = result.report
    assert report is not None
    draft = (run_dir(Path("."), event) / "draft.md").read_text(encoding="utf-8")
    planned = _planned_lenses(draft)
    assert planned, "the fixture run selected no lens"
    assert set(report.lenses_run) == planned
    assert report.recommended_event == "REQUEST_CHANGES"
    assert "read in full" in report.files_note
    body = render_comment(report, post_key(event), lambda item: item)
    payload = comment_payload(event.head_sha, body)
    assert payload["event"] == "COMMENT"
    run_section = body.split("## Lenses run", 1)[1].split("## Lenses not run", 1)[0]
    for name in planned:
        assert name in run_section
    assert "## Lenses not run\n\nNone." in body
    assert "was read in full" in body


def _planned_lenses(draft: str) -> set[str]:
    """The lenses the agentic draft's ledger shows as run."""
    found = set()
    for line in section(draft, "Lens coverage (attestation ledger)").splitlines():
        match = re.match(r"^- L\d+ (.+?): \*\*(.+?)\*\*", line)
        if match and match.group(2) in {"clean", "partial"}:
            found.add(match.group(1))
    return found


def test_an_agentic_draft_reports_selection_stops_and_cost():
    status = json.dumps(
        {
            "mode": "agentic",
            "review_event": "COMMENT",
            "proposed_event": "APPROVE",
            "coverage_complete": False,
            "changed_files": 3,
            "unreviewed_files": 1,
            "limit_stop": {
                "limit": "review_wall_s",
                "configured": "3600",
                "observed": "3600",
                "setting": "--review-wall-seconds or ATLAS_REVIEW_WALL_S",
            },
        }
    )
    draft = (
        f"<!-- atlas-review-status: {status} -->\n"
        "> **REVIEW INCOMPLETE -- not approvable.** Review event: COMMENT. "
        "Lens coverage is not complete (other-lens: failed), and 1 changed "
        'file not read in full: `"src/b.py"`.\n'
        "\n"
        "## Lens selection\n"
        "\n"
        '- NOT RUN: `"reviewing-concurrency-and-async"` (not picked)\n'
        "\n"
        "## Findings (verified quotes only)\n"
        "\n"
        "No verified findings.\n"
        "\n"
        "## Context omissions\n"
        "\n"
        "- pull request diff (character budget): kept 1 of 2\n"
        "\n"
        "## Lens coverage (attestation ledger)\n"
        "\n"
        "- L1 tracing-correctness-and-invariants: **clean**; body sha256 ab12\n"
        "- L2 other-lens: **failed**; attestation: not_delivered\n"
        "\n"
        "Model calls: 12; committed: $0.34.\n"
        "the derived reservation was clamped to the $10 ceiling\n"
    )
    report = summarize_draft(draft)
    assert report.lenses_run == ("tracing-correctness-and-invariants",)
    assert report.lenses_not_run == (
        "reviewing-concurrency-and-async: not picked",
        "other-lens",
    )
    assert "1 of 3" in report.files_note and "not read in full" in report.files_note
    assert report.files_not_read == ("src/b.py",)
    assert report.limit_stops[0] == (
        "review_wall_s stopped the review: configured 3600, observed 3600. "
        "Change it with --review-wall-seconds or ATLAS_REVIEW_WALL_S."
    )
    assert "pull request diff (character budget): kept 1 of 2" in report.limit_stops
    assert report.limit_stops[-1] == (
        "the derived reservation was clamped to the $10 ceiling"
    )
    assert report.cost_lines == ("Model calls: 12; committed: $0.34.",)
    assert report.recommended_event == "COMMENT"


def test_a_draft_reports_lenses_limits_cost_and_files():
    report = summarize_draft(DRAFT)
    assert report.lenses_run == ("tracing-correctness-and-invariants",)
    assert report.lenses_not_run == (
        "reviewing-concurrency-and-async: over the character budget",
    )
    assert report.files_not_read == ("src/a.py",)
    assert "PARTIAL" in report.files_note
    assert report.limit_stops == (
        "pull request diff | too large for one review pass | kept 1",
    )
    assert report.cost_lines == ("reserved $1.00 actual $0.10",)
    assert report.recommended_event == "APPROVE"
    empty = summarize_draft("no sections\n")
    assert empty.lenses_run == ()
    assert empty.files_note == "The draft has no diff-coverage note."


def test_cancel_stops_the_child(tmp_path):
    cancel = threading.Event()

    def sleeper(seconds):
        cancel.set()

    code = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        os.environ,
        cancel,
        tmp_path / "stderr.txt",
        sleeper=sleeper,
        poll_s=0.01,
    )
    assert code is None


def test_exits_0_4_and_5_are_postable_and_3_is_not(tmp_path):
    config = RunConfig("offline", False, tmp_path)
    event = PrEvent(REPO, 7, SHA)

    def popen_for(code):
        def popen(argv, env, stdout, stderr):
            Path(argv[argv.index("--out") + 1]).write_text(DRAFT, encoding="utf-8")
            return _Proc(code)

        return popen

    for code in (0, 4, 5):
        result = make_runner(config, {}, popen=popen_for(code))(
            event, threading.Event()
        )
        assert result.ok, code
        assert result.report is not None
    failed = make_runner(config, {}, popen=popen_for(3))(event, threading.Event())
    assert failed.ok is False
    assert "exited 3" in failed.error


def test_the_child_is_stopped_at_the_deadline(tmp_path):
    clock = {"t": 0.0}

    def now():
        clock["t"] += 1000.0
        return clock["t"]

    result = make_runner(
        RunConfig("offline", False, tmp_path),
        {},
        popen=lambda *args, **kwargs: _Proc(None),
        sleeper=lambda _seconds: None,
        deadline_s=1.0,
        clock=now,
    )(PrEvent(REPO, 7, SHA), threading.Event())
    assert result.ok is False
    assert result.report is None
    assert result.error == "review deadline"


def test_a_finished_child_becomes_a_report_and_a_failure_does_not(tmp_path):
    config = RunConfig("offline", False, tmp_path)
    event = PrEvent(REPO, 7, SHA)

    def popen(argv, env, stdout, stderr):
        assert WEBHOOK_SECRET_ENV not in env
        out = Path(argv[argv.index("--out") + 1])
        out.write_text(DRAFT, encoding="utf-8")
        return _Proc(0)

    runner = make_runner(config, {WEBHOOK_SECRET_ENV: SECRET}, popen=popen)
    done = runner(event, threading.Event())
    assert done.ok
    assert done.report is not None
    assert done.report.recommended_event == "APPROVE"

    def fail(argv, env, stdout, stderr):
        return _Proc(3)

    failed = make_runner(config, {}, popen=fail)(event, threading.Event())
    assert failed == ReviewRun(False, error="review exited 3: ")


class _Proc:
    def __init__(self, code: int) -> None:
        self._code = code
        self._polls = 0

    def poll(self):
        self._polls += 1
        if self._polls > 1:
            return self._code
        return None

    def send_signal(self, signum):
        return None

    def kill(self):
        return None

    def wait(self, timeout=None):
        return self._code
