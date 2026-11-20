# SPDX-License-Identifier: MIT
"""Webhook admission: signature, allowlist, duplicate delivery, and a moved head."""

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace as dataclass_replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http.client import HTTPConnection
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from atlas_reviewer.budget import DailySpend, no_installation_cap, spend_file
from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.ports import KEY_AUTH_REFUSED, KEY_OUT_OF_CREDIT
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import event_runner_name
from atlas_reviewer.service import (
    _MAX_HTTP_HANDLERS,
    PostAuthError,
    PostNotCurrent,
    RateLimited,
    ReviewServer,
    ServiceConfig,
    ServiceError,
    Worker,
    _Handler,
    _state_is_writable,
    before_send,
    config_from_env,
    handle_delivery,
    main,
    read_bounded,
    serve,
)
from atlas_reviewer.service_admit import signature_matches
from atlas_reviewer.service_queue import Board, Enqueue, JobState, QueueError
from atlas_reviewer.service_run import ReviewReport, ReviewRun, run_dir
from atlas_reviewer.telemetry import JsonlSink, Telemetry

SECRET = "webhook-secret-value"
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
REPO = "brandondees/code-quality-atlas"
OTHER = "other/repo"
REPORT = ReviewReport(
    ("tracing",),
    ("concurrency: over budget",),
    "note",
    (),
    (),
    (),
    "COMMENT",
    coverage_complete=True,
)


def _body(
    action="opened",
    *,
    draft=False,
    include_draft=True,
    repo=REPO,
    base_repo=None,
    number=7,
    sha=SHA_A,
    updated_at="2026-11-12T20:00:00Z",
):
    pull = {
        "number": number,
        "updated_at": updated_at,
        "head": {"sha": sha},
        "base": {"repo": {"full_name": repo if base_repo is None else base_repo}},
    }
    if include_draft:
        pull["draft"] = draft
    return json.dumps(
        {
            "action": action,
            "repository": {"full_name": repo},
            "pull_request": pull,
        }
    ).encode()


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _config(tmp_path: Path) -> ServiceConfig:
    return ServiceConfig(
        secret=SECRET,
        allowlist=frozenset({REPO}),
        state_dir=tmp_path,
        host="127.0.0.1",
        port=0,
    )


def _deliver(
    config,
    board,
    body,
    *,
    signature=None,
    event="pull_request",
    method="POST",
    path="/webhook",
    worker=None,
    classifier=None,
    telemetry=None,
    admission_reader=None,
    spend=None,
    installations=None,
):
    headers = {"X-GitHub-Event": event}
    if signature is None:
        headers["X-Hub-Signature-256"] = _sign(body)
    elif signature:
        headers["X-Hub-Signature-256"] = signature
    return handle_delivery(
        method,
        path,
        headers,
        body,
        config,
        board,
        worker=worker,
        classifier=classifier,
        telemetry=telemetry,
        admission_reader=admission_reader,
        spend=spend,
        installations=installations,
    )


def _worker(
    board,
    runner,
    publisher=None,
    root=None,
    telemetry=None,
    spend=None,
    funding=None,
    tenant_active=None,
):
    return Worker(
        board,
        runner,
        telemetry or Telemetry(SystemClock()),
        publisher,
        state_root=root,
        spend=spend,
        funding=funding,
        tenant_active=tenant_active,
    )


def test_a_bad_signature_is_refused(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    body = _body()
    flipped = bytes([body[0] ^ 0x01]) + body[1:]
    refused = _deliver(config, board, body, signature=_sign(flipped))
    missing = _deliver(config, board, body, signature="")
    assert refused.status == 401
    assert missing.status == 401
    assert board.states() == ()
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert not signature_matches(body, "sha1=" + digest, SECRET)
    assert not signature_matches(body, "sha1=" + "ab" * 32, SECRET)
    assert not signature_matches(body, "sha256=abcd", SECRET)
    tiny = ServiceConfig(
        secret=SECRET, allowlist=frozenset({REPO}), state_dir=tmp_path, max_body_bytes=4
    )
    assert handle_delivery("POST", "/webhook", {}, b"12345", tiny, board).status == 413
    assert handle_delivery("GET", "/nope", {}, b"", config, board).status == 404


def test_a_non_allowlisted_repo_is_ignored(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    result = _deliver(config, board, _body(repo=OTHER))
    assert result.status == 202
    assert result.body == b"ignored\n"
    assert board.states() == ()


def test_a_missing_draft_and_a_different_base_repo_are_ignored(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    missing = _deliver(config, board, _body(include_draft=False))
    forked = _deliver(config, board, _body(base_repo=OTHER))
    assert missing.body == b"ignored\n"
    assert forked.body == b"ignored\n"
    assert board.states() == ()


def test_a_draft_and_an_unwanted_action_are_ignored(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    assert _deliver(config, board, _body(draft=True)).body == b"ignored\n"
    assert _deliver(config, board, _body(action="closed")).body == b"ignored\n"
    assert _deliver(config, board, _body(), event="ping").body == b"pong\n"
    assert _deliver(config, board, b"[]").body == b"ignored\n"
    assert board.states() == ()


def test_a_duplicate_delivery_is_a_no_op(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    body = _body()
    calls = []

    def runner(event, cancel):
        calls.append(event.head_sha)
        return ReviewRun(True, REPORT)

    assert _deliver(config, board, body).body == b"queued\n"
    assert _deliver(config, board, body).body == b"duplicate\n"
    worker = _worker(board, runner)
    assert worker.run_one() is True
    assert worker.run_one() is False
    assert calls == [SHA_A]
    reloaded = Board(tmp_path / "queue.json")
    assert reloaded.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.DUPLICATE


def test_a_moved_head_supersedes_the_old_review(tmp_path):
    board = Board(tmp_path / "queue.json")
    started = threading.Event()
    posted: list[str] = []

    cancelled: list[bool] = []

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            cancel.wait(2)
            cancelled.append(cancel.is_set())
            return ReviewRun(True, REPORT)
        return ReviewRun(True, REPORT)

    def publish(event, report):
        posted.append(event.head_sha)

    worker = _worker(board, runner, publish, tmp_path)
    worker.start()
    try:
        earlier = datetime(2026, 11, 12, 19, 0, tzinfo=UTC)
        later = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier) is Enqueue.QUEUED
        assert started.wait(2)
        assert board.enqueue(PrEvent(REPO, 7, SHA_B), at=later) is Enqueue.QUEUED
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and posted != [SHA_B]:
            time.sleep(0.01)
    finally:
        worker.stop()
    assert cancelled == [True]
    assert posted == [SHA_B]
    assert (SHA_A, JobState.SUPERSEDED) in board.states()
    assert (SHA_B, JobState.DONE) in board.states()
    assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier) is Enqueue.STALE


def test_an_older_redelivery_does_not_cancel_the_newer_head(tmp_path):
    board = Board(tmp_path / "queue.json")
    started = threading.Event()
    older_arrived = threading.Event()
    posted: list[str] = []
    earlier = datetime(2026, 11, 12, 19, 0, tzinfo=UTC)
    later = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)

    still_running: list[bool] = []

    def runner(event, cancel):
        if event.head_sha == SHA_B:
            started.set()
            older_arrived.wait(2)
            still_running.append(not cancel.is_set())
            return ReviewRun(True, REPORT)
        return ReviewRun(True, REPORT)

    def publish(event, report):
        posted.append(event.head_sha)

    worker = _worker(board, runner, publish, tmp_path)
    worker.start()
    try:
        assert board.enqueue(PrEvent(REPO, 7, SHA_B), at=later) is Enqueue.QUEUED
        assert started.wait(2)
        assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier) is Enqueue.STALE
        older_arrived.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and posted != [SHA_B]:
            time.sleep(0.01)
    finally:
        worker.stop()
    assert still_running == [True]
    assert posted == [SHA_B]
    assert (SHA_B, JobState.DONE) in board.states()
    assert SHA_A not in [sha for sha, _state in board.states()]
    reloaded = Board(tmp_path / "queue.json")
    assert reloaded.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier) is Enqueue.STALE
    config = _config(tmp_path)
    hooked = Board(tmp_path / "hook.json")
    assert (
        _deliver(
            config, hooked, _body(sha=SHA_B, updated_at="2026-11-12T20:00:00Z")
        ).body
        == b"queued\n"
    )
    assert (
        _deliver(
            config, hooked, _body(sha=SHA_A, updated_at="2026-11-12T19:00:00Z")
        ).body
        == b"stale\n"
    )
    assert hooked.states() == ((SHA_B, JobState.QUEUED),)


def test_a_failed_review_is_recorded_and_not_published(tmp_path):
    board = Board(tmp_path / "queue.json")
    published: list[str] = []

    def runner(event, cancel):
        raise RuntimeError("runner blew up")

    worker = _worker(
        board,
        runner,
        lambda event, report: published.append(event.head_sha),
        tmp_path,
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    assert published == []
    assert board.states() == ((SHA_A, JobState.FAILED),)
    failed = [
        event for event in worker._telemetry.events if event.step == "review failed"
    ]
    assert failed and failed[0].status == "error"
    assert "RuntimeError" in failed[0].error


def test_a_running_job_is_queued_again_after_a_restart(tmp_path):
    path = tmp_path / "queue.json"
    board = Board(path)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert board.claim() is not None
    assert board.states() == ((SHA_A, JobState.RUNNING),)
    restarted = Board(path)
    assert restarted.states() == ((SHA_A, JobState.QUEUED),)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(QueueError):
        Board(path)


def test_health_and_the_socket_refuse_a_bad_signature(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    server = ReviewServer(config, board, lambda line: None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = _body()
    try:
        health = HTTPConnection(host, port, timeout=2)
        health.request("GET", "/health")
        assert health.getresponse().status == 200
        health.close()
        bad = HTTPConnection(host, port, timeout=2)
        bad.request(
            "POST",
            "/webhook",
            body=body,
            headers={
                "Content-Length": str(len(body)),
                "X-Hub-Signature-256": _sign(body, "not-the-real-secret"),
                "X-GitHub-Event": "pull_request",
            },
        )
        assert bad.getresponse().status == 401
        bad.close()
        good = HTTPConnection(host, port, timeout=2)
        good.request(
            "POST",
            "/webhook",
            body=body,
            headers={
                "Content-Length": str(len(body)),
                "X-Hub-Signature-256": _sign(body),
                "X-GitHub-Event": "pull_request",
            },
        )
        accepted = good.getresponse()
        assert accepted.status == 202
        assert accepted.read() == b"queued\n"
        good.close()
        sock = socket.create_connection((host, port), timeout=2)
        sock.sendall(
            b"POST /webhook HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        assert b"411" in sock.recv(200)
        sock.close()
        huge = socket.create_connection((host, port), timeout=2)
        huge.sendall(
            b"POST /webhook HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: 99999999\r\nConnection: close\r\n\r\n"
        )
        assert b"413" in huge.recv(200)
        huge.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert board.states() == ((SHA_A, JobState.QUEUED),)


def test_a_post_is_not_retried_immediately_or_without_a_budget(tmp_path):
    board = Board(tmp_path / "queue.json")
    calls: list[float] = []
    clock = {"t": 1_000.0}

    def publish(event, report):
        calls.append(clock["t"])
        raise RuntimeError("github down")

    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        publish,
        tmp_path,
    )
    worker._now = lambda: clock["t"]
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    worker._retry_post()
    assert len(calls) == 1
    assert board.states() == ((SHA_A, JobState.POST_PENDING),)
    from atlas_reviewer.service_run import run_dir

    draft = run_dir(tmp_path, PrEvent(REPO, 7, SHA_A))
    draft.mkdir(parents=True)
    (draft / "draft.md").write_text("no sections\n", encoding="utf-8")
    for _ in range(6):
        clock["t"] += 10_000
        worker._retry_post()
    assert board.states() == ((SHA_A, JobState.FAILED),)
    assert len(calls) == 5


def test_stop_cancels_the_review_child(tmp_path):
    board = Board(tmp_path / "queue.json")
    started = threading.Event()

    cancelled: list[bool] = []

    def runner(event, cancel):
        started.set()
        cancel.wait(2)
        cancelled.append(cancel.is_set())
        return ReviewRun(False, error="superseded")

    worker = _worker(board, runner)
    worker.start()
    try:
        board.enqueue(PrEvent(REPO, 7, SHA_A))
        assert started.wait(2)
    finally:
        worker.stop()
    assert cancelled == [True]
    assert board.states() == ((SHA_A, JobState.QUEUED),)


def test_a_stopped_review_is_queued_again_after_reload(tmp_path):
    board = Board(tmp_path / "queue.json")
    started = threading.Event()

    def runner(event, cancel):
        started.set()
        cancel.wait(2)
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)
    moment = datetime(2026, 11, 12, 20, tzinfo=UTC)
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment)
    worker.start()
    try:
        assert started.wait(2)
    finally:
        worker.stop()
    reloaded = Board(tmp_path / "queue.json")
    assert reloaded.states() == ((SHA_A, JobState.QUEUED),)
    later = datetime(2026, 11, 12, 21, tzinfo=UTC)
    assert reloaded.enqueue(PrEvent(REPO, 7, SHA_A), at=later) is Enqueue.DUPLICATE


def test_a_trimmed_commit_and_a_pre_attempts_queue_stay_duplicates(tmp_path):
    board = Board(tmp_path / "queue.json", max_remembered=1)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    claimed = board.claim()
    assert claimed is not None
    board.finish(claimed, JobState.DONE)
    assert board.enqueue(PrEvent(REPO, 8, SHA_B)) is Enqueue.QUEUED
    assert board.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.DUPLICATE
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "repo": REPO,
                        "pr": 7,
                        "sha": SHA_A,
                        "state": "failed",
                        "superseded": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = Board(legacy)
    # A failed head is not a duplicate: the delivery was already
    # acknowledged, so this is the retry.
    assert loaded.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.QUEUED


def test_seen_keeps_current_heads_and_drops_the_oldest_other_keys(tmp_path):
    board = Board(tmp_path / "queue.json", max_remembered=1, max_seen=2)
    base = datetime(2026, 11, 12, 18, tzinfo=UTC)
    shas = [f"{number}" * 40 for number in range(1, 5)]
    for index, sha in enumerate(shas):
        moment = base.replace(hour=18 + index)
        assert board.enqueue(PrEvent(REPO, 7, sha), at=moment) is Enqueue.QUEUED
        job = board.claim()
        assert job is not None
        board.finish(job, JobState.DONE)
    later = datetime(2026, 11, 12, 23, tzinfo=UTC)
    # The current head and the newest trimmed keys stay duplicates. The
    # oldest trimmed key can be admitted again, which is the cap.
    assert board.enqueue(PrEvent(REPO, 7, shas[3]), at=later) is Enqueue.DUPLICATE
    assert board.enqueue(PrEvent(REPO, 7, shas[2]), at=later) is Enqueue.DUPLICATE
    assert board.enqueue(PrEvent(REPO, 7, shas[1]), at=later) is Enqueue.DUPLICATE
    assert board.enqueue(PrEvent(REPO, 7, shas[0]), at=later) is Enqueue.QUEUED


def test_a_finished_review_removes_its_run_directory_and_is_logged(tmp_path):
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("kept until the job ends\n", encoding="utf-8")
    with JsonlSink(tmp_path / "service.jsonl") as sink:
        worker = Worker(
            board,
            lambda event, cancel: ReviewRun(False, error="no"),
            Telemetry(SystemClock(), sink=sink, scrub=lambda text: text),
            state_root=tmp_path,
        )
        board.enqueue(event)
        assert worker.run_one() is True
    assert not directory.exists()
    assert "review failed" in (tmp_path / "service.jsonl").read_text(encoding="utf-8")


def test_a_post_that_finds_the_head_moved_is_not_retried(tmp_path):
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("the review\n", encoding="utf-8")
    calls = []

    def publish(reviewed, report):
        calls.append(reviewed.head_sha)
        for job in board._jobs:
            if job.event.head_sha == reviewed.head_sha:
                job.superseded = True
        raise PostNotCurrent("moved")

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    board.enqueue(event)
    assert worker.run_one() is True
    worker._retry_post()
    assert calls == [SHA_A]
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)
    assert not directory.exists()


def test_a_stop_during_the_post_keeps_the_draft(tmp_path):
    """A stubbed stop is not a moved head.

    The draft stays, and the job goes back to pending. The real listing
    path is ``test_a_stop_during_the_listing_does_not_post``. A moved
    head still removes the directory in
    ``test_a_post_that_finds_the_head_moved_is_not_retried``.
    """
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("the review\n", encoding="utf-8")
    (directory / "stderr.txt").write_text("plainchildsecretvalue\n", encoding="utf-8")

    def publish(_event, _report):
        for job in board._jobs:
            if job.event.head_sha == SHA_A:
                job.cancel.set()
        raise PostNotCurrent("stopped")

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    board.enqueue(event)
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.POST_PENDING),)
    assert (directory / "draft.md").is_file()
    assert (directory / "stderr.txt").is_file()


def test_the_send_rechecks_the_head_before_it_leaves(tmp_path):
    board = Board(tmp_path / "queue.json")
    earlier = datetime(2026, 11, 12, 20, tzinfo=UTC)
    later = datetime(2026, 11, 12, 21, tzinfo=UTC)
    verdict = []

    def publish(event, report):
        board.enqueue(PrEvent(REPO, 7, SHA_B), at=later)
        check = before_send.get()
        assert check is not None
        verdict.append(check())
        if not verdict[-1]:
            raise PostNotCurrent("moved")

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier)
    assert worker.run_one() is True
    assert verdict == [False]
    assert board.states()[0] == (SHA_A, JobState.SUPERSEDED)


def test_an_auth_refusal_fails_the_post_without_a_retry(tmp_path):
    board = Board(tmp_path / "queue.json")
    calls = []

    def publish(event, report):
        calls.append(1)
        raise PostAuthError("HTTP 401")

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    worker._retry_post()
    assert calls == [1]
    assert board.states() == ((SHA_A, JobState.FAILED),)


def test_a_rate_limit_waits_at_least_as_long_as_github_asked(tmp_path):
    board = Board(tmp_path / "queue.json")
    clock = {"t": 1_000.0}
    calls = []

    def publish(event, report):
        calls.append(clock["t"])
        raise RateLimited("slow down", 50)

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    worker._now = lambda: clock["t"]
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    clock["t"] += 49
    worker._retry_post()
    assert calls == [1_000.0]
    assert board.states() == ((SHA_A, JobState.POST_PENDING),)


def test_a_failed_head_can_be_queued_again(tmp_path):
    board = Board(tmp_path / "queue.json", max_remembered=1)
    moment = datetime(2026, 11, 12, 20, tzinfo=UTC)
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment)
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.FAILED)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment) is Enqueue.QUEUED
    # Trim the failure out of the file, then deliver the same SHA again.
    other = board.claim()
    assert other is not None
    board.finish(other, JobState.FAILED)
    assert board.enqueue(PrEvent(REPO, 8, SHA_B), at=moment) is Enqueue.QUEUED
    trimmed = board.claim()
    assert trimmed is not None
    board.finish(trimmed, JobState.DONE)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment) is Enqueue.QUEUED


def test_the_current_head_stays_a_duplicate_after_the_seen_cap(tmp_path):
    board = Board(tmp_path / "queue.json", max_remembered=1, max_seen=1)
    base = datetime(2026, 11, 12, 18, tzinfo=UTC)
    later = datetime(2026, 11, 12, 23, tzinfo=UTC)
    first = "1" * 40
    second = "2" * 40
    third = "3" * 40
    assert board.enqueue(PrEvent(REPO, 7, first), at=base) is Enqueue.QUEUED
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.DONE)
    assert (
        board.enqueue(PrEvent(REPO, 8, second), at=base.replace(hour=19))
        is Enqueue.QUEUED
    )
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.DONE)
    assert (
        board.enqueue(PrEvent(REPO, 9, third), at=base.replace(hour=20))
        is Enqueue.QUEUED
    )
    assert board.enqueue(PrEvent(REPO, 7, first), at=later) is Enqueue.DUPLICATE


