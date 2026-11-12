# SPDX-License-Identifier: MIT
"""Keep a Sprite awake for one lens with the Tasks API.

A Sprite pauses after about 30 seconds without activity, and a quiet exec
is not activity (Fly, Keeping a Sprite Running,
https://docs.fly.io/sprites/keeping-sprites-running, and the 2026-05-08
support note that an exec with no TTY output goes idle). The hold is a
task on the in-Sprite socket `/.sprite/api.sock` (virtual host `sprite`):
create it when the lens starts, refresh it every 60 seconds with a
5-minute expiry, and delete it on the way out, including when the lens
raises or is cancelled. The maximum task lifetime is one hour, so the
short expiry is what limits a forgotten hold. There is no public fork
API (Fly support, 2026-11-06); this module does not snapshot or restore.

The controller starts the hold. A model turn runs on the controller, so
the Sprite would otherwise sit quiet for the whole call. Refresh and tool
execs share the runner's exec lock, so they do not write one stream. Each
hold exec has its own 15-second budget and the guest socket call times out
after 10 seconds, so a stuck refresh cannot hold that lock until the
5-minute task expires. The join waits at most 20 seconds, then the delete
runs anyway.
"""

from __future__ import annotations

import base64
import inspect
import json
import re
import shlex
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, Self
from urllib.parse import quote

from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.runner import DeadlineExceededError, Session

SOCKET_PATH = "/.sprite/api.sock"
HOST = "sprite"
EXPIRE = "5m"
REFRESH_S = 60.0
# Short enough that a stuck refresh, even while it holds the exec lock,
# ends well inside the 5-minute expiry (the refresh itself is every 60s).
HOLD_BUDGET_S = 15.0
JOIN_S = 20.0
_NAME = re.compile(r"atlas-lens-[a-z0-9-]{1,48}\Z")


class TaskClient(Protocol):
    """One named hold. `create` and `refresh` fail closed; `delete` is
    safe to call once the hold is already gone."""

    def create(self, name: str) -> None: ...

    def refresh(self, name: str) -> None: ...

    def delete(self, name: str) -> None: ...


def task_name(digest: str) -> str:
    """`atlas-lens-` plus a hex digest. One hold per review commit."""
    name = f"atlas-lens-{digest}"
    if _NAME.fullmatch(name) is None:
        raise BoundaryError("refusing a task name that is not atlas-lens-<hex>")
    return name


