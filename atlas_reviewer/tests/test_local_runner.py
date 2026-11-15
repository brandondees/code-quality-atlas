# SPDX-License-Identifier: MIT
"""`LocalTasks`: the Tasks API a dry run's keepalive hold talks to, on a
unix socket in this process; and `LocalSprites`' exec contract — the
budget, the timeout's failure shape, and the process group the kill
covers. The bridge, lens-loop, keepalive and end-to-end suites exercise
both through the whole review."""

import shlex
import socket
import time
from pathlib import Path

import pytest

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.domain import RunnerStatus
from atlas_reviewer.fakes import MemoryLedger
from atlas_reviewer.keepalive import SocketTaskClient
from atlas_reviewer.local_runner import LocalSprites, LocalTasks
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError
from atlas_reviewer.runner import exec_argv, run_session


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


def test_an_exec_that_outlives_its_budget_raises_a_stream_timeout():
    """The budget is the subprocess's own timeout, so a hung script ends at
    its budget with the failure a live runner reports, and the review
    fails closed instead of dying on an uncaught `TimeoutExpired`. The
    bytes that arrived before the budget are on the error, as they are on
    a live runner."""
    api = LocalSprites()
    api.create("cqa-rev-test-abc")
    try:
        started = time.monotonic()
        with pytest.raises(StreamTimeoutError) as raised:
            api.exec(
                "cqa-rev-test-abc",
                exec_argv("echo atlas-partial; exec sleep 5", 0),
                b"",
                1,
            )
        assert raised.value.first_byte is False
        assert b"atlas-partial" in raised.value.received
        assert "did not finish within its 1s budget" in str(raised.value)
        # Well under the 5s the killed command would have run to: a mutant
        # that only reaps (and waits for the pipes) rides that 5s.
        assert time.monotonic() - started < 3
    finally:
        api.delete("cqa-rev-test-abc")


def test_a_local_timeout_reports_the_stage_and_purpose_like_a_live_runner():
    """`_send` rewrites a `StreamTimeoutError`'s message with the stage and
    purpose, and the runner fails closed on it. A plain `BoundaryError`
    would keep the local text, so this fails if the local timeout stops
    being the live runner's failure."""
    api = LocalSprites()
    ledger = MemoryLedger()

    def body(session):
        return session.exec("probe", "echo atlas-partial; exec sleep 5", budget_s=1)

    report = run_session(
        api, ledger, body, name="cqa-rev-test-abc",
        deadline_s=30, clock=SystemClock(),
    )  # fmt: skip
    assert report.status is RunnerStatus.FAILED
    assert "session stage, probe:" in report.note
    assert "output stopped before the exit marker" in report.note
    assert "did not finish within its 1s budget" in report.note
    assert api.live_names() == ()
    assert report.status is RunnerStatus.FAILED
    assert "session stage, probe:" in report.note
    assert "output stopped before the exit marker" in report.note
    assert "did not finish within its 1s budget" in report.note


def test_a_timeout_kills_the_whole_process_group(tmp_path):
    """`communicate` kills only the direct child; the exec runs in its own
    process group so a grandchild of `sh` cannot outlive the budget. The
    script's `sleep` is a grandchild, not an `exec` replacement, and the
    timing bound is what locks the kill in: `exec` must return at the
    budget, not after the grandchild's own `sleep 5` closes the pipes a
    reap-only kill would ride to the end."""
    pidfile = tmp_path / "orphan.pid"
    script = f"sleep 5 & echo $! > {shlex.quote(str(pidfile))}; wait"
    api = LocalSprites()
    api.create("cqa-rev-test-abc")
    try:
        started = time.monotonic()
        with pytest.raises(StreamTimeoutError):
            api.exec("cqa-rev-test-abc", exec_argv(script, 0), b"", 1)
        # `exec` must not wait for the grandchild: a kill that only reaps
        # (or kills the direct child alone) returns only once the
        # grandchild's own `sleep 5` has closed the inherited pipes.
        assert time.monotonic() - started < 3
        pid = int(pidfile.read_text().strip())
        deadline = time.monotonic() + 2
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(pid), f"grandchild {pid} outlived the budget"
    finally:
        api.delete("cqa-rev-test-abc")


def _alive(pid: int) -> bool:
    """A live process in /proc: gone when the entry is, and a zombie counts
    as gone, since its parent has been reaped or is about to."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return False
    state = stat.rpartition(")")[2].lstrip()[:1]
    return state != "Z"
