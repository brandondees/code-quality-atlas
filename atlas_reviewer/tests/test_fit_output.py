# SPDX-License-Identifier: MIT
"""A call the reservation cannot cover at the model's full output cap is
sent with a smaller cap that it can cover, down to `min_output_tokens`."""

import math
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.attestation import AttemptOutcome, Cause, LensState
from atlas_reviewer.coordinator import render_draft, synthesize
from atlas_reviewer.fakes import ScriptedLensModel
from atlas_reviewer.lens_loop import (
    REASONING_HINT_CAP,
    AgenticLimits,
    FinalReply,
    Spend,
    TurnRequest,
    UserText,
    _place_call,
    _Progress,
    _reserve_call,
    _Reserved,
    default_reasoning_tokens,
)
from atlas_reviewer.ports import BoundaryError, TransportTimeoutError
from atlas_reviewer.pricing import PricingUnknownError
from atlas_reviewer.redact import Redactor

from .agentic import COST, LIMITS, READ_ALL, final
from .helpers import FakeClock
from .test_lens_loop import attempt
from .test_openrouter import catalog, completion, reply, zdr_payload
from .test_tool_model import model, request, sent

FULL = 64_000
BASE_USD = Decimal("0.10")
PER_TOKEN_USD = Decimal("0.00001")


@dataclass
class PricedModel(ScriptedLensModel):
    """Worst case = a fixed input part plus every output token."""

    def worst_case_usd(self, request):
        return BASE_USD + (request.max_output_tokens or FULL) * PER_TOKEN_USD

    def output_tokens_within(self, request, budget_usd):
        return min(FULL, math.floor((budget_usd - BASE_USD) / PER_TOKEN_USD))


def spent(committed, limits=LIMITS):
    spend = Spend(limits.resolve())
    spend.committed_usd = Decimal(committed)
    # The committed spend is fully settled: a fixture has nothing in
    # flight, so a refused call stops outright instead of waiting out the
    # backpressure backstop for a settle that will never come.
    spend.settled_usd = Decimal(committed)
    return spend


def test_a_call_over_the_reservation_is_sent_with_the_cap_it_can_cover(tmp_path):
    the_model = PricedModel([READ_ALL, final()])
    spend = spent("0.50")
    outcome, _, _ = attempt(tmp_path, [], model=the_model, spend=spend)
    assert outcome.state is LensState.CLEAN
    assert the_model.requests[0].max_output_tokens == 40_000
    assert all(r.max_output_tokens <= 40_000 for r in the_model.requests)
    assert spend.committed_usd <= LIMITS.reservation_usd


def test_a_call_that_fits_whole_keeps_the_models_cap(tmp_path):
    the_model = PricedModel([READ_ALL, final()])
    outcome, _, _ = attempt(tmp_path, [], model=the_model)
    assert outcome.state is LensState.CLEAN
    assert the_model.requests[0].max_output_tokens is None


def test_a_cap_under_the_floor_stops_on_the_reservation_and_says_why(tmp_path):
    the_model = PricedModel([READ_ALL, final()])
    outcome, _, _ = attempt(tmp_path, [], model=the_model, spend=spent("0.85"))
    assert Cause.BUDGET in outcome.causes
    assert the_model.requests == []
    assert outcome.limit_hit is not None
    assert outcome.limit_hit.limit == "reservation_usd"
    assert "covers 5000 output tokens, under min_output_tokens 16000" in (
        outcome.limit_hit.observed
    )
    assert "ATLAS_MIN_OUTPUT_TOKENS" in outcome.limit_hit.observed


def test_a_lower_floor_lets_the_last_dollars_run(tmp_path):
    low = replace(LIMITS, min_output_tokens=4_000)
    the_model = PricedModel([final()])
    attempt(tmp_path, [], model=the_model, limits=low, spend=spent("0.85", low))
    assert the_model.requests[0].max_output_tokens == 5_000


