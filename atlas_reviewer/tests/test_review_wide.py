# SPDX-License-Identifier: MIT
"""D68: the review-wide limits derived from the planned lens count, under
the absolute per-review dollar ceiling. Offline: fakes only, no model,
network or secret."""

import threading
import time
from dataclasses import replace
from decimal import Decimal

import pytest

from atlas_reviewer import lens_loop
from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.attestation import AttemptLedger, Attestation, Cause, LensState
from atlas_reviewer.bridge_staging import SourceTrees
from atlas_reviewer.coordinator import render_draft, review_lenses, status_line
from atlas_reviewer.fakes import MemoryLedger, ScriptedLensModel
from atlas_reviewer.lens_loop import (
    DEFAULT_PER_LENS_CALLS,
    DEFAULT_PER_LENS_USD,
    DEFAULT_REVIEW_CEILING_USD,
    HALTED_CALL,
    AgenticLimits,
    Derivation,
    Spend,
    TurnRequest,
    _reserve_call,
)
from atlas_reviewer.redact import Redactor
from atlas_reviewer.review_wide import (
    derive_review_wide,
    resolve_ceiling,
    review_md_ceiling,
)
from atlas_reviewer.verdict import parse_status

from .agentic import (
    BASE_FILES,
    BODY,
    DIFF,
    HEAD_FILES,
    LIMITS,
    NOTHING,
    READ_ALL,
    TOP,
    final,
    tools,
    trees,
)
from .helpers import HEAD, OLD, FakeClock, LocalSprites, StubLibrary, source_tarball
from .test_coordinator import EVENT


def run(
    tmp_path, names, models, *, limits=None, picker_spend=(0, Decimal(0)), trees_=None
):
    """A multi-lens review over the real bridge through `LocalSprites`,
    one scripted model per lens. No model, Sprite or GitHub call is made."""
    from .test_keepalive import TaskServer, socket_path

    tasks = TaskServer(socket_path(tmp_path))
    tasks.start()
    pending = list(models)
    lock = threading.Lock()

    def model_for():
        with lock:
            # A continuation after the models ran out reuses the last
            # model, whose exhausted script fails its turn like any
            # model error; these tests read the first stop.
            return pending.pop(0) if pending else models[-1]

    try:
        return review_lenses(
            EVENT,
            tuple(names),
            DIFF,
            trees() if trees_ is None else trees_,
            library=StubLibrary({name: BODY for name in names}),
            model=models[0],
            limits=limits or LIMITS,
            ledger=AttemptLedger(
                tmp_path / "state" / "attestations.jsonl", FakeClock()
            ),
            sprites=LocalSprites(),
            runner_ledger=MemoryLedger(),
            redactor=Redactor(),
            clock=FakeClock(),
            nonce=lambda: "f00dfeedf00dfeed",
            bridge_root=str(tmp_path / "bridge"),
            task_socket=str(tasks.path),
            model_for=model_for,
            picker_spend=picker_spend,
        )
    finally:
        tasks.close()
        assert tasks.tasks == {}, tasks.order


# ------------------------------------------------------------ the formulas


def test_the_derived_call_cap_is_the_per_lens_budget_times_the_planned_lenses():
    """Kills the mutant that drops the x-lenses factor: 50 calls for the
    whole review is the flat default this slice removes; a 12-lens review
    must plan 12 x 50 calls."""
    derived, record = derive_review_wide(AgenticLimits(), 12, 1)
    assert derived.max_calls == 50 * 12 + 1 == record.max_calls
    assert DEFAULT_PER_LENS_CALLS == 50


def test_the_derived_reservation_is_the_per_lens_budget_times_the_planned_lenses():
    """Kills the mutant that drops the x-lenses factor on the dollars
    too: $5 for the whole review is the flat default this slice removes.
    $5 per lens x 12 lenses is $60, over the $10 default ceiling, so the
    derived reservation is the clamp."""
    derived, record = derive_review_wide(AgenticLimits(), 12)
    assert derived.reservation_usd == Decimal("10.00") == record.reservation_usd
    assert record.ceiling == DEFAULT_REVIEW_CEILING_USD == Decimal("10.00")
    assert DEFAULT_PER_LENS_USD == Decimal(5)


def test_a_two_lens_derivation_lands_exactly_on_the_ceiling():
    derived, record = derive_review_wide(AgenticLimits(), 2)
    assert derived.reservation_usd == Decimal("10.00")
    assert record.reservation_configured() == (
        "$10.00 (derived $10.00 = $5.00 per lens x 2 planned lenses"
        ", which is the $10.00 per-review ceiling)"
    )


