# SPDX-License-Identifier: MIT
"""The settings page's flows, part two of the split flow suite: the
write surface — rotation, revocation, the cap dial, delete-everything —
and the machinery every write runs through: the CSRF token, the expired
session, the admin rights lost mid-session, the gate re-checked on
every write, the rate limits, and the fake key and tokens that appear
nowhere across every flow. Part one (sign-in, intake, consent) is this
suite's first file."""

from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from atlas_settings.audit import AUDIT_FILE_NAME, AuditLog
from atlas_settings.phrases import (
    ADMIN_REFUSED,
    DELETE_MISMATCH,
    GATE_REFUSED,
    GITHUB_CHECK_FAILED,
    SESSION_EXPIRED,
)
from atlas_settings.server import serve

from .harness import (
    ADMIN_ID,
    FAKE_INSTALL_TOKEN,
    FAKE_KEY,
    FAKE_USER_TOKEN,
    GOOD_ENDPOINT,
    GOOD_MODEL,
    OTHER_REPO,
    _credentials_form,
    build_world,
    sign_in,
)

# ---- the write machinery --------------------------------------------


def test_a_github_failure_at_the_admin_check_refuses_fail_closed(
    tmp_path: Path,
) -> None:
    """The admin check's own read failing is the fail-closed refusal
    with the check-failed phrase, and the store is untouched."""
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.github.api_error = TimeoutError("timed out")
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 502
    assert GITHUB_CHECK_FAILED in response.body.decode()
    assert world.app.store.load("42") is None


