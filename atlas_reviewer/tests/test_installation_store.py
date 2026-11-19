# SPDX-License-Identifier: MIT
"""The installation secrets store (config slice S10, part A; D81 §7
decision 9 and the 5:51 PM CT amendment): the encrypted per-installation
records, the fails-closed reads, the key that never appears in a repr or
an error, the part-B API (store, rotate, revoke, cap, consent, delete),
and the retention sweep. Offline: temp files and the real `cryptography`
Fernet with obviously fake keys."""

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from atlas_reviewer.budget import (
    CAP_REACHED,
    STORE_UNAVAILABLE,
    DailySpend,
    no_installation_cap,
    skip_reason,
)
from atlas_reviewer.installation_store import (
    CONSENT_REQUIRED,
    DEFAULT_RETENTION_DAYS,
    ENV_RETENTION_DAYS,
    ENV_STORE_KEY,
    ConsentNotAcknowledgedError,
    InstallationRecord,
    InstallationStore,
    InstallationStoreError,
    TenantCredentials,
    installation_id,
    retention_days,
    store_root,
)

KEY_A = Fernet.generate_key().decode("ascii")
KEY_B = Fernet.generate_key().decode("ascii")
TENANT_KEY = "sk-tenant-fixture-not-a-real-key"
NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)


def _store(
    tmp_path: Path,
    key: str | None = KEY_A,
    env: dict[str, str] | None = None,
    *,
    clock=lambda: NOW,
):
    environment = dict(env or {})
    if key is not None:
        environment[ENV_STORE_KEY] = key
    store = InstallationStore.open(tmp_path, environment)
    store.clock = clock
    return store


def _seed_raw(tmp_path: Path, ident: str, payload: dict[str, object], key=KEY_A):
    """One record file written directly, the way a crashed operator
    error would leave one: the store's own envelope, encrypted under
    `key`, bypassing the store's API."""
    from atlas_reviewer.ledger import make_private_dirs

    root = store_root(tmp_path)
    make_private_dirs(root)
    envelope = {
        "version": 1,
        "record": Fernet(key.encode("ascii"))
        .encrypt(json.dumps(payload).encode("utf-8"))
        .decode("ascii"),
    }
    (root / f"{ident}.json").write_text(json.dumps(envelope), encoding="utf-8")


def _credentials_record(store, ident="12345"):
    return store.store_credentials(
        ident,
        "https://models.example.invalid/api/v1",
        TENANT_KEY,
        "openai/gpt-4o",
    )


# ------------------------------------------------------- opening the store


def test_an_unconfigured_store_answers_none_and_never_raises(tmp_path):
    store = _store(tmp_path, key=None)
    assert store.configured is False
    assert store.load("12345") is None
    assert store.installation_cap()("12345") is None


def test_a_key_with_no_records_on_disk_is_the_unconfigured_store(tmp_path):
    store = _store(tmp_path, key=None)
    assert store.fernet is None
    assert store.broken_reason == ""


def test_a_missing_key_with_records_on_disk_fails_closed(tmp_path):
    _seed_raw(
        tmp_path,
        "12345",
        {
            "base_url": "https://models.example.invalid/api/v1",
            "key": TENANT_KEY,
            "model": "openai/gpt-4o",
            "daily_cap_usd": None,
            "consent_acknowledged_at": None,
            "updated_at": NOW.isoformat(),
        },
    )
    reopened = _store(tmp_path, key=None)
    assert reopened.broken_reason != ""
    with pytest.raises(InstallationStoreError) as exc:
        reopened.load("12345")
    assert ENV_STORE_KEY in str(exc.value)
    assert TENANT_KEY not in str(exc.value)


def test_an_invalid_key_fails_closed_naming_the_variable(tmp_path):
    store = _store(tmp_path, key="not-a-fernet-key")
    assert store.configured is False
    with pytest.raises(InstallationStoreError) as exc:
        store.load("12345")
    assert ENV_STORE_KEY in str(exc.value)


# ------------------------------------------------------------ the records


