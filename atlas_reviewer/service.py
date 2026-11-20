# SPDX-License-Identifier: MIT
"""Webhook receiver: verify, admit, queue, and run one review at a time.

``python -m atlas_reviewer.service`` listens for GitHub App deliveries and
answers before it runs a review, so the request does not wait on the
controller. ``main`` posts a finished review as one COMMENT through
``publisher_from_env``. A caller that passes no publisher records the
draft and writes nothing to GitHub.

The webhook secret and the App private key stay in this process. The
review child is started without either.
"""

from __future__ import annotations

import contextvars
import json
import math
import os
import random
import shutil
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from atlas_reviewer.budget import (
    DEFAULT_REPO_DAILY_BUDGET_USD,
    DailySpend,
    repo_daily_budget_usd,
    skip_reason,
)
from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.funding import (
    FundingChoice,
    FundingSelector,
    active_choice,
    configured_model,
    funding_key_values,
    key_probe,
    load_funding_sources,
    sources_cover,
)
from atlas_reviewer.head_change import (
    DECISION_CANCEL,
    DECISION_KEEP,
    DEFAULT_CANCEL_FRACTION,
    POLICIES,
    POLICY_CANCEL,
    POLICY_KEEP,
    Decision,
    Progress,
    PushClass,
    cancel_fraction,
    classify_delivery,
    decide,
    head_change_policy,
    last_run_progress,
    read_progress,
)
from atlas_reviewer.installation_store import (
    CONSENT_REQUIRED,
    DEFAULT_RETENTION_DAYS,
    ENV_RETENTION_DAYS,
    ENV_STORE_KEY,
    ConsentNotAcknowledgedError,
    InstallationStore,
    InstallationStoreError,
    TenantCredentials,
    retention_days,
)
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.openrouter import MODEL_ID
from atlas_reviewer.ports import (
    KEY_AUTH_REFUSED,
    KEY_OUT_OF_CREDIT,
    BoundaryError,
    NotFoundError,
    TransportTimeoutError,
)
from atlas_reviewer.redact import Redactor
from atlas_reviewer.repo_config import (
    DEFAULT_POST_CONFIG,
    PostConfigRead,
    parse_post_config,
)
from atlas_reviewer.review_wide import operator_repo_ceiling_max
from atlas_reviewer.runner import event_runner_name
from atlas_reviewer.service_admit import (
    EVENT_HEADER,
    MAX_ADMISSION_BYTES,
    NO_NARROWING,
    REVIEW_MD,
    SIGNATURE_HEADER,
    AdmissionReader,
    Admitted,
    Ignored,
    RepoAdmission,
    admit,
    default_branch,
    narrow,
    parse_delivery,
    parse_repo_admission,
    signature_matches,
)
from atlas_reviewer.service_queue import Board, Enqueue, Job, JobState, QueueError
from atlas_reviewer.service_run import (
    APP_KEY_ENV,
    CLEANUP_WAIT_S,
    DEFAULT_SERVICE_MODE,
    MAX_SERVICE_DEADLINE_S,
    MIN_SERVICE_DEADLINE_S,
    MODE_AGENTIC,
    MODE_ONESHOT,
    WEBHOOK_SECRET_ENV,
    DraftParseError,
    ReviewReport,
    ReviewRun,
    RunConfig,
    RunSecrets,
    known_review_error,
    make_runner,
    review_cost,
    run_dir,
    service_deadline,
    service_mode,
    summarize_draft,
)
from atlas_reviewer.stops import install_interrupts
from atlas_reviewer.telemetry import ERROR, OK, Event, EventSink, JsonlSink, Telemetry
from atlas_reviewer.verdict import STATUS_PREFIX

if TYPE_CHECKING:
    from atlas_reviewer.github_api import GitHubClient

DEFAULT_REPO = "brandondees/code-quality-atlas"
# A pool past this is a bad environment value, not a review budget. Each
# review still has the controller's own call and cost caps.
MAX_CONCURRENCY = 32
MAX_BODY_BYTES = 5_000_000
MAX_POST_ATTEMPTS = 5
# A failed post is tried again on this schedule, then given up. The fifth
# attempt does not wait: it is the last try, so there is no fifth delay.
# Each wait is stretched by up to 20% so several machines do not retry
# together. The waits stop a dead GitHub endpoint from turning into a
# tight loop. They are not a cost cap: the review itself has already finished.
_POST_BACKOFF_S = (5.0, 15.0, 30.0, 60.0)
# One current file plus one rotated file. The cap is the operator log,
# not the review queue.
_SERVICE_LOG_BYTES = 1_048_576
_BACKOFF_JITTER = 0.2


class PostNotCurrent(Exception):
    """The head moved, or a stop landed, before the review was sent."""


class PostHookMissing(Exception):
    """The pre-create check was not installed. Nothing is sent."""


class PostAuthError(Exception):
    """GitHub refused the credential. Do not retry."""


class PostRejected(Exception):
    """GitHub rejected the review. The request will not succeed on retry."""