def test_a_fitted_call_that_fails_names_the_fitted_cap(tmp_path):
    once = replace(LIMITS, call_retries=0)
    the_model = PricedModel([BoundaryError("finish_reason=length")])
    outcome, _, _ = attempt(
        tmp_path, [], model=the_model, limits=once, spend=spent("0.50", once)
    )
    assert Cause.MODEL_ERROR in outcome.causes
    assert "finish_reason=length (output cap fitted to 40000 tokens)" in outcome.detail


def test_a_failed_calls_resend_takes_the_models_cap_again(tmp_path):
    """D92 amends round-1 review of #740: a failed call releases the
    reservation it held only while in flight and settles at $0, so the
    D49 resend prices against the remainder the failure left -- the whole
    reservation minus the seeded spend -- and fits whole at the model's
    cap. Kills the keep-the-worst mutant on the failed-call settle, which
    would shrink the resend's cap against a reservation the failed call
    no longer holds."""
    limits = replace(LIMITS, reservation_usd=Decimal("2.00"), min_output_tokens=10_000)
    the_model = PricedModel([BoundaryError("boom"), READ_ALL, final()])
    outcome, _, spend = attempt(
        tmp_path, [], model=the_model, limits=limits, spend=spent("1.00", limits)
    )
    assert outcome.state is LensState.CLEAN
    assert [r.max_output_tokens for r in the_model.requests] == [None, None, None]
    assert spend.calls == 3
    assert spend.committed_usd == Decimal("1.00") + 2 * COST


def test_a_timeout_resend_refits_against_the_remainder_then_left(tmp_path):
    """Round-1 review of #740, as D92's fix round settles the rule: the
    D58 resend of a timed-out request goes through the reservation-short
    path -- the timed-out send kept its reservation as spent (D58 item 5,
    restored: the request was written, the provider may have billed it) --
    and the resend re-fits against the remainder at that time. Kills the
    release mutant on the timeout settle, which would fit the resend at
    the model's whole cap."""
    limits = replace(LIMITS, reservation_usd=Decimal("2.00"), min_output_tokens=10_000)
    the_model = PricedModel(
        [TransportTimeoutError("the request timed out"), READ_ALL, final()]
    )
    outcome, _, spend = attempt(
        tmp_path, [], model=the_model, limits=limits, spend=spent("1.00", limits)
    )
    assert outcome.state is LensState.CLEAN
    assert [r.max_output_tokens for r in the_model.requests] == [None, 16_000, 14_000]
    assert spend.calls == 3


def test_the_floor_is_configurable_and_at_least_two():
    assert AgenticLimits().resolve().min_output_tokens == 16_000
    assert (
        load_agentic_limits({"ATLAS_MIN_OUTPUT_TOKENS": "2000"}).min_output_tokens
        == 2000
    )
    with pytest.raises(ValueError, match="min_output_tokens"):
        load_agentic_limits({"ATLAS_MIN_OUTPUT_TOKENS": "1"})


def test_a_negative_remainder_is_shown_at_zero_in_the_fit_stop(tmp_path):
    """Round-1 review of #740: spend can sit past its reservation (a
    settle that reported above its own worst case), and the fit's stop
    then rendered the negative remainder as `$-0.50`. The stop shows the
    remainder at zero; what it could cover is already clamped to zero."""
    the_model = PricedModel([READ_ALL, final()])
    outcome, _, _ = attempt(tmp_path, [], model=the_model, spend=spent("1.50"))
    assert Cause.BUDGET in outcome.causes
    assert outcome.limit_hit is not None
    assert "$-0.50" not in outcome.limit_hit.observed
    assert "the $0 left covers 0 output tokens" in outcome.limit_hit.observed


def test_a_fit_that_cannot_compute_keeps_the_remainder_in_the_stop(tmp_path):
    """Round-1 review of #740: when the model cannot answer the fit, the
    refusal stands but keeps the remainder it was fitting against and the
    reason, so the stop still says what the reservation had left."""

    class Unfittable(PricedModel):
        def output_tokens_within(self, request, budget_usd):
            raise BoundaryError("the catalog is unreachable")

    the_model = Unfittable([READ_ALL, final()])
    outcome, _, _ = attempt(tmp_path, [], model=the_model, spend=spent("0.50"))
    assert Cause.BUDGET in outcome.causes
    assert outcome.limit_hit is not None
    assert "the $0.50 left could not be fitted" in outcome.limit_hit.observed
    assert "the catalog is unreachable" in outcome.limit_hit.observed


