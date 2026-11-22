# SPDX-License-Identifier: MIT
"""The settings page's HTTP server (D90): stdlib `http.server`, no web
framework — the page's surface is six routes of server-rendered HTML
with plain form posts, and adding a dependency for that buys nothing.

The handler applies the decided security headers to every response,
bounds and parses the request body, never logs a query string (the
OAuth code and state live there), and turns every unexpected exception
into a generic 500 so a bug can never echo a submitted value into a
response or a log."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import SocketIO
from typing import Any, Literal, cast

from atlas_settings.app import (
    MAX_BODY_BYTES,
    Response,
    SettingsApp,
    parse_form,
    remote_address,
)

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
# The decided security headers, applied to every response the handler
# sends — its own and the stdlib's error pages alike.
_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'"
        ),
    ),
    ("X-Frame-Options", "DENY"),
    ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
)
# The bounded server: how many requests are handled at once, how long
# one read may block, and how long a whole request may take.
_MAX_CONCURRENT_REQUESTS = 20
_REQUEST_TIMEOUT_S = 30.0
# The whole-request budget: the request line, the headers and the
# bounded 8 KiB body must all have arrived within this much time,
# measured on the monotonic clock from the moment the handler picked
# the connection up. A real request completes in well under a second
# on any honest link; sixty seconds is twice the per-recv timeout and
# bounds a slow-drip client's slot hold to about a minute — the
# per-recv timeout alone cannot do that, because a client sending one
# byte every 29 seconds resets it on every byte and holds a handler
# slot forever.
_REQUEST_DEADLINE_S = 60.0


class _DeadlineBoundSocket:
    """The request socket under the whole-request deadline: every
    read's timeout is the smaller of the per-recv timeout and what
    remains of the request's budget on the monotonic clock, and a read
    attempted past the budget raises at once. This is what turns the
    per-recv timeout — which a one-byte-every-29-seconds drip resets
    forever — into a bound on the whole request. Everything else
    delegates to the real socket; the reads are intercepted here
    because `makefile` must build its streams over this object, so the
    buffered request-line, header and body reads all drain the same
    budget."""

    def __init__(
        self,
        sock: socket.socket,
        clock: Callable[[], float],
        deadline_s: float,
        per_recv_s: float,
    ) -> None:
        self._sock = sock
        self._clock = clock
        self._deadline_s = deadline_s
        self._per_recv_s = per_recv_s
        self._started = clock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)

    def makefile(self, /, mode: str, buffering: int | None = None) -> Any:
        # The stream is built over this object, not the real socket, so
        # the buffered reads drain the same budget; `SocketIO` takes the
        # mode only — the buffering is the caller's `BufferedReader`
        # wrapper's business. The casts: `SocketIO` is typed against the
        # real socket, and this object satisfies its read protocol
        # dynamically (the runtime proof is the socket-level suite).
        return SocketIO(
            cast("socket.socket", self),
            cast("Literal['rb', 'wb', 'rwb']", mode),
        )

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        remaining = self._deadline_s - (self._clock() - self._started)
        if remaining <= 0:
            raise TimeoutError("the request outlived its whole-request deadline")
        self._sock.settimeout(min(remaining, self._per_recv_s))
        return self._sock.recv_into(buffer, nbytes, flags)


class SettingsServer(ThreadingHTTPServer):
    """The page's server: a thread per request, but never more than
    `max_concurrent` handlers running — a connection arriving while all
    the slots are taken is answered 503 and closed, not queued without
    bound."""

    daemon_threads = True
    max_concurrent = _MAX_CONCURRENT_REQUESTS

    def __init__(
        self,
        *args: Any,
        max_concurrent: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(
            self.max_concurrent if max_concurrent is None else max_concurrent
        )

    def process_request(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int] | str,
    ) -> None:
        if not self._slots.acquire(blocking=False):
            self._refuse_busy(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:  # pragma: no cover - a failed thread start is defensive
            # The handler thread was never started, so its `finally`
            # will not run: hand the slot back here instead.
            self._slots.release()
            raise

    def process_request_thread(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int] | str,
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def _refuse_busy(
        self, request: socket.socket | tuple[bytes, socket.socket]
    ) -> None:
        peer = cast("socket.socket", request)
        try:
            # The headers are spelled out because no handler object
            # exists on this path: the connection is refused before one
            # is ever started, and the refusal is still a response this
            # page sends.
            peer.sendall(
                b"HTTP/1.1 503 Service Unavailable\r\n"
                + b"".join(
                    f"{name}: {value}\r\n".encode("ascii")
                    for name, value in _SECURITY_HEADERS
                )
                + b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
        except OSError:
            pass
        finally:
            self.shutdown_request(request)


class SettingsHandler(BaseHTTPRequestHandler):
    """One request. The `app`, `log_sink`, and the deadline settings are
    class attributes set by `serve`; the handler holds no per-request
    state of its own."""

    app: SettingsApp
    log_sink: Any  # Callable[[str], None]
    _request_deadline_s: float = _REQUEST_DEADLINE_S
    _deadline_clock = staticmethod(time.monotonic)

    def setup(self) -> None:
        # The request socket is wrapped so every read's timeout is the
        # smaller of the per-recv timeout and what remains of the
        # whole-request budget: the per-recv timeout bounds one read,
        # not the request, and a slow drip resets it on every byte.
        self.request = _DeadlineBoundSocket(
            self.request,
            self._deadline_clock,
            self._request_deadline_s,
            self.timeout if self.timeout is not None else _REQUEST_TIMEOUT_S,
        )
        super().setup()

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            response = self._dispatch(method)
        except TimeoutError:
            # The whole-request budget lapsed mid-request (the body
            # read is where a drip that got past the request line dies):
            # the connection is closed and the slot released, and
            # nothing is answered, because a client this slow is not a
            # request but a connection test.
            self.close_connection = True
            self.log_error("the request deadline lapsed")
            return
        except Exception as exc:  # noqa: BLE001 -- a bug must not echo values
            self.log_sink(f"internal error handling {method}: {type(exc).__name__}")
            # The one bare inline body in the layer, deliberately: the
            # app is failing, so building the error through a full page
            # render could fail again; fixed text, nothing echoed.
            response = Response(500, b"<html><body><p>internal error</p></body></html>")
        self._send(response)

    def _dispatch(self, method: str) -> Response:
        path, _, query = self.path.partition("?")
        cookie = self._cookie()
        addr = remote_address(self.client_address)
        if method == "GET":
            return self.app.get(path, query, cookie, addr)
        error = self._read_form_error()
        if error is not None:
            return error
        form = parse_form(self._body)
        return self.app.post(path, form, cookie, addr)

    def _cookie(self) -> str:
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "atlas_settings_session":
                return value.strip()
        return ""

    def _read_form_error(self) -> Response | None:
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type != _FORM_CONTENT_TYPE:
            return Response(
                415, b"<html><body><p>unsupported content type</p></body></html>"
            )
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return Response(411, b"<html><body><p>length required</p></body></html>")
        try:
            length = int(raw_length)
        except ValueError:
            return Response(400, b"<html><body><p>bad request</p></body></html>")
        if length < 0:
            # A negative length is a malformed request, not an oversized
            # body — it answers 400, the honest status.
            return Response(400, b"<html><body><p>bad request</p></body></html>")
        if length > MAX_BODY_BYTES:
            return Response(
                413, b"<html><body><p>request body too large</p></body></html>"
            )
        body = self._read_exactly(length)
        if body is None:
            # The body ended before its promised length: a malformed
            # request, and never a form to parse — a truncated body must
            # not be processed as if it were whole.
            return Response(400, b"<html><body><p>bad request</p></body></html>")
        self._body = body
        return None

    def _read_exactly(self, length: int) -> bytes | None:
        """Exactly `length` bytes, or `None` when the body ended short.
        `BufferedReader.read` on a timeout-mode socket returns what one
        raw read produced, so a single `read(length)` can return a
        truncated body — and a truncated form must never be parsed as
        if it were whole. The loop is also what makes the body drip
        hold the slot: every raw read drains the same whole-request
        budget, and the read that outlives it raises."""
        chunks: list[bytes] = []
        got = 0
        while got < length:
            chunk = self.rfile.read(length - got)
            if not chunk:
                return None
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        if response.location is not None:
            self.send_header("Location", response.location)
        if response.set_cookie is not None:
            self.send_header("Set-Cookie", response.set_cookie)
        # `end_headers` adds the decided security headers, for this
        # response and for every other response the handler sends.
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def end_headers(self) -> None:
        """The decided security headers ride every response this handler
        sends — its own, and the stdlib-generated error pages (`send_error`'s
        400/501/505), which flush through here too. One source: a header
        added to `_send` alone would skip the error pages."""
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        """The stdlib's error pages, sent as real HTTP/1.x replies. A
        request line that failed to parse leaves `request_version` at
        the HTTP/0.9 default, under which the stdlib sends a bare body
        with no status line and no headers at all — an error answer is
        still a response this page sends, so it goes out with a status
        line and the decided security headers. The body stays the
        stdlib's fixed error page; nothing from the request is echoed."""
        self.request_version = "HTTP/1.1"
        super().send_error(code, message, explain)

    def log_message(self, format: str, *args: object) -> None:
        """Never runs: the stdlib's default access-log line would carry
        the request line's query, and the query is where the OAuth code
        and state live."""

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """The request log: the method, the path without its query, and
        the status — never the query itself, so a log line can never
        carry a secret."""
        # `getattr`: a request line that failed to parse never set
        # `path`, and `send_error` logs before and after that point —
        # the malformed-request log line must not raise of its own.
        path = getattr(self, "path", "").partition("?")[0]
        command = getattr(self, "command", "") or "-"
        self.log_sink(f"{command} {path} {code}")

    def log_error(self, format: str, *args: object) -> None:
        command = getattr(self, "command", "") or "-"
        path = getattr(self, "path", "").partition("?")[0]
        self.log_sink(f"{command} {path} error")


