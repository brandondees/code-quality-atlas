# SPDX-License-Identifier: MIT
"""Operator entry point: `python -m atlas_reviewer {review,sweep,probe-runner}`.

`review --dry-run` needs no credentials and no network: GitHub is a fixture
directory, the runner is the in-memory fake, the provider is offline.
Live mode reads credentials from the environment variables named below and
hands each one only to the adapter that needs it. Live model inference is
off unless `--provider openrouter --allow-live-inference` are both given.
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

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.controller import DEFAULT_TOOLS, Deps, ReviewConfig, review
from atlas_reviewer.domain import InvalidEventError, PrEvent, SourceKey, SourceKind
from atlas_reviewer.fakes import FakeSprites, MemoryLedger
from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.github_auth import READ_PERMISSIONS, AppInstallationTokens
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.harness import SkillBundleHarness, load_bundle
from atlas_reviewer.http import UrllibTransport
from atlas_reviewer.ledger import FileLedger, ReviewInProgressError, single_review_lock
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.ports import BoundaryError, Clock, ModelProvider, SpritesApi
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import probe_runner, runner_name, sweep
from atlas_reviewer.sprites_api import SpritesClient

ENV_APP_ID = "ATLAS_GITHUB_APP_ID"
ENV_APP_KEY = "ATLAS_GITHUB_APP_PRIVATE_KEY"
ENV_INSTALLATION_ID = "ATLAS_GITHUB_INSTALLATION_ID"
ENV_SPRITES_TOKEN = "ATLAS_SPRITES_TOKEN"
ENV_OPENROUTER_KEY = "ATLAS_OPENROUTER_API_KEY"
ENV_STATE_DIR = "ATLAS_REVIEWER_STATE_DIR"
DEFAULT_STATE_DIR = Path(".atlas-reviewer-state")
PROVIDER_CHOICES = ("offline", "openrouter")

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
    openrouter: Callable[[str], OpenRouterProvider],
) -> ModelProvider:
    if args.provider == "offline":
        return OfflineProvider()
    if args.dry_run:
        raise UsageError("--dry-run is offline-only; drop --provider openrouter")
    if not args.allow_live_inference:
        raise UsageError(
            "live inference is off: pass --allow-live-inference with --provider openrouter"
        )
    provider = openrouter(_require_env(env, ENV_OPENROUTER_KEY))
    provider.preflight()
    return provider


def _live_openrouter(key: str) -> OpenRouterProvider:
    return OpenRouterProvider(UrllibTransport(), key, sleep=time.sleep)


def _dry_run_wiring(
    args: argparse.Namespace, event_path: Path, provider: ModelProvider
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
    )
    return _Wiring(
        deps, f"dry run (fixtures: {fixtures}; fake runner; provider {provider.name})"
    )


def _live_wiring(
    args: argparse.Namespace,
    env: Mapping[str, str],
    event: PrEvent,
    provider: ModelProvider,
) -> _Wiring:
    private_key = _pem(_require_env(env, ENV_APP_KEY))
    sprites_token = _require_env(env, ENV_SPRITES_TOKEN)
    clock = SystemClock()
    transport = UrllibTransport()
    tokens = AppInstallationTokens(
        transport,
        clock,
        app_id=_require_env(env, ENV_APP_ID),
        private_key=private_key,
        installation_id=_installation_id(env),
        permissions=_permissions(args.include_issues),
        repositories=(event.repo.split("/", 1)[1],),
    )
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
    )
    return _Wiring(deps, f"live (GitHub App + Sprites; provider {provider.name})")


def _permissions(include_issues: bool) -> dict[str, str]:
    base = dict(READ_PERMISSIONS)
    return {**base, "issues": "read"} if include_issues else base


def _cmd_review(args: argparse.Namespace, env: Mapping[str, str], out: TextIO) -> int:
    event_path = Path(args.event)
    event = load_event(event_path)
    provider = _select_provider(args, env, args.openrouter_factory)
    wiring = (
        _dry_run_wiring(args, event_path, provider)
        if args.dry_run
        else _live_wiring(args, env, event, provider)
    )
    config = ReviewConfig(
        expected=parse_expected(args.expect),
        include_issues=args.include_issues,
        deadline_s=args.deadline_seconds,
        mode=wiring.mode,
    )
    with single_review_lock(_state_dir(args, env) / "review.lock"):
        draft = review(event, wiring.deps, config)
    _emit(draft, args.out, out)
    return EXIT_OK


def _emit(draft: str, out_path: str | None, out: TextIO) -> None:
    if out_path is None:
        out.write(draft)
        return
    Path(out_path).write_text(draft, encoding="utf-8")
    out.write(f"review draft written to {out_path}\n")


def _live_sprites(env: Mapping[str, str]) -> SpritesApi:
    return SpritesClient(UrllibTransport(), _require_env(env, ENV_SPRITES_TOKEN))


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
    api = args.sprites_factory(env)
    clock: Clock = SystemClock()
    with single_review_lock(_state_dir(args, env) / "review.lock"):
        outcome = probe_runner(
            api,
            FileLedger(_state_dir(args, env) / "runners.ledger"),
            DEFAULT_TOOLS,
            name=runner_name(clock),
            deadline_s=args.deadline_seconds,
            clock=clock,
        )
    r = outcome.report
    out.write(f"runner: {r.runner_name}\nstatus: {r.status.value}\n")
    out.write(f"cleanup: {r.cleanup.value}\nnote: {r.note}\n")
    out.writelines(
        f"tool {b}: {'present' if ok else 'ABSENT'}\n"
        for b, ok in outcome.available.items()
    )
    out.write(f"raw exec response sample: {outcome.framing_sample[:200]!r}\n")
    out.write(f"stdin round-trip: {outcome.stdin_check}\n")
    return EXIT_OK


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
    rev.add_argument("--provider", choices=PROVIDER_CHOICES, default="offline")
    rev.add_argument(
        "--allow-live-inference",
        action="store_true",
        help="required with --provider openrouter; spends real money (capped)",
    )
    rev.set_defaults(handler=_cmd_review)
    swp = sub.add_parser(
        "sweep", help="destroy runners a crashed review left in the ledger"
    )
    swp.set_defaults(handler=_cmd_sweep)
    probe = sub.add_parser(
        "probe-runner",
        help="live Sprites protocol check: create, deny-all, probe tools, destroy",
    )
    probe.add_argument("--deadline-seconds", type=float, default=120.0)
    probe.set_defaults(handler=_cmd_probe)
    return parser


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
    openrouter_factory: Callable[[str], OpenRouterProvider] | None = None,
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
