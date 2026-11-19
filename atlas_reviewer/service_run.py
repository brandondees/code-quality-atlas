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
per-review ceiling included). The per-tenant bound the child clamps a
repo-raised ceiling with, ``ATLAS_REPO_CEILING_MAX_USD`` (config slice
S9), rides along too; the daily budget is the parent's own admission
bound and is not passed. The tenant-supplied model credentials (config
slice S10) ride as three variables -- the key ``ATLAS_TENANT_MODEL_KEY``
(the one credential variable the allowlist gains), and the settings
``ATLAS_TENANT_BASE_URL`` and ``ATLAS_TENANT_MODEL`` -- but only on a
tenant-path run, where the parent also drops the operator's model key,
so the operator-key path and the tenant path never share a child
environment. The agentic child also takes
``--round-log`` naming the per-pull-request round log on the volume
(D74), outside the per-head run directory, so a later head of the same
pull request reads the earlier rounds; the one-shot command takes no
round log. The one-shot command reads the route
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
from atlas_reviewer.installation_store import InstallationStoreError
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.lens_contract import Severity
from atlas_reviewer.limit_stop import LimitHit
from atlas_reviewer.notes import RECOVERED_NOTE_PATTERN
from atlas_reviewer.openrouter import (
    ENV_ALLOW_SAFETY_RETENTION,
    ENV_KEY_CEILING_USD,
    ENV_MODEL,
    ENV_PROVIDERS,
    ENV_REQUIRE_ZDR,
)
from atlas_reviewer.picker import FLOOR_TIER
from atlas_reviewer.review_wide import ENV_REPO_CEILING_MAX_USD
from atlas_reviewer.runner import CLEANUP_BUDGET_S
from atlas_reviewer.tenant_provider import (
    ENV_TENANT_BASE_URL,
    ENV_TENANT_MODEL,
    ENV_TENANT_MODEL_KEY,
    TenantCredentials,
)
from atlas_reviewer.verdict import parse_status

WEBHOOK_SECRET_ENV = "ATLAS_GITHUB_WEBHOOK_SECRET"
APP_KEY_ENV = "ATLAS_GITHUB_APP_PRIVATE_KEY"
READ_TOKEN_ENV = "ATLAS_GITHUB_INSTALLATION_TOKEN"
# The operator's model key. The child receives it on the operator path;
# a tenant-path child does not (`child_env` drops it), because the
# operator's key must never be available to a tenant review.
MODEL_KEY_ENV = "ATLAS_OPENROUTER_API_KEY"
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
        MODEL_KEY_ENV,
        "ATLAS_SPRITES_TOKEN",
        READ_TOKEN_ENV,
        ENV_MODEL,
        ENV_PROVIDERS,
        ENV_ALLOW_SAFETY_RETENTION,
        ENV_REQUIRE_ZDR,
        ENV_KEY_CEILING_USD,
        # The per-tenant bound the child clamps a repo-raised ceiling with
        # (config slice S9): a setting, not a credential.
        ENV_REPO_CEILING_MAX_USD,
        # The tenant-supplied model credentials (config slice S10): the
        # key is the one credential variable the allowlist gains, the
        # way the operator key above is held; the endpoint base URL and
        # the chosen model are settings. The three travel together only
        # on a tenant-path run, where `child_env` also drops the
        # operator's key, so the two paths never share a child env.
        ENV_TENANT_MODEL_KEY,
        ENV_TENANT_BASE_URL,
        ENV_TENANT_MODEL,
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


