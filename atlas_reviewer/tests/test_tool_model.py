# SPDX-License-Identifier: MIT
"""The live tool-calling adapter. Recorded HTTP only: no OpenRouter call."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from atlas_reviewer.attestation import (
    AttemptOutcome,
    Attestation,
    Cause,
    LensState,
    ToolUse,
    body_digest,
    body_markers,
)
from atlas_reviewer.bridge import UNKNOWN_TOOL, Status
from atlas_reviewer.bridge_args import RejectedError, Rev, validate
from atlas_reviewer.budget import worst_case_usd
from atlas_reviewer.cache_stats import session_lines
from atlas_reviewer.call_facts import take_call
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    AssistantCalls,
    SharedPrefix,
    Spend,
    ToolRequest,
    ToolResults,
    TurnRequest,
    UserText,
    lens_skill,
    resolve_per_call,
    shared_system,
    tool_schemas,
)
from atlas_reviewer.limit_stop import LimitRefused
from atlas_reviewer.openrouter import OpenRouterProvider
from atlas_reviewer.ports import (
    BoundaryError,
    ByokRefusedError,
    KeyRefusedError,
    TransportError,
    TransportTimeoutError,
)
from atlas_reviewer.pricing import PricingUnknownError
from atlas_reviewer.prompt import RepoText, UntrustedBlock, fence
from atlas_reviewer.tool_model import OpenRouterLensModel, _payload

from .agentic import BODY, DIFF, LIMITS, final, finding
from .helpers import FakeClock
from .test_lens_loop import CONTRACT, LENS, NONCE, attempt, job
from .test_openrouter import (
    KEY,
    MODEL_ID,
    OpenRouterFake,
    catalog,
    completion,
    key_status,
    reply,
    zdr_payload,
)

SYSTEM = "You are one lens. Read the change with the tools."
SECOND_LENS = "sweeping-for-security"
SECOND_BODY = "# Sweeping for security\n\nSweep the change for risks.\n"


def prefixed_request(*messages, lens=LENS, body=None, retry_of=None) -> TurnRequest:
    """A turn request shaped the way the loop builds one on the shared
    prefix path (D65): the lens skill in `system`, the shared prefix in
    `prefix`. `lens` and `body` select which lens's skill it carries."""
    text = body if body is not None else BODY
    prefix = SharedPrefix(
        shared_system(CONTRACT, nonce=NONCE),
        fence(UntrustedBlock("pull-request-diff", RepoText(DIFF)), NONCE),
    )
    history = messages or (UserText(job().first_turn),)
    return TurnRequest(
        lens_skill(lens, text, retry_of), history, tool_schemas(), prefix
    )


def request(*messages, tools=None) -> TurnRequest:
    history = messages or (UserText("Review the change."),)
    return TurnRequest(SYSTEM, history, tools if tools is not None else tool_schemas())