def test_active_jobs_stop_at_the_cap(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json", max_remembered=1)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.QUEUED
    assert board.enqueue(PrEvent(REPO, 8, SHA_B)) is Enqueue.FULL
    refused = _deliver(config, board, _body(number=9, sha="9" * 40))
    assert refused.status == 503
    assert refused.body == b"full\n"


def test_a_save_error_does_not_kill_the_worker(tmp_path):
    board = Board(tmp_path / "queue.json")
    ran: list[str] = []

    def runner(event, cancel):
        ran.append(event.head_sha)
        return ReviewRun(False, error="no")

    worker = _worker(board, runner, root=tmp_path)
    original = board.finish

    def finish(job, state):
        if job.event.head_sha == SHA_A:
            raise OSError("disk")
        return original(job, state)

    board.finish = finish
    worker.start()
    try:
        board.enqueue(PrEvent(REPO, 7, SHA_A))
        board.enqueue(PrEvent(REPO, 8, SHA_B))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and SHA_B not in ran:
            time.sleep(0.01)
        assert SHA_B in ran
        assert worker.healthy()
    finally:
        worker.stop()


def test_a_dead_worker_fails_health(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    server = ReviewServer(config, board, lambda line: None)
    worker = _worker(board, lambda event, cancel: ReviewRun(False, error="no"))
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    worker._threads.append(thread)
    server.worker = worker
    server.timeout = 0.2
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    host, port = server.server_address
    try:
        health = HTTPConnection(host, port, timeout=2)
        health.request("GET", "/health")
        assert health.getresponse().status == 503
        health.close()
    finally:
        server.shutdown()
        listener.join(timeout=2)
        server.server_close()


def test_the_service_log_rotates_and_names_the_head(tmp_path):
    from atlas_reviewer.telemetry import JsonlSink

    with JsonlSink(tmp_path / "service.jsonl", max_bytes=1) as sink:
        telemetry = Telemetry(SystemClock(), sink=sink, scrub=lambda text: text)
        telemetry.record(
            "service",
            "review failed",
            {"pr": 7, "sha12": "a" * 12, "attempts": 2, "retry_s": 5},
            status="error",
            error="HTTP 500",
        )
        telemetry.record("service", "review posted", {"pr": 7, "sha12": "b" * 12})
    assert (tmp_path / "service.jsonl.1").is_file()
    assert [event.step for event in telemetry.events] == [
        "review failed",
        "review posted",
    ]
    bounded = Telemetry(SystemClock(), max_kept=2)
    for number in range(4):
        bounded.record("service", f"step-{number}", {})
    assert [event.step for event in bounded.events] == ["step-2", "step-3"]


def test_the_module_refuses_a_port_other_than_8080(tmp_path):
    with pytest.raises(ServiceError, match="8080"):
        config_from_env(
            {
                "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
                "ATLAS_SERVICE_PROVIDER": "offline",
                "ATLAS_SERVICE_PORT": "8081",
                "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
            }
        )
    config = config_from_env(
        {
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
            "ATLAS_SERVICE_PROVIDER": "offline",
            "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        }
    )
    assert config.host == "127.0.0.1"
    assert config.port == 8080


def test_a_publisher_that_ignores_the_recheck_is_not_called_once_superseded(tmp_path):
    board = Board(tmp_path / "queue.json")
    called: list[str] = []

    def publish(event, report):
        called.append(event.head_sha)

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    job.superseded = True
    worker._send(job, REPORT)
    assert called == []
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)


def test_a_review_logs_the_runner_name(tmp_path):
    board = Board(tmp_path / "queue.json")
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    event = PrEvent(REPO, 7, SHA_A)
    board.enqueue(event)
    job = board.claim()
    assert job is not None
    worker._execute(job)
    named = [item for item in worker._telemetry.events if item.step == "runner named"]
    assert [item.fields["runner"] for item in named] == [event_runner_name(event)]


def test_a_supersede_during_finish_is_what_the_log_says(tmp_path):
    board = Board(tmp_path / "queue.json")
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    real = board.still_current

    def still(current):
        ok = real(current)
        current.superseded = True
        return ok

    board.still_current = still
    worker._execute(job)
    finished = [event.step for event in worker._telemetry.events]
    assert "review finished" not in finished
    assert "review superseded" in finished
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)


def test_a_log_error_after_a_settled_review_does_not_fail_the_job(tmp_path):
    """The silent-failures case: the review settled DONE, then the log
    write raised. The head must stay DONE, not become a retry."""

    class RaisingSink:
        def emit(self, event):
            if event.step == "review finished":
                raise OSError("log full")

    board = Board(tmp_path / "queue.json")
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock(), sink=RaisingSink(), scrub=lambda text: text),
        state_root=tmp_path,
    )
    moment = datetime(2026, 11, 12, 20, tzinfo=UTC)
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment)
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.DONE),)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment) is Enqueue.DUPLICATE


def test_a_newer_head_replaces_the_slot_when_the_queue_is_full(tmp_path):
    board = Board(tmp_path / "queue.json", max_remembered=1)
    earlier = datetime(2026, 11, 12, 19, tzinfo=UTC)
    later = datetime(2026, 11, 12, 20, tzinfo=UTC)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier) is Enqueue.QUEUED
    old = board._jobs[0]
    assert board.enqueue(PrEvent(REPO, 7, SHA_B), at=later) is Enqueue.QUEUED
    assert old.cancel.is_set()
    assert old.state is JobState.SUPERSEDED
    assert dict(board.states())[SHA_B] is JobState.QUEUED
    running = Board(tmp_path / "running.json", max_remembered=1)
    assert running.enqueue(PrEvent(REPO, 7, SHA_A), at=earlier) is Enqueue.QUEUED
    claimed = running.claim()
    assert claimed is not None
    assert running.enqueue(PrEvent(REPO, 7, SHA_B), at=later) is Enqueue.QUEUED
    assert claimed.cancel.is_set()
    assert claimed.superseded is True


def test_stop_does_not_start_a_queued_review(tmp_path):
    board = Board(tmp_path / "queue.json")
    entered = threading.Event()
    release = threading.Event()
    started: list[bool] = []
    real = board.claim

    def claim():
        entered.set()
        assert release.wait(2)
        return real()

    board.claim = claim

    def runner(event, cancel):
        started.append(cancel.is_set())
        return ReviewRun(False, error="ran")

    worker = _worker(board, runner, root=tmp_path)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    worker.start()
    assert entered.wait(2)

    def release_after_stop_begins():
        assert worker._stop.wait(2)
        release.set()

    threading.Thread(target=release_after_stop_begins).start()
    worker.stop(timeout=2)
    assert started == []
    assert board.states() == ((SHA_A, JobState.QUEUED),)
    assert board._jobs[0].cancel.is_set() is False


def test_a_failed_claim_save_leaves_the_job_queued(tmp_path):
    board = Board(tmp_path / "queue.json")
    real = board._save
    calls = {"n": 0}

    def save():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("disk")
        return real()

    board._save = save
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    with pytest.raises(OSError, match="disk"):
        board.claim()
    assert board.states() == ((SHA_A, JobState.QUEUED),)
    board._save = real
    claimed = board.claim()
    assert claimed is not None
    assert claimed.state is JobState.RUNNING


def test_a_supersede_during_a_deferred_post_is_not_logged_as_a_retry(tmp_path):
    board = Board(tmp_path / "queue.json")
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    real = board.settle

    def settle(current, state, **kw):
        current.superseded = True
        return real(current, state, **kw)

    board.settle = settle
    worker._defer_post(job, "github down")
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)
    steps = [event.step for event in worker._telemetry.events]
    assert "review post failed" not in steps
    assert "review superseded" in steps


def test_finish_stores_superseded_when_the_flag_is_already_set(tmp_path):
    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    job.superseded = True
    assert board.finish(job, JobState.DONE) is JobState.SUPERSEDED
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)


def test_the_post_backoff_includes_jitter(tmp_path):
    board = Board(tmp_path / "queue.json")
    clock = {"t": 1_000.0}
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        lambda event, report: (_ for _ in ()).throw(RuntimeError("down")),
        tmp_path,
    )
    worker._now = lambda: clock["t"]
    worker._random = lambda: 1.0
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    job = board._jobs[0]
    assert job.retry_at == 1_000.0 + 5.0 * 1.2


def test_a_log_error_after_a_defer_leaves_the_post_pending(tmp_path):
    """A sink error after the post is deferred must not mark the job
    FAILED, or the same commit is reviewed again."""
    from atlas_reviewer.service_run import run_dir

    class RaisingSink:
        def emit(self, event):
            if event.step == "review post failed":
                raise OSError("log full")

    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    draft = run_dir(tmp_path, event)
    draft.mkdir(parents=True)
    (draft / "draft.md").write_text("kept while the post waits\n", encoding="utf-8")
    moment = datetime(2026, 11, 12, 20, tzinfo=UTC)

    def publish(event, report):
        raise RuntimeError("github down")

    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        Telemetry(SystemClock(), sink=RaisingSink(), scrub=lambda text: text),
        publish,
        state_root=tmp_path,
    )
    board.enqueue(event, at=moment)
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.POST_PENDING),)
    assert (draft / "draft.md").is_file()
    assert board.enqueue(event, at=moment) is Enqueue.DUPLICATE


def test_a_log_error_after_failure_or_supersede_leaves_that_state(tmp_path):
    def drive(root, step, runner):
        class RaisingSink:
            def emit(self, event):
                if event.step == step:
                    raise OSError("log full")

        board = Board(root / "queue.json")
        finishes: list[JobState] = []
        real = board.settle

        def settle(job, state, **kw):
            committed, _follow_up = real(job, state)
            finishes.append(committed)
            return committed, _follow_up

        board.settle = settle
        worker = Worker(
            board,
            runner,
            Telemetry(SystemClock(), sink=RaisingSink(), scrub=lambda text: text),
            state_root=root,
        )
        board.enqueue(PrEvent(REPO, 7, SHA_A))
        assert worker.run_one() is True
        return board, finishes

    failed, failed_calls = drive(
        tmp_path / "failed",
        "review failed",
        lambda event, cancel: ReviewRun(False, error="no"),
    )
    assert failed.states() == ((SHA_A, JobState.FAILED),)
    assert failed_calls == [JobState.FAILED]

    board_box: dict[str, Board] = {}

    def mark_runner(event, cancel):
        for job in board_box["board"]._jobs:
            job.superseded = True
            job.cancel.set()
        return ReviewRun(True, REPORT)

    class RaisingSink:
        def emit(self, event):
            if event.step == "review superseded":
                raise OSError("log full")

    board = Board(tmp_path / "superseded" / "queue.json")
    board_box["board"] = board
    finishes: list[JobState] = []
    real = board.settle

    def settle(job, state, **kw):
        committed, _follow_up = real(job, state)
        finishes.append(committed)
        return committed, _follow_up

    board.settle = settle
    worker = Worker(
        board,
        mark_runner,
        Telemetry(SystemClock(), sink=RaisingSink(), scrub=lambda text: text),
        state_root=tmp_path / "superseded",
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)
    assert JobState.FAILED not in finishes


def test_stop_before_claim_does_not_claim(tmp_path):
    board = Board(tmp_path / "queue.json")
    calls: list[int] = []
    real = board.claim

    def claim():
        calls.append(1)
        return real()

    board.claim = claim
    worker = _worker(board, lambda event, cancel: ReviewRun(False, error="no"))
    worker._stop.set()
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is False
    assert calls == []
    assert board.states() == ((SHA_A, JobState.QUEUED),)


def test_a_failed_post_claim_save_stays_pending(tmp_path, monkeypatch):
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.POST_PENDING)
    job.retry_at = 0

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError, match="disk"):
        board.claim_post(1.0)
    assert board.states() == ((SHA_A, JobState.POST_PENDING),)
    assert board.saves_ok() is False


def test_a_persistent_save_failure_does_not_hot_loop(tmp_path, monkeypatch):
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    started = time.monotonic()
    real = queue_mod._store

    def boom(*args, **kwargs):
        if time.monotonic() - started < 1.0:
            raise OSError("disk")
        return real(*args, **kwargs)

    monkeypatch.setattr(queue_mod, "_store", boom)
    claims = {"n": 0, "at": []}
    real_claim = board.claim

    def claim():
        claims["at"].append(time.monotonic())
        claims["n"] += 1
        return real_claim()

    board.claim = claim
    worker = _worker(
        board, lambda event, cancel: ReviewRun(False, error="no"), root=tmp_path
    )
    config = _config(tmp_path)
    server = ReviewServer(config, board, lambda line: None)
    server.worker = worker
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    host, port = server.server_address
    worker.start()
    try:
        time.sleep(0.3)
        health = HTTPConnection(host, port, timeout=2)
        health.request("GET", "/health")
        assert health.getresponse().status == 503
        health.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not board.saves_ok():
            time.sleep(0.05)
        recovered = HTTPConnection(host, port, timeout=2)
        recovered.request("GET", "/health")
        assert recovered.getresponse().status == 200
        recovered.close()
        gaps = [
            claims["at"][index] - claims["at"][index - 1]
            for index in range(1, len(claims["at"]))
        ]
        assert gaps
        assert min(gaps) >= 0.8
    finally:
        worker.stop()
        server.shutdown()
        listener.join(timeout=2)
        server.server_close()


def test_a_failed_save_rolls_back_enqueue_finish_and_begin_post(tmp_path, monkeypatch):
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError, match="disk"):
        board.enqueue(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 21, tzinfo=UTC)
        )
    assert job.superseded is False
    assert job.cancel.is_set() is False
    assert board.states() == ((SHA_A, JobState.RUNNING),)
    with pytest.raises(OSError, match="disk"):
        board.begin_post(job)
    assert board.states() == ((SHA_A, JobState.RUNNING),)
    with pytest.raises(OSError, match="disk"):
        board.finish(job, JobState.DONE)
    assert board.states() == ((SHA_A, JobState.RUNNING),)


def test_a_claim_save_error_names_the_job(tmp_path, monkeypatch):
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    holder: dict[str, Worker] = {}

    class Sink:
        def emit(self, event):
            if event.step == "worker error":
                holder["worker"]._stop.set()

    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(False, error="no"),
        Telemetry(SystemClock(), sink=Sink(), scrub=lambda text: text),
        state_root=tmp_path,
    )
    holder["worker"] = worker
    worker._loop()
    errors = [
        event for event in worker._telemetry.events if event.step == "worker error"
    ]
    assert errors
    assert errors[0].fields["pr"] == 7
    assert errors[0].fields["repo"] == REPO
    assert errors[0].fields["sha12"] == SHA_A[:12]


def test_a_deeply_nested_body_is_ignored(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    body = b"[" * 10_000 + b"]" * 10_000
    result = _deliver(config, board, body)
    assert result.status == 202
    assert board.states() == ()


def test_the_same_second_with_a_different_sha_is_not_stale(tmp_path):
    board = Board(tmp_path / "queue.json")
    moment = datetime(2026, 11, 12, 20, tzinfo=UTC)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment) is Enqueue.QUEUED
    assert board.enqueue(PrEvent(REPO, 7, SHA_B), at=moment) is Enqueue.QUEUED
    assert board.states()[0] == (SHA_A, JobState.SUPERSEDED)
    assert board.states()[1] == (SHA_B, JobState.QUEUED)


def test_a_post_claim_waits_out_a_failed_save(tmp_path, monkeypatch):
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.POST_PENDING)
    job.retry_at = 0

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError):
        board._save()
    assert board.claim_post(time.time()) is None
    assert board.states() == ((SHA_A, JobState.POST_PENDING),)


def test_a_due_post_does_not_spin_without_a_publisher(tmp_path):
    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    board.finish(job, JobState.POST_PENDING)
    job.retry_at = 0
    started = time.monotonic()
    board.wait_for_work(0.4, threading.Event(), time.time(), posts=False)
    assert time.monotonic() - started >= 0.3


def test_a_log_that_always_raises_does_not_kill_the_worker(tmp_path):
    class Boom:
        def emit(self, event):
            raise OSError("log")

    board = Board(tmp_path / "queue.json")
    worker = Worker(
        board,
        lambda event, cancel: ReviewRun(False, error="no"),
        Telemetry(SystemClock(), sink=Boom(), scrub=lambda text: text),
        state_root=tmp_path,
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    worker.start()
    try:
        time.sleep(0.3)
        assert worker.healthy()
    finally:
        worker.stop()


def test_a_slow_body_is_refused(tmp_path, monkeypatch):
    import atlas_reviewer.service as service_mod

    clock = {"t": 0.0}

    def now() -> float:
        clock["t"] += 25
        return clock["t"]

    monkeypatch.setattr(service_mod, "_monotonic", now)

    class Reader:
        def read(self, _n: int) -> bytes:
            return b"x"

        def read1(self, n: int) -> bytes:
            return self.read(n)

    class Conn:
        def gettimeout(self) -> float:
            return 20.0

        def settimeout(self, value: float) -> None:
            return None

    handler = _Handler.__new__(_Handler)
    handler.rfile = Reader()
    handler.connection = Conn()
    handler.headers = {"Content-Length": "40"}
    handler.timeout = 20.0
    sent: list[int] = []
    handler._send = lambda status, body: sent.append(status)  # type: ignore[method-assign]
    handler.server = type(
        "S",
        (),
        {
            "config": type("C", (), {"max_body_bytes": 1_000_000})(),
            "log": staticmethod(lambda line: None),
        },
    )()
    handler._read_post()
    assert sent == [408]


def test_read_bounded_stops_at_the_deadline():
    def read(_n: int) -> bytes:
        return b"x"

    clock = iter((0.0, 0.0, 100.0))
    assert read_bounded(read, 40, 20.0, lambda: next(clock)) is None


def test_a_full_connection_table_refuses_the_next_client(tmp_path):
    board = Board(tmp_path / "queue.json")
    server = ReviewServer(_config(tmp_path), board, lambda line: None)
    held = [
        server.connections.acquire(blocking=False) for _ in range(_MAX_HTTP_HANDLERS)
    ]
    assert all(held)
    sent: list[bytes] = []

    class Sock:
        def sendall(self, data: bytes) -> None:
            sent.append(data)

        def close(self) -> None:
            return None

    server.process_request(Sock(), ("127.0.0.1", 9))  # type: ignore[arg-type]
    assert sent and b"429" in sent[0]
    for _ in held:
        server.connections.release()
    server.server_close()


def test_main_scrubs_the_child_secrets(tmp_path, monkeypatch):
    import atlas_reviewer.service as service_mod

    seen: dict[str, object] = {}

    def serve(config, env, **kwargs):
        seen["sources"] = kwargs.get("secret_sources", ())
        return 0

    monkeypatch.setattr(service_mod, "serve", serve)
    # On the posting branch, main mints a publisher before serve. That
    # construction needs App env this test does not set, and it is not
    # what the assertion checks.
    try:
        import atlas_reviewer.service_post as post_mod
    except ImportError:
        post_mod = None
    if post_mod is not None and hasattr(post_mod, "publisher_from_env"):

        class _Poster:
            def post(self, event, report):
                return None

            def credential_secrets(self):
                return ("minted-app-credential",)

        monkeypatch.setattr(
            post_mod, "publisher_from_env", lambda *args, **kwargs: _Poster()
        )
    sprite = "sprite-token-value"
    env = {
        "ATLAS_GITHUB_WEBHOOK_SECRET": "webhook-secret-value",
        "ATLAS_SERVICE_PROVIDER": "offline",
        "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        "ATLAS_SPRITES_TOKEN": sprite,
    }
    assert main(env=env) == 0
    sources = seen["sources"]
    assert isinstance(sources, tuple) and sources
    scrubbed = Redactor(known_secrets=("webhook-secret-value",), sources=sources)(
        f"stderr saw {sprite} and minted-app-credential"
    )
    assert sprite not in scrubbed.text
    assert "minted-app-credential" not in scrubbed.text


def test_a_finished_review_keeps_its_draft_when_nothing_is_posted(tmp_path):
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("the review\n", encoding="utf-8")
    (directory / "stderr.txt").write_text("plainchildsecretvalue\n", encoding="utf-8")
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    board.enqueue(event)
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.DONE),)
    assert (directory / "draft.md").is_file()
    assert not (directory / "stderr.txt").exists()


def test_a_supersede_during_release_removes_the_run_directory(tmp_path, monkeypatch):
    """The worker reads ``superseded`` before ``release_claim``.

    A newer head in that window makes the Board store SUPERSEDED. The
    run directory, including the child's stderr, has to be removed, and
    the supersede has to be logged.
    """
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    board.enqueue(event, at=datetime(2026, 11, 12, 20, tzinfo=UTC))

    def runner(_event, cancel):
        directory.mkdir(parents=True)
        (directory / "draft.md").write_text("the review\n", encoding="utf-8")
        (directory / "stderr.txt").write_text(
            "plainchildsecretvalue\n", encoding="utf-8"
        )
        cancel.set()
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)
    real = board.release_claim

    def release(job):
        assert (
            board.enqueue(
                PrEvent(REPO, 7, SHA_B),
                at=datetime(2026, 11, 12, 21, tzinfo=UTC),
            )
            is Enqueue.QUEUED
        )
        return real(job)

    monkeypatch.setattr(board, "release_claim", release)
    assert worker.run_one() is True
    assert (SHA_A, JobState.SUPERSEDED) in board.states()
    assert not directory.exists()
    assert any(
        record.step == "review superseded" for record in worker._telemetry.events
    )


def test_a_newer_head_removes_a_queued_run_directory(tmp_path):
    """A queued job is stored SUPERSEDED inside enqueue.

    It never returns to the worker, so the delivery has to remove the
    run directory and log the supersede.
    """
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    board.enqueue(event, at=datetime(2026, 11, 12, 20, tzinfo=UTC))
    job = board.claim()
    assert job is not None
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("the review\n", encoding="utf-8")
    (directory / "stderr.txt").write_text("plainchildsecretvalue\n", encoding="utf-8")
    assert board.release_claim(job) is JobState.QUEUED
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    delivered = _deliver(
        _config(tmp_path),
        board,
        _body(sha=SHA_B, updated_at="2026-11-12T21:00:00Z"),
        worker=worker,
    )
    assert delivered.status == 202
    assert job.state is JobState.SUPERSEDED
    assert not directory.exists()
    assert any(
        record.step == "review superseded" for record in worker._telemetry.events
    )


