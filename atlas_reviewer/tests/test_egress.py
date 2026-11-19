# SPDX-License-Identifier: MIT
"""The tenant endpoint's egress guard (config slice S10, D81 §4): every
blocked range over IPv4 and IPv6, the rebinding double that refuses the
whole host, the pinned connect, the HTTPS-only URL check, and the
transport's byte cap and redirect pass-through. Offline: no socket ever
connects -- the resolver and the connect are test seams."""

import ipaddress
import socket

import pytest

from atlas_reviewer.egress import (
    BLOCKED_V4,
    BLOCKED_V6,
    EgressRefused,
    Pinned,
    PinnedHTTPSConnection,
    TenantEndpointTransport,
    blocked_reason,
    check_url,
    resolve_and_check,
)
from atlas_reviewer.ports import BoundaryError, ResponseTooLargeError

PUBLIC_V4 = ipaddress.ip_address("8.8.8.8")
PUBLIC_V6 = ipaddress.ip_address("2606:4700:4700::1111")


# ------------------------------------------------------- the blocked set


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "127.0.0.1",
        "127.8.8.8",
        "169.254.169.254",
        "0.0.0.0",
        "0.1.2.3",
        "100.64.0.1",
        "100.127.255.255",
        "224.0.0.1",
        "240.0.0.1",
    ],
)
def test_every_blocked_ipv4_range_is_refused_by_name(address):
    reason = blocked_reason(ipaddress.ip_address(address))
    assert reason is not None
    assert reason.startswith("egress refused: the endpoint's address is in ")


@pytest.mark.parametrize(
    "address",
    [
        "::",
        "::1",
        "::7f00:1",
        "::127.0.0.1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        # The whole IPv4-mapped range is blocked, public mapped
        # addresses included: the resolver that answers v4 as v6-mapped
        # does not get around the v4 checks.
        "::ffff:8.8.8.8",
        "64:ff9b::7f00:1",
        "64:ff9b:1::1",
        "100::1",
        "2001:0:7f00:1::",
        "2001::1",
        "2002:7f00:1::",
        "fc00::1",
        "fd00::1",
        "fe80::1",
        "febf::1",
        "ff01::1",
        "ff0e::1",
    ],
)
def test_every_blocked_ipv6_range_is_refused_by_name(address):
    reason = blocked_reason(ipaddress.ip_address(address))
    assert reason is not None
    assert "egress refused" in reason


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_a_public_address_is_allowed(address):
    assert blocked_reason(ipaddress.ip_address(address)) is None


def test_the_blocked_set_names_the_plans_required_ranges():
    """The plan §4 list is the minimum, and the round-1 additions are
    the decided beyond-it set: assert the exact networks are present, so
    trimming the set cannot happen silently. The networks are compared
    parsed, not as strings -- some Pythons print an IPv4-mapped network
    as `::ffff:0.0.0.0/96` and some as `::ffff:0:0/96`, and the set's
    membership is what the guard runs on."""
    blocked = (*BLOCKED_V4, *BLOCKED_V6)
    for required in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "0.0.0.0/8",
        "100.64.0.0/10",
        "224.0.0.0/4",
        "240.0.0.0/4",
        # The plan §4 list, then the round-1 additions: the
        # IPv4-embedding IPv6 forms an HTTPS model API has no business
        # on, the discard-only range, and IPv6 multicast.
        "::/96",
        "::1/128",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/32",
        "2002::/16",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    ):
        wanted = ipaddress.ip_network(required)
        assert any(network == wanted for network in blocked), (
            f"the blocked set lost {required}"
        )


# --------------------------------------------- resolve, check, and pin


def _infos(*addresses):
    """getaddrinfo-shaped results for one or more addresses (v4 and v6
    mixed, the order a resolver answers in)."""
    out = []
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if parsed.version == 6 else (address, 443)
        out.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
    return out


@pytest.fixture
def resolver(monkeypatch):
    answers: dict[str, list[tuple[int, int, int, str, tuple]]] = {}

    def install(host: str, *addresses):
        answers[host] = _infos(*addresses)
        monkeypatch.setattr(
            "atlas_reviewer.egress.socket.getaddrinfo",
            lambda h, p, type=0, **_kw: answers[h],
        )
        return answers[host]

    return install


