# SPDX-License-Identifier: MIT
"""Minimal HTTP transport (stdlib only) shared by the live adapters.

Redirects are never followed automatically: urllib would replay the
`Authorization` header to whatever host a redirect names, and GitHub's log
and tarball endpoints redirect to third-party blob storage. Callers that
expect a redirect follow it themselves, without credentials.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from atlas_reviewer.ports import BoundaryError

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
    ) -> HttpResponse:
        if urlsplit(url).scheme not in self._schemes:
            raise BoundaryError(f"refusing non-allowed URL scheme: {safe_url(url)}")
        req = urllib.request.Request(
            url, data=body, method=method, headers=dict(headers)
        )
        try:
            with self._opener.open(req, timeout=timeout_s) as resp:
                return HttpResponse(resp.status, dict(resp.headers), self._read(resp))
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers or {}), self._read(exc))
        except (urllib.error.URLError, OSError) as exc:
            raise BoundaryError(f"{method} {safe_url(url)} failed: {exc}") from exc

    def _read(self, stream: object) -> bytes:
        read = getattr(stream, "read")  # noqa: B009
        data: bytes = read(self._max_bytes + 1)
        if len(data) > self._max_bytes:
            raise BoundaryError(f"response exceeded {self._max_bytes} bytes")
        return data
