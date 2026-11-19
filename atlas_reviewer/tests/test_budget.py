# SPDX-License-Identifier: MIT
"""The per-tenant daily spend bounds (config slice S9, D81): the
append-only per-repo-per-day ledger, its percent-encoded file names, the
UTC reset, the stricter-of-the-two refusal, and the named, bounded
check-then-act race. Offline: temp files only."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from atlas_reviewer.budget import (
    BUDGET_REACHED,
    CAP_REACHED,
    DEFAULT_REPO_DAILY_BUDGET_USD,
    ENV_REPO_DAILY_BUDGET_USD,
    SKIP_BUDGET_REASON,
    STORE_UNAVAILABLE,
    DailySpend,
    no_installation_cap,
    repo_daily_budget_usd,
    skip_reason,
    spend_file,
    spend_segment,
)

DAY = date(2026, 11, 19)


def _spend(tmp_path, *, budget=Decimal("100.00"), cap=no_installation_cap, today=None):
    return DailySpend(
        tmp_path,
        budget,
        cap_for=cap,
        today=(lambda: DAY) if today is None else today,
    )


# --------------------------------------------------------- the file names


def test_a_segment_escapes_every_byte_outside_letters_and_digits():
    assert spend_segment("brandondees") == "brandondees"
    assert spend_segment("a-b") == "a%2Db"
    assert spend_segment("a/b") == "a%2Fb"
    assert spend_segment("a%b") == "a%25b"
    assert spend_segment("a b") == "a%20b"
    assert spend_segment("café") == "caf%C3%A9"
    assert spend_segment("") == ""


def test_two_distinct_owner_repo_pairs_never_share_a_spend_file(tmp_path):
    """The done-when, pinned at the file level: the joining `-` is
    unambiguous because a literal `-` inside a segment always reads
    `%2D`, so `a-b/c` and `a/b-c` name different files."""
    first = spend_file(tmp_path, "a-b/c", DAY)
    second = spend_file(tmp_path, "a/b-c", DAY)
    assert first != second
    assert first.name == "a%2Db-c-2026-11-19.jsonl"
    assert second.name == "a-b%2Dc-2026-11-19.jsonl"
    # And the encoding is injective: no two names collide.
    assert spend_segment("a%2Db-c") != spend_segment("a-b%2Fc")


def test_the_spend_file_lives_under_the_state_roots_spend_directory(tmp_path):
    path = spend_file(tmp_path, "o/r", DAY)
    assert path == tmp_path / "spend" / "o-r-2026-11-19.jsonl"


# ------------------------------------------------------------- the ledger


def test_no_file_reads_as_zero_and_no_gap(tmp_path):
    assert _spend(tmp_path).committed("o/r") == (Decimal(0), "")


def test_a_recorded_review_is_the_days_committed_total(tmp_path):
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("0.0100"), 2, at=_at(1))
    spend.record("o/r", Decimal("1.2300"), 5, at=_at(2))
    total, gap = spend.committed("o/r")
    assert total == Decimal("1.2400")
    assert gap == ""


def _at(minute: int) -> datetime:
    return datetime(2026, 11, 19, 0, minute, tzinfo=UTC)


def test_the_total_survives_a_restart(tmp_path):
    """A fresh ledger instance over the same state root reads the total
    the previous process appended -- the total is the file, not memory."""
    _spend(tmp_path).record("o/r", Decimal("2.5000"), 4)
    total, gap = _spend(tmp_path).committed("o/r")
    assert total == Decimal("2.5000")
    assert gap == ""


def test_the_total_resets_at_the_utc_boundary(tmp_path):
    """The date in the file name makes the reset structural: a new UTC day
    is a new file, and the old day's total does not carry over."""
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("99.0000"), 1)
    next_day = DailySpend(tmp_path, Decimal("100.00"), today=lambda: date(2026, 11, 20))
    assert next_day.committed("o/r") == (Decimal(0), "")
    # The old day's file still holds its own total.
    assert spend.committed("o/r") == (Decimal("99.0000"), "")


