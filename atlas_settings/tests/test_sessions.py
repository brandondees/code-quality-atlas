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
    SessionError,
    SessionStore,
    cleared_cookie_header,
    cookie_header,
)

from .harness import ADMIN_ID, ADMIN_LOGIN, SESSION_KEY, FakeClock

OTHER_KEY = "a-different-signing-key-0123456789"


def _store(clock: FakeClock, **kwargs: int) -> SessionStore:
    return SessionStore(SESSION_KEY, clock.now, mono=clock.monotonic, **kwargs)


def test_an_expired_pre_login_row_cannot_be_upgraded() -> None:
    """The pre-login binding's 10-minute lifetime is enforced on the
    upgrade path too, at the same boundary `get()` uses: a caller
    holding a `Session` object one second inside the lifetime can still
    upgrade it, at exactly the lifetime it is refused, and past it the
    refusal stands with nothing changed (kills the `>=`-to-`>`
    mutant — the 601-only probe survived it — and the
    drop-the-TTL-check mutant, which minted a signed-in session from a
    binding that had expired)."""
    clock = FakeClock()
    store = _store(clock, pre_login_ttl_s=600)
    session, _value = store.start_login("state-abc", "verifier-abc")
    clock.advance(599)
    # One second inside the lifetime: the upgrade is allowed.
    _signed, _cookie = store.upgrade(session, ADMIN_ID, ADMIN_LOGIN)
    assert store._signed_in_count == 1
    # A fresh binding created at the same moment, probed at exactly its
    # lifetime (600 seconds later).
    session2, _value2 = store.start_login("state-def", "verifier-def")
    clock.advance(600)
    with pytest.raises(SessionError, match="expired"):
        store.upgrade(session2, ADMIN_ID, ADMIN_LOGIN)
    # The refusal mutated nothing: the refused row is still counted
    # where it was, and no second signed-in session exists.
    assert store._pre_login_count == 1
    assert store._signed_in_count == 1
    # The expired row still expires normally on its own path.
    assert store.get(store.cookie_value(session2)) is None


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


def test_the_pre_login_cookie_is_lax_and_the_session_cookie_strict() -> None:
    """The pre-login binding's cookie is `SameSite=Lax`: its whole life
    is the round trip through GitHub's authorize page, and the redirect
    back is a cross-site top-level GET navigation, which a `Strict`
    cookie is not sent on — in a browser the binding would never reach
    the callback (kills the strict-everywhere mutant). The signed-in
    session's cookie stays `Strict`: its life is same-site."""
    assert "SameSite=Lax" in cookie_header("v", samesite="Lax")
    assert "SameSite=Strict" in cookie_header("v")
    assert "SameSite=Lax" not in cookie_header("v")
    assert "SameSite=Strict" not in cookie_header("v", samesite="Lax")


def test_a_forged_or_truncated_cookie_is_an_expired_session() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, value = store.start_login("state-abc", "verifier-abc")
    assert store.get(value) is session
    sid = value.partition(".")[0]
    assert store.get(sid) is None  # signature dropped
    assert store.get(sid + "." + "0" * 64) is None  # forged signature
    assert store.get("garbage") is None
    # A signature under a different key is a forgery, not a session:
    # the same session id, signed under the other key, must be refused
    # by the real store while its own cookie still answers (kills the
    # ignores-the-key mutant — an unknown-sid store would pass it).
    other = SessionStore(OTHER_KEY, clock.now)
    forged = other.cookie_value(session)
    assert store.get(forged) is None
    assert store.get(value) is session


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


def test_at_the_cap_a_new_sign_in_evicts_the_oldest_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap never locks the page: at the pre-login cap the oldest row
    is evicted and the new sign-in is admitted — one caller cannot hold
    every new sign-in shut by keeping 256 rows alive (kills the
    refuse-at-the-cap mutant)."""
    from atlas_settings import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "_MAX_PRE_LOGIN_SESSIONS", 4)
    clock = FakeClock()
    store = _store(clock)
    first_session, first_cookie = store.start_login("s0", "v0")
    cookies = [store.start_login(f"s{n}", f"v{n}")[1] for n in range(1, 4)]
    # The 5th sign-in succeeds: the oldest row goes, nobody is refused.
    _session, newest_cookie = store.start_login("s4", "v4")
    assert store.get(first_cookie) is None
    assert store.get(newest_cookie) is not None
    assert all(store.get(c) is not None for c in cookies)
    # A sign-in whose row was evicted fails cleanly: its upgrade is the
    # consumed-session refusal, not a crash and not a second login.
    from atlas_settings.sessions import SessionError

    with pytest.raises(SessionError, match="already consumed"):
        store.upgrade(first_session, 11, "octo-admin")


def test_the_signed_in_table_evicts_its_least_recently_used_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas_settings import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "_MAX_SIGNED_IN_SESSIONS", 3)
    clock = FakeClock()
    store = _store(clock)
    signed_cookies = []
    for n in range(3):
        session, _cookie = store.start_login(f"s{n}", f"v{n}")
        _signed, signed_value = store.upgrade(session, 100 + n, f"u{n}")
        signed_cookies.append(signed_value)
    clock.advance(10)
    session4, _cookie = store.start_login("s3", "v3")
    _signed, fourth = store.upgrade(session4, 103, "u3")
    # The least recently used signed-in row (the first) made room.
    assert store.get(signed_cookies[0]) is None
    assert store.get(signed_cookies[1]) is not None
    assert store.get(fourth) is not None


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


def test_the_cookie_max_age_follows_the_absolute_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header's Max-Age is the ABSOLUTE_TTL_S constant, not a
    copy-pasted literal: with the constant patched, the header follows
    it (kills the literal-43200 mutant)."""
    from atlas_settings import sessions as sessions_module
    from atlas_settings.sessions import cookie_header

    monkeypatch.setattr(sessions_module, "ABSOLUTE_TTL_S", 99)
    clock = FakeClock()
    store = _store(clock)
    _session, value = store.start_login("s", "v")
    assert "Max-Age=99" in cookie_header(value)


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