def model(*chat, key=None, limits=None, catalog_reply=None, zdr=None, route=None):
    extra = {} if catalog_reply is None else {"model": catalog_reply}
    if zdr is not None:
        extra["zdr"] = zdr
    fake = OpenRouterFake(*chat, key=key, **extra)
    provider = OpenRouterProvider(fake, KEY, limits=limits)
    if route is not None:
        provider.configure(route)
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
    assert body["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in body["provider"]
    assert "plugins" not in body
    assert [tool["function"]["name"] for tool in body["tools"]] == [
        "diff_stat",
        "diff_file",
        "list_files",
        "read_file",
        "grep",
        "run_tests",
        "run_probe",
        "mutate",
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
    assert body["cache_control"] == {"type": "ephemeral"}
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


def test_a_finalize_turn_keeps_the_tools_alongside_the_tool_history():
    """The repeated-refusal stop's finalize turn (issue #693) rides on a
    conversation that already holds assistant tool calls and tool
    results. A request carrying that history next to an empty tools
    array is a shape the pinned routes reject -- Bedrock Converse
    requires a toolConfig when toolUse and toolResult blocks are present
    -- so the finalize request keeps the tool schemas, and the spent
    bridge refuses whatever the model still calls."""
    lens, fake = model(reply(completion("done")))
    lens.turn(
        request(
            UserText("Review the change."),
            AssistantCalls((ToolRequest("diff_stat", {}),)),
            ToolResults(("fenced result",)),
        )
    )
    body = sent(fake)
    assert [tool["function"]["name"] for tool in body["tools"]] == [
        "diff_stat",
        "diff_file",
        "list_files",
        "read_file",
        "grep",
        "run_tests",
        "run_probe",
        "mutate",
    ]
    assert body["messages"][-1]["role"] == "tool"


def test_a_request_with_tool_history_and_no_tools_is_refused_before_any_call():
    """The adapter's shape invariant, pinned: tool history next to an
    empty tools array is refused before any request, so a future
    tool-less finalize turn cannot fail the call mid-review on the pinned
    route. The one tool-less request that exists -- the re-assessment
    call's single user turn -- carries no tool history and still goes
    out."""
    lens, fake = model(reply(completion("done")))
    with pytest.raises(BoundaryError, match="empty tools array"):
        _payload_of(
            lens,
            request(
                UserText("Review the change."),
                AssistantCalls((ToolRequest("diff_stat", {}),)),
                ToolResults(("fenced result",)),
                tools=(),
            ),
        )
    assert fake.chat_requests() == []
    assert _payload_of(lens, request(tools=()))["tools"] == []


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


def test_a_timeout_raises_for_the_loop_to_retry():
    """The adapter sends one request per turn: a read timeout raises
    `TransportTimeoutError`, and the loop owns the one retry -- it must
    reserve the retry as its own call against the shared budget, which a
    retry inside the adapter could not do (review M2)."""
    lens, fake = model(
        TransportTimeoutError(
            "POST https://openrouter.ai/api/v1/chat/completions failed: timed out"
        ),
        reply(completion("done")),
    )
    with pytest.raises(TransportTimeoutError):
        lens.turn(request())
    assert len(fake.chat_requests()) == 1
    assert lens.timeout_s == 300.0


def test_a_byok_credit_balance_400_on_the_lens_path_is_out_of_credit():
    """The agentic adapter classifies the same BYOK 400 the one-shot
    adapter does. The pilot key's identical body stays a per-call error.
    Kills updating only one of the two call sites."""
    body = {
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low. sk-secret",
        }
    }
    lens, fake = model(reply(body, status=400))
    lens.provider.byok_source = True
    with pytest.raises(KeyRefusedError, match="HTTP 400") as refused:
        lens.turn(request())
    assert refused.value.review_error == "model key out of credit"
    assert len(fake.chat_requests()) == 1
    assert "sk-secret" not in str(refused.value)
    assert "credit balance" not in str(refused.value)
    pilot, pilot_fake = model(reply(body, status=400))
    with pytest.raises(BoundaryError, match="HTTP 400") as plain:
        pilot.turn(request())
    assert not isinstance(plain.value, KeyRefusedError)
    assert len(pilot_fake.chat_requests()) == 1


def test_a_transport_error_other_than_a_timeout_is_not_retried():
    lens, fake = model(BoundaryError("connection refused"))
    with pytest.raises(TransportError, match="transport error"):
        lens.turn(request())
    assert len(fake.chat_requests()) == 1


def test_a_zdr_list_timeout_on_the_lens_path_is_recorded_as_a_refusal():
    """Review round 1 of PR #687, Minor 3: the adapter reaches `load_terms`
    directly, not through `complete`, so a ZDR-list read that failed closed
    was never recorded in `budget.refusals` and the budget report did not
    say why no lens call could be made."""

    class Timeout(OpenRouterFake):
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            if str(url).endswith("/endpoints/zdr"):
                raise TransportTimeoutError(
                    "GET https://openrouter.ai/api/v1/endpoints/zdr failed: timed out"
                )
            return super().request(method, url, headers, body, timeout_s, max_bytes)

    fake = Timeout(reply(completion()))
    lens = OpenRouterLensModel(OpenRouterProvider(fake, KEY))
    with pytest.raises(TransportTimeoutError, match="timed out"):
        lens.worst_case_usd(request())
    assert fake.chat_requests() == []
    assert lens.provider.budget.refusals == [
        "GET https://openrouter.ai/api/v1/endpoints/zdr failed: timed out"
    ]
    # One entry per failed read, like the budget's own refusals.
    with pytest.raises(TransportTimeoutError):
        lens.worst_case_usd(request())
    assert len(lens.provider.budget.refusals) == 2


def test_a_zdr_list_http_failure_on_the_lens_path_is_recorded_as_a_refusal():
    """Issue #689: a 5xx is a server error (`BoundaryError`), not a
    refusal (`PricingUnknownError`)."""
    fake = OpenRouterFake(reply(completion()), zdr=reply({}, status=503))
    lens = OpenRouterLensModel(OpenRouterProvider(fake, KEY))
    with pytest.raises(BoundaryError, match="HTTP 503") as excinfo:
        lens.worst_case_usd(request())
    assert not isinstance(excinfo.value, PricingUnknownError)
    assert lens.provider.budget.refusals == [
        "OpenRouter HTTP 503 for https://openrouter.ai/api/v1/endpoints/zdr"
    ]


def test_a_catalog_timeout_on_the_lens_path_is_recorded_as_a_refusal():
    class CatalogTimeout(OpenRouterFake):
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            if "/model/" in str(url):
                raise TransportTimeoutError(
                    f"GET https://openrouter.ai/api/v1/model/{MODEL_ID} "
                    "failed: timed out"
                )
            return super().request(method, url, headers, body, timeout_s, max_bytes)

    fake = CatalogTimeout(reply(completion()))
    lens = OpenRouterLensModel(OpenRouterProvider(fake, KEY))
    with pytest.raises(TransportTimeoutError, match="timed out"):
        lens.worst_case_usd(request())
    assert lens.provider.budget.refusals == [
        f"GET https://openrouter.ai/api/v1/model/{MODEL_ID} failed: timed out"
    ]


def test_a_model_error_after_a_response_is_not_retried():
    lens, fake = model(reply(completion(), status=503))
    with pytest.raises(BoundaryError, match="503"):
        lens.turn(request())
    assert len(fake.chat_requests()) == 1


@pytest.mark.parametrize(
    ("status", "cause"),
    [
        (401, "model key refused"),
        (402, "model key out of credit"),
    ],
)
def test_a_refused_key_from_the_agentic_adapter_is_a_key_refusal(status, cause):
    """D92, as its fix round 3 settles the mapping: the agentic adapter
    classifies a 401/402 as `KeyRefusedError` with the fixed cause text,
    the message carrying a status and a safe URL only -- no key material,
    no response body. Kills the generic-boundary mutant, which would route
    the refusal into the lens loop's D49 retry and book it at its full
    worst case."""
    lens, fake = model(reply(completion(), status=status))
    with pytest.raises(KeyRefusedError) as caught:
        lens.turn(request())
    assert caught.value.review_error == cause
    assert len(fake.chat_requests()) == 1


def test_a_priced_response_the_turn_rejects_carries_its_cost():
    """D92's fix round: a 200 whose usage priced and whose turn then
    failed -- an unfinished turn here -- raises with the parsed cost
    attached, so the settle at the raise site books the real bill. Kills
    the dropped-attachment mutant, which would leave the served call to
    settle at $0."""
    from decimal import Decimal

    lens, _fake = model(
        reply(
            completion(text="later", finish="error"),
        )
    )
    with pytest.raises(BoundaryError) as caught:
        lens.turn(request())
    assert caught.value.reported_cost == Decimal("0.0123")


def test_the_largest_call_reservation_is_the_per_call_cap_priced():
    """D92's fix round: the credit check's per-call figure is the LARGEST
    reservation one call holds -- the per-call input cap priced at the
    endpoint's rates -- and the method is named for what it computes.
    Kills the smaller-bound mutant, which would price a smaller input and
    let a key that cannot fund the largest call through the check."""

    from atlas_reviewer.budget import worst_case_usd
    from atlas_reviewer.tool_model import resolve_per_call

    lens, _fake = model(reply(completion("done")))
    terms, _counts, _selected = lens._ready()
    bounds = resolve_per_call(lens.per_call, terms)
    expected = worst_case_usd(bounds.max_input_tokens, terms, bounds)
    assert lens.largest_call_reservation() == expected
    assert lens.largest_call_reservation() >= worst_case_usd(
        bounds.max_input_tokens // 2, terms, bounds
    )


def test_a_too_large_response_keeps_its_reservation_in_the_loop(tmp_path):
    """D92's fix round 3, the loop-level pin: a `ResponseTooLargeError`
    turn was served, so its reservation stays committed -- the review's
    committed spend ends at the reservation, not at $0. Kills the release
    mutant that the adapter-level attachment alone does not reach (a
    settle that released despite the attached `UNPRICED`)."""
    from decimal import Decimal

    from atlas_reviewer.lens_loop import Spend
    from atlas_reviewer.ports import ResponseTooLargeError

    from .test_lens_loop import CONTRACT, NONCE, job, lens_system

    # Two steps: the too-large call is retried once (D49), and both
    # attempts are served-but-unpriced reservations that stay committed.
    lens, _fake = model(
        ResponseTooLargeError("response exceeded 50 bytes"),
        ResponseTooLargeError("response exceeded 50 bytes"),
    )
    ask = TurnRequest(
        lens_system(
            "tracing-correctness-and-invariants", BODY, CONTRACT, None, nonce=NONCE
        ),
        (UserText(job().first_turn),),
        tool_schemas(),
    )
    worst = lens.worst_case_usd(ask)
    outcome, _m, spend = attempt(
        tmp_path,
        [],
        model=lens,
        spend=Spend(
            replace(LIMITS, reservation_usd=Decimal(5), lens_wall_s=600).resolve()
        ),
    )
    assert Cause.MODEL_ERROR in outcome.causes
    assert spend.committed_usd == 2 * worst


def test_an_unresolvable_per_call_override_names_no_credit_figure():
    """D92's fix round 4: `resolve_per_call` runs inside the same guarded
    read as the terms, so a per-call override above the endpoint's limit
    does not escape the credit check and kill the review before any lens
    starts -- the adapter names no figure, the check accepts, and the lens
    loop reports the limit the same way the turn path does. Kills the
    outside-the-try mutant, which raised `LimitRefused` out of
    `largest_call_reservation`."""
    from atlas_reviewer.coordinator import limits_for_lens, model_for_lens
    from atlas_reviewer.openrouter import OpenRouterProvider

    from .test_openrouter import KEY, OpenRouterFake

    limits = limits_for_lens({"ATLAS_MAX_OUTPUT_TOKENS": "99000"})
    adapter = model_for_lens(OpenRouterProvider(OpenRouterFake(), KEY), limits)
    assert adapter.largest_call_reservation() is None


def test_a_priced_200_with_no_choices_carries_its_cost():
    """D92's fix round 2: `_choice`'s refusal sits between the cost
    computation and the `_priced` raises, so an empty `choices` list on a
    200 whose usage priced left `reported_cost` unset and the settle
    released a real bill at $0. The refusal now carries the parsed cost.
    Kills the unpriced-choice mutant, which would leave the served call
    to settle at $0."""
    from decimal import Decimal

    lens, _fake = model(
        reply(
            {
                "model": MODEL_ID,
                "choices": [],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "cost": "1.25",
                    "is_byok": False,
                },
            }
        )
    )
    with pytest.raises(BoundaryError, match="no choice") as caught:
        lens.turn(request())
    assert caught.value.reported_cost == Decimal("1.25")


