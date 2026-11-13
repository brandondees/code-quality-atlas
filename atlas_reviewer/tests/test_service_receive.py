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
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.redact import Redactor
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
REPO = "brandondees/code-quality-atlas"
OTHER = "other/repo"
REPORT = ReviewReport(
    ("tracing",), ("concurrency: over budget",), "note", (), (), (), "COMMENT"
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
):
    headers = {"X-GitHub-Event": event}
    if signature is None:
        headers["X-Hub-Signature-256"] = _sign(body)
    elif signature:
        headers["X-Hub-Signature-256"] = signature
    return handle_delivery(method, path, headers, body, config, board, worker=worker)


def _worker(board, runner, publisher=None, root=None):
    return Worker(
        board,
        runner,
        Telemetry(SystemClock()),
        publisher,
        state_root=root,
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
    calls = []

    def publish(event, report):
        calls.append(event.head_sha)
        raise PostNotCurrent("moved")

    worker = _worker(
        board, lambda event, cancel: ReviewRun(True, REPORT), publish, tmp_path
    )
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert worker.run_one() is True
    worker._retry_post()
    assert calls == [SHA_A]
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)


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
    real = board.finish

    def finish(current, state):
        current.superseded = True
        return real(current, state)

    board.finish = finish
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
        real = board.finish

        def finish(job, state):
            finishes.append(state)
            return real(job, state)

        board.finish = finish
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
    real = board.finish

    def finish(job, state):
        finishes.append(state)
        return real(job, state)

    board.finish = finish
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
    real = board.finish

    def finish(job, state):
        job.superseded = True
        return real(job, state)

    monkeypatch.setattr(board, "finish", finish)
    assert worker.run_one() is True
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)
    assert not directory.exists()


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
