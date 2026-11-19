# SPDX-License-Identifier: MIT
"""The session store: the signed cookie's shape and attributes, the
expiry (pre-login and signed-in TTLs, the absolute cap), the HMAC
forgery refusal, the login upgrade's fresh id and CSRF token, and the
destroy."""

from datetime import UTC, datetime

from atlas_settings.sessions import (
    COOKIE_NAME,
    Session,
    SessionStore,
    cleared_cookie_header,
    cookie_header,
)

from .harness import SESSION_KEY, FakeClock

OTHER_KEY = "a-different-signing-key-0123456789"


def _store(clock: FakeClock, **kwargs: int) -> SessionStore:
    return SessionStore(SESSION_KEY, clock.now, **kwargs)


def test_the_cookie_carries_the_decided_attributes() -> None:
    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("state-abc", "verifier-abc")
    header = cookie_header(value)
    assert f"{COOKIE_NAME}=" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=Strict" in header
    assert "Path=/" in header


def test_a_forged_or_truncated_cookie_is_an_expired_session() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, value = store.start_login("state-abc", "verifier-abc")
    assert store.get(value) is session
    sid = value.partition(".")[0]
    assert store.get(sid) is None  # signature dropped
    assert store.get(sid + "." + "0" * 64) is None  # forged signature
    assert store.get("garbage") is None
    # A signature under a different key is a forgery, not a session.
    other = SessionStore(OTHER_KEY, clock.now)
    assert other.get(value) is None


def test_a_signed_in_session_expires_at_its_idle_ttl() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, _value = store.start_login("state", "verifier")
    signed, signed_value = store.upgrade(session, 11, "octo-admin")
    assert signed.signed_in
    # Untouched, it dies at the TTL.
    clock.advance(1799)
    assert store.get(signed_value) is signed
    clock.advance(1800)
    assert store.get(signed_value) is None


def test_use_refreshes_the_ttl_until_the_absolute_cap() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, _value = store.start_login("state", "verifier")
    signed, signed_value = store.upgrade(session, 11, "octo-admin")
    # Each use inside the TTL window refreshes it, for 12 hours total.
    for _ in range(24):
        clock.advance(1799)
        assert store.get(signed_value) is signed
    clock.advance(1799)
    # Past the absolute lifetime the session is gone however fresh the
    # last touch was.
    assert store.get(signed_value) is None


def test_a_pre_login_session_expires_sooner() -> None:
    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("state", "verifier")
    clock.advance(600)
    assert store.get(value) is None


def test_a_pre_login_session_survives_inside_its_ttl() -> None:
    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("state", "verifier")
    clock.advance(599)
    assert store.get(value) is not None


def test_the_absolute_lifetime_caps_a_refreshed_session() -> None:
    clock = FakeClock()
    store = _store(clock, ttl_s=60, absolute_ttl_s=180)
    session, _value = store.start_login("state", "verifier")
    _signed, signed_value = store.upgrade(session, 11, "octo-admin")
    for _ in range(3):
        clock.advance(50)
        assert store.get(signed_value) is not None
    clock.advance(50)
    # Past the absolute lifetime the session is gone however fresh the
    # last touch was.
    assert store.get(signed_value) is None


def test_the_upgrade_issues_a_fresh_id_and_csrf_and_drops_the_bindings() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, value = store.start_login("state-abc", "verifier-abc")
    assert session.state == "state-abc"
    assert session.verifier == "verifier-abc"
    signed, signed_value = store.upgrade(session, 11, "octo-admin")
    assert signed.sid != session.sid
    assert signed.csrf != session.csrf
    assert signed.state is None
    assert signed.verifier is None
    # The pre-login cookie no longer answers: only the new one does.
    assert store.get(value) is None
    assert store.get(signed_value) is signed


def test_the_state_binding_is_consumed_by_one_callback_only() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, value = store.start_login("state-abc", "verifier-abc")
    assert store.get(value) is session
    store.upgrade(session, 11, "octo-admin")
    # A replayed callback finds no pre-login session: the store answers
    # None for the old cookie.
    assert store.get(value) is None


def test_destroy_ends_the_session() -> None:
    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("s", "v")
    session = store.get(value)
    assert session is not None
    store.destroy(session)
    assert store.get(value) is None


def test_the_cleared_cookie_ends_the_session_in_the_browser() -> None:
    header = cleared_cookie_header()
    assert "Max-Age=0" in header
    assert "HttpOnly" in header and "Secure" in header


def test_an_empty_signing_key_refuses() -> None:
    import pytest

    from atlas_settings.sessions import SessionError

    with pytest.raises(SessionError):
        SessionStore("")


def test_the_session_records_its_times_in_utc() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, _value = store.start_login("s", "v")
    assert session.created.tzinfo is UTC
    assert isinstance(session.created, datetime)
    assert session.csrf


def test_a_session_without_identity_is_not_signed_in() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, _value = store.start_login("s", "v")
    assert not session.signed_in
    assert (
        Session(sid="x", created=clock.now(), last_used=clock.now(), csrf="c").signed_in
        is False
    )


def test_the_default_clock_is_the_real_utc_now() -> None:
    store = SessionStore(SESSION_KEY)
    session, value = store.start_login("s", "v")
    assert store.get(value) is not None
    assert session.created.tzinfo is UTC
    assert store.get("no-such-cookie") is None