def test_two_repos_never_share_a_total(tmp_path):
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("1.0000"), 1)
    spend.record("a/b", Decimal("50.0000"), 1)
    assert spend.committed("o/r") == (Decimal("1.0000"), "")
    assert spend.committed("a/b") == (Decimal("50.0000"), "")


def test_an_unreadable_record_makes_the_total_unknown_and_the_gap_names_it(tmp_path):
    """A spend file this service cannot parse must never open the budget:
    the total reads unknown and the caller refuses, with the gap that
    says so."""
    path = spend_file(tmp_path, "o/r", DAY)
    path.parent.mkdir(parents=True)
    path.write_text('{"committed_usd": "1.00"}\nnot json at all\n', encoding="utf-8")
    total, gap = _spend(tmp_path).committed("o/r")
    assert total is None
    assert "unreadable record" in gap
    assert "line 2" in gap


def test_a_negative_or_non_numeric_amount_is_an_unreadable_record(tmp_path):
    path = spend_file(tmp_path, "o/r", DAY)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"committed_usd": "-1.00"}\n{"committed_usd": 5}\n', encoding="utf-8"
    )
    total, gap = _spend(tmp_path).committed("o/r")
    assert total is None
    assert "line 1" in gap


def test_an_unreadable_spend_file_is_a_gap(tmp_path):
    """A file the OS will not read (here: a directory where the file
    should be) is an unknown total, not a zero."""
    path = spend_file(tmp_path, "o/r", DAY)
    path.parent.mkdir(parents=True)
    path.mkdir()
    total, gap = _spend(tmp_path).committed("o/r")
    assert total is None
    assert "could not be read" in gap


def test_a_record_cannot_be_negative(tmp_path):
    with pytest.raises(ValueError):
        _spend(tmp_path).record("o/r", Decimal("-0.01"), 1)


# ------------------------------------------------------- the daily budget


def test_the_budget_defaults_to_the_decided_hundred_dollars():
    assert repo_daily_budget_usd({}) == Decimal("100.00")
    assert DEFAULT_REPO_DAILY_BUDGET_USD == Decimal("100.00")


def test_the_budget_reads_the_operator_variable():
    assert repo_daily_budget_usd({ENV_REPO_DAILY_BUDGET_USD: "40"}) == Decimal(40)


def test_an_empty_budget_variable_reads_as_unset():
    assert repo_daily_budget_usd({ENV_REPO_DAILY_BUDGET_USD: ""}) == Decimal("100.00")


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "Infinity"])
def test_an_unusable_budget_value_is_refused_naming_the_variable(raw):
    with pytest.raises(ValueError, match=ENV_REPO_DAILY_BUDGET_USD):
        repo_daily_budget_usd({ENV_REPO_DAILY_BUDGET_USD: raw})


def test_a_ledger_refuses_a_non_positive_budget():
    with pytest.raises(ValueError):
        DailySpend(Path("."), Decimal(0))


# --------------------------------------------------------- the refusals


def test_under_the_budget_no_refusal_names(tmp_path):
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("99.9900"), 1)
    assert spend.refusal("o/r", "") == ("", "")


def test_a_repo_that_has_spent_its_budget_is_refused_with_the_plain_record(tmp_path):
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("100.0000"), 1)
    message, gap = spend.refusal("o/r", "")
    assert message == BUDGET_REACHED == "skipped: daily budget reached"
    assert gap == ""


def test_a_repo_over_its_budget_is_refused_the_same_way(tmp_path):
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("125.0000"), 2)
    assert spend.refusal("o/r", "") == (BUDGET_REACHED, "")


def test_another_repo_is_not_refused_by_one_repos_spending(tmp_path):
    spend = _spend(tmp_path)
    spend.record("o/r", Decimal("125.0000"), 2)
    assert spend.refusal("a/b", "") == ("", "")


def test_the_total_is_compared_against_the_ledgers_own_budget(tmp_path):
    spend = _spend(tmp_path, budget=Decimal("10.00"))
    spend.record("o/r", Decimal("10.0000"), 1)
    assert spend.refusal("o/r", "") == (BUDGET_REACHED, "")


# -------------------------------------------- the installation's daily cap