def test_a_small_review_keeps_the_per_lens_formula_without_the_clamp():
    derived, record = derive_review_wide(AgenticLimits(), 1)
    assert derived.max_calls == 50  # 50 per lens, no picker call
    assert derived.reservation_usd == Decimal("5.00")
    assert record.reservation_configured() == (
        "$5.00 (derived $5.00 = $5.00 per lens x 1 planned lens"
        "; the $10.00 per-review ceiling is above it)"
    )


def test_the_derived_review_wall_scales_with_the_planned_waves():
    """A wave is one pool-full of planned lenses; the derived wall is the
    standing default raised to lens_wall_s x waves, never lowered."""
    derived, record = derive_review_wide(AgenticLimits(), 12)
    assert (record.waves, derived.review_wall_s) == (12, 1200 * 12)
    pooled, record = derive_review_wide(replace(AgenticLimits(), pool_size=4), 12)
    assert (pooled.review_wall_s, record.waves) == (3600, 3)
    # Never below the standing default: 8 lenses at pool 4 are 2 waves,
    # whose 2400s would otherwise shrink the 3600s the review runs on.
    small, _ = derive_review_wide(replace(AgenticLimits(), pool_size=4), 8)
    assert small.review_wall_s == 3600


def test_waves_round_up_when_planned_is_not_a_pool_multiple():
    """Kills the ceil-division mutant (round-1 review of #717, m-4): 7
    lenses at pool 4 need 2 waves, whose 8000s the second wave runs in;
    the floor mutant derives 1 wave and the second dies at the wall."""
    limits = replace(AgenticLimits(), pool_size=4, lens_wall_s=4000)
    derived, record = derive_review_wide(limits, 7)
    assert record.waves == 2
    assert derived.review_wall_s == 8000


def test_an_explicit_review_wide_override_wins_and_the_ceiling_still_clamps():
    """An operator-set `--max-calls` or `--reservation-usd` keeps the
    meaning it always had; the ceiling clamps the reservation even then."""
    limits = load_agentic_limits(
        {"ATLAS_MAX_CALLS": "100", "ATLAS_RESERVATION_USD": "40"}
    )
    assert limits.explicit == frozenset({"max_calls", "reservation_usd"})
    derived, record = derive_review_wide(limits, 12, 1)
    assert derived.max_calls == 100
    assert not record.calls_derived
    assert record.calls_configured() == "100"
    assert record.calls_setting() == "--max-calls or ATLAS_MAX_CALLS"
    assert derived.reservation_usd == Decimal("10.00")
    assert not record.reservation_derived
    assert record.reservation_configured() == (
        "$10.00 (the configured reservation, clamped to the $10.00 per-review ceiling)"
    )
    assert "ATLAS_REVIEW_CEILING_USD" in record.reservation_setting()


def test_an_explicit_review_wall_is_honored_and_an_unset_one_is_derived():
    limits = load_agentic_limits({"ATLAS_REVIEW_WALL_S": "2000"})
    assert limits.explicit == frozenset({"review_wall_s"})
    derived, _ = derive_review_wide(limits, 12)
    assert derived.review_wall_s == 2000
    unset, _ = derive_review_wide(load_agentic_limits({}), 12)
    assert unset.review_wall_s == 1200 * 12


def test_the_per_lens_knobs_are_env_configurable_and_drive_the_derivation():
    limits = load_agentic_limits(
        {
            "ATLAS_PER_LENS_CALLS": "20",
            "ATLAS_PER_LENS_USD": "0.50",
            "ATLAS_REVIEW_CEILING_USD": "8",
            "ATLAS_MAX_TURNS": "20",
        }
    )
    derived, record = derive_review_wide(limits, 12, 1)
    assert derived.max_calls == 20 * 12 + 1
    assert derived.reservation_usd == Decimal("6.00")
    assert record.ceiling == Decimal("8.00")
    assert record.calls_configured() == (
        "241 (20 per lens x 12 planned lenses + 1 picker call; the "
        "$8.00 per-review dollar ceiling bounds the spend)"
    )
    with pytest.raises(ValueError, match="per_lens_calls"):
        load_agentic_limits({"ATLAS_PER_LENS_CALLS": "0"})
    with pytest.raises(ValueError, match="per_lens_calls"):
        AgenticLimits(per_lens_calls=True).resolve()
    with pytest.raises(ValueError, match="per_lens_usd"):
        load_agentic_limits({"ATLAS_PER_LENS_USD": "nope"})
    with pytest.raises(ValueError, match="review_ceiling_usd"):
        AgenticLimits(review_ceiling_usd=Decimal(0)).resolve()


