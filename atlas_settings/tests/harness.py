# SPDX-License-Identifier: MIT
"""The settings-page tests' harness: the shared fixture vocabulary the
page's tests import — the obviously fake keys, tokens, ids, endpoints,
and the base environment. The vocabulary is declared here whole, at the
bottom layer, because every value is inert data the whole stack's tests
read; the harness's later pieces (the fake GitHub
transport, the resolver, and the world builder) land with their first
user in the layers that need them.

Everything here is obviously fake: no credential is real, no network
call is made, no deployed service setting is touched."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet

from atlas_reviewer.egress import Pinned
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.installation_store import InstallationStore
from atlas_reviewer.tenant_provider import PricingUnknownError
from atlas_settings.app import SettingsApp
from atlas_settings.audit import AUDIT_FILE_NAME, AuditLog
from atlas_settings.config import ENV_APP_ID, settings_config
from atlas_settings.github import GitHubClient
from atlas_settings.ratelimit import RateLimiter
from atlas_settings.sessions import COOKIE_NAME, SessionStore

FAKE_KEY = "sk-fake-key-0123456789abcdef-not-real"
FAKE_USER_TOKEN = "ghu_fakeusertoken_abcdefghij0123456789"
FAKE_INSTALL_TOKEN = "ghs_fakeinstallationtoken_000000000000000"
FAKE_JWT = "fake-app-jwt.not-a-signature"
ALLOWLISTED_REPO = "brandondees/code-quality-atlas"
OTHER_REPO = "someone-else/other-repo"
ADMIN_ID, ADMIN_LOGIN = 11, "octo-admin"
ORG_ACCOUNT_LOGIN = "acme-corp"
GOOD_ENDPOINT = "https://api.example.com/v1"
GOOD_MODEL = "vendor/good-model"
ZERO_MODEL = "vendor/zero-priced-model"
UNKNOWN_MODEL = "vendor/not-in-the-table"

STORE_KEY = Fernet.generate_key().decode("ascii")
SESSION_KEY = "fake-session-signing-key-0123456789abcdef"

START = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)

BASE_ENV: dict[str, str] = {
    "ATLAS_SETTINGS_GITHUB_CLIENT_ID": "Iv1fakeclientid2345678",
    "ATLAS_SETTINGS_GITHUB_CLIENT_SECRET": "fake-client-secret-000000",
    "ATLAS_SETTINGS_SESSION_KEY": SESSION_KEY,
    "ATLAS_SETTINGS_BASE_URL": "https://settings.example.com",
    ENV_APP_ID: "12345",
    "ATLAS_GITHUB_APP_PRIVATE_KEY": "fake-pem-not-a-key",
    "ATLAS_GITHUB_INSTALLATION_ID": "42",
    "ATLAS_INSTALLATION_STORE_KEY": STORE_KEY,
    "ATLAS_REVIEW_REPOS": ALLOWLISTED_REPO,
}


class FakeClock:
    """The wall clock — and its monotonic companion — that the sessions
    and the audit run on, advanced by tests so expiries are
    deterministic."""

    def __init__(self) -> None:
        self.moment = START
        self._mono = 0.0

    def now(self) -> datetime:
        return self.moment

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self.moment = self.moment + timedelta(seconds=seconds)
        self._mono += seconds


@dataclass
class Recorded:
    method: str
    url: str
    body: bytes | None


class FakeGitHub:
    """The GitHub boundary's fake: scripted identity, installation,
    membership, repository, and OAuth-exchange answers, every request
    recorded for the tests' assertions. A route can be switched to an
    error mid-session (the admin-rights-lost test does exactly that)."""

    def __init__(self) -> None:
        self.requests: list[Recorded] = []
        self.user = {"id": ADMIN_ID, "login": ADMIN_LOGIN}
        self.account = {"id": ADMIN_ID, "login": ADMIN_LOGIN, "type": "User"}
        self.membership: dict[str, str] | None = {"role": "admin", "state": "active"}
        self.repos: list[str] = [ALLOWLISTED_REPO]
        self.exchange_status = 200
        self.exchange_body: dict[str, Any] = {
            "access_token": FAKE_USER_TOKEN,
            "token_type": "bearer",
        }
        self.exchange_error: Exception | None = None
        self.api_error: Exception | None = None
        self.mint_status = 201
        self.user_status = 200
        self.user_raw: bytes | None = None
        self.repos_payload: dict[str, Any] | None = None
        self.membership_status = 200
        self.api_error_fires = 1
        self.repos_error: Exception | None = None

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_s: float,
        max_bytes: int | None = None,
    ) -> HttpResponse:
        del headers, timeout_s, max_bytes
        self.requests.append(Recorded(method, url, body))
        if self.exchange_error is not None and "access_token" in url:
            exc, self.exchange_error = self.exchange_error, None
            raise exc
        if self.api_error is not None and "access_token" not in url:
            self.api_error_fires -= 1
            if self.api_error_fires <= 0:
                exc, self.api_error = self.api_error, None
                raise exc
        parts = urlsplit(url)
        path = parts.path
        if path == "/login/oauth/access_token":
            return _json(self.exchange_status, self.exchange_body)
        if path == "/user":
            if self.user_raw is not None:
                return HttpResponse(self.user_status, {}, self.user_raw)
            return _json(self.user_status, self.user)
        if path == "/app/installations/42":
            return _json(200, {"account": self.account})
        if path == "/app/installations/42/access_tokens":
            return _json(
                self.mint_status,
                {
                    "token": FAKE_INSTALL_TOKEN,
                    "expires_at": (
                        datetime.now(UTC) + timedelta(minutes=10)
                    ).isoformat(),
                    "permissions": {"contents": "read", "members": "read"},
                },
            )
        if path.startswith("/orgs/") and "/memberships/" in path:
            if self.membership is None:
                return _json(404, {"message": "Not Found"})
            return _json(self.membership_status, self.membership)
        if path == "/installation/repositories":
            if self.repos_error is not None:
                exc, self.repos_error = self.repos_error, None
                raise exc
            if self.repos_payload is not None:
                return _json(200, self.repos_payload)
            query = parse_qs(parts.query)
            page = int(query.get("page", ["1"])[0])
            chunk = self.repos[(page - 1) * 100 : page * 100]
            payload = {"repositories": [{"full_name": name} for name in chunk]}
            return _json(200, payload)
        return _json(404, {"message": "Not Found"})


def _json(status: int, payload: Any) -> HttpResponse:
    return HttpResponse(
        status,
        {"Content-Type": "application/json"},
        json.dumps(payload).encode("utf-8"),
    )


@dataclass
class World:
    """One page under test: the app, its fakes, and the captured log."""

    app: SettingsApp
    github: FakeGitHub
    clock: FakeClock
    monotonic: list[float]
    store_key: str
    state_dir: Path
    logs: list[str] = field(default_factory=list)
    cookie: str = ""

    def cookie_from(self, response: Any) -> str:
        cookie = SimpleCookie()
        cookie.load(response.set_cookie or "")
        return cookie[COOKIE_NAME].value

    def state_from(self, response: Any) -> str:
        query = urlsplit(response.location or "").query
        return (parse_qs(query).get("state") or [""])[0]

    def csrf(self) -> str:
        response = self.app.get("/settings", "", self.cookie, "1.2.3.4")
        match = re.search(r'name="csrf" value="([^"]+)"', response.body.decode())
        assert match is not None, "the settings page carries no CSRF token"
        return match.group(1)

    def page_text(self) -> str:
        response = self.app.get("/settings", "", self.cookie, "1.2.3.4")
        return response.body.decode("utf-8", errors="replace")

    def bump_time(self, seconds: float) -> None:
        self.clock.advance(seconds)
        self.monotonic[0] += seconds


def build_world(
    tmp_path: Path,
    *,
    env_extra: dict[str, str] | None = None,
    resolve: Any = "fake",
    validate_model: Any = None,
) -> World:
    """`resolve="fake"` (the default) injects the allow-everything fake
    resolver; `resolve=None` runs the real egress guard, which is what
    the hostile-endpoint tests pass so the guard's own refusals are
    what is proven."""
    env = dict(BASE_ENV)
    env["ATLAS_REVIEWER_STATE_DIR"] = str(tmp_path / "state")
    env.update(env_extra or {})
    config = settings_config(env)
    clock = FakeClock()
    github = FakeGitHub()
    monotonic = [0.0]

    def tick() -> float:
        return monotonic[0]

    client = GitHubClient(
        github,
        clock,  # type: ignore[arg-type]
        app_id=config.app_id,
        app_private_key=config.app_private_key,
        installation_id=config.installation_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        encode=lambda claims, key: FAKE_JWT,
    )
    store = InstallationStore.open(config.state_dir, env)
    store.clock = clock.now
    logs: list[str] = []
    return World(
        app=SettingsApp(
            config=config,
            store=store,
            github=client,
            sessions=SessionStore(
                config.session_key,
                clock.now,
                mono=clock.monotonic,
                pre_login_ttl_s=600,
            ),
            limiter=RateLimiter(now=tick),
            audit=AuditLog(config.state_dir / AUDIT_FILE_NAME, clock.now),
            resolve=default_resolve if resolve == "fake" else resolve,
            validate_model_fn=validate_model or _fake_model_table(),
        ),
        github=github,
        clock=clock,
        monotonic=monotonic,
        store_key=STORE_KEY,
        state_dir=config.state_dir,
        logs=logs,
    )


def default_resolve(host: str, port: int) -> Pinned:
    """The tests' default resolver: any host passes, shaped exactly like
    the real guard's answer — so the hostile-endpoint tests that pass
    the *real* resolver are the ones proving refusals."""
    import socket

    return Pinned(socket.AF_INET, (f"93.0.{port % 250}.{port % 250}", port))


def _fake_model_table() -> Any:
    def validate(model: str) -> tuple[Decimal, Decimal]:
        if model == UNKNOWN_MODEL:
            raise PricingUnknownError(
                "the operator's price table has no entry for this model"
            )
        if model == ZERO_MODEL:
            return Decimal(0), Decimal(0)
        return Decimal("3.00"), Decimal("15.00")

    return validate


def sign_in(
    world: World,
    *,
    user_id: int = ADMIN_ID,
    login: str = ADMIN_LOGIN,
    org: bool = False,
    admin: bool = True,
    allowlisted: bool = True,
    account: dict[str, Any] | None = None,
) -> str:
    """The full happy-path sign-in against the fake GitHub, ending with
    the signed-in cookie value. The fake's answers stay configured for
    the test's later writes unless it changes them (the rights-lost
    test does)."""
    if account is not None:
        world.github.account = account
    elif org:
        world.github.account = {
            "id": 5,
            "login": ORG_ACCOUNT_LOGIN,
            "type": "Organization",
        }
    else:
        world.github.account = {"id": user_id, "login": login, "type": "User"}
    world.github.user = {"id": user_id, "login": login}
    world.github.membership = (
        {"role": "admin", "state": "active"}
        if admin or not org
        else {"role": "member", "state": "active"}
    )
    world.github.repos = [ALLOWLISTED_REPO] if allowlisted else [OTHER_REPO]
    started = world.app.get("/login", "", "", "1.2.3.4")
    assert started.status == 302, started
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    path, _, query = f"/callback?code=fake-code&state={state}".partition("?")
    callback = world.app.get(path, query, cookie, "1.2.3.4")
    assert callback.status == 303, callback.body.decode("utf-8", errors="replace")
    signed_in_cookie = world.cookie_from(callback)
    world.cookie = signed_in_cookie
    return signed_in_cookie


def _credentials_form(world, *, endpoint=GOOD_ENDPOINT, key=FAKE_KEY, model=GOOD_MODEL):
    return {
        "csrf": world.csrf(),
        "base_url": endpoint,
        "key": key,
        "model": model,
    }
