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
from http.client import HTTPConnection
from pathlib import Path

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.service import (
    ReviewServer,
    ServiceConfig,
    ServiceError,
    Worker,
    _state_is_writable,
    config_from_env,
    handle_delivery,
)
from atlas_reviewer.service_admit import signature_matches
from atlas_reviewer.service_queue import Board, Enqueue, JobState, QueueError
from atlas_reviewer.service_run import ReviewReport, ReviewRun
from atlas_reviewer.telemetry import Telemetry

SECRET = "webhook-secret-value"
SHA_A = "a" * 40
SHA_B = "b" * 40
REPO = "brandondees/code-quality-atlas"
OTHER = "other/repo"
REPORT = ReviewReport(
    ("tracing",), ("concurrency: over budget",), "note", (), (), (), "COMMENT"
)


def _body(action="opened", *, draft=False, repo=REPO, number=7, sha=SHA_A):
    return json.dumps(
        {
            "action": action,
            "repository": {"full_name": repo},
            "pull_request": {
                "number": number,
                "draft": draft,
                "head": {"sha": sha},
                "base": {"repo": {"full_name": repo}},
            },
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

    def runner(event, cancel):
        if event.head_sha == SHA_A:
            started.set()
            assert cancel.wait(2)
            return ReviewRun(True, REPORT)
        return ReviewRun(True, REPORT)

    def publish(event, report):
        posted.append(event.head_sha)

    worker = _worker(board, runner, publish, tmp_path)
    worker.start()
    assert board.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.QUEUED
    assert started.wait(2)
    assert board.enqueue(PrEvent(REPO, 7, SHA_B)) is Enqueue.QUEUED
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and posted != [SHA_B]:
        time.sleep(0.01)
    worker.stop()
    assert posted == [SHA_B]
    assert (SHA_A, JobState.SUPERSEDED) in board.states()
    assert (SHA_B, JobState.DONE) in board.states()
    assert board.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.STALE


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

    def runner(event, cancel):
        started.set()
        assert cancel.wait(2)
        return ReviewRun(False, error="superseded")

    worker = _worker(board, runner)
    worker.start()
    board.enqueue(PrEvent(REPO, 7, SHA_A))
    assert started.wait(2)
    worker.stop()
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
    assert loaded.enqueue(PrEvent(REPO, 7, SHA_A)) is Enqueue.DUPLICATE


def test_the_module_refuses_to_start_without_a_secret():
    env = os.environ.copy()
    env["ATLAS_GITHUB_WEBHOOK_SECRET"] = ""
    env["ATLAS_SERVICE_PROVIDER"] = "offline"
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
