# SPDX-License-Identifier: MIT
"""COMMENT-only posting: a failure publishes nothing, and a retry does not
post a second review."""

import contextvars
import inspect
import json
import threading
import time
from pathlib import Path

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.github_auth import (
    POST_PERMISSIONS,
    POST_WRITABLE,
    AppInstallationTokens,
)
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.service import (
    PostAuthError,
    PostNotCurrent,
    PostRejected,
    RateLimited,
    ReviewServer,
    Worker,
    before_send,
    config_from_env,
    main,
    serve,
)
from atlas_reviewer.service_post import (
    PostLedger,
    RefusedReviewEvent,
    ReviewPoster,
    _repository_names,
    comment_only,
    comment_payload,
    marker_for,
    post_key,
    render_comment,
)
from atlas_reviewer.service_queue import Board, JobState
from atlas_reviewer.service_run import ReviewReport, ReviewRun, run_dir, summarize_draft
from atlas_reviewer.telemetry import Telemetry

SECRET = "webhook-secret-value"
SHA = "d" * 40
REPO = "brandondees/code-quality-atlas"
EVENT = PrEvent(REPO, 7, SHA)
REPORT = ReviewReport(
    lenses_run=("tracing-correctness-and-invariants",),
    lenses_not_run=("reviewing-concurrency-and-async: over the character budget",),
    files_note="Diff coverage after the model calls: PARTIAL. 1 of 2 file(s) in full.",
    files_not_read=("src/a.py",),
    limit_stops=("pull request diff | too large for one review pass | kept 1",),
    cost_lines=("reserved $1.00 actual $0.10",),
    recommended_event="APPROVE",
)


class GitHub:
    def __init__(self, *, post_status: int = 200) -> None:
        self.post_status = post_status
        self.calls: list[tuple[str, str, bytes | None]] = []
        self.reviews: list[dict[str, object]] = []

    def request(self, method, url, headers, body, timeout_s, max_bytes=None):
        self.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, json.dumps(self.reviews).encode())
        payload = json.loads(body)
        if self.post_status != 200:
            return HttpResponse(self.post_status, {}, b"")
        self.reviews.append(
            {
                "id": 9,
                "body": payload["body"],
                "commit_id": payload["commit_id"],
                "user": {"login": "code-quality-atlas[bot]", "type": "Bot"},
            }
        )
        return HttpResponse(200, {}, b'{"id": 9}')


class Tokens:
    def token(self) -> str:
        return "ghs_test"


@pytest.fixture(autouse=True)
def _pre_create_hook_is_set():
    """Direct poster calls are not the worker. The worker installs the
    real check; these tests allow the create unless they clear the hook."""
    token = before_send.set(lambda: True)
    yield
    before_send.reset(token)


def _poster(
    tmp_path: Path, github: GitHub | None = None
) -> tuple[ReviewPoster, GitHub]:
    github = github or GitHub()
    poster = ReviewPoster(
        github,
        Tokens(),
        PostLedger(tmp_path / "posted.json"),
        lambda text: text,
        bot_login="code-quality-atlas[bot]",
    )
    return poster, github


def _posted_body(github: GitHub) -> dict[str, str]:
    posts = [call for call in github.calls if call[0] == "POST"]
    assert len(posts) == 1
    payload = json.loads(posts[0][2] or b"")
    assert isinstance(payload, dict)
    return payload


