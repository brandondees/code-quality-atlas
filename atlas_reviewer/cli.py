# SPDX-License-Identifier: MIT
"""Operator entry point: `python -m atlas_reviewer {review,agentic-review,sweep,eval,probe-runner}`.

`review --dry-run` needs no credentials and no network: GitHub is a fixture
directory, the runner is the in-memory fake, the provider is offline.
Live mode reads credentials from the environment variables named below and
hands each one only to the adapter that needs it. Live model inference is
off unless `--provider openrouter --allow-live-inference` are both given.

Every live command records lifecycle telemetry (`atlas_reviewer.telemetry`)
to a JSONL file: `--events PATH`, or by default
`<state dir>/telemetry/<command>-<UTC time to the microsecond>-<random>.jsonl`,
named only once the review lock is held. A dry run writes one only when
`--events` is given. Event text, the probe report and stderr pass through
a redactor holding every credential value from the environment and every
installation token minted during the run.
"""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import math
import os
import re
import secrets
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO, cast

from atlas_reviewer.agentic_config import ENV as AGENTIC_ENV
from atlas_reviewer.attestation import AttemptLedger
from atlas_reviewer.bridge_staging import fetch_sources
from atlas_reviewer.budget import (
    BUDGET_CEILING_USD,
    MAX_CALLS_CEILING,
    CallLimits,
    ReviewBudget,
)
from atlas_reviewer.clock import SystemClock
from atlas_reviewer.controller import (
    DEFAULT_DIFF_CHARS_PER_CALL,
    MAX_MODEL_CALLS,
    MAX_TARBALL_BYTES,
    Deps,
    ReviewConfig,
    run_review,
)
from atlas_reviewer.coordinator import (
    limits_for_lens,
    model_for_lens,
    render_draft,
    review_lenses,
)
from atlas_reviewer.diffs import diff_paths
from atlas_reviewer.domain import (
    CleanupStatus,
    InvalidEventError,
    PrEvent,
    RunnerReport,
    RunnerStatus,
    SourceKey,
    SourceKind,
)
from atlas_reviewer.draft import telemetry_section
from atlas_reviewer.eval_harness import EvalFormatError, load_directory
from atlas_reviewer.fakes import FakeSprites, MemoryLedger
from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.github_auth import READ_PERMISSIONS, AppInstallationTokens
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.harness import SkillBundleHarness, load_bundle
from atlas_reviewer.http import UrllibStreamingTransport, UrllibTransport
from atlas_reviewer.instrumented import InstrumentedGitHub
from atlas_reviewer.interpreter import TrustedPython
from atlas_reviewer.ledger import (
    FileLedger,
    ReviewInProgressError,
    make_private_dirs,
    single_review_lock,
)
from atlas_reviewer.lens_loop import AgenticLimits, FinalReply, LensModel, TurnRequest
from atlas_reviewer.lenses import LensLibrary, LensStatus
from atlas_reviewer.openrouter import KEY_LIMIT_MAX_USD, OpenRouterProvider
from atlas_reviewer.picker import Depth, picker_instructions, select_agentic_lenses
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    ModelProvider,
    PickRequest,
    SpritesApi,
)
from atlas_reviewer.prompt import RepoText, UntrustedBlock
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import (
    DEFAULT_TOOLS,
    FIRST_FRAME_BUDGET_S,
    TRIVIAL_TOOL,
    Diagnostic,
    RunnerJob,
    Swept,
    ToolAbsent,
    ToolRan,
    ToolResult,
    event_runner_name,
    probe_runner,
    run_disposable,
    runner_name,
    sweep,
)
from atlas_reviewer.sprites_api import RUNNER_PREFIX, SpritesClient
from atlas_reviewer.stops import raise_if_stopped
from atlas_reviewer.telemetry import JsonlSink, Telemetry
from atlas_reviewer.tracing import (
    acquire_shared,
    header_values,
    opening_trace,
    release_shared,
    shared_trace,
    shutdown_shared,
    validate_export,
)
from atlas_reviewer.verdict import ReviewEvent, Verdict

ENV_APP_ID = "ATLAS_GITHUB_APP_ID"
ENV_APP_KEY = "ATLAS_GITHUB_APP_PRIVATE_KEY"
ENV_INSTALLATION_ID = "ATLAS_GITHUB_INSTALLATION_ID"
# A read-only installation token minted by the webhook parent. When it is
# set, the review does not read the App private key.
ENV_INSTALLATION_TOKEN = "ATLAS_GITHUB_INSTALLATION_TOKEN"
ENV_SPRITES_TOKEN = "ATLAS_SPRITES_TOKEN"
ENV_OPENROUTER_KEY = "ATLAS_OPENROUTER_API_KEY"
ENV_STATE_DIR = "ATLAS_REVIEWER_STATE_DIR"
DEFAULT_STATE_DIR = Path(".atlas-reviewer-state")
PROVIDER_CHOICES = ("offline", "openrouter")
SECRET_ENV = (ENV_APP_KEY, ENV_SPRITES_TOKEN, ENV_OPENROUTER_KEY)

