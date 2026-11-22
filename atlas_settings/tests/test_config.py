# SPDX-License-Identifier: MIT
"""The settings page's configuration: the four new variables and the App
credentials it reuses, the refuse-to-start rule, the base URL's shape,
and the daily cap's intake grammar (positive, at most two decimals, the
sane upper bound, empty clears)."""

from decimal import Decimal
from pathlib import Path

import pytest

from atlas_settings import phrases
from atlas_settings.config import (
    ENV_STORE_KEY,
    MAX_CAP_USD,
    CapRejectedError,
    SettingsConfigError,
    parse_daily_cap,
    settings_config,
)
from atlas_settings.phrases import CAP_REFUSED, CONSENT_STATEMENT

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


def test_the_consent_statement_is_the_plan_s_own_sentence() -> None:
    """The phrases module's one externally-decided text, pinned where the
    phrase vocabulary lands: the consent statement is plan §7 decision
    3's sentence, verbatim."""
    assert CONSENT_STATEMENT == (
        "The PR diff is sent to the installation's own endpoint."
    )


# ---- the fix-round pins (r1 review of #779) -------------------------


def test_the_store_key_is_required_at_startup() -> None:
    env = dict(BASE_ENV)
    del env[ENV_STORE_KEY]
    with pytest.raises(SettingsConfigError, match="ATLAS_INSTALLATION_STORE_KEY"):
        settings_config(env)
    env[ENV_STORE_KEY] = "   "
    with pytest.raises(SettingsConfigError, match="ATLAS_INSTALLATION_STORE_KEY"):
        settings_config(env)


def test_the_repr_and_str_redact_the_three_secrets() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_REVIEWER_STATE_DIR"] = "/tmp/unused-state"
    config = settings_config(env)
    text = repr(config) + " " + str(config)
    for secret in (
        BASE_ENV["ATLAS_SETTINGS_GITHUB_CLIENT_SECRET"],
        BASE_ENV["ATLAS_SETTINGS_SESSION_KEY"],
        BASE_ENV["ATLAS_GITHUB_APP_PRIVATE_KEY"],
    ):
        assert secret not in text
    assert "client_secret=<redacted>" in repr(config)
    assert "session_key=<redacted>" in repr(config)
    assert "app_private_key=<redacted>" in repr(config)


def test_a_config_error_never_carries_a_secret_value() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_GITHUB_CLIENT_SECRET"] = "canary-secret-value-000"
    env["ATLAS_SETTINGS_SESSION_KEY"] = ""
    with pytest.raises(SettingsConfigError) as excinfo:
        settings_config(env)
    assert "canary-secret-value-000" not in str(excinfo.value)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1/page",
        "file://localhost/tmp/x",
        "javascript://localhost/alert",
        "ws://127.0.0.1/x",
        "gopher://127.0.0.1",
    ],
)
def test_non_http_schemes_are_refused_even_on_loopback(url: str) -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = url
    with pytest.raises(SettingsConfigError, match="https://"):
        settings_config(env)


@pytest.mark.parametrize(
    "raw",
    ["²", "١٢", "１２"],
)
def test_non_ascii_digits_are_refused_for_the_installation_id(raw: str) -> None:
    env = dict(BASE_ENV)
    env["ATLAS_GITHUB_INSTALLATION_ID"] = raw
    with pytest.raises(SettingsConfigError, match="ATLAS_GITHUB_INSTALLATION_ID"):
        settings_config(env)
    env["ATLAS_GITHUB_INSTALLATION_ID"] = "42"
    env["ATLAS_GITHUB_APP_ID"] = "١٢"
    with pytest.raises(SettingsConfigError, match="ATLAS_GITHUB_APP_ID"):
        settings_config(env)
    env["ATLAS_GITHUB_APP_ID"] = "0"
    with pytest.raises(SettingsConfigError, match="ATLAS_GITHUB_APP_ID"):
        settings_config(env)