def test_a_stop_during_the_listing_does_not_post(tmp_path):
    """A real poster, with only GitHub's HTTP faked.

    ``stop`` sets the job's cancel during the review list. ``begin_post``
    then refuses, so no create POST is sent and the draft stays. Removing
    the cancel check from ``begin_post`` lets the create through.
    """
    board = Board(tmp_path / "queue.json")
    directory = run_dir(tmp_path, EVENT)
    github = GitHub()
    original = github.request

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        if method == "GET":
            board.cancel_active()
        return original(method, url, headers, body, timeout_s, max_bytes)

    github.request = request
    poster, _ = _poster(tmp_path, github)

    def runner(_event, _cancel):
        directory.mkdir(parents=True)
        (directory / "draft.md").write_text("the review\n", encoding="utf-8")
        return ReviewRun(True, REPORT)

    worker = Worker(
        board, runner, Telemetry(SystemClock()), poster.post, state_root=tmp_path
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert [call for call in github.calls if call[0] == "POST"] == []
    assert (directory / "draft.md").is_file()
    assert board.states() == ((SHA, JobState.POST_PENDING),)


def test_a_missing_pre_create_hook_does_not_post(tmp_path):
    board = Board(tmp_path / "queue.json")
    github = GitHub()
    poster, _ = _poster(tmp_path, github)

    def publish(event, report):
        before_send.set(None)
        poster.post(event, report)

    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        publish,
        state_root=tmp_path,
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert [call for call in github.calls if call[0] == "POST"] == []
    assert board.states() == ((SHA, JobState.FAILED),)
    assert any(
        "pre-create check" in (record.error or "")
        for record in worker._telemetry.events
    )


def test_approve_and_request_changes_cannot_be_sent(tmp_path):
    poster, github = _poster(tmp_path)
    assert "event" not in inspect.signature(comment_payload).parameters
    for event in ("APPROVE", "REQUEST_CHANGES"):
        with pytest.raises(RefusedReviewEvent):
            comment_only(event)
        with pytest.raises(RefusedReviewEvent):
            poster._create(EVENT, {"commit_id": SHA, "body": "x", "event": event})
    assert github.calls == []
    payload = comment_payload(SHA, "hello")
    assert payload["event"] == "COMMENT"
    assert set(payload) == {"commit_id", "body", "event"}


def test_a_finished_review_is_one_comment_with_the_banner_and_the_lists(tmp_path):
    poster, github = _poster(tmp_path)
    poster.post(EVENT, REPORT)
    assert "per_page=100" in github.calls[0][1]
    payload = _posted_body(github)
    assert payload["event"] == "COMMENT"
    assert payload["commit_id"] == SHA
    body = payload["body"]
    assert "Advisory only" in body
    assert "not a substitute for the full Claude Code protocol review" in body
    assert "The draft recommended `APPROVE`" in body
    assert "That event was not sent" in body
    for text in (
        "tracing-correctness-and-invariants",
        "reviewing-concurrency-and-async",
        "PARTIAL",
        "src/a.py",
        "too large for one review pass",
        "actual $0.10",
        "## Lenses run",
        "## Lenses not run",
        "## Files read",
        "## Limit stops",
        "## Cost",
    ):
        assert text in body, text
    assert marker_for(post_key(EVENT)) in body
    poster.post(EVENT, REPORT)
    assert [call[0] for call in github.calls].count("POST") == 1


def test_a_retry_finds_the_marker_when_the_local_record_was_lost(tmp_path):
    github = GitHub()
    first, _ = _poster(tmp_path, github)
    first.post(EVENT, REPORT)
    second = ReviewPoster(
        github,
        Tokens(),
        PostLedger(tmp_path / "fresh.json"),
        lambda text: text,
        bot_login="code-quality-atlas[bot]",
    )
    before = len(github.calls)
    second.post(EVENT, REPORT)
    assert [call[0] for call in github.calls[before:]] == ["GET"]
    assert second._ledger.seen(post_key(EVENT)) == 9


def test_a_failed_post_records_nothing(tmp_path):
    poster, github = _poster(tmp_path, GitHub(post_status=500))
    with pytest.raises(BoundaryError, match="HTTP 500"):
        poster.post(EVENT, REPORT)
    assert poster._ledger.seen(post_key(EVENT)) is None
    assert github.reviews == []


def test_a_failed_review_posts_nothing(tmp_path):
    board = Board(tmp_path / "queue.json")
    poster, github = _poster(tmp_path)

    def runner(event, cancel):
        raise RuntimeError("runner blew up")

    worker = Worker(
        board,
        runner,
        Telemetry(SystemClock()),
        poster.post,
        state_root=tmp_path,
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert github.calls == []
    assert board.states() == ((SHA, JobState.FAILED),)


def test_a_post_failure_stays_unposted_until_a_later_try(tmp_path):
    board = Board(tmp_path / "queue.json")
    github = GitHub(post_status=500)
    poster, _ = _poster(tmp_path, github)
    clock = {"t": 1_000.0}
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        poster.post,
        state_root=tmp_path,
        now=lambda: clock["t"],
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert board.states() == ((SHA, JobState.POST_PENDING),)
    assert poster._ledger.seen(post_key(EVENT)) is None
    github.post_status = 200
    directory = run_dir(tmp_path, EVENT)
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text(
        "<!-- atlas-review-status: "
        '{"review_event": "COMMENT", "proposed_event": "COMMENT",'
        ' "coverage_complete": true, "changed_files": 1, "unreviewed_files": 0} -->\n'
        "\n## Model usage\n\n- actual $0.10\n",
        encoding="utf-8",
    )
    clock["t"] += 10_000
    worker._retry_post()
    assert board.states() == ((SHA, JobState.DONE),)
    posts = [call for call in github.calls if call[0] == "POST"]
    assert json.loads(posts[-1][2] or b"")["event"] == "COMMENT"


def test_a_human_review_with_the_marker_does_not_suppress_the_post(tmp_path):
    github = GitHub()
    github.reviews.append(
        {
            "id": 3,
            "body": marker_for(post_key(EVENT)),
            "commit_id": SHA,
            "user": {"login": "brandondees", "type": "User"},
        }
    )
    poster, _ = _poster(tmp_path, github)
    poster.post(EVENT, REPORT)
    assert [call[0] for call in github.calls].count("POST") == 1
    other = GitHub()
    other.reviews.append(
        {
            "id": 4,
            "body": marker_for(post_key(EVENT)),
            "commit_id": "e" * 40,
            "user": {"login": "code-quality-atlas[bot]", "type": "Bot"},
        }
    )
    again, _ = _poster(tmp_path / "other", other)
    again.post(EVENT, REPORT)
    assert [call[0] for call in other.calls].count("POST") == 1


def test_a_huge_comment_keeps_the_idempotency_marker():
    report = ReviewReport(
        tuple(f"item-{i:04d}" for i in range(6000)), (), "note", (), (), (), "COMMENT"
    )
    key = post_key(EVENT)
    text = render_comment(report, key, lambda item: item)
    assert text.endswith(marker_for(key))
    assert "comment cut to fit the post limit" in text
    assert len(text) <= 65_000


def test_a_secret_and_markup_in_the_report_do_not_reach_the_comment(tmp_path):
    secret = "super-secret-value"
    report = ReviewReport(
        (f"see {secret} <!-- hide -->",),
        (),
        "note",
        (),
        (),
        (),
        "COMMENT",
    )
    poster, github = _poster(tmp_path)
    poster._scrub = lambda text: text.replace(secret, "[REDACTED]")
    poster.post(EVENT, report)
    body = _posted_body(github)["body"]
    assert secret not in body
    assert "<!-- hide" not in body
    assert r"\u003c!-- hide" in body
    assert "[REDACTED]" in body


def test_an_off_api_link_is_refused_and_not_followed(tmp_path):
    class OffApi(GitHub):
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            self.calls.append((method, url, body))
            return HttpResponse(
                200,
                {"Link": '<https://evil.example/reviews>; rel="next"'},
                b"[]",
            )

    poster, github = _poster(tmp_path, OffApi())
    with pytest.raises(BoundaryError, match="off the API"):
        poster.post(EVENT, REPORT)
    assert [call[0] for call in github.calls] == ["GET"]


def test_a_rate_limit_is_not_retried_as_a_server_error(tmp_path):
    github = GitHub(post_status=429)
    github_headers = {"Retry-After": "12", "x-ratelimit-reset": "1"}

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(429, github_headers, b"")

    github.request = request
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(RateLimited) as caught:
        poster.post(EVENT, REPORT)
    assert caught.value.retry_after == 12


def test_a_403_with_a_reset_header_and_budget_left_is_auth(tmp_path):
    github = GitHub()
    reset = str(int(time.time()) + 30)

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(
            403, {"x-ratelimit-reset": reset, "x-ratelimit-remaining": "12"}, b""
        )

    github.request = request
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(PostAuthError):
        poster.post(EVENT, REPORT)


def test_a_403_with_no_budget_left_waits_for_the_reset(tmp_path):
    github = GitHub()
    reset = str(int(time.time()) + 30)

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(
            403, {"x-ratelimit-reset": reset, "x-ratelimit-remaining": "0"}, b""
        )

    github.request = request
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(RateLimited) as caught:
        poster.post(EVENT, REPORT)
    assert 0 < caught.value.retry_after <= 30


def test_a_retry_after_above_15_minutes_is_capped_and_a_bare_403_is_auth(tmp_path):
    github = GitHub()

    def limited(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(429, {"Retry-After": "100000"}, b"")

    github.request = limited
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(RateLimited) as caught:
        poster.post(EVENT, REPORT)
    assert caught.value.retry_after == 900

    def bare(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(403, {}, b"")

    github.request = bare
    poster, _ = _poster(tmp_path / "bare", github)
    with pytest.raises(PostAuthError):
        poster.post(EVENT, REPORT)


def test_a_secondary_limit_with_no_headers_waits_a_minute(tmp_path):
    github = GitHub()

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(403, {}, b"You have exceeded a secondary rate limit")

    github.request = request
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(RateLimited) as caught:
        poster.post(EVENT, REPORT)
    assert caught.value.retry_after == 60


def test_a_422_is_not_retried(tmp_path):
    github = GitHub()

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(422, {}, b"")

    github.request = request
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(PostRejected):
        poster.post(EVENT, REPORT)


def test_a_refused_token_mint_is_an_auth_failure(tmp_path):
    class Refused:
        def token(self) -> str:
            raise BoundaryError(
                "GitHub App token mint: HTTP 401 for https://api.github.com/x"
            )

    github = GitHub()
    poster = ReviewPoster(
        github, Refused(), PostLedger(tmp_path / "posted.json"), lambda text: text
    )
    with pytest.raises(PostAuthError):
        poster.post(EVENT, REPORT)
    assert github.calls == []


def test_an_auth_refusal_is_not_a_retryable_post_error(tmp_path):
    github = GitHub(post_status=401)

    def request(method, url, headers, body, timeout_s, max_bytes=None):
        github.calls.append((method, url, body))
        if method == "GET":
            return HttpResponse(200, {}, b"[]")
        return HttpResponse(401, {}, b"")

    github.request = request
    poster, _ = _poster(tmp_path, github)
    with pytest.raises(PostAuthError):
        poster.post(EVENT, REPORT)
    assert [call[0] for call in github.calls] == ["GET", "POST"]


def test_a_moved_head_is_not_created(tmp_path):
    poster, github = _poster(tmp_path)
    token = before_send.set(lambda: False)
    try:
        with pytest.raises(PostNotCurrent):
            poster.post(EVENT, REPORT)
    finally:
        before_send.reset(token)
    assert [call[0] for call in github.calls] == ["GET"]


def test_a_post_attempt_stops_at_its_deadline(tmp_path):
    ticks = {"n": 0}

    def now() -> float:
        ticks["n"] += 1
        return 0.0 if ticks["n"] == 1 else 100.0

    github = GitHub()
    poster = ReviewPoster(
        github,
        Tokens(),
        PostLedger(tmp_path / "posted.json"),
        lambda text: text,
        now=now,
    )
    with pytest.raises(BoundaryError, match="deadline"):
        poster.post(EVENT, REPORT)
    assert github.calls == []


def test_another_apps_bot_does_not_suppress_the_post(tmp_path):
    github = GitHub()
    github.reviews.append(
        {
            "id": 4,
            "body": marker_for(post_key(EVENT)),
            "commit_id": SHA,
            "user": {"login": "evil-app[bot]", "type": "Bot"},
        }
    )
    poster, _ = _poster(tmp_path, github)
    poster.post(EVENT, REPORT)
    assert [call[0] for call in github.calls].count("POST") == 1


def test_sprites_and_openrouter_secrets_do_not_reach_the_comment(tmp_path):
    sprite = "org/1/sprites-secret-value"
    model = "sk-or-v1-secret-value"
    report = ReviewReport(
        (f"see {sprite} and {model}",), (), "note", (), (), (), "COMMENT"
    )
    poster, github = _poster(tmp_path)
    poster._scrub = lambda text: text.replace(sprite, "[REDACTED]").replace(
        model, "[REDACTED]"
    )
    poster.post(EVENT, report)
    body = _posted_body(github)["body"]
    assert sprite not in body
    assert model not in body


def test_a_minted_token_in_the_report_does_not_reach_the_comment(tmp_path, monkeypatch):
    minted = "ghs_minted_value"

    class Minted:
        def __init__(self, *args, **kwargs):
            self._values: list[str] = []

        def token(self) -> str:
            self._values.append(minted)
            return minted

        def secrets(self) -> tuple[str, ...]:
            return tuple(self._values)

        def limit_timeout(self, seconds: float) -> None:
            return None

    monkeypatch.setattr("atlas_reviewer.service_post.AppInstallationTokens", Minted)
    from atlas_reviewer.clock import SystemClock
    from atlas_reviewer.service_post import publisher_from_env

    github = GitHub()
    poster = publisher_from_env(
        {
            "ATLAS_GITHUB_APP_ID": "5648875",
            "ATLAS_GITHUB_APP_PRIVATE_KEY": "pem-secret-value",
            "ATLAS_GITHUB_INSTALLATION_ID": "1",
            "ATLAS_GITHUB_APP_SLUG": "code-quality-atlas",
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
            "ATLAS_SPRITES_TOKEN": "org/1/sprites-secret-value",
            "ATLAS_OPENROUTER_API_KEY": "sk-or-v1-secret-value",
        },
        frozenset({REPO}),
        tmp_path,
        transport=github,
        clock=SystemClock(),
    )
    report = ReviewReport(
        (f"leaked {minted} org/1/sprites-secret-value sk-or-v1-secret-value",),
        (),
        "note",
        (),
        (),
        (),
        "COMMENT",
    )
    poster.post(EVENT, report)
    body = _posted_body(github)["body"]
    assert minted not in body
    assert "sprites-secret-value" not in body
    assert "sk-or-v1-secret-value" not in body


def test_the_deadline_includes_the_token_mint(tmp_path):
    clock = {"t": 0.0}
    seen: list[float] = []

    class Mint:
        def token(self) -> str:
            clock["t"] = 100.0
            return "ghs_test"

        def limit_timeout(self, seconds: float) -> None:
            seen.append(seconds)

    github = GitHub()
    poster = ReviewPoster(
        github,
        Mint(),
        PostLedger(tmp_path / "posted.json"),
        lambda text: text,
        now=lambda: clock["t"],
        bot_login="code-quality-atlas[bot]",
    )
    with pytest.raises(BoundaryError, match="deadline"):
        poster.post(EVENT, REPORT)
    assert github.calls == []
    assert seen and seen[0] <= 45


def test_a_corrupt_post_ledger_exits_2(tmp_path, capsys):
    (tmp_path / "posted.json").write_text("{", encoding="utf-8")
    code = main(
        env={
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
            "ATLAS_SERVICE_PROVIDER": "offline",
            "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
            "ATLAS_GITHUB_APP_ID": "5648875",
            "ATLAS_GITHUB_APP_PRIVATE_KEY": "pem-secret-value",
            "ATLAS_GITHUB_INSTALLATION_ID": "1",
            "ATLAS_GITHUB_APP_SLUG": "code-quality-atlas",
        }
    )
    assert code == 2
    assert "post ledger" in capsys.readouterr().err


def test_stop_does_not_send_a_deferred_post(tmp_path):
    board = Board(tmp_path / "queue.json")
    posted: list[str] = []
    in_post = threading.Event()
    release = threading.Event()
    other = "e" * 40

    def publish(event, report):
        posted.append(event.head_sha)
        if event.head_sha == SHA:
            in_post.set()
            release.wait(2)

    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        publish,
        state_root=tmp_path,
    )
    board.enqueue(EVENT)
    board.enqueue(PrEvent(REPO, 8, other))
    worker.start()
    assert in_post.wait(2)
    for job in board._jobs:
        if job.event.head_sha == other:
            job.state = JobState.POST_PENDING
            job.retry_at = 0
    from atlas_reviewer.service_run import run_dir

    draft = run_dir(tmp_path, PrEvent(REPO, 8, other))
    draft.mkdir(parents=True)
    (draft / "draft.md").write_text("a deferred review\n", encoding="utf-8")

    def release_after_stop_begins():
        assert worker._stop.wait(2)
        release.set()

    helper = threading.Thread(target=release_after_stop_begins)
    helper.start()
    worker.stop(timeout=2)
    helper.join(timeout=2)
    assert posted == [SHA]
    assert other not in posted


def test_stop_after_the_post_is_claimed_does_not_send(tmp_path):
    board = Board(tmp_path / "queue.json")
    posted: list[str] = []

    def publish(event, report):
        posted.append(event.head_sha)

    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        publish,
        state_root=tmp_path,
    )
    real = board.begin_post

    def begin_post(job):
        ok = real(job)
        worker._stop.set()
        job.cancel.set()
        return ok

    board.begin_post = begin_post
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert posted == []
    assert board.states() == ((SHA, JobState.POST_PENDING),)


def test_limit_timeout_stays_on_the_calling_thread():
    seen: dict[str, float] = {}

    class Transport:
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            seen["timeout"] = timeout_s
            payload = {
                "token": "ghs_minted_value",
                "expires_at": "2099-01-01T00:00:00Z",
                "permissions": {"pull_requests": "write"},
            }
            return HttpResponse(201, {}, json.dumps(payload).encode())

    tokens = AppInstallationTokens(
        Transport(),
        SystemClock(),
        app_id="5648875",
        private_key="not-used",
        installation_id=1,
        permissions=POST_PERMISSIONS,
        writable=POST_WRITABLE,
        encode=lambda claims, key: "jwt",
    )
    tokens.limit_timeout(7.5)

    def other() -> None:
        tokens.limit_timeout(1.0)

    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert tokens.token() == "ghs_minted_value"
    assert seen["timeout"] == 7.5
    tokens._cached = None
    assert tokens.token() == "ghs_minted_value"
    assert seen["timeout"] == 30.0


def test_one_workers_deadline_does_not_clear_anothers(tmp_path):
    poster, _github = _poster(tmp_path)
    blocked = threading.Event()
    release = threading.Event()
    gate = threading.Lock()
    seen: dict[str, float | None] = {}

    class Transport:
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            if method == "GET":
                return HttpResponse(200, {}, b"[]")
            with gate:
                first = "first" not in seen
                if first:
                    seen["first"] = 1.0
            if first:
                blocked.set()
                assert release.wait(2)
                seen["remaining"] = poster._remaining()
            review_id = 1 if first else 2
            return HttpResponse(201, {}, json.dumps({"id": review_id}).encode())

    poster._transport = Transport()
    other = PrEvent(REPO, 8, "e" * 40)
    # A new thread does not inherit the context. Copy it so the
    # pre-create hook set for this test is the one each post reads.
    first = threading.Thread(
        target=contextvars.copy_context().run, args=(poster.post, EVENT, REPORT)
    )
    second_ctx = contextvars.copy_context()
    second = threading.Thread(target=second_ctx.run, args=(poster.post, other, REPORT))
    first.start()
    assert blocked.wait(2)
    second.start()
    second.join(2)
    release.set()
    first.join(2)
    assert seen["remaining"] is not None
    assert seen["remaining"] > 0


def test_a_hostile_narrative_is_not_posted():
    secret = "sprt_secret_shaped_value"
    mention = "@everyone"
    image = "https://evil.example/tracker.png"
    draft = f"""\
## Review lenses

| Lens | Status | Characters | Chosen as | Why not run |
| --- | --- | --- | --- | --- |
| tracing-correctness-and-invariants | run whole | 10 | critical |  |

## Review narrative

{secret} {mention} ![]({image})
"""
    body = render_comment(summarize_draft(draft), post_key(EVENT), lambda text: text)
    payload = comment_payload(SHA, body)
    assert secret not in body
    assert mention not in body
    assert image not in body
    assert payload["event"] == "COMMENT"


def test_claim_post_refuses_a_stopped_worker(tmp_path):
    board = Board(tmp_path / "queue.json")
    board.enqueue(EVENT)
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.POST_PENDING)
    job.retry_at = 0
    stop = threading.Event()
    stop.set()
    assert board.claim_post(time.time(), stop=stop) is None
    assert board.states() == ((SHA, JobState.POST_PENDING),)


def test_the_loop_does_not_retry_a_post_after_stop(tmp_path):
    board = Board(tmp_path / "queue.json")
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        lambda event, report: None,
        state_root=tmp_path,
    )
    calls: list[str] = []

    def run_one() -> bool:
        worker._stop.set()
        return False

    def retry_post() -> None:
        calls.append("retry")

    worker.run_one = run_one  # type: ignore[method-assign]
    worker._retry_post = retry_post  # type: ignore[method-assign]
    worker._loop()
    assert calls == []


