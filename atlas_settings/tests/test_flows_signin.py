# SPDX-License-Identifier: MIT
"""The settings page's flows, part one of the split flow suite: the
full GitHub sign-in against the fake, the settings page's render, the
consent acknowledgement, the credentials' first save with its intake
validations, and the refusals those surfaces decide — sign-in failures,
the expired and lost-authorization paths' read side, the store naming
its own failure, hostile endpoints, the unknown model. The write
surface's own flows (rotate, revoke, cap, delete, CSRF, the audit of
every write) are this suite's second file."""

import json
from decimal import Decimal
from pathlib import Path

from atlas_reviewer.installation_store import InstallationStore
from atlas_reviewer.tenant_provider import PricingUnknownError
from atlas_settings.app import LOGIN_LIMIT
from atlas_settings.phrases import (
    ADMIN_REFUSED,
    CONSENT_REFUSED,
    CONSENT_STATEMENT,
    CONSENT_UNCHECKED,
    GATE_REFUSED,
    LOGIN_FAILED,
)

from .harness import (
    ADMIN_ID,
    ADMIN_LOGIN,
    FAKE_KEY,
    GOOD_ENDPOINT,
    GOOD_MODEL,
    ORG_ACCOUNT_LOGIN,
    OTHER_REPO,
    UNKNOWN_MODEL,
    ZERO_MODEL,
    _credentials_form,
    build_world,
    default_resolve,
    sign_in,
)

# ---- sign-in --------------------------------------------------------


