# SPDX-License-Identifier: MIT
"""The rendered pages, tested directly against the rendering functions:
every section's both states, the escaping, and the write-only key — the
settings render never carries a key, whatever the inputs."""

from datetime import UTC, datetime

from atlas_settings.pages import (
    error_page,
    esc,
    esc_attr,
    layout,
    login_page,
    settings_page,
)

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
CSRF = "csrf-token-value"


def _render(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "installation_id": "42",
        "account_login": "octo-admin",
        "account_type": "User",
        "allowlisted_repo_count": 1,
        "has_credentials": False,
        "credentials_saved_at": None,
        "base_url": "",
        "model": "",
        "consent_acknowledged_at": None,
        "daily_cap_usd": None,
        "csrf": CSRF,
        "flash": None,
    }
    kwargs.update(overrides)
    return settings_page(**kwargs)  # type: ignore[arg-type]


def test_the_layout_escapes_and_carries_the_flash_only_when_given() -> None:
    plain = layout("Title", "<p>body</p>")
    assert "<title>Title</title>" in plain
    assert "flash" not in plain
    flashed = layout("Title", "<p>body</p>", flash="the fixed phrase")
    assert '<p class="flash">the fixed phrase</p>' in flashed


def test_the_login_page_asks_for_github_sign_in() -> None:
    page = login_page()
    assert 'href="/login"' in page
    assert "administrator" in page


def test_the_error_page_carries_its_message_and_a_way_back() -> None:
    page = error_page("Refused", "the fixed phrase")
    assert "<title>Refused</title>" in page
    assert "the fixed phrase" in page
    assert 'href="/"' in page


def test_the_unset_installation_renders_the_consent_form_and_no_credentials() -> None:
    page = _render()
    assert "No key is stored" in page
    assert "none set" in page
    assert "Data policy:" in page
    assert 'action="/settings/consent"' in page
    assert 'type="checkbox"' in page
    assert 'action="/settings/credentials"' in page
    # Nothing stored yet: the danger section offers only the delete.
    assert 'action="/settings/revoke"' not in page
    assert 'action="/settings/delete"' in page


def test_the_stored_credentials_are_shown_without_the_key() -> None:
    page = _render(
        has_credentials=True,
        credentials_saved_at=NOW,
        base_url="https://api.example.com/v1",
        model="vendor/good-model",
        consent_acknowledged_at=NOW,
        daily_cap_usd="5.25",
    )
    assert "A key is stored" in page
    assert "never shown again" in page
    assert "Credentials last saved: 2026-11-19 12:00:00 UTC." in page
    assert "<code>https://api.example.com/v1</code>" in page
    assert "<code>vendor/good-model</code>" in page
    assert "Consent acknowledged at" in page
    assert "$5.25 per UTC day" in page
    assert 'action="/settings/revoke"' in page
    assert "Rotate the key" in page


def test_a_stored_key_without_a_recorded_save_time_says_so() -> None:
    page = _render(
        has_credentials=True,
        credentials_saved_at=None,
        base_url="https://api.example.com/v1",
        model="vendor/good-model",
    )
    assert "Credentials last saved: not on record." in page


def test_the_escaped_values_never_become_markup() -> None:
    page = _render(account_login="<script>alert(1)</script>")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_the_text_and_attribute_escapers_differ_in_quote_handling() -> None:
    # Element text: the markup-significant characters only — the quote
    # characters pass through. Attribute values: the quotes escaped too.
    assert esc("a<b>&'\"") == "a&lt;b&gt;&amp;'\""
    assert esc_attr("a<b>&'\"") == "a&lt;b&gt;&amp;&#x27;&quot;"
