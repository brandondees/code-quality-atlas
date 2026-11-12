# SPDX-License-Identifier: MIT
"""Agentic per-call limits: model-aware defaults, configuration, and a
stop that names the limit instead of a generic model error."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from atlas_reviewer.agentic_config import load_agentic_limits
from atlas_reviewer.attestation import AttemptLedger, Cause, LensState
from atlas_reviewer.budget import CallLimits
from atlas_reviewer.coordinator import status_line, synthesize
from atlas_reviewer.lens_loop import (
    _LIMIT_CAUSES,
    AgenticLimits,
    Spend,
    _cause_for,
    resolve_per_call,
    run_attempt,
)
from atlas_reviewer.limit_stop import SETTINGS, LimitHit, LimitRefused, hit
from atlas_reviewer.openrouter import MODEL_ID
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.pricing import PricingUnknownError, parse_model_terms
from atlas_reviewer.verdict import parse_status

from .agentic import LIMITS
from .helpers import FakeClock
from .test_attestation import KEY
from .test_coordinator import lens_result
from .test_lens_loop import job
from .test_openrouter import catalog, completion, reply
from .test_tool_model import model, request, sent


def test_unset_limits_keep_the_defaults_and_derive_per_call_bounds():
    limits = load_agentic_limits({})
    resolved = limits.resolve()
    assert (resolved.max_calls, resolved.reservation_usd) == (50, Decimal(5))
    assert resolved.max_input_tokens is None
    terms = parse_model_terms(catalog(), MODEL_ID)
    call = resolve_per_call(resolved, terms)
    assert (call.max_output_tokens, call.reasoning_max_tokens) == (64_000, 63_999)
    assert call.max_input_tokens == 1_000_000 - 64_000


def test_a_flag_wins_over_the_environment_and_can_only_tighten():
    limits = load_agentic_limits(
        {
            "ATLAS_MAX_CALLS": "10",
            "ATLAS_MAX_TURNS": "4",
            "ATLAS_MAX_INPUT_TOKENS": "5000",
        },
        max_calls="4",
    )
    assert (limits.max_calls, limits.max_input_tokens) == (4, 5000)
    terms = parse_model_terms(catalog(), MODEL_ID)
    assert resolve_per_call(limits.resolve(), terms).max_input_tokens == 5000
    with pytest.raises(LimitRefused, match="max_input_tokens"):
        resolve_per_call(replace(limits.resolve(), max_input_tokens=2_000_000), terms)


def test_an_unparseable_limit_is_refused():
    with pytest.raises(ValueError, match="max_turns"):
        load_agentic_limits({"ATLAS_MAX_TURNS": "nope"})
    with pytest.raises(ValueError, match="max_turns"):
        load_agentic_limits({}, max_turns="80", max_calls="10")


def test_the_output_default_is_the_models_and_an_override_cannot_exceed_it():
    terms = parse_model_terms(catalog(), MODEL_ID)
    over = replace(AgenticLimits().resolve(), max_output_tokens=128_000)
    with pytest.raises(LimitRefused, match="max_output_tokens") as raised:
        resolve_per_call(over, terms)
    assert raised.value.hit.observed == "64000"
    assert raised.value.hit.setting.endswith("ATLAS_MAX_OUTPUT_TOKENS")


def test_the_adapter_sends_the_model_caps_and_ignores_the_reasoning_hint():
    lens, fake = model(reply(completion("ok")))
    lens.turn(request())
    body = sent(fake)
    assert body["max_tokens"] == 64_000
    assert body["reasoning"]["max_tokens"] == 63_999

    priced = reply(catalog(internal_reasoning="0.00002"))
    low, low_fake = model(reply(completion("ok")), catalog_reply=priced)
    high, high_fake = model(reply(completion("ok")), catalog_reply=priced)
    low.per_call = replace(
        AgenticLimits().resolve(), max_output_tokens=4_000, reasoning_max_tokens=100
    )
    high.per_call = replace(
        AgenticLimits().resolve(), max_output_tokens=4_000, reasoning_max_tokens=3_000
    )
    # The hint is inside the request body, so a longer number costs a few
    # input tokens. It must not be priced as 2,900 extra reasoning tokens.
    delta = abs(low.worst_case_usd(request()) - high.worst_case_usd(request()))
    assert delta < Decimal("0.01")
    low.turn(request())
    high.turn(request())
    assert sent(low_fake)["reasoning"]["max_tokens"] == 100
    assert sent(high_fake)["reasoning"]["max_tokens"] == 3_000


def test_a_prompt_over_the_input_cap_names_the_limit_and_is_not_sent():
    lens, fake = model(reply(completion("ok")))
    lens.per_call = replace(AgenticLimits().resolve(), max_input_tokens=8)
    with pytest.raises(LimitRefused, match="max_input_tokens") as raised:
        lens.worst_case_usd(request())
    assert raised.value.hit.setting.endswith("ATLAS_MAX_INPUT_TOKENS")
    assert int(raised.value.hit.observed) > int(raised.value.hit.configured)
    assert fake.chat_requests() == []


def test_a_missing_context_length_refuses_before_a_call():
    data = catalog()
    del data["data"]["context_length"]
    lens, fake = model(reply(completion("ok")), catalog_reply=reply(data))
    with pytest.raises((PricingUnknownError, BoundaryError)):
        lens.worst_case_usd(request())
    assert fake.chat_requests() == []


def test_the_loop_records_an_input_cap_as_its_own_cause():
    class Capped:
        name = "capped"

        def worst_case_usd(self, _request):
            raise LimitRefused(hit("max_input_tokens", 8, 400))

        def turn(self, _request):
            raise AssertionError("the refused call must not be sent")

    outcome = run_attempt(
        job(),
        object(),
        Capped(),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
    )
    assert Cause.INPUT_CAP in outcome.causes
    assert Cause.MODEL_ERROR not in outcome.causes
    assert outcome.limit_hit is not None
    assert outcome.limit_hit.observed == "400"
    parsed = parse_status(status_line(synthesize([lens_result(outcome)])))
    assert parsed is not None
    assert parsed["limit_stop"] == outcome.limit_hit.as_dict()


def test_a_limit_hit_round_trips_through_the_ledger(tmp_path):
    class Capped:
        name = "capped"

        def worst_case_usd(self, _request):
            raise LimitRefused(hit("context_length", 1000, 5000))

        def turn(self, _request):
            raise AssertionError("not sent")

    outcome = run_attempt(
        job(),
        object(),
        Capped(),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
    )
    path = tmp_path / "ledger.jsonl"
    book = AttemptLedger(path, FakeClock())
    book.finish(KEY, 1, outcome, scrub=str)
    (attempt,) = AttemptLedger(path, FakeClock()).attempts(KEY)
    assert attempt.outcome.limit_hit == outcome.limit_hit
    assert Cause.CONTEXT in attempt.outcome.causes


def test_the_one_shot_input_cap_stays_200k():
    assert CallLimits().max_input_tokens == 200_000
    assert CallLimits().max_calls == 3


def test_every_agentic_limit_can_be_set_and_a_bad_one_is_refused():
    limits = load_agentic_limits(
        {
            "ATLAS_RESERVATION_USD": "2.50",
            "ATLAS_LENS_WALL_S": "100",
            "ATLAS_REVIEW_WALL_S": "200",
            "ATLAS_MAX_OUTPUT_TOKENS": "4000",
            "ATLAS_REASONING_MAX_TOKENS": "1500",
            "ATLAS_MAX_CALLS": "",
        },
        max_calls="8",
        max_turns="6",
        max_input_tokens="1000",
    )
    assert limits.reservation_usd == Decimal("2.50")
    assert (limits.lens_wall_s, limits.review_wall_s) == (100.0, 200.0)
    assert (limits.max_output_tokens, limits.reasoning_max_tokens) == (4000, 1500)
    assert (limits.max_calls, limits.max_turns, limits.max_input_tokens) == (8, 6, 1000)
    with pytest.raises(ValueError, match="reservation_usd"):
        load_agentic_limits({"ATLAS_RESERVATION_USD": "nope"})
    with pytest.raises(ValueError, match="max_calls"):
        load_agentic_limits({"ATLAS_MAX_CALLS": "0"})
    with pytest.raises(ValueError, match="lens_wall_s"):
        load_agentic_limits({"ATLAS_LENS_WALL_S": "0"})
    with pytest.raises(ValueError, match="review_wall_s"):
        load_agentic_limits({"ATLAS_REVIEW_WALL_S": "later"})
    with pytest.raises(ValueError, match="unknown agentic limit"):
        load_agentic_limits({}, nope="1")


def test_a_per_call_override_must_be_a_positive_int_the_model_can_hold():
    with pytest.raises(ValueError, match="max_input_tokens"):
        AgenticLimits(max_input_tokens=True).resolve()
    with pytest.raises(ValueError, match="reasoning_max_tokens"):
        AgenticLimits(max_output_tokens=100, reasoning_max_tokens=100).resolve()
    terms = parse_model_terms(catalog(), MODEL_ID)
    base = AgenticLimits().resolve()
    with pytest.raises(LimitRefused, match="max_output_tokens"):
        resolve_per_call(replace(base, max_output_tokens=1), terms)
    with pytest.raises(LimitRefused, match="reasoning_max_tokens"):
        resolve_per_call(
            replace(base, max_output_tokens=100, reasoning_max_tokens=0), terms
        )
    with pytest.raises(LimitRefused, match="max_input_tokens"):
        resolve_per_call(replace(base, max_input_tokens=950_000), terms)
    tight = replace(terms, context_length=64_000, max_completion_tokens=64_000)
    with pytest.raises(LimitRefused, match="context_length") as raised:
        resolve_per_call(base, tight)
    assert "catalog context_length" in raised.value.hit.setting
    with pytest.raises(ValueError, match="unknown limit"):
        hit("not-a-limit", 1, 2)


def test_a_limit_refused_on_the_turn_is_not_a_model_error():
    class Capped:
        name = "capped"

        def worst_case_usd(self, _request):
            return Decimal("0.01")

        def turn(self, _request):
            raise LimitRefused(hit("max_completion_tokens", 64_000, 128_000))

    outcome = run_attempt(
        job(),
        object(),
        Capped(),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
    )
    assert outcome.causes == {Cause.CONTEXT, Cause.FILES_UNREAD}
    assert outcome.state is LensState.PARTIAL
    assert outcome.retryable is False
    assert outcome.limit_hit is not None
    assert "max_completion_tokens" in outcome.limit_hit.setting


def test_a_damaged_limit_object_abandons_the_ledger_line(tmp_path):
    class Capped:
        name = "capped"

        def worst_case_usd(self, _request):
            raise LimitRefused(hit("max_calls", 3, 4))

        def turn(self, _request):
            raise AssertionError("not sent")

    outcome = run_attempt(
        job(),
        object(),
        Capped(),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
    )
    path = tmp_path / "ledger.jsonl"
    book = AttemptLedger(path, FakeClock())
    book.start(KEY, 1)
    book.finish(KEY, 1, outcome, scrub=str)
    lines = path.read_text().splitlines()
    finished = json.loads(lines[-1])
    finished["outcome"]["limit"] = "max_calls"
    lines[-1] = json.dumps(finished)
    path.write_text("\n".join(lines) + "\n")
    again = AttemptLedger(path, FakeClock())
    (attempt,) = again.attempts(KEY)
    assert attempt.outcome.limit_hit is None
    assert again.damaged == 1


def test_every_limit_has_one_cause_and_an_unknown_name_is_refused():
    assert set(_LIMIT_CAUSES) == set(SETTINGS)
    with pytest.raises(ValueError, match="no cause"):
        _cause_for(LimitHit("not-a-limit", "1", "2", "nowhere"))


def test_an_output_override_and_a_reasoning_hint_have_their_own_causes():
    class Refuses:
        name = "refuses"

        def __init__(self, found):
            self.found = found

        def worst_case_usd(self, _request):
            raise LimitRefused(self.found)

        def turn(self, _request):
            raise AssertionError("not sent")

    output = run_attempt(
        job(),
        object(),
        Refuses(hit("max_output_tokens", 128_000, 64_000)),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
    )
    reasoning = run_attempt(
        job(),
        object(),
        Refuses(hit("reasoning_max_tokens", 0, "1..63")),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
    )
    assert Cause.OUTPUT_CAP in output.causes
    assert Cause.CONTEXT not in output.causes
    assert Cause.REASONING_CAP in reasoning.causes
    assert Cause.CONTEXT not in reasoning.causes
