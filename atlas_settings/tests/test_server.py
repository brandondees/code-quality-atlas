# SPDX-License-Identifier: MIT
"""The HTTP handler and the bounded server: the security headers on
every response, the bounded body, the content-type gate, the log lines
that never carry a query string and never trip over a malformed request
line, the request timeout, the concurrency cap with its 503 overflow,
and one full flow served over a real loopback socket."""

import http.client
import socket
import threading
import time
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

from atlas_settings.app import Response
from atlas_settings.server import SettingsServer, serve

from .harness import build_world


def _serve(world, tmp_path: Path):
    server = serve(world.app, "127.0.0.1", 0, lambda line: world.logs.append(line))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _get(server, path: str, cookie: str | None = None) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    headers = {"Cookie": f"atlas_settings_session={cookie}"} if cookie else {}
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    body = response.read()
    response.body_text = body.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    connection.close()
    return response


def _post(
    server, path: str, body: str, cookie: str | None = None
) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = f"atlas_settings_session={cookie}"
    connection.request("POST", path, body=body, headers=headers)
    response = connection.getresponse()
    body_text = response.read().decode("utf-8", errors="replace")
    response.body_text = body_text  # type: ignore[attr-defined]
    connection.close()
    return response


def test_every_response_carries_the_decided_headers(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        response = _get(server, "/")
        assert response.status == 200
        assert response.getheader("Content-Security-Policy") == (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
        assert response.getheader("X-Frame-Options") == "DENY"
        assert (
            response.getheader("Strict-Transport-Security")
            == "max-age=31536000; includeSubDomains"
        )
        assert response.getheader("Referrer-Policy") == "no-referrer"
        assert response.getheader("Cache-Control") == "no-store"
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        login = _get(server, "/login")
        set_cookie = login.getheader("Set-Cookie") or ""
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=Strict" in set_cookie
        assert login.getheader("Location", "").startswith(
            "https://github.com/login/oauth/authorize"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_log_lines_never_carry_a_query_string(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        _get(server, "/login?tracking=1")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert world.logs, "the handler logs its requests"
    for line in world.logs:
        assert "tracking=1" not in line
        assert "?" not in line


def test_a_malformed_request_line_still_gets_an_answer(tmp_path: Path) -> None:
    """A request line that fails to parse must still be answered 400 by
    the server, not dropped: the error log fires before `path` and
    `command` exist, and must not raise of its own. The error answer is
    a real HTTP/1.x reply carrying the decided security headers — the
    stdlib's HTTP/0.9-style bare body is not what this page sends."""
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        sock = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        sock.sendall(b"GARBAGE\r\n\r\n")
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        assert raw.startswith(b"HTTP/1.0 400 "), raw[:60]
        # The decided security headers ride the error answer too.
        assert b"Content-Security-Policy: default-src 'none'" in raw
        assert b"X-Frame-Options: DENY" in raw
        assert b"Cache-Control: no-store" in raw
        # Before the guard, the handler's own log_error raised on this
        # path and the connection was dropped with no answer at all.
        # Membership, not exact order: the sequence is the stdlib's
        # contract, not this code's.
        assert any(line.endswith(" error") for line in world.logs), world.logs
        assert any(line.endswith(" 400") for line in world.logs), world.logs
        assert all("GARBAGE" not in line for line in world.logs), world.logs
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_an_unsupported_method_gets_the_headers_too(tmp_path: Path) -> None:
    """A parseable request whose method has no handler answers the
    stdlib's 501 — with the decided security headers, because the
    docstring's "every response" is meant literally."""
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        sock = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        sock.sendall(b"BREW / HTTP/1.1\r\nHost: x\r\n\r\n")
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        assert raw.startswith(b"HTTP/1.0 501 "), raw[:60]
        assert b"X-Frame-Options: DENY" in raw
        assert b"Cache-Control: no-store" in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_bad_content_length_is_answered_400_not_413(tmp_path: Path) -> None:
    """A negative or non-numeric Content-Length is a malformed request,
    not an oversized body: both answer 400 (kills the
    negative-is-oversized mutant, which answered 413)."""
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        for header in (b"Content-Length: -5\r\n", b"Content-Length: abc\r\n"):
            sock = socket.create_connection(
                ("127.0.0.1", server.server_address[1]), timeout=10
            )
            sock.sendall(
                b"POST /settings/cap HTTP/1.0\r\nHost: x\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                + header
                + b"\r\n"
            )
            raw = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
            sock.close()
            assert raw.startswith(b"HTTP/1.0 400 "), (header, raw[:60])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_connection_that_never_finishes_its_request_is_closed(
    tmp_path: Path,
) -> None:
    """The bounded read: a client that opens a connection and sends
    half a request line has its connection closed when the request
    timeout lapses, instead of holding a handler thread forever."""
    world = build_world(tmp_path)
    server = serve(
        world.app,
        "127.0.0.1",
        0,
        lambda line: world.logs.append(line),
        request_timeout_s=0.5,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        sock.sendall(b"GET / HT")
        sock.settimeout(10)
        assert sock.recv(4096) == b""
        sock.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_an_overflow_request_is_refused_not_queued(tmp_path: Path) -> None:
    """With the handler slots full, a further connection is answered
    503 at once rather than queued behind an unbounded pile of
    threads — and the slot is handed back when the busy handler ends."""
    world = build_world(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def block(*args: object, **kwargs: object) -> Response:
        entered.set()
        release.wait(10)
        return Response(200, b"slow but fine")

    world.app.get = block  # type: ignore[method-assign]
    server = serve(
        world.app,
        "127.0.0.1",
        0,
        lambda line: world.logs.append(line),
        max_concurrent=1,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    first_response: list[http.client.HTTPResponse] = []

    def slow_request() -> None:
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=10
        )
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        first_response.append(response)
        connection.close()

    busy = threading.Thread(target=slow_request, daemon=True)
    try:
        busy.start()
        assert entered.wait(10), "the first request never reached the handler"
        overflow = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        overflow.sendall(b"GET / HTTP/1.0\r\n\r\n")
        raw = b""
        while True:
            chunk = overflow.recv(4096)
            if not chunk:
                break
            raw += chunk
        overflow.close()
        assert raw.startswith(b"HTTP/1.1 503 "), raw[:60]
        # The refusal is a response this page sends: it carries the
        # decided security headers even though no handler exists yet.
        assert b"X-Frame-Options: DENY" in raw
        assert b"Content-Security-Policy: default-src 'none'" in raw
        release.set()
        busy.join(timeout=10)
        assert first_response[0].status == 200
        # The slot was handed back: the next request is served normally.
        assert _get(server, "/").status == 200
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_busy_refusal_survives_a_client_that_already_left() -> None:
    """A peer that hangs up before the 503 is sent must not crash the
    accept loop: the refusal's send failure is swallowed and the request
    socket is still shut down."""

    class DeadPeer:
        def sendall(self, data: bytes) -> None:
            raise ConnectionResetError("the peer is gone")

        def shutdown(self, how: int) -> None:
            raise OSError

        def close(self) -> None:
            closed.append(True)

    closed: list[bool] = []
    server = object.__new__(SettingsServer)
    SettingsServer._refuse_busy(server, cast("socket.socket", DeadPeer()))
    assert closed == [True]


class _FastClock:
    """A monotonic clock that runs faster than real time, advanced from
    its own thread: the drip tests' fake clock — the budget lapses in
    about a second of real time without any real sleep at the timeout's
    scale."""

    def __init__(self, fake_seconds_per_real_second: float = 10.0) -> None:
        self.now = 0.0
        self._rate = fake_seconds_per_real_second
        self._stop = threading.Event()

    def __call__(self) -> float:
        return self.now

    def start(self) -> None:
        def run() -> None:
            while not self._stop.wait(0.05):
                self.now += self._rate * 0.05

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def test_a_body_shorter_than_its_length_is_a_400(tmp_path: Path) -> None:
    """A body that ends before its Content-Length is a malformed
    request, answered 400 — never parsed as a whole form (kills the
    process-the-truncation mutant, under which the single-read body
    returned early and the app acted on a cut-mid-field form)."""
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        sock = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        sock.sendall(
            b"POST /settings/cap HTTP/1.0\r\nHost: x\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: 8\r\n\r\n"
            b"ab"
        )
        sock.shutdown(socket.SHUT_WR)
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        assert raw.startswith(b"HTTP/1.0 400 "), raw[:60]
        assert b"bad request" in raw
        assert world.app.store.load("42") is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_slow_drip_cannot_hold_a_slot_past_the_deadline(tmp_path: Path) -> None:
    """The whole-request budget: a client dripping one byte at a time,
    every gap far inside the per-recv timeout, loses its connection when
    the monotonic budget lapses — the per-recv timeout alone would never
    fire — and its slot is released, so a fresh client is served (kills
    the drop-the-deadline mutant, under which the dripping client holds
    the slot and the fresh client sees nothing but 503s)."""
    world = build_world(tmp_path)
    clock = _FastClock()
    server = serve(
        world.app,
        "127.0.0.1",
        0,
        lambda line: world.logs.append(line),
        request_timeout_s=100.0,
        request_deadline_s=5.0,
        deadline_clock=clock,
        max_concurrent=1,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clock.start()
    try:
        drip = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        drip.sendall(b"P")  # one request-line byte; the line never completes
        drip.settimeout(10)
        closed = False
        answered: list[bytes] = []
        for _ in range(240):  # up to ~12 real seconds of dripping
            time.sleep(0.05)
            drip.settimeout(0.2)
            try:
                data = drip.recv(64)
            except TimeoutError:
                data = None  # no answer yet; keep dripping
            if data == b"":
                closed = True  # the server closed its side, nothing sent
                break
            if data:
                answered.append(data)
                break  # the server answered a client that never finished
            drip.settimeout(10)
            try:
                drip.sendall(b"x")  # well inside the 100s per-recv timeout
            except OSError:
                # A reset without a FIN we observed: probe once more for
                # the EOF — a clean cut-off ends with one.
                drip.settimeout(0.5)
                try:
                    closed = drip.recv(64) == b""
                except (TimeoutError, OSError):
                    closed = False
                break
        assert closed and not answered, (
            f"the drip ended wrong: closed={closed}, answered={answered!r}"
        )
        drip.close()
        # The slot is free again: with a single slot, a fresh client is
        # served only once the drip's handler has ended. The 503s before
        # that are the shedding rule working while the drip still held.
        served = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                response = _get(server, "/")
                served = response.status
                if served == 200:
                    break
            except OSError:
                served = None
            time.sleep(0.1)
        assert served == 200, f"the fresh client was never served (last: {served})"
    finally:
        clock.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_body_that_drips_past_the_deadline_is_cut_off(tmp_path: Path) -> None:
    """A drip that got past the request line and headers dies in the
    body read: the budget covers the body too, the connection is closed
    with nothing answered — not even the generic 500, which would treat
    a pacing attack as an app bug — and the slot is freed (kills the
    answer-the-lapse mutant, which sent the 500)."""
    world = build_world(tmp_path)
    clock = _FastClock()
    server = serve(
        world.app,
        "127.0.0.1",
        0,
        lambda line: world.logs.append(line),
        request_timeout_s=100.0,
        request_deadline_s=5.0,
        deadline_clock=clock,
        max_concurrent=1,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clock.start()
    try:
        drip = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        # The headers arrive whole and inside the budget; the body is
        # the part that drips.
        drip.sendall(
            b"POST /settings/cap HTTP/1.0\r\nHost: x\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: 64\r\n\r\n"
        )
        drip.settimeout(10)
        closed = False
        answered: list[bytes] = []
        for _ in range(240):
            time.sleep(0.05)
            drip.settimeout(0.2)
            try:
                data = drip.recv(64)
            except TimeoutError:
                data = None  # no answer yet; keep dripping
            if data == b"":
                closed = True  # closed with nothing answered
                break
            if data:
                answered.append(data)
                break  # the budget lapse was answered — the mutant's shape
            drip.settimeout(10)
            try:
                drip.sendall(b"x")
            except OSError:
                drip.settimeout(0.5)
                try:
                    closed = drip.recv(64) == b""
                except (TimeoutError, OSError):
                    closed = False
                break
        assert closed and not answered, (
            f"the body drip ended wrong: closed={closed}, answered={answered!r}"
        )
        drip.close()
        served = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                response = _get(server, "/")
                served = response.status
                if served == 200:
                    break
            except OSError:
                served = None
            time.sleep(0.1)
        assert served == 200, f"the fresh client was never served (last: {served})"
    finally:
        clock.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_an_oversized_body_is_refused(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        response = _post(server, "/settings/cap", "csrf=x&cap_usd=" + "9" * 9000)
        assert response.status == 413
        # No Content-Length at all: a raw request on the socket.
        import socket as socket_module

        sock = socket_module.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        sock.sendall(
            b"POST /settings/cap HTTP/1.0\r\nHost: x\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n\r\n"
        )
        raw = sock.recv(4096)
        sock.close()
        assert raw.startswith(b"HTTP/1.0 411 "), raw[:60]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_wrong_content_type_is_refused(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=10
        )
        connection.request(
            "POST",
            "/settings/cap",
            body="csrf=x",
            headers={"Content-Type": "text/plain"},
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 415
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_an_unexpected_exception_answers_the_generic_500(tmp_path: Path) -> None:
    world = build_world(tmp_path)

    def explode(*args: object, **kwargs: object) -> None:
        raise ValueError("submitted value secret-abc")

    world.app.get = explode  # type: ignore[method-assign]
    server, thread = _serve(world, tmp_path)
    try:
        response = _get(server, "/")
        assert response.status == 500
        assert "secret-abc" not in response.body_text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_full_login_flow_over_the_real_socket(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        started = _get(server, "/login")
        location = started.getheader("Location") or ""
        assert started.status == 302
        state = (parse_qs(urlsplit(location).query).get("state") or [""])[0]
        cookie_value = _cookie_value(started)
        # GitHub's side is fake; the callback is driven through the app
        # itself (the fake transport is not an HTTP server), then the
        # signed-in page is read over the socket.
        callback = world.app.get(
            "/callback",
            f"code=fake-code&state={state}",
            cookie_value,
            "127.0.0.1",
        )
        assert callback.status == 303
        page = _get(server, "/settings", world.cookie_from(callback))
        assert page.status == 200
        assert "octo-admin" in page.body_text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _cookie_value(response: http.client.HTTPResponse) -> str:
    header = response.getheader("Set-Cookie") or ""
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "atlas_settings_session":
            return value
    raise AssertionError("no session cookie was set")


def test_a_successful_socket_post_changes_state(tmp_path: Path) -> None:
    """The successful POST path end to end over the socket: consent
    recorded, 303 answered."""
    import re as re_module

    world = build_world(tmp_path)
    server, thread = _serve(world, tmp_path)
    try:
        started = _get(server, "/login")
        location = started.getheader("Location") or ""
        state = (parse_qs(urlsplit(location).query).get("state") or [""])[0]
        callback = world.app.get(
            "/callback",
            f"code=fake-code&state={state}",
            _cookie_value(started),
            "127.0.0.1",
        )
        cookie = world.cookie_from(callback)
        page = _get(server, "/settings", cookie)
        match = re_module.search(r'name="csrf" value="([^"]+)"', page.body_text)
        assert match is not None
        response = _post(
            server,
            "/settings/consent",
            f"csrf={match.group(1)}&acknowledge=1",
            cookie,
        )
        assert response.status == 303
        record = world.app.store.load("42")
        assert record is not None
        assert record.consent_acknowledged_at is not None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