def test_the_sweep_reclaims_an_expired_signed_in_row_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap-triggered sweep drops every kind of expired row: the
    signed-in session whose TTL ran out goes with the abandoned
    sign-ins, and its slot in the signed-in count goes with it."""
    from atlas_settings import sessions as sessions_module
    from atlas_settings.sessions import ABSOLUTE_TTL_S

    monkeypatch.setattr(sessions_module, "_MAX_PRE_LOGIN_SESSIONS", 1)
    clock = FakeClock()
    store = _store(clock)
    session, signed_cookie = store.start_login("s", "v")
    _signed, _value = store.upgrade(session, 11, "octo-admin")
    clock.advance(ABSOLUTE_TTL_S + 1)  # past the signed-in session's cap
    _pre_login_session, pre_login_cookie = store.start_login("s2", "v2")
    clock.advance(601)
    # At the pre-login cap the sweep runs and takes the dead signed-in
    # row with the expired sign-in; the new sign-in is admitted.
    store.start_login("s3", "v3")
    assert store.get(signed_cookie) is None
    assert store.get(pre_login_cookie) is None


def test_destroy_decrements_the_right_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Destroying a signed-in row and destroying a pre-login row each
    release their own slot, so a later start_login and upgrade see the
    true counts."""
    from atlas_settings import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "_MAX_PRE_LOGIN_SESSIONS", 1)
    monkeypatch.setattr(sessions_module, "_MAX_SIGNED_IN_SESSIONS", 1)
    clock = FakeClock()
    store = _store(clock)
    pre_session, pre_cookie = store.start_login("s", "v")
    store.destroy(pre_session)
    signed_session, _cookie = store.start_login("s2", "v2")
    signed, signed_cookie = store.upgrade(signed_session, 11, "octo-admin")
    store.destroy(signed)
    # Both slots are free again: a fresh pre-login sign-in and a fresh
    # upgrade are both admitted without any eviction.
    session3, _c = store.start_login("s3", "v3")
    _signed3, _v = store.upgrade(session3, 12, "u3")
    assert store.get(pre_cookie) is None
    assert store.get(signed_cookie) is None


def test_destroying_an_already_gone_session_is_a_no_op() -> None:
    clock = FakeClock()
    store = _store(clock)
    session, _cookie = store.start_login("s", "v")
    store.destroy(session)
    store.destroy(session)  # already gone: no error, no counter change
    store.destroy(
        type(session)(
            sid="never-existed",
            created=clock.now(),
            last_used=clock.now(),
            csrf="c",
        )
    )
    # The counters still tell the truth: a fresh sign-in is admitted.
    _session2, _value = store.start_login("s2", "v2")


def test_the_sweep_never_leaves_the_counters_lying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counters must track the table exactly: after a sweep has
    emptied it, the next two sign-ins are admitted with no eviction at
    all — the first new sign-in's row survives the second one (kills the
    mutant that forgets the eviction's own counter decrement: its count
    reads higher than the table, and the second sign-in evicts the
    first's live row)."""
    from atlas_settings import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "_MAX_PRE_LOGIN_SESSIONS", 2)
    clock = FakeClock()
    store = _store(clock)
    _first, first_cookie = store.start_login("s1", "v1")
    store.start_login("s2", "v2")
    # The eviction path runs while both rows are live: the third sign-in
    # gives up the oldest.
    _session, third_cookie = store.start_login("s3", "v3")
    assert store.get(first_cookie) is None
    clock.advance(601)
    # The sweep drops the expired rows; the next sign-in is admitted
    # with no eviction and no crash.
    _session, fourth_cookie = store.start_login("s4", "v4")
    assert store.get(third_cookie) is None
    # A second sign-in right after: still no eviction — the first new
    # row survives (the counters read the table, not the history).
    _session, fifth_cookie = store.start_login("s5", "v5")
    assert store.get(fourth_cookie) is not None
    assert store.get(fifth_cookie) is not None


