# SPDX-License-Identifier: MIT
"""COMMENT-only posting: a failure publishes nothing, and a retry does not
post a second review."""

import inspect
import json
from pathlib import Path

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.service import Worker, main
from atlas_reviewer.service_post import (
    PostLedger,
    RefusedReviewEvent,
    ReviewPoster,
    comment_only,
    comment_payload,
    marker_for,
    post_key,
    render_comment,
)
from atlas_reviewer.service_queue import Board, JobState
from atlas_reviewer.service_run import ReviewReport, ReviewRun, run_dir
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


def _poster(
    tmp_path: Path, github: GitHub | None = None
) -> tuple[ReviewPoster, GitHub]:
    github = github or GitHub()
    poster = ReviewPoster(
        github,
        Tokens(),
        PostLedger(tmp_path / "posted.json"),
        lambda text: text,
    )
    return poster, github


def _posted_body(github: GitHub) -> dict[str, str]:
    posts = [call for call in github.calls if call[0] == "POST"]
    assert len(posts) == 1
    payload = json.loads(posts[0][2] or b"")
    assert isinstance(payload, dict)
    return payload


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