def test_the_full_login_flow_ends_signed_in(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    cookie = sign_in(world)
    assert cookie
    page = world.page_text()
    assert "octo-admin" in page
    assert "Installation" in page


def test_the_login_page_asks_for_github_sign_in(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    response = world.app.get("/", "", "", "1.2.3.4")
    assert response.status == 200
    assert "Sign in with GitHub" in response.body.decode()


def test_a_state_mismatch_at_the_callback_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    response = world.app.get(
        "/callback", "code=fake-code&state=forged-state", cookie, "1.2.3.4"
    )
    assert response.status == 403
    assert LOGIN_FAILED in response.body.decode()
    # No signed-in session was created; the read still answers signed
    # out (the redirect to the sign-in page).
    response = world.app.get("/settings", "", cookie, "1.2.3.4")
    assert response.status == 303
    assert response.location == "/login"


def test_a_callback_without_a_session_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    response = world.app.get("/callback", "code=c&state=s", "", "1.2.3.4")
    assert response.status == 403


def test_a_callback_without_a_code_refuses(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    response = world.app.get("/callback", f"state={state}", cookie, "1.2.3.4")
    assert response.status == 400


def test_a_failed_exchange_refuses_without_creating_a_session(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    world.github.exchange_status = 500
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    response = world.app.get(
        "/callback", f"code=fake-code&state={state}", cookie, "1.2.3.4"
    )
    assert response.status == 502
    assert LOGIN_FAILED in response.body.decode()


def test_a_non_admin_is_refused_at_login(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.account = {"id": 5, "login": ORG_ACCOUNT_LOGIN, "type": "Organization"}
    world.github.user = {"id": ADMIN_ID, "login": ADMIN_LOGIN}
    world.github.membership = {"role": "member", "state": "active"}
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    response = world.app.get(
        "/callback", f"code=fake-code&state={state}", cookie, "1.2.3.4"
    )
    assert response.status == 403
    assert ADMIN_REFUSED in response.body.decode()


def test_a_non_allowlisted_installation_is_refused_at_login(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    world.github.repos = [OTHER_REPO]
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    response = world.app.get(
        "/callback", f"code=fake-code&state={state}", cookie, "1.2.3.4"
    )
    assert response.status == 403
    assert GATE_REFUSED in response.body.decode()


def test_a_github_read_failure_at_login_refuses_fail_closed(tmp_path: Path) -> None:
    """A GitHub read that fails mid-sign-in (here: the identity read)
    refuses the login with a fixed phrase and creates no session."""
    world = build_world(tmp_path)
    world.github.api_error = TimeoutError("timed out")
    started = world.app.get("/login", "", "", "1.2.3.4")
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    response = world.app.get(
        "/callback", f"code=fake-code&state={state}", cookie, "1.2.3.4"
    )
    assert response.status == 502
    assert LOGIN_FAILED in response.body.decode()
    assert world.app.get("/settings", "", cookie, "1.2.3.4").location == "/login"


# ---- the settings page ----------------------------------------------


def test_the_settings_page_shows_the_state_without_the_key(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    page = world.page_text()
    assert "A key is stored" in page
    # The key is write-only: it never appears again, not even partly.
    assert FAKE_KEY not in page
    assert GOOD_ENDPOINT in page
    assert GOOD_MODEL in page
    assert "Credentials last saved" in page


def test_the_settings_page_shows_an_unset_installation(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    page = world.page_text()
    assert "No key is stored" in page
    assert "none set" in page


def test_the_page_carries_the_consent_statement_verbatim(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    assert CONSENT_STATEMENT in world.page_text()


def test_an_org_admin_sees_the_org_account(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world, org=True)
    page = world.page_text()
    assert ORG_ACCOUNT_LOGIN in page
    assert "Organization" in page


def test_an_unknown_action_is_a_not_found(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    response = world.app.post(
        "/settings/whatever", {"csrf": world.csrf()}, world.cookie, "1.2.3.4"
    )
    assert response.status == 404


def test_a_post_outside_the_settings_scope_is_a_not_found(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    response = world.app.post(
        "/settings/a/b", {"csrf": world.csrf()}, world.cookie, "1.2.3.4"
    )
    assert response.status == 404


# ---- consent --------------------------------------------------------


def test_saving_credentials_without_consent_stores_nothing(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    response = world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    assert response.status == 403
    assert CONSENT_REFUSED in response.body.decode()
    assert world.app.store.load("42") is None


def test_the_consent_checkbox_is_required(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    response = world.app.post(
        "/settings/consent", {"csrf": world.csrf()}, world.cookie, "1.2.3.4"
    )
    assert response.status == 400
    assert CONSENT_UNCHECKED in response.body.decode()
    assert world.app.store.load("42") is None


def test_consent_is_recorded_before_credentials_are_usable(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    consented = world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    assert consented.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.consent_acknowledged_at is not None
    assert record.consent_acknowledged_at == world.clock.now()
    # The page shows the acknowledgement.
    assert "Consent acknowledged at" in world.page_text()


# ---- credentials -----------------------------------------------------


def test_credentials_save_end_to_end(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    saved = world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    assert saved.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.base_url == GOOD_ENDPOINT
    assert record.model == GOOD_MODEL
    assert record.has_credentials
    # The audit line carries the write without any value.
    entries = world.app.audit.entries("42", "store-credentials")
    assert len(entries) == 1
    assert json.dumps(FAKE_KEY) not in json.dumps(entries)
    assert entries[0]["github_user_id"] == ADMIN_ID


def test_a_store_failure_names_itself_and_changes_nothing(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    # The CSRF token was captured while the store still answered.
    csrf = world.csrf()
    # Break the store the way a missing key breaks it: a fresh store
    # over the same directory without the key.
    broken = InstallationStore.open(world.state_dir, {})
    assert not broken.configured
    world.app.store = broken
    response = world.app.post(
        "/settings/credentials",
        {
            "csrf": csrf,
            "base_url": GOOD_ENDPOINT,
            "key": FAKE_KEY,
            "model": GOOD_MODEL,
        },
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 503
    assert "the installation store refused the change" in response.body.decode()
    # The consent record stands; the refused credentials stored nothing.
    working = InstallationStore.open(
        world.state_dir, {"ATLAS_INSTALLATION_STORE_KEY": world.store_key}
    )
    record = working.load("42")
    assert record is not None
    assert not record.has_credentials


# ---- the endpoint and model intake checks ---------------------------


def test_hostile_endpoints_are_refused_by_the_real_egress_check(
    tmp_path: Path,
) -> None:
    """The intake validation runs the real egress guard here: no fake
    resolver stands in for it in this test, and no network is needed —
    every hostile host refuses before any connection."""
    world = build_world(tmp_path, resolve=None)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    # The non-https and userinfo shapes are refused by the URL-level
    # half, deterministically, in test_checks (a resolver that would
    # allow anything still refuses them); this flow pins the
    # address-level half against hosts that resolve without a network.
    for endpoint in (
        "https://127.0.0.1:8080/v1",  # loopback
        "https://localhost:9/v1",  # loopback by name
        "https://169.254.169.254/latest",  # the metadata service
        "https://[::1]:8443/v1",  # IPv6 loopback
    ):
        response = world.app.post(
            "/settings/credentials",
            _credentials_form(world, endpoint=endpoint),
            world.cookie,
            "1.2.3.4",
        )
        assert response.status == 400, (endpoint, response.status)
        assert "the endpoint was refused" in response.body.decode()
        record = world.app.store.load("42")
        assert record is None or not record.has_credentials


def test_an_allowlisted_shape_endpoint_passes_the_guard(tmp_path: Path) -> None:
    """The injected resolver answers for the public host, and the save
    succeeds — the guard's refusal is the only thing a fake can do, so
    the pass-through is the real guard's decision shape under a public
    resolution."""
    world = build_world(tmp_path, resolve=default_resolve)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    saved = world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    assert saved.status == 303


def test_an_unknown_model_is_refused(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    response = world.app.post(
        "/settings/credentials",
        _credentials_form(world, model=UNKNOWN_MODEL),
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 400
    assert "the model was refused" in response.body.decode()
    record = world.app.store.load("42")
    assert record is None or not record.has_credentials


def test_a_zero_priced_model_is_allowed(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    saved = world.app.post(
        "/settings/credentials",
        _credentials_form(world, model=ZERO_MODEL),
        world.cookie,
        "1.2.3.4",
    )
    assert saved.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.model == ZERO_MODEL


def test_a_price_table_read_failure_refuses_the_model(tmp_path: Path) -> None:
    def broken_table(model: str) -> tuple[Decimal, Decimal]:
        raise PricingUnknownError(
            "the operator's price table could not be read for this model"
        )

    world = build_world(tmp_path, validate_model=broken_table)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    response = world.app.post(
        "/settings/credentials", _credentials_form(world), world.cookie, "1.2.3.4"
    )
    assert response.status == 400
    assert "the model was refused" in response.body.decode()


# ---- rate limits -----------------------------------------------------


def test_sign_in_is_rate_limited_per_ip(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    for _ in range(LOGIN_LIMIT):
        world.app.get("/login", "", "", "9.9.9.9")
    limited = world.app.get("/login", "", "", "9.9.9.9")
    assert limited.status == 429
    # A different IP still gets through.
    assert world.app.get("/login", "", "", "8.8.8.8").status == 302


def test_a_refused_credentials_submit_refills_the_typed_fields(
    tmp_path: Path,
) -> None:
    """The refusal render carries the endpoint and model the admin typed
    (escaped into the value attributes), so only the key is re-typed;
    the key itself is never echoed back (kills the blank-form mutant)."""
    world = build_world(tmp_path)
    sign_in(world)
    world.app.post(
        "/settings/consent",
        {"csrf": world.csrf(), "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    csrf = world.csrf()
    response = world.app.post(
        "/settings/credentials",
        {
            "csrf": csrf,
            "base_url": "https://api.example.com/v1",
            "key": FAKE_KEY,
            "model": UNKNOWN_MODEL,
        },
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 400
    body = response.body.decode()
    assert 'value="https://api.example.com/v1"' in body
    assert 'value="vendor/not-in-the-table"' in body
    assert FAKE_KEY not in body
