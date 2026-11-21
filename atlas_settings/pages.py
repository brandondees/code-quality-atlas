# SPDX-License-Identifier: MIT
"""The settings page's server-rendered HTML: one layout, one settings
page, one error page. No client-side JavaScript, no third-party script,
font, or CDN — the page's only active surface is plain HTML forms
posted to the page's own `/settings/*` routes, and every dynamic value
is escaped on its way into the markup."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime

from atlas_settings.phrases import (
    CAP_STATEMENT,
    CONSENT_PROMPT,
    CONSENT_STATEMENT,
    DELETE_CONFIRM_PROMPT,
)


@dataclass(frozen=True)
class StoredCredentials:
    """The stored-credentials fact as one value: a record exists, saved
    at this time, holding this endpoint and model. One optional value
    instead of four loose parameters — no combination exists where an
    endpoint shows without a key behind it. `saved_at` is the audit's
    own record of the last store-credentials write falling back to the
    record's timestamp; `None` means neither could answer — the audit
    line is lost and the record carries no time of its own — and the
    section still shows, with "not on record" in place of the time."""

    saved_at: datetime | None
    base_url: str
    model: str


def layout(title: str, body: str, flash: str | None = None) -> str:
    """One page: the stylesheet link, the flash line when a status
    message rides the render, the body. The flash is escaped like every
    other interpolated text — it is written by this page from fixed
    phrases, but the escape is not a judgment call."""
    flash_html = f'<p class="flash" role="status">{esc(flash)}</p>' if flash else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="/static/styles.css">
</head>
<body>
<header><h1>Atlas reviewer — BYOK settings</h1></header>
{flash_html}
<main>
{body}
</main>
</body>
</html>"""


def login_page() -> str:
    body = """<p>Sign in with GitHub to manage this installation's
reviewer settings. Only the installation's administrator — the org
owner, or the owner of the user account the App is installed on — may
use this page.</p>
<p><a href="/login" rel="nofollow">Sign in with GitHub</a></p>"""
    return layout("Sign in", body)


def error_page(title: str, message: str) -> str:
    body = f"<p>{esc(message)}</p>"
    body += '<p><a href="/">Start over</a></p>'
    return layout(title, body)


def settings_page(
    *,
    installation_id: str,
    account_login: str,
    account_type: str,
    allowlisted_repo_count: int,
    credentials: StoredCredentials | None,
    consent_acknowledged_at: datetime | None,
    daily_cap_usd: str | None,
    csrf: str,
    flash: str | None = None,
    prefill_base_url: str = "",
    prefill_model: str = "",
) -> str:
    """The settings page itself. The key is never shown — not even
    partly — after it is saved; what is shown is that a key is set, when
    it was saved, the endpoint, and the model."""
    sections: list[str] = [
        _installation_section(
            installation_id, account_login, account_type, allowlisted_repo_count
        )
    ]
    sections.append(_credentials_section(credentials))
    sections.append(_consent_section(consent_acknowledged_at, csrf))
    sections.append(_cap_section(daily_cap_usd, csrf))
    sections.append(
        _credentials_form_section(
            csrf,
            credentials is not None,
            consent_acknowledged_at,
            prefill_base_url,
            prefill_model,
        )
    )
    sections.append(_danger_section(csrf, credentials is not None))
    return layout("Installation settings", "\n".join(sections), flash=flash)


def _installation_section(
    installation_id: str, account_login: str, account_type: str, repos: int
) -> str:
    return f"""<section id="installation">
<h2>Installation</h2>
<table>
<tr><th>Installation</th><td>{esc(installation_id)}</td></tr>
<tr><th>Account</th><td>{esc(account_login)} ({esc(account_type)})</td></tr>
<tr><th>Allowlist coverage</th><td>{repos} repo(s) on the reviewer's allowlist</td></tr>
</table>
</section>"""


def _credentials_section(credentials: StoredCredentials | None) -> str:
    if credentials is not None:
        status = (
            "<p>A key is stored. The key is never shown again after it "
            "is saved, not even partly.</p>"
            f"<p>Credentials last saved: {esc(_stamp(credentials.saved_at))}.</p>"
            f"<p>Endpoint: <code>{esc(credentials.base_url)}</code></p>"
            f"<p>Model: <code>{esc(credentials.model)}</code></p>"
        )
    else:
        status = "<p>No key is stored for this installation.</p>"
    return (
        f'<section id="credentials-state"><h2>Stored credentials</h2>{status}</section>'
    )