def test_a_derived_call_budget_below_the_turn_cap_is_refused_before_any_lens():
    """The limits guard against runaway loops and costly failures, never
    against thoroughness: a per-lens call budget under the per-lens turn
    cap would cut every attempt short, so the derivation refuses it."""
    limits = load_agentic_limits(
        {"ATLAS_MAX_TURNS": "40", "ATLAS_PER_LENS_CALLS": "10"}
    )
    with pytest.raises(ValueError, match="per_lens_calls"):
        derive_review_wide(limits, 12)
    # An explicit review-wide call cap is not derived, so the per-lens
    # budget is never consulted and the same turn cap runs unchanged.
    explicit = load_agentic_limits({"ATLAS_MAX_TURNS": "40", "ATLAS_MAX_CALLS": "100"})
    derived, _ = derive_review_wide(explicit, 12)
    assert derived.max_calls == 100


def test_the_derivation_refuses_an_impossible_plan():
    with pytest.raises(ValueError, match="planned_lenses"):
        derive_review_wide(AgenticLimits(), 0)
    with pytest.raises(ValueError, match="planned_lenses"):
        derive_review_wide(AgenticLimits(), True)
    with pytest.raises(ValueError, match="negative"):
        derive_review_wide(AgenticLimits(), 1, picker_calls=-1)


def test_cross_limit_relations_are_checked_against_the_derived_totals():
    """D68: the derivation raises the review-wide totals above the
    configured ones, so a per-lens budget above the flat defaults is a
    valid multi-lens configuration; an explicit review-wide value below
    its per-lens budget is still refused, against the derived totals."""
    turns = load_agentic_limits({"ATLAS_MAX_TURNS": "60", "ATLAS_PER_LENS_CALLS": "60"})
    derived, _ = derive_review_wide(turns, 12)
    assert derived.max_calls == 60 * 12
    walls = load_agentic_limits({"ATLAS_LENS_WALL_S": "4000"})
    derived_walls, _ = derive_review_wide(walls, 12)
    assert derived_walls.review_wall_s == 4000 * 12
    with pytest.raises(ValueError, match="max_turns must be no greater than max_calls"):
        derive_review_wide(
            load_agentic_limits({"ATLAS_MAX_CALLS": "30", "ATLAS_MAX_TURNS": "40"}),
            2,
        )
    with pytest.raises(
        ValueError, match="lens_wall_s must be no greater than review_wall_s"
    ):
        derive_review_wide(
            load_agentic_limits(
                {"ATLAS_LENS_WALL_S": "3000", "ATLAS_REVIEW_WALL_S": "2000"}
            ),
            2,
        )


def test_the_single_lens_path_still_checks_the_relations_against_its_configured_totals():
    """The relations the derivation defers are still enforced where the
    configured review-wide values are the totals: the single-lens path
    resolves with them on."""
    with pytest.raises(ValueError, match="no greater than max_calls"):
        replace(AgenticLimits(), max_turns=60, per_lens_calls=60).resolve()
    with pytest.raises(ValueError, match="lens_wall_s must be no greater"):
        replace(AgenticLimits(), lens_wall_s=4000).resolve()


# ---------------------------------------------------------------- ceiling


def test_the_ceiling_precedence_is_repo_then_configured_then_default():
    assert resolve_ceiling(None, None) == Decimal("10.00")
    assert resolve_ceiling(Decimal(7), None) == Decimal(7)
    assert resolve_ceiling(Decimal(7), Decimal(3)) == Decimal(3)
    assert resolve_ceiling(None, Decimal("12.5")) == Decimal("12.5")


def _tarball(files: dict[str, bytes]) -> bytes:
    return source_tarball(files, top="example-app")


def test_the_reviewed_repos_review_md_sets_the_ceiling():
    tarball = _tarball({"REVIEW.md": b"# policy\n\nreview_ceiling_usd: 15\n"})
    read = review_md_ceiling(tarball)
    assert read.value == Decimal(15)
    assert read.note == ""


def test_a_commented_or_spaced_ceiling_line_is_honored():
    tarball = _tarball(
        {"REVIEW.md": b"review_ceiling_usd:  7.25  # room for two big lenses\n"}
    )
    assert review_md_ceiling(tarball).value == Decimal("7.25")


