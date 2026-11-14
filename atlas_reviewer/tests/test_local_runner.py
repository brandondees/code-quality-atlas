# SPDX-License-Identifier: MIT
"""`LocalTasks`: the Tasks API a dry run's keepalive hold talks to, on a
unix socket in this process. `LocalSprites` itself is exercised by the
bridge, lens-loop, keepalive and end-to-end suites; this file pins the
socket server's own behavior."""

import socket

from atlas_reviewer.keepalive import SocketTaskClient
from atlas_reviewer.local_runner import LocalTasks
from atlas_reviewer.ports import BoundaryError


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