EXIT_OK, EXIT_USAGE, EXIT_BOUNDARY, EXIT_INCOMPLETE = 0, 2, 3, 4
EXIT_CHANGES_REQUESTED = 5


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
    kinds = {k.value: k for k in SourceKind if k is not SourceKind.LISTING}
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
    if not (raw.isascii() and raw.isdigit() and int(raw) > 0):
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
    limits: CallLimits,
) -> ModelProvider:
    if args.provider == "offline":
        return OfflineProvider()
    if args.dry_run:
        raise UsageError("--dry-run is offline-only; drop --provider openrouter")
    if not args.allow_live_inference:
        raise UsageError(
            "live inference is off: pass --allow-live-inference with --provider openrouter"
        )
    provider = openrouter(_require_env(env, ENV_OPENROUTER_KEY), limits)
    if isinstance(provider, OpenRouterProvider):
        provider.key_ceiling = _key_ceiling(args, env)
    telemetry.span("model preflight", "key status", provider.preflight)
    return provider


def _live_openrouter(key: str, limits: CallLimits) -> OpenRouterProvider:
    return OpenRouterProvider(UrllibTransport(), key, limits=limits, sleep=time.sleep)


class _Credentials:
    """Every credential value one invocation holds: the environment's, and
    each installation token minted since. `redactor` reads the minted ones
    on every call, so telemetry, the probe report and stderr written after
    a mint all lose the token."""

    def __init__(self, env: Mapping[str, str]) -> None:
        values = [env.get(name, "") for name in SECRET_ENV]
        values.append(_pem(env.get(ENV_APP_KEY, "")))
        values.append(env.get(ENV_INSTALLATION_TOKEN, ""))
        values.extend(header_values(env))
        self._sources: list[Callable[[], Sequence[str]]] = []
        self.redactor = Redactor(
            tuple(dict.fromkeys(v for v in values if v)), sources=(self._minted,)
        )

    def register(self, source: Callable[[], Sequence[str]]) -> None:
        self._sources.append(source)

    def scrub(self, text: str) -> str:
        return self.redactor(text).text

    def _minted(self) -> tuple[str, ...]:
        return tuple(s for source in self._sources for s in source())


@dataclass
class _Run:
    """One invocation's state that is not a command-line option."""

    env: Mapping[str, str]
    out: TextIO
    err: TextIO
    credentials: _Credentials
    telemetry: Telemetry | None = None


def _review_lock(
    args: argparse.Namespace, env: Mapping[str, str]
) -> AbstractContextManager[None]:
    state_dir = _state_dir(args, env)
    try:
        make_private_dirs(state_dir)
    except OSError as exc:
        raise UsageError(f"--state-dir {state_dir}: cannot be created ({exc})") from exc
    return single_review_lock(state_dir / "review.lock")


def _telemetry(
    args: argparse.Namespace,
    run: _Run,
    command: str,
    claims: ExitStack,
    *,
    default_file: bool,
) -> Telemetry:
    """Call with the review lock held: a contender that loses the lock must
    not have created, let alone written, a telemetry file. An explicit
    `--events` file is claimed before it is opened, for the same reason.
    The sink's descriptor and the claim are released when `claims` closes."""
    clock = SystemClock()
    stamp = f"{clock.now():%Y%m%dT%H%M%S.%fZ}-{secrets.token_hex(4)}"
    default = _state_dir(args, run.env) / "telemetry" / f"{command}-{stamp}.jsonl"
    path = Path(args.events) if args.events else (default if default_file else None)
    if path is None:
        return Telemetry(clock, None, scrub=run.credentials.scrub)
    if args.events:
        claims.enter_context(_claimed(path))
    try:
        sink = claims.enter_context(JsonlSink(path))
    except OSError as exc:
        raise UsageError(f"telemetry file {path}: {exc}") from exc
    return Telemetry(clock, sink, scrub=run.credentials.scrub)


@contextmanager
def _claimed(path: Path) -> Iterator[None]:
    """Hold `<path>.lock` for this run. The review lock is per state
    directory, so two runs with different state directories could still
    interleave their events in one explicit `--events` file. Locking a
    sibling leaves a refused run with no telemetry file; the lock file
    stays, since unlinking one another run may be opening would race."""
    lock = path.with_name(f"{path.name}.lock")
    try:
        make_private_dirs(path.parent)
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError as exc:
        raise UsageError(f"telemetry file {path}: {exc}") from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UsageError(f"telemetry file {path} is in use by another run") from exc
        yield
    finally:
        os.close(fd)