def test_a_no_space_ceiling_line_is_honored():
    """The tight form parses too (round-2 review of #717, m-7): a repo
    that hand-writes `review_ceiling_usd:15` gets its ceiling, not a
    silent fall-back to the default."""
    tarball = _tarball({"REVIEW.md": b"review_ceiling_usd:15\n"})
    read = review_md_ceiling(tarball)
    assert read.value == Decimal(15)
    assert read.note == ""


def test_no_review_md_or_no_line_leaves_the_default_standing():
    assert review_md_ceiling(_tarball({})).value is None
    assert (
        review_md_ceiling(_tarball({"README.md": b"review_ceiling_usd: 15"})).value
        is None
    )
    absent = review_md_ceiling(_tarball({"REVIEW.md": b"no setting here"}))
    assert absent.value is None
    assert absent.note == ""  # no line: silent, like no override at all
    assert review_md_ceiling(b"").value is None


def test_an_unusable_ceiling_value_is_ignored_not_refused():
    """An unparseable or non-positive override leaves None -- the default
    stands -- the way REVIEW.md's own policy treats an unknown value."""
    for raw in (
        b"review_ceiling_usd: later\n",
        b"review_ceiling_usd:bad\n",
        b"review_ceiling_usd: 0\n",
        b"review_ceiling_usd: -3\n",
        b"review_ceiling_usd:\n",
        b"review_ceiling_usd: 5\nreview_ceiling_usd: 9\n",
    ):
        read = review_md_ceiling(_tarball({"REVIEW.md": raw}))
        assert read.value is None, raw
        assert "review_ceiling_usd" in read.note
        assert "ignored" in read.note


def test_an_oversized_review_md_is_not_parsed_cut():
    """A REVIEW.md over the read bound is unparseable, not truncated
    text: a cut inside the value could read as a number it is not."""
    big = b"# policy\n\nreview_ceiling_usd: 15\n\n" + b"# " + b"x" * (80 * 1024)
    read = review_md_ceiling(_tarball({"REVIEW.md": big}))
    assert read.value is None
    assert "read bound" in read.note


def test_a_repo_ceiling_overrides_the_configured_one_in_the_derivation():
    limits = load_agentic_limits({"ATLAS_REVIEW_CEILING_USD": "8"})
    derived, record = derive_review_wide(limits, 12, repo_ceiling=Decimal("20.00"))
    assert derived.reservation_usd == Decimal("20.00") == record.ceiling


def _mixed_trees(base_review: bytes | None, head_review: bytes | None) -> SourceTrees:
    base_files = {**BASE_FILES}
    head_files = {**HEAD_FILES}
    if base_review is not None:
        base_files["REVIEW.md"] = base_review
    if head_review is not None:
        head_files["REVIEW.md"] = head_review
    return SourceTrees(
        source_tarball(base_files, top=TOP),
        source_tarball(head_files, top=TOP),
        OLD,
        HEAD,
    )


def test_the_ceiling_is_read_from_the_merge_base_tree(tmp_path):
    """The ceiling comes from the merge-base tree the review already
    fetches (D68; round-1 review of #717, m-1), not the base-ref tip and
    never the head: a head REVIEW.md naming a different ceiling does not
    move it, and the merge-base copy is the one the stop names."""
    models = [ScriptedLensModel([READ_ALL, final()], worst_usd=Decimal("3.00"))]
    result = run(
        tmp_path,
        ["lens-1"],
        models,
        trees_=_mixed_trees(b"review_ceiling_usd: 2\n", b"review_ceiling_usd: 50\n"),
    )
    stopped = [
        r
        for r in result.lenses
        if r.outcome is not None and r.outcome.limit_hit is not None
    ]
    assert stopped
    assert "$2.00 per-review ceiling" in stopped[0].outcome.limit_hit.configured


def test_an_unusable_ceiling_line_is_named_in_the_draft(tmp_path):
    """A ceiling line present but unusable fails open to the default, and
    the draft says so, so a meant ceiling that silently fell back is
    visible (round-1 review of #717, m-5); with no line at all the draft
    stays silent."""
    (tmp_path / "unusable").mkdir()
    unusable = run(
        tmp_path / "unusable",
        ["lens-1"],
        [ScriptedLensModel([READ_ALL, final(lens="lens-1")])],
        trees_=_mixed_trees(b"review_ceiling_usd: later\n", None),
    )
    draft = render_draft(unusable, Redactor())
    assert "review_ceiling_usd" in draft
    assert "ignored" in draft
    assert unusable.coverage_complete

    (tmp_path / "quiet").mkdir()
    quiet = run(
        tmp_path / "quiet",
        ["lens-1"],
        [ScriptedLensModel([READ_ALL, final(lens="lens-1")])],
    )
    assert "review_ceiling_usd" not in render_draft(quiet, Redactor())


