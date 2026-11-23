# SPDX-License-Identifier: MIT
"""The operator entry point: the startup refusals and the composition
root — `main`'s exit-2 contract for a misconfigured environment (the
message names the missing variables and never a value), `build`'s
refusal when the installation store cannot be used, the wired app a
configured environment gets, and the bind failure folded into the same
clean exit. The serving loop itself runs behind a stub server here;
its request handling is the socket-level suite's subject."""

import os
from pathlib import Path

import pytest

from atlas_settings.__main__ import build, main
from atlas_settings.app import SettingsApp
from atlas_settings.config import SettingsConfig, SettingsConfigError, settings_config

from .harness import BASE_ENV


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = dict(BASE_ENV)
    env["ATLAS_REVIEWER_STATE_DIR"] = str(tmp_path / "state")
    env.update(overrides)
    return env


def test_a_missing_config_exits_two_naming_the_missing_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A misconfigured environment exits 2 with the aggregated
    missing-variable message on stderr — variable names only: a value
    that is present is never echoed (kills the echo-the-value mutant)."""
    monkeypatch.setattr(
        os,
        "environ",
        {"ATLAS_SETTINGS_SESSION_KEY": "fake-session-secret-value-0123456789"},
    )
    exit_code = main([])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert err.startswith("atlas_settings: ")
    assert "ATLAS_SETTINGS_GITHUB_CLIENT_ID" in err
    assert "ATLAS_SETTINGS_BASE_URL" in err
    assert "ATLAS_GITHUB_APP_ID" in err
    assert "fake-session-secret-value-0123456789" not in err


def test_an_unconfigured_store_refuses_to_start(tmp_path: Path) -> None:
    """An environment without a store key leaves the store unconfigured
    (no records on disk), and `build` refuses to start naming the store
    as unusable. The config gate above `build` requires a valid key, so
    the refusal is reached by handing `build` the environment it is
    asked to run with — its own contract, one gate deeper."""
    env = _env(tmp_path)
    storeless = dict(env)
    del storeless["ATLAS_INSTALLATION_STORE_KEY"]
    with pytest.raises(SettingsConfigError, match="not usable"):
        build(settings_config(env), storeless)


def test_a_broken_store_refuses_to_start(tmp_path: Path) -> None:
    """A store key that is not a valid Fernet key leaves the store
    broken — every read would fail — and `build` refuses to start with
    the store's own reason carried, one gate deeper than the config's
    own key validation."""
    env = _env(tmp_path)
    broken = dict(env, ATLAS_INSTALLATION_STORE_KEY="not-a-fernet-key")
    with pytest.raises(SettingsConfigError, match="not usable"):
        build(settings_config(env), broken)


def test_a_configured_environment_builds_a_wired_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fully configured environment composes the page exactly as the
    tested modules expect: the config is the one the environment
    produced, and the store is the configured one."""
    env = _env(tmp_path)
    monkeypatch.setattr(os, "environ", env)
    config: SettingsConfig = settings_config()
    app = build(config, env)
    assert isinstance(app, SettingsApp)
    assert app.config is config
    assert app.store.configured is True


def test_the_serving_loop_starts_and_stops_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A configured environment serves: the startup line names the
    address, the loop runs until interrupted, and the server is closed
    on the way out (kills the dropped-server_close mutant, which leaked
    the listening socket)."""
    import atlas_settings.__main__ as entry

    monkeypatch.setattr(os, "environ", _env(tmp_path))

    class StubServer:
        def __init__(self) -> None:
            self.closed = False

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self.closed = True

    stub = StubServer()
    monkeypatch.setattr(entry, "serve", lambda *args, **kwargs: stub)
    exit_code = main([])
    assert exit_code == 0
    assert stub.closed is True
    out = capsys.readouterr().out
    assert "serving on http://127.0.0.1:8090" in out


def test_a_bind_failure_folds_into_the_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A port already in use is the operator's most common startup
    error: it folds into the same clean `atlas_settings: <reason>`
    exit-2 shape as a misconfigured environment, instead of a raw
    traceback (kills the raw-traceback mutant)."""
    import atlas_settings.__main__ as entry

    monkeypatch.setattr(os, "environ", _env(tmp_path))

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(entry, "serve", refuse)
    exit_code = main([])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert err.startswith("atlas_settings: ")
    assert "Address already in use" in err
