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
import re
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Self

from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError
from atlas_reviewer.runner import (
    DENY_ALL,
    EGRESS_TAG,
    EXIT_MARKER,
    SWEEP_TAG,
)

REAP_TIMEOUT_S = 5.0


# How long a sweep waits for SIGKILL to land before it fails closed.
_SWEEP_REAP_S = 0.5


class LocalSprites(FakeSprites):
    """Runs the exec wrapper's argv here and answers with its stdout as
    one stdout frame, the shape the live exec stream has. The exec's
    budget is honored as the subprocess's own timeout, in its own process
    group so no grandchild outlives it; a command that outlives the budget
    raises `StreamTimeoutError`, the same failure a live runner reports,
    not a crash."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Adopt the orphans this runner's execs leave behind (the daemon
        # shape: a test process that detached from its exec's group and
        # outlived it), so the sweep can find them by ancestry instead of
        # by a uid scope that on this machine would reach processes that
        # are not the runner's.
        try:
            import ctypes

            ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
        except (OSError, ImportError):  # pragma: no cover - non-Linux
            pass

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        script = argv[-1]
        if SWEEP_TAG in script:
            # The sweep script's uid scope is what holds on a real Sprite;
            # on this machine it would kill processes that are not the
            # runner's, so the local runner answers the sweep with its own
            # scoped implementation instead of executing it.
            self._record("exec", name, script)
            self._note_policy(name)
            self.sweep(name)
            return b"\x01" + f"{SWEEP_TAG}:clean\n{EXIT_MARKER}0\n".encode()
        if EGRESS_TAG in script:
            # The egress check runs real outbound connects on a live
            # runner; this machine's real network would answer for
            # itself, and no local enforcement exists, so the local
            # runner reports the outcome the deny-all policy produces --
            # every connect attempts and times out -- instead of
            # executing the script. The same modeling choice the sweep's
            # scoped stand-in makes.
            self._record("exec", name, script)
            self._note_policy(name)
            return b"\x01" + self._egress_answer(script)
        self._record("exec", name, script)
        self._note_policy(name)
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

    def _note_policy(self, name: str) -> None:
        """Records whether this exec ran under deny-all (issue #819, D95):
        the order proof's raw material, shared with the fake's own exec."""
        self.policy_deny_at_exec.append(self._get(name).network_rules == list(DENY_ALL))

    def _egress_answer(self, script: str) -> bytes:
        """The egress verdict lines the deny-all policy produces: one
        timed-out connect per target, in script order."""
        found = re.search(r"for t in (.+?); do", script)
        targets = found.group(1).split() if found else ()
        lines = [f"{EGRESS_TAG}:{t}:tried:timeout:0" for t in targets]
        body = "\n".join(lines)
        return f"{body}\n{EXIT_MARKER}0\n".encode()

    def sweep(
        self,
        name: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """The local sweep (D80 round 2), scoped to this runner's own
        processes: the machine running the tests has other work under the
        same user, and the live sweep's uid scope would kill it, so the
        local sweep kills only what this runner spawned or adopted -- the
        subreaper flag in `__init__` makes every orphan its execs leave
        (the detached-daemon shape) a direct child of this process. It
        reaps, kills the surviving runner descendants, reaps again, and
        fails closed -- `BoundaryError`, the gap a live sweep's survivor
        count produces -- when any of them remains. The live sweep's uid
        scope is what holds on a real Sprite; this is its testable
        stand-in, and the difference is recorded in D80."""
        self._reap()
        for pid in self._stray_descendants():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # SIGKILL is asynchronous. One 50 ms sleep is not always enough
        # for a loaded runner to drop the process from the scan, so poll
        # until the deadline and then fail closed.
        deadline = monotonic() + _SWEEP_REAP_S
        while True:
            sleep(0.05)
            self._reap()
            survivors = self._stray_descendants()
            if not survivors or monotonic() >= deadline:
                break
        if survivors:
            raise BoundaryError(
                f"the stray-process sweep left {len(survivors)} survivor(s)"
            )

    def _reap(self) -> None:
        while True:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return

    def _stray_descendants(self) -> set[int]:
        """Every live, non-zombie process whose parent chain reaches this
        process -- the runner's own exec tree and whatever its execs left
        behind -- except this process itself. `/proc/<pid>/status`'s
        `PPid` is the chain; a detached daemon's chain reaches here
        because the subreaper adopted it. A zombie is skipped: it is
        dead, holds no code, and the reaping is this process's job."""
        me = os.getpid()
        strays: set[int] = set()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == me:
                continue
            try:
                status = (entry / "status").read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
            state = re.search(r"^State:\s+(\S)", status, re.MULTILINE)
            if state is not None and state.group(1) == "Z":
                continue
            hop, hops = pid, 0
            while hop != me and hop != 0 and hop != -1 and hops < 64:
                try:
                    ancestor = (entry.parent / str(hop) / "status").read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    break
                match = re.search(r"^PPid:\s+(\d+)", ancestor, re.MULTILINE)
                if match is None:
                    break
                hop = int(match.group(1))
                hops += 1
            if hop == me:
                strays.add(pid)
        return strays


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the exec's whole process group and reap it. `communicate` left
    the direct child alive; `start_new_session` made it its group's
    leader, so a grandchild `sh` left behind cannot outlive the budget.
    The reap is bounded: something that left the group but kept the
    inherited pipes could otherwise hold this wait past the budget, and
    the caller's own timeout error is the one that matters."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.communicate(timeout=REAP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


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
