# SPDX-License-Identifier: MIT
"""The settings page's server-side sessions and their signed cookie
(D90): the cookie carries only a random session id plus an HMAC-SHA256
signature under the operator's `ATLAS_SETTINGS_SESSION_KEY`; every other
session fact — identity, CSRF token, the pre-login OAuth bindings —
lives server-side in this process and never leaves it.

The cookie is `HttpOnly`, `Secure`, and `SameSite=Strict`. Sessions are
short-lived: a pre-login session (holding the OAuth state and PKCE
verifier) lives 10 minutes from creation and is never refreshed — its
whole life is one round trip to GitHub and back; a signed-in session is
refreshed on use up to a fixed absolute lifetime, after which every
request is answered as signed-out — a read redirects to the sign-in
page and a write is refused, so an expired session can change nothing.
Expiry is measured on a monotonic clock (a wall-clock step backward
cannot extend a session). Both tables are bounded, and a full table
never locks the page out: `start_login` at the pre-login cap first
sweeps the expired rows and then, if the cap still holds, evicts the
oldest pre-login row and admits the new sign-in — one caller cannot
hold every new sign-in shut by keeping 256 rows alive; `upgrade` at the
signed-in cap evicts the least-recently-used signed-in row the same
way. The walks run only on those rare paths, so the common insert is
constant work.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

COOKIE_NAME = "atlas_settings_session"
PRE_LOGIN_TTL_S = 600
SESSION_TTL_S = 1800
ABSOLUTE_TTL_S = 43200
_ID_BYTES = 32
# The tables' bounds: an unauthenticated surface must not be able to
# park unbounded state in the process, and neither may a signed-in
# crowd. A full table never refuses: the expired rows are swept first
# and the oldest live row is evicted after that, so one caller cannot
# hold the page's sign-in (or its signed-in capacity) shut.
_MAX_PRE_LOGIN_SESSIONS = 256
_MAX_SIGNED_IN_SESSIONS = 4096


class SessionError(RuntimeError):
    """The session could not be established or is no longer valid."""


@dataclass
class Session:
    sid: str
    created: datetime
    last_used: datetime
    csrf: str = field(repr=False)
    # Pre-login OAuth bindings, present until the callback consumes
    # them; repr-hidden with the CSRF token, whose values stay in this
    # process and must never ride a log line, an error, or an f-string.
    state: str | None = field(default=None, repr=False)
    verifier: str | None = field(default=None, repr=False)
    # Signed-in identity, present from the callback on.
    user_id: int | None = None
    login: str | None = None
    # The monotonic timestamps the expiry comparisons run on, beside the
    # wall-clock record above; 0.0 only for a hand-built session.
    created_mono: float = 0.0
    last_used_mono: float = 0.0

    @property
    def signed_in(self) -> bool:
        return self.user_id is not None and self.login is not None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    """The process-local session table behind the signed cookie.

    One process runs the page, so a lock-guarded dict is the whole
    store; a restart signs everyone out, which a short-TTL session
    accepts by construction."""

    def __init__(
        self,
        signing_key: str,
        now: Callable[[], datetime] = _utc_now,
        *,
        mono: Callable[[], float] = time.monotonic,
        ttl_s: int = SESSION_TTL_S,
        pre_login_ttl_s: int = PRE_LOGIN_TTL_S,
        absolute_ttl_s: int = ABSOLUTE_TTL_S,
    ) -> None:
        if not signing_key:
            raise SessionError("the session signing key must not be empty")
        self._key = signing_key.encode("utf-8")
        self._now = now
        self._mono = mono
        self._ttl_s = ttl_s
        self._pre_login_ttl_s = pre_login_ttl_s
        self._absolute_s = absolute_ttl_s
        self._sessions: dict[str, Session] = {}
        self._pre_login_count = 0
        self._signed_in_count = 0
        self._lock = threading.Lock()

    def start_login(self, state: str, verifier: str) -> tuple[Session, str]:
        """A pre-login session holding fresh OAuth bindings — the random
        state and the PKCE verifier, both stored server-side only — and
        its signed cookie value. The bindings are consumed by exactly one
        callback: a second callback presenting the same state finds the
        session already upgraded and is refused."""
        with self._lock:
            if self._pre_login_count >= _MAX_PRE_LOGIN_SESSIONS:
                # The rare path: the cap is reached, so the walk runs —
                # the expired rows go first, and if live rows still fill
                # the table the oldest is evicted. A new sign-in is never
                # refused because someone else filled the table.
                self._sweep()
            if self._pre_login_count >= _MAX_PRE_LOGIN_SESSIONS:
                oldest = min(
                    (s for s in self._sessions.values() if not s.signed_in),
                    key=lambda s: s.created_mono,
                    default=None,
                )
                if oldest is not None:
                    del self._sessions[oldest.sid]
                    self._pre_login_count -= 1
            now, mono_now = self._now(), self._mono()
            session = Session(
                sid=self._new_id(),
                created=now,
                last_used=now,
                csrf=secrets.token_urlsafe(_ID_BYTES),
                state=state,
                verifier=verifier,
                created_mono=mono_now,
                last_used_mono=mono_now,
            )
            self._sessions[session.sid] = session
            self._pre_login_count += 1
        return session, self.cookie_value(session)

    def _sweep(self) -> None:
        """Drop the expired rows under the caller's lock. The walk runs
        on the rare over-cap paths only (start_login at the pre-login
        cap), so an abandoned sign-in — a dead tab, an attack — is
        reclaimed when the table next fills, not by every insert and not
        only by its own cookie's return; below the cap an expired row
        leaves on its cookie's next presentation or the next sweep."""
        mono_now = self._mono()
        for sid, session in list(self._sessions.items()):
            age = mono_now - session.created_mono
            idle = mono_now - session.last_used_mono
            expired = (
                age >= self._pre_login_ttl_s
                if not session.signed_in
                else (idle >= self._ttl_s or age >= self._absolute_s)
            )
            if expired:
                del self._sessions[sid]
                if session.signed_in:
                    self._signed_in_count -= 1
                else:
                    self._pre_login_count -= 1

    def upgrade(
        self, session: Session, user_id: int, login: str
    ) -> tuple[Session, str]:
        """The signed-in session replacing a consumed pre-login one: a
        new id (session fixation never carries the login across), a new
        CSRF token, the OAuth bindings dropped, the identity kept."""
        with self._lock:
            # Single-use under overlapping callbacks, checked BEFORE any
            # mutation: the live row must be this very pre-login session.
            # A refused call — an already-upgraded or half-upgraded
            # object — changes nothing: the table and both counters are
            # untouched, so a refused upgrade can never destroy a live
            # signed-in session or drift a counter that later feeds an
            # eviction's min().
            current = self._sessions.get(session.sid)
            if current is not session or session.signed_in:
                raise SessionError("the sign-in session is already consumed")
            del self._sessions[session.sid]
            # The consumed pre-login row's slot moves to the signed-in
            # table with it.
            self._pre_login_count -= 1
            if self._signed_in_count >= _MAX_SIGNED_IN_SESSIONS:
                least_recent = min(
                    (s for s in self._sessions.values() if s.signed_in),
                    key=lambda s: s.last_used_mono,
                    default=None,
                )
                if least_recent is not None:
                    del self._sessions[least_recent.sid]
                    self._signed_in_count -= 1
            now, mono_now = self._now(), self._mono()
            signed_in = Session(
                sid=self._new_id(),
                created=now,
                last_used=now,
                csrf=secrets.token_urlsafe(_ID_BYTES),
                user_id=user_id,
                login=login,
                created_mono=mono_now,
                last_used_mono=mono_now,
            )
            self._sessions[signed_in.sid] = signed_in
            self._signed_in_count += 1
        return signed_in, self.cookie_value(signed_in)

    def get(self, cookie_value: str) -> Session | None:
        """The live session a cookie value names, or None. The signature
        is verified first, so a forged or truncated cookie is None; an
        expired session is removed on sight and answers None. A
        signed-in session's TTL is idle time since the last use
        (sliding), capped by the absolute lifetime since creation — a
        session kept alive by use still dies at the absolute cap. A
        pre-login session expires 10 minutes after it was created and is
        never refreshed."""
        # `http.server` decodes headers as latin-1, so a client can send
        # a non-ASCII cookie; it is refused as the forged thing it is,
        # never encoded or compared.
        if not cookie_value.isascii():
            return None
        sid = _parse_cookie(cookie_value)
        if sid is None or not _mac_ok(self._key, cookie_value, sid):
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return None
            now, mono_now = self._now(), self._mono()
            age = mono_now - session.created_mono
            # A pre-login session's whole life is one round trip to
            # GitHub and back: it expires 10 minutes after it was
            # created and is never refreshed by a repeat presentation.
            if not session.signed_in:
                if age >= self._pre_login_ttl_s:
                    del self._sessions[sid]
                    self._pre_login_count -= 1
                    return None
                return session
            idle = mono_now - session.last_used_mono
            if idle >= self._ttl_s or age >= self._absolute_s:
                del self._sessions[sid]
                self._signed_in_count -= 1
                return None
            session.last_used = now
            session.last_used_mono = mono_now
            return session

    def destroy(self, session: Session) -> None:
        with self._lock:
            if self._sessions.pop(session.sid, None) is not None:
                if session.signed_in:
                    self._signed_in_count -= 1
                else:
                    self._pre_login_count -= 1

    def cookie_value(self, session: Session) -> str:
        """The signed cookie value for one session:
        `<sid>.<hex hmac(sid)>`. The signature is verified before any
        lookup, so a forged or truncated id is an expired session, not a
        crash."""
        mac = hmac.new(
            self._key, session.sid.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return f"{session.sid}.{mac}"

    def _new_id(self) -> str:
        return secrets.token_urlsafe(_ID_BYTES)


def cookie_header(value: str) -> str:
    """The `Set-Cookie` header's value: the signed id with the decided
    attributes. `Secure` is set unconditionally — the deployed page is
    https; a loopback test reads the cookie by hand."""
    return (
        f"{COOKIE_NAME}={value}; Path=/; HttpOnly; Secure; "
        f"SameSite=Strict; Max-Age={ABSOLUTE_TTL_S}"
    )


def cleared_cookie_header() -> str:
    """The header that ends a session on the browser side."""
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"


def _parse_cookie(value: str) -> str | None:
    sid, separator, mac = value.partition(".")
    if not separator or not sid or not mac:
        return None
    return sid


def _mac_ok(key: bytes, cookie_value: str, sid: str) -> bool:
    expected = hmac.new(key, sid.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(cookie_value.rpartition(".")[2], expected)