# ------------------------------------------------------- the limit stops


def test_a_reservation_stop_names_the_derivation_the_ceiling_and_the_knobs(tmp_path):
    """Pushing spend past the derived reservation produces a limit_stop
    that names the derived values, the absolute ceiling, the observed
    value and the knob to change."""
    models = [ScriptedLensModel([READ_ALL, final()], worst_usd=Decimal("15.00"))]
    result = run(
        tmp_path,
        ["lens-1"],
        models,
        limits=replace(LIMITS, per_lens_usd=Decimal("1.00")),
    )
    stopped = [
        r
        for r in result.lenses
        if r.outcome is not None and r.outcome.limit_hit is not None
    ]
    assert stopped
    hit = stopped[0].outcome.limit_hit
    assert hit.limit == "reservation_usd"
    assert hit.configured == (
        "$1.00 (derived $1.00 = $1.00 per lens x 1 planned lens"
        "; the $10.00 per-review ceiling is above it)"
    )
    assert hit.observed == "$15.00"
    assert hit.setting == (
        "--per-lens-usd or ATLAS_PER_LENS_USD (D68 derives the review total "
        "from the planned lens count); the ceiling: --review-ceiling-usd or "
        "ATLAS_REVIEW_CEILING_USD, or the reviewed repo's REVIEW.md"
    )
    parsed = parse_status(status_line(result))
    assert parsed is not None
    assert parsed["limit_stop"]["limit"] == "reservation_usd"


def test_a_call_cap_stop_names_the_derived_total_and_the_per_lens_knob(tmp_path):
    """Pushing calls past the derived cap stops the review with the same
    four facts: the derived value, the ceiling it sits under, the observed
    call, and the knob. The cap binds on the continuation turn here: the
    per-lens budget covered the first attempt, and the review-wide total
    is what the derivation planned."""
    model = ScriptedLensModel(
        [
            tools(("diff_file", {"path": "calc.py"})),
            final(),
            final(),
            tools(("diff_file", {"path": "config/keys.py"})),
            final(),
        ]
    )
    result = run(
        tmp_path,
        ["lens-1"],
        [model],
        limits=replace(LIMITS, per_lens_calls=4, max_turns=3),
    )
    stopped = [
        r
        for r in result.lenses
        if r.outcome is not None and r.outcome.limit_hit is not None
    ]
    assert stopped, "the derived cap must stop the 5th call"
    hit = stopped[0].outcome.limit_hit
    assert hit.limit == "max_calls"
    assert hit.configured == (
        "4 (4 per lens x 1 planned lens; the $10.00 per-review "
        "dollar ceiling bounds the spend)"
    )
    assert hit.observed == "next call 5"
    assert "ATLAS_PER_LENS_CALLS" in hit.setting
    assert not result.coverage_complete


def test_a_derived_reservation_stops_the_review_under_a_repo_ceiling(tmp_path):
    """A ceiling lower than the derived reservation binds, and the stop
    names it."""
    models = [ScriptedLensModel([READ_ALL, final()], worst_usd=Decimal("3.00"))]
    result = run(
        tmp_path,
        ["lens-1", "lens-2"],
        models,
        limits=replace(LIMITS, review_ceiling_usd=Decimal("2.00")),
    )
    stopped = [
        r
        for r in result.lenses
        if r.outcome is not None and r.outcome.limit_hit is not None
    ]
    assert stopped
    hit = stopped[0].outcome.limit_hit
    assert hit.limit == "reservation_usd"
    assert "$2.00 per-review ceiling" in hit.configured


# ------------------------------------------------- the scripted parity run


def test_a_pool_of_concurrent_worst_case_first_calls_waits_not_stops(tmp_path):
    """M-1's acceptance variant (round-1 review of #717): the scripted
    per-call worst case is the recorded catalog's -- about $2.90, the
    pinned Sonnet terms' output reserve priced at completion plus
    reasoning -- so a 12-lens review at pool 4 projects concurrent worst
    cases against the $10 clamped reservation. Each first turn holds its
    worst case in flight briefly, the overflow waits for a settle instead
    of stopping a lens, and the review completes with full coverage. The
    deterministic kill for the revert-to-stop mutant is
    `test_the_fourth_concurrent_reservation_waits_for_a_settle`."""
    names = [f"lens-{i}" for i in range(1, 13)]
    models = []
    for name in names:
        first = READ_ALL

        def slow(request, _first=first):
            time.sleep(0.2)
            return _first

        models.append(
            ScriptedLensModel([slow, final(lens=name)], worst_usd=Decimal("2.90"))
        )
    result = run(
        tmp_path,
        names,
        models,
        limits=replace(LIMITS, pool_size=4, lens_wall_s=300, review_wall_s=600),
    )
    assert result.coverage_complete
    assert result.model_calls == 24
    assert all(lens.outcome.limit_hit is None for lens in result.lenses)
    # Every call settled at $0.02; the reservations' worst cases came down
    # as the turns completed, which is what the waits waited for.
    assert Decimal(result.committed_usd) == Decimal("0.48")


