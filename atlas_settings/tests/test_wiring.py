# SPDX-License-Identifier: MIT
"""The remaining branches the flows don't reach on their own: the
unrouted paths, the stylesheet, the store-broken write paths, the audit
gap, the callback's rate limit, and the page render's fallbacks."""

import threading
from pathlib import Path

from atlas_reviewer.installation_store import InstallationStore
from atlas_settings.phrases import GATE_REFUSED
from atlas_settings.server import serve

from .harness import (
    FAKE_KEY,
    GOOD_ENDPOINT,
    GOOD_MODEL,
    UNKNOWN_MODEL,
    build_world,
    sign_in,
)


def test_an_index_visit_while_signed_in_redirects_to_settings(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    response = world.app.get("/", "", world.cookie, "1.2.3.4")
    assert response.status == 303
    assert response.location == "/settings"


def test_the_stylesheet_is_served_and_unknown_paths_404(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    response = world.app.get("/static/styles.css", "", "", "1.2.3.4")
    assert response.status == 200
    assert response.content_type == "text/css; charset=utf-8"
    assert b"font-family" in response.body
    assert world.app.get("/no/such/page", "", "", "1.2.3.4").status == 404


def test_a_write_with_a_missing_field_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    csrf = world.csrf()
    for fields in (
        {"base_url": GOOD_ENDPOINT, "key": FAKE_KEY, "model": ""},
        {"base_url": GOOD_ENDPOINT, "key": "", "model": GOOD_MODEL},
        {"base_url": "", "key": FAKE_KEY, "model": GOOD_MODEL},
    ):
        response = world.app.post(
            "/settings/credentials",
            {"csrf": csrf, **fields},
            world.cookie,
            "1.2.3.4",
        )
        assert response.status == 400, fields
        assert "all required" in response.body.decode()
    record = world.app.store.load("42")
    assert record is None or not record.has_credentials


def test_a_broken_store_refuses_every_write(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    broken = InstallationStore.open(world.state_dir, {})
    assert not broken.configured
    world.app.store = broken
    for path, fields in (
        ("/settings/revoke", {}),
        ("/settings/cap", {"cap_usd": "5"}),
        ("/settings/delete", {"confirm": "DELETE"}),
        ("/settings/consent", {"acknowledge": "1"}),
    ):
        response = world.app.post(
            path, {"csrf": csrf, **fields}, world.cookie, "1.2.3.4"
        )
        assert response.status == 503, (path, response.status)
        assert "the installation store refused the change" in response.body.decode()


def test_an_audit_failure_after_a_write_says_the_write_was_applied(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()

    class FailingAudit:
        def record(self, *args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        def last_credentials_at(self, installation: str):
            return None

    world.app.audit = FailingAudit()  # type: ignore[assignment]
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 500
    assert "was applied but could not be recorded" in response.body.decode()
    # The write itself went through: the cap is in the store.
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd is not None


def test_the_callback_is_rate_limited_with_the_login_window(
    tmp_path: Path,
) -> None:
    from atlas_settings.app import LOGIN_LIMIT

    world = build_world(tmp_path)
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    for _ in range(LOGIN_LIMIT - 1):
        world.app.get("/login", "", "", "1.2.3.4")
    response = world.app.get("/callback", f"code=c&state={state}", cookie, "1.2.3.4")
    assert response.status == 429


def test_the_settings_page_refuses_when_rights_are_lost(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world, org=True)
    world.github.membership = {"role": "member", "state": "active"}
    response = world.app.get("/settings", "", world.cookie, "1.2.3.4")
    assert response.status == 403
    assert GATE_REFUSED not in response.body.decode()
    assert "not an administrator" in response.body.decode()


def test_the_settings_page_refuses_when_the_gate_is_lost(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.github.repos = ["someone-else/other-repo"]
    response = world.app.get("/settings", "", world.cookie, "1.2.3.4")
    assert response.status == 403
    assert GATE_REFUSED in response.body.decode()


def test_the_settings_page_refuses_when_the_store_is_broken(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    # A record on disk is what makes the keyless store *broken* rather
    # than unconfigured: the records it cannot read may hold state.
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    broken = InstallationStore.open(world.state_dir, {})
    assert broken.broken_reason
    world.app.store = broken
    response = world.app.get("/settings", "", world.cookie, "1.2.3.4")
    assert response.status == 503
    assert "the installation store refused the change" in response.body.decode()


def test_the_refusal_render_falls_back_when_the_account_cannot_be_read(
    tmp_path: Path,
) -> None:
    """A refused write's re-render reads the installation's account for
    its display; a read that fails shows the placeholder instead of
    failing the refusal render."""
    world = build_world(tmp_path)
    sign_in(world)
    session = world.app.sessions.get(world.cookie)
    assert session is not None
    # The render reads the installation's account for its display; a
    # read that fails shows the placeholder instead of failing the
    # refusal render.
    world.github.api_error = TimeoutError("timed out")
    response = world.app._settings_render(session, "the refusal phrase", 400)
    assert response.status == 400
    assert "the refusal phrase" in response.body.decode()
    assert "<td>- (-)</td>" in response.body.decode()


def test_the_audit_gap_does_not_lose_the_written_value(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    # A credentials save with the unknown model exercises the model
    # refusal render's fallback path too.
    response = world.app.post(
        "/settings/credentials",
        {
            "csrf": world.csrf(),
            "base_url": GOOD_ENDPOINT,
            "key": FAKE_KEY,
            "model": UNKNOWN_MODEL,
        },
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 400
    assert "the model was refused" in response.body.decode()
    record = world.app.store.load("42")
    assert record is not None
    assert not record.has_credentials


def test_a_bad_content_length_and_a_garbage_request_line_are_answered(
    tmp_path: Path,
) -> None:
    """The handler's own bad-request paths (mypy for the server module):
    a non-integer Content-Length answers 400, and a request line the
    parser cannot read still logs without a query string."""
    import socket as socket_module

    world = build_world(tmp_path)
    server = serve(world.app, "127.0.0.1", 0, lambda line: world.logs.append(line))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket_module.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        sock.sendall(
            b"POST /settings/cap HTTP/1.0\r\nHost: x\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: abc\r\n\r\n"
        )
        raw = sock.recv(4096)
        sock.close()
        assert raw.startswith(b"HTTP/1.0 400 "), raw[:60]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_error_log_line_never_carries_the_query(tmp_path: Path) -> None:
    """`log_error` is called on stdlib parse errors; its line is built
    the same safe way `log_request`'s is."""
    from atlas_settings.server import SettingsHandler

    world = build_world(tmp_path)
    handler = SettingsHandler.__new__(SettingsHandler)
    handler.command = "GET"
    handler.path = "/callback?code=fake-code&state=fake-state"
    handler.log_sink = world.logs.append
    handler.log_error("boom %s", "arg")
    assert world.logs == ["GET /callback error"]


def test_the_credentials_time_falls_back_to_the_record(
    tmp_path: Path,
) -> None:
    """When the audit loses its file, a stored credential's shown time
    falls back to the record's own `updated_at` — the page shows a real
    time, not the not-on-record line a missing credential would produce
    (kills the fallback's dropped-record mutant)."""
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials",
        {
            "csrf": world.csrf(),
            "base_url": GOOD_ENDPOINT,
            "key": FAKE_KEY,
            "model": GOOD_MODEL,
        },
        world.cookie,
        "1.2.3.4",
    )
    (tmp_path / "state" / "settings-audit.jsonl").unlink()
    page = world.page_text()
    assert "Credentials last saved:" in page
    assert "not on record" not in page
