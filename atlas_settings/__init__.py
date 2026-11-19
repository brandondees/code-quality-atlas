# SPDX-License-Identifier: MIT
"""The operator-hosted BYOK settings page (config slice S10, part B1;
issue #768; D90): a GitHub App installation's admin signs in with GitHub
and manages that installation's tenant-supplied model credentials,
consent acknowledgement, and daily cap through part A's store API
(`atlas_reviewer.installation_store`).

The page is a new top-level package outside `atlas_reviewer`, runs as its
own process (`python -m atlas_settings`), and shares the state volume and
part A's store module. Every write goes through the store's API — never
around it — so the per-installation `fcntl.flock` (D89) serializes this
process against the review service's writes.

Nothing here makes a model call, a live GitHub write, or any other
network call beyond the reads the page itself needs: the GitHub
user-authorization web flow, the admin and coverage checks, and the
operator's public price table. Keys and secrets never appear in a
response, a log line, an error, a redirect, or the audit.
"""

from atlas_settings.config import (
    ENV_BASE_URL,
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    ENV_SESSION_KEY,
    SettingsConfigError,
    settings_config,
)

__all__ = [
    "ENV_BASE_URL",
    "ENV_CLIENT_ID",
    "ENV_CLIENT_SECRET",
    "ENV_SESSION_KEY",
    "SettingsConfigError",
    "settings_config",
]