def test_the_traced_wrapper_carries_every_protocol_member():
    """Round-1 review of #740, Major: the traced wrapper wraps every
    production lens model, so a `LensModel` member it fails to forward is
    an `AttributeError` at the worst moment -- the reservation-short fit.
    The wrapper is checked against the protocol itself, so a member added
    to the protocol later cannot be forgotten here."""
    from atlas_reviewer.lens_loop import LensModel
    from atlas_reviewer.tracing import _TracedModel

    for member in LensModel.__protocol_attrs__:
        assert hasattr(_TracedModel, member), member


def test_the_fit_runs_through_the_real_traced_wrapper():
    """Round-1 review of #740, Major: the fit must run through the traced
    wrapper every production review places its calls behind. A
    reservation-short call reserves with the fitted cap instead of dying
    in the wrapper's missing `output_tokens_within`."""
    from atlas_reviewer.tracing import memory_trace

    lens, _fake = model(reply(completion("ok")))
    low = replace(LIMITS, reservation_usd=Decimal("5.00"), min_output_tokens=100)
    trace, _exporter = memory_trace(str)
    try:
        wrapped = trace.wrap_model(lens)
        clock = FakeClock()
        reserved = _reserve_call(
            wrapped, request(), spent("4.50", low), clock, clock.monotonic() + 600
        )
    finally:
        trace.shutdown()
    assert isinstance(reserved, _Reserved)
    assert reserved.request.max_output_tokens is not None
    assert 0 < reserved.request.max_output_tokens < FULL
    assert reserved.worst <= low.reservation_usd - Decimal("4.50")


def test_the_live_model_fits_a_cap_whose_worst_case_is_in_the_budget():
    """The fit's contract is safety first, tightness second: the worst
    case of the returned cap stays within the budget, and the cap is the
    largest within the fit's own whole-payload arithmetic -- not globally,
    because the worst case is not monotonic in the cap across the
    reasoning-hint halving regime (D50: the hint is
    `min(output // 2, REASONING_HINT_CAP)`), and the adapter's metered
    bound can realize one token more headroom than that arithmetic. The
    assertions sweep several budgets so a prompt or schema byte change
    that moves the fitted cap onto or off a regime boundary shifts which
    budget is exercised, not whether the suite passes: safety must hold at
    every budget, and the realized maximum may sit at most one token above
    the returned cap (the fit's whole-payload bound is conservative by at
    most the per-message overhead). The fee is set at or above the
    per-token rate, so the fee-drop mutant shifts the fit's floor by at
    least one token and overshoots the budget, dying on the safety
    assertion. The prices live on the ZDR endpoint rows, because
    `load_terms` prices from the rows the route selected, not from the
    catalog's headline numbers."""
    lens, fake = model(
        reply(completion("ok")),
        zdr=reply(
            zdr_payload(pricing={"internal_reasoning": "0.000006", "request": "0.0001"})
        ),
    )
    full = lens.worst_case_usd(request())
    cap = FULL
    for fraction in (1, 2, 3, 5, 8, 10):
        budget = full * fraction / 21
        cap = lens.output_tokens_within(request(), budget)
        assert 0 < cap <= FULL
        fitted = replace(request(), max_output_tokens=cap)
        # Safety: the invariant the spend protection depends on.
        assert lens.worst_case_usd(fitted) <= budget
        # Tightness within one token: scan upward for the realized maximum
        # and require it to sit at most one token above the returned cap.
        # The scan stops at FULL: the resolved cap is the contract's ceiling.
        realized = cap
        ceiling = min(cap + 1, FULL)
        while (
            realized < ceiling
            and lens.worst_case_usd(replace(request(), max_output_tokens=realized + 1))
            <= budget
        ):
            realized += 1
        assert realized <= cap + 1
        assert realized >= cap
    lens.turn(replace(request(), max_output_tokens=cap))
    body = sent(fake)
    hint = default_reasoning_tokens(FULL)
    if hint >= cap:
        hint = default_reasoning_tokens(cap)
    assert body["max_tokens"] == cap
    assert body["reasoning"]["max_tokens"] == hint
    assert cap - hint > 1