def _cap(caps: dict[str, Decimal]):
    return lambda installation: caps.get(installation)


def test_an_unset_cap_means_none_applies(tmp_path):
    """When no cap is set, none applies: the per-repo daily budget
    remains the bound (D81's 5:13 PM CT answer, the stated default)."""
    spend = _spend(tmp_path, cap=_cap({}))
    spend.record("o/r", Decimal("99.0000"), 1)
    assert spend.refusal("o/r", "1234") == ("", "")


def test_an_installation_over_its_cap_is_refused_the_cap_way(tmp_path):
    spend = _spend(tmp_path, cap=_cap({"1234": Decimal("50.00")}))
    spend.record("o/r", Decimal("50.0000"), 1)
    message, gap = spend.refusal("o/r", "1234")
    assert message == CAP_REACHED == "skipped: installation daily cap reached"
    assert gap == ""


def test_an_installation_without_a_cap_is_not_refused_by_one_that_has_one(tmp_path):
    spend = _spend(tmp_path, cap=_cap({"1234": Decimal("50.00")}))
    spend.record("o/r", Decimal("50.0000"), 1)
    assert spend.refusal("o/r", "5678") == ("", "")


def test_the_stricter_of_cap_and_budget_governs_each_check(tmp_path):
    """A cap below the budget binds first; a cap above it never binds
    before the budget does."""
    tight = _spend(tmp_path, cap=_cap({"1234": Decimal("10.00")}))
    tight.record("o/r", Decimal("10.0000"), 1)
    assert tight.refusal("o/r", "1234") == (CAP_REACHED, "")
    loose = _spend(tmp_path / "loose", cap=_cap({"1234": Decimal("500.00")}))
    loose.record("o/r", Decimal("100.0000"), 1)
    assert loose.refusal("o/r", "1234") == (BUDGET_REACHED, "")


def test_an_unknown_total_refuses_and_carries_the_gap(tmp_path):
    path = spend_file(tmp_path, "o/r", DAY)
    path.parent.mkdir(parents=True)
    path.write_text("garbage\n", encoding="utf-8")
    message, gap = _spend(tmp_path).refusal("o/r", "")
    assert message == BUDGET_REACHED
    assert "unreadable record" in gap


# ------------------------------------- the named, bounded check-then-act race


def test_concurrent_admissions_overcommit_by_at_most_in_flight_times_the_max(
    tmp_path,
):
    """The race is accepted, not locked (D81): N admissions that each read
    the total before any of them commits all pass, and the reviews they
    started can push the day's total past the budget by at most the
    in-flight reviews times each one's per-review ceiling -- at the
    decided values, 32 in-flight reviews x the $25 operator max = $800
    past the $100 budget. The next admission after the spend is committed
    is the one refused."""
    spend = _spend(tmp_path)
    admissions = 32
    operator_max = Decimal("25.00")
    # The day is already nearly spent when the burst lands: $99.99
    # committed, one cent under the budget.
    spend.record("o/r", Decimal("99.9900"), 4)
    # Every concurrent admission reads that same uncommitted total and
    # passes; none of them records before the others read.
    for _ in range(admissions):
        assert spend.refusal("o/r", "") == ("", "")
    # Each in-flight review then settles at its per-review worst case.
    for _ in range(admissions):
        spend.record("o/r", operator_max, 1)
    total, gap = spend.committed("o/r")
    assert gap == ""
    # The committed total is at most budget + in-flight x max -- at the
    # decided values $100 + 32 x $25 = $900, i.e. at most $800 past the
    # budget -- and never more, whatever the deliveries' timing.
    assert total == Decimal("899.9900")
    assert total <= Decimal("100.00") + admissions * operator_max
    # The refusal applies to the next admission after the total is
    # committed.
    assert spend.refusal("o/r", "") == (BUDGET_REACHED, "")


