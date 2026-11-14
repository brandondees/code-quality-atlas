# SPDX-License-Identifier: MIT
"""Offline runners for `--dry-run`: the runner lifecycle, executed here.

`LocalSprites` is a `SpritesApi` whose `exec` runs the runner's one exec
wrapper on this machine instead of inside a Sprite: create, the deny-all
set and its read-back, the memory limit, the ledger and the destroy are
the fake's own records, and every script — git staging, the bridge's tool
calls, the task hold — is run as a real subprocess with `env -i`. Nothing
leaves the machine: there is no network client here, and the policy that
the live path sets and reads back is recorded and verified the same way.
The tests run the same class (`test_bridge`, `test_lens_loop`), so the
dry run exercises exactly the code they do.

`LocalTasks` answers the Tasks API the keepalive's hold exec calls: the
same create/refresh/delete on a unix socket in this process, so a lens
hold runs for real without a Sprite. A dry run binds it under its state
directory and closes it when the review ends.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import threading
from pathlib import Path
from typing import Self

from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError


class LocalSprites(FakeSprites):
    """Runs the exec wrapper's argv here and answers with its stdout as
    one stdout frame, the shape the live exec stream has. The exec's
    budget is honored as the subprocess's own timeout, in its own process
    group so no grandchild outlives it; a command that outlives the budget
    raises `StreamTimeoutError`, the same failure a live runner reports,
    not a crash."""

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        self._record("exec", name, argv[-1])
        self._get(name)
        self.argv_seen.append(tuple(argv))
        self.timeouts_seen.append(timeout_s)
        try:
            proc = subprocess.Popen(
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise BoundaryError(f"local exec could not start: {exc}") from exc
        try:
            stdout, _stderr = proc.communicate(stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(proc)
            received = exc.stdout or b""
            raise StreamTimeoutError(
                f"local exec did not finish within its {timeout_s}s budget",
                received=received,
                first_byte=False,
            ) from exc
        return b"\x01" + stdout


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the exec's whole process group and reap it. `communicate` left
    the direct child alive; `start_new_session` made it its group's
    leader, so a grandchild `sh` left behind cannot outlive the budget."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.communicate()


class LocalTasks:
    """The Tasks API, on a unix socket, just enough to answer the hold.

    `POST /v1/tasks` creates (`409` when the name exists, which the hold
    refuses), `PUT /v1/tasks/<name>` upserts, `DELETE` deletes (`404`
    counts as already gone). Anything else is `400`. `close` stops the
    server thread and unlinks the socket."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tasks: dict[str, str] = {}
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if path.exists():
            path.unlink()
        self._sock.bind(str(path))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, name="atlas-tasks", daemon=True
        )

    def __enter__(self) -> Self:
        self.start()
        return self

    def start(self) -> None:
        self._thread.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=5)
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
        conn.settimeout(5)
        head, body = _read_request(conn)
        try:
            status = self._apply(head, body)
        except (ValueError, KeyError, UnicodeDecodeError):
            status = 400
        reason = "OK" if status < 300 else "ERR"
        conn.sendall(
            f"HTTP/1.1 {status} {reason}\r\nContent-Length: 0\r\n"
            "Connection: close\r\n\r\n".encode()
        )

    def _apply(self, head: bytes, body: bytes) -> int:
        line = head.split(b"\r\n", 1)[0].decode()
        method, target, _version = line.split(" ", 2)
        with self._lock:
            if method == "POST":
                name = str(json.loads(body)["name"])
                if name in self.tasks:
                    return 409
                self.tasks[name] = body.decode()
                return 201
            name = target.rsplit("/", 1)[-1]
            if method == "PUT":
                self.tasks[name] = body.decode()
                return 200
            if method == "DELETE":
                self.tasks.pop(name, None)
                return 204
        return 400


def _read_request(conn: socket.socket) -> tuple[bytes, bytes]:
    """The head and the exact `Content-Length` body of one request. The
    guest sends the body and closes; a short read is whatever arrived."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return data, b""
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    length = 0
    for field in head.split(b"\r\n"):
        if field.lower().startswith(b"content-length:"):
            length = int(field.split(b":", 1)[1].strip() or 0)
    while len(rest) < length:
        chunk = conn.recv(4096)
        if not chunk:
            break
        rest += chunk
    return head, rest[:length]
