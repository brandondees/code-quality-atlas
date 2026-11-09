# SPDX-License-Identifier: MIT
"""OpenRouter adapter and the per-review budget: every limit is enforced in
code before a request is sent. No test here touches the network."""

import json
from decimal import Decimal

import pytest

from atlas_reviewer.budget import (
    BudgetRefusedError,
    CallLimits,
    ReviewBudget,
    input_token_bound,
    prompt_token_room,
    worst_case_usd,
)
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.openrouter import (
    LISTED_PROVIDER_SLUGS,
    MODEL_ID,
    PINNED_PROVIDERS,
    OpenRouterProvider,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.pricing import (
    PricingUnknownError,
    parse_key_status,
    parse_model_terms,
)
from atlas_reviewer.prompt import Prompt

KEY = "sk-or-v1-" + "f" * 64
API = "https://openrouter.ai/api/v1"
SMALL = Prompt("system", "review this")


def catalog(**pricing_changes):
    pricing = {
        "prompt": "0.000003",
        "completion": "0.000015",
        "request": "0",
        "input_cache_write": "0.00000375",
        "overrides": [{"prompt": "0.000006", "completion": "0.0000225"}],
        **pricing_changes,
    }
    return {
        "data": {
            "id": MODEL_ID,
            "context_length": 1_000_000,
            "pricing": {k: v for k, v in pricing.items() if v is not None},
            "top_provider": {"max_completion_tokens": 64_000},
        }
    }


def key_status(limit=5, remaining=5, usage=0, **extra):
    return {
        "data": {"limit": limit, "limit_remaining": remaining, "usage": usage, **extra}
    }


def completion(text="review text", model=MODEL_ID, usage=None, finish="stop"):
    return {
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0123},
    }  # fmt: skip


def reply(payload, status=200, headers=None):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return HttpResponse(status, headers or {}, raw)


class OpenRouterFake:
    """Serves the key and catalog endpoints; chat replies come from a script."""

    def __init__(self, *chat, key=None, model=None):
        self.chat = list(chat)
        self.key = key if key is not None else reply(key_status())
        self.model = model if model is not None else reply(catalog())
        self.requests = []

    def request(self, method, url, headers, body, timeout_s, max_bytes=None):
        self.requests.append((method, url, dict(headers), body))
        if url == f"{API}/key":
            return self.key
        if url == f"{API}/model/{MODEL_ID}":
            return self.model
        step = self.chat.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def chat_requests(self):
        return [r for r in self.requests if r[1].endswith("/chat/completions")]


def provider(fake, **limits):
    p = OpenRouterProvider(fake, KEY, limits=CallLimits(**limits) if limits else None)
    p.preflight()
    return p


# --- request shape ---------------------------------------------------------


def test_request_is_pinned_to_one_model_with_no_fallbacks_or_plugins():
    fake = OpenRouterFake(reply(completion()))
    assert provider(fake).complete(SMALL) == "review text"
    ((method, url, headers, body),) = fake.chat_requests()
    sent = json.loads(body)
    assert (method, url) == ("POST", f"{API}/chat/completions")
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert sent["model"] == MODEL_ID
    assert "models" not in sent and "plugins" not in sent and "tools" not in sent
    assert ":online" not in sent["model"]
    assert sent["max_tokens"] == 24_000
    assert sent["reasoning"] == {"max_tokens": 12_000, "exclude": True}
    assert sent["stream"] is False
    assert sent["provider"] == {
        "only": list(PINNED_PROVIDERS),
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
        "max_price": {"prompt": 6.0, "completion": 22.5},
    }
    assert set(PINNED_PROVIDERS) == LISTED_PROVIDER_SLUGS
    assert "google-vertex" not in sent["provider"]["only"]


@pytest.mark.parametrize(
    "slugs",
    [
        ("google-vertex",),
        ("google-vertex/us-east5",),
        ("amazon-bedrock/eu-west-1",),
        ("openai",),
        ("amazon-bedrock", "not-a-provider"),
        (),
    ],
)
def test_unknown_or_unlisted_provider_slugs_fail_closed(slugs):
    fake = OpenRouterFake(reply(completion()))
    with pytest.raises(
        BudgetRefusedError, match="unlisted provider slugs|allowlist is empty"
    ):
        OpenRouterProvider(fake, KEY, providers=slugs)
    assert fake.requests == []