def test_a_newer_head_removes_a_pending_post_directory(tmp_path):
    """A post waiting to retry is stored SUPERSEDED inside enqueue.

    The draft and the child's stderr are on disk, and this job does not
    go back through the worker.
    """
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    board.enqueue(event, at=datetime(2026, 11, 12, 20, tzinfo=UTC))
    job = board.claim()
    assert job is not None
    assert board.finish(job, JobState.POST_PENDING) is JobState.POST_PENDING
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("the review\n", encoding="utf-8")
    (directory / "stderr.txt").write_text("plainchildsecretvalue\n", encoding="utf-8")
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    delivered = _deliver(
        _config(tmp_path),
        board,
        _body(sha=SHA_B, updated_at="2026-11-12T21:00:00Z"),
        worker=worker,
    )
    assert delivered.status == 202
    assert job.state is JobState.SUPERSEDED
    assert not directory.exists()
    assert any(
        record.step == "review superseded" for record in worker._telemetry.events
    )


def test_a_bad_status_line_removes_the_run_directory(tmp_path):
    """``parse_status`` raises on a status wrapper that is not JSON.

    ``_publish_saved`` does not catch that, so ``_fail_closed`` has to
    settle the job and remove the directory.
    """
    from atlas_reviewer.verdict import STATUS_PREFIX

    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    board.enqueue(event)
    job = board.claim()
    assert job is not None
    assert board.finish(job, JobState.POST_PENDING) is JobState.POST_PENDING
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text(
        f"{STATUS_PREFIX}not-json -->\n", encoding="utf-8"
    )
    (directory / "stderr.txt").write_text("plainchildsecretvalue\n", encoding="utf-8")
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        publisher=lambda event, report: None,
        root=tmp_path,
    )
    worker._retry_post()
    assert job.state is JobState.FAILED
    assert not directory.exists()


def test_a_supersede_during_finish_removes_the_draft(tmp_path, monkeypatch):
    """A no-publisher finish that stores SUPERSEDED drops the directory.

    The draft stays only when the stored state is DONE.
    """
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    board.enqueue(event)

    def runner(_event, _cancel):
        directory.mkdir(parents=True)
        (directory / "draft.md").write_text("the review\n", encoding="utf-8")
        (directory / "stderr.txt").write_text(
            "plainchildsecretvalue\n", encoding="utf-8"
        )
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)
    real = board.settle

    def settle(job, state, **kw):
        job.superseded = True
        return real(job, state)

    monkeypatch.setattr(board, "settle", settle)
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)
    assert not directory.exists()


def test_a_supersede_that_wins_the_pause_race_is_not_left_pending(tmp_path):
    """The worker reads ``superseded`` outside the lock, then parks the post.

    A newer head can set the flag in that window. ``pause_post`` has to
    store SUPERSEDED under the lock, or the job stays pending and holds
    an active slot ``claim_post`` will not take.
    """
    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=datetime(2026, 11, 12, 20, tzinfo=UTC))
    job = board.claim()
    assert job is not None
    assert board.begin_post(job) is True
    saw_clear = threading.Event()
    landed = threading.Event()

    def worker() -> None:
        superseded = job.superseded
        saw_clear.set()
        assert landed.wait(2)
        if superseded:
            board.finish(job, JobState.SUPERSEDED)
            return
        board.pause_post(job)

    thread = threading.Thread(target=worker)
    thread.start()
    assert saw_clear.wait(2)
    assert (
        board.enqueue(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 21, tzinfo=UTC)
        )
        is Enqueue.QUEUED
    )
    assert job.superseded and job.state is JobState.POSTING
    landed.set()
    thread.join(2)
    assert not thread.is_alive()
    assert job.state is JobState.SUPERSEDED
    loaded = Board(tmp_path / "queue.json")
    assert (SHA_A, JobState.SUPERSEDED) in loaded.states()


def test_a_supersede_during_pause_removes_the_run_directory(tmp_path, monkeypatch):
    """The worker reads ``superseded`` before ``pause_post``.

    A newer head in that window makes the Board store SUPERSEDED. The
    run directory has to be removed, and the supersede has to be logged.
    """
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    directory = run_dir(tmp_path, event)
    directory.mkdir(parents=True)
    (directory / "draft.md").write_text("the review\n", encoding="utf-8")
    (directory / "stderr.txt").write_text("plainchildsecretvalue\n", encoding="utf-8")
    board.enqueue(event, at=datetime(2026, 11, 12, 20, tzinfo=UTC))
    job = board.claim()
    assert job is not None
    assert board.begin_post(job) is True
    job.cancel.set()
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    real = board.pause_post

    def pause(claimed):
        assert (
            board.enqueue(
                PrEvent(REPO, 7, SHA_B),
                at=datetime(2026, 11, 12, 21, tzinfo=UTC),
            )
            is Enqueue.QUEUED
        )
        return real(claimed)

    monkeypatch.setattr(board, "pause_post", pause)
    worker._stopped_or_superseded(job, {"pr": 7, "sha12": SHA_A[:12], "repo": REPO})
    assert job.state is JobState.SUPERSEDED
    assert not directory.exists()
    assert any(
        record.step == "review superseded" for record in worker._telemetry.events
    )


def test_a_failed_pause_save_restores_a_superseded_post(tmp_path, monkeypatch):
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=datetime(2026, 11, 12, 20, tzinfo=UTC))
    job = board.claim()
    assert job is not None
    assert board.begin_post(job) is True
    job.cancel.set()
    assert (
        board.enqueue(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 21, tzinfo=UTC)
        )
        is Enqueue.QUEUED
    )
    assert job.state is JobState.POSTING
    assert job.superseded and job.cancel.is_set()

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError, match="disk"):
        board.pause_post(job)
    assert job.state is JobState.POSTING
    assert job.superseded
    assert job.cancel.is_set()


def test_releasing_a_superseded_claim_does_not_leave_it_queued(tmp_path):
    board = Board(tmp_path / "queue.json")
    moment = datetime(2026, 11, 12, 20, tzinfo=UTC)
    board.enqueue(PrEvent(REPO, 7, SHA_A), at=moment)
    job = board.claim()
    assert job is not None
    board.enqueue(PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 21, tzinfo=UTC))
    board.release_claim(job)
    assert (SHA_A, JobState.SUPERSEDED) in board.states()
    claimed = board.claim()
    assert claimed is not None
    assert claimed.event.head_sha == SHA_B


def test_a_superseded_running_job_reloads_as_superseded(tmp_path):
    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    job.superseded = True
    board._save()
    loaded = Board(tmp_path / "queue.json")
    assert loaded.states() == ((SHA_A, JobState.SUPERSEDED),)


def test_a_corrupt_queue_exits_2(tmp_path, capsys, monkeypatch):
    # Posting builds a publisher before it opens the queue. Stub that so
    # this test reaches the corrupt file.
    try:
        import atlas_reviewer.service_post as post_mod
    except ImportError:
        post_mod = None
    if post_mod is not None and hasattr(post_mod, "publisher_from_env"):

        class _Poster:
            def post(self, event, report):
                return None

            def credential_secrets(self):
                return ()

        monkeypatch.setattr(
            post_mod, "publisher_from_env", lambda *args, **kwargs: _Poster()
        )
    (tmp_path / "queue.json").write_text("{", encoding="utf-8")
    code = main(
        env={
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
            "ATLAS_SERVICE_PROVIDER": "offline",
            "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        }
    )
    assert code == 2
    assert "queue" in capsys.readouterr().err


def test_serve_scrubs_a_child_secret_from_the_log(tmp_path, monkeypatch):
    import atlas_reviewer.service as service_mod

    secret = "plainchildsecretvalue"
    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))

    def runner(event, cancel):
        return ReviewRun(False, error=f"child said {secret}")

    def serve_forever(self, poll_interval=0.5):
        path = tmp_path / "service.jsonl"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if path.is_file() and "review failed" in path.read_text(encoding="utf-8"):
                return
            time.sleep(0.02)

    monkeypatch.setattr(service_mod.ReviewServer, "serve_forever", serve_forever)
    config = ServiceConfig(
        secret=SECRET,
        allowlist=frozenset({REPO}),
        state_dir=tmp_path,
        host="127.0.0.1",
        port=0,
    )
    assert (
        serve(
            config,
            {"ATLAS_SPRITES_TOKEN": secret},
            runner=runner,
            log=lambda line: None,
            secret_sources=(lambda: (secret,),),
        )
        == 0
    )
    text = (tmp_path / "service.jsonl").read_text(encoding="utf-8")
    assert "review failed" in text
    assert secret not in text


def test_the_body_read_restores_the_handler_timeout(monkeypatch):
    import atlas_reviewer.service as service_mod

    monkeypatch.setattr(service_mod, "_BODY_BUDGET_S", 0.4)

    class Conn:
        def __init__(self) -> None:
            self.calls: list[float | None] = []
            self._timeout: float | None = 20.0

        def gettimeout(self) -> float | None:
            return self._timeout

        def settimeout(self, value: float | None) -> None:
            self._timeout = value
            self.calls.append(value)

    class Reader:
        def read1(self, _n: int) -> bytes:
            return b""

    handler = _Handler.__new__(_Handler)
    handler.rfile = Reader()
    handler.connection = Conn()
    handler.headers = {"Content-Length": "40"}
    sent: list[int] = []
    handler._send = lambda status, body: sent.append(status)  # type: ignore[method-assign]
    handler.server = type(
        "S",
        (),
        {
            "config": type("C", (), {"max_body_bytes": 1_000_000})(),
            "log": staticmethod(lambda line: None),
        },
    )()
    handler._read_post()
    assert sent == [408]
    assert handler.connection.calls
    assert min(c for c in handler.connection.calls if c is not None) < 1
    assert handler.connection.calls[-1] == 20.0


def test_the_body_read_restores_the_timeout_when_the_read_raises(monkeypatch):
    import atlas_reviewer.service as service_mod

    monkeypatch.setattr(service_mod, "_BODY_BUDGET_S", 0.4)

    class Conn:
        def __init__(self) -> None:
            self.calls: list[float | None] = []
            self._timeout: float | None = 20.0

        def gettimeout(self) -> float | None:
            return self._timeout

        def settimeout(self, value: float | None) -> None:
            self._timeout = value
            self.calls.append(value)

    class Reader:
        def read1(self, _n: int) -> bytes:
            raise OSError("reset")

    handler = _Handler.__new__(_Handler)
    handler.rfile = Reader()
    handler.connection = Conn()
    handler.headers = {"Content-Length": "40"}
    handler.server = type(
        "S",
        (),
        {
            "config": type("C", (), {"max_body_bytes": 1_000_000})(),
            "log": staticmethod(lambda line: None),
        },
    )()
    with pytest.raises(OSError, match="reset"):
        handler._read_post()
    assert handler.connection.calls
    assert handler.connection.calls[-1] == 20.0


def test_a_continuous_trickle_is_refused_before_the_body_ends(tmp_path, monkeypatch):
    """Bytes that keep arriving inside the socket timeout must still 408.

    ``BufferedReader.read`` would collect the whole body, because each
    byte lands before the timeout ``arm`` set once. ``read1`` returns
    after the bytes already buffered, so the deadline is checked again.
    """
    import atlas_reviewer.service as service_mod

    monkeypatch.setattr(service_mod, "_BODY_BUDGET_S", 0.4)
    board = Board(tmp_path / "queue.json")
    server = ReviewServer(_config(tmp_path), board, lambda line: None)
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    host, port = server.server_address
    sock = socket.create_connection((host, port), timeout=2)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        length = 20
        sock.sendall(
            b"POST /webhook HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 20\r\n"
            b"X-GitHub-Event: pull_request\r\n"
            b"\r\n"
        )
        sock.settimeout(0.05)
        started = time.monotonic()
        sent = 0
        data = b""
        while sent < length and b"408" not in data and time.monotonic() - started < 3:
            try:
                sock.sendall(b"x")
            except OSError:
                break
            sent += 1
            try:
                while True:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    data += chunk
            except TimeoutError:
                pass
            time.sleep(0.12)
        assert b"408" in data
        assert sent < length
        assert time.monotonic() - started < 2
    finally:
        sock.close()
        server.shutdown()
        listener.join(timeout=2)
        server.server_close()


def test_a_trickled_body_is_refused_on_the_socket(tmp_path, monkeypatch):
    import atlas_reviewer.service as service_mod

    monkeypatch.setattr(service_mod, "_BODY_BUDGET_S", 0.4)
    board = Board(tmp_path / "queue.json")
    server = ReviewServer(_config(tmp_path), board, lambda line: None)
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    host, port = server.server_address
    sock = socket.create_connection((host, port), timeout=2)
    try:
        sock.sendall(
            b"POST /webhook HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 8\r\n"
            b"X-GitHub-Event: pull_request\r\n"
            b"\r\nx"
        )
        started = time.monotonic()
        sock.settimeout(2)
        data = b""
        while b"\r\n\r\n" not in data and time.monotonic() - started < 1.5:
            try:
                chunk = sock.recv(1024)
            except TimeoutError:
                break
            if not chunk:
                break
            data += chunk
        assert b"408" in data
        assert time.monotonic() - started < 1.2
    finally:
        sock.close()
        server.shutdown()
        listener.join(timeout=2)
        server.server_close()


def test_the_module_entry_shares_the_poster_hook():
    """``python -m atlas_reviewer.service`` must use one module object.

    The worker sets ``before_send`` and catches the poster's exceptions.
    A second import of this file leaves the poster's hook unset and its
    exception classes unmatched.
    """
    root = Path(__file__).resolve().parents[2]
    script = """
import sys
from runpy import _run_module_as_main

import atlas_reviewer.service as canonical

def wrapped():
    import tempfile
    from pathlib import Path

    import atlas_reviewer.service_post as poster_mod
    from atlas_reviewer.clock import SystemClock
    from atlas_reviewer.domain import PrEvent
    from atlas_reviewer.http import HttpResponse
    from atlas_reviewer.service_queue import Board
    from atlas_reviewer.service_run import ReviewReport, ReviewRun, run_dir
    from atlas_reviewer.telemetry import Telemetry

    poster = poster_mod
    token = canonical.before_send.set(lambda: False)
    try:
        hook = poster.before_send.get()
        fired = hook is not None and hook() is False
        same = (
            poster.before_send is canonical.before_send
            and poster.PostNotCurrent is canonical.PostNotCurrent
            and poster.PostAuthError is canonical.PostAuthError
            and poster.PostRejected is canonical.PostRejected
            and poster.RateLimited is canonical.RateLimited
            and poster.PostHookMissing is canonical.PostHookMissing
        )
    finally:
        canonical.before_send.reset(token)
    root = Path(tempfile.mkdtemp())
    board = Board(root / "queue.json")
    event = PrEvent("brandondees/code-quality-atlas", 7, "d" * 40)
    directory = run_dir(root, event)
    calls = []

    class GitHub:
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            calls.append(method)
            if method == "GET":
                board.cancel_active()
                return HttpResponse(200, {}, b"[]")
            return HttpResponse(200, {}, b'{"id": 9}')

    class Tokens:
        def token(self):
            return "ghs_test"

    review_poster = poster.ReviewPoster(
        GitHub(),
        Tokens(),
        poster.PostLedger(root / "posted.json"),
        lambda text: text,
    )
    report = ReviewReport(("tracing",), (), "note", (), (), (), "COMMENT")

    def runner(_event, _cancel):
        directory.mkdir(parents=True)
        (directory / "draft.md").write_text("the review\\n", encoding="utf-8")
        return ReviewRun(True, report)

    worker = canonical.Worker(
        board, runner, Telemetry(SystemClock()), review_poster.post, state_root=root
    )
    board.enqueue(event)
    worker.run_one()
    posted = calls.count("POST")
    kept = (directory / "draft.md").is_file()
    print(f"fired={fired} same={same} posted={posted} kept={kept}")
    return 0 if fired and same and posted == 0 and kept else 1

canonical.main = wrapped

def capture(code=0):
    raise SystemExit(code)

sys.exit = capture
try:
    _run_module_as_main("atlas_reviewer.service")
except SystemExit as exc:
    raise SystemExit(exc.code)
"""
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("ATLAS_")
    }
    env["PYTHONPATH"] = str(root)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "fired=True same=True posted=0 kept=True" in proc.stdout