def test_the_fit_is_safe_on_both_sides_of_the_hint_halving_regime_edge():
    """The hint's regime boundary sits at twice `REASONING_HINT_CAP`:
    below it the hint grows with the cap, from there up the hint is the
    constant cap. A cap fitted right at the edge pins the boundary on
    purpose, so a prompt or schema byte change that moves the fitted cap
    across it changes what this test exercises, never whether it passes:
    safety and one-token tightness must hold on both sides, and the sent
    body's hint must be the capped one above the edge."""
    lens, fake = model(
        reply(completion("ok")),
        zdr=reply(
            zdr_payload(pricing={"internal_reasoning": "0.000006", "request": "0.0001"})
        ),
    )
    full = lens.worst_case_usd(request())
    edge = 2 * REASONING_HINT_CAP
    assert default_reasoning_tokens(edge - 1) == REASONING_HINT_CAP - 1
    assert default_reasoning_tokens(edge) == REASONING_HINT_CAP
    assert default_reasoning_tokens(edge + 1) == REASONING_HINT_CAP
    # The first token past the edge is where the cap bites: the uncapped
    # half would be one over, so an implementation that ignores the
    # halving regime's cap is caught here and not at the boundary itself,
    # where the two agree.
    assert default_reasoning_tokens(edge + 2) == REASONING_HINT_CAP
    budgets = {}
    low, high = full / 64, full
    for target in (edge - 1, edge, edge + 1):
        while lens.output_tokens_within(request(), low) > target:
            low /= 2
        probe = high
        while lens.output_tokens_within(request(), probe) < target:
            probe = (probe + high) / 2
        hi, lo = probe, low
        for _ in range(80):
            mid = (hi + lo) / 2
            if lens.output_tokens_within(request(), mid) >= target:
                hi = mid
            else:
                lo = mid
        budgets[target] = hi
    for target, budget in budgets.items():
        cap = lens.output_tokens_within(request(), budget)
        assert cap == target
        fitted = replace(request(), max_output_tokens=cap)
        assert lens.worst_case_usd(fitted) <= budget
        realized = cap
        while (
            lens.worst_case_usd(replace(request(), max_output_tokens=realized + 1))
            <= budget
        ):
            realized += 1
            assert realized <= cap + 1
        assert realized >= cap
    lens.turn(replace(request(), max_output_tokens=edge + 2))
    body = sent(fake)
    assert body["max_tokens"] == edge + 2
    assert body["reasoning"]["max_tokens"] == REASONING_HINT_CAP