def _telemetry_line(run: _Run, telemetry: Telemetry) -> str:
    """Scrubbed like any other stderr text: an `--events` path is free text
    that could hold a credential value."""
    sink = telemetry.sink
    path = str(sink.path) if isinstance(sink, JsonlSink) else "(not written)"
    return (
        f"telemetry: {len(telemetry.events)} event(s), {run.credentials.scrub(path)}\n"
    )


def _dry_run_wiring(
    args: argparse.Namespace,
    event_path: Path,
    provider: ModelProvider,
    telemetry: Telemetry,
) -> _Wiring:
    fixtures = Path(args.fixtures) if args.fixtures else event_path.parent
    if not fixtures.is_dir():
        raise UsageError(f"fixture directory {fixtures} does not exist")
    redactor = Redactor()
    clock = SystemClock()
    deps = Deps(
        github=FixtureGitHub(fixtures),
        sprites=_scripted_runner(fixtures / "runner-script.json"),
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


def _scripted_runner(path: Path) -> FakeSprites:
    if not path.is_file():
        return FakeSprites.from_script({})
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read runner script {path}: {exc}") from exc
    if not isinstance(script, dict):
        raise UsageError(f"runner script {path} must hold a JSON object")
    try:
        return FakeSprites.from_script(script)
    except (KeyError, TypeError, ValueError) as exc:
        raise UsageError(f"invalid runner script {path}: {exc!r}") from exc


class _FixedToken:
    """A token the parent already minted. It cannot mint another.

    GitHub installation tokens last one hour. The service stops the child
    at 1,200 seconds, which is inside that hour, so this token is not
    refreshed."""

    def __init__(self, token: str) -> None:
        self._token = token

    def token(self) -> str:
        return self._token

    def secrets(self) -> tuple[str, ...]:
        return (self._token,)


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
    runner: str,
    credentials: _Credentials,
) -> _Wiring:
    _require_env(env, ENV_SPRITES_TOKEN)
    clock = SystemClock()
    transport = UrllibTransport()
    fixed = env.get(ENV_INSTALLATION_TOKEN, "")
    tokens: _FixedToken | AppInstallationTokens
    if fixed:
        tokens = _FixedToken(fixed)
    else:
        _require_env(env, ENV_APP_KEY)
        tokens = _app_tokens(env, event, args.include_issues, transport)
    credentials.register(tokens.secrets)
    redactor = credentials.redactor
    sprites = args.sprites_factory(env)
    _require_runner_absent(sprites, runner)
    deps = Deps(
        github=GitHubClient(transport, tokens),
        sprites=sprites,
        ledger=FileLedger(_state_dir(args, env) / "runners.ledger"),
        harness=SkillBundleHarness(provider, load_bundle(), redactor),
        clock=clock,
        redactor=redactor,
        runner_name=lambda: runner,
        telemetry=telemetry,
    )
    return _Wiring(deps, f"live (GitHub App + Sprites; provider {provider.name})")


def _require_runner_absent(api: SpritesApi, name: str) -> None:
    """The name comes from the event, so a Sprite that already holds it was
    left by an earlier review of this commit or belongs to one still
    running. Neither is a fresh runner."""
    if api.exists(name):
        raise BoundaryError(
            f"a Sprite named {name} already exists. If no review of this commit "
            f"is running, delete it with `sweep --runner {name} --force-live`, "
            "then review again"
        )


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


def _cmd_review(args: argparse.Namespace, run: _Run) -> int:
    env, out, err = run.env, run.out, run.err
    _key_ceiling(args, env)
    # ATLAS_* limit variables are not read here, and this command does not
    # accept the agentic limit flags. D25's one-shot ceilings stay, and a
    # value such as ATLAS_MAX_CALLS=10 must not refuse this command. The
    # lens entry point is what applies the variables.
    event_path = Path(args.event)
    event = load_event(event_path)
    _review_config(args, "check")
    _check_out_path(args.out)
    with _review_lock(args, env), ExitStack() as claims:
        telemetry = _telemetry(
            args, run, "review", claims, default_file=not args.dry_run
        )
        run.telemetry = telemetry
        provider = _select_provider(
            args,
            env,
            args.openrouter_factory,
            telemetry,
            CallLimits(max_calls=args.max_model_calls),
        )
        if args.dry_run:
            wiring = _dry_run_wiring(args, event_path, provider, telemetry)
        else:
            runner = event_runner_name(event)
            err.write(f"atlas_reviewer: runner Sprite for this review: {runner}\n")
            wiring = _live_wiring(
                args, env, event, provider, telemetry, runner, run.credentials
            )
        outcome = run_review(event, wiring.deps, _review_config(args, wiring.mode))
    written = _emit(outcome.draft, args.out, out, err)
    verdict = outcome.verdict
    # Stdout carries the draft unless it went to a file; the summary must
    # not be appended to a draft someone pipes on.
    (out if written else err).write(
        f"{_telemetry_line(run, telemetry)}"
        f"review event: {verdict.event.value}; coverage_complete="
        f"{str(verdict.coverage_complete).lower()}; unreviewed_files="
        f"{len(verdict.coverage.unreviewed)}\n"
    )
    return review_exit(verdict)


