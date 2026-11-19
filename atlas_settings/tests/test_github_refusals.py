# SPDX-License-Identifier: MIT
"""The GitHub boundary's remaining refusal shapes: every non-200 the
reads can answer, every shape the parses refuse, and the encoder's own
failure — each fail-closed, none echoing a body."""

from pathlib import Path

import pytest

from atlas_settings.github import GitHubRefused, GitHubUser

from .harness import (
    ADMIN_ID,
    ADMIN_LOGIN,
    ALLOWLISTED_REPO,
    build_world,
)


def test_an_account_that_is_not_an_object_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.account = "not-an-object"
    with pytest.raises(GitHubRefused, match="account"):
        world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_membership_read_that_is_not_200_or_404_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.account = {"id": 5, "login": "acme-corp", "type": "Organization"}
    world.github.membership_status = 500
    with pytest.raises(GitHubRefused, match="did not answer"):
        world.app.github.admin_status(GitHubUser(ADMIN_ID, ADMIN_LOGIN))


def test_a_repositories_payload_without_a_list_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.repos_payload = {"repositories": "no"}
    with pytest.raises(GitHubRefused, match="repositories"):
        world.app.github.installation_repositories()


def test_a_malformed_repository_entry_is_skipped_not_fatal(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.repos_payload = {
        "repositories": ["just-a-string", {"full_name": ALLOWLISTED_REPO}]
    }
    assert world.app.github.installation_repositories() == (ALLOWLISTED_REPO,)


def test_a_failed_jwt_encoding_refuses_without_the_key(tmp_path: Path) -> None:
    world = build_world(tmp_path)

    def broken_encode(claims: object, key: str) -> str:
        raise ValueError("bad key")

    world.app.github.encode = broken_encode  # type: ignore[assignment]
    with pytest.raises(GitHubRefused, match="identity"):
        world.app.github.installation_account()
    # The key is in no message.
    try:
        world.app.github.installation_account()
    except GitHubRefused as exc:
        assert "fake-pem" not in str(exc)


def test_a_non_200_identity_read_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.user_status = 500
    with pytest.raises(GitHubRefused, match="did not answer"):
        world.app.github.get_user("a-token")


def test_a_non_json_identity_read_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.user_raw = b"<html>not json</html>"
    with pytest.raises(GitHubRefused, match="did not answer"):
        world.app.github.get_user("a-token")


def test_a_non_object_identity_read_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.user_raw = b"[1, 2, 3]"
    with pytest.raises(GitHubRefused, match="did not answer"):
        world.app.github.get_user("a-token")