class RunSecrets:
    """The credentials the review runs resolved from the installation
    store (config slice S10), registered for the parent's scrubber.

    The child's stderr tail lands in the run's error string and, from
    there, on the `review failed` telemetry record. The child scrubs its
    own writes, but the parent's redaction exists precisely to not
    depend on that completeness -- an unhandled traceback, or a future
    child write path that forgets the scrub -- and the tenant key is not
    in the parent's environment (the store resolved it at run time), so
    `_child_secrets` cannot see it. A run that resolved tenant
    credentials registers the key here **before the child starts**, and
    the service log's and the poster's redactors read it on every scrub
    from then on. Registered values are never cleared: a key stays a
    value the log must never print after the run that used it, whether
    that run succeeded or failed, and scrubbing a rotated-away key is
    harmless."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, None] = {}

    def register(self, *values: str) -> None:
        """Add the run's resolved credentials. A value under eight
        characters is ignored, the way `_child_secrets` filters: a short
        string is more likely a test fixture than a key, and redacting a
        short common string would scrub the log's own words."""
        with self._lock:
            for value in values:
                if len(value) >= 8:
                    self._values[value] = None

    def __call__(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._values)


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


_COST_LINE = re.compile(r"Model calls: (\d+); committed: \$([0-9]+(?:\.[0-9]+)?)")


def review_cost(report: ReviewReport) -> tuple[int, str] | None:
    """The (calls, committed dollars) the draft's cost lines record, or
    None when none parses -- the cost event then falls back to the
    progress records, and to "unknown" past those."""
    for line in report.cost_lines:
        found = _COST_LINE.search(line)
        if found is not None:
            return int(found.group(1)), found.group(2)
    return None


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
    findings: tuple[str, ...] = ()
    resolved: tuple[str, ...] = ()
    """A delta review's resolved findings (#702): the draft's
    resolved-section bullets, each the whole line the draft wrote, so the
    posted comment shows what the new commits fixed and why."""
    coverage_complete: bool | None = None
    """The draft status line's coverage flag: True when the review read
    every changed file, False when it did not, None when the draft's
    status line does not say (a pre-#702 draft, say). The queue keys the
    follow-up's shape on it (round-5 review of #748): a finished review
    that did not cover the pull request cannot stand in for the files it
    never read, so its follow-up is queued as an ordinary full review,
    not as a delta on top of it."""
    delta_note: str = ""
    """The draft status line's carry-forward note (#702), as the
    coordinator recorded it. The post cites it instead of asserting that
    the earlier findings were carried forward when the note says
    otherwise -- an unreadable round record is not a review with no
    prior findings (round-5 review of #748)."""
    carried_unverified: tuple[str, ...] = ()
    """A delta review's carried findings without a re-anchored, verified
    quote (#702): the draft's carried-section bullets. They are not
    findings, but the post shows them, so a carried finding is never
    silently dropped between the draft and the comment."""
    lens_decisions: tuple[str, ...] = ()
    """A delta review's per-lens decisions (D83): the draft's
    decisions-section bullets -- which lenses the follow-up re-ran and
    which it reused, each with the coordinator's reason -- so the posted
    comment shows the judgment, not only its outcome. Empty on a full
    review."""
    review_error: str = ""
    """The fixed cause a refused key halted the review with (D92), read
    from the draft status line: `model key out of credit` or `model key
    refused`. Non-empty means the post is the error that cause names, not
    a review -- no findings section, no coverage claim. Empty on every
    review that ran on a served key."""


@dataclass(frozen=True)
class ReviewRun:
    ok: bool
    report: ReviewReport | None = None
    error: str = ""


def run_dir(root: Path, event: PrEvent) -> Path:
    repo = event.repo.replace("/", "-")
    return root / "runs" / f"{repo}-{event.pr_number}-{event.head_sha}"


def round_log_path(root: Path, event: PrEvent) -> Path:
    """The per-pull-request round log (D74), keyed by repository and PR
    number -- not by head SHA -- so a later head of the same pull request
    reads the earlier rounds. The repository key is casefolded to match
    the reader's case-insensitive record key, so a case-only repository
    rename keeps the log instead of silently starting a fresh one. It
    lives outside the per-head run
    directory, on the volume, and survives the run directory's removal.
    The name flattens the repository the way `run_dir` does."""
    repo = event.repo.casefold().replace("/", "-")
    return root / "rounds" / f"{repo}-{event.pr_number}.jsonl"