def test_a_response_too_large_is_not_a_transport_error():
    """Review Minor 2: `ResponseTooLargeError` is raised after the response
    arrived, so it is a model-level error, not a retryable transport one.
    D92's fix round 3: the converted error is served-but-unpriced -- the
    provider generated the body and may have billed it -- so it carries
    `UNPRICED` and the settle keeps the reservation instead of releasing
    it at $0. Kills the unset-cost mutant on the too-large rewrap."""
    from atlas_reviewer.ports import ResponseTooLargeError
    from atlas_reviewer.tool_model import UNPRICED

    lens, fake = model(ResponseTooLargeError("response exceeded 50 bytes"))
    with pytest.raises(BoundaryError, match="too large") as excinfo:
        lens.turn(request())
    assert not isinstance(excinfo.value, TransportError)
    assert excinfo.value.reported_cost is UNPRICED
    assert len(fake.chat_requests()) == 1


def test_a_403_on_the_agentic_adapter_is_a_plain_per_call_error():
    """D92's fix round 3: a 403 on the agentic adapter stays the plain
    boundary error it was -- a flagged input is a per-request refusal, not
    a key problem -- so the lens loop's D49 retry and the per-lens failure
    apply, and the review is not halted. Kills the key-refusal mutant on
    the adapter's status classification."""
    lens, fake = model(reply(completion(), status=403), reply(completion("later")))
    with pytest.raises(BoundaryError) as caught:
        lens.turn(request())
    assert not isinstance(caught.value, KeyRefusedError)
    assert getattr(caught.value, "review_error", None) is None
    # The next call goes out: the review was not halted.
    assert lens.turn(request()).text == "later"
    assert len(fake.chat_requests()) == 2


