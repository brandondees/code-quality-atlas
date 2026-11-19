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

from atlas_settings.config import settings_config
from atlas_settings.github import (
    GitHubClient,
    GitHubRefused,
    GitHubUser,
    code_challenge,
    new_login_challenge,
)

from .harness import (
    ADMIN_ID,
    ADMIN_LOGIN,
    BASE_ENV,
    FAKE_JWT,
    FAKE_USER_TOKEN,
    ORG_ACCOUNT_LOGIN,
    FakeClock,
    FakeGitHub,
)


def _client(tmp_path: Path) -> tuple[GitHubClient, FakeGitHub]:
    """The GitHub boundary under test, constructed directly: this layer
    runs before the settings application exists, so the client is built
    by hand against the same fakes the app's own harness assembles."""
    env = dict(BASE_ENV)
    env["ATLAS_REVIEWER_STATE_DIR"] = str(tmp_path / "state")
    config = settings_config(env)
    fake = FakeGitHub()
    return (
        GitHubClient(
            fake,
            FakeClock(),  # type: ignore[arg-type]
            app_id=config.app_id,
            app_private_key=config.app_private_key,
            installation_id=config.installation_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            encode=lambda claims, key: FAKE_JWT,
        ),
        fake,
    )


def test_the_authorize_url_carries_state_pkce_and_the_redirect(tmp_path: Path) -> None:
    client, _fake = _client(tmp_path)
    challenge = new_login_challenge()
    url = client.authorize_url(challenge, "https://settings.example.com/callback")
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
    client, fake = _client(tmp_path)
    challenge = new_login_challenge()
    user = client.exchange_code(
        "the-code", challenge.verifier, "https://settings.example.com/callback"
    )
    assert (user.id, user.login) == (ADMIN_ID, ADMIN_LOGIN)
    exchange = next(r for r in fake.requests if "access_token" in r.url)
    body = exchange.body.decode() if exchange.body else ""
    assert "code=the-code" in body
    assert f"code_verifier={challenge.verifier}" in body
    assert "client_secret=" in body
    # The identity read used the exchanged token as its bearer.
    identity = next(r for r in fake.requests if r.url.endswith("/user"))
    assert identity.method == "GET"


