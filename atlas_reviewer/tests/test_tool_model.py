# SPDX-License-Identifier: MIT
"""The live tool-calling adapter. Recorded HTTP only: no OpenRouter call."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from atlas_reviewer.attestation import Cause, ToolUse
from atlas_reviewer.bridge import UNKNOWN_TOOL, Status
from atlas_reviewer.bridge_args import RejectedError, Rev, validate
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    AssistantCalls,
    Spend,
    ToolRequest,
    ToolResults,
    TurnRequest,
    UserText,
    tool_schemas,
)
from atlas_reviewer.limit_stop import LimitRefused
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.ports import BoundaryError, ByokRefusedError
from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence
from atlas_reviewer.tool_model import OpenRouterLensModel

from .agentic import LIMITS, final, finding
from .test_lens_loop import NONCE, attempt
from .test_openrouter import (
    KEY,
    MODEL_ID,
    OpenRouterFake,
    catalog,
    completion,
    key_status,
    reply,
)

SYSTEM = "You are one lens. Read the change with the tools."


def request(*messages, tools=None) -> TurnRequest:
    history = messages or (UserText("Review the change."),)
    return TurnRequest(SYSTEM, history, tools if tools is not None else tool_schemas())


def model(*chat, key=None, limits=None, catalog_reply=None):
    extra = {} if catalog_reply is None else {"model": catalog_reply}
    fake = OpenRouterFake(*chat, key=key, **extra)
    provider = OpenRouterProvider(fake, KEY, limits=limits)
    return OpenRouterLensModel(provider), fake


def test_the_adapter_is_built_with_the_configured_limits():
    from atlas_reviewer.coordinator import limits_for_lens, model_for_lens

    limits = limits_for_lens({"ATLAS_MAX_INPUT_TOKENS": "8"})
    adapter = model_for_lens(OpenRouterProvider(OpenRouterFake(), KEY), limits)
    assert adapter.per_call == limits.resolve()
    assert adapter.per_call.max_input_tokens == 8


def sent(fake: OpenRouterFake) -> dict:
    ((_method, _url, _headers, body),) = fake.chat_requests()
    return json.loads(body)


def tool_response(name="diff_stat", arguments="{}", usage=None, finish="tool_calls"):
    return reply(
        completion(
            text="",
            usage=usage,
            finish=finish,
        )
        | {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": name, "arguments": arguments},
                            }
                        ],
                    },
                    "finish_reason": finish,
                }
            ],
        }
    )


def test_the_adapter_uses_the_provider_name_and_wraps_a_transport_error():
    lens, _fake = model(BoundaryError("down"))
    assert lens.name == lens.provider.name == f"openrouter:{MODEL_ID}"
    with pytest.raises(BoundaryError, match="transport error"):
        lens.turn(request())


def test_the_request_uses_the_one_shot_pin_and_only_our_tools():
    from .test_openrouter import SMALL, provider

    one = OpenRouterFake(reply(completion()))
    provider(one).complete(SMALL)
    lens, fake = model(reply(completion("findings")))
    lens.turn(request())
    body = sent(fake)
    one_body = json.loads(one.chat_requests()[0][3])
    assert body["provider"] == one_body["provider"]
    assert body["provider"]["require_parameters"] is True
    assert body["provider"]["zdr"] is True
    assert body["provider"]["data_collection"] == "deny"
    assert body["provider"]["allow_fallbacks"] is False
    assert body["model"] == MODEL_ID
    assert body["stream"] is False
    assert "cache_control" not in body
    assert "cache_control" not in body["provider"]
    assert "plugins" not in body
    assert [tool["function"]["name"] for tool in body["tools"]] == [
        "diff_stat",
        "diff_file",
        "list_files",
        "read_file",
        "grep",
    ]
    assert fake.chat_requests()[0][2]["Authorization"] == f"Bearer {KEY}"
    assert len(fake.chat_requests()) == 1


def test_the_tool_request_omits_parameters_the_endpoint_does_not_list():
    from .test_openrouter import zdr_payload

    bare, fake = model(
        reply(completion("findings")),
        # The helper's catalog_reply is the model catalog. ZDR is separate.
    )
    fake.zdr = reply(zdr_payload(parameters=["max_tokens", "tools"]))
    bare.turn(request())
    body = sent(fake)
    assert "reasoning" not in body
    assert "cache_control" not in body
    assert body["provider"]["require_parameters"] is True
    assert body["provider"]["zdr"] is True
    assert body["provider"]["data_collection"] == "deny"
    assert body["provider"]["allow_fallbacks"] is False
    assert "max_price" in body["provider"]
    bare2, fake2 = model(reply(completion("findings")))
    fake2.zdr = reply(zdr_payload(parameters=["tools"]))
    bare2.turn(request())
    assert sent(fake2)["max_tokens"] == 64_000

    cached, cached_fake = model(reply(completion("findings")))
    cached_fake.zdr = reply(
        zdr_payload(parameters=["reasoning", "cache_control", "max_tokens", "tools"])
    )
    cached.turn(request())
    sent_body = sent(cached_fake)
    assert sent_body["cache_control"] == {"type": "ephemeral"}
    assert sent_body["reasoning"]["exclude"] is True


def test_a_tool_result_is_forwarded_with_its_nonce_fence_unchanged():
    fenced = fence(UntrustedBlock("tool-result", RepoText("diff text")), NONCE)
    lens, fake = model(reply(completion("done")))
    lens.turn(
        request(
            UserText("Review the change."),
            AssistantCalls((ToolRequest("diff_stat", {}),)),
            ToolResults((fenced,)),
        )
    )
    messages = sent(fake)["messages"]
    tool = messages[-1]
    assert tool["role"] == "tool"
    assert tool["content"] == fenced
    assert NONCE in tool["content"]
    assert messages[-2]["tool_calls"][0]["id"] == tool["tool_call_id"]


def test_one_turn_does_not_retry_or_touch_the_one_shot_budget():
    lens, fake = model(reply(completion(), status=429), reply(completion("later")))
    with pytest.raises(BoundaryError, match="429"):
        lens.turn(request())
    assert len(fake.chat) == 1
    assert lens.provider.budget.calls == []


def test_a_reported_cost_settles_and_an_invalid_one_stays_at_the_worst_case():
    lens, _fake = model(
        reply(completion("done", usage={"cost": "0.25", "is_byok": False}))
    )
    spend = Spend(AgenticLimits().resolve())
    ask = request()
    worst = lens.worst_case_usd(ask)
    assert spend.reserve(worst) is None
    spend.settle(worst, lens.turn(ask).cost_usd)
    assert spend.committed_usd == Decimal("0.25")

    broken, _fake = model(reply(completion("done", usage={"is_byok": False})))
    spend = Spend(AgenticLimits().resolve())
    worst = broken.worst_case_usd(ask)
    spend.reserve(worst)
    reply_turn = broken.turn(ask)
    assert reply_turn.cost_usd.is_infinite()
    spend.settle(worst, reply_turn.cost_usd)
    assert spend.committed_usd == worst
    assert broken.provider.budget.calls == []


def test_token_counts_without_a_cost_are_priced_from_the_catalog():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "is_byok": False}
    lens, _fake = model(reply(completion("done", usage=usage)))
    # 1000 x 0.000006 + 100 x 0.0000225, the highest catalog rates.
    assert lens.turn(request()).cost_usd == Decimal("0.00825")


def test_a_missing_cost_with_no_cache_counts_uses_the_reservation_input_rate():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "is_byok": False}
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        catalog_reply=reply(catalog(input_cache_write="0.00001")),
    )
    # The write rate is above the prompt rate, so every prompt token is
    # charged at that reservation rate when the response names no cache split.
    # 1000 x 0.00001 + 100 x 0.0000225.
    assert lens.turn(request()).cost_usd == Decimal("0.01225")


def test_an_empty_cache_detail_object_still_uses_the_reservation_input_rate():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "is_byok": False,
        "prompt_tokens_details": {},
    }
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        catalog_reply=reply(catalog(input_cache_write="0.00001")),
    )
    assert lens.turn(request()).cost_usd == Decimal("0.01225")


def test_cache_tokens_without_a_cost_use_the_catalog_cache_rates():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "is_byok": False,
        "prompt_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 100},
    }
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        catalog_reply=reply(catalog(input_cache_read="0.000001")),
    )
    # 100 x 0.000006 + 800 x 0.000001 + 100 x 0.00000375 + 100 x 0.0000225.
    assert lens.turn(request()).cost_usd == Decimal("0.004025")


@pytest.mark.parametrize(
    ("cached", "expected"),
    [(800, Decimal("0.00905")), (0, Decimal("0.01225"))],
    ids=["some-reads", "no-reads"],
)
def test_a_missing_write_count_prices_the_rest_at_the_reservation_input_rate(
    cached, expected
):
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "is_byok": False,
        "prompt_tokens_details": {"cached_tokens": cached},
    }
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        catalog_reply=reply(catalog(input_cache_write="0.00001")),
    )
    # The write count is absent, so the uncached tokens may include writes
    # at 0.00001. The reads (if any) are at the prompt rate, 0.000006.
    assert lens.turn(request()).cost_usd == expected


def test_cache_reads_past_the_prompt_with_no_write_count_keep_the_reservation():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 1,
        "is_byok": False,
        "prompt_tokens_details": {"cached_tokens": 50},
    }
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        catalog_reply=reply(catalog(input_cache_write="0.00001")),
    )
    spend = Spend(AgenticLimits().resolve())
    ask = request()
    worst = lens.worst_case_usd(ask)
    assert spend.reserve(worst) is None
    turn = lens.turn(ask)
    assert turn.cost_usd.is_infinite()
    spend.settle(worst, turn.cost_usd)
    assert spend.committed_usd == worst


def test_cache_reads_without_a_catalog_rate_use_the_prompt_rate():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "is_byok": False,
        "prompt_tokens_details": {"cache_write_tokens": 100},
    }
    lens, _fake = model(reply(completion("done", usage=usage)))
    # 900 x 0.000006 + 100 x 0.00000375 + 100 x 0.0000225.
    assert lens.turn(request()).cost_usd == Decimal("0.008025")


@pytest.mark.parametrize(
    "details",
    [
        {"cached_tokens": 0, "cache_write_tokens": "1000"},
        {"cached_tokens": -1, "cache_write_tokens": 0},
    ],
    ids=["malformed-write", "negative-read"],
)
def test_an_unreadable_cache_count_keeps_the_reservation(details):
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "is_byok": False,
        "prompt_tokens_details": details,
    }
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        catalog_reply=reply(catalog(input_cache_write="0.00001")),
    )
    spend = Spend(AgenticLimits().resolve())
    ask = request()
    worst = lens.worst_case_usd(ask)
    assert spend.reserve(worst) is None
    turn = lens.turn(ask)
    assert turn.cost_usd.is_infinite()
    spend.settle(worst, turn.cost_usd)
    assert spend.committed_usd == worst


def test_cache_counts_past_the_prompt_keep_the_reservation():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 1,
        "is_byok": False,
        "prompt_tokens_details": {"cached_tokens": 8, "cache_write_tokens": 8},
    }
    lens, _fake = model(reply(completion("done", usage=usage)))
    spend = Spend(AgenticLimits().resolve())
    ask = request()
    worst = lens.worst_case_usd(ask)
    assert spend.reserve(worst) is None
    turn = lens.turn(ask)
    assert turn.cost_usd.is_infinite()
    spend.settle(worst, turn.cost_usd)
    assert spend.committed_usd == worst


def test_a_reported_cost_is_used_when_cache_tokens_are_present():
    usage = {
        "cost": "0.42",
        "is_byok": False,
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 50},
    }
    lens, _fake = model(reply(completion("done", usage=usage)))
    assert lens.turn(request()).cost_usd == Decimal("0.42")


def test_a_review_fetches_the_catalog_and_the_zdr_list_once():
    usage = {"cost": "0.01", "is_byok": False}
    lens, fake = model(
        reply(completion("one", usage=usage)),
        reply(completion("two", usage=usage)),
    )
    ask = request()
    lens.worst_case_usd(ask)
    lens.turn(ask)
    lens.worst_case_usd(ask)
    lens.turn(ask)
    fetched = [
        url for _method, url, _headers, _body in fake.requests if "/model/" in url
    ]
    zdr = [url for _m, url, _h, _b in fake.requests if url.endswith("/endpoints/zdr")]
    assert fetched == [f"https://openrouter.ai/api/v1/model/{MODEL_ID}"]
    assert zdr == ["https://openrouter.ai/api/v1/endpoints/zdr"]
    other, other_fake = model(reply(completion("three", usage=usage)))
    other.turn(request())
    assert any("/model/" in url for _m, url, _h, _b in other_fake.requests)


def test_an_unparseable_reply_on_a_no_byok_key_is_refused():
    lens, fake = model(
        reply(b"not-json"),
        key=reply(key_status(include_byok_in_limit=False)),
    )
    with pytest.raises(ByokRefusedError, match="could not be parsed"):
        lens.turn(request())
    assert len(fake.chat) == 0


def test_non_finite_and_deeply_nested_arguments_are_refused():
    """Through `turn`, so a parser that bypasses the strict check is caught."""

    def arguments_of(raw: str):
        lens, _fake = model(tool_response("diff_file", raw))
        (call,) = lens.turn(request()).calls
        return call.tool, call.args

    assert arguments_of('{"n": 1e999}') == ("diff_file", ())
    assert arguments_of('{"n": [1e999]}') == ("diff_file", ())
    nested = '{"a": ' + '{"b": ' * 2000 + "1" + "}" * 2000 + "}"
    assert arguments_of(nested) == ("diff_file", ())


def test_a_zero_cost_settles_at_zero():
    lens, _fake = model(reply(completion("done", usage={"cost": 0, "is_byok": False})))
    ask = request()
    spend = Spend(AgenticLimits().resolve())
    worst = lens.worst_case_usd(ask)
    spend.reserve(worst)
    spend.settle(worst, lens.turn(ask).cost_usd)
    assert spend.committed_usd == Decimal(0)


def test_byok_upstream_cost_is_added_and_a_missing_one_is_unpriced():
    usage = {
        "cost": "0.01",
        "is_byok": True,
        "cost_details": {"upstream_inference_cost": "0.02"},
    }
    lens, _fake = model(reply(completion("done", usage=usage)))
    assert lens.turn(request()).cost_usd == Decimal("0.03")

    missing, _fake = model(
        reply(completion("done", usage={"cost": "0.01", "is_byok": True}))
    )
    assert missing.turn(request()).cost_usd.is_infinite()


def test_a_key_that_does_not_count_byok_refuses_an_unlabelled_call():
    lens, fake = model(
        reply(completion("done", usage={"cost": "0.01"})),
        key=reply(key_status(include_byok_in_limit=False)),
    )
    with pytest.raises(ByokRefusedError, match="is_byok"):
        lens.turn(request())
    assert len(fake.chat) == 0


def test_a_response_from_another_model_is_rejected():
    lens, _fake = model(
        reply(
            completion(
                "done", model="other/model", usage={"cost": "0.01", "is_byok": False}
            )
        )
    )
    with pytest.raises(BoundaryError, match="other/model"):
        lens.turn(request())


def test_a_malformed_choice_or_unfinished_tool_call_is_rejected():
    empty, _fake = model(
        reply(
            {"model": MODEL_ID, "choices": [], "usage": {"cost": 0, "is_byok": False}}
        )
    )
    with pytest.raises(BoundaryError, match="no choice"):
        empty.turn(request())
    note = completion("done", usage={"cost": 0, "is_byok": False})
    note["choices"][0]["message"] = "not an object"
    words, _fake = model(reply(note))
    with pytest.raises(BoundaryError, match="no message"):
        words.turn(request())
    stopped = tool_response("diff_stat", "{}", finish="content_filter")
    filtered, _fake = model(stopped)
    with pytest.raises(BoundaryError, match="did not finish"):
        filtered.turn(request())
    other = completion("done", usage={"cost": 0, "is_byok": False}, finish="error")
    unfinished, _fake = model(reply(other))
    with pytest.raises(BoundaryError, match="did not finish"):
        unfinished.turn(request())


def test_a_tool_call_that_is_not_one_function_cannot_be_executed():
    def turned(mutate):
        body = json.loads(tool_response("diff_stat", "{}").body)
        mutate(body["choices"][0]["message"]["tool_calls"])
        lens, _fake = model(reply(body))
        return lens.turn(request()).calls[0]

    assert turned(lambda calls: calls.__setitem__(0, "nope")) == ToolRequest("", ())
    assert turned(
        lambda calls: calls[0].__setitem__("function", "diff_stat")
    ) == ToolRequest("", ())
    assert turned(
        lambda calls: calls[0]["function"].__setitem__("name", "")
    ) == ToolRequest("", ())


def test_a_truncated_turn_is_an_output_cap_stop():
    lens, _fake = model(tool_response(finish="length"))
    with pytest.raises(LimitRefused) as raised:
        lens.turn(request())
    assert raised.value.hit.limit == "max_output_tokens"
    assert raised.value.hit.configured == "64000"
    assert raised.value.hit.observed == "finish_reason=length"


def test_an_empty_or_non_text_reply_is_rejected():
    blank, _fake = model(
        reply(completion("   ", usage={"cost": "0", "is_byok": False}))
    )
    with pytest.raises(BoundaryError, match="no text"):
        blank.turn(request())
    body = completion("done", usage={"cost": "0", "is_byok": False})
    body["choices"][0]["message"]["content"] = ["not text"]
    pieces, _fake = model(reply(body))
    with pytest.raises(BoundaryError, match="no text"):
        pieces.turn(request())


def test_tool_results_must_match_the_calls_that_preceded_them():
    lens, fake = model(reply(completion("done")))
    with pytest.raises(BoundaryError, match="tool result"):
        lens.turn(request(AssistantCalls((ToolRequest("diff_stat", {}),))))
    with pytest.raises(BoundaryError, match="do not match"):
        lens.turn(
            request(
                AssistantCalls(
                    (ToolRequest("diff_stat", {}), ToolRequest("diff_stat", {}))
                ),
                ToolResults(("only one",)),
            )
        )
    assert fake.chat_requests() == []
    with pytest.raises(BoundaryError, match="tool result is missing"):
        lens.turn(
            request(
                AssistantCalls((ToolRequest("diff_stat", {}),)),
                UserText("and another question"),
            )
        )
    with pytest.raises(BoundaryError, match="tool result is missing"):
        lens.turn(
            request(
                AssistantCalls((ToolRequest("diff_stat", {}),)),
                AssistantCalls((ToolRequest("diff_stat", {}),)),
            )
        )
    lens2, fake2 = model(reply(completion("done")))
    lens2.turn(
        request(
            AssistantCalls((ToolRequest(None, ()),)),
            ToolResults(("fenced result",)),
        )
    )
    echoed = json.loads(fake2.chat_requests()[0][3])["messages"][-2]
    assert echoed["tool_calls"][0]["function"] == {"name": "", "arguments": "{}"}


def test_a_well_formed_tool_call_is_parsed_and_not_executed_here():
    lens, fake = model(tool_response("diff_file", '{"path": "calc.py"}'))
    turn = lens.turn(request())
    (call,) = turn.calls
    assert (call.tool, call.args) == ("diff_file", {"path": "calc.py"})
    checked = validate(call.tool, call.args, frozenset({Rev.HEAD}))
    assert checked.tool == "diff_file"
    assert len(fake.chat_requests()) == 1


@pytest.mark.parametrize(
    ("name", "arguments", "tool", "args"),
    [
        ("rm", "{}", "rm", {}),
        ("diff_file", "{", "diff_file", ()),
        ("diff_file", "[1]", "diff_file", ()),
        ("diff_file", '{"path": "a", "path": "b"}', "diff_file", ()),
    ],
)
def test_an_unknown_tool_or_bad_arguments_cannot_be_executed(
    name, arguments, tool, args
):
    lens, _fake = model(tool_response(name, arguments))
    (call,) = lens.turn(request()).calls
    assert (call.tool, call.args) == (tool, args)
    with pytest.raises(RejectedError):
        validate(call.tool, call.args, frozenset({Rev.HEAD}))


def test_a_preparsed_argument_object_cannot_be_executed():
    body = json.loads(tool_response("diff_file", "{}").body)
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = {
        "path": "calc.py"
    }
    lens, _fake = model(reply(body))
    (call,) = lens.turn(request()).calls
    assert call.args == ()
    with pytest.raises(RejectedError):
        validate(call.tool, call.args, frozenset({Rev.HEAD}))


def test_the_loop_refuses_an_unknown_tool_and_sends_the_fence_back(tmp_path):
    usage = {"cost": "0.01", "is_byok": False}
    done = final(finding())
    lens, fake = model(
        tool_response("rm", "{}"), reply(completion(done.text, usage=usage))
    )
    outcome, _, _spend = attempt(
        tmp_path,
        [],
        model=lens,
        limits=replace(LIMITS, reservation_usd=Decimal(5)),
    )
    assert outcome.tools == (ToolUse(UNKNOWN_TOOL, "", Status.REJECTED.name),)
    messages = json.loads(fake.chat_requests()[-1][3])["messages"]
    tool = messages[-1]
    assert tool["role"] == "tool"
    assert tool["content"].startswith(f'<untrusted-data id="{NONCE}"')
    assert tool["content"].endswith(f'</untrusted-data id="{NONCE}">')
    assert "unknown-tool" in tool["content"]
    assert len(fake.chat_requests()) == 2
    assert lens.provider.budget.calls == []


def test_the_loop_turn_cap_stops_the_adapter_at_one_request(tmp_path):
    lens, fake = model(
        tool_response("rm", "{}"),
        reply(
            completion("should not be sent", usage={"cost": "0.01", "is_byok": False})
        ),
    )
    outcome, _, _spend = attempt(
        tmp_path,
        [],
        model=lens,
        limits=replace(LIMITS, reservation_usd=Decimal(5), max_turns=1, max_calls=20),
    )
    assert outcome.causes == {Cause.TURN_CAP, Cause.FILES_UNREAD}
    assert len(fake.chat_requests()) == 1
    assert len(fake.chat) == 1


def test_a_call_that_is_not_a_function_cannot_be_executed():
    body = json.loads(tool_response("diff_stat", "{}").body)
    body["choices"][0]["message"]["tool_calls"][0]["type"] = "shell"
    lens, _fake = model(reply(body))
    (call,) = lens.turn(request()).calls
    assert (call.tool, call.args) == ("", ())
    with pytest.raises(RejectedError):
        validate(call.tool, call.args, frozenset({Rev.HEAD}))
