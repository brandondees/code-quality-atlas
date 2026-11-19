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

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from atlas_settings.app import (
    MAX_BODY_BYTES,
    Response,
    SettingsApp,
    parse_form,
    remote_address,
)

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


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
        path = self.path.partition("?")[0]
        self.log_sink(f"{self.command} {path} {code}")

    def log_error(self, format: str, *args: object) -> None:
        path = self.path.partition("?")[0]
        self.log_sink(f"{self.command} {path} error")


def serve(app: SettingsApp, host: str, port: int, log_sink: Any) -> ThreadingHTTPServer:
    """The page's server: threads per request (the page's own state is
    lock-guarded; the store's per-installation `flock` serializes
    against the review service's writes), bound to the operator's
    host and port."""

    class Bound(SettingsHandler):
        pass

    Bound.app = app
    # staticmethod: a plain function assigned to a class attribute
    # becomes a method, and the sink's first argument would be the
    # handler itself.
    Bound.log_sink = staticmethod(log_sink)
    server = ThreadingHTTPServer((host, port), Bound)
    server.daemon_threads = True
    return server