def exchange(socket_path: str, method: str, target: str, body: str) -> None:
    """One HTTP/1.1 request on the Sprite management socket.

    Create and refresh must answer 200, 201 or 204. A 404 is success only
    for delete, which means the hold is already gone; a refresh that gets
    404 has not renewed the task. The socket call times out after 10
    seconds, and only the status line is read (at most 512 bytes). A bad
    status or a socket error raises `RuntimeError` or `OSError`. This
    function is copied into the guest script, so it uses only the standard
    library and does not refer to names outside itself."""
    payload = body.encode()
    request = (
        f"{method} {target} HTTP/1.1\r\n"
        "Host: sprite\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode() + payload
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(10)
        sock.connect(socket_path)
        sock.sendall(request)
        data = bytearray()
        while b"\r\n" not in data and len(data) < 512:
            chunk = sock.recv(min(256, 512 - len(data)))
            if not chunk:
                break
            data += chunk
    finally:
        sock.close()
    line = bytes(data).split(b"\r\n", 1)[0]
    parts = line.split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError(f"sprite task socket {method} returned no status")
    status = int(parts[1])
    allowed = {200, 201, 204, 404} if method == "DELETE" else {200, 201, 204}
    if status not in allowed:
        raise RuntimeError(f"sprite task socket {method} returned HTTP {status}")


def _checked(socket_path: str, method: str, target: str, body: str) -> None:
    try:
        exchange(socket_path, method, target, body)
    except (RuntimeError, OSError) as exc:
        raise BoundaryError(str(exc)) from exc


def hold_script(socket_path: str, method: str, target: str, body: str) -> str:
    """A self-contained script the controller execs inside the Sprite. The
    guest does not have this package, so the script carries `exchange`."""
    program = (
        "import socket\n"
        + inspect.getsource(exchange)
        + "\n"
        + f"exchange({socket_path!r}, {method!r}, {target!r}, {body!r})\n"
    )
    encoded = base64.b64encode(program.encode()).decode()
    return (
        "# atlas-task-hold\n"
        "/usr/bin/python3 -c "
        + shlex.quote("import base64,sys; exec(base64.b64decode(sys.argv[1]))")
        + " "
        + shlex.quote(encoded)
        + "\n"
    )


def _check_name(name: str) -> None:
    if _NAME.fullmatch(name) is None:
        raise BoundaryError("refusing a task name that is not atlas-lens-<hex>")


def _target(name: str, method: str) -> str:
    _check_name(name)
    if method == "POST":
        return "/v1/tasks"
    return "/v1/tasks/" + quote(name, safe="")


def _payload(name: str, method: str) -> str:
    if method == "DELETE":
        return ""
    fields = {"expire": EXPIRE}
    if method == "POST":
        fields = {"name": name, "expire": EXPIRE}
    return json.dumps(fields)


@dataclass
class SocketTaskClient:
    """Talks to a management socket directly. Tests point it at a fake
    socket; a process inside a Sprite would use `/.sprite/api.sock`."""

    socket_path: str = SOCKET_PATH

    def create(self, name: str) -> None:
        _checked(
            self.socket_path, "POST", _target(name, "POST"), _payload(name, "POST")
        )

    def refresh(self, name: str) -> None:
        _checked(self.socket_path, "PUT", _target(name, "PUT"), _payload(name, "PUT"))

    def delete(self, name: str) -> None:
        _checked(
            self.socket_path,
            "DELETE",
            _target(name, "DELETE"),
            _payload(name, "DELETE"),
        )


@dataclass
class ExecTaskClient:
    """The controller-side client: each call is one exec of `hold_script`."""

    session: Session
    socket_path: str = SOCKET_PATH

    def create(self, name: str) -> None:
        self._run("POST", name)

    def refresh(self, name: str) -> None:
        self._run("PUT", name)

    def delete(self, name: str) -> None:
        self._run("DELETE", name)

    def _run(self, method: str, name: str) -> None:
        code, text = self.session.exec(
            "task hold",
            hold_script(
                self.socket_path, method, _target(name, method), _payload(name, method)
            ),
            stage="keepalive",
            budget_s=HOLD_BUDGET_S,
        )
        if code != 0:
            tail = " ".join(text.split())[:200]
            detail = f": {tail}" if tail else ""
            raise BoundaryError(
                f"sprite task hold {method} failed (exit {code}){detail}"
            )


Wait = Callable[[float], bool]


@dataclass
class LensHold:
    """Create a hold, refresh it until exit, then delete it.

    `__exit__` joins the refresh thread before it deletes. A refresh
    stores a failure under the lock before it releases the lock, so the
    delete cannot pass until that error is stored; the join waits for an
    in-flight refresh to finish, and it is bounded (`join_s`). The lock,
    and the stop and held guards, are what stop a refresh from upserting
    the task after the delete (the Tasks API's PUT is an upsert). Delete
    runs when the body returns, when it raises, and when it is cancelled,
    including when the join is interrupted. A refresh that fails is
    raised after the delete, unless the body already raised: the body's
    exception is the one the caller sees, and no error from the delete
    replaces it."""

    client: TaskClient
    name: str
    refresh_s: float = REFRESH_S
    wait: Wait | None = None
    join_s: float = JOIN_S
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _error: Exception | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _held: bool = field(default=False, init=False)

    def __enter__(self) -> Self:
        self.client.create(self.name)
        self._held = True
        self._thread = threading.Thread(
            target=self._beat, name=f"atlas-task-{self.name}", daemon=True
        )
        try:
            self._thread.start()
        except Exception:
            self._release()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: object,
    ) -> Literal[False]:
        self._stop.set()
        thread = self._thread
        join_error: KeyboardInterrupt | None = None
        try:
            if thread is not None and thread is not threading.current_thread():
                thread.join(self.join_s)
        except KeyboardInterrupt as exc:
            join_error = exc
        delete_error: Exception | None = None
        try:
            self._release()
        except Exception as exc:  # noqa: BLE001 - any delete error yields to the lens
            delete_error = exc
        if join_error is not None:
            raise join_error
        if exc_type is not None:
            return False
        if self._error is not None:
            if delete_error is not None:
                raise self._error from delete_error
            raise self._error
        if delete_error is not None:
            raise delete_error
        return False

    def refresh(self) -> None:
        """One refresh. A failure is stored before the lock is released,
        then raised to the caller."""
        with self._lock:
            if self._stop.is_set() or not self._held:
                return
            try:
                self.client.refresh(self.name)
            except (BoundaryError, DeadlineExceededError) as exc:
                self._error = exc
                self._stop.set()
                raise

    def _beat(self) -> None:
        wait = self._stop.wait if self.wait is None else self.wait
        while not wait(self.refresh_s):
            try:
                self.refresh()
            except (BoundaryError, DeadlineExceededError):
                return

    def _release(self) -> None:
        if not self._lock.acquire(timeout=self.join_s):
            raise BoundaryError(
                "sprite task hold delete timed out waiting for a refresh"
            )
        try:
            if not self._held:
                return
            self._held = False
            self.client.delete(self.name)
        finally:
            self._lock.release()


def lens_hold(
    session: Session, digest: str, socket_path: str = SOCKET_PATH
) -> LensHold:
    """The hold the controller keeps for the length of one lens."""
    return LensHold(ExecTaskClient(session, socket_path), task_name(digest))
