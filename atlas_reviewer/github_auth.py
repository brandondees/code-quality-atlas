# SPDX-License-Identifier: MIT
"""Mint short-lived GitHub App installation tokens in the controller.

Flow (https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation):
sign an RS256 JWT with the App private key (`iss` = App ID, lifetime <= 10
minutes), then `POST /app/installations/{id}/access_tokens`. The request
asks for read permissions and, when given, a single repository, so the
token is narrower than whatever the App itself was granted. A response
granting a non-read permission is refused, except a ``write`` on a
permission named in ``writable`` (the service poster passes
``pull_requests`` so it can create one COMMENT review).

Tokens are cached until `REFRESH_MARGIN_S` before their `expires_at`. The
private key and every token stay inside this object: they are exposed only
through `secrets()`, which feeds the redactor, and never appear in an
error message.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import jwt

from atlas_reviewer.http import Transport, safe_url
from atlas_reviewer.ports import BoundaryError, Clock

API_URL = "https://api.github.com"
JWT_BACKDATE_S = 60
JWT_LIFETIME_S = 540
REFRESH_MARGIN_S = 300
READ_PERMISSIONS: Mapping[str, str] = {
    "contents": "read",
    "checks": "read",
    "actions": "read",
    "pull_requests": "read",
}
# Creating a pull-request review requires write. Write on a GitHub App
# permission includes read on that same permission.
POST_PERMISSIONS: Mapping[str, str] = {"pull_requests": "write"}
POST_WRITABLE = frozenset({"pull_requests"})

Encoder = Callable[[Mapping[str, Any], str], str]


def rs256(claims: Mapping[str, Any], key: str) -> str:
    return jwt.encode(dict(claims), key, algorithm="RS256")


@dataclass(frozen=True)
class _Cached:
    token: str
    expires_at: datetime


class AppInstallationTokens:
    """A `TokenSource` for one installation, optionally one repository."""

    def __init__(
        self,
        transport: Transport,
        clock: Clock,
        *,
        app_id: str,
        private_key: str,
        installation_id: int,
        permissions: Mapping[str, str] = READ_PERMISSIONS,
        repositories: Sequence[str] = (),
        writable: frozenset[str] = frozenset(),
        api_url: str = API_URL,
        encode: Encoder = rs256,
        timeout_s: float = 30.0,
    ) -> None:
        if not app_id.isdigit():
            raise ValueError("GitHub App ID must be numeric")
        if installation_id < 1:
            raise ValueError("installation id must be positive")
        if any(
            level != "read" and not (level == "write" and name in writable)
            for name, level in permissions.items()
        ):
            raise ValueError("only read permissions may be requested")
        self._transport, self._clock = transport, clock
        self._app_id, self._key = app_id, private_key
        self._installation_id = installation_id
        self._permissions = dict(permissions)
        self._writable = frozenset(writable)
        self._repositories = tuple(repositories)
        self._api_url = api_url.rstrip("/")
        self._encode, self._timeout_s = encode, timeout_s
        self._cached: _Cached | None = None
        self._minted: list[str] = []
        self._lock = threading.Lock()

    def limit_timeout(self, seconds: float) -> None:
        """The next mint waits at most ``seconds``. The poster's attempt
        deadline is what passes this in, so the mint cannot run past it."""
        self._timeout_s = max(0.0, seconds)

    def token(self) -> str:
        with self._lock:
            if self._cached is None or self._stale(self._cached):
                self._cached = self._mint()
                self._minted.append(self._cached.token)
            return self._cached.token

    def secrets(self) -> tuple[str, ...]:
        with self._lock:
            return (self._key, *self._minted)

    def _stale(self, cached: _Cached) -> bool:
        margin = timedelta(seconds=REFRESH_MARGIN_S)
        return cached.expires_at - self._clock.now() <= margin

    def _jwt(self) -> str:
        now = int(self._clock.now().timestamp())
        claims = {
            "iat": now - JWT_BACKDATE_S,
            "exp": now + JWT_LIFETIME_S,
            "iss": self._app_id,
        }
        try:
            return self._encode(claims, self._key)
        except Exception as exc:  # noqa: BLE001 -- key errors must not echo the key
            raise BoundaryError(
                f"could not sign the GitHub App JWT ({type(exc).__name__})"
            ) from None

    def _mint(self) -> _Cached:
        url = f"{self._api_url}/app/installations/{self._installation_id}/access_tokens"
        body: dict[str, Any] = {"permissions": self._permissions}
        if self._repositories:
            body["repositories"] = list(self._repositories)
        resp = self._transport.request(
            "POST",
            url,
            {
                "Authorization": f"Bearer {self._jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "code-quality-atlas-reviewer",
                "Content-Type": "application/json",
            },
            json.dumps(body).encode(),
            self._timeout_s,
        )
        if resp.status != 201:
            raise BoundaryError(
                f"GitHub App token mint: HTTP {resp.status} for {safe_url(url)}"
            )
        return self._parse(resp.body)

    def _parse(self, raw: bytes) -> _Cached:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BoundaryError("GitHub App token mint returned non-JSON") from None
        if not isinstance(data, dict):
            raise BoundaryError("GitHub App token mint returned a non-object")
        token, expires = data.get("token"), data.get("expires_at")
        if not isinstance(token, str) or not token or not isinstance(expires, str):
            raise BoundaryError("GitHub App token mint lacks token or expires_at")
        granted = data.get("permissions")
        _require_read_only(granted, self._writable)
        missing = sorted(
            name
            for name, level in self._permissions.items()
            if level == "write"
            and (not isinstance(granted, dict) or granted.get(name) != "write")
        )
        if missing:
            raise BoundaryError(
                f"minted token did not grant {', '.join(missing)}=write"
            )
        return _Cached(token, _expiry(expires, self._clock.now()))


def _require_read_only(granted: object, writable: frozenset[str] = frozenset()) -> None:
    if not isinstance(granted, dict):
        raise BoundaryError("GitHub App token mint did not report its permissions")
    accepted = {
        name for name, level in granted.items() if level == "write" and name in writable
    }
    extra = sorted(
        name
        for name, level in granted.items()
        if level != "read" and name not in accepted
    )
    if extra:
        raise BoundaryError(f"minted token is not read-only: {', '.join(extra)}")


def _expiry(raw: str, now: datetime) -> datetime:
    try:
        expires = datetime.fromisoformat(raw)
    except ValueError:
        raise BoundaryError("GitHub App token expires_at is not ISO 8601") from None
    if expires.tzinfo is None or expires <= now:
        raise BoundaryError("GitHub App token expires_at is naive or already past")
    return expires
