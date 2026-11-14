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
    default_output_tokens,
    default_reasoning_tokens,
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
from .test_openrouter import catalog, completion, reply, zdr_payload
from .test_tool_model import model, request, sent


def test_unset_limits_keep_the_defaults_and_derive_per_call_bounds():
    limits = load_agentic_limits({})
    resolved = limits.resolve()
    assert (resolved.max_calls, resolved.reservation_usd) == (50, Decimal(5))
    assert resolved.max_input_tokens is None
    terms = parse_model_terms(catalog(), MODEL_ID)
    call = resolve_per_call(resolved, terms)
    assert call.max_output_tokens == 64_000
    assert call.reasoning_max_tokens == default_reasoning_tokens(64_000) == 32_000
    assert call.max_output_tokens - call.reasoning_max_tokens == 32_000
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
    with pytest.raises(LimitRefused, match="max_input_tokens"):
        resolve_per_call(replace(limits.resolve(), max_input_tokens=950_000), terms)


def test_an_empty_flag_is_refused_and_an_empty_variable_stays_unset():
    with pytest.raises(ValueError, match="max_calls"):
        load_agentic_limits({"ATLAS_MAX_CALLS": "10"}, max_calls="")
    limits = load_agentic_limits({"ATLAS_MAX_CALLS": ""})
    assert limits.max_calls == AgenticLimits().max_calls


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
    assert raised.value.hit.setting == "--max-output-tokens or ATLAS_MAX_OUTPUT_TOKENS"


def test_the_adapter_sends_the_model_caps_and_ignores_the_reasoning_hint():
    lens, fake = model(reply(completion("ok")))
    lens.turn(request())
    body = sent(fake)
    assert body["max_tokens"] == 64_000
    assert body["reasoning"]["max_tokens"] == 32_000

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
    assert raised.value.hit.setting == "--max-input-tokens or ATLAS_MAX_INPUT_TOKENS"
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
        review_started=0,
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
        review_started=0,
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
    assert CallLimits().budget_usd == Decimal("3.00")


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
    # The completion limit fills the context. The default leaves a quarter
    # of it for output so the call still has input room.
    fitted = resolve_per_call(base, tight)
    assert fitted.max_output_tokens == 16_000
    assert fitted.max_input_tokens == 48_000
    with pytest.raises(LimitRefused, match="context_length") as raised:
        resolve_per_call(replace(base, max_output_tokens=64_000), tight)
    assert raised.value.hit.setting == "the pinned endpoints' context_length"
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
        review_started=0,
    )
    assert outcome.causes == {Cause.CONTEXT, Cause.FILES_UNREAD}
    assert outcome.state is LensState.PARTIAL
    assert outcome.retryable is False
    assert outcome.limit_hit is not None
    assert outcome.limit_hit.setting == "the pinned endpoints' max_completion_tokens"


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
        review_started=0,
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


def test_a_length_stop_is_the_output_cap_and_not_a_model_error():
    lens, _fake = model(reply(completion("cut off", finish="length")))
    outcome = run_attempt(
        job(),
        object(),
        lens,
        Spend(replace(LIMITS, reservation_usd=Decimal(5)).resolve()),
        FakeClock(),
        review_deadline=600,
        review_started=0,
    )
    assert Cause.OUTPUT_CAP in outcome.causes
    assert Cause.MODEL_ERROR not in outcome.causes
    assert outcome.limit_hit is not None
    assert outcome.limit_hit.limit == "max_output_tokens"
    assert outcome.limit_hit.configured == "64000"
    assert outcome.limit_hit.observed == "finish_reason=length"


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
        review_started=0,
    )
    reasoning = run_attempt(
        job(),
        object(),
        Refuses(hit("reasoning_max_tokens", 0, "1..63")),
        Spend(LIMITS.resolve()),
        FakeClock(),
        review_deadline=600,
        review_started=0,
    )
    assert Cause.OUTPUT_CAP in output.causes
    assert Cause.CONTEXT not in output.causes
    assert Cause.REASONING_CAP in reasoning.causes
    assert Cause.CONTEXT not in reasoning.causes


def test_a_context_limited_endpoint_caps_max_tokens_not_the_catalog():
    """DeepInfra's context was smaller than the catalog, and the request
    asked for the catalog's completion limit."""
    rows = zdr_payload(context_length=16_384, max_completion_tokens=8_192)
    lens, fake = model(reply(completion("ok")), zdr=reply(rows))
    lens.turn(request())
    body = sent(fake)
    # 16_384 // 4 == 4_096. The catalog fixture's completion limit is 64_000.
    assert body["max_tokens"] == 4_096
    assert body["provider"]["max_price"] == {"prompt": 6.0, "completion": 22.5}
    assert body["provider"]["zdr"] is True