def test_the_first_turn_keeps_the_byte_bound():
    lens, _fake = model(reply(completion("done")))
    ask = request()
    expected = len(json.dumps(_payload_of(lens, ask))) + 64
    assert lens.worst_case_usd(ask) == worst_case_usd(
        expected, *_terms_and_bounds(lens)
    )
    assert "no reported usage yet" in lens.bound_note


def _payload_of(lens: OpenRouterLensModel, ask: TurnRequest) -> dict:
    terms, _counts, selected = lens._ready()
    bounds = resolve_per_call(lens.per_call, terms)
    return _payload(lens.provider, ask, terms, bounds, selected)


def _terms_and_bounds(lens: OpenRouterLensModel):
    terms, _counts, _selected = lens._ready()
    return terms, resolve_per_call(lens.per_call, terms)


def test_the_input_bound_comes_from_the_reported_usage_plus_new_messages():
    """D58: the byte bound overcounted tokens about 2.8x on the trial
    calls. After a response reports `prompt_tokens`, the next turn's bound
    is that count plus the new messages' bytes at one token per byte --
    asserted here against an independent literal, not the function under
    test (review round 3, m1)."""
    usage = {"prompt_tokens": 1000, "completion_tokens": 5, "is_byok": False}
    lens, _fake = model(reply(completion("done", usage=usage)))
    first = request()
    lens.worst_case_usd(first)
    lens.turn(first)
    second = request(UserText("Review the change."), UserText("One more question."))
    whole = len(json.dumps(_payload_of(lens, second)))
    prefix = len(
        json.dumps(
            _payload_of(
                lens,
                TurnRequest(SYSTEM, second.messages[:1], second.tools),
            )
        )
    )
    expected = 1000 + (whole - prefix) + 64
    assert lens.worst_case_usd(second) == worst_case_usd(
        expected, *_terms_and_bounds(lens)
    )
    assert f"usage 1000 + {whole - prefix} new bytes" in lens.bound_note
    # The new messages are one short user turn: the estimate is far below
    # what a whole-payload byte bound would have said.
    assert expected < whole + 64


def test_a_conversation_restart_falls_back_to_the_byte_bound():
    usage = {"prompt_tokens": 1000, "completion_tokens": 5, "is_byok": False}
    lens, _fake = model(reply(completion("done", usage=usage)))
    longer = request(
        UserText("Review the change."),
        AssistantCalls((ToolRequest("diff_stat", {}),)),
        ToolResults(("fenced result",)),
    )
    lens.worst_case_usd(longer)
    lens.turn(longer)
    restarted = request()
    lens.worst_case_usd(restarted)
    # A retry attempt's first turn is shorter than the conversation the
    # last response priced: no baseline, so the byte bound.
    assert "the conversation restarted" in lens.bound_note
    expected = len(json.dumps(_payload_of(lens, restarted))) + 64
    assert lens.worst_case_usd(restarted) == worst_case_usd(
        expected, *_terms_and_bounds(lens)
    )


def test_an_input_cap_refusal_names_the_usage_basis():
    usage = {"prompt_tokens": 1000, "completion_tokens": 5, "is_byok": False}
    lens, _fake = model(reply(completion("done", usage=usage)))
    ask = request()
    lens.worst_case_usd(ask)
    lens.turn(ask)
    lens.per_call = replace(lens.per_call, max_input_tokens=8)
    grown = request(UserText("Review the change."), UserText("More context. " * 200))
    with pytest.raises(LimitRefused, match="max_input_tokens") as raised:
        lens.worst_case_usd(grown)
    assert "bound from usage 1000 +" in raised.value.hit.observed


def test_an_unreadable_usage_count_falls_back_to_the_byte_bound():
    lens, _fake = model(reply(completion("done", usage={"is_byok": False})))
    ask = request()
    lens.worst_case_usd(ask)
    lens.turn(ask)
    # The note must be recomputed after the turn: `bound_note` is set by
    # the worst-case call that preceded it, and a stale note would pass
    # for any `prompt_tokens` value the meter accepted (review round 3,
    # m7).
    lens.worst_case_usd(ask)
    assert "no reported usage yet" in lens.bound_note
    # The bound the note names is the whole payload's byte bound.
    assert (
        f"bytes {len(json.dumps(_payload_of(lens, ask)))} + overhead 64"
        in lens.bound_note
    )