def test_the_signed_in_eviction_is_least_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The signed-in eviction keys on last use, not creation: refreshing
    the oldest session's cookie keeps it and gives up the next one
    (kills the created-order mutant)."""
    from atlas_settings import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "_MAX_SIGNED_IN_SESSIONS", 2)
    clock = FakeClock()
    store = _store(clock)
    s1, _c1 = store.start_login("s1", "v1")
    _signed1, v1 = store.upgrade(s1, 101, "u1")
    s2, _c2 = store.start_login("s2", "v2")
    _signed2, v2 = store.upgrade(s2, 102, "u2")
    clock.advance(5)
    store.get(v1)  # the oldest-created session is the most recently used
    s3, _c3 = store.start_login("s3", "v3")
    _signed3, v3 = store.upgrade(s3, 103, "u3")
    assert store.get(v1) is not None  # refreshed: it stays
    assert store.get(v2) is None  # the least recently used goes
    assert store.get(v3) is not None


def test_a_drifted_counter_is_a_no_op_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a counter ever drifts above the real row count, the eviction's
    min() finds nothing and the drift is a no-op — the sign-in and the
    upgrade are both admitted, nobody is refused, nothing crashes (the
    bot's hardening ask; kills the unguarded-min mutant)."""
    from atlas_settings import sessions as sessions_module

    monkeypatch.setattr(sessions_module, "_MAX_PRE_LOGIN_SESSIONS", 2)
    monkeypatch.setattr(sessions_module, "_MAX_SIGNED_IN_SESSIONS", 2)
    clock = FakeClock()
    store = _store(clock)
    store._pre_login_count = 5  # drifted: no pre-login rows exist
    store._signed_in_count = 5  # drifted: no signed-in rows exist
    session, _cookie = store.start_login("s", "v")
    _signed, signed_value = store.upgrade(session, 11, "octo-admin")
    assert store.get(signed_value) is not None


def test_a_refused_upgrade_of_a_signed_in_session_destroys_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """upgrade() validates before it mutates: handing it an already
    signed-in session raises and leaves everything untouched — the live
    signed-in row still answers get(), both counters are unchanged, and
    a later upgrade under a patched cap of 1 does not crash on an empty
    eviction set (kills the pop-before-validate mutant, whose refused
    call deleted the live row and drifted the count)."""
    from atlas_settings import sessions as sessions_module
    from atlas_settings.sessions import SessionError

    monkeypatch.setattr(sessions_module, "_MAX_SIGNED_IN_SESSIONS", 2)
    clock = FakeClock()
    store = _store(clock)
    pre_session, _pre_cookie = store.start_login("s", "v")
    signed, signed_cookie = store.upgrade(pre_session, 11, "octo-admin")
    assert signed.signed_in
    with pytest.raises(SessionError, match="already consumed"):
        store.upgrade(signed, 12, "someone-else")
    # Nothing moved: the live session still answers, the counters read
    # the table.
    assert store.get(signed_cookie) is signed
    assert store._signed_in_count == 1
    assert store._pre_login_count == 0
    # A later sign-in and upgrade succeed without any drift crash.
    pre2, _c = store.start_login("s2", "v2")
    _signed2, _v2 = store.upgrade(pre2, 12, "someone-else")
    assert store.get(signed_cookie) is signed


def test_a_refused_upgrade_leaves_the_next_one_working_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bot's drift-crash scenario at the tightest cap (1): a refused
    upgrade of the live signed-in session changes nothing, and the next
    legitimate sign-in and upgrade at that same cap succeeds without an
    empty-eviction ValueError (kills the crash mutant whose drifted
    count makes every later upgrade fail)."""
    from atlas_settings import sessions as sessions_module
    from atlas_settings.sessions import SessionError

    monkeypatch.setattr(sessions_module, "_MAX_SIGNED_IN_SESSIONS", 1)
    clock = FakeClock()
    store = _store(clock)
    pre, _pre_cookie = store.start_login("s", "v")
    signed, _signed_cookie = store.upgrade(pre, 11, "octo-admin")
    with pytest.raises(SessionError, match="already consumed"):
        store.upgrade(signed, 12, "someone-else")
    # The refused call left the live session intact and the counters
    # true; the next legitimate upgrade at the same cap succeeds.
    pre2, _c = store.start_login("s2", "v2")
    _signed2, signed_value2 = store.upgrade(pre2, 12, "someone-else")
    assert store.get(signed_value2) is not None