def test_the_module_refuses_to_start_without_a_secret():
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("ATLAS_")
    }
    proc = subprocess.run(
        [sys.executable, "-m", "atlas_reviewer.service"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 2
    assert b"webhook secret" in proc.stderr


def test_a_file_is_not_a_writable_state_dir(tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("x", encoding="utf-8")
    assert _state_is_writable(target) is False


def test_config_rejects_a_short_secret_and_reads_the_allowlist(tmp_path):
    with pytest.raises(ServiceError):
        ServiceConfig(secret="short", allowlist=frozenset({REPO}))
    config = config_from_env(
        {
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
            "ATLAS_REVIEW_REPOS": f"{REPO}, {OTHER}",
            "ATLAS_REVIEW_CONCURRENCY": "2",
            "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
            "ATLAS_SERVICE_PROVIDER": "offline",
        }
    )
    assert config.allowlist == frozenset({REPO, OTHER})
    assert config.concurrency == 2
    assert config.provider == "offline"
    assert config.state_dir == tmp_path
    with pytest.raises(ServiceError, match="live inference"):
        config_from_env(
            {
                "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
                "ATLAS_SERVICE_PROVIDER": "openrouter",
            }
        )
    with pytest.raises(ServiceError):
        config_from_env({})


def test_the_mode_defaults_to_agentic_and_an_unknown_mode_refuses_startup():
    base = {"ATLAS_GITHUB_WEBHOOK_SECRET": SECRET, "ATLAS_SERVICE_PROVIDER": "offline"}
    assert config_from_env(base).mode == "agentic"
    assert config_from_env({**base, "ATLAS_SERVICE_MODE": "oneshot"}).mode == "oneshot"
    with pytest.raises(ServiceError) as refused:
        config_from_env({**base, "ATLAS_SERVICE_MODE": "fast"})
    assert "ATLAS_SERVICE_MODE" in str(refused.value)
    with pytest.raises(ServiceError):
        ServiceConfig(
            secret=SECRET,
            allowlist=frozenset({REPO}),
            mode="fast",
        )


def test_the_review_deadline_is_read_and_bounded():
    base = {"ATLAS_GITHUB_WEBHOOK_SECRET": SECRET, "ATLAS_SERVICE_PROVIDER": "offline"}
    from atlas_reviewer.service_run import MAX_SERVICE_DEADLINE_S

    # The agentic default is the bound's ceiling: a backstop, not the
    # child's real limit (its derived wall is).
    assert config_from_env(base).deadline_s == MAX_SERVICE_DEADLINE_S
    oneshot = config_from_env({**base, "ATLAS_SERVICE_MODE": "oneshot"})
    assert oneshot.deadline_s == 1200.0
    long = config_from_env({**base, "ATLAS_SERVICE_DEADLINE_S": "7200"})
    assert long.deadline_s == 7200.0
    # In agentic mode a value below the child's configured wall refuses,
    # and so does an invalid child wall -- naming the variable.
    for raw in ("0", "30", "1200", "abc", "20000"):
        with pytest.raises(ServiceError):
            config_from_env({**base, "ATLAS_SERVICE_DEADLINE_S": raw})
    with pytest.raises(ServiceError):
        ServiceConfig(secret=SECRET, allowlist=frozenset({REPO}), deadline_s=10.0)


# --------------------------------------------------- keep or cancel (#702)

REPORT_COST = ReviewReport(
    ("tracing",),
    (),
    "note",
    (),
    (),
    ("Model calls: 12; settled: $3.40; held at reservation: $0.",),
    "COMMENT",
)


def _newer_body(sha: str, updated_at: str) -> bytes:
    return _body(sha=sha, updated_at=updated_at)


def _code_push(running: PrEvent, new: PrEvent):
    from atlas_reviewer.head_change import PushClass, PushKind

    return PushClass(PushKind.CODE, ("src/x.py",))


def _docs_push(running: PrEvent, new: PrEvent):
    from atlas_reviewer.head_change import PushClass, PushKind

    return PushClass(PushKind.DOCS_TESTS, ("docs/a.md",))


def test_a_push_mid_review_is_kept_and_queued_as_the_follow_up(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    seen: list[tuple[str, str]] = []

    def runner(event, cancel):
        seen.append((event.head_sha, event.delta_from))
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        # The classifier is None: an unclassifiable push keeps the
        # review, the owner's default. The response names the keep.
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        assert (REPO, 7, SHA_B) in board.pending_heads()
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (SHA_B, SHA_A) not in seen:
            time.sleep(0.01)
    finally:
        worker.stop()
    # Mutant: the pending head never materialized, or materialized
    # without its delta base -- either drops the follow-up review or
    # detaches it from the head it builds on.
    assert seen == [(SHA_A, ""), (SHA_B, SHA_A)]
    assert board.pending_heads() == ()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert [event.fields["decision"] for event in decisions] == ["keep"]


def test_an_early_code_push_cancels_the_running_review(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    seen: list[str] = []

    def runner(event, cancel):
        seen.append(event.head_sha)
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=_code_push,
                telemetry=telemetry,
            ).body
            == b"queued\n"
        )
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and seen != [SHA_A, SHA_B]:
            time.sleep(0.01)
    finally:
        worker.stop()
    # Mutant: the cancel branch dropped (or the classifier ignored), so
    # a push that changes code under review never restarts early.
    assert seen == [SHA_A, SHA_B]
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields["decision"] == "cancel"
    assert decisions[0].fields["kind"] == "code"
    # No progress events exist, so the fractions read as early.
    assert decisions[0].fields["lens_fraction"] == "0.00"


def test_a_docs_push_is_kept_without_any_progress(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=_docs_push,
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        release.set()
    finally:
        worker.stop()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields["decision"] == "keep"
    assert decisions[0].fields["kind"] == "docs or tests only"


def test_a_classification_failure_keeps_the_review_and_records_the_gap(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    def broken(running: PrEvent, new: PrEvent):
        raise RuntimeError("github unreachable")

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=broken,
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        release.set()
    finally:
        worker.stop()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert len(decisions) == 1
    assert decisions[0].fields["decision"] == "keep"
    assert decisions[0].status == "error"
    assert "RuntimeError" in decisions[0].error


def test_a_posting_review_is_never_cancelled(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.QUEUED
    claimed = board.claim()
    assert claimed is not None
    assert board.begin_post(claimed) is True
    telemetry = Telemetry(SystemClock())
    result = _deliver(
        config,
        board,
        _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
        classifier=_code_push,
        telemetry=telemetry,
    )
    assert result.body == b"kept\n"
    # Mutant: a posting review treated like an early one, which would
    # cancel a review whose spend is fully spent.
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields["decision"] == "keep"
    assert "posting" in decisions[0].fields["reason"]


def test_a_redelivery_of_the_pending_head_is_a_duplicate(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    assert board.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.QUEUED
    claimed = board.claim()
    assert claimed is not None
    assert (
        _deliver(config, board, _newer_body(SHA_B, "2026-11-12T20:00:00Z")).body
        == b"kept\n"
    )
    again = _deliver(config, board, _newer_body(SHA_B, "2026-11-12T20:00:00Z"))
    assert again.body == b"duplicate\n"
    older = _deliver(config, board, _newer_body(SHA_C, "2026-11-12T19:30:00Z"))
    assert older.body == b"stale\n"
    assert (REPO, 7, SHA_B) in board.pending_heads()


def test_a_newer_push_while_a_delta_is_queued_inherits_its_delta_from(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    seen: list[tuple[str, str]] = []

    def runner(event, cancel):
        seen.append((event.head_sha, event.delta_from))
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)

    assert (
        _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
        == b"queued\n"
    )
    runner_thread = threading.Thread(target=worker.run_one)
    runner_thread.start()
    try:
        assert started.wait(2)
        assert (
            _deliver(config, board, _newer_body(SHA_B, "2026-11-12T20:00:00Z")).body
            == b"kept\n"
        )
        release.set()
        runner_thread.join(2)
        # A settled; its pending head B is queued as the follow-up, and
        # the worker is not looping, so B stays queued for this push.
        assert board.pending_heads() == ()
        assert (
            _deliver(config, board, _newer_body(SHA_C, "2026-11-12T21:00:00Z")).body
            == b"queued\n"
        )
        # Mutant: the superseded queued follow-up's delta base dropped,
        # so the replacement review would build on nothing and re-review
        # the whole pull request.
        assert worker.run_one() is True
    finally:
        release.set()
        runner_thread.join(2)
    assert seen == [(SHA_A, ""), (SHA_C, SHA_A)]


def test_a_kept_head_is_materialized_as_a_full_review_when_the_review_fails(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    seen: list[tuple[str, str]] = []

    def runner(event, cancel):
        seen.append((event.head_sha, event.delta_from))
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
            return ReviewRun(False, error="boom")
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(config, board, _newer_body(SHA_B, "2026-11-12T20:00:00Z")).body
            == b"kept\n"
        )
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (SHA_B, "") not in seen:
            time.sleep(0.01)
    finally:
        worker.stop()
    # Mutant: the failed review materialized a delta review anyway,
    # building on a review that never posted.
    assert seen == [(SHA_A, ""), (SHA_B, "")]


def test_the_pending_head_survives_a_restart(tmp_path):
    path = tmp_path / "queue.json"
    board = Board(path)
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(5)
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(config, board, _newer_body(SHA_B, "2026-11-12T20:00:00Z")).body
            == b"kept\n"
        )
    finally:
        # A stop cancels the running review without settling it: it
        # returns to queued, and the pending head stays recorded.
        worker.stop()
        release.set()
    reloaded = Board(path)
    assert (REPO, 7, SHA_B) in reloaded.pending_heads()
    # The reloaded review runs to completion, and the pending head
    # materializes with its delta base from the reloaded board.
    seen: list[tuple[str, str]] = []

    def rerun(event, cancel):
        seen.append((event.head_sha, event.delta_from))
        return ReviewRun(True, REPORT)

    worker2 = _worker(reloaded, rerun, root=tmp_path)
    assert worker2.run_one() is True
    assert worker2.run_one() is True
    assert worker2.run_one() is False
    assert seen == [(SHA_A, ""), (SHA_B, SHA_A)]


def test_the_cancel_policy_restores_the_blanket_supersede(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = ServiceConfig(
        secret=SECRET,
        allowlist=frozenset({REPO}),
        state_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        head_change_policy="cancel",
    )
    started = threading.Event()
    release = threading.Event()
    cancelled: list[bool] = []

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
            cancelled.append(cancel.is_set())
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(config, board, _newer_body(SHA_B, "2026-11-12T20:00:00Z")).body
            == b"queued\n"
        )
        release.set()
    finally:
        worker.stop()
    assert cancelled == [True]
    assert board.pending_heads() == ()


def test_a_progress_record_lets_a_late_code_push_keep_the_review(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            # The child's events file, as the coordinator's progress
            # records land in it: three of the four planned lenses have
            # settled, most of the budget spent, nothing left reading
            # but a file the push never touches.
            run = run_dir(tmp_path, event)
            run.mkdir(parents=True, exist_ok=True)
            lines = [
                json.dumps(
                    {
                        "seq": index,
                        "phase": "progress",
                        "step": "lens settled",
                        "status": "ok",
                        "lens": lens,
                        "lenses_done": index,
                        "lenses_total": 4,
                        "calls": 3 * index,
                        "settled_usd": str(2 * index),
                        "reservation_usd": "10",
                        "reading": "src/untouched.py",
                    }
                )
                for index, lens in enumerate(("tracing", "security", "hygiene"), 1)
            ]
            (run / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=_code_push,
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        release.set()
    finally:
        worker.stop()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    # Mutant: the progress read dropped, so the decision cancels on the
    # zero-progress default instead of reading the review's real state.
    assert decisions[0].fields["decision"] == "keep"
    assert decisions[0].fields["lens_fraction"] == "0.75"


def test_a_finished_review_logs_its_cost(tmp_path):
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT_COST),
        root=tmp_path,
        telemetry=telemetry,
    )
    _deliver(_config(tmp_path), board, _body())
    assert worker.run_one() is True
    costs = [e for e in telemetry.events if e.step == "review cost"]
    # Mutant: the cost logging dropped, which loses the measure-first
    # numbers the decision's tuning reads.
    assert costs[0].fields["calls"] == 12
    assert costs[0].fields["billed_usd"] == "3.40"
    assert costs[0].fields["held_usd"] == "0"
    assert costs[0].fields["committed_usd"] == "3.40"
    assert costs[0].fields["measured"] == "final"


def test_a_cancelled_review_logs_the_cost_its_progress_recorded(tmp_path):
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            run = run_dir(tmp_path, event)
            run.mkdir(parents=True, exist_ok=True)
            (run / "events.jsonl").write_text(
                json.dumps(
                    {
                        "seq": 1,
                        "phase": "progress",
                        "step": "lens settled",
                        "status": "ok",
                        "lens": "tracing",
                        "lenses_done": 1,
                        "lenses_total": 4,
                        "calls": 3,
                        "settled_usd": "1.10",
                        "committed_usd": "2.20",
                        "reservation_usd": "10",
                        "reading": "src/x.py",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=_code_push,
                telemetry=telemetry,
            ).body
            == b"queued\n"
        )
        release.set()
    finally:
        worker.stop()
    costs = [e for e in telemetry.events if e.step == "review cost"]
    # Mutant: the cost event read after the run directory was dropped,
    # which would log every cancelled review as unknown.
    assert costs[0].fields["calls"] == 3
    assert costs[0].fields["measured"] == "partial"
    # committed_usd stays the ceiling figure ($2.20, in-flight included).
    # billed_usd is the settled bill ($1.10). Kills writing the bill into
    # the committed field (round-1 review of #799).
    assert costs[0].fields["committed_usd"] == "2.20"
    assert costs[0].fields["billed_usd"] == "1.10"
    assert costs[0].fields["settled_usd"] == "1.10"


def test_a_review_whose_cost_is_nowhere_is_logged_as_unknown(tmp_path):
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        root=tmp_path,
        telemetry=telemetry,
    )
    _deliver(_config(tmp_path), board, _body())
    assert worker.run_one() is True
    costs = [e for e in telemetry.events if e.step == "review cost"]
    assert costs[0].fields["measured"] == "unknown"


def test_the_head_change_settings_are_validated_at_boot():
    base = {"ATLAS_GITHUB_WEBHOOK_SECRET": SECRET, "ATLAS_SERVICE_PROVIDER": "offline"}
    defaults = config_from_env(base)
    assert defaults.head_change_policy == "keep"
    assert defaults.cancel_fraction == 0.5
    assert (
        config_from_env(
            {**base, "ATLAS_HEAD_CHANGE_POLICY": "cancel"}
        ).head_change_policy
        == "cancel"
    )
    assert (
        config_from_env(
            {**base, "ATLAS_HEAD_CHANGE_CANCEL_FRACTION": "0.25"}
        ).cancel_fraction
        == 0.25
    )
    with pytest.raises(ServiceError):
        config_from_env({**base, "ATLAS_HEAD_CHANGE_POLICY": "maybe"})
    for raw in ("1.5", "-0.1", "half"):
        with pytest.raises(ServiceError):
            config_from_env({**base, "ATLAS_HEAD_CHANGE_CANCEL_FRACTION": raw})


# ------------------------------------------------- round-1 fixes (#747)


def test_a_kept_head_with_no_running_review_is_installed_not_dropped(tmp_path):
    """The race branch (round-1 F2): the review settled between
    `head_change_candidate` and `keep_head` -- up to three GitHub reads
    later -- and `keep_head` must install the head under the same lock,
    because a 202 `queued` is an acknowledgment GitHub will not
    redeliver. Mutant: the branch answers QUEUED and installs nothing,
    which drops the pushed head permanently."""
    board = Board(tmp_path / "queue.json")
    result = board.keep_head(
        PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
    )
    assert result is Enqueue.QUEUED
    # The head is a real queued job now, not a lost acknowledgment.
    assert (SHA_B, JobState.QUEUED) in board.states()
    job = board.claim()
    assert job is not None
    assert job.event.head_sha == SHA_B
    # A full review, with no delta base to build on, and no pending
    # record left behind.
    assert job.event.delta_from == ""
    assert board.pending_heads() == ()


def test_a_delivery_through_the_race_path_queues_the_new_head(tmp_path):
    """The same race through `handle_delivery`: nothing running, so the
    keep decision's keep path installs and answers queued -- the head
    the next worker claims is the pushed one."""
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    result = _deliver(
        config, board, _body(sha=SHA_B, updated_at="2026-11-12T20:00:00Z")
    )
    assert result.body == b"queued\n"
    assert (SHA_B, JobState.QUEUED) in board.states()


def test_a_no_classifier_decision_records_the_gap_with_an_error_status(tmp_path):
    """A deployment with no classifier (round-1 F3) keeps every push --
    the owner's default -- but the decision event carries the gap with
    an error status, so the lost cancel branch is visible in the
    telemetry instead of reading as a normal keep. Mutant: the gap
    dropped (status ok, no gap), which is the defect."""
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        release.set()
    finally:
        worker.stop()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields["decision"] == "keep"
    assert decisions[0].status == "error"
    assert "no head-change classifier" in decisions[0].error
    # The decision's own duration is on the event (round-1 F8).
    assert decisions[0].duration_s >= 0.0


def test_a_timing_out_classification_is_marked_on_the_event(tmp_path):
    """A classification that runs past its transport timeout is recorded
    with the `timed_out` flag, so GitHub-side delivery failures
    correlate with classifications (round-1 F8)."""
    from atlas_reviewer.ports import TransportTimeoutError

    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    def slow(running: PrEvent, new: PrEvent):
        raise TransportTimeoutError("the compare read timed out")

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=slow,
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        release.set()
    finally:
        worker.stop()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields.get("timed_out") == "1"
    assert decisions[0].status == "error"


def test_a_stranded_pending_head_is_recovered_at_boot(tmp_path):
    """The crash window (round-1 F7): a kept head whose review finished
    and whose materialization never ran -- the process died, or the
    save failed -- is queued by `recover_pending`, as an ordinary review
    (what it should have built on is not knowable there). Mutant: the
    recovery dropped, which leaves the head stranded forever, with its
    redelivery answered duplicate."""
    path = tmp_path / "queue.json"
    board = Board(path)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )
    board.finish(job, JobState.DONE)
    # The materialization never ran (the crash window): the pending head
    # is stranded, and its PR has no active job.
    assert (REPO, 7, SHA_B) in board.pending_heads()
    reloaded = Board(path)
    recovered = reloaded.recover_pending()
    assert [(event.head_sha, event.delta_from) for event in recovered] == [(SHA_B, "")]
    assert (SHA_B, JobState.QUEUED) in reloaded.states()
    assert reloaded.pending_heads() == ()
    # A worker claims and runs it.
    worker = _worker(
        reloaded, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    assert worker.run_one() is True


def test_a_pending_head_on_a_full_queue_waits_for_the_recovery(tmp_path):
    """`take_pending` does not append past the queue's cap (round-1
    F13): the finished job's freed slot can be taken by another thread's
    enqueue in between, so a full queue leaves the pending head recorded
    for the recovery to retry when there is room."""
    path = tmp_path / "queue.json"
    board = Board(path, max_remembered=2)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )
    # While the review runs, another PR's job fills the second slot.
    assert board.enqueue(PrEvent(OTHER, 8, SHA_B)) is Enqueue.QUEUED
    assert board.finish(job, JobState.DONE) is JobState.DONE
    # Another enqueue takes the slot the settled job freed, before the
    # materialization runs -- the interleaving the cap check exists for.
    assert board.enqueue(PrEvent(OTHER, 9, SHA_C)) is Enqueue.QUEUED
    assert board.take_pending(PrEvent(REPO, 7, SHA_A), succeeded=True) is None
    assert (REPO, 7, SHA_B) in board.pending_heads()
    # The worker's own idle pass retries it once there is room: the
    # second pass's recovery installs B while the queue is under the cap.
    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), root=tmp_path
    )
    assert (
        worker.run_one() is True
    )  # runs one OTHER job; the recovery is still capped out
    assert (REPO, 7, SHA_B) in board.pending_heads()
    assert worker.run_one() is True  # runs the other; the recovery installs B
    assert (REPO, 7, SHA_B) not in board.pending_heads()
    assert (SHA_B, JobState.QUEUED) in board.states()


def test_the_worker_loop_recovers_a_stranded_pending_head(tmp_path):
    """The idle recovery (round-1 F7): a worker pass finds the stranded
    pending head and queues it, with the follow-up telemetry naming it."""
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    telemetry = Telemetry(SystemClock())
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, REPORT),
        root=tmp_path,
        telemetry=telemetry,
    )
    assert (
        _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
        == b"queued\n"
    )
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )
    board.finish(job, JobState.DONE)
    # One worker pass: the recovery installs the stranded head, and the
    # same pass claims and runs it.
    assert worker.run_one() is True
    assert (REPO, 7, SHA_B) not in board.pending_heads()
    assert (SHA_B, JobState.DONE) in board.states()
    queued = [e for e in telemetry.events if e.step == "follow-up queued"]
    assert [e.fields["sha12"] for e in queued] == [SHA_B[:12]]


def test_a_stale_pending_head_is_dropped_not_installed_by_the_recovery(tmp_path):
    """The recovery's stale window (round-2 R2-F4): a pending head the
    pull request has moved past must not be installed -- it would
    review, and post for, a head that is no longer the PR's head
    (`still_current` compares nothing against the accepted heads). The
    recovery drops the stale record, the way `take_pending` drops one.
    The state is built directly -- a pending entry outliving its head is
    the crash/recovery shape the check exists for. Mutant: the check
    dropped, which installs the stale head."""
    path = tmp_path / "queue.json"
    stamp = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
    path.write_text(
        json.dumps(
            {
                "jobs": [],
                "seen": [],
                "heads": [
                    {"repo": REPO, "pr": 7, "sha": SHA_C, "at": stamp.isoformat()}
                ],
                "pending": [
                    {"repo": REPO, "pr": 7, "sha": SHA_B, "at": stamp.isoformat()}
                ],
            }
        ),
        encoding="utf-8",
    )
    board = Board(path)
    assert (REPO, 7, SHA_B) in board.pending_heads()
    # Mutant target: B installed (and eventually posted) though C is the
    # pull request's head.
    assert board.recover_pending() == ()
    assert board.pending_heads() == ()
    assert board.states() == ()


def test_a_classification_past_its_budget_is_unclassifiable_and_flagged(
    tmp_path, monkeypatch
):
    """The classification's overall budget (round-2 R2-F8): a fetch that
    runs past `_READ_BUDGET_S` is given up on inside the webhook
    handler -- the push is unclassifiable (the owner's keep default),
    the gap names the budget, and the `timed_out` flag is on -- so the
    handler's occupancy is bounded. Mutant: the budget wait removed
    (the handler blocks on the classifier), which hangs this test's
    slow classifier past the budget."""
    import atlas_reviewer.service as service_module

    # Read the shipped budget before the monkeypatch is active (round-3
    # R3-F4): the final assertion must judge the constant that ships,
    # not the patched 0.2 s this test installs.
    shipped_budget = service_module._READ_BUDGET_S
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    def slow(running: PrEvent, new: PrEvent):
        release.wait(30)
        return _code_push(running, new)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    monkeypatch.setattr(service_module, "_READ_BUDGET_S", 0.2)
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        result = _deliver(
            config,
            board,
            _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
            classifier=slow,
            telemetry=telemetry,
        )
        # The past-budget classification is the keep default, flagged.
        assert result.body == b"kept\n"
        decisions = [e for e in telemetry.events if e.step == "head change"]
        assert decisions[0].fields["decision"] == "keep"
        assert decisions[0].fields.get("timed_out") == "1"
        assert "budget" in decisions[0].error
        # The gap names the classification, the text the pre-generalization
        # helper carried (round-1 review of #756, Nit 6).
        assert decisions[0].error.startswith("the classification exceeded")
    finally:
        release.set()
        worker.stop()
    # The bounded budget is the shipped constant, read before this
    # test's monkeypatch was active, small enough to sit inside
    # GitHub's response window.
    assert shipped_budget <= 10.0


def test_the_decision_duration_pin_uses_a_clock_that_advances(tmp_path):
    """The duration pin made real (round-2 R2-F11): the classification
    consumes clock time, so a recorded `start_s` yields the decision's
    own duration, while a dropped `start_s` (the mutant) measures from
    the record's own moment and reads about zero. The decision here is
    the classifier's code push with no progress recorded, so it cancels
    -- and the event's duration is what is pinned."""
    from atlas_reviewer.tests.helpers import FakeClock

    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    clock = FakeClock()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(clock, scrub=lambda text: text)
    clock.advance(100.0)

    def slow_clock(running: PrEvent, new: PrEvent):
        # The classification consumes clock time: the recorded duration
        # is the decision's own only when `start_s` names when it began.
        clock.advance(50.0)
        return _code_push(running, new)

    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                classifier=slow_clock,
                telemetry=telemetry,
            ).body
            == b"queued\n"
        )
        release.set()
    finally:
        worker.stop()
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields["decision"] == "cancel"
    # Mutant: `start_s` dropped -- the duration then reads from the
    # record's own moment (about zero), not the decision's 50 advanced
    # seconds.
    assert decisions[0].duration_s >= 40.0


# ------------------------------------------------- round-3 fixes (#747)


def test_a_failed_save_rolls_back_keep_head(tmp_path, monkeypatch):
    """The keep path's rollback (round-3 R3-F2): a failed save inside
    `keep_head` puts the pending record, the head pointer and any
    touched job's flags back, the way the enqueue/finish/begin-post
    rollback does. Mutant: the rollback dropped, which leaves a pending
    head recorded for a push the queue never acknowledged."""
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError, match="disk"):
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
    assert board.states() == ((SHA_A, JobState.RUNNING),)
    assert board.pending_heads() == ()
    assert job.superseded is False
    assert job.cancel.is_set() is False


def test_a_failed_save_rolls_back_settle(tmp_path, monkeypatch):
    """The settle rollback (round-3 R3-F2): a failed save inside
    `settle` puts the job's terminal state, the installed follow-up and
    the pending record back together -- the one-save atomicity the
    two-step path could not give, which this failing save is also what
    pins structurally (round-3 R3-F10). Mutant: the rollback dropped,
    which leaves a queued follow-up whose review never settled."""
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError, match="disk"):
        board.settle(job, JobState.DONE)
    assert job.state is JobState.RUNNING
    assert board.states() == ((SHA_A, JobState.RUNNING),)
    assert (REPO, 7, SHA_B) in board.pending_heads()


def test_a_failed_save_rolls_back_the_recovery(tmp_path, monkeypatch):
    """The recovery's rollback (round-3 R3-F2): a failed save inside
    `recover_pending` pops the job it appended and puts the pending
    record back, so a stranded head stays recorded for the next pass
    instead of half-installed in memory while absent from the queue
    file. Mutant: the rollback dropped, which leaves the appended job
    and the lost pending entry."""
    import atlas_reviewer.service_queue as queue_mod

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )
    board.finish(job, JobState.DONE)
    assert (REPO, 7, SHA_B) in board.pending_heads()

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(queue_mod, "_store", boom)
    with pytest.raises(OSError, match="disk"):
        board.recover_pending()
    assert board.states() == ((SHA_A, JobState.DONE),)
    assert (REPO, 7, SHA_B) in board.pending_heads()


