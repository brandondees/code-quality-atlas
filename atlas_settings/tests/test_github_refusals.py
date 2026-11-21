# SPDX-License-Identifier: MIT
"""The GitHub boundary's remaining refusal shapes: every non-200 the
reads can answer, every shape the parses refuse, and the encoder's own
failure — each fail-closed, none echoing a body."""

from pathlib import Path

import pytest

from atlas_settings.config import settings_config
from atlas_settings.github import GitHubClient, GitHubRefused, GitHubUser

from .harness import (
    ADMIN_ID,
    ADMIN_LOGIN,
    ALLOWLISTED_REPO,
    BASE_ENV,
    FAKE_JWT,
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


def test_an_account_that_is_not_an_object_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.account = "not-an-object"
    with pytest.raises(GitHubRefused, match="account"):
        client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_membership_read_that_is_not_200_or_404_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.account = {"id": 5, "login": "acme-corp", "type": "Organization"}
    fake.membership_status = 500
    with pytest.raises(GitHubRefused, match="did not answer"):
        client.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_repositories_payload_without_a_list_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.repos_payload = {"repositories": "no"}
    with pytest.raises(GitHubRefused, match="repositories"):
        client.installation_repositories()


def test_a_malformed_repository_entry_is_skipped_not_fatal(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.repos_payload = {
        "repositories": ["just-a-string", {"full_name": ALLOWLISTED_REPO}]
    }
    assert client.installation_repositories() == (ALLOWLISTED_REPO,)


def test_a_failed_jwt_encoding_refuses_without_the_key(tmp_path: Path) -> None:
    client, _fake = _client(tmp_path)

    def broken_encode(claims: object, key: str) -> str:
        raise ValueError("bad key")

    client.encode = broken_encode  # type: ignore[method-assign]
    with pytest.raises(GitHubRefused, match="identity"):
        client.installation_account()
    # The key is in no message.
    try:
        client.installation_account()
    except GitHubRefused as exc:
        assert "fake-pem" not in str(exc)


def test_a_non_200_identity_read_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.user_status = 500
    with pytest.raises(GitHubRefused, match="did not answer"):
        client.get_user("a-token")


def test_a_non_json_identity_read_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.user_raw = b"<html>not json</html>"
    with pytest.raises(GitHubRefused, match="did not answer"):
        client.get_user("a-token")


def test_a_non_object_identity_read_refuses(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    fake.user_raw = b"[1, 2, 3]"
    with pytest.raises(GitHubRefused, match="did not answer"):
        client.get_user("a-token")
