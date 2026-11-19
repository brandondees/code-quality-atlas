# SPDX-License-Identifier: MIT
"""The settings page's configuration: the four new variables and the App
credentials it reuses, the refuse-to-start rule, the base URL's shape,
and the daily cap's intake grammar (positive, at most two decimals, the
sane upper bound, empty clears)."""

from decimal import Decimal
from pathlib import Path

import pytest

from atlas_settings.config import (
    MAX_CAP_USD,
    CapRejectedError,
    SettingsConfigError,
    parse_daily_cap,
    settings_config,
)

from .harness import BASE_ENV


def test_config_reads_the_decided_variables(tmp_path: Path) -> None:
    env = dict(BASE_ENV)
    env["ATLAS_REVIEWER_STATE_DIR"] = str(tmp_path / "state")
    config = settings_config(env)
    assert config.client_id == "Iv1fakeclientid2345678"
    assert config.installation_id == "42"
    assert config.allowlist == frozenset({"brandondees/code-quality-atlas"})
    assert config.state_dir == tmp_path / "state"


def test_a_missing_variable_names_every_missing_one_and_refuses_to_start() -> None:
    env = dict(BASE_ENV)
    del env["ATLAS_SETTINGS_GITHUB_CLIENT_ID"]
    env["ATLAS_SETTINGS_SESSION_KEY"] = ""
    with pytest.raises(SettingsConfigError) as excinfo:
        settings_config(env)
    message = str(excinfo.value)
    assert "ATLAS_SETTINGS_GITHUB_CLIENT_ID" in message
    assert "ATLAS_SETTINGS_SESSION_KEY" in message
    assert "ATLAS_SETTINGS_GITHUB_CLIENT_SECRET" not in message


def test_a_non_https_base_url_refuses_unless_it_is_loopback() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = "http://settings.example.com"
    with pytest.raises(SettingsConfigError, match="https://"):
        settings_config(env)
    env["ATLAS_SETTINGS_BASE_URL"] = "http://127.0.0.1:8090"
    assert settings_config(env).base_url == "http://127.0.0.1:8090"


def test_a_non_numeric_installation_or_app_id_refuses() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_GITHUB_INSTALLATION_ID"] = "drop-table"
    with pytest.raises(SettingsConfigError, match="ATLAS_GITHUB_INSTALLATION_ID"):
        settings_config(env)
    env["ATLAS_GITHUB_INSTALLATION_ID"] = "42"
    env["ATLAS_GITHUB_APP_ID"] = "Acme"
    with pytest.raises(SettingsConfigError, match="ATLAS_GITHUB_APP_ID"):
        settings_config(env)


# ---- the daily cap's grammar ---------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["12.5", "12.50", "0.01", "100", "10000", " 12.50 "],
)
def test_acceptable_caps_parse(raw: str) -> None:
    assert parse_daily_cap(raw) == Decimal(raw.strip())


@pytest.mark.parametrize(
    "raw",
    [
        "abc",
        "-5",
        "-0.01",
        "0",
        "0.00",
        "1.999",
        "10,234.00",
        "1e3",
        "NaN",
        "Infinity",
        "10000.01",
        "$5",
    ],
)
def test_unacceptable_caps_refuse_with_the_one_fixed_phrase(raw: str) -> None:
    """Every rejection carries the same fixed phrase — the rejected
    value is never echoed back, whatever it was."""
    with pytest.raises(CapRejectedError) as excinfo:
        parse_daily_cap("not-a-cap")
    phrase = str(excinfo.value)
    with pytest.raises(CapRejectedError) as excinfo:
        parse_daily_cap(raw)
    assert str(excinfo.value) == phrase


def test_the_upper_bound_is_the_decided_one() -> None:
    assert MAX_CAP_USD == Decimal(10000)
    assert parse_daily_cap("10000") == MAX_CAP_USD


def test_an_empty_cap_clears() -> None:
    assert parse_daily_cap("") is None
    assert parse_daily_cap("   ") is None


def test_a_base_url_without_a_host_or_with_userinfo_refuses() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = "https://"
    with pytest.raises(SettingsConfigError, match="must name a host"):
        settings_config(env)
    env["ATLAS_SETTINGS_BASE_URL"] = "https://user:pass@settings.example.com"
    with pytest.raises(SettingsConfigError, match="userinfo"):
        settings_config(env)