def test_retry_post_does_not_claim_after_stop(tmp_path):
    board = Board(tmp_path / "queue.json")
    board.enqueue(EVENT)
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.POST_PENDING)
    job.retry_at = 0
    claimed: list[str] = []

    def claim_post(*_args, **_kwargs):
        claimed.append("claim")

    board.claim_post = claim_post  # type: ignore[method-assign]
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        lambda event, report: None,
        state_root=tmp_path,
    )
    worker._stop.set()
    worker._retry_post()
    assert claimed == []


def test_a_rejected_post_fails_without_a_retry(tmp_path):
    board = Board(tmp_path / "queue.json")
    calls: list[int] = []

    def publish(event, report):
        calls.append(1)
        raise PostRejected("HTTP 422")

    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        publish,
        state_root=tmp_path,
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    worker._retry_post()
    assert calls == [1]
    assert board.states() == ((SHA, JobState.FAILED),)
    refused = [event for event in worker._telemetry.events if "422" in event.error]
    assert refused
    assert refused[0].error.startswith("post rejected:")
    assert "post auth refused" not in refused[0].error


def test_the_service_log_scrubs_the_sprites_and_openrouter_secrets(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_init(self, config, board, log):
        self.config = config
        self.board = board
        self.log = log
        self.worker = None

    monkeypatch.setattr(ReviewServer, "__init__", fake_init)
    monkeypatch.setattr(ReviewServer, "serve_forever", lambda self: None)
    monkeypatch.setattr(ReviewServer, "server_close", lambda self: None)
    monkeypatch.setattr(Worker, "start", lambda self: None)
    monkeypatch.setattr(Worker, "stop", lambda self, timeout=30: None)
    real = Telemetry

    def capture(clock, sink=None, scrub=None, max_kept=500):
        captured["scrub"] = scrub
        return real(clock, sink=sink, scrub=scrub, max_kept=max_kept)

    monkeypatch.setattr("atlas_reviewer.service.Telemetry", capture)
    sprite = "org/1/sprites-secret-value"
    model = "sk-or-v1-secret-value"
    env = {
        "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
        "ATLAS_SERVICE_PROVIDER": "offline",
        "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        "ATLAS_SPRITES_TOKEN": sprite,
        "ATLAS_OPENROUTER_API_KEY": model,
    }
    assert serve(config_from_env(env), env) == 0
    scrub = captured["scrub"]
    assert callable(scrub)
    text = scrub(f"see {sprite} and {model}")
    assert sprite not in text
    assert model not in text


def _minting_poster(tmp_path: Path, status: int, body: bytes) -> ReviewPoster:
    class Transport:
        def request(self, method, url, headers, body_bytes, timeout_s, max_bytes=None):
            if str(url).endswith("/access_tokens"):
                return HttpResponse(status, {}, body)
            return HttpResponse(200, {}, b"[]")

    tokens = AppInstallationTokens(
        Transport(),
        SystemClock(),
        app_id="5648875",
        private_key="not-used",
        installation_id=1,
        permissions=POST_PERMISSIONS,
        writable=POST_WRITABLE,
        encode=lambda claims, key: "jwt",
    )
    return ReviewPoster(
        Transport(),
        tokens,
        PostLedger(tmp_path / "posted.json"),
        lambda text: text,
        bot_login="code-quality-atlas[bot]",
    )


def test_a_mint_secondary_limit_is_retried(tmp_path):
    poster = _minting_poster(
        tmp_path, 403, b'{"message":"You have exceeded a secondary rate limit."}'
    )
    board = Board(tmp_path / "queue.json")
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        poster.post,
        state_root=tmp_path,
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert board.states() == ((SHA, JobState.POST_PENDING),)


def test_a_mint_401_is_not_retried(tmp_path):
    poster = _minting_poster(tmp_path, 401, b"")
    board = Board(tmp_path / "queue.json")
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock()),
        poster.post,
        state_root=tmp_path,
    )
    board.enqueue(EVENT)
    assert worker.run_one() is True
    assert board.states() == ((SHA, JobState.FAILED),)