def test_catalog_is_fetched_without_the_key():
    fake = OpenRouterFake(reply(completion()))
    provider(fake).complete(SMALL)
    catalog_get = next(r for r in fake.requests if "/model/" in r[1])
    assert "Authorization" not in catalog_get[2]


# --- 3-call cap, retries included ------------------------------------------


def test_retries_count_against_the_three_call_cap():
    fake = OpenRouterFake(*[reply({}, status=503) for _ in range(5)])
    p = provider(fake)
    with pytest.raises(BoundaryError, match="HTTP 503"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 3
    report = p.usage_lines()
    assert report[-1].endswith("3 of 3 calls used")


def test_cap_spans_every_completion_in_the_review():
    fake = OpenRouterFake(
        reply({}, status=429), reply(completion()), reply(completion())
    )
    p = provider(fake)
    assert p.complete(SMALL) == "review text"
    assert p.complete(SMALL) == "review text"
    with pytest.raises(BudgetRefusedError, match="call cap reached: 3 model calls"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 3


def test_a_numeric_retry_after_is_honoured_and_capped():
    sleeps = []
    fake = OpenRouterFake(
        reply({}, status=503, headers={"Retry-After": "1"}),
        reply({}, status=429, headers={"Retry-After": "120"}),
        reply(completion()),
    )
    p = OpenRouterProvider(fake, KEY, sleep=sleeps.append)
    p.preflight()
    assert p.complete(SMALL) == "review text"
    assert sleeps == [1.0, 8.0]
    assert len(fake.chat_requests()) == 3


def test_a_non_numeric_retry_after_falls_back_to_backoff():
    sleeps = []
    fake = OpenRouterFake(
        reply({}, status=503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
        reply({}, status=429, headers={"Retry-After": "-5"}),
        reply(completion()),
    )
    p = OpenRouterProvider(fake, KEY, sleep=sleeps.append)
    p.preflight()
    assert p.complete(SMALL) == "review text"
    assert sleeps == [2.0, 4.0]


def test_transport_errors_are_retried_within_the_cap():
    sleeps = []
    fake = OpenRouterFake(BoundaryError("timed out"), reply(completion()))
    p = OpenRouterProvider(fake, KEY, sleep=sleeps.append)
    p.preflight()
    assert p.complete(SMALL) == "review text"
    assert sleeps == [2.0]
    assert "transport error: timed out" in p.usage_lines()[1]


def test_non_retryable_errors_stop_at_once():
    fake = OpenRouterFake(reply({}, status=400), reply(completion()))
    with pytest.raises(BoundaryError, match="HTTP 400"):
        provider(fake).complete(SMALL)
    assert len(fake.chat_requests()) == 1


# --- $3 reservation ----------------------------------------------------------


def test_call_whose_worst_case_could_pass_three_dollars_is_refused():
    big = Prompt("s", "x" * 170_000)
    terms = parse_model_terms(catalog(), MODEL_ID)
    worst = worst_case_usd(
        input_token_bound(big.system + big.user), terms, CallLimits()
    )
    assert Decimal("1.5") < worst < Decimal(3)
    fake = OpenRouterFake(reply({}, status=503), reply(completion()))
    p = provider(fake)
    with pytest.raises(BoundaryError, match="HTTP 503"):
        p.complete(big)
    assert len(fake.chat_requests()) == 1
    assert any(
        line.startswith("refused: cost cap") and "over $3.00" in line
        for line in p.usage_lines()
    )


def test_a_separate_reasoning_price_is_reserved():
    terms = parse_model_terms(catalog(internal_reasoning="0.00002"), MODEL_ID)
    plain = parse_model_terms(catalog(), MODEL_ID)
    limits = CallLimits()
    extra = limits.reasoning_max_tokens * terms.reasoning_rate
    assert extra == Decimal("0.24")
    assert (
        worst_case_usd(1000, terms, limits)
        == worst_case_usd(1000, plain, limits) + extra
    )


def test_reservation_uses_the_highest_price_tier_and_cache_writes():
    terms = parse_model_terms(catalog(input_cache_write="0.00001"), MODEL_ID)
    assert terms.input_rate == Decimal("0.00001")
    assert terms.prompt_rate == Decimal("0.000006")
    assert terms.completion_rate == Decimal("0.0000225")
    worst = worst_case_usd(1000, terms, CallLimits())
    assert worst == Decimal("0.01") + Decimal("0.54")


def test_failed_attempts_stay_counted_at_their_full_reservation():
    budget = ReviewBudget(CallLimits())
    record = budget.reserve(Decimal("1.40"))
    budget.settle(record, "HTTP 503 (retryable)")
    budget.reserve(Decimal("1.40"))
    with pytest.raises(BudgetRefusedError, match="over \\$3.00"):
        budget.reserve(Decimal("0.21"))
    budget.reserve(Decimal("0.20"))
    assert budget.committed_usd() == Decimal("3.00")


def test_settled_actuals_replace_reservations():
    budget = ReviewBudget(CallLimits())
    record = budget.reserve(Decimal("2.90"))
    budget.settle(record, "ok", Decimal("0.10"))
    budget.reserve(Decimal("2.90"))
    assert budget.committed_usd() == Decimal("3.00")


def test_key_remaining_credit_caps_retries_too():
    fake = OpenRouterFake(
        reply({}, status=503),
        reply(completion()),
        key=reply(key_status(remaining=0.60)),
    )
    p = provider(fake)
    with pytest.raises(BoundaryError, match="HTTP 503"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    assert any("over $0.60" in line for line in p.usage_lines())


def test_worst_case_over_the_key_remaining_credit_is_never_sent():
    fake = OpenRouterFake(reply(completion()), key=reply(key_status(remaining=0.10)))
    with pytest.raises(BudgetRefusedError, match="over \\$0.10"):
        provider(fake).complete(SMALL)
    assert fake.chat_requests() == []


# --- token bounds --------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,model,match",
    [
        (Prompt("s", "x" * 200_001), catalog(), "input cap"),
        (SMALL, {"data": {**catalog()["data"], "top_provider": {"max_completion_tokens": 8000}}},
         "completion limit"),
        (SMALL, {"data": {**catalog()["data"], "context_length": 20_000}}, "context"),
    ],
)  # fmt: skip
def test_token_bounds_are_checked_before_sending(prompt, model, match):
    fake = OpenRouterFake(reply(completion()), model=reply(model))
    with pytest.raises(BudgetRefusedError, match=match):
        provider(fake).complete(prompt)
    assert fake.chat_requests() == []


def test_prompt_token_room_is_what_still_fits_in_the_context():
    """The room a later step sizes a diff part against. The input cap wins
    when it is the tighter of the two bounds."""
    assert prompt_token_room(CallLimits()) == 176_000
    assert prompt_token_room(CallLimits(), context_tokens=100_000) == 76_000
    tight = CallLimits(
        max_input_tokens=50_000, max_output_tokens=30_000, reasoning_max_tokens=1_000
    )
    assert prompt_token_room(tight) == 50_000


def test_limits_reject_nonsense():
    for bad in (
        {"max_calls": 0},
        {"max_calls": 4},
        {"budget_usd": Decimal(0)},
        {"budget_usd": Decimal("3.01")},
        {"max_output_tokens": 100},
    ):
        with pytest.raises(ValueError):
            CallLimits(**bad)


# --- fail closed on unknown pricing -----------------------------------------


@pytest.mark.parametrize(
    "model,match",
    [
        (reply({}, status=404), "HTTP 404"),
        (reply(b"<html>"), "non-JSON"),
        (reply(b'{"a": "\xff"}'), "non-JSON"),
        (reply([]), "non-object"),
        (reply({"data": "x"}), "no data object"),
        (reply(catalog(prompt="-1")), "unknown"),
        (reply(catalog(prompt=None)), "pricing.prompt is missing"),
        (reply(catalog(completion="free")), "not a number"),
        (reply(catalog(completion=True)), "not a number"),
        (reply(catalog(completion="NaN")), "non-finite"),
        (reply(catalog(overrides={"prompt": "1"})), "overrides"),
        (reply(catalog(overrides=[{"completion": "-1"}])), "unknown"),
        (
            reply({"data": {**catalog()["data"], "id": "anthropic/other"}}),
            "not 'anthropic",
        ),
        (reply({"data": {**catalog()["data"], "pricing": None}}), "no pricing object"),
        (
            reply({"data": {**catalog()["data"], "context_length": None}}),
            "context_length",
        ),
        (
            reply({"data": {**catalog()["data"], "top_provider": None}}),
            "max_completion_tokens",
        ),
    ],
)
def test_unknown_or_unparseable_pricing_refuses_before_any_call(model, match):
    fake = OpenRouterFake(reply(completion()), model=model)
    with pytest.raises(PricingUnknownError, match=match):
        provider(fake).complete(SMALL)
    assert fake.chat_requests() == []


# --- key-limit preflight -------------------------------------------------------


@pytest.mark.parametrize(
    "key,match",
    [
        (reply(key_status(limit=None)), "no credit limit"),
        (reply(key_status(limit=5.01)), "over the \\$5.00 pilot ceiling"),
        (reply(key_status(limit=100, remaining=100)), "pilot ceiling"),
        (reply(key_status(remaining=0)), "no credit remaining"),
        (reply(key_status(remaining=None)), "limit_remaining"),
        (reply(key_status(include_byok_in_limit=False)), "BYOK spend"),
        (reply(key_status(include_byok_in_limit=None)), "BYOK spend"),
        (reply({}, status=401), "HTTP 401"),
        (reply(b"nope"), "non-JSON"),
        (reply({"data": None}), "no data object"),
    ],
)
def test_preflight_refuses_unless_the_key_has_a_hard_limit_of_at_most_five_dollars(
    key, match
):
    fake = OpenRouterFake(key=key)
    with pytest.raises(PricingUnknownError, match=match):
        OpenRouterProvider(fake, KEY).preflight()
    assert [r[1] for r in fake.requests] == [f"{API}/key"]
    assert fake.requests[0][2]["Authorization"] == f"Bearer {KEY}"


def test_preflight_accepts_a_five_dollar_key():
    status = OpenRouterProvider(OpenRouterFake(), KEY).preflight()
    assert status == parse_key_status(key_status())


def test_key_status_is_read_only_by_the_preflight_so_a_lagging_counter_cannot_mismatch():
    fake = OpenRouterFake(reply(completion()))
    p = provider(fake)
    p.complete(SMALL)
    key_reads = [r for r in fake.requests if r[1] == f"{API}/key"]
    assert len(key_reads) == 1
    assert fake.requests.index(key_reads[0]) == 0


def test_recorded_spend_comes_from_the_response_even_when_the_key_counter_reads_zero():
    zero_usage_key = reply(key_status(usage=0))
    fake = OpenRouterFake(
        reply(
            completion(usage={"prompt_tokens": 5, "completion_tokens": 5, "cost": 0.17})
        ),
        key=zero_usage_key,
    )
    p = provider(fake)
    p.complete(SMALL)
    assert any("$0.1700" in line for line in p.usage_lines())


def test_no_inference_without_a_passed_preflight():
    fake = OpenRouterFake(reply(completion()))
    with pytest.raises(BudgetRefusedError, match="preflight has not passed"):
        OpenRouterProvider(fake, KEY).complete(SMALL)
    assert fake.requests == []


# --- responses -----------------------------------------------------------------


def test_byok_upstream_cost_counts_toward_the_review_ceiling():
    """usage.cost on a BYOK call is OpenRouter's fee. The upstream charge
    is what the $3 ceiling has to see."""
    usage = {
        "prompt_tokens": 150_000,
        "completion_tokens": 100,
        "cost": "0.05",
        "is_byok": True,
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    fake = OpenRouterFake(*[reply(completion(usage=usage)) for _ in range(3)])
    p = provider(fake)
    assert p.complete(SMALL) == "review text"
    assert p.complete(SMALL) == "review text"
    with pytest.raises(BudgetRefusedError, match="over \\$3.00"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 2
    assert p.budget.committed_usd() == Decimal("2.62")


def test_a_byok_call_without_an_upstream_cost_keeps_its_reservation():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": True,
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]
    assert "BYOK upstream cost not reported" in p.usage_lines()[1]


def test_an_unreadable_upstream_cost_keeps_the_reservation():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "cost_details": {"upstream_inference_cost": "nope"},
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]


def test_an_upstream_cost_is_added_when_the_call_is_not_marked_byok():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert p.budget.committed_usd() == Decimal("1.31")


def test_actual_cost_and_usage_are_recorded():
    usage = {"prompt_tokens": 120, "completion_tokens": 40, "cost": "0.0123",
             "completion_tokens_details": {"reasoning_tokens": 7}}  # fmt: skip
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    line = p.usage_lines()[1]
    assert "actual $0.0123" in line
    assert "tokens in=120 out=40 reasoning=7" in line


def test_fallback_cost_includes_a_separate_reasoning_charge():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "completion_tokens_details": {"reasoning_tokens": 40},
    }
    fake = OpenRouterFake(
        reply(completion(usage=usage)),
        model=reply(catalog(internal_reasoning="0.00005")),
    )
    p = provider(fake)
    p.complete(SMALL)
    # 1000 x 0.000006 + 100 x 0.0000225 + 40 x 0.00005
    assert p.budget.committed_usd() == Decimal("0.01025")
    assert "cost computed at the highest catalog rates" in p.usage_lines()[1]


def test_priced_reasoning_without_a_token_count_keeps_the_reservation():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    fake = OpenRouterFake(
        reply(completion(usage=usage)),
        model=reply(catalog(internal_reasoning="0.00005")),
    )
    p = provider(fake)
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]


def test_refusals_before_a_call_are_reported_and_not_counted_as_calls():
    bare = OpenRouterProvider(OpenRouterFake(reply(completion())), KEY)
    with pytest.raises(BudgetRefusedError, match="preflight has not passed"):
        bare.complete(SMALL)
    assert bare.usage_lines()[-1].endswith("0 of 3 calls used")
    assert any(
        "refused: " in line and "preflight" in line for line in bare.usage_lines()
    )

    unpriced = provider(
        OpenRouterFake(reply(completion()), model=reply(catalog(prompt=None)))
    )
    with pytest.raises(PricingUnknownError, match="pricing.prompt is missing"):
        unpriced.complete(SMALL)
    assert unpriced.usage_lines()[-1].endswith("0 of 3 calls used")
    assert any(
        "refused: pricing.prompt is missing" in line for line in unpriced.usage_lines()
    )

    bounded = provider(
        OpenRouterFake(
            reply(completion()),
            model=reply({"data": {**catalog()["data"], "context_length": 20_000}}),
        )
    )
    with pytest.raises(BudgetRefusedError, match="context"):
        bounded.complete(SMALL)
    assert bounded.usage_lines()[-1].endswith("0 of 3 calls used")
    assert any(
        line.startswith("refused:") and "context" in line
        for line in bounded.usage_lines()
    )


def test_cost_is_computed_from_catalog_rates_when_not_reported():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual $0.0082" in p.usage_lines()[1]
    assert "cost computed at the highest catalog rates" in p.usage_lines()[1]


@pytest.mark.parametrize(
    "usage", [{}, {"prompt_tokens": -1_000_000, "completion_tokens": 5}]
)
def test_missing_usage_keeps_the_reservation_as_spent(usage):
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]