AGENTIC_POOL = 4
_BODY_MARKER = re.compile(r"=== lens body begins: (\S+) \(sha256 ([0-9a-f]{64})\) ===")


class _DryRunLensModel:
    """A lens turn that acknowledges the delivered body and reports no
    findings. It calls no tool, so a dry run spends nothing and leaves
    file coverage incomplete."""

    name = "dry-run"

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        return Decimal("0.01")

    def turn(self, request: TurnRequest) -> FinalReply:
        system = getattr(request, "system", "")
        match = _BODY_MARKER.search(system)
        payload: dict[str, object] = {"findings": []}
        if match is not None:
            payload = {
                "lens": match.group(1),
                "body_sha256": match.group(2),
                "findings": [],
            }
        return FinalReply(json.dumps(payload), Decimal("0.01"))


def _cmd_agentic_review(args: argparse.Namespace, run: _Run) -> int:
    """Every selected lens, concurrently up to the pool, then one draft.

    The one-shot `review` command does not call this. A dry run uses the
    fixture directory and an in-memory runner and does not read credentials.
    """
    env, out, err = run.env, run.out, run.err
    limits = _agentic_limits(args, env)
    event = load_event(Path(args.event))
    _check_out_path(args.out)
    with _review_lock(args, env), ExitStack() as claims:
        telemetry = _telemetry(
            args, run, "agentic-review", claims, default_file=not args.dry_run
        )
        run.telemetry = telemetry
        lens_model: LensModel
        model_factory: Callable[[], LensModel] | None
        picker_provider: ModelProvider
        github: FixtureGitHub | GitHubClient
        if args.dry_run:
            fixtures = Path(args.fixtures) if args.fixtures else Path(args.event).parent
            if not fixtures.is_dir():
                raise UsageError(f"fixture directory {fixtures} does not exist")
            github = FixtureGitHub(fixtures)
            sprites = _scripted_runner(fixtures / "runner-script.json")
            redactor = Redactor()
            lens_model = _DryRunLensModel()
            model_factory = None
            picker_provider = OfflineProvider()
        else:
            provider = _select_provider(
                args, env, args.openrouter_factory, telemetry, _picker_limits(limits)
            )
            if not isinstance(provider, OpenRouterProvider):
                raise UsageError(
                    "agentic-review live mode needs --provider openrouter "
                    "--allow-live-inference"
                )
            github = _live_github(args, env, event, run.credentials)
            sprites = args.sprites_factory(env)
            redactor = run.credentials.redactor
            picker_provider = provider

            def live_model() -> LensModel:
                return cast(LensModel, model_for_lens(provider, limits))

            lens_model = live_model()
            model_factory = live_model

        clock = SystemClock()
        pull = github.get_pull(event.repo, event.pr_number)
        _require_head(pull, event, "the PR head is no longer the event SHA")
        diff = github.get_pull_diff(event.repo, event.pr_number)
        _require_head(
            github.get_pull(event.repo, event.pr_number),
            event,
            "the PR head moved while the diff was fetched",
        )
        base = pull.get("base") if isinstance(pull, dict) else None
        ref = base.get("ref") if isinstance(base, dict) else None
        if not isinstance(ref, str) or not ref:
            raise UsageError("the pull request has no base ref")
        trees = fetch_sources(github, event.repo, ref, event.head_sha)
        library = LensLibrary()
        depth = Depth(args.depth)
        harness = SkillBundleHarness(picker_provider, load_bundle(), redactor)

        def scrub(text: str) -> str:
            return redactor(text).text

        def run_picker() -> str:
            paths = diff_paths(diff)[:500]
            shown = "\n".join(paths) or "(no changed paths)"
            title = pull.get("title") if isinstance(pull, dict) else ""
            return harness.pick(
                PickRequest(
                    event.repo,
                    event.pr_number,
                    event.head_sha,
                    picker_instructions(depth),
                    (
                        UntrustedBlock("pull-request", redactor(str(title or ""))),
                        UntrustedBlock("changed-paths", RepoText(shown)),
                    ),
                )
            )

        acquire_shared()
        try:
            with opening_trace(None, scrub).review(
                event.repo, event.pr_number, event.head_sha
            ) as span:
                selection, plan = select_agentic_lenses(
                    depth,
                    None if depth is Depth.TRIAGE else run_picker,
                    library,
                    scrub=scrub,
                )
                names = tuple(loaded.name for loaded in plan.loaded)
                budget = getattr(picker_provider, "budget", None)
                picker_spend = (
                    (len(budget.calls), budget.committed_usd())
                    if isinstance(budget, ReviewBudget)
                    else (0, Decimal(0))
                )
                ledger = AttemptLedger(
                    _state_dir(args, env) / "attestation.ledger", clock
                )
                review = review_lenses(
                    event,
                    names,
                    diff,
                    trees,
                    library=library,
                    model=lens_model,
                    limits=limits,
                    ledger=ledger,
                    sprites=sprites,
                    runner_ledger=FileLedger(_state_dir(args, env) / "runners.ledger"),
                    redactor=redactor,
                    clock=clock,
                    telemetry=telemetry,
                    model_for=model_factory,
                    picker_spend=picker_spend,
                )
                review = replace(
                    review,
                    selection_note=selection.note,
                    not_picked=tuple(
                        (use.name, use.reason)
                        for use in plan.uses
                        if use.status is LensStatus.NOT_RUN
                    ),
                )
                span.set("atlas.review_event", review.event.value)
        finally:
            release_shared()
    written = _emit(render_draft(review, redactor), args.out, out, err)
    (out if written else err).write(
        f"{_telemetry_line(run, telemetry)}"
        f"review event: {review.event.value}; coverage_complete="
        f"{str(review.coverage_complete).lower()}; unreviewed_files="
        f"{len(review.unreviewed_paths)}; lenses={len(names)}; "
        f"not_run={len(review.not_picked)}\n"
    )
    if not review.coverage_complete:
        return EXIT_INCOMPLETE
    if review.proposed_event is ReviewEvent.REQUEST_CHANGES:
        return EXIT_CHANGES_REQUESTED
    return EXIT_OK


