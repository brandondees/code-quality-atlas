# SPDX-License-Identifier: MIT
"""The settings page's configuration, read from the environment.

Four variables are new to this page — `ATLAS_SETTINGS_GITHUB_CLIENT_ID`,
`ATLAS_SETTINGS_GITHUB_CLIENT_SECRET`, `ATLAS_SETTINGS_SESSION_KEY`, and
`ATLAS_SETTINGS_BASE_URL` — and the page refuses to start when any of
them is missing, naming every missing variable at once. The App
credentials the page's GitHub reads need (`ATLAS_GITHUB_APP_ID`,
`ATLAS_GITHUB_APP_PRIVATE_KEY`, `ATLAS_GITHUB_INSTALLATION_ID`), the
store's key (`ATLAS_INSTALLATION_STORE_KEY`), and the allowlist
(`ATLAS_REVIEW_REPOS`) are part A's variables the deployment already
carries; the page reads them from the same environment and refuses to
start without them too, because a page that cannot verify the visitor or
write the store must not start at all. None of these is set in any
deployment yet; the README's operator section documents each one.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

ENV_CLIENT_ID = "ATLAS_SETTINGS_GITHUB_CLIENT_ID"
ENV_CLIENT_SECRET = "ATLAS_SETTINGS_GITHUB_CLIENT_SECRET"
ENV_SESSION_KEY = "ATLAS_SETTINGS_SESSION_KEY"
ENV_BASE_URL = "ATLAS_SETTINGS_BASE_URL"
ENV_APP_ID = "ATLAS_GITHUB_APP_ID"
ENV_APP_KEY = "ATLAS_GITHUB_APP_PRIVATE_KEY"
ENV_INSTALLATION = "ATLAS_GITHUB_INSTALLATION_ID"
ENV_STATE_DIR = "ATLAS_REVIEWER_STATE_DIR"
ENV_REPOS = "ATLAS_REVIEW_REPOS"
DEFAULT_REPO = "brandondees/code-quality-atlas"
DEFAULT_STATE_DIR = ".atlas-reviewer-state"

# The daily cap's sane upper bound (D90): an installation admin can set
# any positive dollar amount with at most two decimal places up to this,
# and nothing above it. S9's stricter-wins combination and the operator
# max remain the outer bounds on what the cap ever releases.
MAX_CAP_USD = Decimal(10000)
MAX_CAP_TEXT = "10000"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class SettingsConfigError(RuntimeError):
    """The page's configuration is unusable and the process must not
    start: the message names every missing or unusable variable and
    never carries a secret value."""


@dataclass(frozen=True)
class SettingsConfig:
    client_id: str
    client_secret: str
    session_key: str
    base_url: str
    state_dir: Path
    installation_id: str
    app_id: str
    app_private_key: str
    allowlist: frozenset[str]


def settings_config(env: Mapping[str, str] | None = None) -> SettingsConfig:
    """The page's configuration from the environment, refusing to start
    with every missing variable named at once."""
    environ = os.environ if env is None else env
    missing = [
        name
        for name in (
            ENV_CLIENT_ID,
            ENV_CLIENT_SECRET,
            ENV_SESSION_KEY,
            ENV_BASE_URL,
            ENV_APP_ID,
            ENV_APP_KEY,
            ENV_INSTALLATION,
        )
        if not environ.get(name, "").strip()
    ]
    if missing:
        raise SettingsConfigError(
            "the settings page refuses to start; these environment "
            "variables must be set: " + ", ".join(missing)
        )
    base_url = environ[ENV_BASE_URL].strip()
    _check_base_url(base_url)
    installation = environ[ENV_INSTALLATION].strip()
    if not installation.isdigit() or int(installation) < 1:
        raise SettingsConfigError(
            f"{ENV_INSTALLATION} must be a positive integer, the App "
            "installation this deployment reviews for"
        )
    app_id = environ[ENV_APP_ID].strip()
    if not app_id.isdigit():
        raise SettingsConfigError(f"{ENV_APP_ID} must be the App's numeric id")
    return SettingsConfig(
        client_id=environ[ENV_CLIENT_ID].strip(),
        client_secret=environ[ENV_CLIENT_SECRET].strip(),
        session_key=environ[ENV_SESSION_KEY].strip(),
        base_url=base_url,
        state_dir=Path(environ.get(ENV_STATE_DIR, "") or DEFAULT_STATE_DIR),
        installation_id=installation,
        app_id=app_id,
        app_private_key=environ[ENV_APP_KEY],
        allowlist=_allowlist(environ),
    )


def _allowlist(environ: Mapping[str, str]) -> frozenset[str]:
    """The invite-only gate's allowlist, parsed exactly the way
    `service.py` parses `ATLAS_REVIEW_REPOS`."""
    repos = environ.get(ENV_REPOS, DEFAULT_REPO)
    return frozenset(part.strip() for part in repos.split(",") if part.strip())


def _check_base_url(base_url: str) -> None:
    """The page's own base URL: https, a host, no userinfo. Plain http is
    accepted only for a loopback host, the shape an operator tests on
    locally — the deployed page is behind https and never accepts
    anything else."""
    parts = urlsplit(base_url)
    if parts.scheme != "https" and (parts.hostname or "") not in _LOOPBACK_HOSTS:
        raise SettingsConfigError(
            f"{ENV_BASE_URL} must be an https:// URL (a loopback http:// "
            "URL is accepted for local testing only)"
        )
    if not parts.hostname:
        raise SettingsConfigError(f"{ENV_BASE_URL} must name a host")
    if parts.username is not None or parts.password is not None:
        raise SettingsConfigError(f"{ENV_BASE_URL} must not carry userinfo")


def parse_daily_cap(raw: str) -> Decimal | None:
    """The submitted daily cap as the store takes it, or None when the
    admin cleared it. A positive decimal dollar amount with at most two
    decimal places and at most the sane upper bound is accepted;
    anything else is refused with the fixed phrase — never the raw
    value. The grammar is a plain decimal literal: no exponent, no
    sign, no thousands separator, so the shape an admin types is the
    shape the store stores."""
    text = raw.strip()
    if text == "":
        return None
    if _CAP_RE.fullmatch(text) is None:
        raise CapRejectedError(_CAP_PHRASE)
    cap = Decimal(text)
    if cap <= 0 or cap > MAX_CAP_USD:
        raise CapRejectedError(_CAP_PHRASE)
    return cap


class CapRejectedError(ValueError):
    """The submitted daily cap is not a positive dollar amount within
    the bounds; the fixed phrase is the whole message."""


_CAP_RE = re.compile(r"\A\d{1,7}(\.\d{1,2})?\Z")


_CAP_PHRASE = (
    "the daily cap must be a dollar amount between $0.01 and $"
    f"{MAX_CAP_TEXT} with at most two decimal places, or empty to clear "
    "it (no cap set means none applies; the per-repo daily budget and "
    "the operator's max per review remain the outer bounds either way)"
)
