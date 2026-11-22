# SPDX-License-Identifier: MIT
"""The rendered pages, tested directly against the rendering functions:
every section's both states, the escaping, and the write-only key — the
settings render never carries a key, whatever the inputs."""

from datetime import UTC, datetime, timedelta, timezone

from atlas_settings.pages import (
    StoredCredentials,
    error_page,
    esc,
    esc_attr,
    layout,
    login_page,
    settings_page,
)

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
CSRF = "csrf-token-value"


def _stored(**overrides: object) -> StoredCredentials | None:
    """The stored-credentials value from the loose test shorthand: the
    tests' `has_credentials`/`credentials_saved_at`/`base_url`/`model`
    keys compose into the one value the page now takes."""
    if not overrides.pop("has_credentials", False):
        return None
    return StoredCredentials(
        saved_at=overrides.pop("credentials_saved_at", None),  # type: ignore[arg-type]
        base_url=overrides.pop("base_url", ""),  # type: ignore[arg-type]
        model=overrides.pop("model", ""),  # type: ignore[arg-type]
    )


def _render(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "installation_id": "42",
        "account_login": "octo-admin",
        "account_type": "User",
        "allowlisted_repo_count": 1,
        "consent_acknowledged_at": None,
        "daily_cap_usd": None,
        "csrf": CSRF,
        "flash": None,
    }
    kwargs.update(overrides)
    kwargs["credentials"] = _stored(**kwargs)  # type: ignore[arg-type]
    for name in ("has_credentials", "credentials_saved_at", "base_url", "model"):
        kwargs.pop(name, None)
    return settings_page(**kwargs)  # type: ignore[arg-type]


def test_the_layout_escapes_and_carries_the_flash_only_when_given() -> None:
    plain = layout("Title", "<p>body</p>")
    assert "<title>Title</title>" in plain
    assert "flash" not in plain
    flashed = layout("Title", "<p>body</p>", flash="the fixed phrase")
    assert '<p class="flash" role="status">the fixed phrase</p>' in flashed


def test_the_login_page_asks_for_github_sign_in() -> None:
    page = login_page()
    assert 'href="/login"' in page
    assert "administrator" in page


def test_the_error_page_carries_its_message_and_a_way_back() -> None:
    page = error_page("Refused", "the fixed phrase")
    assert "<title>Refused</title>" in page
    assert "the fixed phrase" in page
    assert 'href="/"' in page


def test_both_sections_carry_their_headings_in_both_states() -> None:
    """The stored-credentials and consent headings render in both the
    unset and stored states, so removing either heading fails in either
    state (the review's surviving-mutant case)."""
    for page in (
        _render(),
        _render(
            has_credentials=True,
            credentials_saved_at=NOW,
            base_url="https://api.example.com/v1",
            model="vendor/good-model",
            consent_acknowledged_at=NOW,
        ),
    ):
        assert "<h2>Stored credentials</h2>" in page
        assert "<h2>Data-policy consent</h2>" in page


def test_the_unset_installation_renders_the_consent_form_and_no_credentials() -> None:
    page = _render()
    assert "No key is stored" in page
    assert "none set" in page
    assert "Data policy:" in page
    assert 'action="/settings/consent"' in page
    assert 'type="checkbox"' in page
    # The credentials form stays hidden until the consent is
    # acknowledged: a key pasted into a form the server would refuse is
    # a dropped secret (kills the always-render-form mutant).
    assert 'action="/settings/credentials"' not in page
    assert "appears once the data-policy consent" in page
    # Nothing stored yet: the danger section offers only the delete.
    assert 'action="/settings/revoke"' not in page
    assert 'action="/settings/delete"' in page