def test_a_queued_delta_job_survives_a_queue_file_reload_with_its_delta_base(
    tmp_path,
):
    """The wire path (round-3 R3-F3): a queued delta job's `delta_from`
    survives the queue-file save and reload -- a dropped field in
    `as_dict` or in the reload parser would strand the delta base
    silently across a restart. Mutant: the field dropped from the
    record."""
    path = tmp_path / "queue.json"
    board = Board(path)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )
    committed, follow_up = board.settle(job, JobState.DONE)
    assert committed is JobState.DONE
    assert follow_up is not None
    assert follow_up.head_sha == SHA_B
    reloaded = Board(path)
    requeued = reloaded.claim()
    assert requeued is not None
    assert requeued.event.head_sha == SHA_B
    assert requeued.event.delta_from == SHA_A


def test_the_childs_event_file_carries_the_delta_base_round_trip(tmp_path):
    """The wire path (round-3 R3-F3): the run child's event file carries
    `delta_from` and `load_event` reads it back; a malformed value is
    refused rather than silently dropped."""
    from atlas_reviewer.cli import UsageError, load_event
    from atlas_reviewer.service_run import _write_event

    path = tmp_path / "event.json"
    _write_event(path, PrEvent(REPO, 7, SHA_B, delta_from=SHA_A))
    assert load_event(path).delta_from == SHA_A
    path.write_text(
        json.dumps(
            {"repo": REPO, "pr_number": 7, "head_sha": SHA_B, "delta_from": "abc"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(UsageError, match="invalid event"):
        load_event(path)


def test_a_candidate_that_crosses_into_posting_during_the_window_is_kept(
    tmp_path,
):
    """The posting snapshot re-check (round-3 R3-F5): the snapshot is
    read before the <=8s classification window; a review that crosses
    into posting during it is decided on the re-read state, so the
    recorded verdict and the action the caller takes agree. Mutant: the
    re-check dropped -- the stale snapshot decides, and a code push
    against a review that is already posting its comment cancels."""
    from atlas_reviewer.service import _head_change_decision

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    telemetry = Telemetry(SystemClock())

    def late_posting(running: PrEvent, new: PrEvent):
        # The review's lens loop ended and it began posting while the
        # classification ran.
        job.state = JobState.POSTING
        return _code_push(running, new)

    verdict = _head_change_decision(
        job,
        PrEvent(REPO, 7, SHA_B),
        _config(tmp_path),
        late_posting,
        telemetry,
    )
    assert verdict.cancel is False
    assert verdict.reason == "the review was already posting its comment"
    decisions = [e for e in telemetry.events if e.step == "head change"]
    assert decisions[0].fields["decision"] == "keep"


# ------------------------------------------------- round-5 fixes (#748)


def test_an_incomplete_reviews_follow_up_queues_as_a_full_review(tmp_path):
    """The follow-up's shape (round-5 review of #748, Major 1): a
    finished review whose coverage was incomplete cannot stand in for
    the files it never read, so the kept head queues as an ordinary
    full review of the pull request, not as a delta on top of it -- the
    delta's narrowing would leave exactly those files to no review at
    all. Mutant: the covered flag dropped from settle, which queues a
    delta over an unread base."""
    path = tmp_path / "queue.json"
    board = Board(path)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    job = board.claim()
    assert job is not None
    assert (
        board.keep_head(
            PrEvent(REPO, 7, SHA_B), at=datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
        )
        is Enqueue.KEPT
    )
    committed, follow_up = board.settle(job, JobState.DONE, covered=False)
    assert committed is JobState.DONE
    assert follow_up is not None
    # Mutant target: a delta base on top of an unread review.
    assert follow_up.delta_from == ""
    reloaded = Board(path)
    requeued = reloaded.claim()
    assert requeued is not None
    assert requeued.event.head_sha == SHA_B
    assert requeued.event.delta_from == ""


def test_the_worker_keys_the_followup_on_the_reports_coverage(tmp_path):
    """The worker passes its report's coverage flag into the settle
    (round-5 review of #748, Major 1): an incomplete report's follow-up
    runs as an ordinary review, with no delta base on the event. Mutant:
    the flag not threaded from the report, which queues the follow-up
    as a delta."""
    from dataclasses import replace

    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    seen: list[tuple[str, str]] = []
    incomplete = replace(REPORT, coverage_complete=False)

    def runner(event, cancel):
        seen.append((event.head_sha, event.delta_from))
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, incomplete)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert (
            _deliver(config, board, _body(updated_at="2026-11-12T19:00:00Z")).body
            == b"queued\n"
        )
        assert started.wait(2)
        assert (
            _deliver(
                config,
                board,
                _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
                telemetry=telemetry,
            ).body
            == b"kept\n"
        )
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and len(seen) < 2:
            time.sleep(0.01)
    finally:
        worker.stop()
    # Mutant target: the follow-up ran as a delta on the unread base.
    assert seen == [(SHA_A, ""), (SHA_B, "")]
    queued = [e for e in telemetry.events if e.step == "follow-up queued"]
    assert [e.fields["sha12"] for e in queued] == [SHA_B[:12]]
    assert all("delta_from" not in e.fields for e in queued)


# ------------------------------------------------------------------
# The repo's own narrowing (config slice S4): the base-ref REVIEW.md
# narrows what the operator's envelope already admits, and can never
# widen it. A skipped delivery is logged with its reason and never
# queued or posted; a read that fails stands on the operator's envelope.


def _labeled_body(
    *labels, base_ref="main", action="opened", sha=SHA_A, default_branch="trunk"
):
    pull = {
        "number": 7,
        "updated_at": "2026-11-12T20:00:00Z",
        "draft": False,
        "head": {"sha": sha},
        "base": {"ref": base_ref, "repo": {"full_name": REPO}},
        "labels": [{"name": label} for label in labels],
    }
    repository = {"full_name": REPO}
    if default_branch:
        repository["default_branch"] = default_branch
    return json.dumps(
        {
            "action": action,
            # The default branch differs from the base ref the fixtures
            # deliver, so a read of the base ref cannot pass for a read
            # of the default branch (round-1 review of #756, Major 1).
            "repository": repository,
            "pull_request": pull,
        }
    ).encode()


def _admission_reader(text, seen=None):
    def read(repo: str, ref: str):
        if seen is not None:
            seen.append((repo, ref))
        return None if text is None else text.encode()

    return read


def test_a_repo_skip_event_is_ignored_and_logged_not_queued(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    seen: list[tuple[str, str]] = []
    reader = _admission_reader("review_skip_events: synchronize\n", seen)
    result = _deliver(
        config,
        board,
        _labeled_body(action="synchronize"),
        admission_reader=reader,
        telemetry=telemetry,
    )
    assert result.status == 202
    assert result.body == b"ignored\n"
    assert result.detail == "ignored:repo-skip-event"
    assert board.states() == ()
    # The config is read from the repository's default branch, never the
    # PR head and never the PR's own base branch.
    assert seen == [(REPO, "trunk")]
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert [e.fields["reason"] for e in skips] == ["repo-skip-event"]
    assert [e.fields["pr"] for e in skips] == [7]
    # The other accepted events still queue under the same config.
    queued = _deliver(config, board, _labeled_body(), admission_reader=reader)
    assert queued.body == b"queued\n"
    assert len(board.states()) == 1


def test_the_config_is_read_from_the_default_branch_not_the_base_ref(tmp_path):
    """Major 1 (round-1 review of #756): a same-repo PR's author controls
    its base branch, so reading the config from it would let the author
    opt their own PR out of review. The delivery's base ref here differs
    from the repository's default branch, so a mutant that reads the
    base ref dies on the pin."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    seen: list[tuple[str, str]] = []
    reader = _admission_reader("review_base_include: main\n", seen)
    result = _deliver(
        config,
        board,
        _labeled_body(base_ref="feature/x"),
        admission_reader=reader,
    )
    assert seen == [(REPO, "trunk")]
    assert result.detail == "ignored:repo-base-branch"
    assert board.states() == ()


def test_a_label_rule_cannot_narrow_and_the_envelope_stands(tmp_path):
    """The label filters are deliberately absent (the plan-review scope
    change): the PR author can set labels, so a skip rule on them would
    let an author opt their own PR out of review. A label line is not an
    admission key -- the delivery is queued either way."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    result = _deliver(
        config,
        board,
        _labeled_body("wip"),
        admission_reader=_admission_reader(
            "review_required_labels: priority\nreview_skip_labels: wip\n"
        ),
    )
    assert result.body == b"queued\n"
    assert len(board.states()) == 1


def test_a_base_branch_outside_the_include_list_is_skipped(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    reader = _admission_reader("review_base_include: main, release*\n")
    outside = _deliver(
        config, board, _labeled_body(base_ref="feature/x"), admission_reader=reader
    )
    assert outside.detail == "ignored:repo-base-branch"
    assert board.states() == ()
    prefix = _deliver(
        config, board, _labeled_body(base_ref="release-1"), admission_reader=reader
    )
    assert prefix.body == b"queued\n"


def test_no_review_md_on_the_base_ref_leaves_the_envelope_standing(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    result = _deliver(
        config,
        board,
        _labeled_body(),
        admission_reader=_admission_reader(None),
        telemetry=telemetry,
    )
    assert result.body == b"queued\n"
    assert len(board.states()) == 1
    assert [e for e in telemetry.events if e.step == "repo admission"] == []


def test_a_failed_admission_read_is_a_recorded_gap_and_not_a_skip(tmp_path):
    """Mutant: a read failure that skipped instead of standing on the
    operator's envelope would empty the board here; the gap is recorded
    so the lost read is visible, not silent."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())

    def broken(repo: str, ref: str) -> bytes:
        raise RuntimeError("the read failed")

    result = _deliver(
        config,
        board,
        _labeled_body(),
        admission_reader=broken,
        telemetry=telemetry,
    )
    assert result.body == b"queued\n"
    assert len(board.states()) == 1
    gaps = [e for e in telemetry.events if e.step == "repo admission"]
    assert len(gaps) == 1
    assert gaps[0].status == "error"
    assert "RuntimeError" in gaps[0].error


def test_an_unusable_admission_line_is_named_and_narrows_nothing(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    result = _deliver(
        config,
        board,
        _labeled_body(),
        admission_reader=_admission_reader("review_base_include:\n"),
        telemetry=telemetry,
    )
    assert result.body == b"queued\n"
    assert len(board.states()) == 1
    notes = [e for e in telemetry.events if e.step == "repo admission"]
    assert len(notes) == 1
    assert notes[0].status == "error"
    assert "review_base_include" in notes[0].error
    assert "ignored" in notes[0].error


def test_the_admission_reader_needs_the_app_credentials(tmp_path):
    import atlas_reviewer.service as service_module

    config = _config(tmp_path)
    reader, reason = service_module._repo_admission_reader(config, {})
    assert reader is None
    assert "ATLAS_GITHUB_APP_ID" in reason


def test_the_admission_reader_reads_one_bounded_file(tmp_path, monkeypatch):
    import atlas_reviewer.service as service_module
    from atlas_reviewer.ports import NotFoundError
    from atlas_reviewer.service_admit import MAX_ADMISSION_BYTES, REVIEW_MD

    calls: list[tuple[str, str, str, int]] = []

    class _Client:
        def __init__(self, result):
            self.result = result

        def get_file(self, repo, ref, path, max_bytes):
            calls.append((repo, ref, path, max_bytes))
            if self.result is None:
                raise NotFoundError("GitHub 404")
            return self.result

    for missing, expected in ((b"config", b"config"), (None, None)):
        client = _Client(missing)
        monkeypatch.setattr(
            service_module, "_read_client", lambda config, env, c=client: (c, "")
        )
        reader, reason = service_module._repo_admission_reader(_config(tmp_path), {})
        assert reason == ""
        # The file is the default-branch REVIEW.md under the shipped read bound.
        assert reader("o/r", "main") is expected
        assert calls[-1] == ("o/r", "main", REVIEW_MD, MAX_ADMISSION_BYTES)
        assert calls[-1][3] == 64 * 1024


def test_the_admission_reader_recovers_an_unnamed_default_branch(tmp_path, monkeypatch):
    """Major 1's fallback (round-1 review of #756): a payload shape that
    does not carry the default branch is recovered with one read-only
    lookup. A lookup that fails -- a 404 or a reply without a usable
    name -- is the recorded gap, not a guess and not a silent
    stand-down (round-2 nit on #756)."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.ports import BoundaryError, NotFoundError
    from atlas_reviewer.service_admit import MAX_ADMISSION_BYTES, REVIEW_MD

    calls: list[tuple[object, ...]] = []

    class _Client:
        def __init__(self, repo_json, file_result=b"config"):
            self.repo_json = repo_json
            self.file_result = file_result

        def get_repository(self, repo):
            calls.append(("repo", repo))
            if self.repo_json is None:
                raise NotFoundError("GitHub 404")
            return self.repo_json

        def get_file(self, repo, ref, path, max_bytes):
            calls.append(("file", repo, ref, path, max_bytes))
            return self.file_result

    found = _Client({"default_branch": "trunk"})
    monkeypatch.setattr(service_module, "_read_client", lambda config, env: (found, ""))
    reader, _ = service_module._repo_admission_reader(_config(tmp_path), {})
    assert reader("o/r", "") == b"config"
    assert calls[-2:] == [
        ("repo", "o/r"),
        ("file", "o/r", "trunk", REVIEW_MD, MAX_ADMISSION_BYTES),
    ]
    # A payload that names the branch reads no lookup at all.
    calls.clear()
    assert reader("o/r", "main") == b"config"
    assert calls == [("file", "o/r", "main", REVIEW_MD, MAX_ADMISSION_BYTES)]
    # A lookup that 404s is a recorded gap, not the silent unconfigured
    # repo (round-2 nit on #756): the NotFoundError propagates to the
    # caller, which records it on a `repo admission` event.
    missing = _Client(None)
    monkeypatch.setattr(
        service_module, "_read_client", lambda config, env: (missing, "")
    )
    reader, _ = service_module._repo_admission_reader(_config(tmp_path), {})
    with pytest.raises(NotFoundError):
        reader("o/r", "")
    # A reply without a usable default branch is the gap, not a guess.
    nameless = _Client({})
    monkeypatch.setattr(
        service_module, "_read_client", lambda config, env: (nameless, "")
    )
    reader, _ = service_module._repo_admission_reader(_config(tmp_path), {})
    with pytest.raises(BoundaryError):
        reader("o/r", "")


def test_the_operator_log_line_carries_a_skip_reason():
    """A skip's one-line reason reaches the operator log, not only the
    JSONL sink, so a rule-based skip can be told apart from the service
    being down. Mutant: the reason dropped from the line."""
    from atlas_reviewer.service import _LoggingSink
    from atlas_reviewer.telemetry import Event, NullSink

    lines: list[str] = []
    sink = _LoggingSink(NullSink(), lines.append)
    sink.emit(
        Event(
            seq=1,
            phase="service",
            step="review skipped",
            status="ok",
            start_s=0.0,
            duration_s=0.0,
            fields={"pr": 7, "sha12": "aaaaaaaaaaaa", "reason": "repo-skip-event"},
        )
    )
    assert len(lines) == 1
    assert "review skipped" in lines[0]
    assert "reason=repo-skip-event" in lines[0]


def test_the_admission_read_shares_the_handlers_read_budget(tmp_path, monkeypatch):
    """Minor 2 (round-1 review of #756): the admission read and the
    head-change classification share one handler read budget, so the two
    together cannot hold the handler for two full budgets. An admission
    read that spends the budget leaves the classification none: the keep
    verdict is the owner's default and the spent budget is the named
    gap. Mutant: a second full budget for the classification would run
    it and record the classification's own timeout text instead."""
    import atlas_reviewer.service as service_module

    shipped_budget = service_module._READ_BUDGET_S
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    def slow_read(repo: str, ref: str):
        time.sleep(0.5)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    monkeypatch.setattr(service_module, "_READ_BUDGET_S", 0.2)
    try:
        assert _deliver(config, board, _labeled_body()).body == b"queued\n"
        assert started.wait(2)
        result = _deliver(
            config,
            board,
            _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
            admission_reader=slow_read,
            classifier=lambda running, new: _code_push(running, new),
            telemetry=telemetry,
        )
        # The spent budget is the keep default, flagged as the gap.
        assert result.body == b"kept\n"
        decisions = [e for e in telemetry.events if e.step == "head change"]
        assert decisions[0].fields["decision"] == "keep"
        assert "spent on the admission read" in decisions[0].error
    finally:
        release.set()
        worker.stop()
    # The shared budget is the shipped constant, read before this test's
    # monkeypatch was active, small enough to sit inside GitHub's
    # response window even with both reads stacked.
    assert shipped_budget <= 10.0


def test_a_misbehaving_classifier_is_unclassifiable_not_a_crash(tmp_path):
    """Nit 5 (round-1 review of #756): the generalized read helper no
    longer type-checks its result, so the classification call site
    carries the guard the pre-generalization helper had -- a classifier
    whose answer is not a PushClass is unclassifiable (the keep
    default), never a verdict and never a handler crash."""
    board = Board(tmp_path / "queue.json")
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    telemetry = Telemetry(SystemClock())
    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry)
    worker.start()
    try:
        assert _deliver(config, board, _body()).body == b"queued\n"
        assert started.wait(2)
        result = _deliver(
            config,
            board,
            _newer_body(SHA_B, "2026-11-12T20:00:00Z"),
            classifier=lambda running, new: "not a push class",
            telemetry=telemetry,
        )
        assert result.body == b"kept\n"
        decisions = [e for e in telemetry.events if e.step == "head change"]
        assert decisions[0].fields["decision"] == "keep"
        assert "kind" not in decisions[0].fields
    finally:
        release.set()
        worker.stop()


def test_a_fallback_lookup_404_is_a_recorded_gap_and_not_a_stand_down(
    tmp_path, monkeypatch
):
    """The fallback lookup's own 404 (a payload without the default
    branch, and a repository the API cannot find) is a gap on a
    `repo admission` event, and the delivery still queues on the
    operator's envelope -- not the silent unconfigured case, which is
    the file read's 404 only (round-2 nit on #756)."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.ports import NotFoundError

    class _Repo404:
        def get_repository(self, repo):
            raise NotFoundError("GitHub 404 for /repos/o/r")

    monkeypatch.setattr(
        service_module, "_read_client", lambda config, env: (_Repo404(), "")
    )
    reader, _ = service_module._repo_admission_reader(_config(tmp_path), {})
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    result = _deliver(
        config,
        board,
        _labeled_body(default_branch=""),
        admission_reader=reader,
        telemetry=telemetry,
    )
    assert result.body == b"queued\n"
    assert len(board.states()) == 1
    gaps = [e for e in telemetry.events if e.step == "repo admission"]
    assert len(gaps) == 1
    assert gaps[0].status == "error"
    assert "NotFoundError" in gaps[0].error


# ------------------------------------------------------------------
# The retarget re-admission (#758): a base-change `edited` delivery
# re-runs admission against the base the PR now targets. A title or
# body edit stays outside the envelope. A retarget into an excluded
# base is skipped with the usual reason and leaves a review already
# running for the head alone -- it was admitted under the old base and
# is advisory -- and nothing new is queued or posted.


def _retarget_body(
    *,
    from_ref,
    base_ref,
    sha=SHA_A,
    updated_at="2026-11-12T21:00:00Z",
):
    body = json.loads(_labeled_body(base_ref=base_ref, sha=sha).decode())
    body["action"] = "edited"
    body["changes"] = {"base": {"ref": {"from": from_ref}}}
    body["pull_request"]["updated_at"] = updated_at
    body["pull_request"]["state"] = "open"
    return json.dumps(body).encode()


def test_a_retarget_into_an_included_base_is_queued_against_the_new_base(tmp_path):
    """The gap #758 closes: a PR opened against a base the narrowing
    excludes is picked up when it is retargeted onto an included one,
    without waiting for its next push. The config is still read from the
    repository's default branch -- the retarget changes the match
    target, never the config's source."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    seen: list[tuple[str, str]] = []
    reader = _admission_reader("review_base_include: main\n", seen)
    before = _deliver(
        config,
        board,
        _labeled_body(base_ref="feature/x"),
        admission_reader=reader,
    )
    assert before.detail == "ignored:repo-base-branch"
    assert board.states() == ()
    result = _deliver(
        config,
        board,
        _retarget_body(from_ref="feature/x", base_ref="main"),
        admission_reader=reader,
    )
    assert result.body == b"queued\n"
    assert board.states() == ((SHA_A, JobState.QUEUED),)
    assert seen == [(REPO, "trunk"), (REPO, "trunk")]


def test_a_title_or_body_edit_is_ignored(tmp_path):
    """The widening is one event shape, not the ``edited`` family: an
    edit that carries no ``changes.base`` re-enters nothing, with or
    without an admission reader on the deployment."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    reader = _admission_reader("review_base_include: main\n")
    for changes in (
        {"title": {"from": "old"}},
        {"body": {"from": "old"}},
        {"title": {"from": "a"}, "body": {"from": "b"}},
    ):
        body = json.loads(_retarget_body(from_ref="main", base_ref="main").decode())
        body["changes"] = changes
        result = _deliver(
            config, board, json.dumps(body).encode(), admission_reader=reader
        )
        assert result.detail == "ignored:action"
    assert board.states() == ()


def test_a_retarget_into_an_excluded_base_is_skipped_with_the_usual_reason(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    reader = _admission_reader("review_base_include: main\n")
    result = _deliver(
        config,
        board,
        _retarget_body(from_ref="main", base_ref="feature/x"),
        admission_reader=reader,
        telemetry=telemetry,
    )
    assert result.detail == "ignored:repo-base-branch"
    assert board.states() == ()
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert [e.fields["reason"] for e in skips] == ["repo-base-branch"]


def test_a_retarget_to_an_excluded_base_leaves_a_running_review_alone(tmp_path):
    """The in-flight case, defined: the running review was admitted under
    the base it was reviewed against and is advisory (the service is
    COMMENT-only), so the skip acts on the delivery only -- the review
    finishes and posts, and nothing new is queued. Mutant: a skip that
    superseded the running job would leave nothing posted."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    started = threading.Event()
    release = threading.Event()
    posted: list[str] = []

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    def publish(event, report):
        posted.append(event.head_sha)

    worker = _worker(board, runner, publish, tmp_path)
    worker.start()
    try:
        assert (
            _deliver(
                config,
                board,
                _labeled_body(base_ref="main", sha=SHA_A),
                admission_reader=_admission_reader("review_base_include: main\n"),
            ).body
            == b"queued\n"
        )
        assert started.wait(2)
        result = _deliver(
            config,
            board,
            _retarget_body(from_ref="main", base_ref="feature/x"),
            admission_reader=_admission_reader("review_base_include: main\n"),
        )
        assert result.detail == "ignored:repo-base-branch"
        assert board.states() == ((SHA_A, JobState.RUNNING),)
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not posted:
            time.sleep(0.01)
        assert posted == [SHA_A]
    finally:
        worker.stop()


def test_a_retarget_while_a_review_runs_dedupes_against_it(tmp_path):
    """A retarget onto an included base while a review of the same head
    runs is a duplicate, not a supersede: the head did not move, so the
    running review keeps its post."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    started = threading.Event()
    release = threading.Event()
    posted: list[str] = []

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            release.wait(2)
        return ReviewRun(True, REPORT)

    def publish(event, report):
        posted.append(event.head_sha)

    worker = _worker(board, runner, publish, tmp_path)
    worker.start()
    try:
        assert (
            _deliver(
                config,
                board,
                _labeled_body(base_ref="main", sha=SHA_A),
                admission_reader=_admission_reader("review_base_include: main\n"),
            ).body
            == b"queued\n"
        )
        assert started.wait(2)
        result = _deliver(
            config,
            board,
            _retarget_body(from_ref="feature/x", base_ref="main"),
            admission_reader=_admission_reader("review_base_include: main\n"),
        )
        assert result.body == b"duplicate\n"
        assert board.states() == ((SHA_A, JobState.RUNNING),)
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not posted:
            time.sleep(0.01)
        assert posted == [SHA_A]
    finally:
        worker.stop()


def test_a_retarget_of_a_draft_is_still_ignored(tmp_path):
    """The retarget widening touches the event set only; the draft rule
    of the operator envelope stands."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    body = json.loads(_retarget_body(from_ref="main", base_ref="main").decode())
    body["pull_request"]["draft"] = True
    result = _deliver(config, board, json.dumps(body).encode())
    assert result.detail == "ignored:draft"
    assert board.states() == ()


def test_a_retarget_of_a_closed_pr_is_ignored(tmp_path):
    """GitHub sends a base change only for an open PR's retarget; the
    state guard is defense-in-depth, so an anomalous closed-PR delivery
    costs no review and posts no comment."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    body = json.loads(_retarget_body(from_ref="main", base_ref="main").decode())
    body["pull_request"]["state"] = "closed"
    result = _deliver(config, board, json.dumps(body).encode())
    assert result.detail == "ignored:state"
    assert board.states() == ()


def test_a_repo_can_opt_out_of_retarget_reviews(tmp_path):
    """``edited`` is a legal ``review_skip_events`` value, so the
    documented invariant holds: a repo that skips every skippable event
    is never reviewed. Skipping ``edited`` suppresses the
    retarget-triggered review only -- the delivery is skipped with the
    usual reason -- and a skip set that does not name it leaves the
    retarget queued."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    opt_out = _admission_reader("review_skip_events: edited\n")
    result = _deliver(
        config,
        board,
        _retarget_body(from_ref="feature/x", base_ref="main"),
        admission_reader=opt_out,
        telemetry=telemetry,
    )
    assert result.detail == "ignored:repo-skip-event"
    assert board.states() == ()
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert [e.fields["reason"] for e in skips] == ["repo-skip-event"]
    # A skip set that does not name `edited` leaves the retarget queued.
    other = _admission_reader("review_skip_events: synchronize\n")
    queued = _deliver(
        config,
        board,
        _retarget_body(from_ref="feature/x", base_ref="main"),
        admission_reader=other,
    )
    assert queued.body == b"queued\n"
    assert len(board.states()) == 1


def test_a_settled_review_is_not_re_run_by_a_retarget(tmp_path):
    """The settled half of the dedupe: once the head's review has settled
    and posted, a retarget of the same head is a duplicate -- the queue's
    key remembers the head -- and nothing is posted twice."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    posted: list[str] = []

    def runner(event, cancel):
        return ReviewRun(True, REPORT)

    def publish(event, report):
        posted.append(event.head_sha)

    worker = _worker(board, runner, publish, tmp_path)
    worker.start()
    try:
        assert (
            _deliver(
                config,
                board,
                _labeled_body(base_ref="main", sha=SHA_A),
                admission_reader=_admission_reader("review_base_include: main\n"),
            ).body
            == b"queued\n"
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not posted:
            time.sleep(0.01)
        assert posted == [SHA_A]
        result = _deliver(
            config,
            board,
            _retarget_body(from_ref="feature/x", base_ref="main"),
            admission_reader=_admission_reader("review_base_include: main\n"),
        )
        assert result.body == b"duplicate\n"
        assert posted == [SHA_A]
    finally:
        worker.stop()


# ------------------------------- the repo's own post settings (S3, D84)


def test_the_post_config_fetcher_needs_the_app_credentials(tmp_path):
    import atlas_reviewer.service as service_module

    config = _config(tmp_path)
    fetcher, reason = service_module._post_config_fetcher(config, {})
    assert fetcher is None
    assert "ATLAS_GITHUB_APP_ID" in reason


def test_the_post_config_fetcher_recovers_the_default_branch_then_reads_the_file(
    tmp_path, monkeypatch
):
    """At post time no payload carries the default branch, so the fetch
    recovers it with one read-only lookup and then reads the file under
    the same 64 KiB bound the admission read uses. A missing file is the
    ordinary unconfigured repo (None); the lookup's own 404 propagates
    as the gap."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.ports import NotFoundError
    from atlas_reviewer.service_admit import MAX_ADMISSION_BYTES, REVIEW_MD

    calls: list[tuple[object, ...]] = []

    class _Client:
        def __init__(self, repo_json, file_result=b"config"):
            self.repo_json = repo_json
            self.file_result = file_result

        def get_repository(self, repo):
            calls.append(("repo", repo))
            if self.repo_json is None:
                raise NotFoundError("GitHub 404")
            return self.repo_json

        def get_file(self, repo, ref, path, max_bytes):
            calls.append(("file", repo, ref, path, max_bytes))
            if self.file_result is None:
                raise NotFoundError("GitHub 404")
            return self.file_result

    found = _Client({"default_branch": "trunk"})
    monkeypatch.setattr(service_module, "_read_client", lambda config, env: (found, ""))
    fetcher, reason = service_module._post_config_fetcher(_config(tmp_path), {})
    assert reason == ""
    assert fetcher("o/r") == b"config"
    assert calls == [
        ("repo", "o/r"),
        ("file", "o/r", "trunk", REVIEW_MD, MAX_ADMISSION_BYTES),
    ]

    # No file on the default branch: None, not an error.
    unconfigured = _Client({"default_branch": "trunk"}, None)
    monkeypatch.setattr(
        service_module, "_read_client", lambda config, env: (unconfigured, "")
    )
    fetcher, _ = service_module._post_config_fetcher(_config(tmp_path), {})
    assert fetcher("o/r") is None

    # A lookup that 404s propagates: the caller records it as the gap.
    missing = _Client(None)
    monkeypatch.setattr(
        service_module, "_read_client", lambda config, env: (missing, "")
    )
    fetcher, _ = service_module._post_config_fetcher(_config(tmp_path), {})
    with pytest.raises(NotFoundError):
        fetcher("o/r")


def test_the_post_config_source_fails_open_to_the_default_and_records_the_gap():
    """A fetch that fails or times out leaves the default standing -- the
    protective direction: a lost read can only make the post more
    complete, never less -- and the gap is on the telemetry. A no-file
    repo is the ordinary unconfigured case: the default, silently."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.repo_config import DEFAULT_POST_CONFIG
    from atlas_reviewer.telemetry import Telemetry

    telemetry = Telemetry(SystemClock())
    event = PrEvent("o/r", 7, "a" * 40)

    def broken(repo: str) -> bytes:
        raise RuntimeError("the fetch blew up")

    source = service_module._post_config_source(broken, event, telemetry)
    assert source() == DEFAULT_POST_CONFIG
    gaps = [event for event in telemetry.events if event.step == "post config"]
    assert len(gaps) == 1 and "RuntimeError" in gaps[0].error

    def no_file(repo: str) -> bytes | None:
        return None

    source = service_module._post_config_source(no_file, event, telemetry)
    assert source() == DEFAULT_POST_CONFIG
    assert len([e for e in telemetry.events if e.step == "post config"]) == 1


def test_the_post_config_source_parses_and_records_unusable_lines():
    import atlas_reviewer.service as service_module
    from atlas_reviewer.lens_contract import Severity
    from atlas_reviewer.telemetry import Telemetry

    telemetry = Telemetry(SystemClock())
    event = PrEvent("o/r", 7, "a" * 40)

    def configured(repo: str) -> bytes | None:
        return b"review_severity_floor: major\nreview_post_verbosity: terse\n"

    source = service_module._post_config_source(configured, event, telemetry)
    config = source()
    assert config.floor is Severity("major")
    # The unusable dial line fails open on its own key; the floor stands.
    assert config.verbosity == "full"
    assert len(config.notes) == 1 and "review_post_verbosity:" in config.notes[0]
    named = [event for event in telemetry.events if event.step == "post config"]
    assert len(named) == 1 and "review_post_verbosity:" in named[0].error


def test_the_post_config_source_survives_a_timeout(monkeypatch):
    """A read past its budget is the recorded gap and the default, and
    the source never raises into the post path."""
    import threading

    import atlas_reviewer.service as service_module
    from atlas_reviewer.repo_config import DEFAULT_POST_CONFIG
    from atlas_reviewer.telemetry import Telemetry

    monkeypatch.setattr(service_module, "_READ_BUDGET_S", 0.2)
    telemetry = Telemetry(SystemClock())
    event = PrEvent("o/r", 7, "a" * 40)
    release = threading.Event()

    def slow(repo: str) -> bytes | None:
        release.wait(5)
        return b"review_severity_floor: major\n"

    source = service_module._post_config_source(slow, event, telemetry)
    assert source() == DEFAULT_POST_CONFIG
    release.set()
    gaps = [event for event in telemetry.events if event.step == "post config"]
    assert len(gaps) == 1 and "budget" in gaps[0].error


def test_the_wrapped_publisher_resolves_the_config_and_hands_the_source():
    """`_post_config_publisher` wraps the publisher so each post resolves
    the repo's post configuration lazily -- the source the poster reads
    after its own dedupe checks -- and passes everything through when
    there is no publisher or no fetcher."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.lens_contract import Severity
    from atlas_reviewer.repo_config import PostConfigRead

    seen: list[tuple[object, ...]] = []

    def publisher(event, report, source):
        seen.append((event, report, source))

    def fetcher(repo: str) -> bytes | None:
        return b"review_severity_floor: minor\n"

    wrapped = service_module._post_config_publisher(publisher, fetcher, None)
    assert wrapped is not None
    event = PrEvent("o/r", 7, "a" * 40)
    report = ReviewReport((), (), "", (), (), (), "COMMENT")
    wrapped(event, report)
    assert len(seen) == 1
    source = seen[0][2]
    config = source()
    assert config == PostConfigRead(Severity("minor"), "full", ())

    # No publisher, or no fetcher: pass-through, the same object.
    assert service_module._post_config_publisher(None, fetcher, None) is None
    assert service_module._post_config_publisher(publisher, None, None) is publisher


def test_serve_installs_the_post_config_wrapper_and_the_post_honors_it(
    tmp_path, monkeypatch
):
    """The r1 Minor's seam, driven end to end: `serve` wraps the
    publisher with the post-config source when a fetcher is configured,
    the worker posts through the wrapped publisher, and the real poster
    reads the source after its dedupe checks -- a below-floor
    preference-tier finding never reaches the body, the blocker does,
    and the floor key is named. Kills the mutant that deletes the
    wrapper's installation in `serve`."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.http import HttpResponse
    from atlas_reviewer.service_post import PostLedger, ReviewPoster

    class _ConfigClient:
        def get_repository(self, repo: str):
            return {"default_branch": "main"}

        def get_file(self, repo: str, ref: str, path: str, max_bytes: int) -> bytes:
            return b"review_severity_floor: major\n"

    monkeypatch.setattr(
        service_module, "_read_client", lambda config, env: (_ConfigClient(), "")
    )

    findings = (
        (
            "**L1-F1** [blocker, defect, route: eng, introduced] `a.py:1` "
            "(reviewing-api-contract-safety): breaks callers"
        ),
        (
            "**L1-F2** [minor, defect, route: eng, introduced] `a.py:3` "
            "(checking-restraint): naming"
        ),
    )
    report = dataclass_replace(
        REPORT,
        findings=findings,
        coverage_complete=True,
        lenses_run=("tracing-correctness-and-invariants",),
    )

    class _GitHub:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bytes | None]] = []
            self.reviews: list[dict[str, object]] = []

        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            self.calls.append((method, url, body))
            if method == "GET":
                return HttpResponse(200, {}, json.dumps(self.reviews).encode())
            payload = json.loads(body)
            self.reviews.append(
                {
                    "id": 9,
                    "body": payload["body"],
                    "commit_id": payload["commit_id"],
                    "user": {"login": "code-quality-atlas[bot]", "type": "Bot"},
                }
            )
            return HttpResponse(200, {}, b'{"id": 9}')

    class _Tokens:
        def token(self) -> str:
            return "ghs_test"

    github = _GitHub()
    poster = ReviewPoster(
        github,
        _Tokens(),
        PostLedger(tmp_path / "posted.json"),
        lambda text: text,
        bot_login="code-quality-atlas[bot]",
    )
    config = ServiceConfig(
        secret=SECRET,
        allowlist=frozenset({REPO}),
        state_dir=tmp_path,
        host="127.0.0.1",
        port=0,
    )
    board = Board(tmp_path / "queue.json")
    event = PrEvent(REPO, 7, SHA_A)
    board.enqueue(event)

    def serve_forever(self, poll_interval=0.5):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if github.reviews:
                return
            time.sleep(0.02)

    monkeypatch.setattr(service_module.ReviewServer, "serve_forever", serve_forever)
    assert (
        serve(
            config,
            {},
            runner=lambda _event, _cancel: ReviewRun(True, report),
            publisher=poster.post,
            post_config_fetcher=service_module._post_config_fetcher(config, {})[0],
            log=lambda line: None,
        )
        == 0
    )
    posts = [call for call in github.calls if call[0] == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0][2] or b"")["body"]
    assert "`review_severity_floor: major`" in body
    assert findings[0] in body
    assert findings[1] not in body
    assert "[1 below-floor finding(s) from preference-tier lenses" in body


def test_the_wrapped_publisher_hands_the_poster_a_post_config_read():
    """The wrapper's own contract at the composition seam: the lazy
    source it hands the poster parses the fetcher's bytes, so the poster
    never sees the raw file."""
    import atlas_reviewer.service as service_module
    from atlas_reviewer.repo_config import PostConfigRead

    seen: list[object] = []

    def publisher(event, report, source):
        seen.append(source())

    def fetcher(repo: str) -> bytes | None:
        return b"review_post_verbosity: brief\n"

    wrapped = service_module._post_config_publisher(publisher, fetcher, None)
    assert wrapped is not None
    wrapped(PrEvent(REPO, 7, SHA_A), REPORT)
    assert seen == [PostConfigRead(None, "brief", ())]


# -------------------------------- the per-tenant daily bounds (S9, issue 767)


_BUDGET_DAY = date(2026, 11, 19)


def _spend(tmp_path, *, budget=Decimal("100.00"), cap=None):
    """`cap` is an installation-id-keyed dict, the test double for S10's
    installation store; None is the S9 production provider (no cap)."""
    caps = cap or {}
    return DailySpend(
        tmp_path,
        budget,
        cap_for=(lambda installation: caps.get(installation))
        if cap is not None
        else no_installation_cap,
        today=lambda: _BUDGET_DAY,
    )


def test_a_repo_over_its_daily_budget_is_refused_at_admission(tmp_path):
    """The done-when: a repo over its daily budget is refused with the
    plain record -- the fixed reason label, the plain refusal text -- and
    the delivery is acknowledged and ignored, never queued."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    spend = _spend(tmp_path)
    spend.record(REPO, Decimal("100.0000"), 4)
    result = _deliver(config, board, _body(), telemetry=telemetry, spend=spend)
    assert result.status == 202
    assert result.detail == "ignored:daily-budget"
    assert board.states() == ()
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert skips and skips[0].fields["reason"] == "daily-budget"
    assert "skipped: daily budget reached" in skips[0].error


def test_a_repo_under_its_daily_budget_is_queued(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)
    spend.record(REPO, Decimal("99.9900"), 4)
    assert _deliver(config, board, _body(), spend=spend).body == b"queued\n"
    assert board.states() == ((SHA_A, JobState.QUEUED),)


def test_the_budget_check_runs_before_the_admission_read(tmp_path):
    """A repo over its budget costs no GitHub read: the delivery is
    refused before the default-branch REVIEW.md is fetched."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    reads = []

    def reader(repo, branch):
        reads.append(repo)

    spend = _spend(tmp_path)
    spend.record(REPO, Decimal("100.0000"), 4)
    _deliver(config, board, _body(), admission_reader=reader, spend=spend)
    assert reads == []


def test_an_installation_over_its_daily_cap_is_refused_the_same_way(tmp_path):
    """The cap double (S10's store stands in): an installation over its
    admin's cap is refused with the cap's own plain record, and an
    installation with no cap is not refused by one that has one."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    spend = _spend(tmp_path, cap={"1234": Decimal("50.00")})
    spend.record(REPO, Decimal("50.0000"), 2)
    body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": 1234},
            "repository": {"full_name": REPO},
            "pull_request": {
                "number": 7,
                "draft": False,
                "updated_at": "2026-11-12T20:00:00Z",
                "head": {"sha": SHA_A},
                "base": {"repo": {"full_name": REPO}},
            },
        }
    ).encode()
    result = _deliver(config, board, body, telemetry=telemetry, spend=spend)
    assert result.detail == "ignored:daily-budget"
    assert board.states() == ()
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert "skipped: installation daily cap reached" in skips[0].error
    # A different installation with no cap set: none applies.
    body_other = json.loads(body)
    body_other["installation"] = {"id": 5678}
    assert (
        _deliver(
            config,
            board,
            json.dumps(body_other).encode(),
            spend=spend,
        ).body
        == b"queued\n"
    )


def test_an_unset_cap_leaves_the_budget_the_only_bound(tmp_path):
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)
    spend.record(REPO, Decimal("99.0000"), 1)
    assert _deliver(config, board, _body(), spend=spend).body == b"queued\n"


def test_an_unreadable_spend_file_refuses_and_names_the_gap(tmp_path):
    """Fail closed: a spend file the service cannot parse holds the
    budget until it is repaired, and the record names the ledger gap
    beside the plain refusal."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    path = spend_file(tmp_path, REPO, _BUDGET_DAY)
    path.parent.mkdir(parents=True)
    path.write_text("not a record\n", encoding="utf-8")
    result = _deliver(
        config, board, _body(), telemetry=telemetry, spend=_spend(tmp_path)
    )
    assert result.detail == "ignored:daily-budget"
    assert board.states() == ()
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert "skipped: daily budget reached" in skips[0].error
    assert "unreadable record" in skips[0].error


def test_a_queued_review_is_refused_again_at_preflight(tmp_path):
    """The re-check: a delivery admitted while the day had room is
    refused in the worker before the review starts, when the day's total
    was spent in between. The runner never runs, nothing is posted, and
    the record says plainly what refused it."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    spend = _spend(tmp_path)
    assert _deliver(config, board, _body(), spend=spend).body == b"queued\n"
    spend.record(REPO, Decimal("100.0000"), 4)
    ran = []

    def runner(event, cancel):
        ran.append(event.head_sha)
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry, spend=spend)
    assert worker.run_one() is True
    assert ran == []
    assert board.states() == ((SHA_A, JobState.FAILED),)
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert skips and skips[0].fields["reason"] == "daily-budget"
    assert "skipped: daily budget reached" in skips[0].error
    published = [e for e in telemetry.events if e.step == "review finished"]
    assert published == []


def test_a_settled_review_records_its_settled_bill_on_the_days_ledger(tmp_path):
    """The counting: the finished review's settled bill -- the child's
    own token-counts-times-price-table figure from the draft's cost line
    -- is appended to the day's file, and the next admission sees it. The
    finished draft's settled figure is the one recorded, not a stale
    progress record's partial and not the reservation that record holds."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)

    def runner(event, cancel):
        run = run_dir(tmp_path, event)
        run.mkdir(parents=True, exist_ok=True)
        (run / "events.jsonl").write_text(
            json.dumps(
                {
                    "seq": 1,
                    "phase": "progress",
                    "step": "lens settled",
                    "status": "ok",
                    "lens": "tracing",
                    "lenses_done": 1,
                    "lenses_total": 4,
                    "calls": 3,
                    "settled_usd": "1.10",
                    "committed_usd": "2.20",
                    "reservation_usd": "10",
                    "reading": "src/x.py",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return ReviewRun(True, REPORT_COST)

    worker = _worker(board, runner, root=tmp_path, spend=spend)
    _deliver(config, board, _body(), spend=spend)
    assert worker.run_one() is True
    total, gap = spend.committed(REPO)
    assert gap == ""
    assert total == Decimal("3.40")
    # The committed spend governs the next admission: enough reviews at
    # the ceiling spend the day.
    spend.record(REPO, Decimal("99.9900"), 1)
    assert _deliver(config, board, _body(sha=SHA_B), spend=spend).detail == (
        "ignored:daily-budget"
    )


def test_a_failed_review_records_the_settled_bill_its_progress_recorded(tmp_path):
    """The progress record's committed figure still includes an in-flight
    reservation ($2.20). The ledger records the settled bill ($1.10).
    Kills the backfill that still books `committed_usd`."""
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)

    def runner(event, cancel):
        run = run_dir(tmp_path, event)
        run.mkdir(parents=True, exist_ok=True)
        (run / "events.jsonl").write_text(
            json.dumps(
                {
                    "seq": 1,
                    "phase": "progress",
                    "step": "lens settled",
                    "status": "ok",
                    "lens": "tracing",
                    "lenses_done": 1,
                    "lenses_total": 4,
                    "calls": 3,
                    "settled_usd": "1.10",
                    "committed_usd": "2.20",
                    "reservation_usd": "10",
                    "reading": "src/x.py",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("runner blew up")

    worker = _worker(board, runner, root=tmp_path, spend=spend)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    total, gap = spend.committed(REPO)
    assert gap == ""
    assert total == Decimal("1.10")


def test_refused_calls_add_nothing_to_the_daily_ledger(tmp_path):
    """Issue #797: a finished review whose calls were refused records the
    settled figure, $0, and not the reservation the cost line holds.
    Kills a parser that books the held amount, and one that adds held
    to settled."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)
    refused = dataclass_replace(
        REPORT_COST,
        cost_lines=("Model calls: 15; settled: $0; held at reservation: $24.90.",),
    )
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, refused),
        root=tmp_path,
        spend=spend,
    )
    _deliver(config, board, _body(), spend=spend)
    assert worker.run_one() is True
    assert spend.committed(REPO) == (Decimal(0), "")


