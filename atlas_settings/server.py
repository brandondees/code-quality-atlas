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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from atlas_settings.app import (
    MAX_BODY_BYTES,
    Response,
    SettingsApp,
    parse_form,
    remote_address,
)

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
# The bounded server: how many requests are handled at once, and how
# long one request may take to arrive before its connection is closed.
_MAX_CONCURRENT_REQUESTS = 20
_REQUEST_TIMEOUT_S = 30.0


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
            peer.sendall(
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
        except OSError:
            pass
        finally:
            self.shutdown_request(request)


class SettingsHandler(BaseHTTPRequestHandler):
    """One request. The `app` and `log_sink` are class attributes set by
    `serve`; the handler holds no per-request state of its own."""

    app: SettingsApp
    log_sink: Any  # Callable[[str], None]

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            response = self._dispatch(method)
        except Exception as exc:  # noqa: BLE001 -- a bug must not echo values
            self.log_sink(f"internal error handling {method}: {type(exc).__name__}")
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
        if length < 0 or length > MAX_BODY_BYTES:
            return Response(
                413, b"<html><body><p>request body too large</p></body></html>"
            )
        self._body = self.rfile.read(length)
        return None

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'",
        )
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if response.location is not None:
            self.send_header("Location", response.location)
        if response.set_cookie is not None:
            self.send_header("Set-Cookie", response.set_cookie)
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        """Never the request line: it carries the OAuth code and state
        in the query. What is logged is the method, the path without its
        query, and nothing else — a log line can never carry a secret."""

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
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
) -> ThreadingHTTPServer:
    """The page's server: threads per request, bounded — at most
    `_MAX_CONCURRENT_REQUESTS` requests are handled at once, and a
    connection arriving while every handler is busy is answered 503 and
    closed rather than queued without bound (excess capacity is the
    socket backlog's). Each request's socket read is bounded by
    `_REQUEST_TIMEOUT_S`, so a client that opens a connection and never
    finishes its request line cannot hold a handler forever. The page's
    own state is lock-guarded; the store's per-installation `flock`
    serializes against the review service's writes."""

    class Bound(SettingsHandler):
        pass

    Bound.timeout = (
        _REQUEST_TIMEOUT_S if request_timeout_s is None else request_timeout_s
    )
    Bound.app = app
    # staticmethod: a plain function assigned to a class attribute
    # becomes a method, and the sink's first argument would be the
    # handler itself.
    Bound.log_sink = staticmethod(log_sink)
    server = SettingsServer((host, port), Bound, max_concurrent=max_concurrent)
    return server