@pytest.mark.parametrize(
    "response,match",
    [
        (completion(model="openai/gpt-5"), "served 'openai/gpt-5'"),
        (completion(model=None), "served None"),
        (completion(model=f"{MODEL_ID}-turbo"), "-turbo'"),
        (completion(model=f"{MODEL_ID}-20261001x"), "20261001x'"),
        (completion(text="  "), "no review text"),
        ({"model": MODEL_ID, "choices": []}, "no review text"),
    ],
)
def test_substituted_models_and_empty_reviews_are_rejected_without_retry(
    response, match
):
    fake = OpenRouterFake(reply(response), reply(completion()))
    with pytest.raises(BoundaryError, match=match):
        provider(fake).complete(SMALL)
    assert len(fake.chat_requests()) == 1


@pytest.mark.parametrize("finish", ["error", "content_filter", None, "tool_calls"])
def test_only_a_stop_finish_is_accepted(finish):
    fake = OpenRouterFake(reply(completion(finish=finish)), reply(completion()))
    p = provider(fake)
    with pytest.raises(BoundaryError, match="did not finish"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    shown = "None" if finish is None else finish
    assert f"incomplete review (finish_reason={shown})" in p.usage_lines()[1]
    assert "actual $0.0123" in p.usage_lines()[1]


def test_a_review_cut_at_the_output_limit_is_settled_and_rejected():
    fake = OpenRouterFake(reply(completion(finish="length")), reply(completion()))
    p = provider(fake)
    with pytest.raises(BoundaryError, match="output-token limit"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    line = p.usage_lines()[1]
    assert "incomplete review (finish_reason=length)" in line
    assert "actual $0.0123" in line


def test_dated_variant_of_the_pinned_model_is_accepted():
    fake = OpenRouterFake(reply(completion(model=f"{MODEL_ID}-20261001")))
    assert provider(fake).complete(SMALL) == "review text"


@pytest.mark.parametrize("body", [b"<html>", b'{"a": "\xff"}'])
def test_unparseable_completion_is_settled_and_raised(body):
    p = provider(OpenRouterFake(reply(body)))
    with pytest.raises(BoundaryError, match="non-JSON"):
        p.complete(SMALL)
    assert "unparseable response" in p.usage_lines()[1]