def test_a_served_call_with_no_usage_counts_on_the_daily_ledger(tmp_path):
    """A 200 with no usage is settled at its reservation and held $0
    (what the one-shot and lens paths write). The ledger records that
    reservation. Kills a backfill that records $0 whenever settled
    equals the reservation, and one that subtracts a hold the record
    does not carry (round-1 review of #799)."""
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)

    def runner(event, cancel):
        run = run_dir(tmp_path, event)
        run.mkdir(parents=True, exist_ok=True)
        (run / "events.jsonl").write_text(
            json.dumps(
                {
                    "seq": 1,
                    "phase": "progress",
                    "step": "lens settled",
                    "status": "ok",
                    "lens": "tracing",
                    "lenses_done": 1,
                    "lenses_total": 4,
                    "calls": 1,
                    "settled_usd": "1.68",
                    "held_usd": "0",
                    "committed_usd": "1.68",
                    "reservation_usd": "25",
                    "reading": "src/x.py",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("runner blew up")

    worker = _worker(board, runner, root=tmp_path, spend=spend)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    assert spend.committed(REPO) == (Decimal("1.68"), "")


def test_a_finished_review_logs_the_bill_apart_from_what_it_holds(tmp_path):
    """The cost event's committed_usd stays the ceiling (bill plus
    hold). billed_usd is what the ledger records, and the hold is not
    added to it. Kills writing the bill into committed_usd, and a
    parser that adds the hold to the ledger."""
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    spend = _spend(tmp_path)
    mixed = dataclass_replace(
        REPORT_COST,
        cost_lines=("Model calls: 4; settled: $1.10; held at reservation: $0.50.",),
    )
    worker = _worker(
        board,
        lambda event, cancel: ReviewRun(True, mixed),
        root=tmp_path,
        telemetry=telemetry,
        spend=spend,
    )
    _deliver(_config(tmp_path), board, _body(), spend=spend)
    assert worker.run_one() is True
    assert spend.committed(REPO) == (Decimal("1.10"), "")
    costs = [e for e in telemetry.events if e.step == "review cost"]
    assert costs[0].fields["billed_usd"] == "1.10"
    assert costs[0].fields["held_usd"] == "0.50"
    assert costs[0].fields["committed_usd"] == "1.60"


def test_a_crashed_review_of_only_held_reservations_adds_nothing(tmp_path):
    """A crash whose progress is all held reservations -- settled equal
    to held, the in-flight-inclusive committed figure beside them --
    records $0. Kills the backfill that still books `committed_usd`, and
    one that books `settled_usd` without subtracting held."""
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path)

    def runner(event, cancel):
        run = run_dir(tmp_path, event)
        run.mkdir(parents=True, exist_ok=True)
        (run / "events.jsonl").write_text(
            json.dumps(
                {
                    "seq": 1,
                    "phase": "progress",
                    "step": "lens settled",
                    "status": "ok",
                    "lens": "tracing",
                    "lenses_done": 1,
                    "lenses_total": 4,
                    "calls": 15,
                    "settled_usd": "24.90",
                    "held_usd": "24.90",
                    "committed_usd": "24.90",
                    "reservation_usd": "25",
                    "reading": "src/x.py",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("runner blew up")

    worker = _worker(board, runner, root=tmp_path, spend=spend)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    assert spend.committed(REPO) == (Decimal(0), "")


def test_a_review_with_no_cost_figure_records_nothing(tmp_path):
    """The amount is never guessed: a review whose cost is in neither the
    draft nor a progress record records nothing, and the gap the cost
    event carries is where the miss stays visible."""
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    spend = _spend(tmp_path)

    def runner(event, cancel):
        raise RuntimeError("runner blew up")

    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry, spend=spend)
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    assert spend.committed(REPO) == (Decimal(0), "")
    costs = [e for e in telemetry.events if e.step == "review cost"]
    assert costs and costs[0].fields["measured"] == "unknown"


def test_the_spend_records_survive_a_service_restart(tmp_path):
    """The total lives on the state volume: a DailySpend built fresh over
    the same state root -- what a restarted service constructs -- reads
    the spend the previous process recorded."""
    _spend(tmp_path).record(REPO, Decimal("40.0000"), 2)
    spend = DailySpend(
        tmp_path,
        Decimal("100.00"),
        today=lambda: _BUDGET_DAY,
    )
    assert spend.committed(REPO) == (Decimal("40.0000"), "")
    assert spend.refusal(REPO, "") == ("", "")
    spend.record(REPO, Decimal("60.0000"), 2)
    assert spend.refusal(REPO, "") == ("skipped: daily budget reached", "")


def test_config_from_env_parses_the_per_tenant_bounds(tmp_path):
    env = {
        "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
        "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        "ATLAS_SERVICE_PROVIDER": "offline",
    }
    config = config_from_env(env)
    assert config.repo_daily_budget_usd == Decimal("100.00")
    custom = {**env, "ATLAS_REPO_DAILY_BUDGET_USD": "40"}
    assert config_from_env(custom).repo_daily_budget_usd == Decimal(40)
    for bad in ("abc", "0", "-5"):
        with pytest.raises(ServiceError, match="ATLAS_REPO_DAILY_BUDGET_USD"):
            config_from_env({**env, "ATLAS_REPO_DAILY_BUDGET_USD": bad})
    # The child's clamp variable is validated at boot too.
    with pytest.raises(ServiceError, match="ATLAS_REPO_CEILING_MAX_USD"):
        config_from_env({**env, "ATLAS_REPO_CEILING_MAX_USD": "abc"})
    ok = config_from_env({**env, "ATLAS_REPO_CEILING_MAX_USD": "30"})
    assert ok.repo_daily_budget_usd == Decimal("100.00")


# ------------------------------------------------- the crash backfill (M1)


def _progress_record(committed: str, calls: int, seq: int = 2) -> str:
    return json.dumps(
        {
            "seq": seq,
            "phase": "progress",
            "step": "lens settled",
            "status": "ok",
            "lens": "tracing",
            "lenses_done": 1,
            "lenses_total": 4,
            "calls": calls,
            "settled_usd": "1.10",
            "committed_usd": committed,
            "reservation_usd": "10",
            "reading": "src/x.py",
        }
    )


def _run_start_record(attempt: int = 1) -> str:
    """One run's own first event: `seq` restarts at 1 per run, and the
    monotonic `start_s` differs per run, so two attempts' start lines
    never read the same."""
    return json.dumps(
        {
            "seq": 1,
            "phase": "review",
            "step": "review started",
            "status": "ok",
            "start_s": 100.0 * attempt,
            "duration_s": 0.0,
        }
    )


def _append_events(path: Path, *lines: str) -> None:
    """The way the real child writes: the telemetry sink opens the
    events file `O_APPEND` and appends; nothing truncates."""
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))


def test_a_crashed_attempt_s_spend_is_backfilled_and_the_retry_s_is_added(tmp_path):
    """M1: a review whose process died before the worker could settle it
    never reached the settle-time spend recording. The retry's pre-runner
    pass reads the progress the crash left in the run directory and
    backfills the settled bill ($1.10) onto the day's ledger once -- not
    the committed figure ($2.20) that still includes an in-flight
    reservation -- before the retry appends its own run's events; the
    retry's own settled bill is then added on top."""
    path = tmp_path / "queue.json"
    board = Board(path)
    spend = _spend(tmp_path)
    # The crashed attempt: head A was claimed (left running) and wrote
    # progress before the process died.
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert board.claim() is not None
    run = run_dir(tmp_path, PrEvent(REPO, 7, SHA_A))
    run.mkdir(parents=True, exist_ok=True)
    _append_events(
        run / "events.jsonl",
        _run_start_record(attempt=1),
        _progress_record("2.20", 3),
    )
    # Restart: the reloaded board queues the crashed head again, and the
    # retry's child appends its own run's events to the same file.
    reloaded = Board(path)
    telemetry = Telemetry(SystemClock())
    ran = []

    def runner(event, cancel):
        ran.append(event.head_sha)
        _append_events(
            run / "events.jsonl",
            _run_start_record(attempt=2),
            _progress_record("3.00", 4),
        )
        return ReviewRun(True, REPORT_COST)

    worker = _worker(reloaded, runner, root=tmp_path, telemetry=telemetry, spend=spend)
    assert worker.run_one() is True
    assert ran == [SHA_A]
    total, gap = spend.committed(REPO)
    assert gap == ""
    assert total == Decimal("1.10") + Decimal("3.40")
    backs = [e for e in telemetry.events if e.step == "crashed spend"]
    assert backs and backs[0].fields["measured"] == "backfilled"
    assert backs[0].fields["committed_usd"] == "2.20"
    assert backs[0].fields["billed_usd"] == "1.10"


def test_a_second_backfill_of_the_same_crash_adds_nothing(tmp_path):
    """The once is the ledger's own: the dedupe key is the evidence's
    content hash, so a recovery that runs twice against the same crashed
    attempt -- a failed queue save puts the head back -- appends nothing
    the second time."""
    from atlas_reviewer.service import _backfill_crashed_spend

    spend = _spend(tmp_path)
    event = PrEvent(REPO, 7, SHA_A)
    run = run_dir(tmp_path, event)
    run.mkdir(parents=True, exist_ok=True)
    _append_events(
        run / "events.jsonl",
        _run_start_record(attempt=1),
        _progress_record("2.20", 3),
    )
    telemetry = Telemetry(SystemClock())
    _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    assert spend.committed(REPO) == (Decimal("1.10"), "")
    backs = [e for e in telemetry.events if e.step == "crashed spend"]
    assert len(backs) == 2
    assert backs[0].fields["measured"] == "backfilled"
    assert backs[1].fields["measured"] == "already recorded"


def test_a_crash_with_no_progress_figure_records_nothing_and_names_the_gap(
    tmp_path,
):
    """A run directory left behind with no readable progress figure --
    the child died before its first progress record -- records nothing,
    and the gap is named on the recovery's telemetry rather than silent.
    An ordinary first run (no run directory at all) stays silent."""
    from atlas_reviewer.service import _backfill_crashed_spend

    spend = _spend(tmp_path)
    event = PrEvent(REPO, 7, SHA_A)
    run_dir(tmp_path, event).mkdir(parents=True, exist_ok=True)
    telemetry = Telemetry(SystemClock())
    _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    assert spend.committed(REPO) == (Decimal(0), "")
    backs = [e for e in telemetry.events if e.step == "crashed spend"]
    assert backs and "no progress figure" in backs[0].error
    # No run directory: the ordinary first run -- no event, no note.
    quiet = Telemetry(SystemClock())
    _backfill_crashed_spend(spend, tmp_path, PrEvent(REPO, 7, SHA_B), quiet)
    assert [e for e in quiet.events if e.step == "crashed spend"] == []


def test_a_queued_review_is_refused_at_preflight_by_the_installation_cap(tmp_path):
    """N3: the cap double is enforced at the preflight re-check too, not
    only at admission -- a delivery admitted under an unset-spent cap is
    refused in the worker when the cap is spent by the time it claims."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    telemetry = Telemetry(SystemClock())
    spend = _spend(tmp_path, cap={"": Decimal("10.00")})
    assert _deliver(config, board, _body(), spend=spend).body == b"queued\n"
    spend.record(REPO, Decimal("10.0000"), 4)
    ran = []

    def runner(event, cancel):
        ran.append(event.head_sha)
        return ReviewRun(True, REPORT)

    worker = _worker(board, runner, root=tmp_path, telemetry=telemetry, spend=spend)
    assert worker.run_one() is True
    assert ran == []
    assert board.states() == ((SHA_A, JobState.FAILED),)
    skips = [e for e in telemetry.events if e.step == "review skipped"]
    assert "skipped: installation daily cap reached" in skips[0].error


def test_a_boolean_installation_id_is_not_an_installation_id(tmp_path):
    """N2: the payload's installation id is read only when it is a real
    integer -- a boolean is not one -- so a cap keyed on its string form
    is never consulted."""
    config = _config(tmp_path)
    board = Board(tmp_path / "queue.json")
    spend = _spend(tmp_path, cap={"True": Decimal("0.01")})
    spend.record(REPO, Decimal("0.0100"), 1)
    body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": True},
            "repository": {"full_name": REPO},
            "pull_request": {
                "number": 7,
                "draft": False,
                "updated_at": "2026-11-12T20:00:00Z",
                "head": {"sha": SHA_A},
                "base": {"repo": {"full_name": REPO}},
            },
        }
    ).encode()
    assert _deliver(config, board, body, spend=spend).body == b"queued\n"


def test_a_progress_less_retry_does_not_re_backfill_the_stale_tail(tmp_path):
    """M-R2-1: the events file is append-only across a head's attempts,
    so a retry that appends its startup events and dies before its first
    progress record leaves the previous attempt's figure as the file's
    newest progress line. The backfill keys on the crashed attempt's own
    span -- its run-start line plus its progress records -- so the stale
    tail is not that attempt's figure and records nothing: one crashed
    attempt's spend lands exactly once, however many progress-less
    retries follow."""
    from atlas_reviewer.service import _backfill_crashed_spend

    spend = _spend(tmp_path)
    event = PrEvent(REPO, 7, SHA_A)
    run = run_dir(tmp_path, event)
    run.mkdir(parents=True, exist_ok=True)
    _append_events(
        run / "events.jsonl",
        _run_start_record(attempt=1),
        _progress_record("2.20", 3),
    )
    telemetry = Telemetry(SystemClock())
    _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    assert spend.committed(REPO) == (Decimal("1.10"), "")
    # Two further attempts append their startup events and die
    # progress-less; neither re-arms the backfill on the stale tail.
    for attempt in (2, 3):
        _append_events(run / "events.jsonl", _run_start_record(attempt=attempt))
        _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    assert spend.committed(REPO) == (Decimal("1.10"), "")
    backs = [e for e in telemetry.events if e.step == "crashed spend"]
    assert len(backs) == 3
    assert backs[0].fields["measured"] == "backfilled"
    assert "no progress figure" in backs[1].error
    assert "no progress figure" in backs[2].error


def test_a_retry_s_identical_looking_progress_is_still_its_own(tmp_path):
    """The dedupe is attempt-scoped, not figure-scoped: a second attempt
    whose progress record is byte-identical to the first attempt's --
    `seq` restarts per run, so the fields can repeat exactly -- is a
    different attempt's spend, keyed by its own run-start line, and is
    recorded rather than deduplicated away."""
    from atlas_reviewer.service import _backfill_crashed_spend

    spend = _spend(tmp_path)
    event = PrEvent(REPO, 7, SHA_A)
    run = run_dir(tmp_path, event)
    run.mkdir(parents=True, exist_ok=True)
    _append_events(
        run / "events.jsonl",
        _run_start_record(attempt=1),
        _progress_record("2.20", 3),
    )
    telemetry = Telemetry(SystemClock())
    _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    assert spend.committed(REPO) == (Decimal("1.10"), "")
    # The second attempt dies after writing a byte-identical progress
    # record: a different attempt, a different key, its own record.
    # Each records its settled bill ($1.10), not the committed figure
    # ($2.20) that still includes an in-flight reservation.
    _append_events(
        run / "events.jsonl",
        _run_start_record(attempt=2),
        _progress_record("2.20", 3),
    )
    _backfill_crashed_spend(spend, tmp_path, event, telemetry)
    total, gap = spend.committed(REPO)
    assert gap == ""
    assert total == Decimal("2.20")


# ------------------------------- the installation store path (S10, part A)

_TENANT_KEY = "sk-tenant-fixture-not-a-real-key"
_INSTALLATION = 12345


def _installation_store(tmp_path: Path):
    from cryptography.fernet import Fernet

    from atlas_reviewer.installation_store import InstallationStore

    env = {"ATLAS_INSTALLATION_STORE_KEY": Fernet.generate_key().decode("ascii")}
    return InstallationStore.open(tmp_path, env)


def _installation_body(action="installation.deleted", installation=_INSTALLATION):
    return json.dumps({"action": action, "installation": {"id": installation}}).encode()


def test_an_installation_deleted_delivery_deletes_the_stored_state(tmp_path):
    """The uninstall rule (D81 §7 decision 8): the webhook deletes the
    installation's stored state -- credentials, cap and consent."""

    store = _installation_store(tmp_path)
    store.store_credentials(
        str(_INSTALLATION),
        "https://models.example.invalid/api/v1",
        _TENANT_KEY,
        "openai/gpt-4o",
    )
    store.set_cap(str(_INSTALLATION), Decimal("8.00"))
    store.record_consent(str(_INSTALLATION))
    result = _deliver(
        _config(tmp_path),
        Board(tmp_path / "queue.json"),
        _installation_body(),
        event="installation.deleted",
        installations=store,
    )
    assert result.status == 200
    assert store.load(str(_INSTALLATION)) is None


def test_an_installation_deleted_delivery_without_an_id_is_ignored_and_named(
    tmp_path,
):
    from atlas_reviewer.telemetry import Telemetry

    store = _installation_store(tmp_path)
    telemetry = Telemetry(SystemClock())
    result = _deliver(
        _config(tmp_path),
        Board(tmp_path / "queue.json"),
        _installation_body(installation=None),
        event="installation.deleted",
        telemetry=telemetry,
        installations=store,
    )
    assert result.status == 202
    assert result.detail == "ignored:shape"
    events = [e for e in telemetry.events if e.step == "installation deleted"]
    assert events and events[0].fields.get("reason") == "no-installation-id"


def test_an_installation_deleted_delivery_on_a_broken_store_answers_500(
    tmp_path,
):
    """A store the service cannot read right now must not swallow the
    deletion: the 500 makes GitHub re-deliver, so the deletion is
    retried instead of lost, and the gap is on the telemetry."""
    # A record on disk with no key configured: the broken store.
    from atlas_reviewer.installation_store import InstallationStore, store_root
    from atlas_reviewer.ledger import make_private_dirs
    from atlas_reviewer.telemetry import Telemetry

    make_private_dirs(store_root(tmp_path))
    (store_root(tmp_path) / f"{_INSTALLATION}.json").write_text("{}", encoding="utf-8")
    store = InstallationStore.open(tmp_path, {})
    assert store.broken_reason
    telemetry = Telemetry(SystemClock())
    result = _deliver(
        _config(tmp_path),
        Board(tmp_path / "queue.json"),
        _installation_body(),
        event="installation.deleted",
        telemetry=telemetry,
        installations=store,
    )
    assert result.status == 500
    events = [e for e in telemetry.events if e.step == "installation deleted"]
    assert events and events[0].status == "error"


def test_an_installation_deleted_delivery_on_an_unconfigured_store_answers_ok(
    tmp_path,
):
    """The unconfigured store never stored anything, so the deletion is
    already true and the answer is 200."""
    from atlas_reviewer.installation_store import InstallationStore

    store = InstallationStore.open(tmp_path, {})
    result = _deliver(
        _config(tmp_path),
        Board(tmp_path / "queue.json"),
        _installation_body(),
        event="installation.deleted",
        installations=store,
    )
    assert result.status == 200
    assert result.detail == "deleted:none-stored"


def test_a_pull_request_delivery_is_unaffected_by_the_store(tmp_path):
    store = _installation_store(tmp_path)
    board = Board(tmp_path / "queue.json")
    result = _deliver(_config(tmp_path), board, _body(), installations=store)
    assert result.status == 202
    assert result.detail == "queued"


def test_the_tenant_resolver_answers_none_without_credentials(tmp_path):
    from atlas_reviewer.service import _tenant_credentials_source

    store = _installation_store(tmp_path)
    source = _tenant_credentials_source(
        store, {"ATLAS_GITHUB_INSTALLATION_ID": str(_INSTALLATION)}
    )
    assert source() is None


def test_the_tenant_resolver_answers_the_stored_credentials_with_consent(tmp_path):
    from atlas_reviewer.service import _tenant_credentials_source

    store = _installation_store(tmp_path)
    store.store_credentials(
        str(_INSTALLATION),
        "https://models.example.invalid/api/v1",
        _TENANT_KEY,
        "openai/gpt-4o",
    )
    store.record_consent(str(_INSTALLATION))
    source = _tenant_credentials_source(
        store, {"ATLAS_GITHUB_INSTALLATION_ID": str(_INSTALLATION)}
    )
    credentials = source()
    assert credentials is not None
    assert credentials.key == _TENANT_KEY
    assert credentials.model == "openai/gpt-4o"


def test_the_tenant_resolver_refuses_credentials_without_consent(tmp_path):
    from atlas_reviewer.installation_store import ConsentNotAcknowledgedError
    from atlas_reviewer.service import _tenant_credentials_source

    store = _installation_store(tmp_path)
    store.store_credentials(
        str(_INSTALLATION),
        "https://models.example.invalid/api/v1",
        _TENANT_KEY,
        "openai/gpt-4o",
    )
    source = _tenant_credentials_source(
        store, {"ATLAS_GITHUB_INSTALLATION_ID": str(_INSTALLATION)}
    )
    with pytest.raises(ConsentNotAcknowledgedError) as exc:
        source()
    assert "consent" in str(exc.value)


def test_the_tenant_resolver_fails_closed_on_a_broken_store(tmp_path):
    from atlas_reviewer.installation_store import (
        InstallationStore,
        InstallationStoreError,
        store_root,
    )
    from atlas_reviewer.ledger import make_private_dirs
    from atlas_reviewer.service import _tenant_credentials_source

    make_private_dirs(store_root(tmp_path))
    (store_root(tmp_path) / f"{_INSTALLATION}.json").write_text("{}", encoding="utf-8")
    store = InstallationStore.open(tmp_path, {})
    source = _tenant_credentials_source(
        store, {"ATLAS_GITHUB_INSTALLATION_ID": str(_INSTALLATION)}
    )
    with pytest.raises(InstallationStoreError):
        source()


def test_a_broken_store_refuses_a_delivery_at_admission(tmp_path):
    """The cap check rides the admission: a store that cannot be read is
    an unknown cap, so the delivery is refused there, with the store's
    own label, and nothing reads like a clean review."""
    from atlas_reviewer.budget import DailySpend
    from atlas_reviewer.installation_store import (
        InstallationStore,
        store_root,
    )
    from atlas_reviewer.ledger import make_private_dirs

    make_private_dirs(store_root(tmp_path))
    (store_root(tmp_path) / f"{_INSTALLATION}.json").write_text("{}", encoding="utf-8")
    store = InstallationStore.open(tmp_path, {})
    assert store.broken_reason
    spend = DailySpend(tmp_path, Decimal("100.00"), cap_for=store.installation_cap())
    result = _deliver(
        _config(tmp_path),
        Board(tmp_path / "queue.json"),
        _body(),
        spend=spend,
    )
    assert result.status == 202
    assert result.detail == "ignored:installation-store"


def test_the_serve_log_scrubs_the_store_key(tmp_path):
    """The store key is a service secret: it is in the parent env only,
    and the log scrubber covers it like the other credentials."""
    from cryptography.fernet import Fernet

    import atlas_reviewer.service as service_mod

    key = Fernet.generate_key().decode("ascii")
    scrubbed = service_mod._service_secrets(
        _config(tmp_path), {"ATLAS_INSTALLATION_STORE_KEY": key}
    )
    assert key in scrubbed


def test_the_parent_record_loses_a_child_stderr_tenant_key(tmp_path, monkeypatch):
    """The Major-1 pin (r1 review of #776): the child's stderr tail lands
    in the `review failed` record, and the parent's redaction must lose
    the tenant key from it even though the key is not in the parent
    env -- the run registers it with the shared holder before the child
    starts, and the fake child here writes the key unscrubbed."""
    import atlas_reviewer.service as service_mod
    from atlas_reviewer.installation_store import InstallationStore
    from atlas_reviewer.service_run import RunConfig, RunSecrets, make_runner

    tenant_key = "sk-tenant-fixture-not-a-real-key"
    env = {
        "ATLAS_GITHUB_INSTALLATION_ID": str(_INSTALLATION),
        "ATLAS_INSTALLATION_STORE_KEY": Fernet.generate_key().decode("ascii"),
        "PATH": "/usr/bin",
    }
    store = InstallationStore.open(tmp_path, env)
    store.store_credentials(
        str(_INSTALLATION),
        "https://models.example.invalid/api/v1",
        tenant_key,
        "openai/gpt-4o",
    )
    store.record_consent(str(_INSTALLATION))

    class _Proc:
        def __init__(self) -> None:
            self._polls = 0

        def poll(self):
            self._polls += 1
            if self._polls > 1:
                return 3
            return None

        def send_signal(self, _sig):
            return None

        def wait(self, timeout=None):
            return 3

        def kill(self):
            return None

    def fake_popen(argv, env, stdout, stderr):
        stderr.write(
            "Traceback (most recent call last): the tenant endpoint served "
            f"'{tenant_key}', not 'openai/gpt-4o'\n".encode()
        )
        stderr.flush()
        return _Proc()

    holder = RunSecrets()
    runner = make_runner(
        RunConfig("openrouter", True, tmp_path),
        env,
        popen=fake_popen,
        read_token=lambda _env, _event: ("ghs_readonly", ""),
        tenant_source=service_mod._tenant_credentials_source(store, env),
        tenant_secrets=holder,
    )
    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))

    def serve_forever(self, poll_interval=0.5):
        path = tmp_path / "service.jsonl"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.is_file() and "review failed" in path.read_text(encoding="utf-8"):
                return
            time.sleep(0.02)

    monkeypatch.setattr(service_mod.ReviewServer, "serve_forever", serve_forever)
    config = ServiceConfig(
        secret=SECRET,
        allowlist=frozenset({REPO}),
        state_dir=tmp_path,
        host="127.0.0.1",
        port=0,
    )
    assert (
        serve(config, env, runner=runner, log=lambda line: None, run_secrets=holder)
        == 0
    )
    text = (tmp_path / "service.jsonl").read_text(encoding="utf-8")
    assert "review failed" in text
    assert tenant_key not in text
    assert "[REDACTED" in text


