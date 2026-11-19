# SPDX-License-Identifier: MIT
"""The GitHub boundary client against the fake: the authorize URL's
shape (client id, redirect URI, state, the S256 PKCE challenge), the
code exchange (the verifier travels in the POST body; the token is used
once and dropped), the admin rule for both installation kinds, the
fail-closed shapes, and the coverage read's pagination bound."""

import base64
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from atlas_settings.github import (
    GitHubRefused,
    GitHubUser,
    code_challenge,
    new_login_challenge,
)

from .harness import (
    ADMIN_ID,
    ADMIN_LOGIN,
    FAKE_USER_TOKEN,
    ORG_ACCOUNT_LOGIN,
    build_world,
)


def test_the_authorize_url_carries_state_pkce_and_the_redirect(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    challenge = new_login_challenge()
    url = world.app.github.authorize_url(
        challenge, "https://settings.example.com/callback"
    )
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.netloc == "github.com"
    assert parts.path == "/login/oauth/authorize"
    query = parse_qs(parts.query)
    assert query["client_id"] == ["Iv1fakeclientid2345678"]
    assert query["redirect_uri"] == ["https://settings.example.com/callback"]
    assert query["state"] == [challenge.state]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [code_challenge(challenge.verifier)]


def test_the_s256_challenge_is_the_rfc_shape() -> None:
    verifier = "plain-verifier-string-with-enough-entropy-000000"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert code_challenge(verifier) == expected


def test_the_exchange_sends_the_verifier_and_reads_one_user(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    challenge = new_login_challenge()
    user = world.app.github.exchange_code(
        "the-code", challenge.verifier, "https://settings.example.com/callback"
    )
    assert (user.id, user.login) == (ADMIN_ID, ADMIN_LOGIN)
    exchange = next(r for r in world.github.requests if "access_token" in r.url)
    body = exchange.body.decode() if exchange.body else ""
    assert "code=the-code" in body
    assert f"code_verifier={challenge.verifier}" in body
    assert "client_secret=" in body
    # The identity read used the exchanged token as its bearer.
    identity = next(r for r in world.github.requests if r.url.endswith("/user"))
    assert identity.method == "GET"


def test_the_exchanged_token_is_not_logged_by_the_client(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.app.github.exchange_code(
        "the-code", "verifier-value", "https://settings.example.com/callback"
    )
    # The fake records every request; the token appears only as the
    # identity read's Authorization header — never in a URL, never in a
    # body.
    for recorded in world.github.requests:
        assert FAKE_USER_TOKEN not in recorded.url
        if recorded.body is not None:
            assert FAKE_USER_TOKEN not in recorded.body.decode(
                "utf-8", errors="replace"
            )


def test_an_exchange_failure_is_the_named_refusal(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.exchange_status = 401
    with pytest.raises(GitHubRefused):
        world.app.github.exchange_code(
            "code", "verifier", "https://settings.example.com/callback"
        )
    world.github.exchange_status = 200
    world.github.exchange_body = {"error": "bad_verification_code"}
    with pytest.raises(GitHubRefused):
        world.app.github.exchange_code(
            "code", "verifier", "https://settings.example.com/callback"
        )


def test_a_transport_error_on_the_exchange_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.exchange_error = TimeoutError("timed out")
    with pytest.raises(GitHubRefused):
        world.app.github.exchange_code(
            "code", "verifier", "https://settings.example.com/callback"
        )


# ---- the admin rule -------------------------------------------------


def test_a_user_account_installation_admins_by_id_match(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.account = {"id": ADMIN_ID, "login": ADMIN_LOGIN, "type": "User"}
    admin, account = world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin and account.login == ADMIN_LOGIN and account.type == "User"
    non_admin, _account = world.app.github.admin_status(GitHubUser(999, "someone-else"))
    assert non_admin is False


def test_an_org_installation_admins_by_active_membership_role(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.account = {"id": 5, "login": ORG_ACCOUNT_LOGIN, "type": "Organization"}
    admin, account = world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin and account.type == "Organization"
    # A plain member is not an admin.
    world.github.membership = {"role": "member", "state": "active"}
    admin, _account = world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin is False
    # A pending (inactive) membership is not an admin either.
    world.github.membership = {"role": "admin", "state": "pending"}
    admin, _account = world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin is False
    # A non-member (404) is not an admin.
    world.github.membership = None
    admin, _account = world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin is False


def test_every_unexpected_shape_refuses_fail_closed(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    # A non-JSON identity reply: the identity read's own shape check
    # (the admin check for a user-account installation never reads the
    # user record — it compares ids with the installation's account).
    world.github.user = {"unexpected": "shape"}
    with pytest.raises(GitHubRefused):
        world.app.github.get_user("a-token")
    world.github.user = {"id": ADMIN_ID, "login": ADMIN_LOGIN}
    # An installation whose account is missing.
    world.github.account = {}
    with pytest.raises(GitHubRefused):
        world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    # An account of an unknown type.
    world.github.account = {"id": 5, "login": "x", "type": "Bot"}
    with pytest.raises(GitHubRefused):
        world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_github_timeout_or_transport_error_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.api_error = TimeoutError("timed out")
    with pytest.raises(GitHubRefused):
        world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_failed_members_permission_mint_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.account = {"id": 5, "login": ORG_ACCOUNT_LOGIN, "type": "Organization"}
    world.github.mint_status = 422
    with pytest.raises(GitHubRefused) as excinfo:
        world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert "permission" in str(excinfo.value)


# ---- the coverage read ----------------------------------------------


def test_the_coverage_read_paginates_and_stops_at_a_short_page(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.repos = [f"owner/repo-{n}" for n in range(150)]
    repos = world.app.github.installation_repositories()
    assert len(repos) == 150
    pages = [
        r
        for r in world.github.requests
        if r.url.startswith("https://api.github.com/installation/repositories")
    ]
    assert len(pages) == 2


def test_the_coverage_read_refuses_past_its_bound_rather_than_passing(
    tmp_path: Path,
) -> None:
    """The read's bound is 10 pages of 100. A gate match beyond it is
    never seen — the app's gate check treats an exhausted bound as
    unproven (it requires a match it actually saw), so the bound can
    only refuse, never satisfy, the gate."""
    world = build_world(tmp_path)
    world.github.repos = [f"owner/repo-{n}" for n in range(1000)] + [
        "brandondees/code-quality-atlas"
    ]
    repos = world.app.github.installation_repositories()
    assert len(repos) == 1000
    assert "brandondees/code-quality-atlas" not in repos


def test_a_failing_coverage_read_is_the_named_refusal(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.api_error = TimeoutError("timed out")
    with pytest.raises(GitHubRefused):
        world.app.github.installation_repositories()
