# SPDX-License-Identifier: MIT
"""The HTTP handler: the security headers on every response, the bounded
body, the content-type gate, the log lines that never carry a query
string, and one full flow served over a real loopback socket."""

import http.client
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from atlas_settings.server import serve

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