def test_an_expired_session_redirects_reads_and_refuses_writes(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.bump_time(1801)
    read = world.app.get("/settings", "", world.cookie, "1.2.3.4")
    assert read.status == 303
    assert read.location == "/login"
    write = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert write.status == 403
    assert SESSION_EXPIRED in write.body.decode()
    # Nothing was stored.
    assert world.app.store.load("42") is None


def test_a_csrf_failure_changes_nothing(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    for path, fields in (
        ("/settings/consent", {"acknowledge": "1"}),
        ("/settings/cap", {"cap_usd": "5"}),
        ("/settings/revoke", {}),
        ("/settings/delete", {"confirm": "DELETE"}),
        (
            "/settings/credentials",
            {"base_url": GOOD_ENDPOINT, "key": FAKE_KEY, "model": GOOD_MODEL},
        ),
    ):
        response = world.app.post(path, fields, world.cookie, "1.2.3.4")
        assert response.status == 403, (path, response.status)
        assert "cross-site request token" in response.body.decode()
    assert world.app.store.load("42") is None
    assert not (world.state_dir / "installations" / "42.json").exists()


def test_a_same_length_forged_csrf_token_is_refused_the_same_way(
    tmp_path: Path,
) -> None:
    """The check runs even when the submitted token is the right shape:
    a wrong token of the same length is refused the same way (403).
    Constant-timeness itself is `compare_digest`'s guarantee, not this
    test's subject."""
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    forged = csrf[:-1] + ("0" if csrf[-1] != "0" else "1")
    response = world.app.post(
        "/settings/cap", {"csrf": forged, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 403


def test_admin_rights_lost_mid_session_refuse_every_write(tmp_path: Path) -> None:
    """The admin check is re-verified on every write, not only at
    login: an org admin demoted after sign-in is refused on the next
    write, fail closed."""
    world = build_world(tmp_path)
    sign_in(world, org=True)
    csrf = world.csrf()
    assert (
        world.app.post(
            "/settings/cap",
            {"csrf": csrf, "cap_usd": "5"},
            world.cookie,
            "1.2.3.4",
        ).status
        == 303
    )
    # The demotion lands between the write that worked and the next one;
    # the CSRF token was captured while the admin check still passed.
    world.github.membership = {"role": "member", "state": "active"}
    response = world.app.post(
        "/settings/cap",
        {"csrf": csrf, "cap_usd": "6"},
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 403
    assert ADMIN_REFUSED in response.body.decode()
    # The cap from the earlier write stands; the refused write stored
    # nothing.
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd == Decimal(5)
    world.github.membership = None
    response = world.app.post(
        "/settings/cap",
        {"csrf": csrf, "cap_usd": "6"},
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 403
    assert ADMIN_REFUSED in response.body.decode()
    # Reloaded, not the stale in-memory record: the refused write must
    # have stored nothing, and a stale object cannot show that.
    reloaded = world.app.store.load("42")
    assert reloaded is not None
    assert reloaded.daily_cap_usd == Decimal(5)


def test_the_gate_is_re_checked_on_every_write(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.github.repos = [OTHER_REPO]
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 403
    assert GATE_REFUSED in response.body.decode()
    assert world.app.store.load("42") is None


# ---- credentials -----------------------------------------------------


def test_rotation_replaces_the_key(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    rotated = "sk-rotated-key-9876543210-not-real-either"
    world.app.post(
        "/settings/credentials",
        _credentials_form(world, key=rotated, endpoint="https://api2.example.com"),
        world.cookie,
        "1.2.3.4",
    )
    record = world.app.store.load("42")
    assert record is not None
    assert record.base_url == "https://api2.example.com"
    assert record.key == rotated
    # The cap and the consent survived the rotation.
    assert record.daily_cap_usd is None
    assert record.consent_acknowledged_at is not None
    assert len(world.app.audit.entries("42", "store-credentials")) == 2


def test_revocation_removes_the_key_and_keeps_cap_and_consent(
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
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    world.app.post(
        "/settings/cap", {"csrf": world.csrf(), "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    revoked = world.app.post(
        "/settings/revoke", {"csrf": world.csrf()}, world.cookie, "1.2.3.4"
    )
    assert revoked.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert not record.has_credentials
    assert record.daily_cap_usd == Decimal(5)
    assert record.consent_acknowledged_at is not None
    assert "No key is stored" in world.page_text()


def test_every_write_leaves_its_own_audit_line(tmp_path: Path) -> None:
    """Revoke, set-cap and delete each record their own audit entry —
    the action's fact and the acting user, never any value."""
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    world.app.post(
        "/settings/cap", {"csrf": world.csrf(), "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    world.app.post("/settings/revoke", {"csrf": world.csrf()}, world.cookie, "1.2.3.4")
    deleted = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "DELETE"},
        world.cookie,
        "1.2.3.4",
    )
    assert deleted.status == 303
    for action, count in (
        ("store-credentials", 1),
        ("set-cap", 1),
        ("revoke-credentials", 1),
        ("delete-installation", 1),
    ):
        entries = world.app.audit.entries("42", action)
        assert len(entries) == count, (action, entries)
        assert entries[0]["github_user_id"] == ADMIN_ID
        # No write's value rides the audit line.
        assert FAKE_KEY not in json.dumps(entries)


# ---- the cap --------------------------------------------------------


def test_the_admin_sets_and_clears_the_cap(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    set_response = world.app.post(
        "/settings/cap",
        {"csrf": world.csrf(), "cap_usd": "5.25"},
        world.cookie,
        "1.2.3.4",
    )
    assert set_response.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd == Decimal("5.25")
    assert "$5.25 per UTC day" in world.page_text()
    cleared = world.app.post(
        "/settings/cap", {"csrf": world.csrf(), "cap_usd": ""}, world.cookie, "1.2.3.4"
    )
    assert cleared.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd is None
    assert "none set" in world.page_text()


def test_an_unusable_cap_is_refused_with_the_fixed_phrase(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    for raw in ("abc", "-5", "0", "1.999", "100000"):
        response = world.app.post(
            "/settings/cap",
            {"csrf": world.csrf(), "cap_usd": raw},
            world.cookie,
            "1.2.3.4",
        )
        assert response.status == 400, (raw, response.status)
        assert "at most two decimal places" in response.body.decode()
        assert world.app.store.load("42") is None


# ---- delete everything -----------------------------------------------


def test_delete_requires_the_typed_confirmation(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    wrong = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "delete"},
        world.cookie,
        "1.2.3.4",
    )
    assert wrong.status == 400
    assert DELETE_MISMATCH in wrong.body.decode()
    assert world.app.store.load("42") is not None
    gone = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "DELETE"},
        world.cookie,
        "1.2.3.4",
    )
    assert gone.status == 303
    assert world.app.store.load("42") is None
    # The session cookie is cleared.
    assert gone.set_cookie is not None
    assert gone.set_cookie.startswith("atlas_settings_session=;")
    assert "Max-Age=0" in gone.set_cookie
    # The signed-in session row is destroyed with the delete, not just
    # its cookie: the value it signed is dead in the table too.
    assert world.app.sessions.get(world.cookie) is None


def test_a_non_ascii_confirmation_is_a_mismatch_not_a_crash(
    tmp_path: Path,
) -> None:
    """A confirm value `compare_digest` would refuse as a `str` is
    compared as bytes and answered as the mismatch it is."""
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    response = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "DËLETE"},
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 400
    assert DELETE_MISMATCH in response.body.decode()
    # The installation was not deleted.
    assert world.app.store.load("42") is not None


def test_the_delete_audit_gap_still_ends_the_session(tmp_path: Path) -> None:
    """The delete lands and the audit line cannot be written: the answer
    is the audit-gap 500, and the session still ends with the delete it
    caused — no authenticated session outlives the record it deleted
    (kills the keep-the-session mutant, which left the admin signed in
    over a deleted installation)."""
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )

    class UnwritableAudit(AuditLog):
        def record(
            self,
            action: str,
            installation_id: str,
            github_user_id: int,
            at: datetime | None = None,
        ) -> None:
            raise OSError("the audit file is unwritable")

    world.app.audit = UnwritableAudit(
        world.state_dir / AUDIT_FILE_NAME, world.clock.now
    )
    response = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "DELETE"},
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 500
    assert "was applied but could not be recorded" in response.body.decode()
    assert world.app.store.load("42") is None
    assert world.app.sessions.get(world.cookie) is None
    # The cookie is cleared with the session, on the audit-gap path too.
    assert response.set_cookie is not None
    assert response.set_cookie.startswith("atlas_settings_session=;")
    assert "Max-Age=0" in response.set_cookie


# ---- rate limits -----------------------------------------------------


def test_writes_are_rate_limited_per_session(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    fields = {"csrf": world.csrf(), "cap_usd": ""}
    for _ in range(30):
        world.app.post("/settings/cap", fields, world.cookie, "1.2.3.4")
    response = world.app.post("/settings/cap", fields, world.cookie, "1.2.3.4")
    assert response.status == 429
    assert "too many requests" in response.body.decode()


# ---- the fake key and tokens never appear ---------------------------


def test_the_fake_key_and_tokens_appear_nowhere_across_every_flow(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    surfaces: list[str] = []
    started = world.app.get("/login", "", "", "1.2.3.4")
    surfaces.append(_surface(started))
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    callback = world.app.get(
        "/callback", f"code=fake-code&state={state}", cookie, "1.2.3.4"
    )
    surfaces.append(_surface(callback))
    world.cookie = world.cookie_from(callback)
    csrf = world.csrf()
    consent = world.app.post(
        "/settings/consent",
        {"csrf": csrf, "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    surfaces.append(_surface(consent))
    saved = world.app.post(
        "/settings/credentials",
        _credentials_form(world),
        world.cookie,
        "1.2.3.4",
    )
    surfaces.append(_surface(saved))
    capped = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    surfaces.append(_surface(capped))
    revoked = world.app.post(
        "/settings/revoke", {"csrf": csrf}, world.cookie, "1.2.3.4"
    )
    surfaces.append(_surface(revoked))
    surfaces.append(world.page_text())
    deleted = world.app.post(
        "/settings/delete",
        {"csrf": csrf, "confirm": "DELETE"},
        world.cookie,
        "1.2.3.4",
    )
    surfaces.append(_surface(deleted))
    # The error pages and the login page itself.
    surfaces.append(_surface(world.app.get("/", "", "", "1.2.3.4")))
    world.github.exchange_status = 403
    started2 = world.app.get("/login", "", "", "5.6.7.8")
    surfaces.append(_surface(started2))
    surfaces.append(
        _surface(
            world.app.get(
                "/callback",
                f"code=x&state={world.state_from(started2)}",
                world.cookie_from(started2),
                "5.6.7.8",
            )
        )
    )
    # The log lines are a swept surface too, and the leg is live: one
    # flow runs through the real `serve()` with the sink wired, so a
    # secret that reached a request log would fail here — an
    # always-empty log list would not.
    server = serve(world.app, "127.0.0.1", 0, lambda line: world.logs.append(line))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        surfaces.append(_socket_surface(server, "/", None))
        surfaces.append(_socket_surface(server, "/settings", world.cookie))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert world.logs, "the socket flow reached the handler's log sink"
    surfaces.extend(world.logs)
    audit_path = world.state_dir / "settings-audit.jsonl"
    if audit_path.exists():
        surfaces.append(audit_path.read_text())
    joined = "\n".join(part for part in surfaces if part)
    assert FAKE_KEY not in joined
    assert FAKE_USER_TOKEN not in joined
    assert FAKE_INSTALL_TOKEN not in joined


def _surface(response: object) -> str:
    from atlas_settings.app import Response

    assert isinstance(response, Response)
    parts = [response.body.decode("utf-8", errors="replace")]
    if response.location is not None:
        parts.append(response.location)
    if response.set_cookie is not None:
        parts.append(response.set_cookie)
    return "\n".join(parts)


def _socket_surface(server: Any, path: str, cookie: str | None) -> str:
    """One GET over the real socket, its body and headers as a surface —
    the serve()-routed leg of the redaction sweep."""
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    headers = {"Cookie": f"atlas_settings_session={cookie}"} if cookie else {}
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    body = response.read().decode("utf-8", errors="replace")
    set_cookie = response.getheader("Set-Cookie") or ""
    location = response.getheader("Location") or ""
    connection.close()
    return "\n".join(part for part in (body, set_cookie, location) if part)
