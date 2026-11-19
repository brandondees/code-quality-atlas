# SPDX-License-Identifier: MIT
"""The settings page's server-side sessions and their signed cookie
(D90): the cookie carries only a random session id plus an HMAC-SHA256
signature under the operator's `ATLAS_SETTINGS_SESSION_KEY`; every other
session fact — identity, CSRF token, the pre-login OAuth bindings —
lives server-side in this process and never leaves it.

The cookie is `HttpOnly`, `Secure`, and `SameSite=Strict`. Sessions are
short-lived: a pre-login session (holding the OAuth state and PKCE
verifier) lives minutes; a signed-in session is refreshed on use up to a
fixed absolute lifetime, after which every request is answered as
signed-out — a read redirects to the sign-in page and a write is
refused, so an expired session can change nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

COOKIE_NAME = "atlas_settings_session"
PRE_LOGIN_TTL_S = 600
SESSION_TTL_S = 1800
ABSOLUTE_TTL_S = 43200
_ID_BYTES = 32


class SessionError(RuntimeError):
    """The session could not be established or is no longer valid."""


@dataclass
class Session:
    sid: str
    created: datetime
    last_used: datetime
    csrf: str
    # Pre-login OAuth bindings, present until the callback consumes them.
    state: str | None = None
    verifier: str | None = None
    # Signed-in identity, present from the callback on.
    user_id: int | None = None
    login: str | None = None

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
        ttl_s: int = SESSION_TTL_S,
        pre_login_ttl_s: int = PRE_LOGIN_TTL_S,
        absolute_ttl_s: int = ABSOLUTE_TTL_S,
    ) -> None:
        if not signing_key:
            raise SessionError("the session signing key must not be empty")
        self._key = signing_key.encode("utf-8")
        self._now = now
        self._ttl = timedelta(seconds=ttl_s)
        self._pre_login_ttl = timedelta(seconds=pre_login_ttl_s)
        self._absolute = timedelta(seconds=absolute_ttl_s)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def start_login(self, state: str, verifier: str) -> tuple[Session, str]:
        """A pre-login session holding fresh OAuth bindings — the random
        state and the PKCE verifier, both stored server-side only — and
        its signed cookie value. The bindings are consumed by exactly one
        callback: a second callback presenting the same state finds the
        session already upgraded and is refused."""
        with self._lock:
            session = Session(
                sid=self._new_id(),
                created=self._now(),
                last_used=self._now(),
                csrf=secrets.token_urlsafe(_ID_BYTES),
                state=state,
                verifier=verifier,
            )
            self._sessions[session.sid] = session
        return session, self.cookie_value(session)

    def upgrade(
        self, session: Session, user_id: int, login: str
    ) -> tuple[Session, str]:
        """The signed-in session replacing a consumed pre-login one: a
        new id (session fixation never carries the login across), a new
        CSRF token, the OAuth bindings dropped, the identity kept."""
        with self._lock:
            self._sessions.pop(session.sid, None)
            signed_in = Session(
                sid=self._new_id(),
                created=self._now(),
                last_used=self._now(),
                csrf=secrets.token_urlsafe(_ID_BYTES),
                user_id=user_id,
                login=login,
            )
            self._sessions[signed_in.sid] = signed_in
        return signed_in, self.cookie_value(signed_in)

    def get(self, cookie_value: str) -> Session | None:
        """The live session a cookie value names, or None. The signature
        is verified first, so a forged or truncated cookie is None; an
        expired session is removed on sight and answers None. The TTL is
        idle time since the last use (sliding), capped by the absolute
        lifetime since creation — a session kept alive by use still dies
        at the absolute cap."""
        sid = _parse_cookie(cookie_value)
        if sid is None or not _mac_ok(self._key, cookie_value, sid):
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return None
            now = self._now()
            idle = now - session.last_used
            age = now - session.created
            ttl = self._pre_login_ttl if not session.signed_in else self._ttl
            if idle >= ttl or age >= self._absolute:
                self._sessions.pop(sid, None)
                return None
            session.last_used = now
            return session

    def destroy(self, session: Session) -> None:
        with self._lock:
            self._sessions.pop(session.sid, None)

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
        "SameSite=Strict; Max-Age=43200"
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