def review_argv(
    config: RunConfig,
    directory: Path,
    event: PrEvent,
    *,
    tenant: TenantCredentials | None = None,
) -> list[str]:
    """The child command the mode names: ``agentic-review`` by default,
    the one-shot ``review`` in oneshot mode. Both take the same
    ``--event``, ``--out``, ``--events`` and ``--provider`` wiring. The
    agentic child also takes the per-pull-request ``--round-log`` (D74):
    the child cannot derive it, because its ``--state-dir`` is the
    per-head run directory's. A tenant-path run (config slice S10)
    passes ``--provider tenant`` and implies live inference: the
    installation's own endpoint is the live call, on its own key."""
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
        "tenant" if tenant is not None else config.provider,
    ]
    if config.mode == MODE_AGENTIC:
        argv += ["--round-log", str(round_log_path(config.state_root, event))]
    if (
        tenant is not None
        or config.provider == "openrouter"
        and config.allow_live_inference
    ):
        argv.append("--allow-live-inference")
    return argv


def child_env(
    env: Mapping[str, str],
    *,
    token: str = "",
    tenant: TenantCredentials | None = None,
) -> dict[str, str]:
    """The review process gets only ``_CHILD_ALLOWED``. ``token`` is a
    read-only installation token, when the parent minted one. A
    tenant-path run (config slice S10) adds the installation's own
    endpoint credentials and **drops the operator's key**: the tenant
    child has no use for it, and the two paths never share a child
    environment."""
    cleaned = {key: value for key, value in env.items() if key in _CHILD_ALLOWED}
    # The image starts as root, so HOME can still be /root after the
    # uid drop. The child must not inherit a home it cannot write.
    if cleaned.get("HOME") == "/root":
        cleaned["HOME"] = "/home/atlas"
    if token:
        cleaned[READ_TOKEN_ENV] = token
    if tenant is not None:
        cleaned[ENV_TENANT_MODEL_KEY] = tenant.key
        cleaned[ENV_TENANT_BASE_URL] = tenant.base_url
        cleaned[ENV_TENANT_MODEL] = tenant.model
        cleaned.pop(MODEL_KEY_ENV, None)
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
    tenant_source: Callable[[], TenantCredentials | None] | None = None,
    tenant_secrets: RunSecrets | None = None,
) -> Callable[[PrEvent, threading.Event], ReviewRun]:
    """``tenant_source`` (config slice S10) resolves the installation's
    own endpoint credentials at run time -- fresh, so a rotation between
    queueing and running lands. It returns None for the operator path
    and raises `InstallationStoreError` for a store it cannot read or a
    consent that is not acknowledged: either way the review fails with
    the failure named and **never falls back to the operator key** --
    a store this parent cannot read might hold credentials, and the
    routing rule does not guess."""
    mint = read_token or _read_token

    def run(event: PrEvent, cancel: threading.Event) -> ReviewRun:
        if tenant_source is not None:
            try:
                tenant = tenant_source()
            except InstallationStoreError as exc:
                return ReviewRun(False, error=f"the tenant path refused: {exc}")
        else:
            tenant = None
        if tenant is not None and tenant_secrets is not None:
            # Registered before the child starts, so the parent's
            # scrubber knows the key from the first byte the child
            # writes -- the child's own scrubbing is a defense the
            # parent's does not assume (r1 review of #776, Major 1).
            tenant_secrets.register(tenant.key)
        directory = run_dir(config.state_root, event)
        make_private_dirs(directory)
        _write_event(directory / "event.json", event)
        stderr_path = directory / "stderr.txt"
        argv = review_argv(config, directory, event, tenant=tenant)
        token, mint_error = mint(env, event)
        if mint_error:
            return ReviewRun(False, error=mint_error)
        code = run_process(
            argv,
            child_env(env, token=token, tenant=tenant),
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
    """Lenses, coverage, limit rows, cost lines and verified findings from
    a controller draft.

    The one-shot draft does not list every path a model call saw. The
    files section is the controller's coverage note, plus any path the
    draft's opening warning quotes as not reviewed in full. An agentic
    draft -- its status line says ``"mode": "agentic"`` -- carries the
    same report from its own sections: the selection's NOT RUN bullets
    and the attestation-ledger lens lines, the status line's coverage
    counts and limit stop, the context omissions, the verified-findings
    bullets, and the model-usage line.

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


def _status_flag(status: Mapping[str, object], key: str) -> Any:
    """The status field only when it has the type the field promises:
    a draft the coordinator did not write yields None/empty, not a
    guess."""
    value = status.get(key)
    if key == "coverage_complete":
        return value if isinstance(value, bool) else None
    return value if isinstance(value, str) else ""


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
        findings=_findings(draft),
        coverage_complete=_status_flag(status, "coverage_complete"),
        delta_note=_status_flag(status, "delta_note"),
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
    them -- except a line the coordinator marked recovered (#692), whose
    lens's later clean run supersedes the failure and whose failure text
    is carried among the limit stops instead. The coverage note is built
    from the status line's controller counts, and the limit stops are the
    status line's first stop, the context omissions, and the ceiling note
    the coverage section carries."""
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
        findings=_findings(draft),
        resolved=tuple(_bullets(section(draft, "Resolved by the new commits"))),
        carried_unverified=tuple(_bullets(section(draft, "Carried, not re-verified"))),
        lens_decisions=tuple(_bullets(section(draft, "Lens decisions (delta review)"))),
        coverage_complete=_status_flag(status, "coverage_complete"),
        delta_note=_status_flag(status, "delta_note"),
        review_error=_status_flag(status, "review_error"),
    )


