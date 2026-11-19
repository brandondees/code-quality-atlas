# SPDX-License-Identifier: MIT
"""The session store: the signed cookie's shape and attributes, the
expiry (pre-login and signed-in TTLs, the absolute cap), the HMAC
forgery refusal, the login upgrade's fresh id and CSRF token, and the
destroy."""

from datetime import UTC, datetime, timedelta

import pytest

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
    return SessionStore(SESSION_KEY, clock.now, mono=clock.monotonic, **kwargs)


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


def test_a_pre_login_session_is_never_refreshed_by_a_presentation() -> None:
    """The pre-login session's whole life is one round trip to GitHub
    and back: a repeat presentation inside the TTL does not slide it —
    the second `get`, 599 seconds after the first, is refused (kills the
    mutant that refreshes a pre-login row's clock)."""
    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("state", "verifier")
    clock.advance(599)
    assert store.get(value) is not None
    clock.advance(599)
    assert store.get(value) is None


def test_an_abandoned_sign_in_is_reclaimed_by_the_next_start_login() -> None:
    """A pre-login row whose cookie never comes back is swept by the
    next `start_login` — it does not park state in the process until
    the restart."""
    clock = FakeClock()
    store = _store(clock)
    cookies = [store.start_login("s", "v")[1] for _ in range(256)]
    clock.advance(601)
    # The sweep runs inside the next start_login: no cap refusal.
    _session, _value = store.start_login("s", "v")
    for cookie in cookies:
        assert store.get(cookie) is None


def test_the_pre_login_cap_refuses_past_its_bound() -> None:
    from atlas_settings.sessions import SessionError

    clock = FakeClock()
    store = _store(clock)
    for _ in range(256):
        store.start_login("s", "v")
    with pytest.raises(SessionError, match="too many pending sign-ins"):
        store.start_login("s", "v")


def test_the_session_repr_redacts_the_bindings() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, _value = store.start_login("canary-state-000", "canary-verifier-000")
    text = repr(session) + " " + str(session)
    assert "canary-state-000" not in text
    assert "canary-verifier-000" not in text
    assert session.csrf not in text


@pytest.mark.parametrize("cookie", ["é.abc", "abc.éé"])
def test_a_non_ascii_cookie_is_refused_as_the_forged_thing_it_is(cookie: str) -> None:
    clock = FakeClock()
    store = _store(clock)
    assert store.get(cookie) is None


def test_upgrade_is_single_use_under_overlapping_callbacks() -> None:
    """The upgrade pops the live pre-login row and requires it to be the
    very session handed in: two callbacks that both read the same cookie
    cannot both mint a signed-in session, and re-upgrading a consumed
    session object raises instead of succeeding (kills the mutant that
    ignores the popped row)."""
    from atlas_settings.sessions import SessionError

    clock = FakeClock()
    store = _store(clock)
    session, value = store.start_login("state", "verifier")
    first = store.get(value)
    second = store.get(value)
    assert first is not None and second is not None
    _signed, _signed_value = store.upgrade(first, 11, "octo-admin")
    with pytest.raises(SessionError, match="already consumed"):
        store.upgrade(second, 11, "octo-admin")
    with pytest.raises(SessionError, match="already consumed"):
        store.upgrade(session, 11, "octo-admin")
    assert store.get(value) is None


def test_the_cookie_max_age_is_the_absolute_cap() -> None:
    from atlas_settings.sessions import ABSOLUTE_TTL_S, cookie_header

    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("s", "v")
    assert f"Max-Age={ABSOLUTE_TTL_S}" in cookie_header(value)


def test_expiry_runs_on_the_monotonic_clock_not_the_wall_clock() -> None:
    """A wall-clock step backward cannot extend a session, and the wall
    clock advancing without the monotonic clock cannot expire one: the
    comparisons read the monotonic side."""
    clock = FakeClock()
    store = _store(clock)
    session, _value = store.start_login("state", "verifier")
    _signed, signed_value = store.upgrade(session, 11, "octo-admin")
    # The monotonic clock runs past the TTL while the wall clock stands
    # still: the session expires.
    clock._mono += 3600
    assert store.get(signed_value) is None
    # A fresh session whose wall clock jumped but whose monotonic clock
    # did not: still alive.
    session2, _value2 = store.start_login("s2", "v2")
    _signed2, signed_value2 = store.upgrade(session2, 11, "octo-admin")
    clock.moment = clock.moment + timedelta(seconds=7200)
    assert store.get(signed_value2) is not None


def test_a_signed_in_session_dies_at_exactly_the_absolute_cap() -> None:
    """One second before the absolute cap the session lives; at exactly
    the cap it is gone (kills the `age >= absolute` → `>` mutant)."""
    clock = FakeClock()
    store = _store(clock, ttl_s=300, absolute_ttl_s=180)
    session, _value = store.start_login("s", "v")
    signed, signed_value = store.upgrade(session, 11, "octo-admin")
    clock.advance(179)
    assert store.get(signed_value) is signed
    clock.advance(1)
    assert store.get(signed_value) is None


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
