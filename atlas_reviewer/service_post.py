# SPDX-License-Identifier: MIT
"""Post one finished review as a GitHub pull-request review.

The request body is built in ``comment_payload``, which has no event
argument and always sends COMMENT. ``comment_only`` refuses APPROVE and
REQUEST_CHANGES for any caller that tries to name one. A failed review
never reaches this module.

The idempotency key is ``repo#pr#sha``. It is stored after GitHub accepts
the review, and it is also the HTML marker at the end of the body. A retry
lists reviews first and does not post again when that marker is already
there, including when the process died after GitHub accepted the review
and before the local record was written.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

from atlas_reviewer.domain import PrEvent
from atlas_reviewer.github_auth import (
    POST_PERMISSIONS,
    POST_WRITABLE,
    AppInstallationTokens,
)
from atlas_reviewer.http import HttpResponse, Transport
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.notes import quote_untrusted
from atlas_reviewer.pagination import DEFAULT_MAX_PAGES, next_link
from atlas_reviewer.ports import BoundaryError, Clock, TokenSource
from atlas_reviewer.redact import Redactor
from atlas_reviewer.service import (
    PostAuthError,
    PostNotCurrent,
    PostRejected,
    RateLimited,
    before_send,
)
from atlas_reviewer.service_run import ReviewReport

API_URL = "https://api.github.com"
MAX_COMMENT_CHARS = 65_000
_MARKER = "<!-- atlas-service-post: "
_BANNER = (
    "> **Advisory only.** This is one GitHub review posted with event COMMENT. "
    "It is not an approval and it is not a request for changes. "
    "It is not a substitute for the full Claude Code protocol review: "
    "full repository access, the full pull request diff, and per-lens "
    "subagent fan-out."
)
_FILES = (
    "The controller's coverage note is the record of files a model call "
    "covered. A path named after it is a file the draft says was not "
    "reviewed in full."
)
_EVENTS = frozenset({"APPROVE", "COMMENT", "REQUEST_CHANGES"})
# One list-plus-create attempt. Ten pages at the 30-second socket timeout
# would hold the worker for minutes; this deadline cuts that short.
_ATTEMPT_DEADLINE_S = 45.0
# A rate-limit header longer than this is capped so one response cannot
# stall the machine for hours.
_MAX_RETRY_AFTER_S = 900.0
# GitHub's secondary rate limit guidance is at least a minute when the
# response does not name a shorter wait.
_SECONDARY_FLOOR_S = 60.0


class RefusedReviewEvent(Exception):
    """A review event other than COMMENT. Nothing is sent."""

    def __init__(self, event: str) -> None:
        super().__init__(f"refusing review event {event}")
        self.event = event


def comment_only(event: str) -> str:
    if event != "COMMENT":
        raise RefusedReviewEvent(event)
    return "COMMENT"


def comment_payload(commit_id: str, body: str) -> dict[str, str]:
    """The only review-create body this service sends."""
    return {"commit_id": commit_id, "body": body, "event": comment_only("COMMENT")}


def post_key(event: PrEvent) -> str:
    return f"{event.repo}#{event.pr_number}#{event.head_sha}"


def marker_for(key: str) -> str:
    return f"{_MARKER}{key} -->"


def render_comment(report: ReviewReport, key: str, scrub: Callable[[str], str]) -> str:
    recommended = report.recommended_event
    if recommended not in _EVENTS:
        recommended = "unreported"
    files = (
        report.files_note,
        *(f"not reviewed in full: {path}" for path in report.files_not_read),
    )
    body = "\n\n".join(
        (
            _BANNER,
            f"The draft recommended `{recommended}`. That event was not sent. This review is COMMENT.",
            _section("Lenses run", report.lenses_run, scrub),
            _section("Lenses not run", report.lenses_not_run, scrub),
            _FILES + "\n\n" + _section("Files read", files, scrub),
            _section("Limit stops", report.limit_stops, scrub),
            _section("Cost", report.cost_lines, scrub),
        )
    )
    mark = marker_for(key)
    ending = f"\n\n[comment cut to fit the post limit]\n\n{mark}"
    if len(body) + 2 + len(mark) <= MAX_COMMENT_CHARS:
        return f"{body}\n\n{mark}"
    keep = MAX_COMMENT_CHARS - len(ending)
    return body[: max(keep, 0)] + ending


def _section(title: str, items: tuple[str, ...], scrub: Callable[[str], str]) -> str:
    if not items:
        listed = "None."
    else:
        listed = "\n".join(f"- {quote_untrusted(item, scrub=scrub)}" for item in items)
    return f"## {title}\n\n{listed}"


class PostLedger:
    """Review ids already accepted by GitHub, keyed by ``post_key``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._ids: dict[str, int] = {}
        if path.exists():
            self._ids = _load(path)

    def seen(self, key: str) -> int | None:
        with self._lock:
            return self._ids.get(key)

    def record(self, key: str, review_id: int) -> None:
        with self._lock:
            self._ids[key] = review_id
            make_private_dirs(self._path.parent)
            tmp = self._path.with_name(self._path.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._ids, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)