def test_an_over_long_installation_id_is_refused() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_GITHUB_INSTALLATION_ID"] = "1" * 65
    with pytest.raises(SettingsConfigError, match="64 ASCII digits"):
        settings_config(env)
    env["ATLAS_GITHUB_INSTALLATION_ID"] = "1" * 64
    assert settings_config(env).installation_id == "1" * 64


@pytest.mark.parametrize("raw", ["١٢", "１٢", "²"])
def test_the_cap_refuses_non_ascii_digits(raw: str) -> None:
    with pytest.raises(CapRejectedError) as excinfo:
        parse_daily_cap(raw)
    assert str(excinfo.value) == CAP_REFUSED


def test_a_short_session_key_is_refused() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_SESSION_KEY"] = "a"
    with pytest.raises(SettingsConfigError, match="ATLAS_SETTINGS_SESSION_KEY"):
        settings_config(env)
    env["ATLAS_SETTINGS_SESSION_KEY"] = "a" * 32
    assert settings_config(env).session_key == "a" * 32


def test_control_characters_in_the_base_url_are_refused() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = "https://settings.example.com\r\nSet-Cookie: a=b"
    with pytest.raises(SettingsConfigError, match="control characters") as excinfo:
        settings_config(env)
    # The URL itself is never echoed.
    assert "Set-Cookie" not in str(excinfo.value)
    env["ATLAS_SETTINGS_BASE_URL"] = "https://settings.example.com\x7f"
    with pytest.raises(SettingsConfigError, match="control characters"):
        settings_config(env)


def test_the_duplicated_constants_match_their_part_a_sources() -> None:
    """The page is a separate process and keeps local copies of the
    service's env-var names and defaults — pinned here to their part A
    sources, so a rename on either side fails this test. The one
    deliberate exception is ENV_STORE_KEY, which is imported from part
    A's store module itself (the module this page already depends on;
    no new coupling), recorded in D90's bot-findings update."""
    from atlas_reviewer import cli, service
    from atlas_settings import config

    assert config.ENV_APP_ID == cli.ENV_APP_ID
    assert config.ENV_APP_KEY == cli.ENV_APP_KEY
    assert config.ENV_INSTALLATION == cli.ENV_INSTALLATION_ID
    assert config.ENV_STATE_DIR == cli.ENV_STATE_DIR
    assert config.DEFAULT_STATE_DIR == str(cli.DEFAULT_STATE_DIR)
    assert config.DEFAULT_REPO == service.DEFAULT_REPO


def test_the_state_dir_resolves_the_way_the_service_resolves_it() -> None:
    from atlas_reviewer.service import config_from_env

    ours_env = dict(BASE_ENV)
    # An explicitly blank variable resolves to the current directory on
    # both sides — the service's own semantics, copied exactly.
    ours_env["ATLAS_REVIEWER_STATE_DIR"] = ""
    ours = settings_config(ours_env)
    theirs = config_from_env(
        {
            "ATLAS_SERVICE_PORT": "8080",
            "ATLAS_GITHUB_WEBHOOK_SECRET": "0123456789abcdef",
            "ATLAS_ALLOW_LIVE_INFERENCE": "1",
            "ATLAS_REVIEWER_STATE_DIR": "",
        }
    )
    assert ours.state_dir == Path("")
    assert ours.state_dir == theirs.state_dir
    # Unset: the shared default, the same value on both sides.
    del ours_env["ATLAS_REVIEWER_STATE_DIR"]
    ours = settings_config(ours_env)
    theirs = config_from_env(
        {
            "ATLAS_SERVICE_PORT": "8080",
            "ATLAS_GITHUB_WEBHOOK_SECRET": "0123456789abcdef",
            "ATLAS_ALLOW_LIVE_INFERENCE": "1",
        }
    )
    assert ours.state_dir == Path(".atlas-reviewer-state")
    assert ours.state_dir == theirs.state_dir


def test_a_malformed_store_key_refuses_at_startup() -> None:
    env = dict(BASE_ENV)
    env[ENV_STORE_KEY] = "not-a-fernet-key"
    with pytest.raises(SettingsConfigError, match="valid Fernet key") as excinfo:
        settings_config(env)
    assert "not-a-fernet-key" not in str(excinfo.value)