def test_the_same_bound_holds_past_an_installations_cap(tmp_path):
    """With the cap the stricter bound ($100 against a $500 budget), the
    same race bound holds past the cap: 32 in-flight reviews x the $25
    operator max, and the next admission after the spend is committed is
    the one refused, by the cap."""
    spend = _spend(
        tmp_path, budget=Decimal("900.00"), cap=_cap({"1234": Decimal("100.00")})
    )
    admissions = 32
    operator_max = Decimal("25.00")
    # The cap is already nearly spent when the burst lands.
    spend.record("o/r", Decimal("99.9900"), 4)
    for _ in range(admissions):
        assert spend.refusal("o/r", "1234") == ("", "")
    for _ in range(admissions):
        spend.record("o/r", operator_max, 1)
    total, gap = spend.committed("o/r")
    assert gap == ""
    assert total <= Decimal("100.00") + admissions * operator_max
    assert spend.refusal("o/r", "1234") == (CAP_REACHED, "")


def test_the_fixed_reason_label_is_the_skips_one():
    assert SKIP_BUDGET_REASON == "daily-budget"


def test_a_cap_provider_that_cannot_read_the_store_refuses_fail_closed(tmp_path):
    """The S10 store-backed cap provider raises `InstallationStoreError`
    when it cannot read the record; the refusal is its own fixed text
    with the store's reason as the gap -- an unreadable store is an
    unknown cap, and an unknown cap never opens the budget."""
    from atlas_reviewer.installation_store import InstallationStoreError

    def broken(_installation):
        raise InstallationStoreError(
            "the installation record did not decrypt under the store key"
        )

    spend = _spend(tmp_path, cap=broken)
    message, gap = spend.refusal("o/r", "1234")
    assert message == STORE_UNAVAILABLE
    assert "did not decrypt" in gap
    assert skip_reason(message) == "installation-store"
    assert no_installation_cap("anything") is None


# ------------------------------------------------- the once-only record (M1)


def test_record_once_appends_once_per_key(tmp_path):
    spend = _spend(tmp_path)
    assert spend.record_once("o/r", Decimal("1.00"), 1, "attempt-1") == (True, "")
    assert spend.record_once("o/r", Decimal("1.00"), 1, "attempt-1") == (False, "")
    # A different attempt's key is a different spend and is recorded.
    assert spend.record_once("o/r", Decimal("2.00"), 1, "attempt-2") == (True, "")
    total, gap = spend.committed("o/r")
    assert total == Decimal("3.00")
    assert gap == ""


def test_record_once_does_not_append_to_an_unreadable_ledger(tmp_path):
    path = spend_file(tmp_path, "o/r", DAY)
    path.parent.mkdir(parents=True)
    path.write_text("garbage\n", encoding="utf-8")
    appended, gap = _spend(tmp_path).record_once("o/r", Decimal("1.00"), 1, "k")
    assert appended is False
    assert "unreadable record" in gap


def test_record_once_needs_a_key(tmp_path):
    with pytest.raises(ValueError):
        _spend(tmp_path).record_once("o/r", Decimal("1.00"), 1, "")


def test_the_ledger_write_completes_a_partial_write(tmp_path, monkeypatch):
    """N6: a short `os.write` count is written to completion before the
    file is closed, so a truncated line -- which the reader would fail
    closed on -- cannot be left behind."""
    import os as _os

    from atlas_reviewer import budget

    real_write = _os.write
    writes: list[int] = []

    def short_then_whole(fd, data):
        if not writes:
            writes.append(len(data))
            return real_write(fd, data[: len(data) // 2])
        return real_write(fd, data)

    monkeypatch.setattr(budget.os, "write", short_then_whole)
    _spend(tmp_path).record("o/r", Decimal("1.0000"), 1)
    total, gap = _spend(tmp_path).committed("o/r")
    assert gap == ""
    assert total == Decimal("1.0000")
    assert len(writes) == 1


# ----------------------------------------------- the bounds' check order (M2)


def test_when_both_bounds_are_spent_the_record_names_the_budget(tmp_path):
    """D86's ordering call, pinned: the budget is checked first, so a
    total at or over both bounds reads as the budget's refusal."""
    spend = _spend(tmp_path, cap={"1234": Decimal("10.00")})
    spend.record("o/r", Decimal("100.0000"), 1)
    assert spend.refusal("o/r", "1234") == (BUDGET_REACHED, "")