def test_an_allowlist_entry_without_an_owner_is_refused():
    with pytest.raises(ValueError, match="owner/name"):
        _repository_names(frozenset({"noslash"}))


def test_the_posting_token_covers_one_account():
    with pytest.raises(ValueError, match="one GitHub account"):
        _repository_names(frozenset({"alice/shared", "bob/shared"}))
    assert _repository_names(frozenset({"alice/shared", "alice/other"})) == (
        "other",
        "shared",
    )


def test_limit_timeout_is_the_mint_socket_timeout():
    seen: dict[str, float] = {}

    class Transport:
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            seen["timeout"] = timeout_s
            payload = {
                "token": "ghs_minted_value",
                "expires_at": "2099-01-01T00:00:00Z",
                "permissions": {"pull_requests": "write"},
            }
            return HttpResponse(201, {}, json.dumps(payload).encode())

    tokens = AppInstallationTokens(
        Transport(),
        SystemClock(),
        app_id="5648875",
        private_key="not-used",
        installation_id=1,
        permissions=POST_PERMISSIONS,
        writable=POST_WRITABLE,
        encode=lambda claims, key: "jwt",
        timeout_s=30.0,
    )
    tokens.limit_timeout(7.5)
    assert tokens.token() == "ghs_minted_value"
    assert seen["timeout"] == 7.5


def test_main_does_not_listen_without_a_posting_token(tmp_path, capsys):
    code = main(
        env={
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
            "ATLAS_SERVICE_PROVIDER": "offline",
            "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        }
    )
    assert code == 2
    assert "ATLAS_GITHUB_APP_ID" in capsys.readouterr().err
