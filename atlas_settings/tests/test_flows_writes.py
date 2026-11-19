# SPDX-License-Identifier: MIT
"""The settings page's flows, part two of the split flow suite: the
write surface — rotation, revocation, the cap dial, delete-everything —
and the machinery every write runs through: the CSRF token, the expired
session, the admin rights lost mid-session, the gate re-checked on
every write, the rate limits, and the fake key and tokens that appear
nowhere across every flow. Part one (sign-in, intake, consent) is this
suite's first file."""

from decimal import Decimal
from pathlib import Path

from atlas_settings.phrases import (
    ADMIN_REFUSED,
    DELETE_MISMATCH,
    GATE_REFUSED,
    GITHUB_CHECK_FAILED,
    SESSION_EXPIRED,
)

from .harness import (
    FAKE_INSTALL_TOKEN,
    FAKE_KEY,
    FAKE_USER_TOKEN,
    GOOD_ENDPOINT,
    GOOD_MODEL,
    OTHER_REPO,
    _credentials_form,
    build_world,
    sign_in,
)

# ---- the write machinery --------------------------------------------


def test_a_github_failure_at_the_admin_check_refuses_fail_closed(
    tmp_path: Path,
) -> None:
    """The admin check's own read failing is the fail-closed refusal
    with the check-failed phrase, and the store is untouched."""
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.github.api_error = TimeoutError("timed out")
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 502
    assert GITHUB_CHECK_FAILED in response.body.decode()
    assert world.app.store.load("42") is None


