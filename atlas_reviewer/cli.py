# SPDX-License-Identifier: MIT
"""Operator entry point: `python -m atlas_reviewer {review,sweep}`.

`review --dry-run` needs no credentials and no network: GitHub is a fixture
directory, the runner is the in-memory fake, the provider is offline.
Live mode reads credentials from the environment variables named below and
hands each one only to the adapter that needs it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.controller import Deps, ReviewConfig, review
from atlas_reviewer.domain import InvalidEventError, PrEvent, SourceKey, SourceKind
from atlas_reviewer.fakes import FakeSprites, MemoryLedger
from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.harness import SkillBundleHarness, load_bundle
from atlas_reviewer.http import UrllibTransport
from atlas_reviewer.ledger import FileLedger, ReviewInProgressError, single_review_lock
from atlas_reviewer.ports import BoundaryError, ModelProvider
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import runner_name, sweep
from atlas_reviewer.sprites_api import SpritesClient

ENV_GITHUB_TOKEN = "ATLAS_GITHUB_TOKEN"
ENV_SPRITES_TOKEN = "ATLAS_SPRITES_TOKEN"
ENV_PROVIDER_KEY = "ATLAS_PROVIDER_API_KEY"
ENV_STATE_DIR = "ATLAS_REVIEWER_STATE_DIR"
DEFAULT_STATE_DIR = Path(".atlas-reviewer-state")

PROVIDERS: Mapping[str, Callable[[], ModelProvider]] = {"offline": OfflineProvider}

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
        raise UsageError(
            f"live mode needs the {name} environment variable (or use --dry-run)"
        )
    return value


def _state_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    return Path(args.state_dir or env.get(ENV_STATE_DIR) or DEFAULT_STATE_DIR)


@dataclass(frozen=True)
class _Wiring:
    deps: Deps
    mode: str


def _dry_run_wiring(
    args: argparse.Namespace, event_path: Path, provider: ModelProvider
) -> _Wiring:
    fixtures = Path(args.fixtures) if args.fixtures else event_path.parent
    script_path = fixtures / "runner-script.json"
    script: list[Any] = (
        json.loads(script_path.read_text(encoding="utf-8"))
        if script_path.is_file()
        else []
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
    args: argparse.Namespace, env: Mapping[str, str], provider: ModelProvider
) -> _Wiring:
    gh_token = _require_env(env, ENV_GITHUB_TOKEN)
    sprites_token = _require_env(env, ENV_SPRITES_TOKEN)
    known = tuple(
        v for v in (gh_token, sprites_token, env.get(ENV_PROVIDER_KEY, "")) if v
    )
    redactor = Redactor(known)
    clock = SystemClock()
    transport = UrllibTransport()
    deps = Deps(
        github=GitHubClient(transport, gh_token),
        sprites=SpritesClient(transport, sprites_token),
        ledger=FileLedger(_state_dir(args, env) / "runners.ledger"),
        harness=SkillBundleHarness(provider, load_bundle(), redactor),
        clock=clock,
        redactor=redactor,
        runner_name=lambda: runner_name(clock),
    )
    return _Wiring(deps, f"live (GitHub + Sprites; provider {provider.name})")


def _cmd_review(args: argparse.Namespace, env: Mapping[str, str], out: TextIO) -> int:
    event_path = Path(args.event)
    event = load_event(event_path)
    provider = PROVIDERS[args.provider]()
    wiring = (
        _dry_run_wiring(args, event_path, provider)
        if args.dry_run
        else _live_wiring(args, env, provider)
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


def _cmd_sweep(args: argparse.Namespace, env: Mapping[str, str], out: TextIO) -> int:
    api = SpritesClient(UrllibTransport(), _require_env(env, ENV_SPRITES_TOKEN))
    results = sweep(api, FileLedger(_state_dir(args, env) / "runners.ledger"))
    out.writelines(f"{name}: {status.value}\n" for name, status in results.items())
    out.write(f"{len(results)} runner(s) in the ledger\n")
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
    rev.add_argument("--provider", choices=sorted(PROVIDERS), default="offline")
    rev.set_defaults(handler=_cmd_review)
    swp = sub.add_parser(
        "sweep", help="destroy runners a crashed review left in the ledger"
    )
    swp.set_defaults(handler=_cmd_sweep)
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
) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace, Mapping[str, str], TextIO], int] = (
        args.handler
    )
    try:
        return handler(args, os.environ if env is None else env, out or sys.stdout)
    except tuple(e for e, _ in _ERRORS) as exc:
        (err or sys.stderr).write(f"atlas_reviewer: {exc}\n")
        return next(code for kind, code in _ERRORS if isinstance(exc, kind))
