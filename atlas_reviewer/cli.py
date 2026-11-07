# SPDX-License-Identifier: MIT
"""Operator entry point: `python -m atlas_reviewer {review,sweep,probe-runner}`.

`review --dry-run` needs no credentials and no network: GitHub is a fixture
directory, the runner is the in-memory fake, the provider is offline.
Live mode reads credentials from the environment variables named below and
hands each one only to the adapter that needs it. Live model inference is
off unless `--provider openrouter --allow-live-inference` are both given.

Every live command records lifecycle telemetry (`atlas_reviewer.telemetry`)
to a JSONL file: `--events PATH`, or by default
`<state dir>/telemetry/<command>-<UTC time>.jsonl`. A dry run writes one
only when `--events` is given. Event text passes through a redactor holding
every credential value from the environment first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from atlas_reviewer.budget import CallLimits
from atlas_reviewer.clock import SystemClock
from atlas_reviewer.controller import (
    DEFAULT_DIFF_CHARS_PER_CALL,
    MAX_MODEL_CALLS,
    MAX_TARBALL_BYTES,
    Deps,
    ReviewConfig,
    review,
)
from atlas_reviewer.domain import (
    InvalidEventError,
    PrEvent,
    RunnerReport,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.draft import telemetry_section
from atlas_reviewer.fakes import FakeSprites, MemoryLedger
from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.github_auth import READ_PERMISSIONS, AppInstallationTokens
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.harness import SkillBundleHarness, load_bundle
from atlas_reviewer.http import UrllibStreamingTransport, UrllibTransport
from atlas_reviewer.instrumented import InstrumentedGitHub
from atlas_reviewer.interpreter import TrustedPython
from atlas_reviewer.ledger import FileLedger, ReviewInProgressError, single_review_lock
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.picker import Depth
from atlas_reviewer.ports import BoundaryError, Clock, ModelProvider, SpritesApi
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import (
    DEFAULT_TOOLS,
    FIRST_FRAME_BUDGET_S,
    TRIVIAL_TOOL,
    Diagnostic,
    RunnerJob,
    ToolAbsent,
    ToolRan,
    ToolResult,
    probe_runner,
    run_disposable,
    runner_name,
    sweep,
)
from atlas_reviewer.sprites_api import SpritesClient
from atlas_reviewer.telemetry import JsonlSink, Telemetry

ENV_APP_ID = "ATLAS_GITHUB_APP_ID"
ENV_APP_KEY = "ATLAS_GITHUB_APP_PRIVATE_KEY"
ENV_INSTALLATION_ID = "ATLAS_GITHUB_INSTALLATION_ID"
ENV_SPRITES_TOKEN = "ATLAS_SPRITES_TOKEN"
ENV_OPENROUTER_KEY = "ATLAS_OPENROUTER_API_KEY"
ENV_STATE_DIR = "ATLAS_REVIEWER_STATE_DIR"
DEFAULT_STATE_DIR = Path(".atlas-reviewer-state")
PROVIDER_CHOICES = ("offline", "openrouter")
SECRET_ENV = (ENV_APP_KEY, ENV_SPRITES_TOKEN, ENV_OPENROUTER_KEY)

EXIT_OK, EXIT_USAGE, EXIT_BOUNDARY = 0, 2, 3


class UsageError(Exception):
    pass


def load_event(path: Path) -> PrEvent:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"cannot read event file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError("event file must hold a JSON object")
    try:
        return PrEvent(
            repo=data.get("repo", ""),
            pr_number=data.get("pr_number", 0),
            head_sha=data.get("head_sha", ""),
        )
    except InvalidEventError as exc:
        raise UsageError(f"invalid event: {exc}") from exc


def parse_expected(values: Sequence[str]) -> tuple[SourceKey, ...]:
    kinds = {k.value: k for k in SourceKind}
    keys = []
    for value in values:
        kind, sep, name = value.partition(":")
        if not sep or kind not in kinds or not name:
            raise UsageError(
                f"--expect must be KIND:NAME with KIND in {sorted(kinds)}, got {value!r}"
            )
        keys.append(SourceKey(kinds[kind], name))
    return tuple(keys)


def _require_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise UsageError(f"this command needs the {name} environment variable")
    return value


def _pem(raw: str) -> str:
    return raw.replace("\\n", "\n") if "\n" not in raw else raw


def _installation_id(env: Mapping[str, str]) -> int:
    raw = _require_env(env, ENV_INSTALLATION_ID)
    if not raw.isdigit():
        raise UsageError(f"{ENV_INSTALLATION_ID} must be a positive integer")
    return int(raw)


def _state_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    return Path(args.state_dir or env.get(ENV_STATE_DIR) or DEFAULT_STATE_DIR)


@dataclass(frozen=True)
class _Wiring:
    deps: Deps
    mode: str


def _select_provider(
    args: argparse.Namespace,
    env: Mapping[str, str],
    openrouter: Callable[[str, CallLimits], OpenRouterProvider],
    telemetry: Telemetry,
) -> ModelProvider:
    if args.provider == "offline":
        return OfflineProvider()
    if args.dry_run:
        raise UsageError("--dry-run is offline-only; drop --provider openrouter")
    if not args.allow_live_inference:
        raise UsageError(
            "live inference is off: pass --allow-live-inference with --provider openrouter"
        )
    provider = openrouter(
        _require_env(env, ENV_OPENROUTER_KEY),
        CallLimits(max_calls=args.max_model_calls),
    )
    telemetry.span("model preflight", "key status", provider.preflight)
    return provider


def _live_openrouter(key: str, limits: CallLimits) -> OpenRouterProvider:
    return OpenRouterProvider(UrllibTransport(), key, limits=limits, sleep=time.sleep)


def _env_redactor(env: Mapping[str, str]) -> Redactor:
    return Redactor(tuple(env.get(name, "") for name in SECRET_ENV if env.get(name)))


def _telemetry(
    args: argparse.Namespace,
    env: Mapping[str, str],
    command: str,
    *,
    default_file: bool,
) -> Telemetry:
    clock = SystemClock()
    redactor = _env_redactor(env)
    default = (
        _state_dir(args, env)
        / "telemetry"
        / f"{command}-{clock.now():%Y%m%dT%H%M%SZ}.jsonl"
    )
    path = Path(args.events) if args.events else (default if default_file else None)
    sink = JsonlSink(path) if path else None
    return Telemetry(clock, sink, scrub=lambda text: redactor(text).text)


def _events_path(telemetry: Telemetry) -> str:
    sink = telemetry.sink
    return str(sink.path) if isinstance(sink, JsonlSink) else "(not written)"


def _dry_run_wiring(
    args: argparse.Namespace,
    event_path: Path,
    provider: ModelProvider,
    telemetry: Telemetry,
) -> _Wiring:
    fixtures = Path(args.fixtures) if args.fixtures else event_path.parent
    script_path = fixtures / "runner-script.json"
    script: dict[str, Any] = (
        json.loads(script_path.read_text(encoding="utf-8"))
        if script_path.is_file()
        else {}
    )
    redactor = Redactor()
    clock = SystemClock()
    deps = Deps(
        github=FixtureGitHub(fixtures),
        sprites=FakeSprites.from_script(script),
        ledger=MemoryLedger(),
        harness=SkillBundleHarness(provider, load_bundle(), redactor),
        clock=clock,
        redactor=redactor,
        runner_name=lambda: runner_name(clock),
        telemetry=telemetry,
    )
    return _Wiring(
        deps, f"dry run (fixtures: {fixtures}; fake runner; provider {provider.name})"
    )


def _app_tokens(
    env: Mapping[str, str],
    event: PrEvent,
    include_issues: bool,
    transport: UrllibTransport,
) -> AppInstallationTokens:
    return AppInstallationTokens(
        transport,
        SystemClock(),
        app_id=_require_env(env, ENV_APP_ID),
        private_key=_pem(_require_env(env, ENV_APP_KEY)),
        installation_id=_installation_id(env),
        permissions=_permissions(include_issues),
        repositories=(event.repo.split("/", 1)[1],),
    )


def _live_wiring(
    args: argparse.Namespace,
    env: Mapping[str, str],
    event: PrEvent,
    provider: ModelProvider,
    telemetry: Telemetry,
) -> _Wiring:
    private_key = _pem(_require_env(env, ENV_APP_KEY))
    sprites_token = _require_env(env, ENV_SPRITES_TOKEN)
    clock = SystemClock()
    transport = UrllibTransport()
    tokens = _app_tokens(env, event, args.include_issues, transport)
    known = (private_key, sprites_token, env.get(ENV_OPENROUTER_KEY, ""))
    redactor = Redactor(tuple(k for k in known if k), sources=(tokens.secrets,))
    deps = Deps(
        github=GitHubClient(transport, tokens),
        sprites=args.sprites_factory(env),
        ledger=FileLedger(_state_dir(args, env) / "runners.ledger"),
        harness=SkillBundleHarness(provider, load_bundle(), redactor),
        clock=clock,
        redactor=redactor,
        runner_name=lambda: runner_name(clock),
        telemetry=telemetry,
    )
    return _Wiring(deps, f"live (GitHub App + Sprites; provider {provider.name})")


def _permissions(include_issues: bool) -> dict[str, str]:
    base = dict(READ_PERMISSIONS)
    return {**base, "issues": "read"} if include_issues else base


def _review_config(args: argparse.Namespace, mode: str) -> ReviewConfig:
    try:
        return ReviewConfig(
            expected=parse_expected(args.expect),
            include_issues=args.include_issues,
            deadline_s=args.deadline_seconds,
            mode=mode,
            model_calls=args.max_model_calls,
            diff_chars_per_call=args.diff_chars_per_call,
            first_frame_s=args.first_frame_seconds,
            depth=Depth(args.depth),
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def _cmd_review(args: argparse.Namespace, env: Mapping[str, str], out: TextIO) -> int:
    event_path = Path(args.event)
    event = load_event(event_path)
    _review_config(args, "check")
    telemetry = _telemetry(args, env, "review", default_file=not args.dry_run)
    provider = _select_provider(args, env, args.openrouter_factory, telemetry)
    wiring = (
        _dry_run_wiring(args, event_path, provider, telemetry)
        if args.dry_run
        else _live_wiring(args, env, event, provider, telemetry)
    )
    config = _review_config(args, wiring.mode)
    with single_review_lock(_state_dir(args, env) / "review.lock"):
        draft = review(event, wiring.deps, config)
    _emit(draft, args.out, out)
    if args.out is not None:
        out.write(
            f"telemetry: {len(telemetry.events)} event(s), {_events_path(telemetry)}\n"
        )
    return EXIT_OK


def _emit(draft: str, out_path: str | None, out: TextIO) -> None:
    if out_path is None:
        out.write(draft)
        return
    Path(out_path).write_text(draft, encoding="utf-8")
    out.write(f"review draft written to {out_path}\n")


def _live_sprites(env: Mapping[str, str]) -> SpritesApi:
    return SpritesClient(
        UrllibStreamingTransport(), _require_env(env, ENV_SPRITES_TOKEN)
    )


def _cmd_sweep(args: argparse.Namespace, env: Mapping[str, str], out: TextIO) -> int:
    api = args.sprites_factory(env)
    # The ledger lists a live review's runner too; sweeping during a review
    # would destroy it mid-run, so sweep waits its turn like review does.
    with single_review_lock(_state_dir(args, env) / "review.lock"):
        results = sweep(api, FileLedger(_state_dir(args, env) / "runners.ledger"))
    out.writelines(f"{name}: {status.value}\n" for name, status in results.items())
    out.write(f"{len(results)} runner(s) in the ledger\n")
    return EXIT_OK


def _cmd_probe(args: argparse.Namespace, env: Mapping[str, str], out: TextIO) -> int:
    telemetry = _telemetry(args, env, f"probe-{args.sequence}", default_file=True)
    sequence = _PROBE_SEQUENCES[args.sequence]
    with single_review_lock(_state_dir(args, env) / "review.lock"):
        sequence(args, env, out, telemetry)
    out.write(f"\n{telemetry_section(telemetry.events)}\n\n")
    out.write(
        f"telemetry: {len(telemetry.events)} event(s), {_events_path(telemetry)}\n"
    )
    return EXIT_OK


def _probe_protocol(
    args: argparse.Namespace, env: Mapping[str, str], out: TextIO, telemetry: Telemetry
) -> None:
    clock: Clock = SystemClock()
    outcome = probe_runner(
        args.sprites_factory(env),
        FileLedger(_state_dir(args, env) / "runners.ledger"),
        DEFAULT_TOOLS,
        name=runner_name(clock),
        deadline_s=args.deadline_seconds,
        clock=clock,
        telemetry=telemetry,
        first_frame_s=args.first_frame_seconds,
    )
    _write_report(outcome.report, out)
    out.writelines(
        f"tool {b}: {'present' if ok else 'ABSENT'}\n"
        for b, ok in outcome.available.items()
    )
    out.write(f"raw exec response sample: {outcome.framing_sample[:200]!r}\n")
    out.write(f"stdin round-trip: {outcome.stdin_check}\n")


def _probe_review_sequence(
    args: argparse.Namespace, env: Mapping[str, str], out: TextIO, telemetry: Telemetry
) -> None:
    """The review's exact exec sequence (tool check, upload, unpack, tools)
    on a real checkout, with no model call and no evidence gathering."""
    tarball = _probe_source(args, env, telemetry)
    if len(tarball) > MAX_TARBALL_BYTES:
        raise UsageError(f"tarball is {len(tarball)} bytes, over {MAX_TARBALL_BYTES}")
    clock: Clock = SystemClock()
    tools = DEFAULT_TOOLS if args.tools == "review" else (TRIVIAL_TOOL,)
    outcome = run_disposable(
        args.sprites_factory(env),
        FileLedger(_state_dir(args, env) / "runners.ledger"),
        RunnerJob(tarball, tools, diagnose=True),
        name=runner_name(clock),
        deadline_s=args.deadline_seconds,
        clock=clock,
        telemetry=telemetry,
        first_frame_s=args.first_frame_seconds,
    )
    _write_report(outcome.report, out)
    out.write(f"source tarball: {len(tarball)} bytes\n")
    out.writelines(f"{_tool_report(r)}\n" for r in outcome.results)
    out.write(f"{_python_report(outcome.python)}\n")
    out.writelines(f"{_diagnostic_report(d)}\n" for d in outcome.diagnostics)


def _python_report(python: TrustedPython | None) -> str:
    if python is None:
        return "trusted python: none resolved"
    return f"trusted python: {python.path} ({python.version})"


def _diagnostic_report(result: Diagnostic) -> str:
    return (
        f"diagnostic {result.name}: exit {result.exit_code}: {result.detail} "
        f"[expected: {result.expectation}]"
    )


def _probe_source(
    args: argparse.Namespace, env: Mapping[str, str], telemetry: Telemetry
) -> bytes:
    if args.tarball:
        return _read_tarball(Path(args.tarball))
    if not args.event:
        raise UsageError("--sequence review needs --tarball FILE or --event FILE")
    event = load_event(Path(args.event))
    transport = UrllibTransport()
    github = InstrumentedGitHub(
        GitHubClient(transport, _app_tokens(env, event, False, transport)), telemetry
    )
    return github.get_tarball(event.repo, event.head_sha)


def _read_tarball(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise UsageError(f"cannot read tarball {path}: {exc}") from exc


def _write_report(r: RunnerReport, out: TextIO) -> None:
    out.write(f"runner: {r.runner_name}\nstatus: {r.status.value}\n")
    out.write(f"cleanup: {r.cleanup.value}\nnote: {r.note}\n")


def _tool_report(result: ToolResult) -> str:
    match result:
        case ToolRan(tool=tool, version=version, exit_code=code, output=output):
            return (
                f"tool {tool.name} ({version}): exit {code}; output: {output[-300:]!r}"
            )
        case ToolAbsent(tool=tool, detail=detail):
            return f"tool {tool.name}: not run -- {detail}"
    raise TypeError(f"not a tool result: {result!r}")  # pragma: no cover


_PROBE_SEQUENCES: dict[
    str, Callable[[argparse.Namespace, Mapping[str, str], TextIO, Telemetry], None]
] = {"protocol": _probe_protocol, "review": _probe_review_sequence}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas_reviewer",
        description="Manual Code Quality Atlas review (draft only).",
    )
    parser.add_argument(
        "--state-dir",
        help=f"controller-local state (default: ${ENV_STATE_DIR} or {DEFAULT_STATE_DIR})",
    )
    parser.set_defaults(
        sprites_factory=_live_sprites, openrouter_factory=_live_openrouter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    rev = sub.add_parser("review", help="review one PR event and write a draft")
    rev.add_argument(
        "--event", required=True, help="JSON file with repo, pr_number, head_sha"
    )
    rev.add_argument(
        "--dry-run",
        action="store_true",
        help="fixtures + fake runner + offline provider; no credentials",
    )
    rev.add_argument(
        "--fixtures",
        help="fixture directory for --dry-run (default: the event file's directory)",
    )
    rev.add_argument("--out", help="write the draft here instead of stdout")
    rev.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="KIND:NAME",
        help="evidence that must exist",
    )
    rev.add_argument(
        "--include-issues",
        action="store_true",
        help="opt in to fetching issues the PR closes",
    )
    rev.add_argument(
        "--deadline-seconds", type=float, default=600.0, help="external runner deadline"
    )
    rev.add_argument(
        "--max-model-calls",
        type=int,
        default=MAX_MODEL_CALLS,
        help=(
            "model calls per review, retries included: one for the lens picker "
            f"(except at triage depth), the rest for diff parts (1-{MAX_MODEL_CALLS})"
        ),
    )
    rev.add_argument(
        "--diff-chars-per-call",
        type=int,
        default=DEFAULT_DIFF_CHARS_PER_CALL,
        help=(
            "most diff characters a model call may carry; each review shrinks "
            "parts further to fit its measured prompt under the token bound"
        ),
    )
    rev.add_argument(
        "--depth",
        choices=[d.value for d in Depth],
        default=Depth.REVIEW.value,
        help="the atlas depth mode: triage runs the critical tier with no picker call",
    )
    _events_arg(rev)
    rev.add_argument("--provider", choices=PROVIDER_CHOICES, default="offline")
    rev.add_argument(
        "--allow-live-inference",
        action="store_true",
        help="required with --provider openrouter; spends real money (capped)",
    )
    _first_frame_arg(rev)
    rev.set_defaults(handler=_cmd_review)
    swp = sub.add_parser(
        "sweep", help="destroy runners a crashed review left in the ledger"
    )
    swp.set_defaults(handler=_cmd_sweep)
    probe = sub.add_parser(
        "probe-runner",
        help="live Sprites check without a model: protocol, or the review's exec sequence",
    )
    probe.add_argument("--deadline-seconds", type=float, default=120.0)
    probe.add_argument(
        "--sequence",
        choices=tuple(_PROBE_SEQUENCES),
        default="protocol",
        help="protocol: tool check, framing, 3 MiB stdin; review: tool check, "
        "upload, unpack and tools, exactly as a review runs them",
    )
    probe.add_argument("--tarball", help="--sequence review: a local .tar.gz checkout")
    probe.add_argument(
        "--event",
        help="--sequence review: fetch the head-SHA tarball via the GitHub App",
    )
    probe.add_argument(
        "--tools",
        choices=("trivial", "review"),
        default="trivial",
        help="--sequence review: a trivial file count, or the review's default tools",
    )
    _events_arg(probe)
    _first_frame_arg(probe)
    probe.set_defaults(handler=_cmd_probe)
    return parser


def _first_frame_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--first-frame-seconds",
        type=_positive_seconds,
        default=FIRST_FRAME_BUDGET_S,
        help="fail an exec that sends no input if no output byte arrives in this time",
    )


def _positive_seconds(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return value


def _events_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--events", help="telemetry JSONL file (default: under <state dir>/telemetry/)"
    )


_ERRORS: tuple[tuple[type[Exception], int], ...] = (
    (UsageError, EXIT_USAGE),
    (ReviewInProgressError, EXIT_USAGE),
    (BoundaryError, EXIT_BOUNDARY),
)


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    sprites_factory: Callable[[Mapping[str, str]], SpritesApi] | None = None,
    openrouter_factory: Callable[[str, CallLimits], OpenRouterProvider] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if sprites_factory is not None:
        args.sprites_factory = sprites_factory
    if openrouter_factory is not None:
        args.openrouter_factory = openrouter_factory
    handler: Callable[[argparse.Namespace, Mapping[str, str], TextIO], int] = (
        args.handler
    )
    try:
        return handler(args, os.environ if env is None else env, out or sys.stdout)
    except tuple(e for e, _ in _ERRORS) as exc:
        (err or sys.stderr).write(f"atlas_reviewer: {exc}\n")
        return next(code for kind, code in _ERRORS if isinstance(exc, kind))
