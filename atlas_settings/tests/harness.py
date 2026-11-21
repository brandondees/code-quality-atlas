# SPDX-License-Identifier: MIT
"""The settings-page tests' harness: the shared fixture vocabulary the
page's tests import — the obviously fake keys, tokens, ids, endpoints,
and the base environment. The harness's later pieces (the fake clock,
the fake GitHub transport, the resolver, and the world builder) land
with their first user in the layers that need them.

Everything here is obviously fake: no credential is real, no network
call is made, no deployed service setting is touched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet

from atlas_settings.config import ENV_APP_ID

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