def test_the_fourth_concurrent_reservation_waits_for_a_settle():
    """The deterministic pin of M-1's fix (round-1 review of #717): three
    worst cases in flight against a $10 cap overflow the fourth
    reservation, which waits for a settle instead of stopping -- and a
    stop still comes when nothing in flight could free room. The mutant
    that reverts to the immediate stop dies here: the fourth reserve is
    refused while the settle is still held back."""
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    assert spend.reserve(Decimal("2.90")) is None
    assert spend.reserve(Decimal("2.90")) is None
    assert spend.reserve(Decimal("2.90")) is None
    results: list[object] = []

    def fourth():
        results.append(
            spend.reserve(Decimal("2.90"), clock=FakeClock(), wait_until=10**9)
        )

    waiting = threading.Thread(target=fourth)
    waiting.start()
    time.sleep(0.2)  # the fourth reservation is parked in its wait
    spend.settle(Decimal("2.90"), Decimal("0.02"))
    waiting.join(timeout=5)
    assert results == [None]
    assert spend.calls == 4
    # 3 x $2.90 in flight, one settled to $0.02, then the fourth's $2.90.
    assert spend.committed_usd == Decimal("8.72")


def test_a_backpressure_wait_runs_out_at_the_wall():
    """A wait bounded by the review wall stops at the wall: the projected
    overflow is refused once the deadline has passed, and spend never
    passes the ceiling."""
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None
    hit = spend.reserve(Decimal("2.90"), clock=FakeClock(start=1000), wait_until=900)
    assert hit is not None
    assert hit.limit == "reservation_usd"
    assert spend.calls == 3


def test_a_frozen_clocks_wait_still_ends_on_the_backstop(monkeypatch):
    """Round-3 review of #717, m-8: a reservation parked on a frozen
    review clock -- no settle, no halt, a far wall -- still returns, on
    the real-time backstop the stalled clock earns (shrunk here so the
    test runs in under a second). Kills the progress-comparison mutant
    A9 (`now >= last_seen`): it reads every wake as progress, never arms
    the backstop, and the parked wait never comes back."""
    monkeypatch.setattr(lens_loop, "BACKPRESSURE_REAL_LIMIT_S", 0.3)
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None
    results: list[object] = []

    def fourth():
        results.append(
            spend.reserve(Decimal("2.90"), clock=FakeClock(), wait_until=10**6)
        )

    waiting = threading.Thread(target=fourth, daemon=True)
    waiting.start()
    waiting.join(timeout=3)
    assert not waiting.is_alive()  # A9 would spin forever on the frozen clock
    hit = results[0]
    assert hit is not None and hit.limit == "reservation_usd"
    assert spend.calls == 3


def test_a_healthy_clock_bounds_the_wait_not_the_backstop(monkeypatch):
    """M-1R (round-2 review of #717): the real-time backstop arms only
    when the review clock itself stops moving across wakeups. A freeing
    settle that arrives after 55 seconds of *clock* advance -- beyond the
    10-second backstop's reading -- still reserves: on a healthy clock
    the review wall is the bound, however long a turn takes. The backstop
    is shrunk to a quarter second so the unconditional-backstop mutant
    (which stops the wait at 10 wall-seconds regardless of the clock)
    dies here instead of needing a ten-second test."""
    monkeypatch.setattr(lens_loop, "BACKPRESSURE_REAL_LIMIT_S", 0.25)
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None
    clock = FakeClock()

    def tick():
        # A coarser tick step (round-3 n-9): five seconds of clock a
        # tenth-second, so the pin exercises progress detection with
        # fewer, larger advances.
        for _ in range(12):
            time.sleep(0.1)
            clock.advance(5)

    threading.Thread(target=tick, daemon=True).start()
    results: list[object] = []

    def fourth():
        results.append(spend.reserve(Decimal("2.90"), clock=clock, wait_until=1000))

    waiting = threading.Thread(target=fourth, daemon=True)
    waiting.start()
    time.sleep(1.2)  # the clock is past 55 s and still moving
    spend.settle(Decimal("2.90"), Decimal("0.02"))
    waiting.join(timeout=5)
    assert results == [None]
    assert spend.calls == 4