def test_every_state_changing_form_is_a_post_with_the_csrf_token() -> None:
    """Every form is `method="post"` carrying the session's CSRF token:
    a mutant that deletes a token input or switches a form to GET fails
    here (the review's not-posted finding, named). The token carries a
    quote and an ampersand, and each form's own input is asserted in
    its exact escaped form — so a text-escaper swap at any single form
    (the consent input's mutant) fails for that form, not just in
    bulk."""
    quote_csrfs = "tok\"en&#x27;'&<csrf>"
    for page in (
        _render(),
        _render(
            has_credentials=True,
            credentials_saved_at=NOW,
            base_url="https://api.example.com/v1",
            model="vendor/good-model",
            consent_acknowledged_at=NOW,
            daily_cap_usd="5.25",
        ),
    ):
        actions = [
            name
            for name in ("consent", "credentials", "revoke", "cap", "delete")
            if f'action="/settings/{name}"' in page
        ]
        assert actions
        for action in actions:
            form = _form_for(page, action)
            assert 'method="post"' in form, action
            assert 'name="csrf" value="csrf-token-value"' in form, action
    # The per-site escaper pin: every CSRF input renders the quote- and
    # ampersand-bearing token through `esc_attr`, asserted per form.
    for page in (
        _render(csrf=quote_csrfs),
        _render(
            has_credentials=True,
            credentials_saved_at=NOW,
            base_url="https://api.example.com/v1",
            model="vendor/good-model",
            consent_acknowledged_at=NOW,
            csrf=quote_csrfs,
        ),
    ):
        for action in (
            name
            for name in ("consent", "credentials", "revoke", "cap", "delete")
            if f'action="/settings/{name}"' in page
        ):
            form = _form_for(page, action)
            assert (
                'name="csrf" value="tok&quot;en&amp;#x27;&#x27;&amp;&lt;csrf&gt;"'
                in form
            ), action


def _form_for(page: str, action: str) -> str:
    """The markup of one form, from its `<form` open to its `</form>`
    close — the per-site assertions read one form at a time so a swap
    at a single input cannot hide behind its four siblings."""
    form_at = page.index(f'action="/settings/{action}"')
    form_start = page.rindex("<form", 0, form_at)
    form_end = page.find("</form>", form_at)
    return page[form_start : form_end + 7]


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
    """`saved_at=None` is the documented state where the audit line is
    lost and the record carries no time of its own: the section still
    shows, with "not on record" in place of the time."""
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


def test_a_stamp_in_another_offset_renders_in_utc() -> None:
    """A stored time carries its own offset; the page shows it in UTC
    (kills the literal-UTC-suffix mutant, which never converts: a 14:00
    stamp at +02:00 is 12:00 UTC, not "14:00 UTC")."""
    page = _render(
        has_credentials=True,
        credentials_saved_at=datetime(
            2026, 11, 19, 14, 0, 0, tzinfo=timezone(timedelta(hours=2))
        ),
        base_url="https://api.example.com/v1",
        model="vendor/good-model",
        consent_acknowledged_at=NOW,
    )
    assert "Credentials last saved: 2026-11-19 12:00:00 UTC." in page


def test_a_naive_stamp_is_not_on_record() -> None:
    """The store requires an offset, so a naive value reaching the page
    is not a fact to show."""
    naive = datetime(2026, 11, 19, 14, 0, 0)
    page = _render(
        has_credentials=True,
        credentials_saved_at=naive,
        base_url="https://api.example.com/v1",
        model="vendor/good-model",
        consent_acknowledged_at=NOW,
    )
    assert "Credentials last saved: not on record." in page


def test_the_hostile_payload_escapes_in_every_field() -> None:
    """The hostile probe rides every interpolated field — the element
    texts, the attribute value with its quote, the installation id and
    account type, the cap figure, `error_page`'s title and message, and
    `layout`'s title — and the escaped forms are asserted directly, so
    nothing raw survives and a switch to the text escaper in an
    attribute context fails here (the review's attribute-injection
    case). The payload carries ` onsubmit=x` so an unescaped value
    would render a live event-handler attribute — the escaped form is
    what the assertions demand, per form."""
    payload = "<script>\"'& onsubmit=x"
    page = _render(
        installation_id=payload,
        account_login=payload,
        account_type=payload,
        base_url=f"https://{payload}/v1",
        model=payload,
        consent_acknowledged_at=NOW,
        has_credentials=True,
        credentials_saved_at=NOW,
        daily_cap_usd=payload,
        csrf=payload,
        flash=payload,
    )
    assert "<script>" not in page
    # Every attribute context escapes the quote and the apostrophe —
    # the exact escaped form is asserted per form, because the weaker
    # "raw open-tag absent" check passes even when a text escaper ends
    # a value attribute early, and because one swapped call site must
    # fail alone, not only when every site swaps at once.
    for action in (
        name
        for name in ("consent", "credentials", "revoke", "cap", "delete")
        if f'action="/settings/{name}"' in page
    ):
        form = _form_for(page, action)
        assert (
            'name="csrf" value="&lt;script&gt;&quot;&#x27;&amp; onsubmit=x"' in form
        ), action
    error = error_page(payload, payload)
    assert "<script>" not in error
    # Element text needs no quote escaping (a quote cannot break out of
    # it); the markup-significant characters are what must be escaped.
    assert "&lt;script&gt;" in error
    titled = layout(payload, "<p>body</p>")
    assert "<title>&lt;script&gt;" in titled