def test_an_unreadable_usage_count_after_a_baseline_falls_back_to_the_byte_bound():
    """Review round 4, Minor 4 (CodeRabbit 4569797416): a usable baseline
    followed by unreadable usage must reset to the byte bound -- keeping
    the stale baseline would measure the new bytes from the larger, newer
    prefix and undercount them."""
    usage = {"prompt_tokens": 1000, "completion_tokens": 5, "is_byok": False}
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        reply(completion("done", usage={"is_byok": False})),
    )
    first = request()
    lens.worst_case_usd(first)
    lens.turn(first)
    grown = request(
        UserText("Review the change."),
        AssistantCalls((ToolRequest("diff_stat", {}),)),
        ToolResults(("fenced result",)),
    )
    lens.worst_case_usd(grown)
    lens.turn(grown)
    lens.worst_case_usd(grown)
    assert "no reported usage yet" in lens.bound_note
    assert (
        f"bytes {len(json.dumps(_payload_of(lens, grown)))} + overhead 64"
        in lens.bound_note
    )


def test_a_zero_reported_count_falls_back_to_the_byte_bound():
    """Review Minor 1: a reported `prompt_tokens` of 0 cannot have produced
    a reply; using it as the baseline would ignore the whole prefix."""
    usage = {"prompt_tokens": 0, "completion_tokens": 5, "is_byok": False}
    lens, _fake = model(reply(completion("done", usage=usage)))
    ask = request()
    lens.worst_case_usd(ask)
    lens.turn(ask)
    lens.worst_case_usd(ask)
    assert "no reported usage yet" in lens.bound_note
    assert (
        f"bytes {len(json.dumps(_payload_of(lens, ask)))} + overhead 64"
        in lens.bound_note
    )


def test_an_implausibly_low_count_falls_back_to_the_byte_bound():
    """Review Minor 1: a reported count far below the bytes of the
    conversation it priced is a provider miscount, not a tokenizer; the
    byte bound takes over."""
    from atlas_reviewer.budget import InputTokenMeter

    meter = InputTokenMeter()
    meter.observe(1, 3)
    whole, prefix = 100_000, 90_000
    bound, note = meter.bound(whole, prefix, 5)
    assert bound == whole + 64
    assert "implausibly low" in note


def test_a_changed_system_prompt_resets_the_meter():
    """Review Minor 1: a retry attempt's system prompt carries the refusal
    reasons, so the last reported baseline prices content that is gone;
    the meter resets to the byte bound instead of undercounting."""
    usage = {"prompt_tokens": 1000, "completion_tokens": 5, "is_byok": False}
    lens, _fake = model(reply(completion("done", usage=usage)))
    first = request()
    lens.worst_case_usd(first)
    lens.turn(first)
    retried = TurnRequest(SYSTEM + " A previous attempt was not accepted.", (), ())
    lens.worst_case_usd(retried)
    assert "no reported usage yet" in lens.bound_note


def test_the_timeout_retry_is_its_own_reserved_call(tmp_path):
    """Review M2: the timed-out request keeps its full reservation as
    spent -- it may still be billed (D58 item 5, restored by D92's fix
    round) -- and the retry is its own reserved call against the shared
    budget, counted like any turn."""
    from .test_lens_loop import CONTRACT, NONCE, job, lens_system

    lens, fake = model(
        TransportTimeoutError("POST timed out"),
        reply(completion(final().text, usage={"cost": "0.01", "is_byok": False})),
        reply(completion(final().text, usage={"cost": "0.01", "is_byok": False})),
    )
    # The first request's worst case, measured on the exact conversation
    # the loop's first turn sends.
    ask = TurnRequest(
        lens_system(
            "tracing-correctness-and-invariants", BODY, CONTRACT, None, nonce=NONCE
        ),
        (UserText(job().first_turn),),
        tool_schemas(),
    )
    first_worst = lens.worst_case_usd(ask)
    outcome, _model, spend = attempt(
        tmp_path,
        [],
        model=lens,
        spend=Spend(
            replace(LIMITS, reservation_usd=Decimal(5), lens_wall_s=600).resolve()
        ),
    )
    assert len(fake.chat_requests()) == 3
    assert spend.calls == 3
    # committed = the timed-out request's reservation, kept as spent, plus
    # the retry's and the nudge turn's settled costs.
    assert spend.committed_usd == first_worst + Decimal("0.02")
    assert outcome.causes == {Cause.NO_SOURCE_READ, Cause.FILES_UNREAD}


def test_a_second_timeout_at_the_loop_is_not_retried_again(tmp_path):
    lens, fake = model(
        TransportTimeoutError("POST timed out"),
        TransportTimeoutError("POST timed out"),
    )
    outcome, _model, spend = attempt(
        tmp_path,
        [],
        model=lens,
        spend=Spend(
            replace(LIMITS, reservation_usd=Decimal(5), lens_wall_s=600).resolve()
        ),
    )
    assert outcome.causes == {Cause.TRANSPORT_ERROR, Cause.FILES_UNREAD}
    assert outcome.state is LensState.FAILED
    assert len(fake.chat_requests()) == 2
    # Two requests, both reserved at their worst case, neither settled:
    # the timed-out requests may still be billed.
    assert spend.calls == 2


def test_the_timeout_retry_is_skipped_when_no_clock_room_remains(tmp_path):
    """Review M2: the retry gets a full fresh timeout, so it must not start
    when less than one timeout is left on the lens or review clock."""
    clock = FakeClock()
    clock.advance(350)
    lens, fake = model(TransportTimeoutError("POST timed out"))
    outcome, _model, _spend = attempt(
        tmp_path,
        [],
        model=lens,
        clock=clock,
        spend=Spend(replace(LIMITS, reservation_usd=Decimal(5)).resolve()),
    )
    assert outcome.causes == {Cause.TRANSPORT_ERROR, Cause.FILES_UNREAD}
    assert len(fake.chat_requests()) == 1


