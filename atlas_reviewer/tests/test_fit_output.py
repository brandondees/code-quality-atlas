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
from atlas_reviewer.lens_loop import AgenticLimits, Spend, default_reasoning_tokens
from atlas_reviewer.ports import BoundaryError

from .agentic import LIMITS, READ_ALL, final
from .test_lens_loop import attempt
from .test_openrouter import catalog, completion, reply
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


def test_the_floor_is_configurable_and_at_least_two():
    assert AgenticLimits().resolve().min_output_tokens == 16_000
    assert (
        load_agentic_limits({"ATLAS_MIN_OUTPUT_TOKENS": "2000"}).min_output_tokens
        == 2000
    )
    with pytest.raises(ValueError, match="min_output_tokens"):
        load_agentic_limits({"ATLAS_MIN_OUTPUT_TOKENS": "1"})


def test_the_live_model_fits_a_cap_whose_worst_case_is_in_the_budget():
    lens, fake = model(reply(completion("ok")))
    full = lens.worst_case_usd(request())
    budget = full / 2
    cap = lens.output_tokens_within(request(), budget)
    assert 0 < cap < FULL
    assert lens.worst_case_usd(replace(request(), max_output_tokens=cap)) <= budget
    lens.turn(replace(request(), max_output_tokens=cap))
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
    assert free.output_tokens_within(request(), Decimal(1)) == FULL
    assert free.output_tokens_within(request(), Decimal(0)) == 0


def _free_output():
    return catalog(completion="0", overrides=None)