def serve(
    app: SettingsApp,
    host: str,
    port: int,
    log_sink: Any,
    *,
    max_concurrent: int | None = None,
    request_timeout_s: float | None = None,
    request_deadline_s: float | None = None,
    deadline_clock: Callable[[], float] | None = None,
) -> ThreadingHTTPServer:
    """The page's server: threads per request, bounded — at most
    `_MAX_CONCURRENT_REQUESTS` requests are handled at once, and a
    connection arriving while every handler is busy is answered 503 and
    closed rather than queued without bound (excess capacity is the
    socket backlog's). Each request's socket read is bounded by
    `_REQUEST_TIMEOUT_S`, and the whole request — line, headers, body —
    by `_REQUEST_DEADLINE_S` on the monotonic clock: the per-recv
    timeout alone is reset by every byte a slow drip sends, so only the
    total budget bounds how long one connection can hold a handler
    slot. The page's own state is lock-guarded; the store's
    per-installation `flock` serializes against the review service's
    writes."""

    class Bound(SettingsHandler):
        pass

    Bound.timeout = (
        _REQUEST_TIMEOUT_S if request_timeout_s is None else request_timeout_s
    )
    Bound._request_deadline_s = (
        _REQUEST_DEADLINE_S if request_deadline_s is None else request_deadline_s
    )
    if deadline_clock is not None:
        # staticmethod, as with log_sink: a plain function as a class
        # attribute would become a method, and its first argument would
        # be the handler.
        Bound._deadline_clock = staticmethod(deadline_clock)
    Bound.app = app
    # staticmethod: a plain function assigned to a class attribute
    # becomes a method, and the sink's first argument would be the
    # handler itself.
    Bound.log_sink = staticmethod(log_sink)
    server = SettingsServer((host, port), Bound, max_concurrent=max_concurrent)
    return server