def _findings(draft: str) -> tuple[str, ...]:
    """The verified-findings section's bullets, each the whole finding line
    the draft wrote (id, severity tags, location, lens, text, fix), so
    severity and location survive into the post. The `No verified
    findings.` line is prose, not a bullet, and yields none; the one-shot
    draft has no such section and yields none too. No CRLF or
    wrapped-bullet hardening: the coordinator renders the draft with
    ``"\\n".join`` (never ``\\r``) and every finding field is
    whitespace-collapsed by `quote_untrusted` before it lands in a bullet,
    so a draft violating either is not a draft this coordinator wrote --
    and a marker miss degrades to an empty Findings section, never a
    crash."""
    return tuple(_bullets(section(draft, "Findings (verified quotes only)")))


# The controller-rendered finding line (`coordinator._finding_line`): the
# minted id, the controller-made tags bracket -- whose first tag is the
# finding's severity, after the carried tag's own word when the finding
# was carried forward (#702) -- the location as one inert code span, and
# the lens that raised the finding in the parenthesis that names it,
# before the finding text's own code span begins. The leading `- ` is
# the draft's own bullet; `summarize_draft` strips it from the report's
# findings, so the parse reads both shapes. Every field the tags bracket
# and the lens parenthesis name is controller-made (`Severity`'s own
# spellings, the lens name), not model text, so the match carries no
# untrusted text anywhere; the location span's content is skipped whole,
# and a code span never carries a raw backtick (`quote_untrusted` escapes
# them), so the span boundary is unambiguous.
_FINDING_LINE = re.compile(
    r"^(?:- )?\*\*[^*]+\*\* "
    r"\[(?P<tags>[^\]]*)\] "
    r"`(?P<location>[^`]*)` "
    r"\((?P<lens>`?[a-z0-9]+(?:-[a-z0-9]+)*`?)\): "
)


