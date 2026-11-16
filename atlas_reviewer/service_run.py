# SPDX-License-Identifier: MIT
"""Run one queued commit through the service's review child command.

The service mode selects the child: ``ATLAS_SERVICE_MODE=agentic`` (the
default) runs ``python -m atlas_reviewer agentic-review``, and
``ATLAS_SERVICE_MODE=oneshot`` runs the one-shot ``review`` command
(D53, D70). The one-shot mode stays a complete, callable command; nothing
here stubs it. The child receives an allowlist of environment variables:
the model key, the Sprites token, a read-only installation token,
``ATLAS_MODEL``, ``ATLAS_PROVIDERS``, ``ATLAS_ALLOW_SAFETY_RETENTION``,
``ATLAS_REQUIRE_ZDR``, ``ATLAS_KEY_CEILING_USD``, and the agentic limit
variables (``agentic_config.ENV``, D68's derived limits and the $10
per-review ceiling included). The one-shot command reads the route
variables and does not read the agentic limits, so passing them in that
mode costs nothing; the agentic child reads them. The webhook secret, the
App private key, and anything else the parent holds, including a Fly API
token, are not passed on. The parent's wall-clock deadline defaults to
1,200 seconds and is set with ``ATLAS_SERVICE_DEADLINE_S``, between 60
and 14,400 seconds, because a slower model needs more time than the
one-shot budget. When the queue cancels the job, or the
wall-clock deadline passes, the child is signalled SIGTERM, which the CLI
turns into the stop that deletes its Sprite. The parent waits out the
Sprite cleanup budget plus one Sprites call before SIGKILL, and the
result is not a draft to post. Exit codes 0, 4 and 5 are
the CLI's finished reviews (complete, incomplete coverage, changes
requested). Any other exit, or a finished process with no draft file, is
a failure and produces no report.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas_reviewer.agentic_config import ENV as AGENTIC_LIMIT_ENV
from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.limit_stop import LimitHit
from atlas_reviewer.openrouter import (
    ENV_ALLOW_SAFETY_RETENTION,
    ENV_KEY_CEILING_USD,
    ENV_MODEL,
    ENV_PROVIDERS,
    ENV_REQUIRE_ZDR,
)
from atlas_reviewer.runner import CLEANUP_BUDGET_S
from atlas_reviewer.verdict import parse_status

WEBHOOK_SECRET_ENV = "ATLAS_GITHUB_WEBHOOK_SECRET"
APP_KEY_ENV = "ATLAS_GITHUB_APP_PRIVATE_KEY"
READ_TOKEN_ENV = "ATLAS_GITHUB_INSTALLATION_TOKEN"
# The child reviews with a read-only installation token. The App private
# key stays in the parent, so the child cannot mint a write token.
# Passed through to the child. Everything else the parent holds stays there.
_CHILD_ALLOWED = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "PYTHONIOENCODING",
        "PYTHONHASHSEED",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "ATLAS_OPENROUTER_API_KEY",
        "ATLAS_SPRITES_TOKEN",
        READ_TOKEN_ENV,
        ENV_MODEL,
        ENV_PROVIDERS,
        ENV_ALLOW_SAFETY_RETENTION,
        ENV_REQUIRE_ZDR,
        ENV_KEY_CEILING_USD,
    }
    # The agentic limits (D68's per-lens knobs and the per-review dollar
    # ceiling included) ride along in both modes: the agentic child reads
    # them, and the one-shot `review` command ignores variables it does
    # not read, so passing them costs it nothing. They are settings, not
    # credentials.
    | set(AGENTIC_LIMIT_ENV.values())
)
# The parent stops the child after this long even if the child is still
# running. The controller has its own shorter caps; this is the wall
# around a child that never hits them. ATLAS_SERVICE_DEADLINE_S raises or
# lowers it between these bounds: an agentic review of a slower model can
# need more than the one-shot budget, and a value below a minute cannot
# even start a runner. The default follows the mode: oneshot keeps this
# figure; agentic defaults to the bound's ceiling, because there the
# parent deadline is a backstop -- the child's own derived wall and D68's
# dollar ceiling are the real limits (`service_deadline`).
REVIEW_DEADLINE_S = 1200.0
SERVICE_DEADLINE_ENV = "ATLAS_SERVICE_DEADLINE_S"
MIN_SERVICE_DEADLINE_S = 60.0
MAX_SERVICE_DEADLINE_S = 14400.0
_SERVICE_MODES = ("agentic", "oneshot")
SERVICE_MODE_ENV = "ATLAS_SERVICE_MODE"
MODE_AGENTIC = "agentic"
MODE_ONESHOT = "oneshot"
DEFAULT_SERVICE_MODE = MODE_AGENTIC
_DEADLINE_EXIT = -1
# The CLI's review exits. 4 is incomplete file coverage and 5 is a finished
# review that requests changes. Both still wrote a draft.
POSTABLE_EXITS = frozenset({0, 4, 5})
# ``CLEANUP_BUDGET_S`` is how long a destroy may start new Sprites calls.
# One call can still be in flight, and ``SpritesClient`` bounds that call
# at 30 seconds. SIGKILL before both have elapsed leaves the Sprite up.
_SPRITE_CALL_S = 30.0
CLEANUP_WAIT_S = CLEANUP_BUDGET_S + _SPRITE_CALL_S
_KILL_WAIT_S = 5.0
_QUOTED = re.compile(r"`(\"(?:\\.|[^\"\\])*\")`")

Popen = Callable[..., Any]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class RunConfig:
    provider: str
    allow_live_inference: bool
    state_root: Path
    mode: str = DEFAULT_SERVICE_MODE

    def __post_init__(self) -> None:
        if self.mode not in _SERVICE_MODES:
            raise ValueError(
                f"service mode must be {MODE_AGENTIC} or {MODE_ONESHOT}, "
                f"not {self.mode!r}"
            )


def service_mode(env: Mapping[str, str]) -> str:
    """The child command the service runs: ``ATLAS_SERVICE_MODE``, agentic
    when unset. An unknown value raises instead of silently picking one."""
    raw = env.get(SERVICE_MODE_ENV, "")
    if not raw:
        return DEFAULT_SERVICE_MODE
    if raw not in _SERVICE_MODES:
        raise ValueError(
            f"{SERVICE_MODE_ENV} must be {_SERVICE_MODES[0]} or "
            f"{_SERVICE_MODES[1]}, not {raw!r}"
        )
    return raw


def agentic_child_wall_s(env: Mapping[str, str]) -> float:
    """The review wall the agentic child runs on under this configuration:
    the configured ``ATLAS_REVIEW_WALL_S`` (``agentic_config`` reads it;
    D68's derivation raises the multi-lens wall above it, never below it).
    A healthy review always runs at least this long, so it is the floor
    an explicit parent deadline must clear. A limit variable the loader
    refuses is re-raised naming the environment variable, not the
    loader's internal field name."""
    try:
        return load_agentic_limits(env).resolve(cross_limits=False).review_wall_s
    except ValueError as exc:
        raise ValueError(_named_limit_error(exc)) from exc


def _named_limit_error(exc: ValueError) -> str:
    """The loader's messages lead with the limit's field name
    (``review_wall_s must be ...``); the operator set an environment
    variable, so name that."""
    message = str(exc)
    variable = AGENTIC_LIMIT_ENV.get(message.split(" ", 1)[0])
    return f"{variable}: {message}" if variable else message


def service_deadline(
    env: Mapping[str, str], *, mode: str = DEFAULT_SERVICE_MODE
) -> float:
    """The parent's wall clock around one child, in seconds.

    Oneshot keeps the D53 1,200-second default. Agentic defaults to the
    ceiling itself, because there the parent deadline is a backstop, not
    the real limit: the child's own derived wall (D68 raises the
    configured wall to the lens wall times the waves, from a plan the
    picker produces inside the child, where the parent cannot see it) and
    D68's dollar ceiling are what stop a review. A plan's derived wall
    can reach ``ATLAS_LENS_WALL_S`` x ceil(planned / pool); an operator
    who expects such plans sets ``ATLAS_SERVICE_DEADLINE_S`` to cover
    them -- an explicit value below the *configured* child wall refuses
    at boot, because a shorter parent wall SIGTERMs a healthy review into
    a silent no-post, and a configured wall above the ceiling refuses
    too, because no in-bounds value can cover it. A value outside the
    bounds or not a number raises
    in both modes, so a mistyped setting stops the service instead of
    silently clipping or unbounding every review."""
    raw = env.get(SERVICE_DEADLINE_ENV, "")
    if mode == MODE_AGENTIC:
        # Read the child's wall even when the default does not need it:
        # an invalid limit variable the one-shot child would have ignored
        # is a boot refusal here, with the variable named, not a review
        # that dies at run time. A configured wall above the ceiling is
        # the same refusal: no deadline value inside the bounds can cover
        # it, so booting would guarantee the silent undercut the
        # below-wall refusal exists to prevent.
        wall = agentic_child_wall_s(env)
        if wall > MAX_SERVICE_DEADLINE_S:
            raise ValueError(
                f"ATLAS_REVIEW_WALL_S is {wall:.0f} s, above the "
                f"{MAX_SERVICE_DEADLINE_S:.0f} s deadline ceiling, so no "
                f"{SERVICE_DEADLINE_ENV} value can cover a review this "
                "child would run; lower ATLAS_REVIEW_WALL_S"
            )
        if not raw:
            return MAX_SERVICE_DEADLINE_S
        value = _deadline_value(raw)
        if not math.isfinite(value):
            raise ValueError(_deadline_bounds_message(raw))
        if value < wall:
            raise ValueError(
                f"{SERVICE_DEADLINE_ENV} must be at least the agentic "
                f"child's configured review wall ({wall:.0f} s, "
                f"ATLAS_REVIEW_WALL_S), not {raw!r}: a shorter parent wall "
                "SIGTERMs a healthy review and posts nothing"
            )
        if value > MAX_SERVICE_DEADLINE_S:
            raise ValueError(_deadline_bounds_message(raw))
        return value
    if not raw:
        return REVIEW_DEADLINE_S
    value = _deadline_value(raw)
    if (
        not math.isfinite(value)
        or not MIN_SERVICE_DEADLINE_S <= value <= MAX_SERVICE_DEADLINE_S
    ):
        raise ValueError(_deadline_bounds_message(raw))
    return value


def _deadline_value(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"{SERVICE_DEADLINE_ENV} must be a number of seconds, not {raw!r}"
        ) from None


def _deadline_bounds_message(raw: str) -> str:
    return (
        f"{SERVICE_DEADLINE_ENV} must be between "
        f"{MIN_SERVICE_DEADLINE_S:.0f} and {MAX_SERVICE_DEADLINE_S:.0f} "
        f"seconds, not {raw!r}"
    )


@dataclass(frozen=True)
class ReviewReport:
    """What the posted comment lists, taken from the draft the CLI wrote."""

    lenses_run: tuple[str, ...]
    lenses_not_run: tuple[str, ...]
    files_note: str
    files_not_read: tuple[str, ...]
    limit_stops: tuple[str, ...]
    cost_lines: tuple[str, ...]
    recommended_event: str


@dataclass(frozen=True)
class ReviewRun:
    ok: bool
    report: ReviewReport | None = None
    error: str = ""


def run_dir(root: Path, event: PrEvent) -> Path:
    repo = event.repo.replace("/", "-")
    return root / "runs" / f"{repo}-{event.pr_number}-{event.head_sha}"


def review_argv(config: RunConfig, directory: Path) -> list[str]:
    """The child command the mode names: ``agentic-review`` by default,
    the one-shot ``review`` in oneshot mode. Both take the same
    ``--event``, ``--out``, ``--events`` and ``--provider`` wiring."""
    argv = [
        sys.executable,
        "-m",
        "atlas_reviewer",
        "--state-dir",
        str(directory / "state"),
        "review" if config.mode == MODE_ONESHOT else "agentic-review",
        "--event",
        str(directory / "event.json"),
        "--out",
        str(directory / "draft.md"),
        "--events",
        str(directory / "events.jsonl"),
        "--provider",
        config.provider,
    ]
    if config.provider == "openrouter" and config.allow_live_inference:
        argv.append("--allow-live-inference")
    return argv


def child_env(env: Mapping[str, str], *, token: str = "") -> dict[str, str]:
    """The review process gets only ``_CHILD_ALLOWED``. ``token`` is a
    read-only installation token, when the parent minted one."""
    cleaned = {key: value for key, value in env.items() if key in _CHILD_ALLOWED}
    # The image starts as root, so HOME can still be /root after the
    # uid drop. The child must not inherit a home it cannot write.
    if cleaned.get("HOME") == "/root":
        cleaned["HOME"] = "/home/atlas"
    if token:
        cleaned[READ_TOKEN_ENV] = token
    return cleaned


def make_runner(
    config: RunConfig,
    env: Mapping[str, str],
    *,
    popen: Popen = subprocess.Popen,
    sleeper: Sleeper = time.sleep,
    deadline_s: float = REVIEW_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
    read_token: Callable[[Mapping[str, str], PrEvent], tuple[str, str]] | None = None,
) -> Callable[[PrEvent, threading.Event], ReviewRun]:
    mint = read_token or _read_token

    def run(event: PrEvent, cancel: threading.Event) -> ReviewRun:
        directory = run_dir(config.state_root, event)
        make_private_dirs(directory)
        _write_event(directory / "event.json", event)
        stderr_path = directory / "stderr.txt"
        argv = review_argv(config, directory)
        token, mint_error = mint(env, event)
        if mint_error:
            return ReviewRun(False, error=mint_error)
        code = run_process(
            argv,
            child_env(env, token=token),
            cancel,
            stderr_path,
            popen=popen,
            sleeper=sleeper,
            deadline_s=deadline_s,
            clock=clock,
        )
        if code == _DEADLINE_EXIT:
            return ReviewRun(False, error="review deadline")
        if code is None or cancel.is_set():
            return ReviewRun(False, error="superseded")
        if code not in POSTABLE_EXITS:
            return ReviewRun(False, error=f"review exited {code}: {_tail(stderr_path)}")
        draft_path = directory / "draft.md"
        if not draft_path.is_file():
            return ReviewRun(False, error=f"review exited {code} without a draft")
        try:
            draft = draft_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return ReviewRun(
                False, error=f"could not read the draft: {type(exc).__name__}"
            )
        try:
            report = summarize_draft(draft, expect=config.mode)
        except Exception as exc:  # noqa: BLE001 -- a draft this service cannot read must not post
            return ReviewRun(
                False,
                error=f"draft parse failed: {type(exc).__name__}: {exc}",
            )
        return ReviewRun(True, report)

    return run


def run_process(
    argv: Sequence[str],
    env: Mapping[str, str],
    cancel: threading.Event,
    stderr_path: Path,
    *,
    popen: Popen = subprocess.Popen,
    sleeper: Sleeper = time.sleep,
    poll_s: float = 0.05,
    deadline_s: float = REVIEW_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
) -> int | None:
    """The child's exit code, None when ``cancel`` stopped it, or
    ``_DEADLINE_EXIT`` when ``deadline_s`` passed."""
    fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    handle = os.fdopen(fd, "ab")
    try:
        proc = popen(
            list(argv),
            env=dict(env),
            stdout=subprocess.DEVNULL,
            stderr=handle,
        )
        started = clock()
        while True:
            if cancel.is_set():
                _stop(proc)
                return None
            if clock() - started >= deadline_s:
                _stop(proc)
                return _DEADLINE_EXIT
            code = proc.poll()
            if code is not None:
                return code
            sleeper(poll_s)
    finally:
        handle.close()


def summarize_draft(draft: str, *, expect: str | None = None) -> ReviewReport:
    """Lenses, coverage, limit rows and cost lines from a controller draft.

    The one-shot draft does not list every path a model call saw. The
    files section is the controller's coverage note, plus any path the
    draft's opening warning quotes as not reviewed in full. An agentic
    draft -- its status line says ``"mode": "agentic"`` -- carries the
    same report from its own sections: the selection's NOT RUN bullets
    and the attestation-ledger lens lines, the status line's coverage
    counts and limit stop, the context omissions, and the model-usage
    line.

    ``expect`` is the service mode that ran the child. A draft whose
    status line disagrees with it -- an agentic child's draft with no
    mode field, or a one-shot draft under an agentic parent -- is a
    labeled parse failure, never a silent parse as the other mode's
    shape (the version-skew shape: only a mismatched parent/child pair
    produces it, and one deploy ships them together).
    """
    status = parse_status(draft) or {}
    if status.get("mode") == "agentic":
        if expect == MODE_ONESHOT:
            raise DraftParseError(
                "the draft is an agentic draft but the service ran oneshot"
            )
        return _agentic_report(draft, status)
    if expect == MODE_AGENTIC:
        raise DraftParseError(
            "the draft has no agentic status line; the child and the "
            "service disagree about the service mode"
        )
    return _oneshot_report(draft, status)


class DraftParseError(ValueError):
    """A draft the service cannot map to a report for the mode it ran."""


def _oneshot_report(draft: str, status: Mapping[str, object]) -> ReviewReport:
    recommended = status.get("review_event")
    run: list[str] = []
    skipped: list[str] = []
    for cells in _table(section(draft, "Review lenses")):
        name = cells[0]
        kind = cells[1] if len(cells) > 1 else ""
        why = cells[4] if len(cells) > 4 else ""
        if kind == "run whole":
            run.append(name)
        else:
            skipped.append(f"{name}: {why}" if why else name)
    note = "The draft has no diff-coverage note."
    for line in section(draft, "Controller notes").splitlines():
        if "Diff coverage" in line:
            note = line.lstrip("- ").strip()
            break
    preamble = draft.split("\n## ", 1)[0]
    return ReviewReport(
        tuple(run),
        tuple(skipped),
        note,
        _quoted_strings(preamble),
        tuple(
            " | ".join(cells)
            for cells in _table(section(draft, "Omissions and limits hit"))
        ),
        tuple(_bullets(section(draft, "Model usage"))),
        recommended if isinstance(recommended, str) else "",
    )


# The agentic draft's ledger line: `- L1 <lens>: **<state>**; <rest>`.
_AGENTIC_COVERAGE = re.compile(r"^- L\d+ (.+?): \*\*(.+?)\*\*(?:; (.*))?$")
_AGENTIC_RUN_STATES = frozenset({"clean", "partial"})
_NOT_RUN_BULLET = "- NOT RUN: "
# Coverage-section prose that is not a limit: the runner report and the
# round-log note sit in that section whenever the draft has no prompt-cache
# section between them, and a runner that did not complete adds its own
# quoted note line (`Runner reported, quoted:`).
_AGENTIC_NON_LIMITS = (
    "Runner:",
    "Runner delete",
    "Runner reported, quoted:",
    "Round log, quoted:",
)


def _agentic_report(draft: str, status: Mapping[str, object]) -> ReviewReport:
    """The posted report from an agentic draft. A lens counts as run when
    its ledger line says it ran with its body (``clean`` or ``partial``);
    ``failed`` and ``NOT RUN`` are not run, the way the parity gate reads
    them. The coverage note is built from the status line's controller
    counts, and the limit stops are the status line's first stop, the
    context omissions, and the ceiling note the coverage section carries."""
    skipped: list[str] = []
    named: set[str] = set()

    def skip(name: str, why: str) -> None:
        if name in named:
            return
        named.add(name)
        skipped.append(f"{name}: {why}" if why else name)

    for name, why in _agentic_selection_skips(draft):
        skip(name, why)
    stops = [
        line[2:].strip()
        for line in section(draft, "Context omissions").splitlines()
        if line.startswith("- ")
    ]
    run_names, not_run, cost, notes = _agentic_coverage(draft)
    for name, why in not_run:
        skip(name, why)
    stops.extend(notes)
    stop = status.get("limit_stop")
    if isinstance(stop, dict) and all(
        isinstance(stop.get(field), str) and stop.get(field)
        for field in ("limit", "configured", "observed", "setting")
    ):
        stops.insert(
            0,
            LimitHit(
                str(stop["limit"]),
                str(stop["configured"]),
                str(stop["observed"]),
                str(stop["setting"]),
            ).message(),
        )
    preamble = draft.split("\n## ", 1)[0]
    recommended = status.get("review_event")
    return ReviewReport(
        tuple(run_names),
        tuple(skipped),
        _agentic_coverage_note(status),
        _quoted_strings(preamble),
        tuple(stops),
        tuple(cost),
        recommended if isinstance(recommended, str) else "",
    )


def _agentic_selection_skips(draft: str) -> list[tuple[str, str]]:
    """The selection section's NOT RUN bullets as (lens, why) pairs. The
    lens name is the bullet's first quoted string; the why is the
    parenthetical after it."""
    pairs: list[tuple[str, str]] = []
    for line in section(draft, "Lens selection").splitlines():
        if not line.startswith(_NOT_RUN_BULLET):
            continue
        rest = line[len(_NOT_RUN_BULLET) :]
        quoted = _quoted_strings(rest)
        name = quoted[0] if quoted else rest
        why = ""
        if rest.endswith(")"):
            _, sep, tail = rest.rpartition(" (")
            if sep:
                why = tail[:-1]
        pairs.append((name, why))
    return pairs


def _agentic_coverage(
    draft: str,
) -> tuple[list[str], list[tuple[str, str]], list[str], list[str]]:
    """From the coverage section: the lens names that ran, the (lens, why)
    pairs that did not, the cost lines, and the section's other prose as
    limit notes. A not-run line carries its reason only when the line is
    exactly the state and one quoted reason -- the shape a lens that was
    never attempted renders; a failed lens with an outcome has parts, not
    a reason, and stays name-only."""
    run: list[str] = []
    not_run: list[tuple[str, str]] = []
    cost: list[str] = []
    notes: list[str] = []
    for line in section(draft, "Lens coverage (attestation ledger)").splitlines():
        match = _AGENTIC_COVERAGE.match(line)
        if match is not None:
            name, state, rest = match.group(1), match.group(2), match.group(3) or ""
            if state in _AGENTIC_RUN_STATES:
                run.append(name)
            elif "body sha256" not in rest:
                quoted = _quoted_strings(rest)
                not_run.append((name, quoted[0] if quoted else ""))
            else:
                not_run.append((name, ""))
            continue
        if not line or line.startswith("- "):
            continue
        if line.startswith("Model calls:"):
            cost.append(line)
        elif not line.startswith(_AGENTIC_NON_LIMITS):
            notes.append(line)
    return run, not_run, cost, notes


def _agentic_coverage_note(status: Mapping[str, object]) -> str:
    """The file-coverage note, from the status line's controller counts.
    An incomplete note with no unread file names no cause: the counts do
    not say whether lens coverage, a missing count or an omission is the
    gap, so the note points at the draft instead of guessing."""

    def count(raw: object) -> int | None:
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else None

    changed = count(status.get("changed_files"))
    unreviewed = count(status.get("unreviewed_files"))
    if status.get("coverage_complete") is True:
        files = f" ({changed})" if changed is not None else ""
        return f"Agentic file coverage complete: every changed file{files} was read in full."
    if unreviewed:
        total = str(changed) if changed is not None else "?"
        return (
            f"Agentic file coverage incomplete: {unreviewed} of {total} "
            "changed file(s) were not read in full."
        )
    # No unread file: the gap is lens coverage, a missing count, or a
    # context omission, and the status line does not say which. Name no
    # cause the counts do not show; the draft's own sections do.
    return "Agentic coverage incomplete; see the draft's coverage and omission notes."


def section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker) :]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _table(text: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if not cells or cells[0] in {"Lens", "Source"} or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    return tuple(rows)


def _bullets(text: str) -> tuple[str, ...]:
    return tuple(
        line[2:].strip() for line in text.splitlines() if line.startswith("- ")
    )


def _quoted_strings(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for raw in _QUOTED.findall(text):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, str) and value and value not in found:
            found.append(value)
    return tuple(found)


def _read_token(env: Mapping[str, str], event: PrEvent) -> tuple[str, str]:
    """A read-only installation token for the child, or ``("", "")`` when
    the parent has no App key (offline). The second value is an error
    label when a live mint fails. The key itself is never returned."""
    key = env.get(APP_KEY_ENV, "")
    if not key:
        return "", ""
    app_id = env.get("ATLAS_GITHUB_APP_ID", "")
    installation = env.get("ATLAS_GITHUB_INSTALLATION_ID", "")
    if (
        not app_id.isdigit()
        or not installation.isascii()
        or not installation.isdigit()
        or int(installation) < 1
    ):
        return "", "could not mint a read token"
    from atlas_reviewer.clock import SystemClock
    from atlas_reviewer.github_auth import READ_PERMISSIONS, AppInstallationTokens
    from atlas_reviewer.http import UrllibTransport

    try:
        tokens = AppInstallationTokens(
            UrllibTransport(),
            SystemClock(),
            app_id=app_id,
            private_key=key.replace("\\n", "\n") if "\n" not in key else key,
            installation_id=int(installation),
            # Issues read rides along on every mint: the mint happens
            # before the child exists and `review_argv` builds no
            # --include-issues flag the parent could key on, so a
            # conditional mint would never mint it. The token stays
            # read-only over the one repository.
            permissions={**READ_PERMISSIONS, "issues": "read"},
            repositories=(event.repo.split("/", 1)[1],),
        )
        return tokens.token(), ""
    except (OSError, ValueError, RuntimeError) as exc:
        return "", f"could not mint a read token ({type(exc).__name__})"


def _write_event(path: Path, event: PrEvent) -> None:
    payload = json.dumps(
        {"repo": event.repo, "pr_number": event.pr_number, "head_sha": event.head_sha}
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _tail(path: Path, limit: int = 500) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=CLEANUP_WAIT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=_KILL_WAIT_S)