def test_a_wait_stops_at_the_wall_on_a_healthy_clock():
    """M-1R's second test: the wait outlives the wall and stops at it. On
    a moving clock the wall, not the backstop, ends the wait -- which is
    also the wall-deadline mutant's kill (C9): a waiter that ignores the
    wall on a healthy clock never comes back."""
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None
    clock = FakeClock()

    def tick():
        for _ in range(40):
            time.sleep(0.05)
            clock.advance(1)

    threading.Thread(target=tick, daemon=True).start()
    results: list[object] = []

    def fourth():
        results.append(spend.reserve(Decimal("2.90"), clock=clock, wait_until=5))

    waiting = threading.Thread(target=fourth, daemon=True)
    waiting.start()
    waiting.join(timeout=5)
    assert not waiting.is_alive()  # C9 would leave it waiting forever
    hit = results[0]
    assert hit is not None and hit.limit == "reservation_usd"
    assert clock.monotonic() >= 5  # the wall, not the backstop, ended it


def test_a_genuine_stop_does_not_wait():
    """Kills the genuine-stop-disabled mutant (C8, round-2 review of
    #717, n-4): when the settled spend plus the call's worst case cannot
    fit even with nothing in flight, the stop is immediate -- the mutant
    parks the reservation in the wait and burns the stalled clock's
    backstop out first."""
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None
    spend.settle(Decimal("2.90"), Decimal("0.02"))
    results: list[object] = []

    def fourth():
        results.append(
            spend.reserve(Decimal("10.50"), clock=FakeClock(), wait_until=10**6)
        )

    waiting = threading.Thread(target=fourth, daemon=True)
    waiting.start()
    waiting.join(timeout=2)
    assert not waiting.is_alive()
    hit = results[0]
    assert hit is not None and hit.limit == "reservation_usd"
    assert spend.calls == 3


def test_a_halt_wakes_a_parked_waiter():
    """Kills the halt-ignored mutant (C10, round-2 review of #717, n-4):
    a reservation parked in the wait when the review halts wakes and
    stops instead of riding the stalled clock's backstop out."""
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None
    results: list[object] = []

    def fourth():
        results.append(
            spend.reserve(Decimal("2.90"), clock=FakeClock(), wait_until=10**6)
        )

    waiting = threading.Thread(target=fourth, daemon=True)
    waiting.start()
    time.sleep(0.2)  # parked
    spend.halt()
    waiting.join(timeout=2)
    assert not waiting.is_alive()
    hit = results[0]
    assert hit is not None and hit.limit == "reservation_usd"


def test_a_halted_review_gives_a_parked_reservation_the_halt_outcome():
    """Round-2 review of #717, n-7: a reservation parked in the wait when
    the review halts comes back from `_reserve_call` as the halt outcome
    the loop already records, not as a dollar stop."""
    limits = replace(LIMITS, reservation_usd=Decimal("10.00")).resolve()
    spend = Spend(limits)
    for _ in range(3):
        assert spend.reserve(Decimal("2.90")) is None

    class Model:
        name = "worst"

        def worst_case_usd(self, request):
            return Decimal("2.90")

        def turn(self, request):
            raise AssertionError("a halted review sends no call")

    results: list[object] = []

    def fourth():
        results.append(
            _reserve_call(Model(), TurnRequest("", (), ()), spend, FakeClock(), 10**6)
        )

    waiting = threading.Thread(target=fourth, daemon=True)
    waiting.start()
    time.sleep(0.2)  # parked
    spend.halt()
    waiting.join(timeout=2)
    assert not waiting.is_alive()
    assert results[0] == (Cause.MODEL_ERROR, HALTED_CALL)


def test_a_reservation_still_stops_when_nothing_in_flight_could_free_room(tmp_path):
    """The backpressure's other half: when the settled spend plus the
    call's own worst case cannot fit the ceiling even with nothing in
    flight, the stop is immediate -- spend never passes the ceiling."""
    models = [
        ScriptedLensModel([READ_ALL, final()], worst_usd=Decimal("11.00")),
        ScriptedLensModel([READ_ALL, final()], worst_usd=Decimal("11.00")),
    ]
    result = run(
        tmp_path,
        ["lens-1", "lens-2"],
        models,
        limits=replace(LIMITS, pool_size=2),
    )
    stopped = [
        r
        for r in result.lenses
        if r.outcome is not None and r.outcome.limit_hit is not None
    ]
    assert stopped
    assert stopped[0].outcome.limit_hit.limit == "reservation_usd"
    assert not result.coverage_complete


