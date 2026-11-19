# SPDX-License-Identifier: MIT
"""The two write paths whose store can fail *between* the load and the
write: a store that reads but cannot write (the disk filled, the
directory went read-only) refuses the credentials save and the other
writes with the store's reason, and the gate's own GitHub read failing
mid-write refuses with the check-failed phrase."""

from pathlib import Path

from atlas_reviewer.installation_store import (
    InstallationRecord,
    InstallationStoreError,
)
from atlas_settings.phrases import GITHUB_CHECK_FAILED

from .harness import (
    FAKE_KEY,
    GOOD_ENDPOINT,
    GOOD_MODEL,
    build_world,
    sign_in,
)


class StoreBrokenOnWrite:
    """A store that reads fine and fails every write — the shape a full
    disk or a read-only directory produces."""

    configured = True
    broken_reason = ""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def load(self, installation: str) -> InstallationRecord | None:
        return self._inner.load(installation)  # type: ignore[attr-defined]

    def store_credentials(
        self, installation: str, base_url: str, key: str, model: str
    ) -> InstallationRecord:
        raise InstallationStoreError("the installation record could not be written")

    def revoke_credentials(self, installation: str) -> InstallationRecord:
        raise InstallationStoreError("the installation record could not be written")

    def set_cap(self, installation: str, cap_usd: object) -> InstallationRecord:
        raise InstallationStoreError("the installation record could not be written")

    def record_consent(
        self, installation: str, at: object = None
    ) -> InstallationRecord:
        raise InstallationStoreError("the installation record could not be written")

    def delete(self, installation: str) -> None:
        raise InstallationStoreError("the installation record could not be deleted")


def test_a_store_that_cannot_write_refuses_the_credentials_save(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    csrf = world.csrf()
    world.app.store = StoreBrokenOnWrite(world.app.store)  # type: ignore[assignment]
    for path, fields in (
        (
            "/settings/credentials",
            {
                "base_url": GOOD_ENDPOINT,
                "key": FAKE_KEY,
                "model": GOOD_MODEL,
            },
        ),
        ("/settings/revoke", {}),
        ("/settings/cap", {"cap_usd": "5"}),
        ("/settings/consent", {"acknowledge": "1"}),
        ("/settings/delete", {"confirm": "DELETE"}),
    ):
        response = world.app.post(
            path, {"csrf": csrf, **fields}, world.cookie, "1.2.3.4"
        )
        assert response.status == 503, (path, response.status)
        assert "could not be" in response.body.decode()


def test_the_gate_read_failing_mid_write_refuses_fail_closed(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    # The coverage read alone fails: the admin check passes, and the
    # gate's own fail-closed path is what answers.
    world.github.repos_error = TimeoutError("timed out")
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 502
    assert GITHUB_CHECK_FAILED in response.body.decode()
    assert world.app.store.load("42") is None