def _picker_limits(limits: AgenticLimits) -> CallLimits:
    """The picker's provider budget: no more calls or dollars than the
    agentic review allows, and never past the one-shot D25 ceilings."""
    resolved = limits.resolve()
    return CallLimits(
        max_calls=min(resolved.max_calls, MAX_CALLS_CEILING),
        budget_usd=min(resolved.reservation_usd, BUDGET_CEILING_USD),
    )


def _require_head(pull: object, event: PrEvent, why: str) -> None:
    """The diff endpoint serves the PR's current head; the lenses read
    files at `event.head_sha`. Refuse before any model call when the two
    can differ."""
    head = pull.get("head") if isinstance(pull, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if sha != event.head_sha:
        raise BoundaryError(f"{why}; no model call was made")


def _live_github(
    args: argparse.Namespace,
    env: Mapping[str, str],
    event: PrEvent,
    credentials: _Credentials,
) -> GitHubClient:
    transport = UrllibTransport()
    tokens = _app_tokens(env, event, args.include_issues, transport)
    credentials.register(tokens.secrets)
    return GitHubClient(transport, tokens)


def _agentic_limits(args: argparse.Namespace, env: Mapping[str, str]) -> AgenticLimits:
    flags = {name: getattr(args, name, None) for name in AGENTIC_ENV}
    try:
        limits = limits_for_lens(env, **flags)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    if flags.get("pool_size") is None and not env.get("ATLAS_POOL_SIZE"):
        limits = replace(limits, pool_size=AGENTIC_POOL)
        try:
            limits.resolve()
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
    return limits


def _key_ceiling(args: argparse.Namespace, env: Mapping[str, str]) -> Decimal:
    raw = getattr(args, "key_ceiling_usd", None)
    if raw == "":
        raise UsageError(
            "--key-ceiling-usd was given an empty value; set a positive number "
            "of dollars, or omit it to keep the $5.00 pilot ceiling"
        )
    if raw is None:
        raw = env.get("ATLAS_KEY_CEILING_USD")
    if raw is None or raw == "":
        return KEY_LIMIT_MAX_USD
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise UsageError(
            "the key ceiling must be a positive number of dollars "
            "(--key-ceiling-usd or ATLAS_KEY_CEILING_USD), "
            f"not {raw!r}"
        ) from None
    if not value.is_finite() or value <= 0:
        raise UsageError(
            "the key ceiling must be a positive number of dollars "
            f"(--key-ceiling-usd or ATLAS_KEY_CEILING_USD), not {raw!r}"
        )
    return value


def review_exit(verdict: Verdict) -> int:
    """`review`'s exit code, enough to gate a pipeline on: 4 when file
    coverage is incomplete (D36), whatever the model proposed; with
    complete coverage, 5 when the review requests changes, else 0."""
    if not verdict.coverage_complete:
        return EXIT_INCOMPLETE
    if verdict.event is ReviewEvent.REQUEST_CHANGES:
        return EXIT_CHANGES_REQUESTED
    return EXIT_OK


def _check_out_path(out_path: str | None) -> None:
    """Refuse an unwritable `--out` before the review spends anything."""
    if out_path is None:
        return
    path = Path(out_path)
    parent = path.parent
    if path.is_symlink() and not path.exists():
        raise UsageError(f"--out {out_path}: a symlink to a missing target")
    if path.is_dir() or not parent.is_dir():
        raise UsageError(f"--out {out_path}: not a file in an existing directory")
    target = path if path.exists() else parent
    if not os.access(target, os.W_OK):
        raise UsageError(f"--out {out_path}: not writable")


def _emit(draft: str, out_path: str | None, out: TextIO, err: TextIO) -> bool:
    """True if the draft went to `out_path`. A failed write still delivers
    the draft on stdout and leaves the exit code to the review's result:
    the review finished, so a retry would only repeat it."""
    if out_path is None:
        out.write(draft)
        return False
    try:
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(draft)
    except OSError as exc:
        out.write(draft)
        err.write(
            f"atlas_reviewer: could not write --out {out_path} ({exc}); "
            "the draft went to stdout\n"
        )
        return False
    out.write(f"review draft written to {out_path}\n")
    return True


def _live_sprites(env: Mapping[str, str]) -> SpritesApi:
    return SpritesClient(
        UrllibStreamingTransport(), _require_env(env, ENV_SPRITES_TOKEN)
    )


def _cmd_sweep(args: argparse.Namespace, run: _Run) -> int:
    env, out = run.env, run.out
    named = _named_runners(args)
    api = args.sprites_factory(env)
    # The ledger lists a live review's runner too; sweeping during a review
    # would destroy it mid-run, so sweep waits its turn like review does.
    with _review_lock(args, env):
        ledger = FileLedger(_state_dir(args, env) / "runners.ledger")
        _require_force_live(args, ledger.pending())
        for name in named:
            ledger.record(name)
        results = sweep(api, ledger)
    out.writelines(f"{name}: {_swept_line(r)}\n" for name, r in results.items())
    out.write(f"{len(results)} runner(s) in the ledger\n")
    verified = all(
        r.cleanup is CleanupStatus.DESTROYED_VERIFIED for r in results.values()
    )
    return EXIT_OK if verified else EXIT_BOUNDARY


def _swept_line(result: Swept) -> str:
    if result.cleanup is CleanupStatus.DESTROYED_VERIFIED and not result.deleted:
        return "already absent, nothing deleted (verified absent)"
    return result.cleanup.value


_RUNNER_NAME = re.compile(re.escape(RUNNER_PREFIX) + r"[a-z0-9-]+")


def _named_runners(args: argparse.Namespace) -> list[str]:
    """Runners to add to this machine's ledger before sweeping it: a review
    on another machine recorded them in a ledger this one cannot read."""
    names = list(args.runner)
    if args.event:
        names.append(event_runner_name(load_event(Path(args.event))))
    for name in names:
        if not _RUNNER_NAME.fullmatch(name):
            raise UsageError(
                f"--runner must be a {RUNNER_PREFIX}* name of lowercase letters, "
                f"digits and hyphens, got {name!r}"
            )
    if names and not args.force_live:
        raise UsageError(
            "no lock covers a runner recorded on another machine, so a review "
            "still running there would lose its runner mid-run. Check that no "
            "review of that commit is running, then add --force-live"
        )
    return names


def _require_force_live(args: argparse.Namespace, pending: Sequence[str]) -> None:
    """A ledger entry does not show this machine's create made the Sprite:
    a create of unknown outcome keeps its name, and a review of the same
    commit on another machine may have created that name since."""
    if pending and not args.force_live:
        raise UsageError(
            f"the ledger lists {len(pending)} runner(s). A name whose create "
            "was never confirmed may now be the runner of a review of that "
            "commit on another machine, and no lock covers that. Check that "
            "no such review is running, then add --force-live"
        )


def _cmd_probe(args: argparse.Namespace, run: _Run) -> int:
    env, out = run.env, run.out
    sequence = _PROBE_SEQUENCES[args.sequence]
    report = io.StringIO()
    with _review_lock(args, env), ExitStack() as claims:
        telemetry = _telemetry(
            args, run, f"probe-{args.sequence}", claims, default_file=True
        )
        run.telemetry = telemetry
        try:
            usable = sequence(args, run, report, telemetry)
        finally:
            out.write(run.credentials.scrub(report.getvalue()))
    out.write(f"\n{telemetry_section(telemetry.events)}\n\n")
    out.write(_telemetry_line(run, telemetry))
    if not usable:
        out.write("probe: FAILED -- the runner is not usable as probed\n")
    return EXIT_OK if usable else EXIT_BOUNDARY


def _probe_protocol(
    args: argparse.Namespace, run: _Run, out: TextIO, telemetry: Telemetry
) -> bool:
    env = run.env
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
    out.write(f"outbound connection: {outcome.egress_check}\n")
    return (
        outcome.report.status is RunnerStatus.COMPLETED
        and outcome.stdin_check.startswith("ok:")
        and not outcome.egress_check.startswith("OPEN")
    )


def _probe_review_sequence(
    args: argparse.Namespace, run: _Run, out: TextIO, telemetry: Telemetry
) -> bool:
    """The review's exact exec sequence (tool check, upload, unpack, tools)
    on a real checkout, with no model call and no evidence gathering."""
    env, credentials = run.env, run.credentials
    tarball = _probe_source(args, env, telemetry, credentials)
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
    redactor = credentials.redactor
    out.writelines(f"{_tool_report(r, redactor)}\n" for r in outcome.results)
    out.write(f"{_python_report(outcome.python)}\n")
    out.writelines(f"{_diagnostic_report(d)}\n" for d in outcome.diagnostics)
    return outcome.report.status is RunnerStatus.COMPLETED


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
    args: argparse.Namespace,
    env: Mapping[str, str],
    telemetry: Telemetry,
    credentials: _Credentials,
) -> bytes:
    if args.tarball:
        return _read_tarball(Path(args.tarball))
    if not args.event:
        raise UsageError("--sequence review needs --tarball FILE or --event FILE")
    event = load_event(Path(args.event))
    transport = UrllibTransport()
    tokens = _app_tokens(env, event, False, transport)
    credentials.register(tokens.secrets)
    github = InstrumentedGitHub(GitHubClient(transport, tokens), telemetry)
    return github.get_tarball(event.repo, event.head_sha)


