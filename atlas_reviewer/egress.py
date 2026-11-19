# SPDX-License-Identifier: MIT
"""The tenant endpoint's egress guard (config slice S10, D81 §4): a
user-supplied base URL is user-controlled egress, so the model calls to
it are HTTPS-only and can never reach a private, link-local, loopback,
or metadata address -- over IPv4 *and* IPv6.

The check runs at connect time and pins the address it checked for the
connection: every address the hostname resolves to is validated against
the blocked set first, then the socket connects to one of the allowed
addresses while the TLS handshake still presents the original hostname
(SNI and certificate verification), so a DNS rebinding double -- a
resolver that answers a public address to the checker and a private one
to the connector -- has nothing to rebind to. A hostname that resolves
to any blocked address is refused whole: the connection never races
round-robin against the check.

The blocked set is the plan's §4 list -- the RFC 1918 ranges,
`127.0.0.0/8`, `169.254.0.0/16` (link-local and the cloud metadata
service on it), `0.0.0.0/8`, the carrier-grade `100.64.0.0/10`, the
ULA `fc00::/7`, link-local `fe80::/10`, `::1`, the unspecified `::`,
and all IPv4-mapped IPv6 `::ffff:0:0/96` -- plus the IPv4 multicast,
benchmarking and reserved ranges, which no HTTPS model API can live on.
Redirects are refused rather than re-checked: the transport never
follows one, and the tenant provider refuses a 3xx answer by name.

Responses are model replies: untrusted under the existing pipeline, and
bounded by the same byte cap and timeouts every other request runs
under.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from atlas_reviewer.http import HttpResponse, safe_url
from atlas_reviewer.ports import BoundaryError, ResponseTooLargeError

BLOCKED_V4 = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
)
BLOCKED_V6 = (
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class EgressRefused(BoundaryError):
    """The endpoint's address is in the blocked set, or the URL is not
    HTTPS. The review fails with this named; nothing falls back."""


@dataclass(frozen=True)
class Pinned:
    """One validated, resolved address: the family and socket address a
    connection may use, checked against the blocked set at resolution
    time."""

    family: int
    sockaddr: tuple[str, int]


def blocked_reason(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str | None:
    """Why the address is unreachable for a tenant endpoint, or None.
    The reason names the blocked range -- fixed text, the same words
    every refusal carries. An IPv4-mapped address is caught by
    `::ffff:0:0/96` itself, so a resolver that answers a v4 address in
    v6-mapped form meets the same checks the v4 address would."""
    networks = BLOCKED_V6 if address.version == 6 else BLOCKED_V4
    for network in networks:
        if address in network:
            return f"egress refused: the endpoint's address is in {network}"
    return None


def resolve_and_check(host: str, port: int) -> Pinned:
    """Resolve `host` and check every address the resolver answers with.

    Any blocked address refuses the host whole -- the connection must
    never race a round-robin resolver -- and the returned `Pinned` is
    the one allowed address the socket connects to, so the address the
    check approved is the address that connects. A resolver failure is
    the named refusal it is here, not a silent retry."""
    if host == "":
        raise EgressRefused("egress refused: the endpoint names no host")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressRefused(
            f"egress refused: the endpoint's host does not resolve ({exc})"
        ) from exc
    allowed: list[Pinned] = []
    for family, _type, _proto, _canonname, sockaddr in infos:
        address = ipaddress.ip_address(sockaddr[0])
        reason = blocked_reason(address)
        if reason is not None:
            raise EgressRefused(reason)
        entry = Pinned(family, (str(sockaddr[0]), int(sockaddr[1])))
        if not any(pinned.sockaddr == entry.sockaddr for pinned in allowed):
            allowed.append(entry)
    if not allowed:
        raise EgressRefused("egress refused: the endpoint's host has no address")
    return allowed[0]


def check_url(url: str) -> None:
    """The URL-level half of the guard: HTTPS only, a hostname, and no
    userinfo. Run before anything resolves; the address-level half runs
    per connection."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise EgressRefused(
            "egress refused: the tenant endpoint must be an https:// URL"
        )
    if not parts.hostname:
        raise EgressRefused("egress refused: the tenant endpoint names no host")
    if parts.username is not None or parts.password is not None:
        raise EgressRefused(
            "egress refused: the tenant endpoint must not carry userinfo"
        )


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection to the address the egress check approved.

    `connect` skips the class's own DNS resolution -- which is the
    rebinding hole: a second resolution could answer a different
    address -- and connects the socket to the pinned address instead,
    then wraps TLS with the original hostname so SNI and certificate
    verification still name the endpoint the caller asked for."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        pinned: Pinned,
        context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned = pinned
        self._tls = context if context is not None else ssl.create_default_context()

    def connect(self) -> None:
        sock = socket.socket(self._pinned.family, socket.SOCK_STREAM)
        if self.timeout is not None and self.timeout > 0:
            sock.settimeout(self.timeout)
        sock.connect(self._pinned.sockaddr)
        try:
            self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)
        except (OSError, ValueError):
            sock.close()
            raise


def _target(parts: SplitResult) -> str:
    return f"{parts.path or '/'}{'?' + parts.query if parts.query else ''}"


Connect = Callable[[str, int, float, Pinned], PinnedHTTPSConnection]


def _default_connect(host: str, port: int, timeout: float, pinned: Pinned):
    return PinnedHTTPSConnection(host, port, timeout, pinned)


class TenantEndpointTransport:
    """The transport a tenant model call runs on: the URL-level check,
    the pinned connect, the per-operation timeout, and the byte cap.
    Redirects are never followed -- a 3xx reaches the caller, and the
    provider refuses it by name."""

    def __init__(self, max_bytes: int, *, connect: Connect | None = None) -> None:
        self._max_bytes = max_bytes
        self._connect = connect if connect is not None else _default_connect

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
        max_bytes: int | None = None,
    ) -> HttpResponse:
        check_url(url)
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port if parts.port is not None else 443
        pinned = resolve_and_check(host, port)
        cap = self._max_bytes if max_bytes is None else min(max_bytes, self._max_bytes)
        conn = self._connect(host, port, timeout_s, pinned)
        try:
            conn.request(method, _target(parts), body=body, headers=dict(headers))
            resp = conn.getresponse()
            data = resp.read(cap + 1)
            if len(data) > cap:
                raise ResponseTooLargeError(
                    f"response from {safe_url(url)} exceeded {cap} bytes"
                )
            return HttpResponse(resp.status, dict(resp.getheaders()), data)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise BoundaryError(f"{method} {safe_url(url)} failed: {exc}") from exc
        finally:
            conn.close()