def test_the_credentials_form_refills_the_non_secret_fields() -> None:
    """A refused submit re-renders with the endpoint and model the admin
    typed (escaped into the value attributes); the key is never
    prefilled — a refused save must never leave a pasted key sitting in
    the form. The assertions are whitespace-robust (the template's
    line breaks are its own, not a contract) and the hostile probe
    rides both refilled fields, so a text-escaper swap at either
    prefill input fails alone."""
    page = _render(
        consent_acknowledged_at=NOW,
        prefill_base_url="https://api.example.com/v1",
        prefill_model="vendor/good-model",
    )
    flat = " ".join(page.split())
    assert (
        'name="base_url" autocomplete="off" value="https://api.example.com/v1"' in flat
    )
    assert 'name="model" autocomplete="off" value="vendor/good-model"' in flat
    assert 'name="key"' in page
    assert 'name="key" value=' not in page
    # A hostile prefill escapes too: the value attribute cannot be
    # broken out of, per field.
    hostile = _render(
        consent_acknowledged_at=NOW,
        prefill_base_url="<script>\"'&",
        prefill_model="<script>\"'&",
    )
    assert 'value="<script>' not in hostile
    hostile_flat = " ".join(hostile.split())
    assert (
        'name="base_url" autocomplete="off" '
        'value="&lt;script&gt;&quot;&#x27;&amp;"' in hostile_flat
    )
    assert (
        'name="model" autocomplete="off" '
        'value="&lt;script&gt;&quot;&#x27;&amp;"' in hostile_flat
    )


def test_the_destructive_buttons_carry_the_danger_class_and_the_safe_ones_do_not() -> (
    None
):
    """The revoke and delete buttons render `class="danger"` — the
    leaked-key path's one-click style — and the safe buttons (Set cap,
    Save credentials) do not (kills the strip-the-class mutant, and
    pins that the style did not spread to the everyday buttons)."""
    page = _render(
        has_credentials=True,
        credentials_saved_at=NOW,
        base_url="https://api.example.com/v1",
        model="vendor/good-model",
        consent_acknowledged_at=NOW,
    )
    assert '<button type="submit" class="danger">Revoke the key</button>' in page
    assert '<button type="submit" class="danger">Delete everything</button>' in page
    assert '<button type="submit">Set cap</button>' in page
    assert '<button type="submit">Save credentials</button>' in page


def test_the_clear_cap_hint_lives_in_the_label_not_a_placeholder() -> None:
    """The "leave empty to clear the cap" instruction is label text —
    the placeholder carries the example — so a screen reader reading
    the field's name gets the instruction (kills the hint-into-the-
    placeholder mutant, which moves the text where only a focused
    field shows it)."""
    page = _render(consent_acknowledged_at=NOW)
    label_at = page.index('name="cap_usd"')
    label_start = page.rindex("<label", 0, label_at)
    label_end = page.find("</label>", label_at)
    label = page[label_start:label_end]
    assert "leave empty to clear the cap" in label
    placeholder_at = page.find('placeholder="')
    placeholder = page[placeholder_at + 13 : page.find('"', placeholder_at + 13)]
    assert "leave empty" not in placeholder
    assert placeholder == "e.g. 5.00"