def _consent_section(consent_acknowledged_at: datetime | None, csrf: str) -> str:
    acknowledged = (
        f"<p>Consent acknowledged at {esc(_stamp(consent_acknowledged_at))}.</p>"
        if consent_acknowledged_at is not None
        else f"""<p><strong>Data policy:</strong> {esc(CONSENT_STATEMENT)}</p>
<form method="post" action="/settings/consent">
<input type="hidden" name="csrf" value="{esc_attr(csrf)}">
<label><input type="checkbox" name="acknowledge" value="1" required>
{esc(CONSENT_PROMPT)}</label>
<button type="submit">Record consent</button>
</form>"""
    )
    return f'<section id="consent"><h2>Data-policy consent</h2>{acknowledged}</section>'


def _cap_section(daily_cap_usd: str | None, csrf: str) -> str:
    current = (
        f"${esc(daily_cap_usd)} per UTC day"
        if daily_cap_usd is not None
        else "none set — no installation cap applies"
    )
    return f"""<section id="cap">
<h2>Daily cap</h2>
<p>Current cap: {current}</p>
<p>{esc(CAP_STATEMENT)}</p>
<form method="post" action="/settings/cap">
<input type="hidden" name="csrf" value="{esc_attr(csrf)}">
<label>Daily cap in USD — leave empty to clear the cap
<input type="text" name="cap_usd" inputmode="decimal"
 placeholder="e.g. 5.00"></label>
<button type="submit">Set cap</button>
</form>
</section>"""


def _credentials_form_section(
    csrf: str,
    has_credentials: bool,
    consent_acknowledged_at: datetime | None,
    prefill_base_url: str = "",
    prefill_model: str = "",
) -> str:
    # The endpoint and model are non-secret and refill across a refused
    # submit; the key is never prefilled — a refused save must never be
    # the thing that keeps a pasted key sitting in a form.
    if consent_acknowledged_at is None:
        # The form stays hidden until the consent above is
        # acknowledged: a key pasted into a form whose submit the
        # server would refuse is a dropped secret and a re-typed one.
        return """<section id="credentials-form">
<h2>Add credentials</h2>
<p>The credentials form appears once the data-policy consent above is
acknowledged.</p>
</section>"""
    heading = "Rotate the key" if has_credentials else "Add credentials"
    return f"""<section id="credentials-form">
<h2>{heading}</h2>
<p>The endpoint must be an <code>https://</code> URL whose host passes
the reviewer's egress checks. The model must have an entry in the
operator's price table; a model priced at zero is allowed. No test
model call is made.</p>
<form method="post" action="/settings/credentials">
<input type="hidden" name="csrf" value="{esc_attr(csrf)}">
<label>Endpoint base URL
<input type="url" name="base_url" autocomplete="off"
 value="{esc_attr(prefill_base_url)}"></label>
<label>API key
<input type="password" name="key" autocomplete="new-password"></label>
<label>Model
<input type="text" name="model" autocomplete="off"
 value="{esc_attr(prefill_model)}"></label>
<button type="submit">Save credentials</button>
</form>
</section>"""


def _danger_section(csrf: str, has_credentials: bool) -> str:
    # Revocation is deliberately one click, with no confirm step: it is
    # the leaked-key path, where every extra interaction is time the
    # attacker keeps the key. Deletion, which removes the cap and the
    # consent too, is the one behind the typed confirmation.
    revoke = (
        f"""<form method="post" action="/settings/revoke">
<input type="hidden" name="csrf" value="{esc_attr(csrf)}">
<button type="submit" class="danger">Revoke the key</button>
</form>
<p>Revoking removes the key; the cap and the consent acknowledgement
stay.</p>"""
        if has_credentials
        else ""
    )
    return f"""<section id="danger">
<h2>Revoke and delete</h2>
{revoke}
<form method="post" action="/settings/delete">
<input type="hidden" name="csrf" value="{esc_attr(csrf)}">
<label>{esc(DELETE_CONFIRM_PROMPT)}
<input type="text" name="confirm" autocomplete="off"></label>
<button type="submit" class="danger">Delete everything</button>
</form>
<p>Deleting removes the credentials, the cap and the consent
acknowledgement together.</p>
</section>"""


def _stamp(moment: datetime | None) -> str:
    """A stamp in UTC, whatever offset the stored value carries; a naive
    or missing value is "not on record" — the store requires an offset,
    so a naive value reaching this far is already not a fact to show."""
    if moment is None or moment.tzinfo is None:
        return "not on record"
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def esc(value: str) -> str:
    """Element text: escaping the markup-significant characters. The
    quote attribute form is `esc_attr`, which also escapes the quote
    characters themselves."""
    return html.escape(value, quote=False)


def esc_attr(value: str) -> str:
    return html.escape(value, quote=True)
