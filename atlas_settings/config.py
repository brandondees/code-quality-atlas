# SPDX-License-Identifier: MIT
"""The settings page's configuration, read from the environment.

Four variables are new to this page — `ATLAS_SETTINGS_GITHUB_CLIENT_ID`,
`ATLAS_SETTINGS_GITHUB_CLIENT_SECRET`, `ATLAS_SETTINGS_SESSION_KEY`, and
`ATLAS_SETTINGS_BASE_URL` — and the page refuses to start when any of
them is missing, naming every missing variable at once. The App
credentials the page's GitHub reads need (`ATLAS_GITHUB_APP_ID`,
`ATLAS_GITHUB_APP_PRIVATE_KEY`, `ATLAS_GITHUB_INSTALLATION_ID`) and the
store's key (`ATLAS_INSTALLATION_STORE_KEY`) are the service's
variables: they exist in the service's environment shape, and none of
them is set in any deployment yet — the page shares that environment
and refuses to start without them, because a page that cannot verify
the visitor or write the store must not start at all. The store key
must also be a valid Fernet key: a malformed one would start a page
that then refuses every write, the late failure this gate exists to
prevent. The allowlist (`ATLAS_REVIEW_REPOS`) is the service variable
the page parses exactly the way the service parses it, default
included; it is not a startup gate — the invite-only gate judges the
installation's coverage, not the variable's presence. The README's
operator section, added with this stack's final layer, documents each
variable's purpose, required-or-optional status, and default; nothing
here is set in any deployment yet.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from atlas_reviewer.installation_store import ENV_STORE_KEY
from atlas_settings.phrases import CAP_REFUSED

ENV_CLIENT_ID = "ATLAS_SETTINGS_GITHUB_CLIENT_ID"
ENV_CLIENT_SECRET = "ATLAS_SETTINGS_GITHUB_CLIENT_SECRET"
ENV_SESSION_KEY = "ATLAS_SETTINGS_SESSION_KEY"
ENV_BASE_URL = "ATLAS_SETTINGS_BASE_URL"
ENV_APP_ID = "ATLAS_GITHUB_APP_ID"  # == atlas_reviewer.cli.ENV_APP_ID; pinned by test
ENV_APP_KEY = (
    "ATLAS_GITHUB_APP_PRIVATE_KEY"  # == atlas_reviewer.cli.ENV_APP_KEY; pinned by test
)
ENV_INSTALLATION = "ATLAS_GITHUB_INSTALLATION_ID"  # == atlas_reviewer.cli.ENV_INSTALLATION_ID; pinned by test
ENV_STATE_DIR = (
    "ATLAS_REVIEWER_STATE_DIR"  # == atlas_reviewer.cli.ENV_STATE_DIR; pinned by test
)
ENV_REPOS = "ATLAS_REVIEW_REPOS"
DEFAULT_REPO = "brandondees/code-quality-atlas"
DEFAULT_STATE_DIR = ".atlas-reviewer-state"

# The daily cap's sane upper bound (D90): an installation admin can set
# any positive dollar amount with at most two decimal places up to this,
# and nothing above it. S9's stricter-wins combination and the operator
# max remain the outer bounds on what the cap ever releases.
MAX_CAP_USD = Decimal(10000)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_ASCII_DIGITS = re.compile(r"[0-9]+")
_MAX_ID_DIGITS = 64
_MIN_SESSION_KEY_CHARS = 32
# The cap literal's shape: at most 7 integer digits (a length prefilter
# only — `MAX_CAP_USD` is the actual limit) and at most 2 cent places.
_CAP_RE = re.compile(r"\A[0-9]{1,7}(\.[0-9]{1,2})?\Z")


class CapRejectedError(ValueError):
    """The submitted daily cap is not a positive dollar amount within
    the bounds; the fixed phrase is the whole message."""


class SettingsConfigError(RuntimeError):
    """The page's configuration is unusable and the process must not
    start: the message names every missing or unusable variable and
    never carries a secret value."""


@dataclass(frozen=True)
class SettingsConfig:
    """The page's configuration. Its `repr` and `str` redact the three
    secret fields the way part A's credential types redact the key: a
    logged config, a failed assertion, or an f-string can never carry
    the client secret, the session key, or the App private key."""

    client_id: str
    client_secret: str
    session_key: str
    base_url: str
    state_dir: Path
    installation_id: str
    app_id: str
    app_private_key: str
    allowlist: frozenset[str]

    def __repr__(self) -> str:
        return (
            "SettingsConfig("
            f"client_id={self.client_id!r}, "
            "client_secret=<redacted>, "
            "session_key=<redacted>, "
            f"base_url={self.base_url!r}, "
            f"state_dir={self.state_dir!r}, "
            f"installation_id={self.installation_id!r}, "
            f"app_id={self.app_id!r}, "
            "app_private_key=<redacted>, "
            f"allowlist={sorted(self.allowlist)})"
        )


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
            ENV_STORE_KEY,
        )
        if not environ.get(name, "").strip()
    ]
    if missing:
        raise SettingsConfigError(
            "the settings page refuses to start; these environment "
            "variables must be set: " + ", ".join(missing)
        )
    store_key = environ[ENV_STORE_KEY].strip()
    try:
        Fernet(store_key.encode("ascii"))
    except (ValueError, InvalidToken, UnicodeEncodeError, TypeError):
        raise SettingsConfigError(
            f"{ENV_STORE_KEY} must be a valid Fernet key"
        ) from None
    base_url = environ[ENV_BASE_URL].strip()
    _check_base_url(base_url)
    installation = environ[ENV_INSTALLATION].strip()
    # ASCII digits only, the store's own id rule's shape (`str.isdigit`
    # accepts Unicode digits, and a non-ASCII id is both unusable as a
    # store file name and a crash in `int` for some inputs).
    if (
        _ASCII_DIGITS.fullmatch(installation) is None
        or len(installation) > _MAX_ID_DIGITS
        or int(installation) < 1
    ):
        raise SettingsConfigError(
            f"{ENV_INSTALLATION} must be a positive integer of at most "
            f"{_MAX_ID_DIGITS} ASCII digits, the App installation this "
            "deployment reviews for"
        )
    app_id = environ[ENV_APP_ID].strip()
    if (
        _ASCII_DIGITS.fullmatch(app_id) is None
        or len(app_id) > _MAX_ID_DIGITS
        or int(app_id) < 1
    ):
        raise SettingsConfigError(
            f"{ENV_APP_ID} must be the App's numeric id, a positive "
            f"integer of at most {_MAX_ID_DIGITS} ASCII digits"
        )
    session_key = environ[ENV_SESSION_KEY].strip()
    if len(session_key) < _MIN_SESSION_KEY_CHARS:
        raise SettingsConfigError(
            f"{ENV_SESSION_KEY} must be at least {_MIN_SESSION_KEY_CHARS} characters"
        )
    return SettingsConfig(
        client_id=environ[ENV_CLIENT_ID].strip(),
        client_secret=environ[ENV_CLIENT_SECRET].strip(),
        session_key=session_key,
        base_url=base_url,
        state_dir=Path(environ.get(ENV_STATE_DIR, DEFAULT_STATE_DIR)),
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
    """The page's own base URL: https with a host, no userinfo, and no
    control character. Plain http is the local-testing escape, and only
    that — http on `127.0.0.1`, `::1` or `localhost` is accepted for an
    operator testing locally, and every other non-https scheme is
    refused, loopback or not: the deployed page is behind https."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in base_url):
        raise SettingsConfigError(f"{ENV_BASE_URL} must not carry control characters")
    try:
        parts = urlsplit(base_url)
        _ = parts.port  # a non-numeric or out-of-range port raises here too
    except ValueError:
        raise SettingsConfigError(f"{ENV_BASE_URL} is not a valid URL") from None
    if not (
        parts.scheme == "https"
        or (parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS)
    ):
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
        raise CapRejectedError(CAP_REFUSED)
    cap = Decimal(text)
    if cap <= 0 or cap > MAX_CAP_USD:
        raise CapRejectedError(CAP_REFUSED)
    return cap