def test_the_sweep_boot_log_names_the_skipped_strays(tmp_path):
    """The Minor-2 pin at the boot level: the sweep's log names both the
    records it deleted and the non-record entries it skipped, and the
    sweep still runs past them."""
    from atlas_reviewer.installation_store import InstallationRecord, store_root
    from atlas_reviewer.service import _retention_sweep

    store = _installation_store(tmp_path)
    record = store.store_credentials(
        str(_INSTALLATION),
        "https://models.example.invalid/api/v1",
        _TENANT_KEY,
        "openai/gpt-4o",
    )

    store._write_record(
        str(_INSTALLATION),
        lambda _current: InstallationRecord(
            record.installation_id,
            record.base_url,
            record.key,
            record.model,
            None,
            None,
            record.updated_at - timedelta(days=31),
        ),
    )
    (store_root(tmp_path) / f"{_INSTALLATION}.json.writing").write_text(
        "{torn", encoding="utf-8"
    )
    config = dataclass_replace(_config(tmp_path), installation_retention_days=30)
    lines: list[str] = []
    _retention_sweep(store, config, lines.append)
    assert any("deleted 1 record(s)" in line for line in lines)
    assert any("skipped 1 non-record file(s)" in line for line in lines)
    assert store.load(str(_INSTALLATION)) is None