def _load(path: Path) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BoundaryError(f"cannot read the post ledger {path}") from exc
    if not isinstance(raw, dict):
        raise BoundaryError(f"post ledger {path} is not an object")
    ids: dict[str, int] = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise BoundaryError(f"post ledger {path} holds an unusable record")
        ids[key] = value
    return ids


class ReviewPoster:
    def __init__(
        self,
        transport: Transport,
        tokens: TokenSource,
        ledger: PostLedger,
        scrub: Callable[[str], str],
        *,
        api_url: str = API_URL,
        timeout_s: float = 30.0,
        max_pages: int = DEFAULT_MAX_PAGES,
        now: Callable[[], float] | None = None,
        secrets: Callable[[], tuple[str, ...]] | None = None,
        bot_login: str = "",
    ) -> None:
        self._transport = transport
        self._tokens = tokens
        self._ledger = ledger
        self._scrub = scrub
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_pages = max_pages
        self._now = now or time.monotonic
        self._secrets = secrets or (lambda: ())
        self._bot_login = bot_login
        # One poster is shared by every worker. The attempt deadline is
        # per thread so one worker finishing cannot clear another's.
        self._attempt = threading.local()

    def credential_secrets(self) -> tuple[str, ...]:
        """The App key and every token this poster has minted, for the
        service log scrubber."""
        return self._secrets()

    def post(self, event: PrEvent, report: ReviewReport) -> None:
        key = post_key(event)
        if self._ledger.seen(key) is not None:
            return
        self._attempt.deadline = self._now() + _ATTEMPT_DEADLINE_S
        try:
            existing = self._find(event, marker_for(key))
            if existing is not None:
                self._ledger.record(key, existing)
                return
            # After the list, under the queue lock, and before the create.
            # A review GitHub has already accepted cannot be recalled.
            check = before_send.get()
            if check is not None and not check():
                raise PostNotCurrent("the head moved before the review was sent")
            body = render_comment(report, key, self._scrub)
            review_id = self._create(event, comment_payload(event.head_sha, body))
            self._ledger.record(key, review_id)
        finally:
            self._attempt.deadline = None

    def _create(self, event: PrEvent, payload: Mapping[str, str]) -> int:
        if payload.get("event") != "COMMENT":
            raise RefusedReviewEvent(str(payload.get("event")))
        response = self._request("POST", self._url(event), json.dumps(payload).encode())
        _raise_for_status(response, "GitHub review post")
        try:
            data = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BoundaryError("GitHub review post returned non-JSON") from exc
        review_id = data.get("id") if isinstance(data, dict) else None
        if isinstance(review_id, bool) or not isinstance(review_id, int):
            raise BoundaryError("GitHub review post returned no review id")
        return review_id

    def _find(self, event: PrEvent, marker: str) -> int | None:
        url: str | None = self._url(event)
        pages = 0
        while url is not None and pages < self._max_pages:
            response = self._request("GET", url, None)
            _raise_for_status(response, "GitHub review list")
            try:
                data = json.loads(response.body)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise BoundaryError("GitHub review list returned non-JSON") from exc
            if not isinstance(data, list):
                raise BoundaryError("GitHub review list returned a non-array")
            for item in data:
                found = _marked(item, marker, event.head_sha, self._bot_login)
                if found is not None:
                    return found
            pages += 1
            url = next_link(response.header("Link"))
            if url is not None and not url.startswith(f"{self._api_url}/"):
                raise BoundaryError("refusing a review-list link off the API")
        if url is not None:
            raise BoundaryError(
                "review list was cut off before the idempotency check finished"
            )
        return None

    def _url(self, event: PrEvent) -> str:
        owner, name = event.repo.split("/", 1)
        owner_q, name_q = quote(owner, safe=""), quote(name, safe="")
        return (
            f"{self._api_url}/repos/{owner_q}/{name_q}/pulls/{event.pr_number}/reviews"
        )

    def _remaining(self) -> float | None:
        deadline = getattr(self._attempt, "deadline", None)
        if deadline is None:
            return None
        return deadline - self._now()

    def _request(self, method: str, url: str, body: bytes | None) -> HttpResponse:
        remaining = self._remaining()
        if remaining is not None and remaining <= 0:
            raise BoundaryError("post attempt deadline")
        timeout = (
            self._timeout_s if remaining is None else min(self._timeout_s, remaining)
        )
        limit = getattr(self._tokens, "limit_timeout", None)
        if limit is not None and remaining is not None:
            limit(remaining)
        try:
            token = self._tokens.token()
        except BoundaryError as exc:
            text = str(exc)
            if "HTTP 401" in text or "HTTP 403" in text:
                raise PostAuthError(text) from None
            raise
        remaining = self._remaining()
        if remaining is not None and remaining <= 0:
            raise BoundaryError("post attempt deadline")
        if remaining is not None:
            timeout = min(self._timeout_s, remaining)
        return self._transport.request(
            method,
            url,
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "code-quality-atlas-reviewer",
                "Content-Type": "application/json",
            },
            body,
            timeout,
        )


