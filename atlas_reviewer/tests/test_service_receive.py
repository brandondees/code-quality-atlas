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
from atlas_reviewer.service import (
    PostAuthError,
    PostNotCurrent,
    RateLimited,
    ReviewServer,
    ServiceConfig,
    ServiceError,
    Worker,
    _state_is_writable,
    before_send,
    config_from_env,
    handle_delivery,
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
):
    headers = {"X-GitHub-Event": event}
    if signature is None:
        headers["X-Hub-Signature-256"] = _sign(body)
    elif signature:
        headers["X-Hub-Signature-256"] = signature
    return handle_delivery(method, path, headers, body, config, board)


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
    assert board.states() == ((SHA_A, JobState.SUPERSEDED),)


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
                "ATLAS_SERVICE_PORT": "8081",
                "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
            }
        )
    config = config_from_env(
        {
            "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
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
