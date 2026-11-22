# SPDX-License-Identifier: MIT
"""The settings page's GitHub boundary: the App's user-authorization web
flow, the identity and admin checks, and the coverage (allowlist-gate)
read — every GitHub HTTP call the page makes, behind one transport seam
the tests fake.

The web flow (D90): `authorize_url` names the App's client id, the
page's redirect URI, a random `state`, and a PKCE `code_challenge`
(S256) — GitHub has supported PKCE for the App user-authorization flow
since its 2025-07-14 changelog, and only S256 is accepted, so the
verifier is bound to the pre-login session beside the state and sent
only to the server-side exchange. The exchanged user token identifies
the user with exactly one read (`GET /user`) and is then discarded: it
is never stored, never logged, never kept in the session, and never
carried in an error message.

Every check fails closed. Any HTTP error, timeout, non-JSON body, or
unexpected shape raises `GitHubRefused` with a fixed phrase — the
visitor is refused, never waved through, and no response body is ever
embedded in an error (a GitHub error body is untrusted input, and the
token-exchange body carries the user token itself).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets as random_secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeGuard

from atlas_reviewer.github_auth import (
    AppInstallationTokens,
    MintError,
    normalize_pem_key,
    rs256,
)
from atlas_reviewer.http import HttpResponse, Transport
from atlas_reviewer.ports import BoundaryError, Clock

GITHUB_WEB_URL = "https://github.com"
GITHUB_API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "code-quality-atlas-settings"
# The org-admin check is the one call that needs a permission beyond the
# review path's own reads: Organization "Members: read". If the App does
# not have it, the mint fails and the check refuses — the operator setup
# step is recorded as **not done** (D90, the README), and nothing works
# around the missing permission.
MEMBERS_PERMISSION: Mapping[str, str] = {"members": "read"}
# Listing the installation's repositories needs metadata read only —
# `contents` is the permission that reads files, commits and releases,
# and the coverage read reads no file.
REPO_LIST_PERMISSION: Mapping[str, str] = {"metadata": "read"}
# The coverage read's pagination bound: 10 pages of 100 repositories. An
# installation with more that never matched the allowlist is refused
# fail-closed — the gate is never satisfied by running out of pages.
_REPO_PAGES = 10
_REPO_PAGE = 100

# PKCE (RFC 7636), S256 only (GitHub's documented shape).
_VERIFIER_BYTES = 32
_STATE_BYTES = 32


class GitHubRefused(BoundaryError):
    """A GitHub read or exchange failed and the visitor is refused: the
    message is fixed text naming what could not be established, and
    never carries a response body, a token, or the code."""


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str


@dataclass(frozen=True)
class InstallationAccount:
    id: int
    login: str
    type: str


@dataclass(frozen=True)
class LoginChallenge:
    """The pre-login session's OAuth bindings: the random state and the
    PKCE verifier, both stored server-side only."""

    state: str
    verifier: str


def new_login_challenge() -> LoginChallenge:
    return LoginChallenge(
        state=random_secrets.token_urlsafe(_STATE_BYTES),
        verifier=random_secrets.token_urlsafe(_VERIFIER_BYTES),
    )


def code_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier: BASE64URL(SHA256(verifier)),
    padding stripped, per RFC 7636 section 4.2."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class JwtEncoder(Protocol):
    def __call__(self, claims: Mapping[str, Any], key: str) -> str: ...


@dataclass
class GitHubClient:
    """The page's GitHub reads. One client per process; the installation
    token sources mint and cache under their own locks, and the
    re-verification on every write re-runs the API checks even when the
    token is cached — the token being fresh never stands in for the
    check being fresh."""

    transport: Transport
    clock: Clock
    app_id: str
    app_private_key: str
    installation_id: str
    client_id: str
    client_secret: str
    api_url: str = GITHUB_API_URL
    web_url: str = GITHUB_WEB_URL
    encode: JwtEncoder = field(default=rs256)

    def authorize_url(self, challenge: LoginChallenge, redirect_uri: str) -> str:
        """The App's user-authorization URL: the client id, the page's
        redirect URI, the session-bound state, and the PKCE S256
        challenge. No scope parameter — GitHub Apps take no OAuth scope,
        and the parameter does not control a user access token's
        permissions."""
        query = "&".join(
            f"{name}={_urlquote(value)}"
            for name, value in (
                ("client_id", self._client_id()),
                ("redirect_uri", redirect_uri),
                ("state", challenge.state),
                (
                    "code_challenge",
                    code_challenge(challenge.verifier),
                ),
                ("code_challenge_method", "S256"),
            )
        )
        return f"{self.web_url}/login/oauth/authorize?{query}"

    def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> GitHubUser:
        """The code exchanged server-side for a user access token, the
        token used for exactly one identity read, and then dropped: the
        returned user is all that survives this method."""
        token = self._exchange(code, verifier, redirect_uri)
        try:
            user = self.get_user(token)
        finally:
            del token
        return user

    def _exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        body = {
            "client_id": self._client_id(),
            "client_secret": self._secret(),
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        resp = self._post(f"{self.web_url}/login/oauth/access_token", body)
        if resp.status != 200:
            raise GitHubRefused("GitHub sign-in did not complete; try again")
        data = _json_body(resp.body, "GitHub sign-in did not complete")
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise GitHubRefused("GitHub sign-in did not complete; try again")
        return token

    def get_user(self, token: str) -> GitHubUser:
        data = self._api("GET", "/user", token=token)
        ident, login = data.get("id"), data.get("login")
        if not _valid_id(ident) or not isinstance(login, str) or not login:
            raise GitHubRefused("GitHub sign-in did not identify the user")
        return GitHubUser(ident, login)

    def installation_account(self) -> InstallationAccount:
        """The installation's account, read with the App's own JWT (any
        App may read its installations): the id and type decide which
        admin rule applies — the user account's owner is the user whose
        id matches, and an organization's admins are its `admin`
        members."""
        jwt_token = self._app_jwt()
        data = self._api(
            "GET", f"/app/installations/{self.installation_id}", token=jwt_token
        )
        del jwt_token
        account = data.get("account")
        if not isinstance(account, dict):
            raise GitHubRefused("the installation's account could not be established")
        ident, login, kind = (
            account.get("id"),
            account.get("login"),
            account.get("type"),
        )
        if (
            not _valid_id(ident)
            or not isinstance(login, str)
            or not login
            or kind not in ("User", "Organization")
        ):
            raise GitHubRefused("the installation's account could not be established")
        return InstallationAccount(ident, login, kind)

    def admin_status(self, user: GitHubUser) -> tuple[bool, InstallationAccount]:
        """The issue's admin rule, fail closed: for a user-account
        installation the signed-in user's id equals the installation
        account's id; for an organization the user's membership in that
        org is `admin` and `active`, checked with the App's installation
        token minted for Organization "Members: read". Any API error,
        timeout, or unexpected shape refuses. The installation's account
        comes back beside the verdict, for the page's own display."""
        account = self.installation_account()
        if account.type == "User":
            return user.id == account.id, account
        token = self._mint(MEMBERS_PERMISSION)
        try:
            status, data = self._api_status(
                "GET",
                f"/orgs/{_urlpath(account.login)}/memberships/{_urlpath(user.login)}",
                token=token,
            )
        finally:
            del token
        # 404 is GitHub's definitive "not a member": a negative answer,
        # not a failure — the admin verdict is False, fail-closed in the
        # same direction. Any other non-200 stays the named refusal.
        if status == 404:
            return False, account
        if status != 200:
            raise GitHubRefused(
                "GitHub did not answer this check as it must; the request is refused"
            )
        role, state = data.get("role"), data.get("state")
        return role == "admin" and state == "active", account

    def installation_repositories(self) -> tuple[str, ...]:
        """The full names of the repositories the installation covers,
        read with the App's installation token. A read failure is the
        named refusal it is — the gate can only be established, never
        assumed."""
        token = self._mint(REPO_LIST_PERMISSION)
        try:
            names: list[str] = []
            for page in range(1, _REPO_PAGES + 1):
                data = self._api(
                    "GET",
                    f"/installation/repositories?per_page={_REPO_PAGE}&page={page}",
                    token=token,
                )
                repos = data.get("repositories")
                if not isinstance(repos, list):
                    raise GitHubRefused(
                        "the installation's repositories could not be listed"
                    )
                for repo in repos:
                    name = repo.get("full_name") if isinstance(repo, dict) else None
                    if isinstance(name, str) and name:
                        names.append(name)
                if len(repos) < _REPO_PAGE:
                    return tuple(names)
            return tuple(names)
        finally:
            del token

    def _mint(self, permissions: Mapping[str, str]) -> str:
        source = AppInstallationTokens(
            self.transport,
            self.clock,
            app_id=self.app_id,
            private_key=self.app_private_key,
            installation_id=int(self.installation_id),
            permissions=dict(permissions),
            api_url=self.api_url,
            encode=self.encode,
        )
        try:
            return source.token()
        except (MintError, BoundaryError) as exc:
            raise GitHubRefused(
                "the GitHub authorization needed for this check could not "
                "be established (the App may be missing the permission it "
                "requires)"
            ) from exc

    def _app_jwt(self) -> str:
        now = int(self.clock.now().timestamp())
        claims = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        try:
            return self.encode(claims, normalize_pem_key(self.app_private_key))
        except Exception as exc:  # noqa: BLE001 -- key errors must not echo the key
            raise GitHubRefused(
                f"the App's identity could not be established ({type(exc).__name__})"
            ) from None

    def _client_id(self) -> str:
        return self.client_id

    def _secret(self) -> str:
        return self.client_secret

    def _post(self, url: str, form: dict[str, str]) -> HttpResponse:
        encoded = "&".join(
            f"{name}={_urlquote(value)}" for name, value in form.items()
        ).encode("ascii")
        try:
            return self.transport.request(
                "POST",
                url,
                {
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": USER_AGENT,
                },
                encoded,
                30.0,
            )
        except (BoundaryError, OSError, TimeoutError, ValueError) as exc:
            raise GitHubRefused("GitHub sign-in did not complete; try again") from exc

    def _api(
        self,
        method: str,
        path: str,
        token: str,
    ) -> dict[str, Any]:
        status, data = self._api_status(method, path, token)
        if status != 200:
            raise GitHubRefused(
                "GitHub did not answer this check as it must; the request is refused"
            )
        return data

    def _api_status(
        self,
        method: str,
        path: str,
        token: str,
    ) -> tuple[int, dict[str, Any]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        headers["Authorization"] = f"Bearer {token}"
        try:
            resp = self.transport.request(
                "GET", f"{self.api_url}{path}", headers, None, 30.0
            )
        except (BoundaryError, OSError, TimeoutError, ValueError) as exc:
            raise GitHubRefused(
                "GitHub could not be reached for this check; the request is refused"
            ) from exc
        if resp.status == 404 and path.startswith("/orgs/"):
            # The membership read's definitive negative: answered, and
            # the caller decides.
            return 404, {}
        return resp.status, _json_body(
            resp.body, "GitHub did not answer this check as it must"
        )


def _valid_id(ident: object) -> TypeGuard[int]:
    """The id rule every GitHub identity read applies: a non-bool int
    greater than 0. JSON `true` is not an id (and `True == 1` in Python,
    so accepting it would fail the admin gate open onto user id 1), and
    `0` matches `0` the same way."""
    return isinstance(ident, int) and not isinstance(ident, bool) and ident > 0


def _json_body(raw: bytes, phrase: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise GitHubRefused(phrase) from None
    if not isinstance(data, dict):
        raise GitHubRefused(phrase)
    return data


def _urlquote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _urlpath(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
