# SPDX-License-Identifier: MIT
"""Sprite task hold. No live Sprite call: a fake unix socket, and the
same socket reached by the guest script through `LocalSprites`."""

import socket
import threading
from pathlib import Path

import pytest

from atlas_reviewer.fakes import MemoryLedger
from atlas_reviewer.keepalive import (
    EXPIRE,
    REFRESH_S,
    ExecTaskClient,
    LensHold,
    SocketTaskClient,
    lens_hold,
    task_name,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.runner import run_session

from .helpers import FakeClock, LocalSprites

NAME = "atlas-lens-ab"


class Recording:
    def __init__(self, fail: str = "") -> None:
        self.events: list[str] = []
        self.fail = fail

    def create(self, name: str) -> None:
        self._call("create", name)

    def refresh(self, name: str) -> None:
        self._call("refresh", name)

    def delete(self, name: str) -> None:
        self._call("delete", name)

    def _call(self, kind: str, name: str) -> None:
        if kind == "refresh" and "delete" in self.events:
            raise AssertionError("refresh after delete")
        self.events.append(kind)
        if kind == self.fail:
            raise BoundaryError(f"{kind} failed")
        assert name == NAME


class TaskServer:
    """The Tasks API, on a unix socket, just enough to answer the hold."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.order: list[str] = []
        self.requests: list[tuple[str, str, str, bytes]] = []
        self.tasks: dict[str, str] = {}
        self.fail: str = ""
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if path.exists():
            path.unlink()
        self._sock.bind(str(path))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=2)
        self.path.unlink(missing_ok=True)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                self._handle(conn)
            finally:
                conn.close()

    def _handle(self, conn: socket.socket) -> None:
        head, body = _read(conn)
        line = head.split(b"\r\n", 1)[0].decode()
        method, target, _version = line.split(" ", 2)
        self.order.append(method)
        self.requests.append((method, target, head.decode(), body))
        status = 500 if method == self.fail else self._apply(method, target, body)
        reason = "OK" if status < 300 else "ERR"
        conn.sendall(
            f"HTTP/1.1 {status} {reason}\r\nContent-Length: 0\r\n"
            "Connection: close\r\n\r\n".encode()
        )

    def _apply(self, method: str, target: str, body: bytes) -> int:
        if method == "POST":
            name = _json_name(body)
            if name in self.tasks:
                return 409
            self.tasks[name] = body.decode()
            return 201
        name = target.rsplit("/", 1)[-1]
        if method == "PUT":
            if name not in self.tasks:
                return 404
            self.tasks[name] = body.decode()
            return 200
        if method == "DELETE":
            self.tasks.pop(name, None)
            return 204
        return 400


def _json_name(body: bytes) -> str:
    import json

    data = json.loads(body)
    return str(data["name"])


def _read(conn: socket.socket) -> tuple[bytes, bytes]:
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    head, rest = bytes(buf).split(b"\r\n\r\n", 1)
    length = 0
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(rest) < length:
        chunk = conn.recv(4096)
        if not chunk:
            break
        rest += chunk
    return head, rest[:length]


def socket_path(tmp_path: Path) -> Path:
    path = tmp_path / "t.sock"
    if len(str(path)) < 100:
        return path
    short = Path(f"/tmp/atlas-{tmp_path.name[:12]}.sock")
    short.unlink(missing_ok=True)
    return short


@pytest.fixture
def server(tmp_path: Path):
    task = TaskServer(socket_path(tmp_path))
    task.start()
    try:
        yield task
    finally:
        task.close()


def _once(seconds: float, seen: list[float]) -> bool:
    seen.append(seconds)
    return len(seen) > 1


# ----------------------------------------------------------------- the hold


def test_the_default_refresh_is_sixty_seconds_and_the_expiry_is_five_minutes():
    assert REFRESH_S == 60
    assert EXPIRE == "5m"


def test_the_heartbeat_waits_the_refresh_interval_then_refreshes():
    seen: list[float] = []
    client = Recording()
    hold = LensHold(
        client, NAME, refresh_s=15, wait=lambda seconds: _once(seconds, seen)
    )
    hold._held = True
    hold._beat()
    assert seen == [15, 15]
    assert client.events == ["refresh"]


def test_a_refresh_after_the_hold_stops_does_not_recreate_it():
    client = Recording()
    with LensHold(client, NAME) as hold:
        assert client.events == ["create"]
    hold.refresh()
    assert client.events == ["create", "delete"]


def test_a_finished_lens_deletes_the_hold_last():
    client = Recording()
    order: list[str] = []
    with LensHold(client, NAME) as hold:
        order.append("body")
        thread = hold._thread
    assert client.events == ["create", "delete"]
    assert order == ["body"]
    assert thread is not None and not thread.is_alive()
    hold._release()
    assert client.events == ["create", "delete"]


def test_a_raised_error_still_deletes_the_hold():
    client = Recording()
    with pytest.raises(RuntimeError, match="boom"), LensHold(client, NAME):
        raise RuntimeError("boom")
    assert client.events == ["create", "delete"]


def test_cancellation_still_deletes_the_hold():
    client = Recording()
    with pytest.raises(KeyboardInterrupt), LensHold(client, NAME):
        raise KeyboardInterrupt
    assert client.events == ["create", "delete"]


def test_a_failed_refresh_is_raised_and_the_hold_is_still_deleted():
    client = Recording(fail="refresh")
    with pytest.raises(BoundaryError, match="refresh"), LensHold(client, NAME) as hold:
        hold.refresh()
    assert client.events == ["create", "refresh", "delete"]


def test_a_heartbeat_refresh_failure_is_raised_on_exit_after_delete():
    seen: list[float] = []
    client = Recording(fail="refresh")
    with (
        pytest.raises(BoundaryError, match="refresh"),
        LensHold(client, NAME, wait=lambda seconds: _once(seconds, seen)),
    ):
        pass
    assert client.events[-1] == "delete"
    assert "refresh" in client.events


def test_a_failed_create_does_not_run_the_lens_or_delete():
    client = Recording(fail="create")
    with pytest.raises(BoundaryError, match="create"), LensHold(client, NAME):
        raise AssertionError("the lens ran without a hold")
    assert client.events == ["create"]


def test_a_task_name_outside_the_closed_shape_is_refused():
    with pytest.raises(BoundaryError, match="task name"):
        task_name("../etc")


def test_the_client_refuses_a_bad_task_name_before_it_touches_the_socket(
    server: TaskServer,
):
    client = SocketTaskClient(str(server.path))
    with pytest.raises(BoundaryError, match="task name"):
        client.create("../etc")
    assert server.order == []


def test_a_heartbeat_that_fails_to_start_still_deletes_the_hold(monkeypatch):
    def boom(self):
        raise RuntimeError("start")

    monkeypatch.setattr(threading.Thread, "start", boom)
    client = Recording()
    with pytest.raises(RuntimeError, match="start"), LensHold(client, NAME):
        raise AssertionError("the lens ran")
    assert client.events == ["create", "delete"]


def test_a_socket_reply_with_no_status_is_refused(tmp_path):
    path = socket_path(tmp_path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)

    def once():
        conn, _addr = listener.accept()
        conn.recv(65536)
        conn.sendall(b"nope\r\n")
        conn.close()
        listener.close()

    threading.Thread(target=once).start()
    with pytest.raises(BoundaryError, match="no status"):
        SocketTaskClient(str(path)).create(NAME)


# --------------------------------------------------------------- the socket


def test_the_socket_hold_is_a_five_minute_task_and_is_deleted(server: TaskServer):
    client = SocketTaskClient(str(server.path))
    with LensHold(client, NAME) as hold:
        assert server.order == ["POST"]
        hold.refresh()
        method, target, head, body = server.requests[0]
        _put, put_target, _head, put_body = server.requests[1]
    assert (method, target) == ("POST", "/v1/tasks")
    assert "Host: sprite" in head
    assert "authorization" not in head.lower()
    assert f'"expire": "{EXPIRE}"' in body.decode()
    assert f'"name": "{NAME}"' in body.decode()
    assert put_target == f"/v1/tasks/{NAME}"
    assert put_body.decode() == f'{{"expire": "{EXPIRE}"}}'
    assert server.order == ["POST", "PUT", "DELETE"]
    assert server.tasks == {}


def test_a_refresh_http_failure_deletes_the_socket_hold(server: TaskServer):
    server.fail = "PUT"
    client = SocketTaskClient(str(server.path))
    with pytest.raises(BoundaryError, match="HTTP 500"), LensHold(client, NAME) as hold:
        hold.refresh()
    assert server.order == ["POST", "PUT", "DELETE"]
    assert server.tasks == {}


def test_a_create_http_failure_does_not_leave_a_task(server: TaskServer):
    server.fail = "POST"
    client = SocketTaskClient(str(server.path))
    with pytest.raises(BoundaryError, match="HTTP 500"), LensHold(client, NAME):
        raise AssertionError("the lens ran")
    assert server.tasks == {}
    assert server.order == ["POST"]


# ---------------------------------------------------------- through a Sprite


def test_local_sprites_acquire_and_delete_the_hold_around_the_lens(tmp_path, server):
    order: list[str] = []

    def body(session):
        with lens_hold(session, "ab", str(server.path)):
            order.append("body")
        return "done"

    report = run_session(
        LocalSprites(), MemoryLedger(), body,
        name="cqa-rev-hold", deadline_s=30, clock=FakeClock(),
    )  # fmt: skip
    assert report.note == "done"
    assert order == ["body"]
    assert server.order[0] == "POST"
    assert server.order[-1] == "DELETE"
    assert "body" not in server.order
    assert server.tasks == {}
    posted = server.requests[0][3].decode()
    assert '"name": "atlas-lens-ab"' in posted


def test_a_local_sprites_refresh_failure_still_deletes_the_hold(tmp_path, server):
    server.fail = "PUT"
    caught: list[str] = []

    def body(session):
        try:
            with lens_hold(session, "ab", str(server.path)) as hold:
                hold.refresh()
        except BoundaryError as exc:
            caught.append(str(exc))
        return "done"

    run_session(
        LocalSprites(), MemoryLedger(), body,
        name="cqa-rev-hold", deadline_s=30, clock=FakeClock(),
    )  # fmt: skip
    assert caught and "exit" in caught[0]
    assert server.order[0] == "POST"
    assert "PUT" in server.order
    assert server.order[-1] == "DELETE"
    assert server.tasks == {}


def test_the_exec_client_is_what_the_runner_uses(tmp_path, server):
    seen: list[str] = []

    def body(session):
        client = ExecTaskClient(session, str(server.path))
        assert isinstance(client, ExecTaskClient)
        with LensHold(client, NAME):
            seen.extend(api.argv_seen)
        return "done"

    api = LocalSprites()
    run_session(
        api, MemoryLedger(), body, name="cqa-rev-hold", deadline_s=30, clock=FakeClock(),
    )  # fmt: skip
    assert any("atlas-task-hold" in argv[-1] for argv in seen)
    assert server.tasks == {}
