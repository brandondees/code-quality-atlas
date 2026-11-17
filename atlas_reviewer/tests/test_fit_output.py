# SPDX-License-Identifier: MIT
"""A call the reservation cannot cover at the model's full output cap is
sent with a smaller cap that it can cover, down to `min_output_tokens`."""

import math
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.attestation import Cause, LensState
from atlas_reviewer.fakes import ScriptedLensModel
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    Spend,
    _reserve_call,
    _Reserved,
    default_reasoning_tokens,
)
from atlas_reviewer.ports import BoundaryError, TransportTimeoutError
from atlas_reviewer.pricing import PricingUnknownError

from .agentic import LIMITS, READ_ALL, final
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


def test_a_failed_calls_resend_refits_against_the_remainder_then_left(tmp_path):
    """Round-1 review of #740: the D49 resend of a failed call goes
    through the reservation-short path and re-fits against the remainder
    at that time. The first send fits whole at the model's cap, fails,
    and settles at its reservation; the resend is short against what is
    left and takes a smaller cap; the next turn's call takes a smaller
    one still, so a shrinking remainder tracks the sends it bought."""
    limits = replace(LIMITS, reservation_usd=Decimal("2.00"), min_output_tokens=10_000)
    the_model = PricedModel([BoundaryError("boom"), READ_ALL, final()])
    outcome, _, spend = attempt(
        tmp_path, [], model=the_model, limits=limits, spend=spent("1.00", limits)
    )
    assert outcome.state is LensState.CLEAN
    assert [r.max_output_tokens for r in the_model.requests] == [None, 16_000, 14_000]
    assert spend.calls == 3


def test_a_timeout_resend_refits_against_the_remainder_then_left(tmp_path):
    """Round-1 review of #740: the D58 resend of a timed-out request goes
    through the reservation-short path the same way -- the timed-out send
    kept its reservation as spent, and the resend re-fits against the
    remainder at that time."""
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
    """The fixture prices reasoning and the per-request fee nonzero
    (round-1 review of #740), so a mutant dropping the reasoning term or
    the request fee from the fit's rate math returns a cap whose true
    worst case overshoots the budget and dies on the two assertions
    below: the fit's cap must fit the budget, and one more token of cap
    must not (maximality). The fee is set at or above the per-token rate,
    so the fee-drop mutant shifts the fit's floor by at least one token
    and cannot hide in the floor's rounding slack. The prices live on the
    ZDR endpoint rows, because `load_terms` prices from the rows the
    route selected, not from the catalog's headline numbers."""
    lens, fake = model(
        reply(completion("ok")),
        zdr=reply(
            zdr_payload(pricing={"internal_reasoning": "0.000006", "request": "0.0001"})
        ),
    )
    full = lens.worst_case_usd(request())
    budget = full / 2
    cap = lens.output_tokens_within(request(), budget)
    assert 0 < cap < FULL
    fitted = replace(request(), max_output_tokens=cap)
    assert lens.worst_case_usd(fitted) <= budget
    over = replace(request(), max_output_tokens=cap + 1)
    assert lens.worst_case_usd(over) > budget
    lens.turn(fitted)
    body = sent(fake)
    hint = default_reasoning_tokens(FULL)
    if hint >= cap:
        hint = default_reasoning_tokens(cap)
    assert body["max_tokens"] == cap
    assert body["reasoning"]["max_tokens"] == hint
    assert cap - hint > 1


def test_the_live_model_never_fits_past_the_resolved_cap_or_under_the_input():
    lens, _ = model()
    assert lens.output_tokens_within(request(), Decimal(1000)) == FULL
    assert lens.output_tokens_within(request(), Decimal(0)) < 1
    free, _ = model(catalog_reply=reply(_free_output()))
    with pytest.raises(PricingUnknownError, match="completion is zero"):
        free.output_tokens_within(request(), Decimal(1))


def _free_output():
    return catalog(completion="0", overrides=None)