def test_the_fit_fits_the_same_per_token_rate_the_reservation_prices():
    """Issue #750: the fit priced an output token at the completion rate
    PLUS the reasoning rate while the reservation (amended by the same
    issue) prices the higher of the two, so a fitted cap came back
    smaller than the budget could cover and one more token of cap still
    fit -- failing the maximality pins below on a route whose reasoning
    rate differs from its completion rate. The fixture's reasoning rate
    ($50/M) sits above its completion rate ($22.5/M), so only the
    per-token maximum fits both pins."""
    lens, _fake = model(
        reply(completion("ok")),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    full = lens.worst_case_usd(request())
    budget = full / 2
    cap = lens.output_tokens_within(request(), budget)
    assert 0 < cap < FULL
    assert lens.worst_case_usd(replace(request(), max_output_tokens=cap)) <= budget
    assert lens.worst_case_usd(replace(request(), max_output_tokens=cap + 1)) > budget


def test_the_live_model_never_fits_past_the_resolved_cap_or_under_the_input():
    lens, _ = model()
    assert lens.output_tokens_within(request(), Decimal(1000)) == FULL
    assert lens.output_tokens_within(request(), Decimal(0)) < 1
    free, _ = model(catalog_reply=reply(_free_output()))
    with pytest.raises(PricingUnknownError, match="completion is zero"):
        free.output_tokens_within(request(), Decimal(1))


def _free_output():
    return catalog(completion="0", overrides=None)


_PLACE_SYSTEM = "You are one lens. Read the change with the tools."


def _placed(model, spend, clock, request=None):
    """One placed call through `_place_call`, the loop's own price, reserve,
    send and settle path."""
    clock.advance(0.001)
    return _place_call(
        request or TurnRequest(_PLACE_SYSTEM, (), (UserText("Review the change."),)),
        model,
        spend,
        _Progress(),
        clock,
        clock.monotonic() + 600,
        None,
        clock.monotonic() + 600,
        clock.monotonic() + 600,
    )


def test_a_large_reviews_settles_free_the_ceiling_and_its_keeps_stop_it():
    """Issue #750's recorded shape, pinned with fakes. On the #702 heads
    every turn reserved about a quarter of the $10 per-review ceiling (a
    near-cap input bound plus the whole output cap at the modeled rates),
    so four kept worst cases filled the ceiling and the fifth lens's
    first call stopped the review on `reservation_usd` while the real
    spend stayed far under it. Pinned both ways at the loop's own
    price-reserve-send-settle path: settles that price free the room and
    the review keeps placing calls; settles that cannot price keep the
    full reservation as spent (D43, unchanged) and the fifth call is the
    recorded `reservation_usd` stop, named for the ceiling it passed."""
    worst = Decimal("2.50")
    ask = TurnRequest(_PLACE_SYSTEM, (), (UserText("Review the change."),))

    priced = Spend(replace(LIMITS, reservation_usd=Decimal("10.00")).resolve())
    clock = FakeClock()
    model = ScriptedLensModel([final()] * 5, worst_usd=worst)
    for _ in range(5):
        turn = _placed(model, priced, clock, ask)
        assert isinstance(turn, FinalReply), turn
    assert priced.calls == 5
    assert priced.committed_usd == 5 * COST
    assert priced.settled_usd == 5 * COST

    keeps = Spend(replace(LIMITS, reservation_usd=Decimal("10.00")).resolve())
    clock = FakeClock()
    unpriced = ScriptedLensModel(
        [FinalReply("x", Decimal("Infinity"))] * 5, worst_usd=worst
    )
    for _ in range(4):
        turn = _placed(unpriced, keeps, clock, ask)
        assert isinstance(turn, FinalReply), turn
    assert keeps.calls == 4
    assert keeps.committed_usd == Decimal("10.00")
    outcome = _placed(unpriced, keeps, clock, ask)
    assert isinstance(outcome, AttemptOutcome)
    assert Cause.BUDGET in outcome.causes
    assert outcome.limit_hit is not None
    assert outcome.limit_hit.limit == "reservation_usd"
    assert "$12.50" in outcome.limit_hit.observed


def test_a_reservation_projecting_exactly_to_the_ceiling_is_accepted():
    """Round-1 review of #757, Nit: spend never passes the cap, and a
    projection equal to it is not past it -- D68's ceiling is a ceiling,
    not an exclusive bound. Kills the `>` to `>=` mutant, which would
    spuriously stop a review whose reservations fit its ceiling
    exactly."""
    spend = Spend(replace(LIMITS, reservation_usd=Decimal("1.00")).resolve())
    assert spend.reserve(Decimal("0.60")) is None
    assert spend.reserve(Decimal("0.40")) is None
    assert spend.committed_usd == Decimal("1.00")
    stop = spend.reserve(Decimal("0.01"))
    assert stop is not None
    assert stop.limit == "reservation_usd"


def test_a_settle_above_its_worst_case_is_recorded_as_an_overrun():
    """Round-1 review of #757, Minor 1: D82's subset assumption can fail
    on a route that bills reasoning tokens outside its output cap, and
    the one event that would reveal it -- a settle whose reported cost
    exceeds the worst case reserved for the call -- must leave a trace.
    The accounting moves committed spend to the reported actual, which
    can sit above the reservation; the
    overrun note is the draft-visible signal and the condition D82's
    revisit trigger names. A settle at the worst case, and an unpriced
    settle, record nothing."""
    spend = Spend(replace(LIMITS, reservation_usd=Decimal("1.00")).resolve())
    assert spend.reserve(Decimal("0.50")) is None
    spend.settle(Decimal("0.50"), Decimal("0.75"))
    assert spend.committed_usd == Decimal("0.75")
    assert spend.overruns == ["settled $0.7500 above its $0.5000 worst case"]

    at_bound = Spend(replace(LIMITS, reservation_usd=Decimal("1.00")).resolve())
    assert at_bound.reserve(Decimal("0.50")) is None
    at_bound.settle(Decimal("0.50"), Decimal("0.50"))
    assert at_bound.overruns == []

    unpriced = Spend(replace(LIMITS, reservation_usd=Decimal("1.00")).resolve())
    assert unpriced.reserve(Decimal("0.50")) is None
    unpriced.settle(Decimal("0.50"), None)
    assert unpriced.overruns == []


def test_the_overrun_rides_the_drafts_cost_line():
    """Round-1 review of #757, Minor 1: the tripwire is only observable
    when the draft carries it. The overrun notes join the one
    `Model calls:` cost line -- the line the posted Cost section renders
    and the cost event parses -- not the limit stops, which a settle
    above its reservation is not."""
    spend = Spend(replace(LIMITS, reservation_usd=Decimal("1.00")).resolve())
    assert spend.reserve(Decimal("0.50")) is None
    spend.settle(Decimal("0.50"), Decimal("0.75"))
    review = synthesize([], spend=spend)
    assert review.settle_overruns == ("settled $0.7500 above its $0.5000 worst case",)
    line = next(
        line
        for line in render_draft(review, Redactor()).splitlines()
        if line.startswith("Model calls:")
    )
    assert (
        "1 settle(s) reported a cost above their reservation (D82's tripwire): "
        "settled $0.7500 above its $0.5000 worst case" in line
    )
    clean = synthesize(
        [], spend=Spend(replace(LIMITS, reservation_usd=Decimal("1.00")).resolve())
    )
    assert "settle(s)" not in render_draft(clean, Redactor())


def test_the_fit_walks_up_to_the_true_whole_payload_boundary():
    """The cap sits inside the request payload, whose byte count moves
    with the cap's own digits, so the linear solve can sit a token below
    the true whole-payload boundary. The walk-up climbs while the exact
    whole-payload arithmetic still fits: across a sweep of budgets, the
    returned cap is the true boundary -- its own worst case within the
    budget, and one more token's whole-payload worst case over it (or the
    resolved cap, when everything fits). Without the walk-up some budget
    in the sweep returns a cap one token under its boundary, so this pins
    the climb, not just safety."""
    lens, _fake = model(
        reply(completion("ok")),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    full = lens.worst_case_usd(request())
    under = []
    for step in range(1, 25):
        budget = full * step / 25
        cap = lens.output_tokens_within(request(), budget)
        assert 0 < cap <= FULL
        assert (
            lens.worst_case_usd(replace(request(), max_output_tokens=cap)) <= budget
        ), (
            step,
            cap,
        )
        boundary = (
            cap == FULL
            or lens.worst_case_usd(replace(request(), max_output_tokens=cap + 1))
            > budget
        )
        if not boundary:
            under.append((step, cap))
    assert under == [], under


def test_the_fit_walkup_checks_are_logarithmic(monkeypatch):
    """The climb gallops -- the step doubles each fitting check, then the
    bracket is refined -- so a pathological rate table cannot walk the
    whole cap range one linear step at a time. The whole-payload checks
    the fitter makes for one request are bounded logarithmically in the
    cap range, not linearly."""
    lens, _fake = model(
        reply(completion("ok")),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    calls = []
    original = lens._fits_within

    def counting(request, cap, terms, selected, budget_usd):
        calls.append(cap)
        return original(request, cap, terms, selected, budget_usd)

    monkeypatch.setattr(lens, "_fits_within", counting)
    cap = lens.output_tokens_within(request(), Decimal("0.05"))
    assert 0 < cap <= FULL
    # 64k tokens of headroom: a linear climb would check tens of
    # thousands of candidates; the gallop-and-refine is tens.
    assert len(calls) <= 40, len(calls)


def test_the_fit_walkup_gallops_when_the_start_sits_far_below_the_boundary(
    monkeypatch,
):
    """The linear solve's gap is digit-count effects -- a token or a few
    -- so a climb from the solved cap exercises the gallop only if the
    start sits far below the boundary. This fixture widens the gap by
    the reviewer's own lever: the payload's size shrinks materially as
    the cap shrinks (the uncapped payload the linear solve prices is the
    largest), so the true boundary sits thousands of tokens above the
    linear solve's cap. A linear climb would make thousands of
    whole-payload checks; the gallop-and-refine must stay within the
    same logarithmic bound while returning a cap at the true boundary
    (safety, and one more token over it)."""
    import atlas_reviewer.tool_model as tool_model_module

    lens, _fake = model(
        reply(completion("ok")),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    original_payload = tool_model_module._payload
    # 40 bytes of padding per token of headroom below the resolved cap,
    # and the most on the uncapped payload the linear solve prices: the
    # uncapped request carries ~2.5 MB the near-cap candidates drop, so
    # the linear solve's fixed input cost is enormous and its cap lands
    # thousands of tokens below where the whole-payload arithmetic stops
    # fitting -- and each climbed token's payload shrinks faster (10
    # input tokens' worth) than the output token costs, so the fitted
    # candidates keep fitting all the way to the resolved cap.

    def shrinking_payload(provider, request, terms, limits, selected):
        payload = original_payload(provider, request, terms, limits, selected)
        headroom = FULL - (request.max_output_tokens or 0)
        if headroom:
            padded = []
            for message in payload["messages"]:
                content = message.get("content")
                if isinstance(content, str):
                    message = dict(message, content=content + "x" * (headroom * 40))
                padded.append(message)
            payload["messages"] = padded
        return payload

    monkeypatch.setattr(tool_model_module, "_payload", shrinking_payload)
    calls = []
    original_fits = lens._fits_within

    def counting(request, cap, terms, selected, budget_usd):
        calls.append(cap)
        return original_fits(request, cap, terms, selected, budget_usd)

    monkeypatch.setattr(lens, "_fits_within", counting)

    # A budget just over the uncapped payload's own input cost: the
    # linear solve can afford only a few hundred output tokens on top of
    # it, while every climbed candidate's shrinking payload leaves the
    # whole headroom affordable.
    import json

    uncapped = replace(request(), max_output_tokens=None)
    terms, _, selected = lens._ready()
    bounds = tool_model_module._bounds(lens.per_call, terms, uncapped)
    payload = tool_model_module._payload(
        lens.provider, uncapped, terms, bounds, selected
    )
    fixed = tool_model_module.input_token_bound(json.dumps(payload)) * terms.input_rate
    budget = fixed + terms.request_fee + Decimal("0.001")
    cap = lens.output_tokens_within(request(), budget)
    assert 0 < cap <= FULL
    # The boundary is asserted in the patched arithmetic -- the same fits
    # predicate the climb verified with (the real-world safety pin is the
    # sweep test's, which runs unpatched): the returned cap fits, and one
    # more token does not.
    terms, _, selected = lens._ready()
    assert lens._fits_within(request(), cap, terms, selected, budget)
    assert cap == FULL or not lens._fits_within(
        request(), cap + 1, terms, selected, budget
    )
    # The climb stayed logarithmic: the first check names the linear
    # solve's start (cap_linear + 1), and the gap it closed is wide --
    # a linear climb over it would check thousands of candidates, the
    # gallop-and-refine stays within the bound.
    assert cap - calls[0] > 1000, (cap, calls[0])
    assert len(calls) <= 40, len(calls)
