# SPDX-License-Identifier: MIT
"""Every fixed phrase the settings page refuses, answers, and shows
with (D90). One module holds them so a refusal reads the same words on
every path, tests can pin them, and the redaction-guard check can
enumerate the texts the page and its neighbors write into logs."""

from __future__ import annotations

from atlas_reviewer.budget import (
    BUDGET_REACHED,
    CAP_REACHED,
    STORE_UNAVAILABLE,
)
from atlas_reviewer.installation_store import (
    CONSENT_REQUIRED,
    STORE_BROKEN,
)

# The consent statement (plan §7 decision 3, verbatim from the plan's
# own sentence): what the acknowledgement covers, shown on the consent
# form and required before credentials are usable.
CONSENT_STATEMENT = "The PR diff is sent to the installation's own endpoint."

CONSENT_PROMPT = (
    "I acknowledge that reviews for this installation run on its own "
    "model endpoint and that " + CONSENT_STATEMENT
)

# Saving credentials while the consent is unacknowledged stores nothing
# and says why.
CONSENT_REFUSED = (
    "credentials cannot be saved until the installation admin "
    "acknowledges the data-policy consent on this page"
)

ADMIN_REFUSED = (
    "the settings page refused the request: the signed-in user is not "
    "an administrator of this installation"
)

GATE_REFUSED = (
    "the settings page refused: this installation covers no repository "
    "on the reviewer's allowlist"
)

CSRF_REFUSED = (
    "the form's cross-site request token was missing or stale; nothing was changed"
)

SESSION_EXPIRED = "the session expired; sign in again"

RATE_LIMITED = "too many requests; wait and try again"

LOGIN_FAILED = "GitHub sign-in did not complete; try again"

GITHUB_CHECK_FAILED = (
    "GitHub could not confirm what this request needs; nothing was changed"
)

STORE_REFUSED_PREFIX = "the installation store refused the change: "

ENDPOINT_REFUSED_PREFIX = "the endpoint was refused: "

MODEL_REFUSED_PREFIX = "the model was refused: "

DELETE_CONFIRM_WORD = "DELETE"

DELETE_CONFIRM_PROMPT = (
    f"type {DELETE_CONFIRM_WORD} to delete this installation's "
    "credentials, cap and consent"
)

DELETE_MISMATCH = "the confirmation word did not match; nothing was deleted"

CONSENT_UNCHECKED = "the acknowledgement checkbox was not checked; nothing was recorded"

CAP_STATEMENT = (
    "No cap set means no installation cap applies; the per-repo daily "
    "budget and the operator's max per review remain the outer bounds "
    "either way — whichever bound is stricter governs each review."
)

# The daily-cap refusal, the phrase `config.parse_daily_cap` raises with.
# The bound it names ($10000) is `config.MAX_CAP_USD`; the test pins the
# two together so they cannot drift.
CAP_REFUSED = (
    "the daily cap must be a dollar amount between $0.01 and $10000 "
    "with at most two decimal places, or empty to clear it (no cap set "
    "means none applies; the per-repo daily budget and the operator's "
    "max per review remain the outer bounds either way)"
)

# The fixed texts whose words a tenant key must not collide with (D89's
# r2 record, n-c: refusing colliding keys is part B's intake check). The
# service's fixed refusals are the log text that is guaranteed to
# exist; the residual beyond this enumerated set is named in D90.
REDACTION_GUARD_TEXTS: tuple[str, ...] = (
    CONSENT_STATEMENT,
    CONSENT_PROMPT,
    CONSENT_REFUSED,
    CONSENT_UNCHECKED,
    ADMIN_REFUSED,
    GATE_REFUSED,
    CSRF_REFUSED,
    SESSION_EXPIRED,
    RATE_LIMITED,
    LOGIN_FAILED,
    GITHUB_CHECK_FAILED,
    DELETE_CONFIRM_PROMPT,
    DELETE_MISMATCH,
    CAP_STATEMENT,
    CAP_REFUSED,
    STORE_REFUSED_PREFIX,
    ENDPOINT_REFUSED_PREFIX,
    MODEL_REFUSED_PREFIX,
    CONSENT_REQUIRED,
    STORE_BROKEN,
    BUDGET_REACHED,
    CAP_REACHED,
    STORE_UNAVAILABLE,
)