def test_the_exchanged_token_is_not_logged_by_the_client(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    client.exchange_code(
        "the-code", "verifier-value", "https://settings.example.com/callback"
    )
    # The fake records every request; the token appears only as the
    # identity read's Authorization header — never in a URL, never in a
    # body.
    for recorded in fake.requests:
        assert FAKE_USER_TOKEN not in recorded.url
        if recorded.body is not None:
            assert FAKE_USER_TOKEN not in recorded.body.decode(
                "utf-8", errors="replace"
            )


def test_an_exchange_failure_is_the_named_refusal(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.exchange_status = 401
    with pytest.raises(GitHubRefused):
        client.exchange_code(
            "code", "verifier", "https://settings.example.com/callback"
        )
    fake.exchange_status = 200
    fake.exchange_body = {"error": "bad_verification_code"}
    with pytest.raises(GitHubRefused):
        client.exchange_code(
            "code", "verifier", "https://settings.example.com/callback"
        )


def test_a_transport_error_on_the_exchange_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.exchange_error = TimeoutError("timed out")
    with pytest.raises(GitHubRefused):
        client.exchange_code(
            "code", "verifier", "https://settings.example.com/callback"
        )


# ---- the admin rule -------------------------------------------------


def test_a_user_account_installation_admins_by_id_match(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.account = {"id": ADMIN_ID, "login": ADMIN_LOGIN, "type": "User"}
    admin, account = client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin and account.login == ADMIN_LOGIN and account.type == "User"
    non_admin, _account = client.admin_status(GitHubUser(999, "someone-else"))
    assert non_admin is False


def test_an_org_installation_admins_by_active_membership_role(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.account = {"id": 5, "login": ORG_ACCOUNT_LOGIN, "type": "Organization"}
    admin, account = client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin and account.type == "Organization"
    # A plain member is not an admin.
    fake.membership = {"role": "member", "state": "active"}
    admin, _account = client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin is False
    # A pending (inactive) membership is not an admin either.
    fake.membership = {"role": "admin", "state": "pending"}
    admin, _account = client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin is False
    # A non-member (404) is not an admin.
    fake.membership = None
    admin, _account = client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert admin is False


def test_every_unexpected_shape_refuses_fail_closed(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    # A non-JSON identity reply: the identity read's own shape check
    # (the admin check for a user-account installation never reads the
    # user record — it compares ids with the installation's account).
    fake.user = {"unexpected": "shape"}
    with pytest.raises(GitHubRefused):
        client.get_user("a-token")
    fake.user = {"id": ADMIN_ID, "login": ADMIN_LOGIN}
    # An installation whose account is missing.
    fake.account = {}
    with pytest.raises(GitHubRefused):
        client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    # An account of an unknown type.
    fake.account = {"id": 5, "login": "x", "type": "Bot"}
    with pytest.raises(GitHubRefused):
        client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_github_timeout_or_transport_error_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.api_error = TimeoutError("timed out")
    with pytest.raises(GitHubRefused):
        client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_failed_members_permission_mint_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.account = {"id": 5, "login": ORG_ACCOUNT_LOGIN, "type": "Organization"}
    fake.mint_status = 422
    with pytest.raises(GitHubRefused) as excinfo:
        client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    assert "permission" in str(excinfo.value)


# ---- the coverage read ----------------------------------------------


def test_the_coverage_read_paginates_and_stops_at_a_short_page(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.repos = [f"owner/repo-{n}" for n in range(150)]
    repos = client.installation_repositories()
    assert len(repos) == 150
    pages = [
        r
        for r in fake.requests
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
    client, fake = _client(tmp_path)
    fake.repos = [f"owner/repo-{n}" for n in range(1000)] + [
        "brandondees/code-quality-atlas"
    ]
    repos = client.installation_repositories()
    assert len(repos) == 1000
    assert "brandondees/code-quality-atlas" not in repos


def test_a_failing_coverage_read_is_the_named_refusal(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.api_error = TimeoutError("timed out")
    with pytest.raises(GitHubRefused):
        client.installation_repositories()


# ---- the fix-round pins (r1 review of #788) -------------------------


@pytest.mark.parametrize(
    "bad_id",
    [True, 0, -1],
)
def test_a_boolean_zero_or_negative_account_id_refuses(
    bad_id: object, tmp_path: Path
) -> None:
    client, fake = _client(tmp_path)
    """A GitHub account id must be a non-bool int greater than 0: JSON
    `true` is not an id (and `True == 1`, so accepting it would fail the
    admin gate open onto user id 1), and `0` matches `0` the same way —
    both are refused instead (kills the isinstance-int mutant)."""
    fake.account = {"id": bad_id, "login": "octo-admin", "type": "User"}
    with pytest.raises(GitHubRefused, match="account"):
        client.admin_status(GitHubUser(1, "mojombo"))


@pytest.mark.parametrize(
    "bad_id",
    [True, 0, -1],
)
def test_a_boolean_zero_or_negative_user_id_refuses(
    bad_id: object, tmp_path: Path
) -> None:
    client, fake = _client(tmp_path)
    """The identity read applies the same rule (kills the isinstance-int
    mutant in get_user)."""
    fake.user = {"id": bad_id, "login": "octo-admin"}
    with pytest.raises(GitHubRefused, match="identify"):
        client.get_user("a-token")


def test_the_admin_rule_is_the_id_not_the_login(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    """Id matching is pinned apart from login matching: the same login
    with a different id is not the admin, and the same id with a
    different login is (kills the login-comparison mutant)."""
    fake.account = {"id": ADMIN_ID, "login": ADMIN_LOGIN, "type": "User"}
    same_login_other_id, _ = client.admin_status(GitHubUser(ADMIN_ID + 1, ADMIN_LOGIN))
    assert same_login_other_id is False
    same_id_other_login, _ = client.admin_status(GitHubUser(ADMIN_ID, "someone-else"))
    assert same_id_other_login is True


def _mint_bodies(fake: FakeGitHub) -> list[dict[str, object]]:
    import json as json_module

    bodies = []
    for recorded in fake.requests:
        if recorded.url.endswith("/access_tokens") and recorded.body:
            bodies.append(json_module.loads(recorded.body.decode()))
    return bodies


def test_the_mint_bodies_are_exactly_the_narrow_permissions(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    """The coverage read mints `metadata: read` — the permission that
    lists repositories, not the one that reads files — and the org-admin
    check mints exactly `members: read` (kills the mutant that requests
    contents)."""
    fake.account = {"id": 5, "login": ORG_ACCOUNT_LOGIN, "type": "Organization"}
    client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))
    client.installation_repositories()
    bodies = _mint_bodies(fake)
    assert {"permissions": {"members": "read"}} in bodies
    assert {"permissions": {"metadata": "read"}} in bodies
    for body in bodies:
        assert set(body) == {"permissions"}
        assert set(body["permissions"]) == {"members"} or set(body["permissions"]) == {
            "metadata"
        }


def test_the_identity_read_happens_exactly_once(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    """The exchanged token identifies the user with exactly one
    `GET /user` (kills the mutant that reads it twice)."""
    client.exchange_code(
        "the-code", "verifier-value", "https://settings.example.com/callback"
    )
    identity_reads = [r for r in fake.requests if r.url.endswith("/user")]
    assert len(identity_reads) == 1