def test_the_reasoning_hint_is_recorded_for_the_trace():
    lens, _fake = model(
        reply(completion("done", usage={"cost": "0.01", "is_byok": False}))
    )
    lens.turn(request())
    facts = take_call()
    assert facts is not None
    assert facts.reasoning_hint == 32_000


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
    # 1000 x 0.000006 + 100 x 0.0000225, the highest selected-endpoint rates.
    assert lens.turn(request()).cost_usd == Decimal("0.00825")


def test_a_missing_reasoning_count_settles_instead_of_keeping_the_reservation():
    """Issue #750 through the loop adapter: a model with a reasoning rate
    whose response reports no reasoning-token count used to stay unpriced,
    and the settle kept the call's full reservation as spent -- the keep
    that held a large review at its dollar ceiling after a few calls. The
    missing count now prices the whole completion count at the higher of
    the two rates, which cannot exceed the reservation's own per-token
    worst case, so the settle frees what the reservation held."""
    lens, _fake = model(
        reply(
            completion(
                "done",
                usage={"prompt_tokens": 1000, "completion_tokens": 100},
            )
        ),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    spend = Spend(AgenticLimits().resolve())
    ask = request()
    worst = lens.worst_case_usd(ask)
    assert spend.reserve(worst) is None
    turn = lens.turn(ask)
    assert turn.cost_usd.is_finite()
    # 1000 x 0.000006 + 100 x 0.00005 -- the reasoning rate is the higher
    # of the two rates, so the 100 output tokens price there, not also at
    # the completion rate the old sum added.
    assert turn.cost_usd == Decimal("0.0110")
    spend.settle(worst, turn.cost_usd)
    assert spend.committed_usd == Decimal("0.0110")
    assert spend.committed_usd < worst


def test_a_missing_cost_with_no_cache_counts_uses_the_reservation_input_rate():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "is_byok": False}
    lens, _fake = model(
        reply(completion("done", usage=usage)),
        zdr=reply(zdr_payload(pricing={"input_cache_write": "0.00001"})),
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
        zdr=reply(zdr_payload(pricing={"input_cache_write": "0.00001"})),
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
        zdr=reply(zdr_payload(pricing={"input_cache_read": "0.000001"})),
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
        zdr=reply(zdr_payload(pricing={"input_cache_write": "0.00001"})),
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
        zdr=reply(zdr_payload(pricing={"input_cache_write": "0.00001"})),
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
        zdr=reply(zdr_payload(pricing={"input_cache_write": "0.00001"})),
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
        tool_response("rm", "{}"),
        reply(completion(done.text, usage=usage)),
        reply(completion(done.text, usage=usage)),
    )
    outcome, _, _spend = attempt(
        tmp_path,
        [],
        model=lens,
        limits=replace(LIMITS, reservation_usd=Decimal(5)),
    )
    assert outcome.tools == (ToolUse(UNKNOWN_TOOL, "", Status.REJECTED.name),)
    messages = json.loads(fake.chat_requests()[-1][3])["messages"]
    # The last request also carries the unread-files nudge (D58) after the
    # tool result; the fenced refusal is the message before it.
    tool = messages[-2]
    assert tool["role"] == "tool"
    assert tool["content"].startswith(f'<untrusted-data id="{NONCE}"')
    assert tool["content"].endswith(f'</untrusted-data id="{NONCE}">')
    assert "unknown-tool" in tool["content"]
    assert messages[-1]["role"] == "user"
    assert "unread-files" in messages[-1]["content"]
    assert len(fake.chat_requests()) == 3
    assert lens.provider.budget.calls == []


def test_the_rejected_reply_reaches_the_next_request_as_an_assistant_turn(
    tmp_path,
):
    """CodeRabbit 4569797401: the repair turn carries the rejected reply
    itself, as an assistant turn the model can see, before the repair
    instruction. The loop-level message list is asserted in
    test_lens_loop; this pins the wire serialization through the adapter."""
    usage = {"cost": "0.01", "is_byok": False}
    done = final(finding())
    lens, fake = model(
        tool_response("diff_file", '{"path": "calc.py"}'),
        tool_response("diff_file", '{"path": "config/keys.py"}'),
        reply(completion("Looks fine to me!", usage=usage)),
        reply(completion(done.text, usage=usage)),
    )
    outcome, _, _spend = attempt(
        tmp_path,
        [],
        model=lens,
        limits=replace(LIMITS, reservation_usd=Decimal(5), lens_wall_s=600),
    )
    assert outcome.state is LensState.CLEAN
    assert len(fake.chat_requests()) == 4
    messages = json.loads(fake.chat_requests()[-1][3])["messages"]
    rejected, repair = messages[-2], messages[-1]
    assert rejected == {"role": "assistant", "content": "Looks fine to me!"}
    assert repair["role"] == "user"
    assert "The final reply was not accepted" in repair["content"]
    assert "the reply is not one JSON object" in repair["content"]


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


# --- the prompt-cache sessions (issue #695) ---------------------------------


def cache_usage(prompt, *, cached=None, written=None):
    usage = {"prompt_tokens": prompt, "completion_tokens": 5, "cost": 0.01}
    details = {}
    if cached is not None:
        details["cached_tokens"] = cached
    if written is not None:
        details["cache_write_tokens"] = written
    if details:
        usage["prompt_tokens_details"] = details
    return usage


def marker_system(lens="hunting-silent-failures"):
    begin, end = body_markers(lens, body_digest("the lens body"))
    return f"You are one lens.\n\n{begin}\nthe lens body\n{end}"