@pytest.mark.parametrize(
    "url",
    ["https://[abc", "https://[::1", "https://host:abc"],
)
def test_a_malformed_base_url_refuses_with_the_named_error(url: str) -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = url
    with pytest.raises(SettingsConfigError, match="is not a valid URL") as excinfo:
        settings_config(env)
    assert url not in str(excinfo.value)


def test_an_over_long_app_id_is_refused() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_GITHUB_APP_ID"] = "1" * 65
    with pytest.raises(SettingsConfigError, match="64 ASCII digits"):
        settings_config(env)
    env["ATLAS_GITHUB_APP_ID"] = "1" * 64
    assert settings_config(env).app_id == "1" * 64


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8090", "http://localhost:8090", "http://[::1]:8090"],
)
def test_each_loopback_host_takes_the_local_http_escape(url: str) -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = url
    assert settings_config(env).base_url == url


def test_a_lookalike_host_is_not_the_loopback_escape() -> None:
    env = dict(BASE_ENV)
    env["ATLAS_SETTINGS_BASE_URL"] = "http://localhost.evil.example"
    with pytest.raises(SettingsConfigError, match="https://"):
        settings_config(env)


def test_the_allowlist_parses_the_way_the_service_parses_it() -> None:
    from atlas_reviewer.service import config_from_env

    def service_env(repos: str | None) -> dict[str, str]:
        env = {
            "ATLAS_SERVICE_PORT": "8080",
            "ATLAS_GITHUB_WEBHOOK_SECRET": "0123456789abcdef",
            "ATLAS_ALLOW_LIVE_INFERENCE": "1",
        }
        if repos is not None:
            env["ATLAS_REVIEW_REPOS"] = repos
        return env

    ours_env = dict(BASE_ENV)
    ours_env["ATLAS_REVIEW_REPOS"] = "  a/b, c/d ,, "
    assert settings_config(ours_env).allowlist == {"a/b", "c/d"}
    assert (
        settings_config(ours_env).allowlist
        == config_from_env(service_env("  a/b, c/d ,, ")).allowlist
    )
    # Unset: the service's default repo.
    del ours_env["ATLAS_REVIEW_REPOS"]
    assert settings_config(ours_env).allowlist == {"brandondees/code-quality-atlas"}
    assert (
        settings_config(ours_env).allowlist
        == config_from_env(service_env(None)).allowlist
    )
    # Blank: the page's parse is not a startup gate, so a blank variable
    # yields the empty set the gate then judges; the service itself
    # refuses an empty allowlist at boot, so there is no service side to
    # compare here.
    ours_env["ATLAS_REVIEW_REPOS"] = "   "
    assert settings_config(ours_env).allowlist == frozenset()


def test_every_long_public_phrase_is_in_the_redaction_guard() -> None:
    from atlas_settings.config import MAX_CAP_USD

    # One enumeration for the guard and the loop: a broken helper fails
    # the non-empty assert instead of silently checking nothing (kills
    # the broken-filter mutant, which left the test green over an empty
    # loop).
    public_strings = _public_phrases(phrases)
    assert public_strings, "the phrases module exposes its constants"
    for name, phrase in public_strings:
        if len(phrase) >= _REDACTION_MIN_CHARS:
            assert phrase in phrases.REDACTION_GUARD_TEXTS, name
    # The cap phrase names the config bound; the two cannot drift.
    assert "$10000" in CAP_REFUSED
    assert MAX_CAP_USD == Decimal(10000)


_REDACTION_MIN_CHARS = 8
"""The redaction register's floor: a phrase shorter than this can never
be registered for scrubbing, so it needs no guard entry."""


def _public_phrases(module: object) -> list[tuple[str, str]]:
    return [
        (name, value)
        for name, value in vars(module).items()
        if not name.startswith("_")
        and isinstance(value, str)
        and name != "DELETE_CONFIRM_WORD"
    ]