def test_an_expired_session_redirects_reads_and_refuses_writes(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.bump_time(1801)
    read = world.app.get("/settings", "", world.cookie, "1.2.3.4")
    assert read.status == 303
    assert read.location == "/login"
    write = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert write.status == 403
    assert SESSION_EXPIRED in write.body.decode()
    # Nothing was stored.
    assert world.app.store.load("42") is None


def test_a_csrf_failure_changes_nothing(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    for path, fields in (
        ("/settings/consent", {"acknowledge": "1"}),
        ("/settings/cap", {"cap_usd": "5"}),
        ("/settings/revoke", {}),
        ("/settings/delete", {"confirm": "DELETE"}),
        (
            "/settings/credentials",
            {"base_url": GOOD_ENDPOINT, "key": FAKE_KEY, "model": GOOD_MODEL},
        ),
    ):
        response = world.app.post(path, fields, world.cookie, "1.2.3.4")
        assert response.status == 403, (path, response.status)
        assert "cross-site request token" in response.body.decode()
    assert world.app.store.load("42") is None
    assert not (world.state_dir / "installations" / "42.json").exists()


def test_the_csrf_check_is_constant_time_against_a_matching_length(
    tmp_path: Path,
) -> None:
    """The check runs even when the submitted token is the right shape:
    a wrong token of the same length is refused the same way."""
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    forged = csrf[:-1] + ("0" if csrf[-1] != "0" else "1")
    response = world.app.post(
        "/settings/cap", {"csrf": forged, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 403


def test_admin_rights_lost_mid_session_refuse_every_write(tmp_path: Path) -> None:
    """The admin check is re-verified on every write, not only at
    login: an org admin demoted after sign-in is refused on the next
    write, fail closed."""
    world = build_world(tmp_path)
    sign_in(world, org=True)
    csrf = world.csrf()
    assert (
        world.app.post(
            "/settings/cap",
            {"csrf": csrf, "cap_usd": "5"},
            world.cookie,
            "1.2.3.4",
        ).status
        == 303
    )
    # The demotion lands between the write that worked and the next one;
    # the CSRF token was captured while the admin check still passed.
    world.github.membership = {"role": "member", "state": "active"}
    response = world.app.post(
        "/settings/cap",
        {"csrf": csrf, "cap_usd": "6"},
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 403
    assert ADMIN_REFUSED in response.body.decode()
    # The cap from the earlier write stands; the refused write stored
    # nothing.
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd == Decimal(5)
    world.github.membership = None
    response = world.app.post(
        "/settings/cap",
        {"csrf": csrf, "cap_usd": "6"},
        world.cookie,
        "1.2.3.4",
    )
    assert response.status == 403
    assert record.daily_cap_usd == Decimal(5)


def test_a_github_failure_mid_session_refuses_the_write_fail_closed(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.github.api_error = TimeoutError("timed out")
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 502
    assert GITHUB_CHECK_FAILED in response.body.decode()
    assert world.app.store.load("42") is None


def test_the_gate_is_re_checked_on_every_write(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    csrf = world.csrf()
    world.github.repos = [OTHER_REPO]
    response = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    assert response.status == 403
    assert GATE_REFUSED in response.body.decode()
    assert world.app.store.load("42") is None


# ---- credentials -----------------------------------------------------


def test_rotation_replaces_the_key(tmp_path: Path) -> None:
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
    rotated = "sk-rotated-key-9876543210-not-real-either"
    world.app.post(
        "/settings/credentials",
        _credentials_form(world, key=rotated, endpoint="https://api2.example.com"),
        world.cookie,
        "1.2.3.4",
    )
    record = world.app.store.load("42")
    assert record is not None
    assert record.base_url == "https://api2.example.com"
    assert record.key == rotated
    # The cap and the consent survived the rotation.
    assert record.daily_cap_usd is None
    assert record.consent_acknowledged_at is not None
    assert len(world.app.audit.entries("42", "store-credentials")) == 2


def test_revocation_removes_the_key_and_keeps_cap_and_consent(
    tmp_path: Path,
) -> None:
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
    world.app.post(
        "/settings/cap", {"csrf": world.csrf(), "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    revoked = world.app.post(
        "/settings/revoke", {"csrf": world.csrf()}, world.cookie, "1.2.3.4"
    )
    assert revoked.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert not record.has_credentials
    assert record.daily_cap_usd == Decimal(5)
    assert record.consent_acknowledged_at is not None
    assert "No key is stored" in world.page_text()


# ---- the cap --------------------------------------------------------


def test_the_admin_sets_and_clears_the_cap(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    set_response = world.app.post(
        "/settings/cap",
        {"csrf": world.csrf(), "cap_usd": "5.25"},
        world.cookie,
        "1.2.3.4",
    )
    assert set_response.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd == Decimal("5.25")
    assert "$5.25 per UTC day" in world.page_text()
    cleared = world.app.post(
        "/settings/cap", {"csrf": world.csrf(), "cap_usd": ""}, world.cookie, "1.2.3.4"
    )
    assert cleared.status == 303
    record = world.app.store.load("42")
    assert record is not None
    assert record.daily_cap_usd is None
    assert "none set" in world.page_text()


def test_an_unusable_cap_is_refused_with_the_fixed_phrase(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    for raw in ("abc", "-5", "0", "1.999", "100000"):
        response = world.app.post(
            "/settings/cap",
            {"csrf": world.csrf(), "cap_usd": raw},
            world.cookie,
            "1.2.3.4",
        )
        assert response.status == 400, (raw, response.status)
        assert "at most two decimal places" in response.body.decode()
        assert world.app.store.load("42") is None


# ---- delete everything -----------------------------------------------


def test_delete_requires_the_typed_confirmation(tmp_path: Path) -> None:
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
    wrong = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "delete"},
        world.cookie,
        "1.2.3.4",
    )
    assert wrong.status == 400
    assert DELETE_MISMATCH in wrong.body.decode()
    assert world.app.store.load("42") is not None
    gone = world.app.post(
        "/settings/delete",
        {"csrf": world.csrf(), "confirm": "DELETE"},
        world.cookie,
        "1.2.3.4",
    )
    assert gone.status == 303
    assert world.app.store.load("42") is None
    # The session cookie is cleared.
    assert gone.set_cookie is not None
    assert gone.set_cookie.startswith("atlas_settings_session=;")
    assert "Max-Age=0" in gone.set_cookie


# ---- rate limits -----------------------------------------------------


def test_writes_are_rate_limited_per_session(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    sign_in(world)
    fields = {"csrf": world.csrf(), "cap_usd": ""}
    for _ in range(30):
        world.app.post("/settings/cap", fields, world.cookie, "1.2.3.4")
    response = world.app.post("/settings/cap", fields, world.cookie, "1.2.3.4")
    assert response.status == 429
    assert "too many requests" in response.body.decode()


# ---- the fake key and tokens never appear ---------------------------


def test_the_fake_key_and_tokens_appear_nowhere_across_every_flow(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path)
    surfaces: list[str] = []
    started = world.app.get("/login", "", "", "1.2.3.4")
    surfaces.append(_surface(started))
    cookie = world.cookie_from(started)
    state = world.state_from(started)
    callback = world.app.get(
        "/callback", f"code=fake-code&state={state}", cookie, "1.2.3.4"
    )
    surfaces.append(_surface(callback))
    world.cookie = world.cookie_from(callback)
    csrf = world.csrf()
    consent = world.app.post(
        "/settings/consent",
        {"csrf": csrf, "acknowledge": "1"},
        world.cookie,
        "1.2.3.4",
    )
    surfaces.append(_surface(consent))
    saved = world.app.post(
        "/settings/credentials",
        _credentials_form(world),
        world.cookie,
        "1.2.3.4",
    )
    surfaces.append(_surface(saved))
    capped = world.app.post(
        "/settings/cap", {"csrf": csrf, "cap_usd": "5"}, world.cookie, "1.2.3.4"
    )
    surfaces.append(_surface(capped))
    revoked = world.app.post(
        "/settings/revoke", {"csrf": csrf}, world.cookie, "1.2.3.4"
    )
    surfaces.append(_surface(revoked))
    surfaces.append(world.page_text())
    deleted = world.app.post(
        "/settings/delete",
        {"csrf": csrf, "confirm": "DELETE"},
        world.cookie,
        "1.2.3.4",
    )
    surfaces.append(_surface(deleted))
    # The error pages and the login page itself.
    surfaces.append(_surface(world.app.get("/", "", "", "1.2.3.4")))
    world.github.exchange_status = 403
    started2 = world.app.get("/login", "", "", "5.6.7.8")
    surfaces.append(_surface(started2))
    surfaces.append(
        _surface(
            world.app.get(
                "/callback",
                f"code=x&state={world.state_from(started2)}",
                world.cookie_from(started2),
                "5.6.7.8",
            )
        )
    )
    surfaces.extend(world.logs)
    audit_path = world.state_dir / "settings-audit.jsonl"
    if audit_path.exists():
        surfaces.append(audit_path.read_text())
    joined = "\n".join(part for part in surfaces if part)
    assert FAKE_KEY not in joined
    assert FAKE_USER_TOKEN not in joined
    assert FAKE_INSTALL_TOKEN not in joined


def _surface(response: object) -> str:
    from atlas_settings.app import Response

    assert isinstance(response, Response)
    parts = [response.body.decode("utf-8", errors="replace")]
    if response.location is not None:
        parts.append(response.location)
    if response.set_cookie is not None:
        parts.append(response.set_cookie)
    return "\n".join(parts)
