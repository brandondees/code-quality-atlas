# SPDX-License-Identifier: MIT
"""Sprite task hold. No live Sprite call: a fake unix socket, and the
same socket reached by the guest script through `LocalSprites`."""

import socket
import threading
import time
from pathlib import Path

import pytest

from atlas_reviewer.domain import RunnerStatus
from atlas_reviewer.fakes import FakeSprites, MemoryLedger
from atlas_reviewer.keepalive import (
    EXPIRE,
    HOLD_BUDGET_S,
    REFRESH_S,
    ExecTaskClient,
    LensHold,
    SocketTaskClient,
    exchange,
    lens_hold,
    task_name,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.runner import (
    EXIT_MARKER,
    START_MARKER,
    Deadline,
    DeadlineExceededError,
    Session,
    _Run,
    run_session,
)
from atlas_reviewer.telemetry import Telemetry

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
            # The live Tasks API upserts: a PUT of a missing task creates it.
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


def test_a_delete_failure_surfaces_when_the_lens_succeeds():
    client = Recording(fail="delete")
    with pytest.raises(BoundaryError, match="delete failed"), LensHold(client, NAME):
        pass
    assert client.events == ["create", "delete"]


def test_a_delete_failure_does_not_hide_the_lens_error():
    client = Recording(fail="delete")
    with pytest.raises(RuntimeError, match="boom"), LensHold(client, NAME):
        raise RuntimeError("boom")
    assert client.events == ["create", "delete"]


def test_a_deadline_during_delete_does_not_hide_the_lens_error():
    class Late(Recording):
        def delete(self, name: str) -> None:
            self.events.append("delete")
            raise DeadlineExceededError("deadline reached before task hold")

    client = Late()
    with pytest.raises(ValueError, match="boom"), LensHold(client, NAME):
        raise ValueError("boom")
    assert client.events == ["create", "delete"]


def test_an_interrupt_during_the_join_still_deletes(monkeypatch):
    client = Recording()
    original = threading.Thread.join

    def interrupt(self, timeout=None):
        if self.name.startswith("atlas-task"):
            raise KeyboardInterrupt
        return original(self, timeout)

    monkeypatch.setattr(threading.Thread, "join", interrupt)
    with pytest.raises(KeyboardInterrupt), LensHold(client, NAME):
        pass
    assert client.events == ["create", "delete"]


def test_the_refresh_thread_is_joined_before_the_delete(monkeypatch):
    client = Recording()
    order: list[str] = []
    original = threading.Thread.join

    def record_join(self, timeout=None):
        if self.name.startswith("atlas-task"):
            order.append("join")
        return original(self, timeout)

    def record_delete(name: str) -> None:
        order.append("delete")
        client._call("delete", name)

    monkeypatch.setattr(threading.Thread, "join", record_join)
    client.delete = record_delete
    with LensHold(client, NAME):
        pass
    assert order == ["join", "delete"]


def test_a_refresh_failure_as_the_body_returns_is_raised():
    """The refresh is in flight when the body returns, and it fails before
    the thread exits. The caller still sees that error, after the delete."""
    client = Recording()
    client.inside = threading.Event()
    client.release = threading.Event()

    def refresh(name: str) -> None:
        client.events.append("refresh")
        client.inside.set()
        client.release.wait(5)
        raise BoundaryError("refresh failed")

    client.refresh = refresh
    seen: list[float] = []

    def unblock() -> None:
        assert client.inside.wait(2)
        client.release.set()

    threading.Thread(target=unblock, daemon=True).start()
    with (
        pytest.raises(BoundaryError, match="refresh failed"),
        LensHold(client, NAME, wait=lambda seconds: _once(seconds, seen), join_s=3),
    ):
        assert client.inside.wait(2)
    assert client.events[-1] == "delete"


def test_the_heartbeat_stops_after_a_refresh_failure():
    """A failure returns from the beat. It does not wait for the next
    refresh. The stop flag would also end a real wait; this wait ignores
    the flag, so only the return keeps the count at one."""
    client = Recording(fail="refresh")
    calls = {"n": 0}

    def wait(_seconds: float) -> bool:
        calls["n"] += 1
        return calls["n"] > 5

    with (
        pytest.raises(BoundaryError, match="refresh"),
        LensHold(client, NAME, wait=wait),
    ):
        pass
    assert calls["n"] == 1


def test_a_refresh_past_the_deadline_is_raised_on_exit():
    class Late(Recording):
        def refresh(self, name: str) -> None:
            self.events.append("refresh")
            raise DeadlineExceededError("deadline reached before task hold")

    seen: list[float] = []
    client = Late()
    with (
        pytest.raises(DeadlineExceededError, match="deadline"),
        LensHold(client, NAME, wait=lambda seconds: _once(seconds, seen)),
    ):
        pass
    assert client.events[-1] == "delete"
    assert client.events.count("refresh") == 1


def test_a_delete_does_not_wait_out_a_refresh_that_still_holds_the_lock():
    client = Recording()
    holding = threading.Event()
    release = threading.Event()

    def refresh(_name: str) -> None:
        client.events.append("refresh")
        holding.set()
        release.wait(30)

    client.refresh = refresh
    seen: list[float] = []
    hold = LensHold(
        client, NAME, wait=lambda seconds: _once(seconds, seen), join_s=0.05
    )
    hold.__enter__()
    assert holding.wait(2)
    started = time.monotonic()
    with pytest.raises(BoundaryError, match="timed out"):
        hold.__exit__(None, None, None)
    assert time.monotonic() - started < 2
    release.set()


def test_exit_does_not_wait_out_a_stuck_refresh():
    release = threading.Event()

    def wait(_seconds: float) -> bool:
        release.wait(30)
        return True

    client = Recording()
    hold = LensHold(client, NAME, wait=wait, join_s=0.05)
    hold.__enter__()
    started = time.monotonic()
    hold.__exit__(None, None, None)
    assert time.monotonic() - started < 2
    assert "delete" in client.events
    release.set()


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


def test_a_refresh_of_a_deleted_task_recreates_it(server: TaskServer):
    """The live Tasks API upserts, and so does this socket. A PUT after
    delete brings the task back. The hold refuses that PUT once it has
    stopped, which is what keeps a stopped hold from being recreated."""
    client = SocketTaskClient(str(server.path))
    client.create(NAME)
    client.delete(NAME)
    assert NAME not in server.tasks
    client.refresh(NAME)
    assert NAME in server.tasks
    assert server.order == ["POST", "DELETE", "PUT"]


def test_a_refresh_after_the_hold_stops_sends_no_request(server: TaskServer):
    client = SocketTaskClient(str(server.path))
    with LensHold(client, NAME) as hold:
        pass
    assert server.order == ["POST", "DELETE"]
    assert server.tasks == {}
    hold.refresh()
    assert server.order == ["POST", "DELETE"]
    assert server.tasks == {}


def test_a_refresh_answered_404_is_not_a_success(tmp_path):
    """Delete may treat 404 as gone. A refresh may not: the task was not
    renewed. The fake socket upserts, so this answer comes from a stub."""
    path = socket_path(tmp_path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)

    def once():
        conn, _addr = listener.accept()
        conn.recv(65536)
        conn.sendall(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        conn.close()
        listener.close()

    threading.Thread(target=once, daemon=True).start()
    with pytest.raises(BoundaryError, match="HTTP 404"):
        SocketTaskClient(str(path)).refresh(NAME)


def test_the_status_line_is_enough(tmp_path):
    path = socket_path(tmp_path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    held = threading.Event()

    def once():
        conn, _addr = listener.accept()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 204 No Content\r\n")
        held.wait(5)
        conn.close()
        listener.close()

    threading.Thread(target=once, daemon=True).start()
    started = time.monotonic()
    exchange(str(path), "DELETE", f"/v1/tasks/{NAME}", "")
    assert time.monotonic() - started < 2
    held.set()


def test_a_silent_socket_times_out(tmp_path):
    path = socket_path(tmp_path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    held = threading.Event()

    def once():
        conn, _addr = listener.accept()
        held.wait(30)
        conn.close()
        listener.close()

    threading.Thread(target=once, daemon=True).start()
    box: list[BaseException] = []

    def call():
        try:
            exchange(str(path), "POST", "/v1/tasks", "{}")
        except OSError as exc:
            box.append(exc)

    worker = threading.Thread(target=call, daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(12)
    held.set()
    assert not worker.is_alive()
    assert time.monotonic() - started < 12
    assert box and isinstance(box[0], OSError)


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

    api = LocalSprites()
    report = run_session(
        api, MemoryLedger(), body,
        name="cqa-rev-hold", deadline_s=100, clock=FakeClock(),
    )  # fmt: skip
    assert report.note == "done"
    hold_timeouts = [
        timeout
        for argv, timeout in zip(api.argv_seen, api.timeouts_seen, strict=True)
        if "atlas-task-hold" in argv[-1]
    ]
    assert hold_timeouts == [HOLD_BUDGET_S, HOLD_BUDGET_S]
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


def test_a_fake_sprite_hold_succeeds_until_a_test_sets_its_exit():
    def body(session):
        with lens_hold(session, "ab"):
            return "ran"
        return "ran"

    done = run_session(
        FakeSprites(), MemoryLedger(), body,
        name="cqa-rev-hold", deadline_s=30, clock=FakeClock(),
    )  # fmt: skip
    assert done.status is RunnerStatus.COMPLETED
    failed = run_session(
        FakeSprites(hold_exit=1), MemoryLedger(), body,
        name="cqa-rev-hold", deadline_s=30, clock=FakeClock(),
    )  # fmt: skip
    assert failed.status is RunnerStatus.FAILED
    assert "POST failed" in failed.note


def test_a_keepalive_refresh_does_not_overlap_a_tool_exec():
    """Both go through the one exec lock. A refresh must not share the
    stream with a tool, and the lock is what keeps them apart."""
    api = _Overlap()
    clock = FakeClock()
    session = Session(_Run(api, "n", Deadline(clock, 30), Telemetry(clock)))
    barrier = threading.Barrier(2)

    def one():
        barrier.wait(2)
        session.exec("step", "echo hi\n")

    threads = [threading.Thread(target=one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert api.max_inside == 1


class _Overlap:
    def __init__(self) -> None:
        self.inside = 0
        self.max_inside = 0
        self._lock = threading.Lock()

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        with self._lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        time.sleep(0.05)
        with self._lock:
            self.inside -= 1
        return f"{START_MARKER}\nout\n{EXIT_MARKER}0\n".encode()