def test_the_worker_runs_on_the_source_chosen_at_claim_time(tmp_path):
    """The runner sees the chosen source, and the context is clear again
    after the review. Kills a worker that probes and then forgets to hand
    the choice to the child."""
    from atlas_reviewer.funding import (
        FundingSelector,
        active_choice,
        load_funding_sources,
    )
    from atlas_reviewer.pricing import KeyStatus

    document = json.dumps(
        [
            {
                "name": "subs-a",
                "key_env": "ATLAS_FUNDING_SUBS_A",
                "providers": ["anthropic"],
                "require_zdr": False,
                "model_filter": "*",
                "key_ceiling_usd": "195",
                "byok": True,
            }
        ]
    )
    env = {
        "ATLAS_FUNDING_SOURCES": document,
        "ATLAS_FUNDING_SUBS_A": "sk-or-v1-subs-a",
    }
    sources = load_funding_sources(env)
    assert sources is not None
    selector = FundingSelector(
        sources,
        env,
        lambda key: KeyStatus(Decimal(50), Decimal(40), Decimal(0), True),
        "anthropic/claude-sonnet-5.5",
    )
    seen: list[object] = []

    def runner(event, cancel):
        seen.append(active_choice.get())
        return ReviewRun(True, REPORT)

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert _worker(board, runner, root=tmp_path, funding=selector).run_one() is True
    choice = seen[0]
    assert choice is not None
    assert choice.name == "subs-a"  # type: ignore[attr-defined]
    assert choice.key == "sk-or-v1-subs-a"  # type: ignore[attr-defined]
    assert active_choice.get() is None


def test_a_tenant_claim_does_not_probe_the_operator_list(tmp_path):
    """A tenant run never reads the operator source list. Kills a worker
    that selects an operator source and then also runs the tenant path."""
    from atlas_reviewer.funding import (
        FundingSelector,
        active_choice,
        load_funding_sources,
    )

    document = json.dumps(
        [
            {
                "name": "subs-a",
                "key_env": "ATLAS_FUNDING_SUBS_A",
                "providers": ["anthropic"],
                "require_zdr": False,
                "model_filter": "*",
                "key_ceiling_usd": "195",
                "byok": True,
            }
        ]
    )
    env = {
        "ATLAS_FUNDING_SOURCES": document,
        "ATLAS_FUNDING_SUBS_A": "sk-or-v1-subs-a",
    }
    sources = load_funding_sources(env)
    assert sources is not None

    def probe(key):
        raise AssertionError(f"a tenant claim probed {key}")

    seen: list[object] = []

    def runner(event, cancel):
        seen.append(active_choice.get())
        return ReviewRun(True, REPORT)

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    worker = _worker(
        board,
        runner,
        root=tmp_path,
        funding=FundingSelector(sources, env, probe, "anthropic/claude-sonnet-5.5"),
        tenant_active=lambda: True,
    )
    assert worker.run_one() is True
    assert seen == [None]


def test_every_source_refused_posts_the_error_and_does_not_start_a_child(tmp_path):
    """No source has credit, so the D92 error is posted and the runner
    never starts. Kills starting a child on a dry list, and failing the
    job with no post."""
    from atlas_reviewer.funding import FundingSelector, load_funding_sources
    from atlas_reviewer.ports import KEY_OUT_OF_CREDIT
    from atlas_reviewer.pricing import KeyStatus

    document = json.dumps(
        [
            {
                "name": "subs-a",
                "key_env": "ATLAS_FUNDING_SUBS_A",
                "providers": ["anthropic"],
                "require_zdr": False,
                "model_filter": "*",
                "key_ceiling_usd": "195",
                "byok": True,
            }
        ]
    )
    env = {
        "ATLAS_FUNDING_SOURCES": document,
        "ATLAS_FUNDING_SUBS_A": "sk-or-v1-subs-a",
    }
    sources = load_funding_sources(env)
    assert sources is not None
    posted: list[str] = []

    def publisher(event, report):
        posted.append(report.review_error)
        return True

    def runner(event, cancel):
        raise AssertionError("a dry list must not start a child")

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    worker = _worker(
        board,
        runner,
        publisher=publisher,
        root=tmp_path,
        funding=FundingSelector(
            sources,
            env,
            lambda key: KeyStatus(Decimal(10), Decimal(0), Decimal(10), True),
            "anthropic/claude-sonnet-5.5",
        ),
    )
    assert worker.run_one() is True
    assert posted == [KEY_OUT_OF_CREDIT]
    assert board.states() == ((SHA_A, JobState.DONE),)


def test_an_unreadable_installation_store_does_not_select_an_operator_source(
    tmp_path,
):
    """A store the parent cannot read fails the review. It does not fall
    through to the operator list. Kills that fallback."""
    from atlas_reviewer.funding import FundingSelector, load_funding_sources
    from atlas_reviewer.installation_store import InstallationStoreError

    document = json.dumps(
        [
            {
                "name": "subs-a",
                "key_env": "ATLAS_FUNDING_SUBS_A",
                "providers": ["anthropic"],
                "require_zdr": False,
                "model_filter": "*",
                "key_ceiling_usd": "195",
                "byok": True,
            }
        ]
    )
    env = {
        "ATLAS_FUNDING_SOURCES": document,
        "ATLAS_FUNDING_SUBS_A": "sk-or-v1-subs-a",
    }
    sources = load_funding_sources(env)
    assert sources is not None

    def probe(key):
        raise AssertionError("a broken store must not probe an operator key")

    def runner(event, cancel):
        raise AssertionError("a broken store must not start a child")

    def tenant_active():
        raise InstallationStoreError("the installation record did not decrypt")

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    worker = _worker(
        board,
        runner,
        root=tmp_path,
        funding=FundingSelector(sources, env, probe, "anthropic/claude-sonnet-5.5"),
        tenant_active=tenant_active,
    )
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.FAILED),)


def _funding_pair():
    from atlas_reviewer.funding import FundingSelector, load_funding_sources
    from atlas_reviewer.pricing import KeyStatus

    document = json.dumps(
        [
            {
                "name": "subs-a",
                "key_env": "ATLAS_FUNDING_SUBS_A",
                "providers": ["anthropic"],
                "require_zdr": False,
                "model_filter": "*",
                "key_ceiling_usd": "195",
                "byok": True,
            },
            {
                "name": "subs-b",
                "key_env": "ATLAS_FUNDING_SUBS_B",
                "providers": ["anthropic"],
                "require_zdr": False,
                "model_filter": "*",
                "key_ceiling_usd": "195",
                "byok": True,
            },
        ]
    )
    env = {
        "ATLAS_FUNDING_SOURCES": document,
        "ATLAS_FUNDING_SUBS_A": "sk-or-v1-subs-a-secret",
        "ATLAS_FUNDING_SUBS_B": "sk-or-v1-subs-b-secret",
    }
    sources = load_funding_sources(env)
    assert sources is not None
    return FundingSelector(
        sources,
        env,
        lambda key: KeyStatus(Decimal(50), Decimal(40), Decimal(0), True),
        "anthropic/claude-sonnet-5.5",
    )


def _refused_report(settled: str, cause: str = KEY_OUT_OF_CREDIT) -> ReviewReport:
    return ReviewReport(
        (),
        (),
        "",
        (),
        (),
        (f"Model calls: 1; settled: ${settled}; held at reservation: $0.",),
        "",
        review_error=cause,
        coverage_complete=False,
    )


@pytest.mark.parametrize("cause", [KEY_OUT_OF_CREDIT, KEY_AUTH_REFUSED])
def test_a_key_refusal_requeues_once_and_posts_only_when_every_source_refused(
    tmp_path, cause
):
    """One claim tries one source. A refusal records the bill, puts the
    same head back, and posts nothing. The next claim uses the next
    source. The last refusal is the D92 post. Both D92 causes advance.
    Kills trying the next source inside the same claim, posting the
    intermediate error, and dropping ``KEY_AUTH_REFUSED`` from the
    advance gate."""
    from atlas_reviewer.funding import active_choice

    seen: list[str] = []

    def runner(event, cancel):
        choice = active_choice.get()
        assert choice is not None
        seen.append(choice.name)
        settled = "1.00" if choice.name == "subs-a" else "0.25"
        return ReviewRun(True, _refused_report(settled, cause))

    posted: list[str] = []

    def publisher(event, report):
        posted.append(report.review_error)
        return True

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    spend = _spend(tmp_path)
    worker = _worker(
        board,
        runner,
        publisher=publisher,
        root=tmp_path,
        spend=spend,
        funding=_funding_pair(),
    )
    assert worker.run_one() is True
    assert seen == ["subs-a"]
    assert posted == []
    assert board.states() == ((SHA_A, JobState.QUEUED),)
    assert worker.run_one() is True
    assert seen == ["subs-a", "subs-b"]
    assert posted == [cause]
    assert board.states() == ((SHA_A, JobState.DONE),)
    advances = [
        event for event in worker._telemetry.events if event.step == "refusal advance"
    ]
    assert len(advances) == 1
    assert advances[0].fields["source"] == "subs-a"
    assert advances[0].fields["cause"] == cause
    assert "sk-or" not in str(advances[0].fields)
    total, gap = spend.committed(REPO)
    assert gap == ""
    assert total == Decimal("1.25")


def test_a_requeued_refusal_does_not_bill_the_first_attempt_again(tmp_path):
    """Attempt 1 leaves progress in the run dir and is billed from the
    draft. The re-queue drops that dir. Attempt 2 dies before its own
    progress record, and the ledger stays at attempt 1's bill. Kills
    the crash backfill and the failed-attempt progress read both
    counting attempt 1 a second time."""
    from atlas_reviewer.funding import active_choice

    def runner(event, cancel):
        choice = active_choice.get()
        assert choice is not None
        if choice.name == "subs-a":
            run = run_dir(tmp_path, event)
            run.mkdir(parents=True, exist_ok=True)
            _append_events(
                run / "events.jsonl",
                _run_start_record(),
                _progress_record("2.20", 3),
            )
            return ReviewRun(True, _refused_report("1.00"))
        return ReviewRun(False, error="died before a progress record")

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    spend = _spend(tmp_path)
    worker = _worker(board, runner, root=tmp_path, spend=spend, funding=_funding_pair())
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.QUEUED),)
    assert not run_dir(tmp_path, PrEvent(REPO, 7, SHA_A)).exists()
    first, first_gap = spend.committed(REPO)
    assert first_gap == ""
    assert first == Decimal("1.00")
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.FAILED),)
    total, gap = spend.committed(REPO)
    assert gap == ""
    assert total == Decimal("1.00")


def test_a_tenant_refusal_and_a_failed_run_do_not_advance_to_another_source(
    tmp_path,
):
    """A tenant review's key refusal is posted, not moved onto an
    operator source. A run that failed for another reason stays failed.
    Kills advancing either of those."""
    from atlas_reviewer.funding import active_choice
    from atlas_reviewer.ports import KEY_OUT_OF_CREDIT

    posted: list[str] = []

    def publisher(event, report):
        posted.append(report.review_error)
        return True

    def tenant_runner(event, cancel):
        assert active_choice.get() is None
        return ReviewRun(True, _refused_report("0.10"))

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    selector = _funding_pair()
    worker = _worker(
        board,
        tenant_runner,
        publisher=publisher,
        root=tmp_path,
        funding=selector,
        tenant_active=lambda: True,
    )
    assert worker.run_one() is True
    assert posted == [KEY_OUT_OF_CREDIT]
    assert board.states() == ((SHA_A, JobState.DONE),)

    def failed(event, cancel):
        return ReviewRun(False, error="review exited 1")

    other = Board(tmp_path / "other.json")
    other.enqueue(PrEvent(REPO, 8, SHA_B))
    failed_worker = _worker(other, failed, root=tmp_path, funding=selector)
    assert failed_worker.run_one() is True
    assert other.states() == ((SHA_B, JobState.FAILED),)


def test_a_finished_review_on_a_funding_source_is_not_requeued(tmp_path):
    """A review that ran is posted. A 429, or any other non-refusal,
    does not move the head to the next source. Kills advancing every
    finished review."""
    calls = {"n": 0}

    def runner(event, cancel):
        calls["n"] += 1
        return ReviewRun(True, REPORT)

    posted: list[str] = []

    def publisher(event, report):
        posted.append(report.review_error)
        return True

    board = Board(tmp_path / "queue.json")
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    worker = _worker(
        board, runner, publisher=publisher, root=tmp_path, funding=_funding_pair()
    )
    assert worker.run_one() is True
    assert calls["n"] == 1
    assert posted == [""]
    assert board.states() == ((SHA_A, JobState.DONE),)
