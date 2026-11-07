# SPDX-License-Identifier: MIT
"""Minimal HTTP transport (stdlib only) shared by the live adapters.

Redirects are never followed automatically: urllib would replay the
`Authorization` header to whatever host a redirect names, and GitHub's log
and tarball endpoints redirect to third-party blob storage. Callers that
expect a redirect follow it themselves, without credentials.
"""

from __future__ import annotations

import contextlib
import http.client
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, Self
from urllib.parse import SplitResult, urlsplit

from atlas_reviewer.ports import (
    BoundaryError,
    ResponseTooLargeError,
    StreamTimeoutError,
)

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        lowered = {k.lower(): v for k, v in self.headers.items()}
        return lowered.get(name.lower())


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
        max_bytes: int | None = None,
    ) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_url(url: str) -> str:
    """URL without query string, for error messages."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class UrllibTransport:
    def __init__(
        self,
        max_bytes: int = DEFAULT_MAX_BYTES,
        allowed_schemes: frozenset[str] = frozenset({"https"}),
    ) -> None:
        self._max_bytes = max_bytes
        self._schemes = allowed_schemes
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
        max_bytes: int | None = None,
    ) -> HttpResponse:
        if urlsplit(url).scheme not in self._schemes:
            raise BoundaryError(f"refusing non-allowed URL scheme: {safe_url(url)}")
        req = urllib.request.Request(
            url, data=body, method=method, headers=dict(headers)
        )
        cap = min(max_bytes, self._max_bytes) if max_bytes else self._max_bytes
        try:
            with self._opener.open(req, timeout=timeout_s) as resp:
                return HttpResponse(
                    resp.status, dict(resp.headers), _read(resp, cap, url)
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers or {}), _read(exc, cap, url))
        except (urllib.error.URLError, OSError) as exc:
            raise BoundaryError(f"{method} {safe_url(url)} failed: {exc}") from exc


@dataclass(frozen=True)
class StreamWindow:
    """Wall-clock limits for one streamed response, both measured from when
    the request starts: `total_s` for the whole exchange, `first_byte_s`
    (if set) for the first response body byte. Connect, send and the
    response headers share one cutoff at the first-byte deadline (or the
    total, without one); each body read then gets what is left."""

    total_s: float
    first_byte_s: float | None = None

    def wait_s(self, elapsed: float, got_any: bool) -> float:
        total = self.total_s - elapsed
        if got_any or self.first_byte_s is None:
            return total
        return min(total, self.first_byte_s - elapsed)


class StreamingTransport(Transport, Protocol):
    def stream(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        window: StreamWindow,
        max_bytes: int | None = None,
    ) -> HttpResponse: ...


class UrllibStreamingTransport(UrllibTransport):
    """Adds `stream`, which reads the body as it arrives so a stall keeps
    the bytes that did arrive and a silent response fails at its
    first-byte deadline instead of the per-read socket timeout. It uses
    `http.client` directly (no proxy support) because urllib exposes no
    way to change the socket timeout between reads."""

    def stream(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        window: StreamWindow,
        max_bytes: int | None = None,
    ) -> HttpResponse:
        parts = urlsplit(url)
        if parts.scheme not in self._schemes:
            raise BoundaryError(f"refusing non-allowed URL scheme: {safe_url(url)}")
        cap = min(max_bytes, self._max_bytes) if max_bytes else self._max_bytes
        stream = _Stream(method, url, window, time.monotonic())
        before_body = window.wait_s(0.0, got_any=False)
        conn = _connection(parts, before_body)
        cutoff = _Cutoff(conn, before_body)
        try:
            with cutoff:
                conn.connect()
                sock = conn.sock
                conn.request(method, _target(parts), body=body, headers=dict(headers))
                resp = conn.getresponse()
            if cutoff.fired.is_set():
                raise stream.stalled(b"")
            data = _drain(resp, sock, stream, cap)
            return HttpResponse(resp.status, dict(resp.getheaders()), data)
        except StreamTimeoutError:
            raise
        except TimeoutError as exc:
            raise stream.stalled(b"") from exc
        except (OSError, http.client.HTTPException) as exc:
            if cutoff.fired.is_set():
                raise stream.stalled(b"") from exc
            raise BoundaryError(f"{method} {safe_url(url)} failed: {exc}") from exc
        finally:
            conn.close()


class _Cutoff:
    """Shuts the connection's socket down once `after_s` has passed. A
    socket timeout restarts on every blocking call, so on its own it lets a
    server that trickles header bytes hold the exchange open indefinitely;
    this makes connect, send and the headers share one deadline."""

    def __init__(self, conn: http.client.HTTPConnection, after_s: float) -> None:
        self._conn = conn
        self.fired = threading.Event()
        self._timer = threading.Timer(max(after_s, 0.0), self._cut)
        self._timer.daemon = True

    def __enter__(self) -> Self:
        self._timer.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._timer.cancel()

    def _cut(self) -> None:
        self.fired.set()
        sock = self._conn.sock
        if sock is not None:
            with contextlib.suppress(OSError):  # already closed by the caller
                sock.shutdown(socket.SHUT_RDWR)


def _connection(parts: SplitResult, timeout_s: float) -> http.client.HTTPConnection:
    cls = (
        http.client.HTTPSConnection
        if parts.scheme == "https"
        else http.client.HTTPConnection
    )
    return cls(parts.hostname or "", parts.port, timeout=max(timeout_s, 0.001))


def _target(parts: SplitResult) -> str:
    return f"{parts.path or '/'}{'?' + parts.query if parts.query else ''}"


@dataclass(frozen=True)
class _Stream:
    method: str
    url: str
    window: StreamWindow
    started: float

    def wait_s(self, got_any: bool) -> float:
        return self.window.wait_s(time.monotonic() - self.started, got_any)

    def stalled(self, received: bytes) -> StreamTimeoutError:
        first = self.window.first_byte_s is not None and not received
        limit = self.window.first_byte_s if first else self.window.total_s
        what = (
            "no response byte"
            if first
            else f"response incomplete after {len(received)} byte(s)"
        )
        return StreamTimeoutError(
            f"{self.method} {safe_url(self.url)}: {what} within {limit:g}s",
            received,
            first_byte=first,
        )


def _drain(
    resp: http.client.HTTPResponse, sock: socket.socket, stream: _Stream, cap: int
) -> bytes:
    received = bytearray()
    while len(received) <= cap:
        wait = stream.wait_s(got_any=bool(received))
        if wait <= 0:
            raise stream.stalled(bytes(received))
        sock.settimeout(wait)
        try:
            chunk = resp.read1(64 * 1024)
        except TimeoutError as exc:
            raise stream.stalled(bytes(received)) from exc
        if not chunk:
            return bytes(received)
        received += chunk
    raise ResponseTooLargeError(
        f"response from {safe_url(stream.url)} exceeded {cap} bytes"
    )


def _read(stream: object, cap: int, url: str) -> bytes:
    read = getattr(stream, "read")  # noqa: B009
    data: bytes = read(cap + 1)
    if len(data) > cap:
        raise ResponseTooLargeError(
            f"response from {safe_url(url)} exceeded {cap} bytes"
        )
    return data