def marked_request(system, *messages):
    return TurnRequest(
        system, messages or (UserText("Review the change."),), tool_schemas()
    )


def test_consecutive_turns_of_one_conversation_are_one_cache_session():
    lens, _fake = model(
        reply(completion("thinking", usage=cache_usage(20_000, cached=0, written=20_000))),
        reply(completion("findings", usage=cache_usage(26_000, cached=20_000, written=6_000))),
    )  # fmt: skip
    lens.turn(request())
    lens.turn(request())
    (only,) = lens.cache_sessions()
    assert len(only.turns) == 2
    assert only.misses == 0
    assert only.cache_write_tokens == 26_000
    assert only.final_prompt_tokens == 26_000


def test_a_turn_short_of_the_previous_prompt_counts_as_a_cache_miss():
    lens, _fake = model(
        reply(completion("thinking", usage=cache_usage(20_000, cached=0, written=20_000))),
        reply(completion("findings", usage=cache_usage(26_000, cached=100, written=25_900))),
    )  # fmt: skip
    lens.turn(request())
    lens.turn(request())
    (only,) = lens.cache_sessions()
    assert only.misses == 1


def test_a_turn_with_no_reported_cache_counts_counts_as_a_miss():
    lens, _fake = model(
        reply(completion("thinking", usage=cache_usage(20_000, cached=0, written=20_000))),
        reply(completion("findings", usage=cache_usage(26_000))),
    )  # fmt: skip
    lens.turn(request())
    lens.turn(request())
    (only,) = lens.cache_sessions()
    assert only.misses == 1


def test_a_changed_system_prompt_opens_a_new_session_named_by_the_body_marker():
    first = marker_system("hunting-silent-failures")
    second = marker_system("reviewing-test-quality")
    lens, _fake = model(
        reply(
            completion("thinking", usage=cache_usage(20_000, cached=0, written=20_000))
        ),
        reply(completion("findings", usage=cache_usage(26_000, cached=20_000))),
        reply(
            completion("thinking", usage=cache_usage(30_000, cached=0, written=30_000))
        ),
        reply(completion("findings", usage=cache_usage(34_000, cached=30_000))),
    )
    lens.turn(marked_request(first))
    lens.turn(marked_request(first))
    lens.turn(marked_request(second))
    lens.turn(marked_request(second))
    first_session, second_session = lens.cache_sessions()
    assert first_session.label == "hunting-silent-failures"
    assert first_session.misses == 0
    assert second_session.label == "reviewing-test-quality"
    assert second_session.misses == 0


def test_sessions_render_with_a_run_total():
    lens, _fake = model(
        reply(
            completion("thinking", usage=cache_usage(20_000, cached=0, written=20_000))
        ),
        reply(completion("findings", usage=cache_usage(26_000, cached=100))),
        reply(
            completion("thinking", usage=cache_usage(30_000, cached=0, written=30_000))
        ),
        reply(completion("findings", usage=cache_usage(34_000, cached=30_000))),
    )
    lens.turn(marked_request("one"))
    lens.turn(marked_request("one"))
    lens.turn(marked_request("two"))
    lens.turn(marked_request("two"))
    lines = session_lines(lens.cache_sessions())
    assert "1 cache miss(es)" in lines[0]
    assert lines[-1].startswith("total: 4 turn(s), 1 cache miss(es)")
    assert lines[-1].endswith(
        "50000 cache-write token(s) against 60000 token(s) of final context, "
        "first-turn cache reads summing to 0 token(s)."
    )
    assert "first-turn cache reads summing to 0 token(s)" in lines[-1]


# ---------------------------------------------------- the shared diff prefix


def _breakpoint_index(parts: list) -> int:
    return next(i for i, part in enumerate(parts) if "cache_control" in part)


def cached_prefix_bytes(body: dict) -> bytes:
    """What a prompt cache would match on: the tools and every message up
    to and including the one content part that carries the explicit
    breakpoint, serialized. The comparison is over bytes, not structure,
    so a byte-level difference a structural check would miss fails here."""
    for index, message in enumerate(body["messages"]):
        content = message.get("content")
        if isinstance(content, list) and any("cache_control" in p for p in content):
            cut = _breakpoint_index(content)
            prefix = {
                "tools": body["tools"],
                "messages": [
                    *body["messages"][:index],
                    {**message, "content": content[: cut + 1]},
                ],
            }
            return json.dumps(prefix, sort_keys=True).encode()
    raise AssertionError("the request carries no cache breakpoint")


def test_the_shared_prefix_is_byte_identical_across_lenses_and_a_retry():
    """Mutant M1: any lens-specific byte in the shared block -- the lens
    name, the body, a per-lens nonce, a per-attempt preamble -- breaks the
    byte equality across two lenses and across the same lens's retry."""
    first, first_fake = model(reply(completion("ok")), reply(completion("ok")))
    second, second_fake = model(reply(completion("ok")))
    first.turn(prefixed_request())
    second.turn(prefixed_request(lens=SECOND_LENS, body=SECOND_BODY))
    retry = prefixed_request(
        retry_of=AttemptOutcome(Attestation.UNACKNOWLEDGED, frozenset({Cause.UNPARSED}))
    )
    first.turn(retry)
    a = cached_prefix_bytes(json.loads(first_fake.chat_requests()[0][3]))
    b = cached_prefix_bytes(json.loads(second_fake.chat_requests()[0][3]))
    r = cached_prefix_bytes(json.loads(first_fake.chat_requests()[1][3]))
    assert a == b == r
    # The cached prefix carries the real tools, not an empty list (mutant
    # P15: an empty `tools` on both sides stays byte-identical and would
    # cache a prefix no real request sends).
    prefix_object = json.loads(a)
    assert [tool["function"]["name"] for tool in prefix_object["tools"]] == [
        "diff_stat",
        "diff_file",
        "list_files",
        "read_file",
        "grep",
        "run_tests",
        "run_probe",
        "mutate",
    ]
    # The lens-specific text sits after the breakpoint: the retry's own
    # skill text (its preamble names the refused attempt) is not in any
    # cached prefix, and neither is the other lens's body.
    assert body_markers(LENS, body_digest(BODY))[0].encode() not in a
    assert body_markers(SECOND_LENS, body_digest(SECOND_BODY))[0].encode() not in a