def test_the_default_output_cap_leaves_input_room_when_completion_fills_the_context():
    """Kimi and Qwen left 26_215 input tokens (262_144 - 235_929) when the
    cap was the full completion limit. GLM's ~944k cap priced one call
    over the $5 reservation."""
    rows = zdr_payload(context_length=262_144, max_completion_tokens=235_929)
    lens, fake = model(
        reply(completion("ok")), reply(completion("ok")), zdr=reply(rows)
    )
    lens.turn(request())
    assert sent(fake)["max_tokens"] == 65_536
    assert default_output_tokens(262_144, 235_929) == 65_536
    # Sonnet 5.5's completion limit is 128_000 on a 1_000_000 context,
    # which is under a quarter, so the default stays 128_000.
    assert default_output_tokens(1_000_000, 128_000) == 128_000

    lens.per_call = replace(AgenticLimits().resolve(), max_output_tokens=100_000)
    lens.turn(request())
    assert json.loads(fake.chat_requests()[-1][3])["max_tokens"] == 100_000


def test_a_run_records_whether_zdr_was_required_and_whether_caching_was_enabled():
    from atlas_reviewer.openrouter import model_route
    from atlas_reviewer.tracing import memory_trace

    lens, _fake = model(reply(completion("ok")))
    trace, exporter = memory_trace(lambda text: text)
    try:
        with trace.lens("tracing-correctness-and-invariants"):
            trace.wrap_model(lens).turn(request())
    finally:
        trace.shutdown()
    span = next(s for s in exporter.get_finished_spans() if s.name == "completion")
    assert span.attributes["atlas.zdr_required"] is True
    assert span.attributes["atlas.cache_control"] is True
    assert "zdr required: true" in lens.provider.usage_lines()[0]
    assert "cache_control: true" in lens.provider.usage_lines()[0]

    cached = {
        "data": {
            "id": MODEL_ID,
            "endpoints": [
                {
                    "tag": "amazon-bedrock",
                    "provider_name": "Amazon Bedrock",
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "context_length": 1_000_000,
                    "max_completion_tokens": 64_000,
                    "supported_parameters": ["max_tokens"],
                }
            ],
        }
    }
    off, off_fake = model(
        reply(completion("ok")),
        zdr=reply({"data": []}),
        route=model_route({}, providers="amazon-bedrock", require_zdr=False),
    )
    off_fake.endpoints = reply(cached)
    off.turn(request())
    body = json.loads(off_fake.chat_requests()[-1][3])
    assert "zdr" not in body["provider"]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["provider"]["data_collection"] == "deny"
    assert "zdr required: false" in off.provider.usage_lines()[0]
    assert "cache_control: true" in off.provider.usage_lines()[0]
    assert span.attributes["atlas.endpoint_tags"]
    assert span.attributes["atlas.context_length"] == "1000000"
    assert span.attributes["atlas.max_completion_tokens"] == "64000"
    assert span.attributes["atlas.max_price_prompt"] == "6.0"
    assert "endpoints:" in lens.provider.usage_lines()[0]


def test_the_smaller_pinned_context_and_completion_limit_bound_the_call():
    from atlas_reviewer.openrouter import model_route

    from .test_openrouter import with_terms

    wide = with_terms(
        {
            "model_id": MODEL_ID,
            "tag": "deepinfra/fp8",
            "safety_retention": False,
            "supported_parameters": ["max_tokens"],
            "context_length": 32_768,
            "max_completion_tokens": 16_384,
        }
    )
    tight = with_terms(
        {
            "model_id": MODEL_ID,
            "tag": "deepinfra/fp4",
            "safety_retention": False,
            "supported_parameters": ["max_tokens"],
            "context_length": 16_384,
            "max_completion_tokens": 8_192,
        }
    )
    lens, fake = model(reply(completion("ok")), zdr=reply({"data": [wide, tight]}))
    lens.provider.configure(model_route({}, providers="deepinfra/fp8,deepinfra/fp4"))
    lens.turn(request())
    assert sent(fake)["max_tokens"] == 4_096
    terms, _selected = lens.provider.load_terms()
    call = resolve_per_call(AgenticLimits().resolve(), terms)
    assert call.max_output_tokens == 4_096
    assert call.max_input_tokens == 16_384 - 4_096
    assert terms.context_limit_tags == "deepinfra/fp4"
    assert terms.completion_limit_tags == "deepinfra/fp4"
    with pytest.raises(LimitRefused, match="set by deepinfra/fp4") as raised:
        resolve_per_call(
            replace(AgenticLimits().resolve(), max_output_tokens=10_000), terms
        )
    assert raised.value.hit.setting.endswith("(set by deepinfra/fp4)")


def test_max_prompt_tokens_caps_the_input_when_a_row_sets_it():
    from atlas_reviewer.openrouter import model_route

    from .test_openrouter import zdr_payload

    rows = zdr_payload(
        providers=("amazon-bedrock",),
        context_length=100_000,
        max_completion_tokens=1_000,
    )
    rows["data"][0]["max_prompt_tokens"] = 500
    lens, _fake = model(reply(completion("ok")), zdr=reply(rows))
    lens.provider.configure(model_route({}, providers="amazon-bedrock"))
    terms, _selected = lens.provider.load_terms()
    # The completion limit is 1_000, under a quarter of 100_000, so the
    # output cap stays 1_000. Context would leave 99_000 input tokens.
    call = resolve_per_call(AgenticLimits().resolve(), terms)
    assert call.max_output_tokens == 1_000
    assert call.max_input_tokens == 500
    assert terms.prompt_limit_tags == "amazon-bedrock"
