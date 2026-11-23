# SPDX-License-Identifier: MIT
"""Operator entry point: `python -m atlas_settings [--host H] [--port P]`.

Runs the BYOK settings page as its own process beside the review
service, sharing the state volume (`ATLAS_REVIEWER_STATE_DIR`) and part
A's store module. The page refuses to start when any of its environment
variables is missing — see `atlas_settings.config` for the list and the
README's operator section for what each one is. Deployment is out of
scope for this slice; the README records how the page is run.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping

from atlas_reviewer.clock import SystemClock
from atlas_reviewer.http import UrllibTransport
from atlas_reviewer.installation_store import InstallationStore
from atlas_settings.app import SettingsApp
from atlas_settings.audit import AUDIT_FILE_NAME, AuditLog
from atlas_settings.config import SettingsConfig, SettingsConfigError, settings_config
from atlas_settings.github import GitHubClient
from atlas_settings.ratelimit import RateLimiter
from atlas_settings.server import serve
from atlas_settings.sessions import SessionStore


def build(config: SettingsConfig, env: Mapping[str, str]) -> SettingsApp:
    """The page's composition root: part A's store (opened exactly the
    way the service opens it), the GitHub boundary, the session store,
    the rate limiter, and the audit log."""
    store = InstallationStore.open(config.state_dir, env)
    if not store.configured:
        raise SettingsConfigError(
            "the settings page refuses to start; the installation store "
            "is not usable: "
            + (store.broken_reason or "the installation store is not configured")
        )
    github = GitHubClient(
        UrllibTransport(),
        SystemClock(),
        app_id=config.app_id,
        app_private_key=config.app_private_key,
        installation_id=config.installation_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
    )
    return SettingsApp(
        config=config,
        store=store,
        github=github,
        sessions=SessionStore(config.session_key),
        limiter=RateLimiter(),
        audit=AuditLog(config.state_dir / AUDIT_FILE_NAME),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_settings",
        description="Run the BYOK settings page (config slice S10, part B1).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)
    try:
        config = settings_config()
        app = build(config, dict(os.environ))
    except SettingsConfigError as exc:
        print(f"atlas_settings: {exc}", file=sys.stderr)
        return 2
    try:
        server = serve(app, args.host, args.port, lambda line: print(line, flush=True))
    except OSError as exc:
        # The port already in use is the operator's most common startup
        # error: it folds into the same clean exit-2 shape as a
        # misconfigured environment instead of a raw traceback.
        print(f"atlas_settings: {exc}", file=sys.stderr)
        return 2
    print(
        f"atlas_settings: serving on http://{args.host}:{args.port} "
        f"(state dir {config.state_dir}, audit {AUDIT_FILE_NAME})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if (
    __name__ == "__main__"
):  # pragma: no cover - the imported module is what the tests run
    sys.exit(main())