def finding_class(line: str) -> tuple[Severity | None, str]:
    """The (severity, lens) one controller-rendered finding line carries,
    or ``(None, lens-or-"")`` when the line does not parse as one: the
    severity is the tags bracket's first tag, or the tag after the
    carried tag's own word (#702), and the lens is the parenthesis
    between the location span and the finding text. The severity floor
    keeps what this cannot classify -- dropping an unclassifiable
    finding would be the silent suppression the floor exists to bound --
    so the parse's miss is the safe direction, and the round-trip
    invariant (findings reach `ReviewReport` only through
    `summarize_draft`, from a draft the coordinator rendered) is what
    makes the parse's shape the ordinary one."""
    match = _FINDING_LINE.match(line)
    if match is None:
        return None, ""
    lens = match.group("lens").strip("`")
    tags = match.group("tags").split(", ")
    if not tags:
        return None, lens
    name = tags[1] if tags[0] == "carried" else tags[0]
    try:
        return Severity(name), lens
    except ValueError:
        return None, lens


def apply_severity_floor(
    findings: tuple[str, ...], floor: Severity | None
) -> tuple[tuple[str, ...], int]:
    """The findings the post keeps under the repo's severity floor (D84,
    config slice S3), as ``(kept, held)``.

    A finding at or above the floor -- a severity whose rank is at or
    below the floor's; a lower rank is more severe -- is posted. A
    finding below it from a preference-tier lens is held in the draft,
    named by the post's count, never silently: the floor suppresses the
    post's noise, not the record. A finding from one of the manifest's
    floor-tier lenses (`picker.FLOOR_TIER`, D69's 5:13 PM CT update) is
    never held whatever its severity -- the tier rule carries over
    unchanged (D81 Q3) -- and neither is a line the parse cannot
    classify. The default floor (``None``, the repo raised nothing)
    keeps every finding."""
    if floor is None:
        return findings, 0
    kept: list[str] = []
    held = 0
    for line in findings:
        severity, lens = finding_class(line)
        if severity is None or lens in FLOOR_TIER or severity.rank <= floor.rank:
            kept.append(line)
        else:
            held += 1
    return tuple(kept), held


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
    a reason, and stays name-only. A line the coordinator marked recovered
    (#692) is neither: the same lens's later clean run supersedes the
    failure for coverage, so the lens is run, and the failure stays
    visible as the line itself, carried among the limit notes rather than
    dropped."""
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
            elif RECOVERED_NOTE_PATTERN.search(rest):
                notes.append(line)
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
    """The text after the last whole-line ``## heading`` and before the
    next heading line.

    The match is anchored to a whole heading line and takes the last
    occurrence (#739 round 2): a pre-section field the draft renders
    unquoted -- the selection note, a lens note -- could otherwise carry
    the heading's own literal line and steal the extraction, and the real
    section is always the latest one the controller wrote. No quoted
    field can carry a whole line -- `quote_untrusted` collapses
    whitespace -- so the only way the literal line appears twice is a
    field the draft renders as prose."""
    marker = f"\n## {heading}\n"
    start = text.rfind(marker)
    if start < 0:
        probe = f"## {heading}\n"
        if not text.startswith(probe):
            return ""
        rest = text[len(probe) :]
    else:
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

    # Issues read rides along on every mint: the mint happens before the
    # child exists and `review_argv` builds no --include-issues flag the
    # parent could key on, so a conditional mint would never mint it. The
    # token stays read-only over the one repository.
    permissions = {**READ_PERMISSIONS, "issues": "read"}
    wanted = ", ".join(f"{name} read" for name in permissions)
    try:
        tokens = AppInstallationTokens(
            UrllibTransport(),
            SystemClock(),
            app_id=app_id,
            private_key=key.replace("\\n", "\n") if "\n" not in key else key,
            installation_id=int(installation),
            permissions=permissions,
            repositories=(event.repo.split("/", 1)[1],),
        )
        return tokens.token(), ""
    except (OSError, ValueError, RuntimeError) as exc:
        return "", (
            f"could not mint a read token ({type(exc).__name__}): the "
            f"installation must grant {wanted}; is a permission missing?"
        )


def _write_event(path: Path, event: PrEvent) -> None:
    payload: dict[str, object] = {
        "repo": event.repo,
        "pr_number": event.pr_number,
        "head_sha": event.head_sha,
    }
    if event.delta_from:
        payload["delta_from"] = event.delta_from
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))


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
