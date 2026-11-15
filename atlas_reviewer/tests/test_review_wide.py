# SPDX-License-Identifier: MIT
"""D68: the review-wide limits derived from the planned lens count, under
the absolute per-review dollar ceiling. Offline: fakes only, no model,
network or secret."""

import threading
from dataclasses import replace
from decimal import Decimal

import pytest

from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.attestation import AttemptLedger, Attestation, LensState
from atlas_reviewer.coordinator import review_lenses, status_line
from atlas_reviewer.fakes import MemoryLedger, ScriptedLensModel
from atlas_reviewer.lens_loop import (
    DEFAULT_PER_LENS_CALLS,
    DEFAULT_PER_LENS_USD,
    DEFAULT_REVIEW_CEILING_USD,
    AgenticLimits,
    Derivation,
)
from atlas_reviewer.redact import Redactor
from atlas_reviewer.review_wide import (
    derive_review_wide,
    resolve_ceiling,
    review_md_ceiling,
)
from atlas_reviewer.verdict import parse_status

from .agentic import BODY, DIFF, LIMITS, READ_ALL, final, tools, trees
from .helpers import FakeClock, LocalSprites, StubLibrary, source_tarball
from .test_coordinator import EVENT


def run(tmp_path, names, models, *, limits=None, picker_spend=(0, Decimal(0))):
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
            trees(),
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
    assert review_md_ceiling(tarball) == Decimal(15)


def test_a_commented_or_spaced_ceiling_line_is_honored():
    tarball = _tarball(
        {"REVIEW.md": b"review_ceiling_usd:  7.25  # room for two big lenses\n"}
    )
    assert review_md_ceiling(tarball) == Decimal("7.25")


def test_no_review_md_or_no_line_leaves_the_default_standing():
    assert review_md_ceiling(_tarball({})) is None
    assert review_md_ceiling(_tarball({"README.md": b"review_ceiling_usd: 15"})) is None
    assert review_md_ceiling(_tarball({"REVIEW.md": b"no setting here"})) is None
    assert review_md_ceiling(b"") is None


def test_an_unusable_ceiling_value_is_ignored_not_refused():
    """An unparseable or non-positive override leaves None -- the default
    stands -- the way REVIEW.md's own policy treats an unknown value."""
    for raw in (
        b"review_ceiling_usd: later\n",
        b"review_ceiling_usd: 0\n",
        b"review_ceiling_usd: -3\n",
        b"review_ceiling_usd:\n",
        b"review_ceiling_usd: 5\nreview_ceiling_usd: 9\n",
    ):
        assert review_md_ceiling(_tarball({"REVIEW.md": raw})) is None, raw


def test_an_oversized_review_md_is_not_parsed_cut():
    """A REVIEW.md over the read bound is unparseable, not truncated
    text: a cut inside the value could read as a number it is not."""
    big = b"# policy\n\nreview_ceiling_usd: 15\n\n" + b"# " + b"x" * (80 * 1024)
    assert review_md_ceiling(_tarball({"REVIEW.md": big})) is None


def test_a_repo_ceiling_overrides_the_configured_one_in_the_derivation():
    limits = load_agentic_limits({"ATLAS_REVIEW_CEILING_USD": "8"})
    derived, record = derive_review_wide(limits, 12, repo_ceiling=Decimal("20.00"))
    assert derived.reservation_usd == Decimal("20.00") == record.ceiling


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