def test_a_single_public_address_resolves_to_a_pinned_connect(resolver):
    resolver("api.example.invalid", "8.8.8.8")
    pinned = resolve_and_check("api.example.invalid", 443)
    assert pinned == Pinned(socket.AF_INET, ("8.8.8.8", 443))


def test_a_public_v6_address_resolves_over_ipv6(resolver):
    resolver("api.example.invalid", "2606:4700:4700::1111")
    pinned = resolve_and_check("api.example.invalid", 443)
    assert pinned == Pinned(socket.AF_INET6, ("2606:4700:4700::1111", 443))


@pytest.mark.parametrize(
    "blocked",
    [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "0.1.2.3",
        "100.64.0.1",
        "fc00::1",
        "fe80::1",
        "::1",
        "::",
        "::ffff:127.0.0.1",
    ],
)
def test_any_blocked_address_refuses_the_whole_host(resolver, blocked):
    resolver("rebind.example.invalid", "8.8.8.8", blocked)
    with pytest.raises(EgressRefused) as exc:
        resolve_and_check("rebind.example.invalid", 443)
    assert "egress refused" in str(exc.value)


def test_the_blocked_reason_names_the_range_not_just_the_address(resolver):
    resolver("meta.example.invalid", "169.254.169.254")
    with pytest.raises(EgressRefused) as exc:
        resolve_and_check("meta.example.invalid", 443)
    assert "169.254.0.0/16" in str(exc.value)


def test_a_host_that_does_not_resolve_refuses_with_the_reason_named(
    monkeypatch,
):
    def raise_gaierror(host, port, type=0, **_kw):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr("atlas_reviewer.egress.socket.getaddrinfo", raise_gaierror)
    with pytest.raises(EgressRefused) as exc:
        resolve_and_check("nowhere.example.invalid", 443)
    assert "does not resolve" in str(exc.value)


def test_an_empty_host_refuses():
    with pytest.raises(EgressRefused):
        resolve_and_check("", 443)


# ------------------------------------------------------- the URL check


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.invalid/v1",
        "https://user:pass@api.example.invalid/v1",
        "ftp://api.example.invalid",
        "https:///no-host",
    ],
)
def test_a_non_https_or_hostless_url_is_refused_at_the_url_level(url):
    with pytest.raises(EgressRefused):
        check_url(url)


def test_an_https_url_with_a_host_passes_the_url_level_check():
    check_url("https://api.example.invalid/v1/chat/completions")


# -------------------------------------------------------- the transport