def _raise_for_status(response: HttpResponse, what: str) -> None:
    if 200 <= response.status < 300:
        return
    if response.status == 422:
        raise PostRejected(f"{what} HTTP 422")
    wait = _retry_wait(response)
    if _secondary_limit(response):
        wait = min(max(wait or 0.0, _SECONDARY_FLOOR_S), _MAX_RETRY_AFTER_S)
        raise RateLimited(f"{what} HTTP {response.status}", wait)
    if response.status == 429 or (response.status == 403 and wait is not None):
        raise RateLimited(f"{what} HTTP {response.status}", wait or 0.0)
    if response.status in {401, 403}:
        raise PostAuthError(f"{what} HTTP {response.status}")
    raise BoundaryError(f"{what} HTTP {response.status}")


def _retry_wait(response: HttpResponse) -> float | None:
    """Seconds until GitHub asked us to try again, or None when the
    response is not a rate limit. A wait longer than the cap is cut."""
    header = response.header("Retry-After")
    if header is not None:
        try:
            return min(max(0.0, float(header)), _MAX_RETRY_AFTER_S)
        except ValueError:
            try:
                moment = parsedate_to_datetime(header)
            except (TypeError, ValueError, OverflowError):
                moment = None
            if moment is not None:
                return min(
                    max(0.0, moment.timestamp() - time.time()), _MAX_RETRY_AFTER_S
                )
    remaining = response.header("x-ratelimit-remaining")
    reset = response.header("x-ratelimit-reset")
    # GitHub sends the reset header on ordinary responses. It is a rate
    # limit only when the remaining budget is zero.
    if remaining == "0" and reset is not None:
        try:
            return min(max(0.0, float(reset) - time.time()), _MAX_RETRY_AFTER_S)
        except ValueError:
            return None
    if response.status == 429:
        return 0.0
    return None


def _secondary_limit(response: HttpResponse) -> bool:
    try:
        text = response.body.decode("utf-8", errors="replace").lower()
    except (UnicodeError, AttributeError):
        return False
    return "secondary rate limit" in text


def _marked(item: object, marker: str, sha: str, bot_login: str) -> int | None:
    """A review already posted for this commit by this App. A review a
    person wrote, one from another App, or one attached to another commit,
    does not count, so planting the marker cannot suppress this post."""
    if not bot_login or not isinstance(item, dict) or item.get("commit_id") != sha:
        return None
    user = item.get("user")
    if not isinstance(user, dict) or user.get("type") != "Bot":
        return None
    if user.get("login") != bot_login:
        return None
    body, review_id = item.get("body"), item.get("id")
    if not isinstance(body, str) or marker not in body:
        return None
    if isinstance(review_id, bool) or not isinstance(review_id, int):
        return None
    return review_id


def publisher_from_env(
    env: Mapping[str, str],
    allowlist: frozenset[str],
    state_dir: Path,
    *,
    transport: Transport,
    clock: Clock,
) -> ReviewPoster:
    """The poster for one installation. The private key and the minted
    token stay in this process and are not given to the review child. The
    scrubber removes both from the comment."""
    app_id = _env(env, "ATLAS_GITHUB_APP_ID")
    private_key = _pem(_env(env, "ATLAS_GITHUB_APP_PRIVATE_KEY"))
    installation = _env(env, "ATLAS_GITHUB_INSTALLATION_ID")
    if (
        not installation.isascii()
        or not installation.isdigit()
        or int(installation) < 1
    ):
        raise ValueError("ATLAS_GITHUB_INSTALLATION_ID must be a positive integer")
    slug = _env(env, "ATLAS_GITHUB_APP_SLUG")
    if not slug.isascii() or not slug.replace("-", "").isalnum():
        raise ValueError("ATLAS_GITHUB_APP_SLUG must be an App slug")
    secret = env.get("ATLAS_GITHUB_WEBHOOK_SECRET", "")
    known = [secret, private_key]
    for name in ("ATLAS_SPRITES_TOKEN", "ATLAS_OPENROUTER_API_KEY"):
        value = env.get(name, "")
        if value:
            known.append(value)
    tokens = AppInstallationTokens(
        transport,
        clock,
        app_id=app_id,
        private_key=private_key,
        installation_id=int(installation),
        permissions=POST_PERMISSIONS,
        writable=POST_WRITABLE,
        repositories=tuple(sorted(repo.split("/", 1)[1] for repo in allowlist)),
    )
    redactor = Redactor(known_secrets=tuple(known), sources=(tokens.secrets,))
    return ReviewPoster(
        transport,
        tokens,
        PostLedger(state_dir / "posted.json"),
        lambda text: redactor(text).text,
        secrets=tokens.secrets,
        bot_login=f"{slug}[bot]",
    )


def _env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise ValueError(f"posting a review needs the {name} environment variable")
    return value


def _pem(raw: str) -> str:
    return raw.replace("\\n", "\n") if "\n" not in raw else raw
