# SPDX-License-Identifier: MIT
"""`LocalTasks`: the Tasks API a dry run's keepalive hold talks to, on a
unix socket in this process. `LocalSprites` itself is exercised by the
bridge, lens-loop, keepalive and end-to-end suites; this file pins the
socket server's own behavior."""

import socket
import time

from atlas_reviewer.keepalive import SocketTaskClient
from atlas_reviewer.local_runner import LocalSprites, LocalTasks
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.runner import exec_argv


def client(tmp_path):
    tasks = LocalTasks(tmp_path / "tasks.sock")
    tasks.start()
    return tasks, SocketTaskClient(socket_path=str(tasks.path))


def test_create_refresh_and_delete_round_trip(tmp_path):
    tasks, tasks_api = client(tmp_path)
    try:
        tasks_api.create("atlas-lens-ab")
        tasks_api.refresh("atlas-lens-ab")
        tasks_api.delete("atlas-lens-ab")
        assert tasks.tasks == {}
    finally:
        tasks.close()
    assert not tasks.path.exists()


def test_a_delete_of_a_missing_task_counts_as_already_gone(tmp_path):
    tasks, tasks_api = client(tmp_path)
    try:
        tasks_api.delete("atlas-lens-ab")
    finally:
        tasks.close()


def test_a_duplicate_create_is_refused(tmp_path):
    tasks, tasks_api = client(tmp_path)
    try:
        tasks_api.create("atlas-lens-ab")
        try:
            tasks_api.create("atlas-lens-ab")
        except BoundaryError:
            pass
        else:
            raise AssertionError("the duplicate create was accepted")
    finally:
        tasks.close()


def test_an_unknown_method_is_refused(tmp_path):
    tasks, _tasks_api = client(tmp_path)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(str(tasks.path))
        sock.sendall(
            b"GET /v1/tasks/atlas-lens-ab HTTP/1.1\r\nHost: sprite\r\n"
            b"Content-Length: 0\r\nConnection: close\r\n\r\n"
        )
        line = sock.recv(64).split(b"\r\n", 1)[0]
        assert line.endswith(b" 400 ERR")
        sock.close()
    finally:
        tasks.close()


def test_an_exec_finishing_inside_its_budget_answers():
    api = LocalSprites()
    api.create("cqa-rev-test-abc")
    try:
        raw = api.exec("cqa-rev-test-abc", exec_argv("echo atlas-ok", 0), b"", 10)
        assert b"atlas-ok" in raw
    finally:
        api.delete("cqa-rev-test-abc")


def test_an_exec_that_outlives_its_budget_is_a_boundary_error_not_a_crash():
    """The budget is the subprocess's own timeout, so a hung script ends at
    its budget with the failure a live runner reports, and the review
    fails closed instead of dying on an uncaught `TimeoutExpired`."""
    api = LocalSprites()
    api.create("cqa-rev-test-abc")
    try:
        started = time.monotonic()
        try:
            api.exec("cqa-rev-test-abc", exec_argv("exec sleep 5", 0), b"", 1)
        except BoundaryError as exc:
            assert "did not finish within its 1s budget" in str(exc)
        else:
            raise AssertionError("the over-budget exec was answered")
        assert time.monotonic() - started < 10
    finally:
        api.delete("cqa-rev-test-abc")