class RateLimited(Exception):
    """GitHub asked the caller to wait. ``retry_after`` is seconds."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# The poster reads this in the worker thread, immediately before the
# create, and sends nothing when it returns false.
before_send: contextvars.ContextVar[Callable[[], bool] | None] = contextvars.ContextVar(
    "atlas_review_before_send", default=None
)
_POLL_S = 0.2
_REQUEST_TIMEOUT_S = 20.0
# How long one request body may take, separate from the socket's idle
# timeout so a test can shorten it without also shortening every read.
_BODY_BUDGET_S = _REQUEST_TIMEOUT_S
_MAX_HTTP_HANDLERS = 16

Publisher = Callable[[PrEvent, ReviewReport], bool | None]
Runner = Callable[[PrEvent, threading.Event], ReviewRun]


class PostPublisher(Protocol):
    """A publisher ``serve`` may hand the optional post-config source to:
    the poster's own ``post``, whose third parameter is optional and read
    after the poster's own dedupe checks. The protocol names the contract
    the wrapper relies on, so passing a strict two-argument publisher
    together with a ``post_config_fetcher`` is a type error at the
    ``serve`` call site, not a ``TypeError`` on every post (r1 review of
    #770, Nit 2). A publisher used without a fetcher is never called with
    the third argument, so the plain ``Publisher`` shape keeps working."""

    def __call__(
        self,
        event: PrEvent,
        report: ReviewReport,
        post_config: PostConfigSource | None = ...,
    ) -> bool | None: ...


# The default-branch ``REVIEW.md`` fetch behind the repo's own post
# settings (config slice S3, D84): one repo name in, the file's bytes or
# None when there is no file there. The same shape the admission read's
# reader has, minus the default-branch argument -- at post time no
# payload carries it, so the fetcher recovers the branch itself.
PostConfigFetcher = Callable[[str], bytes | None]
# The per-post source the wrapped publisher hands the poster: called
# lazily, after the poster's own dedupe checks, so an already-posted
# head spends no read. It never raises; a gap reads as the default.
PostConfigSource = Callable[[], PostConfigRead]


class ServiceError(Exception):
    """Startup configuration that must stop the process before it listens."""


@dataclass(frozen=True)
class ServiceConfig:
    secret: str
    allowlist: frozenset[str]
    concurrency: int = 1
    host: str = "127.0.0.1"
    port: int = 8080
    state_dir: Path = Path(".atlas-reviewer-state")
    provider: str = "offline"
    allow_live_inference: bool = False
    max_body_bytes: int = MAX_BODY_BYTES
    mode: str = DEFAULT_SERVICE_MODE
    # None: resolve from the mode in `serve` (`service_deadline`), whose
    # agentic default is the deadline bound's ceiling -- there the parent
    # deadline is a backstop; the child's derived wall is the real limit.
    deadline_s: float | None = None
    # The keep-or-cancel policy for a push that lands mid-review (#702,
    # D79): `keep` holds the new head back while the running review
    # finishes and queues it as its follow-up; `cancel` restores the
    # blanket supersede. `cancel_fraction` is the "early" threshold the
    # cancel branch compares the lens and spend fractions against.
    head_change_policy: str = POLICY_KEEP
    cancel_fraction: float = DEFAULT_CANCEL_FRACTION
    # The per-tenant daily spend bound (config slice S9, D81): the
    # operator's per-repo daily budget, the decided $100 default. The
    # per-installation daily cap rides the same check through
    # `DailySpend.cap_for` -- from S10's store, via
    # `InstallationStore.installation_cap` -- and the operator max per
    # review (`ATLAS_REPO_CEILING_MAX_USD`) is the child's clamp and is
    # validated here but read there from the environment.
    repo_daily_budget_usd: Decimal = DEFAULT_REPO_DAILY_BUDGET_USD
    # The retention sweep's window (config slice S10): how long an
    # installation's stored state may sit unrefreshed before the boot
    # sweep deletes it, catching a missed `installation.deleted`
    # webhook.
    installation_retention_days: int = DEFAULT_RETENTION_DAYS

    def __post_init__(self) -> None:
        if len(self.secret) < 16:
            raise ServiceError("the webhook secret must be at least 16 characters")
        if not self.allowlist:
            raise ServiceError("the repository allowlist is empty")
        if (
            isinstance(self.concurrency, bool)
            or not isinstance(self.concurrency, int)
            or not 1 <= self.concurrency <= MAX_CONCURRENCY
        ):
            raise ServiceError(
                f"concurrency must be an integer from 1 to {MAX_CONCURRENCY}"
            )
        if self.provider not in {"offline", "openrouter"}:
            raise ServiceError("provider must be offline or openrouter")
        if self.provider == "openrouter" and not self.allow_live_inference:
            raise ServiceError(
                "openrouter reviews need live inference enabled on the service"
            )
        if self.mode not in {MODE_AGENTIC, MODE_ONESHOT}:
            raise ServiceError(
                f"service mode must be {MODE_AGENTIC} or {MODE_ONESHOT}, "
                f"not {self.mode!r}"
            )
        if self.deadline_s is not None and (
            isinstance(self.deadline_s, bool)
            or not isinstance(self.deadline_s, (int, float))
            or not math.isfinite(self.deadline_s)
            or not MIN_SERVICE_DEADLINE_S <= self.deadline_s <= MAX_SERVICE_DEADLINE_S
        ):
            raise ServiceError(
                f"the review deadline must be between "
                f"{MIN_SERVICE_DEADLINE_S:.0f} and "
                f"{MAX_SERVICE_DEADLINE_S:.0f} seconds"
            )
        if self.head_change_policy not in POLICIES:
            raise ServiceError(
                f"the head-change policy must be {POLICY_KEEP} or "
                f"{POLICY_CANCEL}, not {self.head_change_policy!r}"
            )
        if (
            isinstance(self.cancel_fraction, bool)
            or not isinstance(self.cancel_fraction, (int, float))
            or not math.isfinite(self.cancel_fraction)
            or not 0.0 <= self.cancel_fraction <= 1.0
        ):
            raise ServiceError("the cancel fraction must be between 0.0 and 1.0")
        if (
            isinstance(self.repo_daily_budget_usd, bool)
            or not isinstance(self.repo_daily_budget_usd, Decimal)
            or not self.repo_daily_budget_usd.is_finite()
            or self.repo_daily_budget_usd <= 0
        ):
            raise ServiceError("the repo daily budget must be a positive dollar amount")
        if (
            isinstance(self.installation_retention_days, bool)
            or not isinstance(self.installation_retention_days, int)
            or self.installation_retention_days < 1
        ):
            raise ServiceError(
                "the installation retention window must be a positive whole "
                "number of days"
            )


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    detail: str = ""


def handle_delivery(
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
    config: ServiceConfig,
    board: Board,
    *,
    worker: Worker | None = None,
    classifier: PushClassifier | None = None,
    telemetry: Telemetry | None = None,
    admission_reader: AdmissionReader | None = None,
    spend: DailySpend | None = None,
    installations: InstallationStore | None = None,
) -> HttpResult:
    """One HTTP request. A bad signature is refused. Everything else that
    is not a queued review is acknowledged so GitHub does not keep the
    delivery open, and nothing is enqueued."""
    route = path.split("?", 1)[0]
    if method == "GET" and route == "/health":
        return HttpResult(200, b"ok\n")
    if method != "POST" or route != "/webhook":
        return HttpResult(404, b"not found\n")
    if len(body) > config.max_body_bytes:
        return HttpResult(413, b"body too large\n", "body too large")
    if not signature_matches(body, _header(headers, SIGNATURE_HEADER), config.secret):
        return HttpResult(401, b"bad signature\n", "bad signature")
    event_name = _header(headers, EVENT_HEADER)
    if event_name == "ping":
        return HttpResult(200, b"pong\n", "ping")
    if event_name == "installation.deleted":
        # The uninstall webhook (config slice S10, D81 §7 decision 8):
        # the installation's stored state -- credentials, cap and
        # consent -- is deleted here. The delivery was already
        # signature-verified above.
        payload = parse_delivery(body)
        if payload is None:
            return HttpResult(202, b"ignored\n", "ignored:body")
        return _installation_deleted(payload, installations, telemetry)
    if event_name != "pull_request":
        return HttpResult(202, b"ignored\n", "ignored:event")
    payload = parse_delivery(body)
    if payload is None:
        return HttpResult(202, b"ignored\n", "ignored:body")
    decision = admit(payload, config.allowlist)
    if isinstance(decision, Admitted):
        # The per-tenant daily bounds (config slice S9, D81) refuse before
        # any GitHub read: a repo over its day's budget -- or over its
        # installation's daily cap, when one is set -- costs no admission
        # read and no review, and the refusal is recorded, never silent.
        # The check runs again at preflight, inside the worker, because a
        # delivery can sit queued while the day's total is spent.
        if spend is not None:
            refusal, gap = spend.refusal(
                decision.event.repo, _delivery_installation(payload)
            )
            if refusal:
                _record(
                    telemetry,
                    "review skipped",
                    {**_fields(decision.event), "reason": skip_reason(refusal)},
                    error=f"{refusal} ({gap})" if gap else refusal,
                )
                return HttpResult(202, b"ignored\n", f"ignored:{skip_reason(refusal)}")
        # The handler's GitHub reads -- the admission read and, when a
        # review is running, the head-change classification -- share one
        # overall budget, so the two together cannot hold the handler
        # past GitHub's response window (round-1 review of #756, Minor
        # 2: two full budgets stacked to ~16 s).
        read_started = _monotonic()
        if admission_reader is not None:
            # The repo's own narrowing is read after the operator's
            # envelope has passed, so a fetch happens only for a
            # delivery that would otherwise be queued, and a repo can
            # only ever narrow what the operator already admits.
            admission = _repo_admission(
                admission_reader, payload, decision.event, telemetry
            )
            skipped = narrow(payload, admission)
            if isinstance(skipped, Ignored):
                _record(
                    telemetry,
                    "review skipped",
                    {**_fields(decision.event), "reason": skipped.reason},
                )
                return HttpResult(202, b"ignored\n", f"ignored:{skipped.reason}")
        return _admit_to_queue(
            decision,
            config,
            board,
            worker=worker,
            classifier=classifier,
            telemetry=telemetry,
            read_started=read_started,
        )
    return HttpResult(202, b"ignored\n", f"ignored:{decision.reason}")


def _repo_admission(
    reader: AdmissionReader,
    payload: Mapping[str, Any],
    event: PrEvent,
    telemetry: Telemetry | None,
) -> RepoAdmission:
    """The reviewed repo's own narrowing, read from the ``REVIEW.md`` on
    the repository's **default branch** -- the branch that changes only
    through reviewed merges, never the PR head and never the PR's own
    base branch, both of which a same-repo PR's author controls
    (round-1 review of #756, Major 1). An empty default branch in the
    payload is recovered by the reader's own read-only lookup.

    The read runs under the handler's shared read budget, in a helper
    thread, the way the head-change classification does. A read that
    fails, a file over the read bound, or an unusable line falls back
    to the default -- which narrows nothing, so the operator's envelope
    stands and nothing is widened -- and the gap is on the telemetry.
    No file at all is the ordinary unconfigured repo: the default
    stands, silently."""
    started = telemetry.elapsed() if telemetry is not None else 0.0
    raw, gap, timed_out = _call_bounded(
        reader,
        event.repo,
        default_branch(payload),
        budget_s=_READ_BUDGET_S,
        what="admission read",
    )
    if raw is None:
        if gap:
            _record(
                telemetry,
                "repo admission",
                _fields(event),
                start_s=started,
                error=gap,
                timed_out=timed_out,
            )
        return NO_NARROWING
    admission = parse_repo_admission(raw.decode("utf-8", errors="replace"))
    if admission.notes:
        _record(
            telemetry,
            "repo admission",
            _fields(event),
            start_s=started,
            error="; ".join(admission.notes),
        )
    return admission


PushClassifier = Callable[[PrEvent, PrEvent], PushClass]


def _delivery_installation(payload: Mapping[str, Any]) -> str:
    """The delivery's App installation id, the key the per-installation
    daily cap is looked up by (config slice S9/S10), or the empty string
    when the payload's shape does not carry one. The id is read from the
    payload when GitHub sent it and never guessed; the cap's value is
    the store's record."""
    installation = payload.get("installation")
    ident = installation.get("id") if isinstance(installation, dict) else None
    if isinstance(ident, int) and not isinstance(ident, bool) and ident > 0:
        return str(ident)
    return ""


def _installation_deleted(
    payload: Mapping[str, Any],
    installations: InstallationStore | None,
    telemetry: Telemetry | None,
) -> HttpResult:
    """The `installation.deleted` webhook (config slice S10, D81 §7
    decision 8): the installation's stored state -- credentials, daily
    cap and consent -- is deleted now, and the retention sweep
    (`ATLAS_INSTALLATION_RETENTION_DAYS`) catches a delivery this
    handler never saw.

    A delivery whose payload does not identify an installation is
    acknowledged and ignored, with the gap recorded: nothing can be
    deleted for an installation the delivery does not name. A store the
    service cannot read right now is answered **500**, not 202 -- GitHub
    re-delivers a webhook it did not receive an acceptance for, so the
    deletion is retried instead of lost -- with the store's failure
    named on the telemetry."""
    ident = _delivery_installation(payload)
    if not ident:
        _record(
            telemetry,
            "installation deleted",
            {"reason": "no-installation-id"},
            error=(
                "the delivery names no installation id; nothing could be "
                "deleted, and the retention sweep is what will catch the "
                "record"
            ),
        )
        return HttpResult(202, b"ignored\n", "ignored:shape")
    if installations is None or (
        not installations.configured and not installations.broken_reason
    ):
        # The unconfigured store never stored anything: the deletion is
        # already true.
        _record(telemetry, "installation deleted", {"installation": ident})
        return HttpResult(200, b"ok\n", "deleted:none-stored")
    try:
        installations.delete(ident)
    except InstallationStoreError as exc:
        _record(
            telemetry,
            "installation deleted",
            {"installation": ident},
            error=str(exc),
        )
        return HttpResult(500, b"store unavailable\n", "store unavailable")
    _record(telemetry, "installation deleted", {"installation": ident})
    return HttpResult(200, b"ok\n", "deleted")


def _admit_to_queue(
    decision: Admitted,
    config: ServiceConfig,
    board: Board,
    *,
    worker: Worker | None,
    classifier: PushClassifier | None,
    telemetry: Telemetry | None,
    read_started: float | None = None,
) -> HttpResult:
    """Queue an admitted delivery, deciding keep-or-cancel first (#702).

    Under the `keep` policy a delivery that would supersede a running or
    posting review is decided instead: `classify_delivery` fetches the
    range between the two heads, the review's own progress is read back
    from its events file, and `decide` keeps or cancels. The decision is
    recorded as telemetry either way. Under the `cancel` policy the
    supersede is decided by the queue alone, exactly as before this
    policy existed. `read_started` is when the handler began its GitHub
    reads; the classification gets what is left of the one shared read
    budget after the admission read (round-1 review of #756, Minor 2)."""
    settled: list[Job] = []
    candidate = (
        board.head_change_candidate(decision.event, at=decision.updated_at)
        if config.head_change_policy == POLICY_KEEP
        else None
    )
    if candidate is None:
        result = board.enqueue(
            decision.event, at=decision.updated_at, superseded=settled
        )
    else:
        budget = (
            _READ_BUDGET_S - (_monotonic() - read_started)
            if read_started is not None
            else _READ_BUDGET_S
        )
        verdict = _head_change_decision(
            candidate, decision.event, config, classifier, telemetry, budget
        )
        if verdict.cancel:
            result = board.enqueue(
                decision.event, at=decision.updated_at, superseded=settled
            )
        else:
            result = board.keep_head(
                decision.event, at=decision.updated_at, superseded=settled
            )
    if worker is not None:
        for job in settled:
            worker._stored_supersede(job, JobState.SUPERSEDED)
    if result is Enqueue.FULL:
        return HttpResult(503, b"full\n", "full")
    return HttpResult(202, f"{result.value}\n".encode(), result.value)


def _head_change_decision(
    candidate: Job,
    new_event: PrEvent,
    config: ServiceConfig,
    classifier: PushClassifier | None,
    telemetry: Telemetry | None,
    budget_s: float | None = None,
) -> Decision:
    """The keep-or-cancel decision for one mid-review push, and its
    telemetry record. A classification failure keeps the review and
    records the gap; the progress read can only contribute nothing.
    ``budget_s`` is what is left of the handler's shared read budget;
    None means the caller did not bound it and the full budget stands."""
    budget = _READ_BUDGET_S if budget_s is None else budget_s
    posting = candidate.state is JobState.POSTING
    push: PushClass | None = None
    gap = ""
    timed_out = False
    started = telemetry.elapsed() if telemetry is not None else 0.0
    if not posting and classifier is not None:
        if budget <= 0:
            # The admission read spent the handler's shared read budget;
            # the classification gets none. The keep verdict is the
            # owner's default, and the spent budget is the named gap, so
            # a deployment whose reads are slow is visible rather than
            # silently keep-everything.
            gap = "the handler's read budget was spent on the admission read"
        else:
            push, gap, timed_out = _call_bounded(
                classifier,
                candidate.event,
                new_event,
                budget_s=budget,
                what="classification",
            )
            if not isinstance(push, PushClass):
                # The guard the pre-generalization helper carried
                # (round-1 review of #756, Nit 5): a misbehaving
                # classifier's answer is unclassifiable, not a verdict.
                push = None
    elif not posting:
        # No classifier on this deployment -- the App credentials are
        # absent or unusable -- so the push could not be classified and
        # the cancel branch cannot fire. That is the owner's default
        # direction, but it is a gap, not a normal decision: the event
        # carries it with an error status, so a deployment that lost its
        # credentials is visible in the telemetry instead of silently
        # keep-everything (round-1 review of #747, F3).
        gap = (
            "no head-change classifier is configured; the push could not be classified"
        )
    progress = (
        None
        if posting
        else read_progress(*_progress_paths(config.state_dir, candidate.event))
    )
    if not posting and candidate.state is JobState.POSTING:
        # The snapshot was taken before the <=8s classification window;
        # the review crossed into posting during it. Re-read rather than
        # decide on the stale snapshot, so the recorded verdict and the
        # action the caller takes agree (round-3 review of #747, R3-F5).
        posting = True
    verdict = decide(push, progress, config.cancel_fraction, posting=posting)
    _record(
        telemetry,
        "head change",
        _decision_fields(candidate, new_event, push, verdict),
        start_s=started,
        error=gap,
        timed_out=timed_out,
    )
    return verdict


def _decision_fields(
    candidate: Job,
    new_event: PrEvent,
    push: PushClass | None,
    verdict: Decision,
) -> dict[str, str | int]:
    fields: dict[str, str | int] = {
        **_fields(new_event),
        "from": candidate.event.head_sha[:12],
    }
    if push is not None:
        fields["kind"] = push.kind.value
    fields.update(
        {
            "decision": DECISION_CANCEL if verdict.cancel else DECISION_KEEP,
            "reason": verdict.reason,
            "lens_fraction": f"{verdict.lens_fraction:.2f}",
            "spend_fraction": f"{verdict.spend_fraction:.2f}",
        }
    )
    return fields


def _record(
    telemetry: Telemetry | None,
    step: str,
    fields: dict[str, str | int],
    *,
    start_s: float | None = None,
    error: str = "",
    timed_out: bool = False,
) -> None:
    if telemetry is None:
        return
    try:
        if timed_out:
            fields = {**fields, "timed_out": "1"}
        telemetry.record(
            "service",
            step,
            fields,
            status=ERROR if error else OK,
            start_s=start_s,
            error=error,
        )
    except Exception:  # noqa: BLE001, S110 -- the log itself failed; the decision stands
        pass


def _progress_paths(state_root: Path, running: PrEvent) -> tuple[Path, ...]:
    run = run_dir(state_root, running)
    events = run / "events.jsonl"
    return (events.with_name(events.name + ".1"), events)


def _backfill_crashed_spend(
    spend: DailySpend | None,
    state_root: Path,
    event: PrEvent,
    telemetry: Telemetry | None,
) -> None:
    """Backfill one crashed attempt's committed spend onto the day's
    ledger (r1 review of #773, M1).

    A review whose process died before the worker could settle it never
    reached the settle-time spend recording, so its committed spend --
    the child's own token-counts-times-price-table accounting, from the
    progress records the crash left in the run directory -- is appended
    before the retry appends over it, exactly once. The events file is
    append-only across a head's attempts, so the figure is scoped to the
    crashed attempt's own span (`head_change.last_run_progress`: the
    run-start line plus that run's progress records): a retry that
    appended its startup events and died before its first progress
    record has no figure of its own, and the previous attempt's stale
    tail is not re-counted (r2 review of #773, M-R2-1).

    No run directory at all is the ordinary first run of a head -- or a
    pending head that was re-queued without ever having run -- and is
    silent. A directory left behind with no figure of the crashed
    attempt's own records nothing, and the gap is named on the
    telemetry, where the unrecorded possibility stays visible -- the
    overshoot bound carries it the way it carries the race. An
    over-count, were one ever to land, fails safe: it makes the bounds
    refuse earlier, never later. A recovery that crosses the UTC
    boundary backfills into the recovery day's ledger -- the day the
    retry is admitted under -- which is the same safe direction."""
    if spend is None:
        return
    paths = _progress_paths(state_root, event)
    if not run_dir(state_root, event).is_dir():
        return
    evidence = last_run_progress(*paths)
    fields: dict[str, str | int] = dict(_fields(event))
    if evidence is None:
        _record(
            telemetry,
            "crashed spend",
            fields,
            error=(
                "the crashed attempt's run directory holds no progress "
                "figure of its own; its spend, if any, is unrecorded "
                "(the overshoot bound carries it)"
            ),
        )
        return
    progress, key = evidence
    fields.update(
        {
            "calls": progress.calls,
            "committed_usd": str(progress.committed_usd),
            "billed_usd": str(progress.billed_usd),
            "settled_usd": str(progress.settled_usd),
            "held_usd": str(progress.held_usd),
            "measured": "backfilled",
        }
    )
    try:
        appended, gap = spend.record_once(
            event.repo,
            progress.billed_usd,
            progress.calls,
            key,
            source=progress.source,
        )
    except OSError as exc:
        _record(
            telemetry,
            "crashed spend",
            fields,
            error=f"{type(exc).__name__}: {exc}",
        )
        return
    if gap:
        fields["measured"] = "unknown"
        _record(telemetry, "crashed spend", fields, error=gap)
        return
    if not appended:
        fields["measured"] = "already recorded"
    _record(telemetry, "crashed spend", fields)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    return lowered.get(name.lower())


def _key_refusal_report(cause: str) -> ReviewReport:
    """The posted review when a key refusal is the whole outcome (D92)."""
    return ReviewReport(
        (),
        (),
        "",
        (),
        (),
        (),
        "",
        review_error=cause,
        coverage_complete=False,
    )


class Worker:
    """Claims queued jobs and runs them. A publisher, when set, is called
    only after a review that was not superseded and did not fail."""

    def __init__(
        self,
        board: Board,
        runner: Runner,
        telemetry: Telemetry,
        publisher: Publisher | None = None,
        concurrency: int = 1,
        state_root: Path | None = None,
        now: Callable[[], float] | None = None,
        spend: DailySpend | None = None,
        installation: str = "",
        *,
        funding: FundingSelector | None = None,
        tenant_active: Callable[[], bool] | None = None,
    ) -> None:
        self._board = board
        self._runner = runner
        self._telemetry = telemetry
        self._publisher = publisher
        self._concurrency = concurrency
        self._state_root = state_root or Path(".atlas-reviewer-state")
        self._now = now or time.time
        self._random = random.random
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # The per-tenant daily bounds (config slice S9, D81): the
        # preflight re-check runs here, inside the worker, because a
        # delivery can sit queued while the day's total is spent; the
        # spend recording rides the settle-time cost event. The
        # installation id is the configured one -- at preflight the
        # payload is long gone; admission resolves it from the payload
        # when GitHub sent it.
        self._spend = spend
        self._installation = installation
        # The operator's funding list (D94). None is today's single key:
        # the worker does not probe and does not name a source. A tenant
        # run never consults the list.
        self._funding = funding
        self._tenant_active = tenant_active or (lambda: False)
        # The D92 cause recorded for a head that advanced off a refused
        # source. Keyed by repository, pull request, and head, and
        # cleared when that job settles. Another head does not read it.
        self._head_causes: dict[tuple[str, int, str], str] = {}

    def healthy(self) -> bool:
        """False once a worker thread has died. ``/health`` then fails
        so a dead worker is not hidden behind a 200."""
        return bool(self._threads) and all(
            thread.is_alive() for thread in self._threads
        )

    def start(self) -> None:
        for index in range(self._concurrency):
            thread = threading.Thread(target=self._loop, name=f"atlas-review-{index}")
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = CLEANUP_WAIT_S) -> None:
        """Cancel an in-flight review so its child can delete the Sprite,
        then wait for the workers. ``timeout`` is per worker thread, and
        the default is the child's Sprite cleanup wait."""
        self._stop.set()
        self._board.cancel_active()
        self._board.wake()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def run_one(self) -> bool:
        if self._stop.is_set():
            return False
        self._recover()
        job = self._board.claim()
        if job is None:
            return False
        if self._stop.is_set():
            self._stored_supersede(job, self._board.release_claim(job))
            return False
        try:
            self._execute(job)
        except Exception as exc:  # noqa: BLE001 -- one job must not kill the worker
            self._fail_closed(job, exc)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._board.wait_for_work(
                    _POLL_S,
                    self._stop,
                    self._now(),
                    posts=self._publisher is not None,
                )
                if self._stop.is_set():
                    return
                self.run_one()
                if self._stop.is_set():
                    return
                self._retry_post()
            except Exception as exc:  # noqa: BLE001 -- the thread has to outlive one failure
                event = getattr(exc, "event", None)
                try:
                    self._telemetry.record(
                        "service",
                        "worker error",
                        _fields(event) if event is not None else {},
                        status=ERROR,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:  # noqa: BLE001, S110 -- the log itself failed
                    pass

    def _retry_post(self) -> None:
        if self._publisher is None:
            return
        if self._stop.is_set():
            return
        job = self._board.claim_post(self._now(), stop=self._stop)
        if job is None:
            return
        try:
            self._publish_saved(job)
        except Exception as exc:  # noqa: BLE001 -- a post retry must not kill the worker
            self._fail_closed(job, exc)

    def _recover(self) -> None:
        """Queue a pending head whose pull request has no active job
        (round-1 review of #747, F7): the crash window inside a review's
        ``settle`` -- the one lock and save that stores the review's
        terminal state and installs its follow-up together -- a failed
        settle save, and a full queue at settle time can all strand one,
        and a redelivery of that
        head is answered duplicate, so without the recovery it is never
        reviewed. Runs on every worker pass; it installs only when there
        is something to install. Before each head is re-queued, the
        crashed attempt's own committed spend is backfilled onto the
        day's ledger once (r1 review of #773, M1) -- a pending head that
        never ran has no run directory and is passed over silently; the
        pre-runner pass in `_execute` covers the head a plain crash left
        running, which the queue's own reload re-queues without ever
        reaching this loop."""
        try:
            for event in self._board.recover_pending():
                _backfill_crashed_spend(
                    self._spend, self._state_root, event, self._telemetry
                )
                self._telemetry.record("service", "follow-up queued", _fields(event))
        except Exception as exc:  # noqa: BLE001 -- recovery must not kill the worker
            self._telemetry.record(
                "service",
                "worker error",
                {},
                status=ERROR,
                error=f"pending-head recovery failed: {type(exc).__name__}: {exc}",
            )

    def _fail_closed(self, job: Job, exc: BaseException) -> None:
        """The job stays FAILED when the save works. When the save itself
        raises, the in-memory state is left as it was so a restart can
        queue a ``running`` job again, and the thread keeps going."""
        note = f"{type(exc).__name__}: {exc}"
        if job.state in {
            JobState.DONE,
            JobState.FAILED,
            JobState.SUPERSEDED,
            JobState.POST_PENDING,
        }:
            note += "; left the settled job alone"
            self._telemetry.record(
                "service",
                "worker error",
                _fields(job.event),
                status=ERROR,
                error=note,
            )
            return
        try:
            committed = self._settle(job, JobState.FAILED)
        except Exception as save_exc:  # noqa: BLE001 -- the thread still has to record why
            note += f"; queue save failed: {type(save_exc).__name__}"
        else:
            if committed is JobState.SUPERSEDED:
                self._note(job, committed, _fields(job.event))
        self._telemetry.record(
            "service",
            "worker error",
            _fields(job.event),
            status=ERROR,
            error=note,
        )

    def _head_cause(self, job: Job) -> str:
        """The D92 cause recorded for this head, or empty."""
        return self._head_causes.get(job.key(), "")

    def _forget_head_cause(self, job: Job) -> None:
        self._head_causes.pop(job.key(), None)

    def _begin_funding(
        self, job: Job
    ) -> tuple[ReviewRun | None, contextvars.Token[FundingChoice | None] | None]:
        """Select the source for this claim, or a run that replaces the child.

        No registry is today's single key: the child starts with whatever
        ``ATLAS_OPENROUTER_API_KEY`` the parent already holds. A tenant
        run does not select, and a store that cannot be read fails the
        review instead of falling through to an operator source. Every
        source refused posts the D92 error without a child. This head's
        recorded cause, when it has one, is the post, including when
        every source is now unavailable. When every source is already
        unavailable and this head has no recorded cause, the post says
        no funding source is available and names each source with its
        cause, in spend order. That post is the selector's state. A
        probe that failed, a blank key, or a key over its ceiling does
        not mark the source unavailable, so that claim fails without a
        post: the next claim can try the source, and a post would say
        the sources are exhausted when they are not."""
        if self._funding is None:
            return None, None
        try:
            tenant = self._tenant_active()
        except InstallationStoreError as exc:
            return ReviewRun(False, error=f"the tenant path refused: {exc}"), None
        if tenant:
            return None, None
        selection = self._funding.choose()
        if selection.choice is not None:
            return None, active_choice.set(selection.choice)
        # This head already advanced off a refused source. That cause
        # wins over the selector-wide notice, including when every
        # source is now unavailable. Another head's cause is not this.
        remembered = self._head_cause(job)
        if remembered:
            return ReviewRun(True, _key_refusal_report(remembered)), None
        notice = self._funding.unavailable_notice()
        if notice:
            return ReviewRun(True, _key_refusal_report(notice)), None
        # A probe that failed, a blank key, or a key over its ceiling
        # leaves the source eligible. Nothing is posted.
        return (
            ReviewRun(
                False,
                error=selection.error or "no funding source is available",
            ),
            None,
        )

    def _advance_on_refusal(
        self, job: Job, report: ReviewReport, choice: FundingChoice | None
    ) -> bool:
        """Re-queue this head on the next source after a key refusal.

        True when this attempt was pinned to one source and another can
        still serve the model. The settled bill is recorded, that
        attempt's run directory is dropped so the next claim cannot
        read the same progress back onto the ledger, and nothing is
        posted. The D92 post is the attempt that finds no further
        source. A tenant run has no choice, so its refusal never advances
        onto an operator source. A review that failed for any other
        reason, including a 429, is not this. A crash between the cost
        record and the run-dir drop leaves the directory on disk with
        the bill already recorded. Recovery re-queues a running job, and
        the next claim's backfill can record that span again. Dropping
        the directory first would lose the bill, so the record stays
        first. The window is the same shape as a crash between the cost
        record and a normal settle."""
        if (
            choice is None
            or self._funding is None
            or report.review_error not in {KEY_OUT_OF_CREDIT, KEY_AUTH_REFUSED}
        ):
            return False
        if not self._funding.mark_refused(choice.name, report.review_error):
            return False
        # The first refusal this head advanced off. A later advance of
        # the same head does not replace it.
        self._head_causes.setdefault(job.key(), report.review_error)
        self._cost_event(job, report, source=choice.name)
        self._telemetry.record(
            "service",
            "refusal advance",
            {
                **_fields(job.event),
                "source": choice.name,
                "cause": report.review_error,
            },
        )
        self._drop_run_dir(job)
        self._stored_supersede(job, self._board.release_claim(job))
        return True

    def _budget_stops(self, job: Job, fields: dict[str, str | int]) -> bool:
        """True when the day's budget stops this claim before a review.

        The crash backfill runs first, so a crashed attempt's spend
        counts against the bounds the retry is admitted under. With no
        funding refusal behind the stop, nothing is posted. A head that
        already advanced off a refused source still posts the cause
        recorded for this head. Another head's cause is not posted."""
        if self._spend is None:
            return False
        _backfill_crashed_spend(
            self._spend, self._state_root, job.event, self._telemetry
        )
        refusal, gap = self._spend.refusal(job.event.repo, self._installation)
        if not refusal:
            return False
        self._telemetry.record(
            "service",
            "review skipped",
            {**fields, "reason": skip_reason(refusal)},
            status=ERROR,
            error=f"{refusal} ({gap})" if gap else refusal,
        )
        remembered = self._head_cause(job)
        if remembered:
            self._publish(job, _key_refusal_report(remembered))
            return True
        committed = self._settle(job, JobState.FAILED)
        if committed is JobState.SUPERSEDED:
            self._note(job, committed, fields)
        return True

    def _note_skipped_sources(self, fields: dict[str, str | int]) -> None:
        """One event naming the sources this claim will not probe."""
        if self._funding is None:
            return
        names = self._funding.unavailable_names()
        if not names:
            return
        self._telemetry.record(
            "service",
            "funding source skipped",
            {**fields, "sources": ",".join(names)},
        )

    def _execute(self, job: Job) -> None:
        fields = _fields(job.event)
        if self._budget_stops(job, fields):
            return
        self._telemetry.record(
            "service",
            "runner named",
            {**fields, "runner": event_runner_name(job.event)},
        )
        token: contextvars.Token[FundingChoice | None] | None = None
        choice: FundingChoice | None = None
        try:
            skipped, token = self._begin_funding(job)
            self._note_skipped_sources(fields)
            if token is not None:
                choice = active_choice.get()
            run = (
                skipped if skipped is not None else self._runner(job.event, job.cancel)
            )
        except Exception as exc:  # noqa: BLE001 -- a review bug must not post
            run = ReviewRun(False, error=f"{type(exc).__name__}: {exc}")
        finally:
            if token is not None:
                active_choice.reset(token)
        source_name = choice.name if choice is not None else ""
        if job.superseded:
            self._cost_event(job, None, source=source_name)
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        if job.cancel.is_set():
            # Stop is not a supersede. The same commit can be reviewed
            # again after the process starts. A newer head that landed
            # after the check above is SUPERSEDED, and that directory
            # still has to go.
            self._cost_event(job, None, source=source_name)
            self._stored_supersede(job, self._board.release_claim(job))
            return
        if not run.ok or run.report is None:
            self._cost_event(job, None, source=source_name)
            committed = self._settle(job, JobState.FAILED)
            if committed is JobState.SUPERSEDED:
                self._note(job, committed, fields)
                return
            self._telemetry.record(
                "service",
                "review failed",
                fields,
                status=ERROR,
                error=run.error or "review failed",
            )
            return
        if self._advance_on_refusal(job, run.report, choice):
            return
        self._cost_event(job, run.report, source=source_name)
        if not self._board.still_current(job):
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        self._publish(job, run.report)

    def _cost_event(
        self, job: Job, report: ReviewReport | None, *, source: str = ""
    ) -> None:
        """The review's cost, logged when it settles (#702's measure-first
        rule): a finished review's cost comes from its draft's cost lines;
        a cancelled or failed one's from the progress figure of its own
        last run, read before the run directory goes. A last run with no
        figure of its own records nothing, so an earlier run's records
        left in the directory are not billed again. A review whose cost
        is in neither is logged as unknown, so the gap between the
        decision records and the cost records stays visible."""
        fields: dict[str, str | int] = dict(_fields(job.event))
        cost = review_cost(report) if report is not None else None
        # The progress evidence's hash is the attempt's identity in the
        # ledger, and its figure is that span's own bill. The first
        # settlement and a later backfill of the same span both carry
        # the hash, so a drop that fails after the settlement does not
        # bill the span again. A failed attempt whose span has no figure
        # of its own records nothing: an earlier span left in the
        # directory is not this attempt's bill.
        evidence = last_run_progress(*_progress_paths(self._state_root, job.event))
        attempt_key = evidence[1] if evidence is not None else ""
        progress = None
        if cost is not None:
            billed = Decimal(cost[1])
            held = Decimal(cost[2])
            fields.update(
                {
                    "calls": cost[0],
                    "billed_usd": cost[1],
                    "held_usd": cost[2],
                    # Nothing is in flight on a finished draft, so the
                    # ceiling figure is the bill plus what is still held.
                    "committed_usd": str(billed + held),
                    "measured": "final",
                }
            )
        else:
            progress = evidence[0] if evidence is not None else None
            if progress is not None:
                fields.update(
                    {
                        "calls": progress.calls,
                        "committed_usd": str(progress.committed_usd),
                        "billed_usd": str(progress.billed_usd),
                        "settled_usd": str(progress.settled_usd),
                        "held_usd": str(progress.held_usd),
                        "measured": "partial",
                    }
                )
            else:
                fields["measured"] = "unknown"
        self._record_spend(job, cost, progress, fields, attempt_key, source)
        self._telemetry.record("service", "review cost", fields)

    def _record_spend(
        self,
        job: Job,
        cost: tuple[int, str, str] | None,
        progress: object,
        fields: dict[str, str | int],
        attempt_key: str = "",
        source: str = "",
    ) -> None:
        """Append the review's settled bill to the day's ledger (config
        slice S9, D81, D93). The figure is the review child's known bill
        -- reported token counts priced at the operator's price table,
        $0 for a non-200 answer, the reservation for a served response
        that could not be priced, never a tenant-reported dollar figure
        and never a reservation held because the request was written and
        never answered -- from the finished draft's cost line, or from
        the last progress record
        when the review did not finish; the final-over-partial precedence is
        `_cost_event`'s by construction, which reads the progress record
        only when the draft's cost line is absent, so this method never
        sees both figures for one review. A review with no figure in
        either records
        nothing: the amount is never guessed, and the gap the cost event
        carries is where the miss stays visible. A write failure is a
        named gap and leaves the total short rather than wrong. When the
        attempt has progress evidence, the bill is recorded once under
        that evidence's key. An unreadable ledger is not appended to:
        its total is unknown, the gap is logged as spend not recorded,
        and the day's budget already holds."""
        if self._spend is None:
            return
        if cost is not None:
            amount, calls = Decimal(cost[1]), cost[0]
            named = source
        elif isinstance(progress, Progress):
            amount, calls = progress.billed_usd, progress.calls
            named = source or progress.source
        else:
            return
        if attempt_key:
            try:
                _appended, gap = self._spend.record_once(
                    job.event.repo, amount, calls, attempt_key, source=named
                )
            except OSError as exc:
                gap = f"{type(exc).__name__}: {exc}"
            if gap:
                self._telemetry.record(
                    "service",
                    "spend not recorded",
                    fields,
                    status=ERROR,
                    error=gap,
                )
            return
        try:
            self._spend.record(job.event.repo, amount, calls, source=named)
        except OSError as exc:
            self._telemetry.record(
                "service",
                "spend not recorded",
                fields,
                status=ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _publish(self, job: Job, report: ReviewReport) -> None:
        fields = _fields(job.event)
        if not self._board.still_current(job):
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        if self._publisher is None:
            # Keep the draft. This process publishes nothing, and the
            # draft is the record of the review. The child's stderr is
            # not: it can hold a secret the log scrubber would remove.
            committed, follow_up = self._board.settle(
                job, JobState.DONE, covered=report.coverage_complete is True
            )
            if committed is JobState.SUPERSEDED:
                self._drop_run_dir(job)
                self._telemetry.record("service", "review superseded", fields)
                return
            if follow_up is not None:
                self._telemetry.record(
                    "service", "follow-up queued", _fields(follow_up)
                )
            stderr = run_dir(self._state_root, job.event) / "stderr.txt"
            if stderr.is_file():
                try:
                    stderr.unlink()
                except OSError as exc:
                    self._telemetry.record(
                        "service",
                        "stderr not removed",
                        fields,
                        status=ERROR,
                        error=f"{type(exc).__name__}: {exc}",
                    )
            self._telemetry.record("service", "review finished", fields)
            return
        token = before_send.set(lambda: self._board.begin_post(job))
        try:
            self._send(job, report)
        finally:
            before_send.reset(token)

    def _send(self, job: Job, report: ReviewReport) -> None:
        assert self._publisher is not None
        fields = _fields(job.event)
        if not self._board.begin_post(job):
            self._stopped_or_superseded(job, fields)
            return
        # stop() can land after the claim moved the job to POSTING and
        # before this send. begin_post has already returned.
        if self._stop.is_set() or job.cancel.is_set():
            self._stopped_or_superseded(job, fields)
            return
        # A synthetic refusal has no child draft. Persist one before the
        # publisher runs, so a rate limit or a transient error retries
        # the same cause from disk. An existing child draft is left as
        # the child wrote it. A cause this service does not post is not
        # written.
        if report.review_error and known_review_error(report.review_error):
            try:
                self._save_refusal_draft(job, report.review_error)
            except OSError as exc:
                self._record_post_refusal(
                    job,
                    fields,
                    f"could not save the refusal draft: {type(exc).__name__}: {exc}",
                )
                return
        try:
            already = self._publisher(job.event, report)
        except PostNotCurrent:
            # begin_post refused. A stop keeps the draft. A moved head
            # is SUPERSEDED. Settling every refusal as SUPERSEDED deletes
            # a finished review that a restart should still post.
            self._stopped_or_superseded(job, fields)
            return
        except PostHookMissing as exc:
            self._record_post_refusal(job, fields, f"post hook missing: {exc}")
            return
        except PostAuthError as exc:
            self._record_post_refusal(job, fields, f"post auth refused: {exc}")
            return
        except PostRejected as exc:
            self._record_post_refusal(job, fields, f"post rejected: {exc}")
            return
        except RateLimited as exc:
            self._defer_post(job, str(exc), retry_after=exc.retry_after)
            return
        except Exception as exc:  # noqa: BLE001 -- a post failure must not post again here
            self._defer_post(job, f"{type(exc).__name__}: {exc}")
            return
        committed = self._settle(
            job, JobState.DONE, covered=report.coverage_complete is True
        )
        if committed is JobState.SUPERSEDED:
            step = "review superseded"
        elif already:
            step = "review already posted"
        else:
            step = "review posted"
        self._telemetry.record("service", step, fields)

    def _record_post_refusal(
        self, job: Job, fields: dict[str, str | int], error: str
    ) -> None:
        committed = self._settle(job, JobState.FAILED)
        if committed is JobState.SUPERSEDED:
            self._note(job, committed, fields)
            return
        self._telemetry.record(
            "service",
            "review post failed",
            fields,
            status=ERROR,
            error=error,
        )

    def _save_refusal_draft(self, job: Job, cause: str) -> None:
        """Write the synthetic refusal as the draft a retry posts. A
        draft already there is kept when it carries this same cause, and
        replaced when it carries another, so a directory a failed drop
        kept cannot make the retry post the earlier attempt. The status
        line is the agentic shape `summarize_draft` reads back, and the
        cause is one `known_review_error` already accepted."""
        path = run_dir(self._state_root, job.event) / "draft.md"
        if path.is_file() and self._draft_cause(path) == cause:
            return
        make_private_dirs(path.parent)
        status = {
            "coverage_complete": False,
            "mode": MODE_AGENTIC,
            "review_error": cause,
        }
        path.write_text(
            f"{STATUS_PREFIX}{json.dumps(status, sort_keys=True)} -->\n",
            encoding="utf-8",
        )

    def _draft_cause(self, path: Path) -> str:
        """The cause a saved draft would post, or empty when it is not
        one this service can read."""
        try:
            report = summarize_draft(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, DraftParseError, ValueError):
            return ""
        return report.review_error

    def _publish_saved(self, job: Job) -> None:
        """A post that failed after the draft was written. The review is
        not run again. A missing draft posts nothing."""
        from atlas_reviewer.service_run import summarize_draft

        path = run_dir(self._state_root, job.event) / "draft.md"
        if not path.is_file() or self._publisher is None:
            committed = self._settle(job, JobState.FAILED)
            if committed is not JobState.SUPERSEDED:
                self._telemetry.record(
                    "service",
                    "review post failed",
                    _fields(job.event),
                    status=ERROR,
                    error="no draft to post",
                )
            else:
                self._note(job, committed, _fields(job.event))
            return
        try:
            report = summarize_draft(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            self._defer_post(job, f"{type(exc).__name__}: {exc}")
            return
        self._publish(job, report)

    def _defer_post(
        self, job: Job, error: str, *, retry_after: float | None = None
    ) -> None:
        """Try the post again later, up to ``MAX_POST_ATTEMPTS``. After
        that the review stays unpublished and the job is failed, so a
        dead endpoint cannot spin the worker. A rate-limit wait replaces
        the schedule when it is longer."""
        if job.superseded or job.cancel.is_set():
            self._stopped_or_superseded(job, _fields(job.event))
            return
        job.attempts += 1
        fields = _fields(job.event)
        if job.attempts >= MAX_POST_ATTEMPTS:
            committed = self._settle(job, JobState.FAILED)
            if committed is JobState.SUPERSEDED:
                self._note(job, committed, fields)
                return
            self._telemetry.record(
                "service",
                "review post failed",
                {**fields, "attempts": job.attempts},
                status=ERROR,
                error=f"post attempts exhausted: {error}",
            )
            return
        base = _POST_BACKOFF_S[min(job.attempts - 1, len(_POST_BACKOFF_S) - 1)]
        delay = base * (1 + self._random() * _BACKOFF_JITTER)
        if retry_after is not None:
            delay = max(delay, retry_after)
        job.retry_at = self._now() + delay
        committed = self._settle(job, JobState.POST_PENDING)
        if committed is JobState.SUPERSEDED:
            self._note(job, committed, fields)
            return
        self._telemetry.record(
            "service",
            "review post failed",
            {**fields, "attempts": job.attempts, "retry_s": round(delay, 3)},
            status=ERROR,
            error=error,
        )

    def _stopped_or_superseded(self, job: Job, fields: dict[str, str | int]) -> None:
        """A real supersede ends the job. A stop puts it back so the same
        commit is reviewed or posted after the process starts again."""
        if job.superseded:
            self._note(job, self._settle(job, JobState.SUPERSEDED), fields)
            return
        if job.state is JobState.POSTING:
            stored = self._board.pause_post(job)
        else:
            stored = self._board.release_claim(job)
        if stored is JobState.SUPERSEDED:
            self._stored_supersede(job, stored)
            return
        if stored in {JobState.QUEUED, JobState.POST_PENDING}:
            self._telemetry.record("service", "review stopped", fields)

    def _settle(self, job: Job, state: JobState, *, covered: bool = True) -> JobState:
        """The terminal state stored and the kept head's follow-up taken
        as one queue step (`Board.settle`, round-2 review of #747,
        R2-F4): the recovery pass can no longer interleave between the
        review's settle and its follow-up's install, and one save covers
        both, so a crash cannot strand a head between them. `covered` is
        the finished review's report flag on the DONE path: a review
        that did not read every changed file queues its follow-up as an
        ordinary full review, not as a delta on top of it (round-5
        review of #748)."""
        committed, follow_up = self._board.settle(job, state, covered=covered)
        if committed in {JobState.DONE, JobState.FAILED, JobState.SUPERSEDED}:
            self._forget_head_cause(job)
            self._drop_run_dir(job)
        if follow_up is not None:
            self._telemetry.record("service", "follow-up queued", _fields(follow_up))
        return committed

    def _stored_supersede(self, job: Job, stored: JobState | None) -> None:
        """The Board settled a supersede the worker had not seen yet.

        ``release_claim`` and ``pause_post`` decide under the lock. When
        they store SUPERSEDED, this is the cleanup ``_settle`` would have
        run, including the log line.
        """
        if stored is not JobState.SUPERSEDED:
            return
        self._forget_head_cause(job)
        self._drop_run_dir(job)
        self._note(job, stored, _fields(job.event))

    def _drop_run_dir(self, job: Job) -> None:
        path = run_dir(self._state_root, job.event)
        if not path.is_dir():
            return
        try:
            shutil.rmtree(path)
        except OSError as exc:
            self._telemetry.record(
                "service",
                "run dir not removed",
                _fields(job.event),
                status=ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _note(
        self, job: Job, committed: JobState, fields: dict[str, str | int]
    ) -> None:
        del job
        step = (
            "review superseded"
            if committed is JobState.SUPERSEDED
            else "review finished"
        )
        self._telemetry.record("service", step, fields)


def _fields(event: PrEvent) -> dict[str, str | int]:
    fields: dict[str, str | int] = {
        "pr": event.pr_number,
        "sha12": event.head_sha[:12],
        "repo": event.repo,
    }
    if event.delta_from:
        fields["delta_from"] = event.delta_from[:12]
    return fields


class _Handler(BaseHTTPRequestHandler):
    server: ReviewServer
    timeout = _REQUEST_TIMEOUT_S

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        worker = getattr(self.server, "worker", None)
        if route == "/health" and (
            (worker is not None and not worker.healthy())
            or not self.server.board.saves_ok()
        ):
            self._send(503, b"unhealthy\n")
            self.server.log("atlas-reviewer: http 503 GET /health")
            return
        self._respond(b"")

    def do_POST(self) -> None:
        if not self.server.slots.acquire(blocking=False):
            self._send(429, b"busy\n")
            self.server.log("atlas-reviewer: http 429 POST /webhook busy")
            return
        try:
            self._read_post()
        finally:
            self.server.slots.release()

    def _read_post(self) -> None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isascii() or not raw.isdigit():
            self._send(411, b"length required\n")
            return
        # Longer than the decimal length of the body cap. Reject before int().
        if len(raw) > len(str(self.server.config.max_body_bytes)):
            self._send(413, b"body too large\n")
            return
        length = int(raw)
        if length > self.server.config.max_body_bytes:
            self._send(413, b"body too large\n")
            return

        # arm() narrows the socket timeout to the body budget. The
        # response write uses the handler timeout again.
        previous = self.connection.gettimeout()

        def arm(seconds: float) -> None:
            # The buffered reader otherwise waits for the whole chunk.
            # The socket timeout is the time left on the body deadline.
            self.connection.settimeout(max(seconds, 0.05))

        try:
            body = read_bounded(
                self.rfile.read1,
                length,
                _monotonic() + _BODY_BUDGET_S,
                _monotonic,
                arm=arm,
            )
        finally:
            self.connection.settimeout(previous)
        if body is None:
            self._send(408, b"timeout\n")
            self.server.log("atlas-reviewer: http 408 POST /webhook slow body")
            return
        self._respond(body)

    def log_message(self, fmt: str, *args: object) -> None:
        """The access log would record the request line only, and a body
        never belongs there. The handler's result line is the record."""
        return

    def _respond(self, body: bytes) -> None:
        result = handle_delivery(
            self.command,
            self.path,
            {key: value for key, value in self.headers.items()},
            body,
            self.server.config,
            self.server.board,
            worker=getattr(self.server, "worker", None),
            classifier=getattr(self.server, "classifier", None),
            telemetry=getattr(self.server, "telemetry", None),
            admission_reader=getattr(self.server, "admission_reader", None),
            spend=getattr(self.server, "spend", None),
            installations=getattr(self.server, "installations", None),
        )
        self._send(result.status, result.body)
        route = self.path.split("?", 1)[0][:200]
        detail = f" {result.detail}" if result.detail else ""
        self.server.log(
            f"atlas-reviewer: http {result.status} {self.command} {route}{detail}"
        )

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def read_bounded(
    read: Callable[[int], bytes],
    length: int,
    deadline: float,
    now: Callable[[], float],
    *,
    arm: Callable[[float], None] | None = None,
) -> bytes | None:
    """Read ``length`` bytes, or None when ``now`` passes ``deadline``.

    ``read`` must return whatever is already available (``BufferedReader.read1``)
    rather than blocking until ``n`` bytes arrive. ``arm`` sets the socket
    timeout to the time still left, so a trickle cannot hold the handler
    by delivering one byte inside each long timeout.
    """
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        left = deadline - now()
        if left <= 0:
            return None
        if arm is not None:
            arm(left)
        try:
            block = read(min(remaining, 4096))
        except TimeoutError:
            return None
        if not block:
            break
        chunks.append(block)
        remaining -= len(block)
    if remaining:
        return None
    return b"".join(chunks)


def _monotonic() -> float:
    return time.monotonic()


class ReviewServer(ThreadingHTTPServer):
    worker: Worker | None = None
    classifier: PushClassifier | None = None
    telemetry: Telemetry | None = None
    admission_reader: AdmissionReader | None = None
    spend: DailySpend | None = None
    installations: InstallationStore | None = None

    def __init__(
        self,
        config: ServiceConfig,
        board: Board,
        log: Callable[[str], None],
    ) -> None:
        super().__init__((config.host, config.port), _Handler)
        self.config = config
        self.board = board
        self.log = log
        self.slots = threading.BoundedSemaphore(_MAX_HTTP_HANDLERS)
        # Covers the thread, including a client that never finishes its
        # headers. The body slots alone start after the headers arrive.
        self.connections = threading.BoundedSemaphore(_MAX_HTTP_HANDLERS)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 429 Too Many Requests\r\n"
                    b"Content-Length: 5\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                    b"busy\n"
                )
            except OSError:
                pass
            request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def config_from_env(env: Mapping[str, str]) -> ServiceConfig:
    secret = env.get(WEBHOOK_SECRET_ENV, "")
    repos = env.get("ATLAS_REVIEW_REPOS", DEFAULT_REPO)
    allowlist = frozenset(part.strip() for part in repos.split(",") if part.strip())
    concurrency = int(env.get("ATLAS_REVIEW_CONCURRENCY", "1"))
    provider = env.get("ATLAS_SERVICE_PROVIDER", "openrouter")
    live = env.get("ATLAS_ALLOW_LIVE_INFERENCE", "") == "1"
    # Local default is the loopback. The Fly app sets
    # ATLAS_SERVICE_HOST=0.0.0.0 because the proxy is not on loopback.
    host = env.get("ATLAS_SERVICE_HOST", "127.0.0.1")
    raw_port = env.get("ATLAS_SERVICE_PORT", "8080")
    if raw_port != "8080":
        raise ServiceError("ATLAS_SERVICE_PORT must be 8080, the port Fly checks")
    port = 8080
    state = Path(env.get("ATLAS_REVIEWER_STATE_DIR", ".atlas-reviewer-state"))
    try:
        mode = service_mode(env)
        deadline_s = service_deadline(env, mode=mode)
        policy = head_change_policy(env)
        fraction = cancel_fraction(env)
        budget = repo_daily_budget_usd(env)
        retention = retention_days(env)
        # Validated here so a mistyped per-tenant bound stops the service
        # at boot, not the first review that reads it in the child.
        operator_repo_ceiling_max(env)
        sources = load_funding_sources(env)
        if sources is not None:
            sources_cover(sources, configured_model(env, MODEL_ID))
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    return ServiceConfig(
        secret=secret,
        allowlist=allowlist,
        concurrency=concurrency,
        host=host,
        port=port,
        state_dir=state,
        provider=provider,
        allow_live_inference=live,
        mode=mode,
        deadline_s=deadline_s,
        head_change_policy=policy,
        cancel_fraction=fraction,
        repo_daily_budget_usd=budget,
        installation_retention_days=retention,
    )


def _funding_selector(env: Mapping[str, str]) -> FundingSelector | None:
    """The claim-time selector, or None when the operator set no list.

    ``key_probe`` is the live ``GET /key``. A test replaces it on this
    module; nothing here calls the network until a review is claimed."""
    sources = load_funding_sources(env)
    if sources is None:
        return None
    return FundingSelector(sources, env, key_probe, configured_model(env, MODEL_ID))


def _installation_has_credentials(
    source: Callable[[], TenantCredentials | None],
) -> Callable[[], bool]:
    """Whether this claim is a tenant run. A store error propagates, and
    the worker fails the review rather than selecting an operator source."""

    def active() -> bool:
        return source() is not None

    return active


def _service_secrets(config: ServiceConfig, env: Mapping[str, str]) -> tuple[str, ...]:
    """Values the service log must never write. The comment scrubber is
    separate and also covers the App key and minted tokens."""
    values = [config.secret]
    for name in (
        "ATLAS_SPRITES_TOKEN",
        "ATLAS_OPENROUTER_API_KEY",
        ENV_STORE_KEY,
    ):
        value = env.get(name, "")
        if value:
            values.append(value)
    for key in funding_key_values(env):
        if key not in values:
            values.append(key)
    return tuple(values)


def _retention_sweep(
    store: InstallationStore, config: ServiceConfig, log: Callable[[str], None]
) -> None:
    """The boot-time retention sweep (config slice S10, D81 §7 decision
    8): stored state unrefreshed past `ATLAS_INSTALLATION_RETENTION_DAYS`
    is deleted, catching an `installation.deleted` webhook the service
    never saw. The sweep runs at boot -- the deployed service restarts
    on every deploy -- and a record it cannot read is left where it is:
    its age cannot be established, and it is already unusable. A sweep
    that fails names the failure and leaves the service running; skipped
    directory entries -- a crash's leftover `<id>.json.writing` temp, a
    stray file -- are named with their count, not allowed to halt the
    sweep (r1 review of #776, Minor 2)."""
    try:
        removed, skipped = store.sweep(
            SystemClock().now(), config.installation_retention_days
        )
    except InstallationStoreError as exc:
        log(f"atlas-reviewer: the installation retention sweep failed: {exc}")
        return
    if removed or skipped:
        log(
            "atlas-reviewer: the installation retention sweep deleted "
            f"{removed} record(s) unrefreshed past the "
            f"{config.installation_retention_days}-day window "
            f"({ENV_RETENTION_DAYS})"
            + (f" and skipped {skipped} non-record file(s)" if skipped else "")
        )


def _tenant_credentials_source(
    store: InstallationStore, env: Mapping[str, str]
) -> Callable[[], TenantCredentials | None]:
    """The tenant-path resolver the runner calls at run time (config
    slice S10): the configured installation's stored credentials, or
    None for the operator path. The routing rule (D89): an allowlisted
    repo whose installation has no stored credentials is reviewed on
    the operator's key, as today; a repo whose installation has
    credentials is reviewed on them; neither path falls back to the
    other. A record with credentials but no consent acknowledgement
    refuses the review (D81 §7 decision 3), and a store that cannot be
    read raises -- the runner fails the review with the reason named,
    never a fallback to the operator key."""
    installation = env.get("ATLAS_GITHUB_INSTALLATION_ID", "")

    def source() -> TenantCredentials | None:
        if store.broken_reason:
            raise InstallationStoreError(store.broken_reason)
        if store.fernet is None:
            # The unconfigured store holds no credentials for anyone, so
            # every review is the operator path.
            return None
        if not installation:
            raise InstallationStoreError(
                "no App installation id is configured, so the "
                "installation's stored credentials cannot be resolved"
            )
        record = store.load(installation)
        if record is None or not record.has_credentials:
            return None
        if record.consent_acknowledged_at is None:
            raise ConsentNotAcknowledgedError(CONSENT_REQUIRED)
        return record.credentials()

    return source


def _state_is_writable(path: Path) -> bool:
    try:
        make_private_dirs(path)
        probe = path / ".writable"
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
    except OSError:
        return False
    return True


class _LoggingSink:
    """Writes each service event to the JSONL sink and to the operator log.
    The event is already scrubbed by the time it is emitted."""

    def __init__(self, inner: EventSink, log: Callable[[str], None]) -> None:
        self._inner = inner
        self._log = log

    def emit(self, event: Event) -> None:
        self._inner.emit(event)
        pr = event.fields.get("pr", "")
        sha = event.fields.get("sha12", "")
        attempts = event.fields.get("attempts", "")
        retry = event.fields.get("retry_s", "")
        reason = event.fields.get("reason", "")
        line = f"atlas-reviewer: {event.step} status={event.status} pr={pr} sha={sha}"
        if attempts != "":
            line += f" attempts={attempts}"
        if retry != "":
            line += f" retry_s={retry}"
        if reason != "":
            # A fixed reason label, never text from the payload or the
            # config; it is what tells a rule-based skip apart from the
            # service being down.
            line += f" reason={reason}"
        if event.error:
            line += f" error={event.error}"
        self._log(line)


def serve(
    config: ServiceConfig,
    env: Mapping[str, str],
    *,
    runner: Runner | None = None,
    publisher: PostPublisher | None = None,
    classifier: PushClassifier | None = None,
    classifier_reason: str = "",
    admission_reader: AdmissionReader | None = None,
    admission_reason: str = "",
    post_config_fetcher: PostConfigFetcher | None = None,
    post_config_reason: str = "",
    spend: DailySpend | None = None,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
    secret_sources: tuple[Callable[[], Sequence[str]], ...] = (),
    run_secrets: RunSecrets | None = None,
) -> int:
    install_interrupts()
    if not _state_is_writable(config.state_dir):
        log(f"atlas-reviewer: state dir {config.state_dir} is not writable")
        return 2
    # The installation store (config slice S10, part A): the encrypted
    # per-installation records the tenant path and the daily cap read.
    # An unconfigured store -- no key, no records -- changes nothing; a
    # broken one fails closed, and the boot log names it.
    store = InstallationStore.open(config.state_dir, env)
    if store.broken_reason:
        log(f"atlas-reviewer: the installation store is broken: {store.broken_reason}")
    if store.configured:
        _retention_sweep(store, config, log)
    if spend is None:
        # The per-tenant daily bounds (config slice S9/S10): production
        # wires the decided default budget and the store-backed cap
        # provider -- the installation admin's cap, when one is set, an
        # unset cap meaning none applies (D86). A store the provider
        # cannot read raises, and the refusal then fails closed with its
        # own named text (D89). A test passes its own to pin the refusal
        # and a cap double.
        spend = DailySpend(
            config.state_dir,
            config.repo_daily_budget_usd,
            cap_for=store.installation_cap(),
        )
    tenant_source = _tenant_credentials_source(store, env)
    if run_secrets is None:
        # The holder the runs register the tenant key into (config slice
        # S10): the parent's scrubber reads it on every scrub, because
        # the child's stderr tail lands in the telemetry and the
        # parent's redaction does not assume the child's own scrubbing
        # was complete (r1 review of #776, Major 1). main() passes the
        # holder the poster's redactor shares.
        run_secrets = RunSecrets()
    board = Board(config.state_dir / "queue.json")
    redactor = Redactor(
        known_secrets=_service_secrets(config, env),
        sources=(*secret_sources, run_secrets),
    )
    sink = JsonlSink(config.state_dir / "service.jsonl", max_bytes=_SERVICE_LOG_BYTES)
    sink.__enter__()
    try:
        telemetry = Telemetry(
            SystemClock(),
            scrub=lambda text: redactor(text).text,
            sink=_LoggingSink(sink, log),
        )
        if runner is None:
            deadline = (
                config.deadline_s
                if config.deadline_s is not None
                else service_deadline(env, mode=config.mode)
            )
            runner = make_runner(
                RunConfig(
                    config.provider,
                    config.allow_live_inference,
                    config.state_dir,
                    config.mode,
                ),
                env,
                deadline_s=deadline,
                tenant_source=tenant_source,
                tenant_secrets=run_secrets,
            )
        posting_publisher = _post_config_publisher(
            publisher, post_config_fetcher, telemetry
        )
        selector = _funding_selector(env)
        worker = Worker(
            board,
            runner,
            telemetry,
            posting_publisher,
            config.concurrency,
            config.state_dir,
            spend=spend,
            installation=env.get("ATLAS_GITHUB_INSTALLATION_ID", ""),
            funding=selector,
            tenant_active=_installation_has_credentials(tenant_source),
        )
        server = ReviewServer(config, board, log)
        server.worker = worker
        server.classifier = classifier
        server.telemetry = telemetry
        server.admission_reader = admission_reader
        server.spend = spend
        server.installations = store
        # A pending head stranded by a crash or a failed save (round-1
        # review of #747, F7) is queued here at boot, before any worker
        # runs, and the same recovery runs on the worker's idle passes.
        try:
            for event in board.recover_pending():
                _backfill_crashed_spend(spend, config.state_dir, event, telemetry)
                telemetry.record("service", "follow-up queued", _fields(event))
        except Exception as exc:  # noqa: BLE001 -- a failed boot recovery is the worker loop's problem
            log(f"atlas-reviewer: pending-head recovery failed: {exc}")
        if config.head_change_policy == POLICY_KEEP and classifier is None:
            # The lost cancel branch is a visible condition, not a silent
            # one (round-1 review of #747, F3): the boot log names it, and
            # every unclassifiable decision records the gap on its event.
            log(
                "atlas-reviewer: head-change policy is keep with NO"
                " classifier: every mid-review push will be kept and the"
                f" gap recorded ({classifier_reason or 'no reason given'})"
            )
        if admission_reader is None and admission_reason:
            # The repo's own narrowing cannot be read without the App
            # credentials; that is a gap named at boot, and every
            # delivery then runs on the operator's envelope alone.
            log(
                "atlas-reviewer: repo admission narrowing is off: the"
                f" default-branch {REVIEW_MD} will not be read ({admission_reason})"
            )
        if post_config_fetcher is None and post_config_reason:
            # The repo's own post settings -- the severity floor and the
            # verbosity dial (config slice S3, D84) -- cannot be read
            # without the App credentials; that is a gap named at boot,
            # and every post then runs on the default: everything
            # posted, the full body.
            log(
                "atlas-reviewer: the repo's post settings are off: the"
                f" default-branch {REVIEW_MD} will not be read"
                f" ({post_config_reason})"
            )
        worker.start()
        log(
            "atlas-reviewer: service listening"
            f" on {config.host}:{config.port};"
            f" concurrency {config.concurrency} (refuses above {MAX_CONCURRENCY});"
            f" repos {', '.join(sorted(config.allowlist))};"
            f" repo daily budget ${config.repo_daily_budget_usd}"
            f" head-change policy {config.head_change_policy}"
            f" (cancel fraction {config.cancel_fraction:.0%})"
            + (
                f"; pending follow-ups {len(board.pending_heads())}"
                if board.pending_heads()
                else ""
            )
        )
        try:
            server.serve_forever()
        finally:
            worker.stop()
            server.server_close()
    finally:
        sink.__exit__(None, None, None)
    return 0


_CLASSIFY_TIMEOUT_S = 5.0
_READ_BUDGET_S = 8.0
"""The handler's overall read budget, inside the webhook handler thread
(round-2 review of #747, R2-F8; round-1 review of #756, Minor 2): the
parent's GitHub reads on one delivery -- the repo admission read and,
when a review is running, the head-change classification's token mint
plus three reads at their own 5-second timeouts -- share it, so however
many reads run they cannot together hold the handler past GitHub's ~10
second response window. Past the budget a read has no result -- the
owner's keep default for the classification, the operator envelope for
the admission read -- with the gap and the `timed_out` flag on the
decision's event, and the handler answers. The read still finishes in
its background thread and is then simply not used."""


def _call_bounded(
    call: Callable[..., Any],
    *args: Any,
    budget_s: float,
    what: str = "read",
) -> tuple[Any, str, bool]:
    """One parent-side GitHub read under an overall deadline (round-2
    review of #747, R2-F8): the call runs in a helper thread and the
    caller waits at most ``budget_s``; past it the read has no result,
    with the gap set and the ``timed_out`` flag on, so the handler's
    occupancy is bounded and the over-run is visible. The helper thread
    outlives the wait only until its own per-read timeouts end it.
    ``what`` names the read in the gap, so the classification's gap
    text stays what it was before the helper was generalized (round-1
    review of #756, Nit 6).

    Returns ``(result, gap, timed_out)``. ``result`` is None on a gap or
    a timeout; a None with an empty gap is the call's own None -- the
    shared budget cannot tell those apart, so a caller whose None is a
    legitimate answer distinguishes them by the gap."""
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["result"] = call(*args)
        except Exception as exc:  # noqa: BLE001 -- the caller keeps the review on any failure
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(budget_s)
    if worker.is_alive():
        return (
            None,
            f"the {what} exceeded its {budget_s:.0f}-second budget",
            True,
        )
    error = outcome.get("error")
    if error is not None:
        return (
            None,
            f"{type(error).__name__}: {error}",
            isinstance(error, TransportTimeoutError),
        )
    return outcome.get("result"), "", False


def _read_client(
    config: ServiceConfig, env: Mapping[str, str]
) -> tuple[GitHubClient | None, str]:
    """The read-only GitHub client each of the parent's own GitHub
    readers builds for itself -- the head-change classifier and the repo
    admission reader -- from the App credentials, scoped to the
    allowlist's repositories with read permissions only, and the reason
    there is none.

    The reason is empty when the client is built. A deployment without
    usable credentials gets None plus the reason; each reader names its
    own gap on it, so the lost read stays visible, not silent."""
    from atlas_reviewer.github_api import GitHubClient
    from atlas_reviewer.github_auth import (
        READ_PERMISSIONS,
        AppInstallationTokens,
        normalize_pem_key,
    )
    from atlas_reviewer.http import UrllibTransport
    from atlas_reviewer.service_post import repository_names

    app_id = env.get("ATLAS_GITHUB_APP_ID", "")
    private_key = env.get(APP_KEY_ENV, "")
    installation = env.get("ATLAS_GITHUB_INSTALLATION_ID", "")
    if not app_id or not private_key or not installation.isdigit():
        return None, (
            "the App credentials (ATLAS_GITHUB_APP_ID, "
            "ATLAS_GITHUB_APP_PRIVATE_KEY, ATLAS_GITHUB_INSTALLATION_ID) are "
            "absent or malformed"
        )
    try:
        tokens = AppInstallationTokens(
            UrllibTransport(),
            SystemClock(),
            app_id=app_id,
            private_key=normalize_pem_key(private_key),
            installation_id=int(installation),
            permissions=READ_PERMISSIONS,
            repositories=repository_names(config.allowlist),
            timeout_s=_CLASSIFY_TIMEOUT_S,
        )
        client = GitHubClient(UrllibTransport(), tokens, timeout_s=_CLASSIFY_TIMEOUT_S)
    except (ValueError, BoundaryError) as exc:
        return None, f"the read-only GitHub client could not be built: {exc}"
    return client, ""


def _head_change_classifier(
    config: ServiceConfig, env: Mapping[str, str]
) -> tuple[PushClassifier | None, str]:
    """The live classifier behind the keep side of the decision, built
    from the same App credentials the poster mints from, scoped to the
    allowlist's repositories with read permissions only -- and the reason
    there is none, for the boot log and the decision events to name.

    The reason is empty when the classifier is built. A deployment
    without usable credentials gets None plus the reason: it keeps every
    mid-review push (the owner's default) rather than failing a webhook
    over a missing classification, and every such decision is recorded
    with the gap, so the lost cancel branch is visible, not silent
    (round-1 review of #747, F3). The short timeout bounds the three
    reads the classification takes; a delivery that outlives the
    webhook's own response window is marked failed in GitHub's UI and is
    NOT redelivered on its own (D53) -- the decision is nonetheless made
    and recorded before the response, so the delivery's loss costs the
    webhook acknowledgment, never the review's correctness."""
    client, reason = _read_client(config, env)
    if client is None:
        return None, reason
    return lambda running, new: classify_delivery(client, running, new), ""


def _repo_admission_reader(
    config: ServiceConfig, env: Mapping[str, str]
) -> tuple[AdmissionReader | None, str]:
    """The default-branch ``REVIEW.md`` reader behind the repo's own
    admission narrowing (config slice S4), a read-only App client built
    from the same credentials and the same read-only scope the
    head-change classifier's is, and the reason there is none.

    The config comes from the **default branch** (round-1 review of
    #756, Major 1): a same-repo PR's author controls the PR's base
    branch, and a config read from it would let the author opt their own
    PR out of review; the default branch changes only through reviewed
    merges. When the payload does not carry the default branch, one
    read-only lookup recovers it; a lookup that fails is a gap. A repo
    with no ``REVIEW.md`` on its default branch reads as None -- the
    ordinary unconfigured repo, the default stands. Any other read
    failure raises and the caller treats it as a gap: the operator's
    envelope stands, and the gap is on the telemetry. The file is read
    under the same 64 KiB bound the review's merge-base copy is, so an
    over-grown file is a gap, not a truncated parse."""
    client, reason = _read_client(config, env)
    if client is None:
        return None, reason

    def read(repo: str, default_branch: str) -> bytes | None:
        # Only the file read catches NotFoundError: no REVIEW.md on the
        # default branch is the ordinary unconfigured repo. The fallback
        # lookup's own 404 propagates -- a repository the delivery named
        # but the API cannot find is a gap the telemetry records, not a
        # silent stand-down (round-2 nit on #756).
        ref = default_branch or _default_branch_via_api(client, repo)
        try:
            return client.get_file(repo, ref, REVIEW_MD, MAX_ADMISSION_BYTES)
        except NotFoundError:
            return None

    return read, ""


def _default_branch_via_api(client: GitHubClient, repo: str) -> str:
    """The repository's default branch, recovered with one read-only
    lookup when the payload's shape did not carry it. A reply without a
    usable name is a boundary failure, and a lookup that 404s raises --
    both are the gap, not a guess and not the silent unconfigured case."""
    repository = client.get_repository(repo)
    branch = repository.get("default_branch") if isinstance(repository, dict) else None
    if not isinstance(branch, str) or not branch:
        raise BoundaryError(f"the repository {repo} has no default branch to read")
    return branch


def _post_config_fetcher(
    config: ServiceConfig, env: Mapping[str, str]
) -> tuple[PostConfigFetcher | None, str]:
    """The default-branch ``REVIEW.md`` reader behind the repo's own post
    settings (config slice S3, D84): the severity floor for posted
    findings and the post's verbosity dial, built from the same
    read-only App client the admission reader's is, and the reason there
    is none.

    The read source is the **default branch**, for the reason the
    admission read's is (round-1 review of #756, Major 1): the floor
    decides which findings reach the post and the dial decides which
    sections it carries, so a config read from a surface the PR's author
    controls -- the PR head, or the merge-base a same-repo or stacked PR
    can carry lines onto -- would let the PR quiet or suppress its own
    review; the default branch changes only through reviewed merges. At
    post time the webhook payload that named the default branch is long
    gone, so the fetch recovers the branch with one read-only lookup
    (`_default_branch_via_api`), then reads the file under the same
    64 KiB bound the admission read uses. A missing file is the ordinary
    unconfigured repo (``None``; the default stands, silently); any
    other failure raises, and the caller treats it as a gap with the
    default standing."""
    client, reason = _read_client(config, env)
    if client is None:
        return None, reason

    def read(repo: str) -> bytes | None:
        # Like the admission read: only the file read catches
        # NotFoundError -- no REVIEW.md on the default branch is the
        # ordinary unconfigured repo -- and the fallback lookup's own
        # 404 propagates as the gap, not a silent stand-down.
        ref = _default_branch_via_api(client, repo)
        try:
            return client.get_file(repo, ref, REVIEW_MD, MAX_ADMISSION_BYTES)
        except NotFoundError:
            return None

    return read, ""


def _post_config_source(
    fetcher: PostConfigFetcher, event: PrEvent, telemetry: Telemetry | None
) -> PostConfigSource:
    """One post's post-configuration source: called lazily, after the
    poster's own dedupe checks, so an already-posted head spends no
    read. The fetch runs bounded and fail-open -- a failure, a timeout
    or a file over the read bound leaves the default standing
    (`DEFAULT_POST_CONFIG`: post every finding, the full body -- the
    protective direction; a lost read can only make the post *more*
    complete, never less) -- and the gap is on the telemetry, the way
    the admission read's is. An unusable line's own fail-open note is
    recorded the same way; the post itself carries it."""

    def read() -> PostConfigRead:
        started = telemetry.elapsed() if telemetry is not None else 0.0
        raw, gap, timed_out = _call_bounded(
            fetcher, event.repo, budget_s=_READ_BUDGET_S, what="post config read"
        )
        if raw is None:
            if gap:
                _record(
                    telemetry,
                    "post config",
                    _fields(event),
                    start_s=started,
                    error=gap,
                    timed_out=timed_out,
                )
            return DEFAULT_POST_CONFIG
        config = parse_post_config(raw.decode("utf-8", errors="replace"))
        if config.notes:
            _record(
                telemetry,
                "post config",
                _fields(event),
                start_s=started,
                error="; ".join(config.notes),
            )
        return config

    return read


def _post_config_publisher(
    publisher: PostPublisher | None,
    fetcher: PostConfigFetcher | None,
    telemetry: Telemetry | None,
) -> Publisher | None:
    """The publisher wrapped to resolve the repo's post configuration for
    each post (config slice S3, D84) and hand it to the poster as a lazy
    source. A publisher or a fetcher that is None passes through
    unchanged: a deployment that posts nothing needs no config, and one
    without the App credentials posts the default -- the boot log names
    the lost read. The publisher this wraps must accept the optional
    post-config source (`PostPublisher`) -- the type system pins that at
    the ``serve`` call site, because the wrapper calls it with three
    arguments."""
    if publisher is None or fetcher is None:
        return publisher

    def posted(event: PrEvent, report: ReviewReport) -> bool | None:
        return publisher(event, report, _post_config_source(fetcher, event, telemetry))

    return posted


def _child_secrets(env: Mapping[str, str]) -> tuple[str, ...]:
    """Values the review child is allowed to hold. The service log has to
    scrub them, because the child's stderr is recorded here."""
    names = (
        "ATLAS_SPRITES_TOKEN",
        "ATLAS_OPENROUTER_API_KEY",
        "ATLAS_GITHUB_INSTALLATION_TOKEN",
    )
    held = [value for name in names if len(value := env.get(name, "")) >= 8]
    for key in funding_key_values(env):
        if key not in held:
            held.append(key)
    return tuple(held)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    del argv
    env = os.environ if env is None else env
    try:
        config = config_from_env(env)
        from atlas_reviewer.http import UrllibTransport
        from atlas_reviewer.service_post import publisher_from_env

        # The run-resolved tenant credentials (config slice S10): one
        # holder shared by the runner (which registers) and both
        # scrubbers (which read) -- the service log's and the poster's.
        run_secrets = RunSecrets()
        publisher = publisher_from_env(
            env,
            config.allowlist,
            config.state_dir,
            transport=UrllibTransport(),
            clock=SystemClock(),
            run_secrets=run_secrets,
        )
    except (ServiceError, ValueError, BoundaryError) as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2
    classifier, classifier_reason = _head_change_classifier(config, env)
    admission_reader, admission_reason = _repo_admission_reader(config, env)
    post_config_fetcher, post_config_reason = _post_config_fetcher(config, env)
    try:
        return serve(
            config,
            env,
            publisher=publisher.post,
            classifier=classifier,
            classifier_reason=classifier_reason,
            admission_reader=admission_reader,
            admission_reason=admission_reason,
            post_config_fetcher=post_config_fetcher,
            post_config_reason=post_config_reason,
            secret_sources=(
                lambda: _child_secrets(env),
                publisher.credential_secrets,
            ),
            run_secrets=run_secrets,
        )
    except KeyboardInterrupt:
        return 0
    except QueueError as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"atlas-reviewer: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    # `python -m` runs this file as __main__. Importing it again under
    # its package name would be a second module, with its own
    # before_send and exception classes. Run the package module's main
    # so the worker and the poster share one set of objects.
    from atlas_reviewer.service import main as run_service

    sys.exit(run_service())
