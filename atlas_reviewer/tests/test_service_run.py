# SPDX-License-Identifier: MIT
"""The service runs the selected mode's review command and reads its draft."""

import argparse
import dataclasses
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
from atlas_reviewer.attestation import AttemptOutcome, Attestation, CheckedFinding
from atlas_reviewer.coordinator import LensResult, render_draft, synthesize
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.lens_contract import (
    Attribution,
    Finding,
    LineRange,
    Route,
    Severity,
    Valence,
)
from atlas_reviewer.quotes import QuoteSource
from atlas_reviewer.redact import Redactor
from atlas_reviewer.service import ServiceError, config_from_env
from atlas_reviewer.service_post import comment_payload, post_key, render_comment
from atlas_reviewer.service_run import (
    APP_KEY_ENV,
    CLEANUP_WAIT_S,
    MAX_SERVICE_DEADLINE_S,
    MODE_AGENTIC,
    MODE_ONESHOT,
    READ_TOKEN_ENV,
    REVIEW_DEADLINE_S,
    SERVICE_DEADLINE_ENV,
    SERVICE_MODE_ENV,
    WEBHOOK_SECRET_ENV,
    ReviewRun,
    RunConfig,
    _read_token,
    _stop,
    apply_severity_floor,
    child_env,
    finding_class,
    make_runner,
    review_argv,
    round_log_path,
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


def test_the_child_env_is_enough_for_the_agentic_command_to_reach_github(
    monkeypatch,
):
    """The boundary between the service parent and the review child: the
    parent passes one read-only installation token and no App credentials,
    and the agentic command the child runs must wire its GitHub client
    from exactly that env. The first live agentic run died here, demanding
    the App id the child must never hold."""
    parent = {
        "ATLAS_OPENROUTER_API_KEY": "sk-or",
        "ATLAS_SPRITES_TOKEN": "sprite",
        "PATH": "/usr/bin",
    }
    env = child_env(parent, token="ghs_read")
    seen = {}

    class Client:
        def __init__(self, _transport, tokens):
            seen["tokens"] = tokens

    monkeypatch.setattr(cli, "GitHubClient", Client)
    cli._live_github(
        argparse.Namespace(include_issues=False),
        env,
        PrEvent(REPO, 7, SHA),
        cli._Credentials(env),
    )
    assert isinstance(seen["tokens"], cli._FixedToken)
    assert seen["tokens"].token() == "ghs_read"


def test_the_agentic_command_without_the_parent_token_refuses_clearly(monkeypatch):
    """A parent that failed to mint and pass the token leaves the child
    with no GitHub credential at all. The agentic command then fails at
    boot with the same clear usage error a standalone run without App
    credentials gets -- naming the App id, the credential only the
    standalone path holds -- instead of starting with broken wiring."""
    env = child_env({"ATLAS_SPRITES_TOKEN": "sprite", "PATH": "/usr/bin"})
    monkeypatch.setattr(
        cli, "AppInstallationTokens", lambda *a, **k: pytest.fail("minted")
    )
    with pytest.raises(cli.UsageError) as raised:
        cli._live_github(
            argparse.Namespace(include_issues=False),
            env,
            PrEvent(REPO, 7, SHA),
            cli._Credentials(env),
        )
    assert "ATLAS_GITHUB_APP_ID" in str(raised.value)


def test_the_read_token_mints_issues_read_too(monkeypatch):
    """The parent's mint includes issues read. The mint happens before the
    child exists and `review_argv` builds no --include-issues flag a
    conditional mint could key on, so the grant rides along on every
    mint; the token stays read-only over the one repository."""
    seen = {}

    class Tokens:
        def __init__(self, _transport, _clock, **kwargs):
            seen.update(kwargs)

        def token(self):
            return "ghs_read"

    monkeypatch.setattr("atlas_reviewer.github_auth.AppInstallationTokens", Tokens)
    token, error = _read_token(
        {
            APP_KEY_ENV: "pem-secret-value",
            "ATLAS_GITHUB_APP_ID": "5648875",
            "ATLAS_GITHUB_INSTALLATION_ID": "12345",
        },
        PrEvent(REPO, 7, SHA),
    )
    assert (token, error) == ("ghs_read", "")
    assert seen["permissions"] == {
        "contents": "read",
        "checks": "read",
        "actions": "read",
        "pull_requests": "read",
        "issues": "read",
    }


def test_a_failed_mint_names_the_permissions_it_asked_for(monkeypatch):
    """A mint refused by GitHub is self-diagnosing: the error names every
    read permission the mint requested and hints that the installation
    may be missing one, and it never carries the key."""

    class Refusing:
        def __init__(self, *a, **k):
            raise RuntimeError("403 from the installation")

    monkeypatch.setattr("atlas_reviewer.github_auth.AppInstallationTokens", Refusing)
    _token, error = _read_token(
        {
            APP_KEY_ENV: "pem-secret-value",
            "ATLAS_GITHUB_APP_ID": "5648875",
            "ATLAS_GITHUB_INSTALLATION_ID": "12345",
        },
        PrEvent(REPO, 7, SHA),
    )
    for permission in ("contents", "checks", "actions", "pull_requests", "issues"):
        assert f"{permission} read" in error
    assert "is a permission missing" in error
    assert "pem-secret-value" not in error


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
    event = PrEvent(REPO, 42, SHA)
    oneshot = review_argv(
        RunConfig("offline", False, tmp_path, MODE_ONESHOT), tmp_path / "run", event
    )
    agentic = review_argv(
        RunConfig("offline", False, tmp_path, MODE_AGENTIC), tmp_path / "run", event
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
        RunConfig("openrouter", True, tmp_path, MODE_ONESHOT), tmp_path / "run", event
    )
    assert live[-1] == "--allow-live-inference"
    live_agentic = review_argv(
        RunConfig("openrouter", True, tmp_path, MODE_AGENTIC), tmp_path / "run", event
    )
    assert live_agentic[-1] == "--allow-live-inference"
    env = child_env({WEBHOOK_SECRET_ENV: SECRET, "ATLAS_SPRITES_TOKEN": "sprite"})
    assert WEBHOOK_SECRET_ENV not in env
    assert env["ATLAS_SPRITES_TOKEN"] == "sprite"


def test_the_agentic_child_reviews_with_a_per_pr_round_log(tmp_path):
    """D74: the service's round log is keyed by repository and pull
    request, so a later head of the same pull request reads the earlier
    rounds. The path sits outside the per-head run directory -- the
    mutant that keys it by head fails here -- and the oneshot child gets
    none: the one-shot `review` command has no round log."""
    first = PrEvent(REPO, 42, SHA)
    second = PrEvent(REPO, 42, "d" * 40)
    agentic = review_argv(
        RunConfig("offline", False, tmp_path, MODE_AGENTIC), tmp_path / "run", first
    )
    round_at = agentic.index("--round-log")
    flagged = Path(agentic[round_at + 1])
    assert flagged == tmp_path / "rounds" / "brandondees-code-quality-atlas-42.jsonl"
    assert run_dir(tmp_path, first) not in flagged.parents
    later = review_argv(
        RunConfig("offline", False, tmp_path, MODE_AGENTIC), tmp_path / "run", second
    )
    assert later[later.index("--round-log") + 1] == str(flagged)
    oneshot = review_argv(
        RunConfig("offline", False, tmp_path, MODE_ONESHOT), tmp_path / "run", first
    )
    assert "--round-log" not in oneshot


def test_a_case_renamed_repository_resolves_to_the_same_round_log(tmp_path):
    """D74 round 1, N1: the filename key is the reader's key -- a
    case-only repository rename keeps the pull request's log instead of
    silently starting a fresh one under the missing-file-is-first-round
    rule."""
    upper = PrEvent("Org/Repo", 42, SHA)
    lower = PrEvent("org/repo", 42, SHA)
    assert round_log_path(tmp_path, upper) == round_log_path(tmp_path, lower)
    assert round_log_path(tmp_path, lower) == tmp_path / "rounds" / "org-repo-42.jsonl"


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
    assert service_deadline({}, mode=MODE_ONESHOT) == REVIEW_DEADLINE_S
    assert service_deadline({SERVICE_DEADLINE_ENV: "3600"}, mode=MODE_ONESHOT) == 3600.0
    for raw in ("0", "-5", "30", "abc", "20000", "nan", "inf"):
        with pytest.raises(ValueError) as refused:
            service_deadline({SERVICE_DEADLINE_ENV: raw}, mode=MODE_ONESHOT)
    assert SERVICE_DEADLINE_ENV in str(refused.value)


def test_the_agentic_deadline_defaults_to_the_bound_ceiling():
    # The parent deadline is a backstop in agentic mode: the child's own
    # derived wall (D68's lens wall times the waves, from a plan the
    # parent cannot see) and the dollar ceiling are the real limits, so
    # the unset default is the bound's ceiling, shared with the bound
    # check -- not the configured wall plus a margin, which a plan of 4
    # or more lenses at pool 1 outgrows.
    assert service_deadline({}, mode=MODE_AGENTIC) == MAX_SERVICE_DEADLINE_S
    # The child's limits are still validated at boot with the default.
    with pytest.raises(ValueError) as refused:
        service_deadline({"ATLAS_REVIEW_WALL_S": "abc"}, mode=MODE_AGENTIC)
    assert "ATLAS_REVIEW_WALL_S" in str(refused.value)
    # An operator-raised child wall does not change the ceiling default.
    assert (
        service_deadline({"ATLAS_REVIEW_WALL_S": "7200"}, mode=MODE_AGENTIC)
        == MAX_SERVICE_DEADLINE_S
    )


def test_an_agentic_deadline_below_the_child_wall_refuses_at_boot():
    from atlas_reviewer.lens_loop import DEFAULT_REVIEW_WALL_S

    with pytest.raises(ValueError) as refused:
        service_deadline({SERVICE_DEADLINE_ENV: "1200"}, mode=MODE_AGENTIC)
    assert "review wall" in str(refused.value)
    assert str(int(DEFAULT_REVIEW_WALL_S)) in str(refused.value)
    # At or above the configured wall is accepted, and the ceiling holds.
    assert service_deadline({SERVICE_DEADLINE_ENV: "3600"}, mode=MODE_AGENTIC) == 3600.0
    with pytest.raises(ValueError):
        service_deadline({SERVICE_DEADLINE_ENV: "20000"}, mode=MODE_AGENTIC)
    # A configured child wall the ceiling cannot cover refuses too -- on
    # the default path as well, where the boot would otherwise carry a
    # 14,400 s deadline below the child's wall and kill every review it
    # queues.
    for env in (
        {"ATLAS_REVIEW_WALL_S": "20000"},
        {"ATLAS_REVIEW_WALL_S": "20000", SERVICE_DEADLINE_ENV: "7200"},
    ):
        with pytest.raises(ValueError) as refused:
            service_deadline(env, mode=MODE_AGENTIC)
        assert "ATLAS_REVIEW_WALL_S" in str(refused.value)
        assert "lower ATLAS_REVIEW_WALL_S" in str(refused.value)


def test_an_invalid_child_wall_refusal_names_the_variable():
    base = {"ATLAS_GITHUB_WEBHOOK_SECRET": SECRET, "ATLAS_SERVICE_PROVIDER": "offline"}
    for raw in ("abc", "0", "-5"):
        with pytest.raises(ServiceError) as refused:
            config_from_env({**base, "ATLAS_REVIEW_WALL_S": raw})
        assert "ATLAS_REVIEW_WALL_S" in str(refused.value)


def test_a_draft_from_the_other_mode_is_a_labeled_parse_failure(tmp_path):
    config = RunConfig("offline", False, tmp_path, MODE_AGENTIC)
    event = PrEvent(REPO, 7, SHA)

    def popen(argv, env, stdout, stderr):
        Path(argv[argv.index("--out") + 1]).write_text(DRAFT, encoding="utf-8")
        return _Proc(0)

    result = make_runner(config, {}, popen=popen)(event, threading.Event())
    assert result.ok is False
    assert "draft parse failed" in result.error
    assert "no agentic status line" in result.error

    agentic_draft = (
        '<!-- atlas-review-status: {"mode": "agentic", "review_event": "COMMENT"} -->\n'
    )

    def popen_agentic(argv, env, stdout, stderr):
        Path(argv[argv.index("--out") + 1]).write_text(agentic_draft, encoding="utf-8")
        return _Proc(0)

    oneshot = make_runner(
        RunConfig("offline", False, tmp_path, MODE_ONESHOT), {}, popen=popen_agentic
    )(event, threading.Event())
    assert oneshot.ok is False
    assert "draft parse failed" in oneshot.error


def test_an_unreadable_draft_fails_with_a_label(tmp_path):
    config = RunConfig("offline", False, tmp_path, MODE_AGENTIC)
    event = PrEvent(REPO, 7, SHA)

    def popen(argv, env, stdout, stderr):
        Path(argv[argv.index("--out") + 1]).write_text(
            "<!-- atlas-review-status: {not json", encoding="utf-8"
        )
        return _Proc(0)

    result = make_runner(config, {}, popen=popen)(event, threading.Event())
    assert result.ok is False
    assert result.report is None
    assert "draft parse failed" in result.error


def _renderer_draft(runner: object | None = None):
    """A draft from the real `coordinator.render_draft`, in the state the
    review flags: one selected lens that never ran, so coverage is
    incomplete with no unread file, and optionally a runner that did not
    complete and reported why."""
    from atlas_reviewer.coordinator import AgenticReview, LensResult, Verdict
    from atlas_reviewer.redact import Redactor

    lens = LensResult(
        "tracing-correctness-and-invariants",
        1,
        None,
        None,
        reason="the review ended first",
    )
    review = AgenticReview(
        lenses=(lens,),
        findings=(),
        verdict=Verdict.APPROVE,
        runner=runner,
    )
    return render_draft(review, Redactor())


def test_the_runners_failure_note_is_not_a_limit_stop():
    from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus

    runner = RunnerReport(
        RunnerStatus.FAILED,
        CleanupStatus.DESTROYED_VERIFIED,
        "cqa-rev-pr7-abcdef",
        "the model refused the lens body",
    )
    draft = _renderer_draft(runner)
    assert "Runner: failed" in draft
    assert "Runner reported, quoted:" in draft
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert report.limit_stops == ()
    assert all("Runner" not in stop for stop in report.limit_stops)


def test_an_incomplete_coverage_with_no_unread_file_names_no_cause():
    draft = _renderer_draft()
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert report.files_note == (
        "Agentic coverage incomplete; see the draft's coverage and omission notes."
    )


def _recovered_draft():
    """A draft from the real `coordinator.render_draft` in #692's state:
    one lens whose first entry is NOT RUN and whose later clean run
    supersedes it, so coverage is complete and the failure is a recovered
    note on the earlier entry's line."""
    lens = "tracing-correctness-and-invariants"
    lost = LensResult(lens, 2, None, None, reason="Sprites HTTP 502 for POST")
    rerun = LensResult(
        lens, 3, None, AttemptOutcome(Attestation.ATTESTED, changed_files=2)
    )
    review = synthesize([lost, rerun])
    return render_draft(review, Redactor())


def test_a_recovered_not_run_is_run_in_the_report_with_the_failure_kept():
    """#692: the service report agrees with the draft's coverage. A lens a
    later clean run recovered counts as run -- not as a NOT RUN lens the
    parity gate would fail -- and the failure survives as the recovered
    note among the limit stops, never silently dropped."""
    draft = _recovered_draft()
    assert "recovered by L3's clean run" in draft
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert report.lenses_run == ("tracing-correctness-and-invariants",)
    assert report.lenses_not_run == ()
    assert report.recommended_event == "APPROVE"
    assert report.files_note == (
        "Agentic file coverage complete: every changed file (2) was read in full."
    )
    stops = " ".join(report.limit_stops)
    assert "recovered by L3's clean run" in stops
    assert "Sprites HTTP 502" in stops


def test_a_recovered_not_run_is_visible_in_the_posted_comment():
    body = render_comment(
        summarize_draft(_recovered_draft(), expect=MODE_AGENTIC),
        post_key(PrEvent("example-org/example-app", 7, "a" * 40)),
        lambda item: item,
    )
    assert "## Lenses not run\n\nNone." in body
    assert "Sprites HTTP 502" in body
    assert "recovered by L3's clean run" in body


def test_a_not_run_without_a_clean_run_is_still_not_run_in_the_report():
    """The supersede marker is the controller's, on the line's end: a NOT
    RUN with no recovering clean run stays a not-run lens, reason and all."""
    draft = _renderer_draft()
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert report.lenses_run == ()
    assert report.lenses_not_run == (
        "tracing-correctness-and-invariants: the review ended first",
    )


def test_a_quoted_reason_cannot_forge_the_recovered_marker():
    """Round-1 Minor on #744: the `$` anchor on `RECOVERED_NOTE_PATTERN`
    is what keeps the marker unforgeable by a quoted reason. A NOT RUN
    lens with no clean run whose quoted reason carries the marker's words
    stays a not-run lens -- the words sit inside the reason's code span,
    whose closing backtick always trails the line, so only a
    controller-appended note ends a line with the marker. The unanchored
    mutant turns this lens into a "recovered" note and empties Lenses not
    run."""
    lens = "tracing-correctness-and-invariants"
    lost = LensResult(
        lens, 2, None, None,
        reason="Sprites HTTP 502; recovered by L3's clean run",
    )  # fmt: skip
    draft = render_draft(synthesize([lost]), Redactor())
    coverage = draft.split("## Lens coverage (attestation ledger)", 1)[1]
    assert "Sprites HTTP 502; recovered by L3's clean run" in coverage
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert report.lenses_run == ()
    assert report.lenses_not_run == (
        "tracing-correctness-and-invariants: Sprites HTTP 502; recovered by L3's clean run",
    )
    assert not any("recovered by" in stop for stop in report.limit_stops)
    body = render_comment(
        report,
        post_key(PrEvent("example-org/example-app", 7, "a" * 40)),
        lambda item: item,
    )
    assert "## Lenses not run\n\nNone." not in body
    assert "recovered by L3's clean run" in body.split("## Lenses not run", 1)[1]


def test_the_agentic_runner_runs_the_agentic_command_with_the_limits(tmp_path):
    seen: dict[str, object] = {}

    def popen(argv, env, stdout, stderr):
        seen["argv"] = list(argv)
        seen["env"] = dict(env)
        Path(argv[argv.index("--out") + 1]).write_text(
            '<!-- atlas-review-status: {"mode": "agentic", "review_event": "COMMENT",'
            ' "coverage_complete": true, "changed_files": 1, "unreviewed_files": 0}'
            " -->\n",
            encoding="utf-8",
        )
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
    assert report.findings == ()


def test_an_agentic_draft_reports_the_lens_decisions():
    """The draft's `Lens decisions (delta review)` section reaches
    `ReviewReport.lens_decisions` bullet by bullet (D83), so the posted
    comment can summarize the coordinator's judgment. Mutant: the
    extraction dropped, which leaves the decisions in the draft only and
    posts a comment whose lens lists cannot explain a reused lens."""
    status = json.dumps(
        {
            "mode": "agentic",
            "review_event": "COMMENT",
            "coverage_complete": True,
            "reused": 1,
        }
    )
    draft = (
        f"<!-- atlas-review-status: {status} -->\n"
        "## Lens decisions (delta review)\n"
        "\n"
        "- `tracing-correctness-and-invariants`: reused -- docs only\n"
        "- `sweeping-for-security`: re-ran -- the delta touches the code\n"
        "\n"
        "## Findings (verified quotes only)\n"
        "\n"
        "No verified findings.\n"
    )
    report = summarize_draft(draft)
    assert report.lens_decisions == (
        "`tracing-correctness-and-invariants`: reused -- docs only",
        "`sweeping-for-security`: re-ran -- the delta touches the code",
    )


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
    assert report.findings == ()
    empty = summarize_draft("no sections\n")
    assert empty.lenses_run == ()
    assert empty.findings == ()
    assert empty.files_note == "The draft has no diff-coverage note."


def _finding_draft(
    findings: tuple, selection_note: str = "", ceiling_note: str = ""
) -> str:
    """A draft from the real `coordinator.render_draft` whose one lens ran
    clean with the given verified findings, each (severity, problem, fix),
    (severity, problem, fix, evidence) or (..., evidence, siblings); the
    two-finding shape is what the #654 round log held."""

    def checked(
        severity: Severity,
        problem: str,
        fix: str,
        evidence: str = "return sum(round(x, 2) for x in xs)",
        siblings: str = "",
    ) -> CheckedFinding:
        return CheckedFinding(
            Finding(
                LineRange("calc.py", 2, 3),
                severity,
                Valence.DEFECT,
                Route.ENG,
                Attribution.INTRODUCED,
                problem,
                fix,
                evidence,
                siblings,
            ),
            QuoteSource.HEAD,
        )

    outcome = AttemptOutcome(
        Attestation.ATTESTED,
        findings=tuple(checked(*f) for f in findings),
        changed_files=1,
    )
    review = synthesize(
        [LensResult("tracing-correctness-and-invariants", 1, "ab12", outcome)]
    )
    if selection_note or ceiling_note:
        review = dataclasses.replace(
            review, selection_note=selection_note, ceiling_note=ceiling_note
        )
    return render_draft(review, Redactor())


def _two_finding_draft() -> str:
    return _finding_draft(
        (
            (Severity.MINOR, "rounds before summing", "sum first"),
            (Severity.NIT, "a magic constant", "name it"),
        )
    )


def test_an_agentic_draft_with_findings_carries_them_into_the_report():
    draft = _two_finding_draft()
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert len(report.findings) == 2
    minor, nit = report.findings
    assert minor.startswith("**L1-F1** [minor, defect, route: eng, introduced]")
    assert "calc.py:2" in minor and "rounds before summing" in minor
    assert nit.startswith("**L1-F2** [nit, defect, route: eng, introduced]")
    assert "calc.py:2" in nit and "a magic constant" in nit


LONG_PROBLEM = (
    "the retry loop re-arms the wall timer before the response is durably "
    "recorded, so a crash between the re-arm and the ledger write leaves the "
    "job unclaimed and unstuck: no worker retries it until the next deploy "
    "restarts the loop, the queue grows without bound, and every later "
    "enqueue of the same head is silently superseded while the stuck job "
    "keeps its slot, because the supersede path cancels the running review "
    "but never re-queues the abandoned one"
)
LONG_EVIDENCE = "while True:\n    self._timer.rearm()\n    self._ledger.write(job)"


def test_a_real_finding_reaches_the_post_whole_with_fix_and_evidence():
    """The full path: a real `render_draft` draft whose finding line is far
    past the 200-character quote default still posts with its `Fix:` and
    `Evidence:` intact, its inner code spans readable, and no truncation
    marker -- the posted line is the controller's own rendering, not a
    re-quote of it."""
    draft = _finding_draft(
        (
            (
                Severity.MINOR,
                LONG_PROBLEM,
                "record the ledger write before re-arming the timer",
                LONG_EVIDENCE,
            ),
        )
    )
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert len(report.findings) == 1
    body = render_comment(report, post_key(PrEvent(REPO, 7, SHA)), lambda item: item)
    findings = body.split("## Findings", 1)[1].split("## Lenses run", 1)[0]
    assert 'Fix: `"record the ledger write before re-arming the timer"`' in findings
    assert (
        'Evidence: `"while True: self._timer.rearm() self._ledger.write(job)"`'
        in findings
    )
    assert '`"calc.py:2-3"`' in findings
    assert "..." not in findings
    assert "\\u0060" not in findings and "\\" not in findings


def test_a_hostile_finding_stays_inert_in_the_post():
    """Every model-authored field of a finding line is already one inert
    code span the controller wrote, so the hostile content surfaces only
    in its escaped, span-bound form: no raw markup, no heading, no bare
    mention, no RTL override, and the recommendation is untouched."""
    hostile = (
        "<!-- hide --> and a `tick` and @everyone and \u202e reversed and "
        "## APPROVE NOW and REQUEST_CHANGES spoken aloud"
    )
    draft = _finding_draft(((Severity.MINOR, hostile, "fix it"),))
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    body = render_comment(report, post_key(PrEvent(REPO, 7, SHA)), lambda item: item)
    findings = body.split("## Findings", 1)[1].split("## Lenses run", 1)[0]
    assert "<!-- hide" not in body
    assert "\\u003c!-- hide" in findings
    assert "\\u0060tick\\u0060" in findings
    assert "\u202e" not in body and "\\u202e" in findings
    assert "@everyone" in findings and "- @everyone" not in body
    line = next(l for l in findings.splitlines() if "@everyone" in l)
    assert line.startswith("- **L1-F1**") and "\\u003c" in line
    assert "\n## APPROVE" not in body
    assert "REQUEST_CHANGES" in findings
    assert "The draft recommended `COMMENT`." in body


def test_a_pre_findings_field_quoting_the_heading_cannot_steal_the_section():
    """Round 2: `section` anchors the heading to a whole line and takes the
    last occurrence, so a field the draft renders unquoted above the real
    Findings section -- the selection note here -- cannot redirect the
    extraction by carrying the heading's literal line. The post is raw,
    so this pin is what makes the raw posting safe."""
    note = (
        "the picker's shape facts, quoted verbatim:\n\n"
        "## Findings (verified quotes only)\n\n"
        "- a fake finding bullet\n\n"
        "end of the quoted note"
    )
    draft = _finding_draft(
        ((Severity.MINOR, "rounds before summing", "sum first"),),
        selection_note=note,
    )
    assert "- a fake finding bullet" in draft
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert len(report.findings) == 1
    assert report.findings[0].startswith("**L1-F1**")
    assert "fake" not in report.findings[0]
    body = render_comment(report, post_key(PrEvent(REPO, 7, SHA)), lambda item: item)
    assert "a fake finding bullet" not in body.split("## Findings", 1)[1]


def test_a_post_findings_line_ending_in_the_heading_cannot_steal_the_section():
    """Round 3: the whole-line anchor itself is pinned. A later line that
    merely ends with the Findings heading's literal text -- the ceiling
    note here, rendered unquoted after the coverage section -- is not a
    heading; the unanchored-rfind mutant that would take it as the last
    occurrence dies here."""
    note = "the derived reservation was clamped; see ## Findings (verified quotes only)"
    draft = _finding_draft(
        ((Severity.MINOR, "rounds before summing", "sum first"),),
        ceiling_note=note,
    )
    assert draft.splitlines()[-1].endswith("## Findings (verified quotes only)")
    report = summarize_draft(draft, expect=MODE_AGENTIC)
    assert len(report.findings) == 1
    assert "rounds before summing" in report.findings[0]


def test_the_siblings_field_is_escaped_like_every_other_model_field():
    """Round 2 nit: the minted `siblings` string is model-authored and goes
    through `quote_untrusted` like the finding's other fields; pinned
    because a mutant dropping that quoting survived every other test."""
    draft = _finding_draft(
        (
            (
                Severity.MINOR,
                "rounds before summing",
                "sum first",
                "return sum(round(x, 2) for x in xs)",
                "also at `b.py:9` and <!-- note --> and @everyone",
            ),
        )
    )
    line = next(l for l in draft.splitlines() if "Siblings: " in l)
    sib = line.split("Siblings: ", 1)[1]
    assert sib.startswith('`"') and sib.endswith('"`')
    assert "\\u0060b.py:9\\u0060" in sib and "`b.py:9`" not in sib
    assert "<!--" not in sib and "\\u003c!--" in sib
    assert "@everyone" in sib


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
    config = RunConfig("offline", False, tmp_path, MODE_ONESHOT)
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
    config = RunConfig("offline", False, tmp_path, MODE_ONESHOT)
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


# ------------------------------------------------- the delta report (#702)


def _delta_draft() -> str:
    status = json.dumps(
        {
            "mode": "agentic",
            "review_event": "COMMENT",
            "proposed_event": "COMMENT",
            "coverage_complete": True,
            "carried": 1,
            "resolved": 1,
        }
    )
    return (
        f"<!-- atlas-review-status: {status} -->\n"
        "**Review event: COMMENT.**\n"
        "\n"
        "Delta review: builds on the review of `3f6c1e9b2a7d`.\n"
        "\n"
        "## Resolved by the new commits\n"
        "\n"
        '- **P2** `"calc.py:9"`: `"the secret is logged"`. '
        'Reason, quoted: `"the delta deletes the log line"`\n'
        "\n"
        "## Carried, not re-verified\n"
        "\n"
        '- **P3** `"docs/x.md:2"`: `"stale example"`\n'
        "\n"
        "## Findings (verified quotes only)\n"
        "\n"
        '- **P1** [carried, blocker] `"calc.py:4"` (`"tracing lens"`): '
        '"rounds per line"\n'
        "\n"
        "## Lens coverage (attestation ledger)\n"
        "\n"
        "- L1 tracing lens: **clean**; body sha256 ab12\n"
        "\n"
        "Model calls: 4; committed: $0.12.\n"
    )


def test_a_delta_drafts_resolved_and_carried_sections_reach_the_report():
    report = summarize_draft(_delta_draft(), expect="agentic")
    # Mutant: the two delta sections dropped from the parse -- the post
    # would lose what the new commits fixed and what was carried
    # unverifiable, both of which the issue's carry-forward contract
    # promises to a reader.
    assert report.findings == (
        '**P1** [carried, blocker] `"calc.py:4"` (`"tracing lens"`): "rounds per line"',
    )
    assert report.resolved == (
        (
            '**P2** `"calc.py:9"`: `"the secret is logged"`. '
            'Reason, quoted: `"the delta deletes the log line"`'
        ),
    )
    assert report.carried_unverified == ('**P3** `"docs/x.md:2"`: `"stale example"`',)


def test_a_full_review_draft_has_no_delta_sections():
    """A full review's draft (no delta sections at all -- a real one, not
    a stripped delta draft) parses with empty resolved and carried
    lists, so the post of a full review gains neither section."""
    status = json.dumps(
        {
            "mode": "agentic",
            "review_event": "COMMENT",
            "proposed_event": "COMMENT",
            "coverage_complete": True,
        }
    )
    draft = (
        f"<!-- atlas-review-status: {status} -->\n"
        "**Review event: COMMENT.**\n"
        "\n"
        "## Findings (verified quotes only)\n"
        "\n"
        '- **L1-F1** [minor] `"calc.py:2"` (`"lens"`): "rounds early"\n'
        "\n"
        "## Lens coverage (attestation ledger)\n"
        "\n"
        "- L1 lens: **clean**; body sha256 ab12\n"
        "\n"
        "Model calls: 4; committed: $0.12.\n"
    )
    report = summarize_draft(draft, expect="agentic")
    assert report.resolved == ()
    assert report.carried_unverified == ()
    assert report.findings == (
        '**L1-F1** [minor] `"calc.py:2"` (`"lens"`): "rounds early"',
    )


# ------------------------------------------------ the severity floor (S3)


def _lens_finding_draft(lens: str, findings: tuple) -> str:
    """A draft from the real `coordinator.render_draft` whose one lens --
    named, so a floor-tier lens's own findings can be tested against the
    preference tier's -- ran clean with the given verified findings, each
    (severity, problem, fix)."""
    from atlas_reviewer.redact import Redactor

    def checked(severity: Severity, problem: str, fix: str) -> CheckedFinding:
        return CheckedFinding(
            Finding(
                LineRange("calc.py", 2, 3),
                severity,
                Valence.DEFECT,
                Route.ENG,
                Attribution.INTRODUCED,
                problem,
                fix,
                "return sum(round(x, 2) for x in xs)",
            ),
            QuoteSource.HEAD,
        )

    outcome = AttemptOutcome(
        Attestation.ATTESTED,
        findings=tuple(checked(*f) for f in findings),
        changed_files=1,
    )
    review = synthesize([LensResult(lens, 1, "ab12", outcome)])
    return render_draft(review, Redactor())


def test_finding_class_reads_the_controller_tags_and_lens():
    """The severity is the tags bracket's first tag and the lens is the
    parenthesis that names it -- on a line the real `render_draft` wrote,
    so the parse's shape is the controller's own."""
    draft = _lens_finding_draft(
        "checking-restraint", ((Severity.MINOR, "rounds before summing", "sum first"),)
    )
    line = summarize_draft(draft, expect=MODE_AGENTIC).findings[0]
    assert line.startswith("**L1-F1** [minor, defect, route: eng, introduced]")
    assert finding_class(line) == (Severity.MINOR, "checking-restraint")


def test_finding_class_reads_a_carried_lines_severity_from_its_second_tag():
    """A carried finding's tags bracket opens with the carried tag's own
    word (#702); the severity is the tag after it, and the lens arrives
    quoted."""
    line = (
        '- **L1-F1** [carried, blocker] `"calc.py:2-3"` '
        "(`tracing-correctness-and-invariants`): "
        "`the refund path rounds before summing`"
    )
    assert finding_class(line) == (
        Severity.BLOCKER,
        "tracing-correctness-and-invariants",
    )


def test_finding_class_keeps_an_unparseable_line_unclassified():
    """A line that is not a controller-rendered finding classifies as
    (None, ""): the floor keeps what it cannot see, never silently
    drops it."""
    assert finding_class("- a plain bullet that is not a finding") == (None, "")
    assert finding_class("") == (None, "")


def test_finding_class_is_not_confused_by_decoy_anchors_in_quoted_text():
    """The location span and the finding text are data: a `(word): `
    sequence inside either must not move the lens the parse reads. The
    anchor's position -- one span, then the lens parenthesis -- is fixed
    by the line's controller-rendered prefix."""
    draft = _lens_finding_draft(
        "checking-restraint",
        (
            (
                Severity.MINOR,
                "the helper at (sum): rounds twice (fix): wrongly",
                "sum first",
            ),
        ),
    )
    line = summarize_draft(draft, expect=MODE_AGENTIC).findings[0]
    assert finding_class(line) == (Severity.MINOR, "checking-restraint")


def test_finding_class_names_an_unknown_severity_tag_unclassified():
    """A tags bracket whose first tag is not a severity name -- a draft
    this coordinator did not write -- classifies as unclassified, with
    the lens it could still read."""
    line = "**L1-F1** [urgent, defect] `calc.py:2-3` (checking-restraint): text"
    assert finding_class(line) == (None, "checking-restraint")


def test_the_default_floor_keeps_every_finding():
    from atlas_reviewer.repo_config import DEFAULT_POST_CONFIG

    findings = (
        (
            "**L1-F1** [minor, defect, route: eng, introduced] `calc.py:2-3` "
            "(checking-restraint): rounds before summing"
        ),
        (
            "**L1-F2** [nit, defect, route: eng, introduced] `calc.py:2-3` "
            "(checking-restraint): a magic constant"
        ),
    )
    kept, held = apply_severity_floor(findings, DEFAULT_POST_CONFIG.floor)
    assert kept == findings
    assert held == 0


def test_the_floor_holds_below_floor_preference_findings_and_counts_them():
    """The repo's floor holds the preference-tier findings below it from
    the post -- named by the count the post carries, never silent --
    and keeps everything at or above it."""
    from atlas_reviewer.lens_contract import Severity as S

    findings = (
        (
            "**L1-F1** [blocker, defect, route: eng, introduced] `a.py:1` "
            "(reviewing-api-contract-safety): breaks callers"
        ),
        (
            "**L1-F2** [major, defect, route: eng, introduced] `a.py:2` "
            "(checking-restraint): overbuilt"
        ),
        (
            "**L1-F3** [minor, defect, route: eng, introduced] `a.py:3` "
            "(checking-restraint): naming"
        ),
        (
            "**L1-F4** [nit, defect, route: eng, introduced] `a.py:4` "
            "(checking-restraint): wording"
        ),
    )
    kept, held = apply_severity_floor(findings, S("major"))
    assert kept == findings[:2]
    assert held == 2


def test_a_finding_exactly_at_the_floor_is_kept():
    """At the floor means posted: `major` keeps a Major. Kills the
    strict-comparison mutant, which dropped the floor's own tier."""
    from atlas_reviewer.lens_contract import Severity as S

    findings = (
        (
            "**L1-F1** [major, defect, route: eng, introduced] `a.py:2` "
            "(checking-restraint): overbuilt"
        ),
    )
    kept, held = apply_severity_floor(findings, S("major"))
    assert kept == findings and held == 0


def test_a_floor_tier_lens_finding_is_never_held_whatever_its_severity():
    """The tier rule carries over unchanged (D81 Q3): a finding from one
    of the manifest's floor-tier lenses is posted at any severity, under
    any floor the repo raised. Kills the tier-exemption-removed mutant."""
    from atlas_reviewer.lens_contract import Severity as S

    findings = (
        (
            "**L1-F1** [nit, defect, route: eng, introduced] `a.py:4` "
            "(hunting-silent-failures): the swallowed OSError hides the refusal"
        ),
    )
    kept, held = apply_severity_floor(findings, S("blocker"))
    assert kept == findings and held == 0


def test_an_unclassifiable_finding_is_kept_under_any_floor():
    """A line the parse cannot classify is kept: the floor suppresses
    only what it can see. Kills the unclassifiable-dropped mutant."""
    from atlas_reviewer.lens_contract import Severity as S

    findings = ("- a bullet this parse cannot read as a finding",)
    kept, held = apply_severity_floor(findings, S("blocker"))
    assert kept == findings and held == 0