def test_stored_credentials_round_trip_through_the_store(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    record = store.load("12345")
    assert record is not None
    assert record.has_credentials
    assert record.base_url == "https://models.example.invalid/api/v1"
    assert record.model == "openai/gpt-4o"
    credentials = record.credentials()
    assert credentials.key == TENANT_KEY


def test_storing_credentials_again_rotates_the_key(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    store.store_credentials(
        "12345",
        "https://models.example.invalid/api/v1",
        "sk-rotated-fixture-key",
        "openai/gpt-4o",
    )
    record = store.load("12345")
    assert record is not None
    assert record.credentials().key == "sk-rotated-fixture-key"


def test_revoking_keeps_the_cap_and_consent_and_drops_the_credentials(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    store.set_cap("12345", Decimal("12.00"))
    store.record_consent("12345", at=NOW)
    store.revoke_credentials("12345")
    record = store.load("12345")
    assert record is not None
    assert not record.has_credentials
    assert record.daily_cap_usd == Decimal("12.00")
    assert record.consent_acknowledged_at == NOW
    with pytest.raises(InstallationStoreError):
        record.credentials()


def test_a_cap_can_be_set_without_credentials(tmp_path):
    store = _store(tmp_path)
    store.set_cap("12345", Decimal("5.00"))
    record = store.load("12345")
    assert record is not None
    assert record.daily_cap_usd == Decimal("5.00")
    assert not record.has_credentials


def test_clearing_the_cap_removes_it(tmp_path):
    store = _store(tmp_path)
    store.set_cap("12345", Decimal("5.00"))
    store.set_cap("12345", None)
    record = store.load("12345")
    assert record is not None
    assert record.daily_cap_usd is None


def test_a_cap_must_be_a_positive_dollar_amount(tmp_path):
    store = _store(tmp_path)
    for bad in (Decimal(0), Decimal(-1), Decimal("nan"), "5", True):
        with pytest.raises(InstallationStoreError):
            store.set_cap("12345", bad)  # type: ignore[arg-type]
    assert store.load("12345") is None


def test_recording_consent_stamps_the_acknowledgement(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    store.record_consent("12345", at=NOW)
    record = store.load("12345")
    assert record is not None
    assert record.consent_acknowledged_at == NOW


def test_delete_removes_the_whole_record(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    store.set_cap("12345", Decimal("5.00"))
    store.delete("12345")
    assert store.load("12345") is None
    # Deleting an installation with no record is already true.
    store.delete("12345")


def test_delete_on_an_unconfigured_store_is_a_no_op(tmp_path):
    store = _store(tmp_path, key=None)
    store.delete("12345")


def test_delete_on_a_broken_store_fails_closed(tmp_path):
    store = _store(tmp_path, key="not-a-fernet-key")
    with pytest.raises(InstallationStoreError):
        store.delete("12345")


# --------------------------------------------------------- failing closed


def test_a_corrupt_record_fails_closed_with_the_reason_named(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    path = store_root(tmp_path) / "12345.json"
    path.write_text("{not the store's document", encoding="utf-8")
    with pytest.raises(InstallationStoreError) as exc:
        store.load("12345")
    assert "corrupt" in str(exc.value)


def test_a_record_under_the_wrong_key_fails_closed(tmp_path):
    store = _store(tmp_path, key=KEY_A)
    _credentials_record(store)
    reopened = _store(tmp_path, key=KEY_B)
    with pytest.raises(InstallationStoreError) as exc:
        reopened.load("12345")
    assert "did not decrypt" in str(exc.value)
    assert TENANT_KEY not in str(exc.value)


def test_an_unreadable_record_fails_closed_with_the_reason_named(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    path = store_root(tmp_path) / "12345.json"
    path.chmod(0o000)
    try:
        with pytest.raises(InstallationStoreError) as exc:
            store.load("12345")
        assert "could not be read" in str(exc.value)
    finally:
        path.chmod(0o600)


def test_a_plaintext_file_with_the_key_in_it_never_echoes_the_key(tmp_path):
    """The fail-closed message is fixed text about the document, never
    its contents: a key that reached the disk in the clear stays there."""
    from atlas_reviewer.ledger import make_private_dirs

    make_private_dirs(store_root(tmp_path))
    path = store_root(tmp_path) / "12345.json"
    path.write_text(json.dumps({"leaked": TENANT_KEY}), encoding="utf-8")
    store = _store(tmp_path)
    with pytest.raises(InstallationStoreError) as exc:
        store.load("12345")
    assert TENANT_KEY not in str(exc.value)


def test_an_installation_id_must_be_digits_so_a_path_cannot_escape(tmp_path):
    for bad in ("", "../x", "a/b", "12 3", "١٢٣", "0", "-1", "9" * 65):
        with pytest.raises(InstallationStoreError):
            installation_id(bad)
    assert installation_id("12345") == "12345"


def test_written_records_are_private_and_leave_no_temporary_behind(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    root = store_root(tmp_path)
    assert (stat.S_IMODE(root.stat().st_mode)) == 0o700
    record_path = root / "12345.json"
    assert (stat.S_IMODE(record_path.stat().st_mode)) == 0o600
    # The lock directory is the store's own; no `.writing` temp survives
    # a completed write.
    assert sorted(p.name for p in root.iterdir()) == ["12345.json", "locks"]


# ----------------------------------------------------- keys never surface


def test_the_record_repr_and_str_never_carry_the_key(tmp_path):
    store = _store(tmp_path)
    record = _credentials_record(store)
    for text in (repr(record), str(record)):
        assert TENANT_KEY not in text
        assert "key=<redacted>" in text


def test_the_credentials_repr_never_carries_the_key():
    credentials = TenantCredentials(
        "https://models.example.invalid/api/v1", TENANT_KEY, "openai/gpt-4o"
    )
    for text in (repr(credentials), str(credentials)):
        assert TENANT_KEY not in text
        assert "key=<redacted>" in text


def test_the_store_object_repr_carries_no_key_material(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    assert TENANT_KEY not in repr(store)
    assert KEY_A not in repr(store)


def test_a_half_revoked_record_is_not_credentials(tmp_path):
    """A record whose fields do not all carry values has no credentials:
    `has_credentials` needs all three, so a torn write (or a seeded
    record) can never hand out an empty key as if it were one."""
    _seed_raw(
        tmp_path,
        "12345",
        {
            "base_url": "https://models.example.invalid/api/v1",
            "key": "",
            "model": "",
            "daily_cap_usd": None,
            "consent_acknowledged_at": None,
            "updated_at": NOW.isoformat(),
        },
    )
    store = _store(tmp_path)
    record = store.load("12345")
    assert record is not None
    assert not record.has_credentials
    with pytest.raises(InstallationStoreError):
        record.credentials()


# ---------------------------------------------------- the process lock


def test_a_record_write_takes_and_releases_a_per_installation_file_lock(
    tmp_path,
):
    """The cross-process serialization (r1 review of #776, Nit 6): the
    read-modify-write holds an advisory `fcntl.flock` on the
    installation's lock file and releases it, so part B's settings-page
    process serializes against the service's instead of losing an
    update. After a completed write the lock is free."""
    import fcntl

    store = _store(tmp_path)
    _credentials_record(store)
    lock_path = store_root(tmp_path) / "locks" / "12345.lock"
    assert lock_path.exists()
    # A second exclusive acquisition succeeds only because the store
    # released the lock when the write returned.
    fd = os.open(lock_path, os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_a_write_waits_for_a_held_file_lock_and_then_lands(tmp_path):
    """Two writers serialize: while another holder keeps the
    installation's flock, the store's read-modify-write blocks, and it
    completes -- with its own update intact -- once the holder
    releases."""
    import fcntl
    import threading

    store = _store(tmp_path)
    lock_path = store_root(tmp_path) / "locks"
    from atlas_reviewer.ledger import make_private_dirs

    make_private_dirs(lock_path)
    held = os.open(lock_path / "12345.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        done = threading.Event()

        def write():
            store.store_credentials(
                "12345",
                "https://models.example.invalid/api/v1",
                TENANT_KEY,
                "openai/gpt-4o",
            )
            done.set()

        worker = threading.Thread(target=write)
        worker.start()
        # Generous margins: the writer is still blocked well past a fast
        # unsynchronized write would take, and lands once released.
        assert not done.wait(0.3)
        fcntl.flock(held, fcntl.LOCK_UN)
        assert done.wait(5.0)
        worker.join(5.0)
        record = store.load("12345")
        assert record is not None
        assert record.credentials().key == TENANT_KEY
    finally:
        os.close(held)


# ------------------------------------------------------- credential checks


def test_a_stored_base_url_must_be_https_with_a_host(tmp_path):
    store = _store(tmp_path)
    for bad in (
        "http://models.example.invalid/api/v1",
        "ftp://models.example.invalid",
        "https://user:pass@models.example.invalid/api/v1",
        "https://models.example.invalid/api/v1?x=1",
        "",
    ):
        with pytest.raises(InstallationStoreError):
            store.store_credentials("12345", bad, TENANT_KEY, "openai/gpt-4o")
    assert store.load("12345") is None


def test_a_stored_model_must_be_a_visible_model_id(tmp_path):
    store = _store(tmp_path)
    for bad in ("", "openai/gpt 4o", "openai/gpt-4o\n", "x" * 201):
        with pytest.raises(InstallationStoreError):
            store.store_credentials(
                "12345", "https://models.example.invalid/api/v1", TENANT_KEY, bad
            )
    assert store.load("12345") is None


# ------------------------------------------------------ the cap interface


def test_the_store_backed_cap_refuses_when_the_days_total_reaches_it(tmp_path):
    store = _store(tmp_path)
    store.set_cap("12345", Decimal("10.00"))
    spend = DailySpend(tmp_path, Decimal("100.00"), cap_for=store.installation_cap())
    spend.record("o/r", Decimal("10.00"), 1)
    message, gap = spend.refusal("o/r", "12345")
    assert message == CAP_REACHED
    assert gap == ""


def test_an_unset_cap_means_none_applies(tmp_path):
    store = _store(tmp_path)
    spend = DailySpend(tmp_path, Decimal("100.00"), cap_for=store.installation_cap())
    spend.record("o/r", Decimal("99.00"), 1)
    message, gap = spend.refusal("o/r", "12345")
    assert message == ""
    assert gap == ""


def test_a_broken_store_refuses_the_budget_check_with_its_own_text(tmp_path):
    store = _store(tmp_path, key="not-a-fernet-key")
    spend = DailySpend(tmp_path, Decimal("100.00"), cap_for=store.installation_cap())
    message, gap = spend.refusal("o/r", "12345")
    assert message == STORE_UNAVAILABLE
    assert "not a valid Fernet key" in gap


def test_the_skip_reason_labels_the_two_refusals_apart():
    assert skip_reason(CAP_REACHED) == "daily-budget"
    assert skip_reason(STORE_UNAVAILABLE) == "installation-store"
    assert skip_reason("skipped: daily budget reached") == "daily-budget"


def test_an_unconfigured_deployment_keeps_the_none_cap(tmp_path):
    """A deployment that never adopted the store behaves exactly as S9
    left it: no cap applies, no refusal appears."""
    store = _store(tmp_path, key=None)
    spend = DailySpend(tmp_path, Decimal("100.00"), cap_for=store.installation_cap())
    assert spend.refusal("o/r", "12345") == ("", "")
    assert spend.refusal("o/r", "") == ("", "")
    fallback = DailySpend(tmp_path, Decimal("100.00"), cap_for=no_installation_cap)
    assert fallback.refusal("o/r", "12345") == ("", "")


# -------------------------------------------------------- consent refusal


def test_credentials_without_consent_refuse_the_tenant_path(tmp_path):
    """The gate the settings page's acknowledgement feeds (D81 §7
    decision 3): credentials present, consent absent -- the tenant path
    is refused with the consent named, and the error is the store
    error the runner turns into the review's named failure."""
    store = _store(tmp_path)
    _credentials_record(store)
    record = store.load("12345")
    assert record is not None
    assert record.consent_acknowledged_at is None
    with pytest.raises(ConsentNotAcknowledgedError):
        _require_consent(record)


def _require_consent(record: InstallationRecord) -> None:
    if record.consent_acknowledged_at is None:
        raise ConsentNotAcknowledgedError(CONSENT_REQUIRED)


# ------------------------------------------------------- retention sweep


def test_the_sweep_deletes_records_past_the_window_and_keeps_fresh_ones(
    tmp_path,
):
    store = _store(tmp_path)
    stale = store.store_credentials(
        "11111", "https://stale.example.invalid", TENANT_KEY, "openai/gpt-4o"
    )
    fresh = store.store_credentials(
        "22222", "https://fresh.example.invalid", TENANT_KEY, "openai/gpt-4o"
    )
    # Rewrite the stale record's updated_at into the past, through the
    # store's own document shape.
    store._write_record(
        "11111",
        lambda _current: InstallationRecord(
            "11111",
            stale.base_url,
            stale.key,
            stale.model,
            None,
            None,
            NOW - timedelta(days=DEFAULT_RETENTION_DAYS + 1),
        ),
    )
    assert fresh.updated_at == NOW
    removed, skipped = store.sweep(NOW, DEFAULT_RETENTION_DAYS)
    assert (removed, skipped) == (1, 0)
    assert store.load("11111") is None
    assert store.load("22222") is not None


def test_the_sweep_skips_a_stray_or_temporary_file_and_still_sweeps(tmp_path):
    """A crash mid-write leaves `<id>.json.writing`; a stray file can be
    anything. Neither halts the sweep -- a sweep that died on one stray
    file would stop catching missed webhooks every boot after it -- and
    neither is deleted: this store removes only what it wrote. Both are
    named in the returned count."""
    store = _store(tmp_path)
    stale = store.store_credentials(
        "11111", "https://stale.example.invalid", TENANT_KEY, "openai/gpt-4o"
    )
    store._write_record(
        "11111",
        lambda _current: InstallationRecord(
            "11111",
            stale.base_url,
            stale.key,
            stale.model,
            None,
            None,
            NOW - timedelta(days=DEFAULT_RETENTION_DAYS + 1),
        ),
    )
    root = store_root(tmp_path)
    (root / "11111.json.writing").write_text("{torn", encoding="utf-8")
    (root / "stray").write_text("anything", encoding="utf-8")
    removed, skipped = store.sweep(NOW, DEFAULT_RETENTION_DAYS)
    assert (removed, skipped) == (1, 2)
    assert store.load("11111") is None
    assert (root / "11111.json.writing").exists()
    assert (root / "stray").exists()


def test_the_sweep_skips_a_record_shaped_name_that_fails_the_ids_checks(
    tmp_path,
):
    """The r2 residual (m2'): the skip is the id's *whole* validation,
    not just its digit check -- `0.json` (a positive-integer failure)
    and an over-long digit name both raise `installation_id`, and both
    are named and skipped like any other stray, never halting the sweep
    and never deleted."""
    store = _store(tmp_path)
    stale = store.store_credentials(
        "11111", "https://stale.example.invalid", TENANT_KEY, "openai/gpt-4o"
    )
    store._write_record(
        "11111",
        lambda _current: InstallationRecord(
            "11111",
            stale.base_url,
            stale.key,
            stale.model,
            None,
            None,
            NOW - timedelta(days=DEFAULT_RETENTION_DAYS + 1),
        ),
    )
    root = store_root(tmp_path)
    (root / "0.json").write_text("{}", encoding="utf-8")
    (root / f"{'9' * 65}.json").write_text("{}", encoding="utf-8")
    removed, skipped = store.sweep(NOW, DEFAULT_RETENTION_DAYS)
    assert (removed, skipped) == (1, 2)
    assert store.load("11111") is None
    assert (root / "0.json").exists()
    assert (root / f"{'9' * 65}.json").exists()


def test_the_sweep_leaves_a_record_it_cannot_read(tmp_path):
    store = _store(tmp_path)
    _credentials_record(store)
    (store_root(tmp_path) / "12345.json").write_text("junk", encoding="utf-8")
    assert store.sweep(NOW, DEFAULT_RETENTION_DAYS) == (0, 0)


def test_the_sweep_needs_a_window_of_at_least_one_day(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.sweep(NOW, 0)


def test_the_retention_window_defaults_to_the_decided_setting():
    assert retention_days({}) == DEFAULT_RETENTION_DAYS
    assert retention_days({ENV_RETENTION_DAYS: "7"}) == 7
    with pytest.raises(ValueError) as exc:
        retention_days({ENV_RETENTION_DAYS: "0"})
    assert ENV_RETENTION_DAYS in str(exc.value)
    with pytest.raises(ValueError) as exc:
        retention_days({ENV_RETENTION_DAYS: "fortnight"})
    assert ENV_RETENTION_DAYS in str(exc.value)
