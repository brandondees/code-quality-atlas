# SPDX-License-Identifier: MIT
"""The intake validations the settings page runs before anything is
stored (D90):

- the endpoint base URL passes part A's URL-level check (`egress`)
  **and** its host passes the egress guard's resolution check — HTTPS
  only, no userinfo, and every address the host resolves to outside the
  blocked set. No test model call is made: the validation costs no
  tenant money, and the per-connection pinned connect is the review
  path's own half.
- the chosen model passes the operator's price table — the same public
  catalog read and parse part A's tenant provider runs. A model with no
  entry is refused; a zero-priced model is allowed (D81's Q3 answer);
  the read carries no credential and makes no model call.
- the key cannot collide with controller text: a key of the length the
  redaction registers (8+ characters) that is a substring of one of the
  fixed phrases the page and the store write into logs would redact
  those words tenant-scoped (D89's r2 record, n-c, names this check as
  part B's). The residual — controller text beyond the enumerated
  phrases — is named in D90, not claimed away.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from atlas_reviewer import egress
from atlas_reviewer.http import UrllibTransport
from atlas_reviewer.installation_store import InstallationStoreError
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.tenant_provider import (
    CATALOG_API_URL,
    CATALOG_TIMEOUT_S,
    PricingUnknownError,
    terms_from_catalog,
)
from atlas_settings.phrases import REDACTION_GUARD_TEXTS


def validate_endpoint(
    url: str,
    *,
    resolve: Callable[[str, int], egress.Pinned] | None = None,
) -> None:
    """The endpoint's intake check: the URL-level guard, then the host's
    resolution against the blocked set. Raises `EgressRefused` — the
    guard's own refusal, the same words the review path refuses with —
    when either half fails."""
    egress.check_url(url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port if parts.port is not None else 443
    resolver = resolve if resolve is not None else egress.resolve_and_check
    resolver(host, port)


def validate_model(
    model: str, *, transport: UrllibTransport | None = None
) -> tuple[Decimal, Decimal]:
    """The model's intake check against the operator's price table: the
    catalog entry read without any credential and parsed by part A's
    own parse. Returns the (prompt, completion) per-million rates —
    zero allowed, negative or missing refused — so the page can state
    the model is priced, and nothing about the check makes a model
    call. The transport is a test seam; production uses the real one."""
    mover = transport if transport is not None else UrllibTransport()
    try:
        resp = mover.request(
            "GET",
            f"{CATALOG_API_URL}/model/{model}",
            {
                "User-Agent": "code-quality-atlas-settings",
                "Accept": "application/json",
            },
            None,
            CATALOG_TIMEOUT_S,
        )
    except (BoundaryError, OSError, TimeoutError, ValueError) as exc:
        raise PricingUnknownError(
            "the operator's price table could not be read for this "
            "model; the model is refused"
        ) from exc
    if resp.status != 200:
        raise PricingUnknownError(
            "the operator's price table has no readable entry for this "
            f"model (HTTP {resp.status}); the model is refused"
        )
    try:
        data: Any = json.loads(resp.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PricingUnknownError(
            "the operator's price table returned a response this page "
            "cannot read; the model is refused"
        ) from exc
    terms = terms_from_catalog(data, model)
    return terms.prompt_rate, terms.completion_rate


def check_key_against_controller_text(key: str) -> None:
    """Refuse a key that would over-redact: one of the fixed controller
    texts contains the key as a substring. The store's own bounds
    (1–4096 characters, no NUL) still apply through it; this is the
    page's additional intake refusal."""
    for text in REDACTION_GUARD_TEXTS:
        if len(key) >= 8 and key in text:
            raise InstallationStoreError(
                "the API key was refused: it would collide with the "
                "service's own fixed log text"
            )