def test_the_first_non_system_message_differs_per_lens():
    """Minor 2 (review round 1 of #704): OpenRouter's sticky-routing hash
    covers the first system message and the first non-system message. The
    layout keeps the lens skill and the turn-1 text in that first
    non-system message, so the routing key differs per lens and the
    locality claim rests on D63's endpoint pin; what the lenses share is
    the breakpoint-marked part 0, the fenced diff."""
    first, first_fake = model(reply(completion("ok")))
    second, second_fake = model(reply(completion("ok")))
    first.turn(prefixed_request())
    second.turn(prefixed_request(lens=SECOND_LENS, body=SECOND_BODY))
    a = json.loads(first_fake.chat_requests()[0][3])
    b = json.loads(second_fake.chat_requests()[0][3])
    assert a["messages"][0]["content"] == b["messages"][0]["content"]
    assert a["messages"][1]["content"][0] == b["messages"][1]["content"][0]
    assert a["messages"][1]["content"][1] != b["messages"][1]["content"][1]
    assert a["messages"][1]["content"][2] == b["messages"][1]["content"][2]


def test_the_explicit_breakpoint_sits_on_the_diff_part_of_the_prefix():
    """Mutant M2: dropping the part-level `cache_control`, or marking a
    different part, leaves the shared block uncached or caches lens
    material with it. The top-level automatic `cache_control` stays (D57),
    so the growing tail keeps caching as it does today."""
    lens, fake = model(reply(completion("ok")), reply(completion("ok")))
    lens.turn(prefixed_request())
    body = sent(fake)
    assert body["cache_control"] == {"type": "ephemeral"}
    system, user = body["messages"][0], body["messages"][1]
    assert user["role"] == "user"
    parts = user["content"]
    assert all(part["type"] == "text" for part in parts)
    assert parts[0]["cache_control"] == {"type": "ephemeral"}
    assert parts[0]["text"] == fence(
        UntrustedBlock("pull-request-diff", RepoText(DIFF)), NONCE
    )
    assert parts[1]["text"] == lens_skill(LENS, BODY)
    assert parts[2]["text"] == job().first_turn
    assert system["role"] == "system"
    assert system["content"] == shared_system(CONTRACT, nonce=NONCE)
    # The rest of the conversation follows as it does without a prefix.
    followup = prefixed_request(
        UserText(job().first_turn),
        AssistantCalls((ToolRequest("diff_stat", {}),)),
        ToolResults((fence(UntrustedBlock("tool-result", RepoText("ok")), NONCE),)),
    )
    lens.turn(followup)
    later = json.loads(fake.chat_requests()[-1][3])
    assert later["messages"][1]["content"] == parts
    assert later["messages"][2]["role"] == "assistant"
    assert later["messages"][3]["role"] == "tool"


def test_a_route_without_cache_control_support_gets_no_marker():
    """Mutant M3: marking a part on a route whose endpoints do not list
    `cache_control` would have `require_parameters` refuse the request.
    The layout stays; the marker does not."""
    from atlas_reviewer.openrouter import model_route

    other = "z-ai/glm-5.3"
    catalog_row = catalog()
    catalog_row["data"]["id"] = other
    rows = zdr_payload(other, parameters=["max_tokens", "tools"])
    lens, fake = model(
        reply(completion("ok", model=other)),
        catalog_reply=reply(catalog_row),
        zdr=reply(rows),
        route=model_route({}, model=other),
    )
    lens.turn(prefixed_request())
    body = sent(fake)
    assert "cache_control" not in body
    parts = body["messages"][1]["content"]
    assert all("cache_control" not in part for part in parts)
    assert parts[0]["text"].startswith('<untrusted-data id="')
    assert body["messages"][0]["content"] == shared_system(CONTRACT, nonce=NONCE)


def test_the_prefix_priced_turn_still_bounds_the_input_from_the_meter():
    """The prefix rides the same pricing path: the byte-bound first turn
    counts the prefix's bytes, and a later turn's bound is the reported
    baseline plus the new messages, prefix included in both sides of that
    difference."""
    lens, fake = model(
        reply(
            completion(
                "ok",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "cost": "0.01",
                    "is_byok": False,
                },
            )
        ),
        reply(
            completion(
                "ok",
                usage={
                    "prompt_tokens": 130,
                    "completion_tokens": 5,
                    "cost": "0.01",
                    "is_byok": False,
                },
            )
        ),
    )
    first = prefixed_request()
    lens.worst_case_usd(first)
    lens.turn(first)
    followup = prefixed_request(
        UserText(job().first_turn),
        AssistantCalls((ToolRequest("diff_stat", {}),)),
        ToolResults((fence(UntrustedBlock("tool-result", RepoText("ok")), NONCE),)),
    )
    bound = lens.worst_case_usd(followup)
    assert bound > 0
    assert len(fake.chat_requests()) == 1