def _read_tarball(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise UsageError(f"cannot read tarball {path}: {exc}") from exc


def _write_report(r: RunnerReport, out: TextIO) -> None:
    out.write(f"runner: {r.runner_name}\nstatus: {r.status.value}\n")
    out.write(f"cleanup: {r.cleanup.value}\nnote: {r.note}\n")


def _tool_report(result: ToolResult, redactor: Redactor) -> str:
    match result:
        case ToolRan(tool=tool, version=version, exit_code=code, output=output):
            shown = redactor(output).text[-300:]
            return f"tool {tool.name} ({version}): exit {code}; output: {shown!r}"
        case ToolAbsent(tool=tool, detail=detail):
            return f"tool {tool.name}: not run -- {detail}"
    raise TypeError(f"not a tool result: {result!r}")  # pragma: no cover


_PROBE_SEQUENCES: dict[
    str,
    Callable[[argparse.Namespace, _Run, TextIO, Telemetry], bool],
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
        "--deadline-seconds",
        type=_positive_seconds,
        default=600.0,
        help="external runner deadline",
    )
    rev.add_argument(
        "--max-model-calls",
        type=int,
        default=MAX_MODEL_CALLS,
        help=(
            "model calls per review, retries included: one for the lens picker "
            "(except at triage depth, or when no picked lens could fit), the rest "
            f"for diff parts (1-{MAX_MODEL_CALLS})"
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
    _key_ceiling_arg(rev)
    rev.add_argument("--provider", choices=PROVIDER_CHOICES, default="offline")
    rev.add_argument(
        "--allow-live-inference",
        action="store_true",
        help="required with --provider openrouter; spends real money (capped)",
    )
    _first_frame_arg(rev)
    rev.set_defaults(handler=_cmd_review)
    ag = sub.add_parser(
        "agentic-review",
        help="review one PR with every selected lens and write one draft",
    )
    ag.add_argument(
        "--event", required=True, help="JSON file with repo, pr_number, head_sha"
    )
    ag.add_argument(
        "--dry-run",
        action="store_true",
        help="fixtures + in-memory runner; no credentials and no model spend",
    )
    ag.add_argument(
        "--fixtures",
        help="fixture directory for --dry-run (default: the event file's directory)",
    )
    ag.add_argument("--out", help="write the draft here instead of stdout")
    ag.add_argument(
        "--include-issues",
        action="store_true",
        help="opt in to fetching issues the PR closes",
    )
    ag.add_argument(
        "--depth",
        choices=[d.value for d in Depth],
        default=Depth.REVIEW.value,
        help="triage runs the critical tier and does not call the picker",
    )
    ag.add_argument(
        "--pool-size",
        dest="pool_size",
        default=None,
        help=(
            "lenses at once, 1 to 16 "
            f"(env {AGENTIC_ENV['pool_size']}; {AGENTIC_POOL} when unset)"
        ),
    )
    _events_arg(ag)
    _agentic_limit_args(ag)
    _key_ceiling_arg(ag)
    ag.add_argument("--provider", choices=PROVIDER_CHOICES, default="offline")
    ag.add_argument(
        "--allow-live-inference",
        action="store_true",
        help="required with --provider openrouter; spends real money (capped)",
    )
    ag.set_defaults(handler=_cmd_agentic_review)
    swp = sub.add_parser(
        "sweep", help="destroy runners a crashed review left in the ledger"
    )
    swp.add_argument(
        "--runner",
        action="append",
        default=[],
        metavar="NAME",
        help="also destroy this runner, recorded in another state dir's ledger",
    )
    swp.add_argument(
        "--event",
        help="also destroy the runner a review of this event file is named",
    )
    swp.add_argument(
        "--force-live",
        action="store_true",
        help="required to delete anything: you checked no review using it runs",
    )
    swp.set_defaults(handler=_cmd_sweep)
    ev = sub.add_parser(
        "eval",
        help="score recorded reviews against reference fixtures (offline)",
    )
    ev.add_argument(
        "--fixtures",
        required=True,
        help="directory of reference rows and optional candidate pairs",
    )
    ev.add_argument(
        "--head",
        help="commit the gate must have a passing pair for",
    )
    ev.add_argument(
        "--gate",
        action="store_true",
        help="exit 1 unless every row is a passing pair, one matches --head, "
        "and one records over_context_window",
    )
    ev.set_defaults(handler=_cmd_eval)
    probe = sub.add_parser(
        "probe-runner",
        help="live Sprites check without a model: protocol, or the review's exec sequence",
    )
    probe.add_argument("--deadline-seconds", type=_positive_seconds, default=120.0)
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
    if not (math.isfinite(value) and value > 0):
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return value


def _key_ceiling_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--key-ceiling-usd",
        default=None,
        help=(
            "most the OpenRouter key's own credit limit may be "
            f"(default ${KEY_LIMIT_MAX_USD}; env ATLAS_KEY_CEILING_USD). "
            "A preflight that finds a higher limit names this setting."
        ),
    )


def _agentic_limit_args(parser: argparse.ArgumentParser) -> None:
    """The agentic limit flags. `agentic-review` applies them. The one-shot
    `review` command does not accept them."""
    note = "This command applies it."
    flags = (
        ("--reservation-usd", "reservation_usd", "per-review dollar reservation"),
        ("--max-calls", "max_calls", "model calls per agentic review"),
        ("--max-turns", "max_turns", "model turns per lens"),
        ("--lens-wall-seconds", "lens_wall_s", "seconds per lens"),
        ("--review-wall-seconds", "review_wall_s", "seconds per review"),
        (
            "--max-input-tokens",
            "max_input_tokens",
            "per-call input cap; default is the model's context minus the output reserve",
        ),
        (
            "--max-output-tokens",
            "max_output_tokens",
            "per-call output cap; default is the model's completion limit",
        ),
        (
            "--reasoning-max-tokens",
            "reasoning_max_tokens",
            "reasoning hint sent on the request; the reservation does not depend on it",
        ),
    )
    for flag, name, meaning in flags:
        parser.add_argument(
            flag,
            dest=name,
            default=None,
            help=(f"{meaning} (env {AGENTIC_ENV[name]}; default when unset). {note}"),
        )


def _events_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--events", help="telemetry JSONL file (default: under <state dir>/telemetry/)"
    )


def _cmd_eval(args: argparse.Namespace, run: _Run) -> int:
    """Score recorded fixtures. No model call and no network."""
    try:
        report = load_directory(Path(args.fixtures), head=args.head)
    except EvalFormatError as exc:
        raise UsageError(str(exc)) from exc
    run.out.write(json.dumps(report, indent=2) + "\n")
    if args.gate and not report["gate_pass"]:
        return 1
    return EXIT_OK


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
    env = os.environ if env is None else env
    try:
        validate_export(env)
    except ValueError as exc:
        (err or sys.stderr).write(f"atlas_reviewer: {exc}\n")
        return EXIT_USAGE
    run = _Run(env, out or sys.stdout, err or sys.stderr, _Credentials(env))
    shared_trace(env, run.credentials.scrub)
    handler: Callable[[argparse.Namespace, _Run], int] = args.handler
    try:
        code = handler(args, run)
    except tuple(e for e, _ in _ERRORS) as exc:
        run.err.write(f"atlas_reviewer: {run.credentials.scrub(str(exc))}\n")
        if run.telemetry is not None:
            run.err.write(_telemetry_line(run, run.telemetry))
        code = next(mapped for kind, mapped in _ERRORS if isinstance(exc, kind))
    finally:
        # The review raises a held stop right after its runner phase.
        # One still pending here is a command that ended in an error,
        # including an exception this handler does not map.
        shutdown_shared()
        raise_if_stopped()
    return code