class _FakeConn:
    def __init__(self, status=200, body=b"{}", headers=None, fail=None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def request(self, method, target, body=None, headers=None):
        self.calls.append((method, target))
        if self.fail is not None:
            raise self.fail

    def getresponse(self):
        class _Resp:
            def __init__(self, conn):
                self._conn = conn

            def read(self, n):
                return self._conn.body

            def getheaders(self):
                return self._conn.headers

            status = property(lambda self: self._conn.status)

        return _Resp(self)

    def close(self):
        self.closed = True


def _transport(monkeypatch, pinned_address="8.8.8.8", conn=None, port=443):
    seen: dict[str, object] = {}
    connection = conn if conn is not None else _FakeConn()

    def connect(host, host_port, timeout, pinned):
        seen["host"] = host
        seen["port"] = host_port
        seen["timeout"] = timeout
        seen["pinned"] = pinned
        return connection

    monkeypatch.setattr(
        "atlas_reviewer.egress.resolve_and_check",
        lambda host, host_port: Pinned(
            socket.AF_INET, (pinned_address, host_port or port)
        ),
    )
    return TenantEndpointTransport(1024, connect=connect), seen, connection


def test_the_transport_connects_to_the_pinned_address_it_checked(monkeypatch):
    transport, seen, _conn = _transport(monkeypatch, pinned_address="8.8.8.8")
    transport.request("POST", "https://api.example.invalid/v1", {}, b"{}", 30.0)
    # The pinned address is what the socket connects to: the check and
    # the connect cannot disagree.
    assert seen["pinned"].sockaddr == ("8.8.8.8", 443)
    assert seen["host"] == "api.example.invalid"
    assert seen["port"] == 443
    assert seen["timeout"] == 30.0


def test_the_transport_sends_the_target_path_and_returns_the_response(
    monkeypatch,
):
    conn = _FakeConn(status=200, body=b'{"ok": true}')
    transport, _seen, _c = _transport(monkeypatch, conn=conn)
    result = transport.request(
        "POST", "https://api.example.invalid/v1/chat/completions", {}, b"{}", 30.0
    )
    assert conn.calls == [("POST", "/v1/chat/completions")]
    assert result.status == 200
    assert result.body == b'{"ok": true}'


def test_the_transport_enforces_the_byte_cap(monkeypatch):
    conn = _FakeConn(status=200, body=b"x" * 4096)
    transport, _seen, _c = _transport(monkeypatch, conn=conn)
    with pytest.raises(ResponseTooLargeError):
        transport.request("POST", "https://api.example.invalid/v1", {}, b"{}", 30.0)


def test_a_transport_failure_is_a_boundary_error_with_the_url_named(monkeypatch):
    conn = _FakeConn(fail=OSError("connection refused"))
    transport, _seen, _c = _transport(monkeypatch, conn=conn)
    with pytest.raises(BoundaryError) as exc:
        transport.request("POST", "https://api.example.invalid/v1", {}, b"{}", 30.0)
    assert "connection refused" in str(exc.value)
    assert "api.example.invalid" in str(exc.value)


def test_a_non_https_url_never_reaches_the_resolver(monkeypatch):
    transport, seen, _conn = _transport(monkeypatch)
    with pytest.raises(EgressRefused):
        transport.request("POST", "http://api.example.invalid/v1", {}, b"{}", 30.0)
    assert "host" not in seen


def test_a_three_digit_redirect_status_reaches_the_caller_unfollowed(
    monkeypatch,
):
    conn = _FakeConn(status=302, body=b"", headers={"Location": "https://other/"})
    transport, _seen, _c = _transport(monkeypatch, conn=conn)
    result = transport.request(
        "POST", "https://api.example.invalid/v1", {}, b"{}", 30.0
    )
    assert result.status == 302
    # One request, no follow-up: the provider refuses the redirect.
    assert conn.calls == [("POST", "/v1")]


def test_the_pinned_connection_closes_the_socket_when_the_connect_fails(
    monkeypatch,
):
    """A connect that raises closes the raw socket before re-raising:
    the caller's close sees no `self.sock` yet, so the one-shot leak
    would otherwise sit until the process ended."""
    closed: list[bool] = []

    class _FailingSocket:
        family = socket.AF_INET

        def settimeout(self, seconds):
            pass

        def connect(self, sockaddr):
            raise OSError("connection refused")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        "atlas_reviewer.egress.socket.socket",
        lambda family, kind: _FailingSocket(),
    )
    conn = PinnedHTTPSConnection(
        "api.example.invalid",
        443,
        5.0,
        Pinned(socket.AF_INET, ("8.8.8.8", 443)),
        context=None,
    )
    with pytest.raises(OSError):
        conn.connect()
    assert closed == [True]


def test_the_pinned_connection_dials_the_checked_address_and_presents_the_host(
    monkeypatch,
):
    """The connect pins the checked address but the TLS handshake still
    presents the endpoint's hostname (SNI and verification), so the
    certificate is checked against the name the caller asked for. The
    socket and the wrap are fakes; nothing dials out."""
    dialed: dict[str, object] = {}

    class _FakeSocket:
        family = socket.AF_INET

        def settimeout(self, seconds):
            dialed["timeout"] = seconds

        def connect(self, sockaddr):
            dialed["sockaddr"] = sockaddr

        def close(self):
            pass

    class _FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            dialed["server_hostname"] = server_hostname
            return sock

    monkeypatch.setattr(
        "atlas_reviewer.egress.socket.socket",
        lambda family, kind: _FakeSocket(),
    )
    conn = PinnedHTTPSConnection(
        "api.example.invalid",
        443,
        5.0,
        Pinned(socket.AF_INET, ("8.8.8.8", 443)),
        context=_FakeContext(),
    )
    conn.connect()
    assert dialed["sockaddr"] == ("8.8.8.8", 443)
    assert dialed["server_hostname"] == "api.example.invalid"