def test_a_twelve_lens_scripted_review_with_fifteen_turns_a_lens_finishes(tmp_path):
    """D68's acceptance: a 12-lens scripted review with 15 turns per lens
    finishes with no limit stop when simulated spend stays under the
    ceiling. On the flat review-wide defaults this review stopped near
    50 calls with lenses unrun; the derivation plans 12 x 15 calls."""
    names = [f"lens-{i}" for i in range(1, 13)]
    models = [
        ScriptedLensModel(
            [
                READ_ALL,
                *(tools(("grep", {"pattern": f"probe-{i}"})) for i in range(13)),
                final(lens=name),
            ]
        )
        for name in names
    ]
    result = run(tmp_path, names, models, limits=replace(LIMITS, max_turns=15))
    assert len(result.lenses) == 12
    assert all(
        lens.state is LensState.CLEAN
        and lens.outcome.attestation is Attestation.ATTESTED
        and lens.outcome.limit_hit is None
        for lens in result.lenses
    )
    assert result.coverage_complete
    assert result.model_calls == 180
    assert parse_status(status_line(result))["limit_stop"] is None
    # The simulated spend settled at $0.02 a call, under the derived
    # reservation.
    assert Decimal(result.committed_usd) == Decimal("3.60")


def test_a_stalled_lens_nudge_turn_fits_the_derived_budget(tmp_path):
    """The merged D66 window and D68's derivation compose: a lens that
    stalls into the no-progress nudge spends one more counted call on the
    nudge turn before it finalizes, and the derived call budget -- per
    lens times planned lenses -- has room for it on every lens. On the
    flat review-wide cap the same review would have stopped mid-lens."""
    names = [f"lens-{i}" for i in range(1, 13)]
    models = [
        ScriptedLensModel(
            [
                READ_ALL,
                NOTHING,
                NOTHING,
                NOTHING,
                NOTHING,
                NOTHING,
                NOTHING,
                final(lens=name),
            ]
        )
        for name in names
    ]
    result = run(
        tmp_path,
        names,
        models,
        limits=replace(LIMITS, per_lens_calls=8, max_turns=8),
    )
    assert len(result.lenses) == 12
    assert all(
        lens.state is LensState.CLEAN
        and lens.outcome.attestation is Attestation.ATTESTED
        and lens.outcome.limit_hit is None
        and "no-progress" in lens.outcome.nudges
        for lens in result.lenses
    )
    # 8 calls per lens x 12 planned lenses: the nudge turn included.
    assert result.model_calls == 96
    assert result.coverage_complete
    assert parse_status(status_line(result))["limit_stop"] is None


def test_the_derivation_record_is_complete_for_the_draft_and_ledger():
    _, record = derive_review_wide(AgenticLimits(), 5, 2, Decimal("0.25"))
    assert isinstance(record, Derivation)
    assert (record.planned_lenses, record.waves) == (5, 5)
    assert (record.picker_calls, record.picker_usd) == (2, Decimal("0.25"))
    assert record.calls_derived and record.reservation_derived
    # $5 per lens x 5 planned lenses is $25.25 with the picker, over the
    # $10 default ceiling, so the derived reservation is the clamp.
    assert record.clamped
    assert record.calls_configured() == (
        "252 (50 per lens x 5 planned lenses + 2 picker calls; the "
        "$10.00 per-review dollar ceiling bounds the spend)"
    )


def test_the_clamp_is_reported_from_the_value_it_bit_on():
    """The clamp flag comes from the value the ceiling clamped -- the
    formula's when the reservation is derived, the configured one when it
    is not -- so an explicit reservation clamped by the ceiling reads as
    clamped even when the formula would sit under it."""
    explicit = load_agentic_limits({"ATLAS_RESERVATION_USD": "40"})
    _, clamped = derive_review_wide(explicit, 1)
    assert clamped.clamped
    assert clamped.reservation_configured() == (
        "$10.00 (the configured reservation, clamped to the $10.00 per-review ceiling)"
    )
    _, under = derive_review_wide(
        load_agentic_limits({"ATLAS_RESERVATION_USD": "3"}), 1
    )
    assert not under.clamped
    assert under.reservation_configured() == (
        "$3.00 (the configured reservation; the $10.00 per-review ceiling is above it)"
    )
    assert derive_review_wide(AgenticLimits(), 12)[1].clamped
    assert not derive_review_wide(AgenticLimits(), 1)[1].clamped
