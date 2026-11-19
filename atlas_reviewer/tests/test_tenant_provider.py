# SPDX-License-Identifier: MIT
"""The tenant-supplied model endpoint's client (config slice S10, part
A): the operator price table as the pricing source with zero-priced
models allowed, the settlement that never reads `usage.cost` or
`cost_details.upstream_inference_cost`, the reservations computed from
operator inputs, the named failures (auth, quota, endpoint down, egress,
unknown price), and the never-echoed key. Offline: fake transports and
catalogs only."""

import json
from decimal import Decimal

import pytest

from atlas_reviewer.budget import CallLimits
from atlas_reviewer.egress import EgressRefused
from atlas_reviewer.installation_store import TenantCredentials
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    FinalReply,
    ToolCalls,
    ToolRequest,
    TurnRequest,
    UserText,
    resolve_per_call,
)
from atlas_reviewer.ports import BoundaryError, TransportError
from atlas_reviewer.prompt import Prompt
from atlas_reviewer.tenant_provider import (
    ENV_TENANT_BASE_URL,
    ENV_TENANT_MODEL,
    ENV_TENANT_MODEL_KEY,
    TenantEndpointProvider,
    TenantLensModel,
    tenant_environment,
    terms_from_catalog,
)
from atlas_reviewer.tool_model import _bounds

CREDENTIALS = TenantCredentials(
    "https://models.example.invalid/api/v1",
    "sk-tenant-fixture-not-a-real-key",
    "openai/gpt-4o",
)
PROMPT = Prompt("be brief.", "review this diff.", ("diff",))


def _catalog_doc(
    *,
    prompt="0.0000015",
    completion="0.0000075",
    model_id="openai/gpt-4o",
    context=200_000,
    completion_cap=64_000,
):
    return {
        "data": {
            "id": model_id,
            "pricing": {"prompt": prompt, "completion": completion},
            "context_length": context,
            "top_provider": {"max_completion_tokens": completion_cap},
        }
    }


def _provider(
    responses,
    *,
    credentials=CREDENTIALS,
    catalog=None,
    limits=None,
    sleep=lambda _s: None,
):
    """A provider whose transport answers `responses` in order and whose
    catalog is injected. Each transport call records what it was sent."""

    class _Transport:
        def __init__(self):
            self.calls: list[dict[str, object]] = []
            self._last: object = None

        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "headers": dict(headers),
                    "body": body,
                    "timeout_s": timeout_s,
                }
            )
            # An empty list repeats the last answer, the way a live
            # transport fails the same way twice in a row.
            answer = responses.pop(0) if responses else self._last
            self._last = answer
            if isinstance(answer, Exception):
                raise answer

            class _Resp:
                status = answer[0]
                body = answer[1]

                @staticmethod
                def header(name):
                    return answer[2].get(name) if len(answer) > 2 else None

            return _Resp()

    transport = _Transport()
    provider = TenantEndpointProvider(
        transport,  # type: ignore[arg-type]
        credentials,
        limits=limits or CallLimits(),
        catalog=catalog if catalog is not None else (lambda _path: _catalog_doc()),
        sleep=sleep,
    )
    return provider, transport


_UNSET = object()


def _completion_body(
    *,
    prompt_tokens=100,
    completion_tokens=20,
    reasoning_tokens=None,
    cost=None,
    upstream=None,
    model="openai/gpt-4o",
    content="Findings: none that survived verification.",
    finish="stop",
):
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    if cost is not None:
        usage["cost"] = cost
    if upstream is not _UNSET and upstream is not None:
        usage["cost_details"] = {"upstream_inference_cost": upstream}
    return json.dumps(
        {
            "id": "x",
            "model": model,
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": usage,
        }
    ).encode()


# --------------------------------------------------------- the price table


def test_the_price_table_prices_the_model_at_the_operators_rates():
    terms = terms_from_catalog(_catalog_doc(), "openai/gpt-4o")
    assert terms.prompt_rate == Decimal("0.0000015")
    assert terms.completion_rate == Decimal("0.0000075")
    assert terms.context_length == 200_000
    assert terms.max_completion_tokens == 64_000


def test_a_zero_priced_model_is_allowed_by_the_price_table():
    """D81's 5:13 PM CT answer to Q3: the dollar bounds accumulate
    nothing for it, so the call caps and walls are its bound."""
    terms = terms_from_catalog(
        _catalog_doc(prompt="0", completion="0"), "openai/gpt-4o"
    )
    assert terms.prompt_rate == 0
    assert terms.completion_rate == 0
    assert terms.input_rate == 0


def test_a_model_with_no_price_table_entry_is_refused_with_the_reason_named():
    with pytest.raises(BoundaryError) as exc:
        terms_from_catalog({}, "openai/gpt-4o")
    assert "price table" in str(exc.value)


def test_a_price_table_entry_for_another_model_is_refused():
    with pytest.raises(BoundaryError) as exc:
        terms_from_catalog(_catalog_doc(model_id="other/model"), "openai/gpt-4o")
    assert "not 'openai/gpt-4o'" in str(exc.value)


def test_preflight_reads_the_operators_table_and_caches_it():
    reads: list[str] = []
    provider, transport = _provider(
        [], catalog=lambda path: reads.append(path) or _catalog_doc()
    )
    terms = provider.preflight()
    assert terms.prompt_rate == Decimal("0.0000015")
    provider.preflight()
    assert reads == ["/model/openai/gpt-4o"]
    assert transport.calls == []


def test_an_unreadable_price_table_refuses_with_the_reason_named():
    provider, _transport = _provider([], catalog=lambda _path: {"no": "entry"})
    with pytest.raises(BoundaryError) as exc:
        provider.preflight()
    assert "price table" in str(exc.value)


# ------------------------------------------------------- the env resolver


def test_the_child_env_resolver_answers_none_when_no_variable_is_set():
    assert tenant_environment({}) is None


def test_the_child_env_resolver_builds_the_credentials():
    route = tenant_environment(
        {
            ENV_TENANT_MODEL_KEY: "sk-x",
            ENV_TENANT_BASE_URL: "https://models.example.invalid/api/v1",
            ENV_TENANT_MODEL: "openai/gpt-4o",
        }
    )
    assert route == TenantCredentials(
        "https://models.example.invalid/api/v1", "sk-x", "openai/gpt-4o"
    )


def test_a_partial_tenant_environment_refuses_naming_the_missing_variable():
    for partial in (
        {ENV_TENANT_MODEL_KEY: "sk-x"},
        {ENV_TENANT_BASE_URL: "https://x.invalid"},
        {ENV_TENANT_MODEL: "openai/gpt-4o"},
        {ENV_TENANT_MODEL_KEY: "sk-x", ENV_TENANT_BASE_URL: "https://x.invalid"},
        {ENV_TENANT_BASE_URL: "https://x.invalid", ENV_TENANT_MODEL: "openai/gpt-4o"},
    ):
        with pytest.raises(BoundaryError) as exc:
            tenant_environment(partial)
        assert "incomplete" in str(exc.value)


# -------------------------------------------------------- the client path


def test_a_completed_call_settles_from_tokens_at_the_operators_table():
    provider, transport = _provider(
        [(200, _completion_body(prompt_tokens=1000, completion_tokens=200))]
    )
    assert provider.preflight() is not None
    text = provider.complete(PROMPT)
    assert "no model findings" not in text
    (call,) = transport.calls
    assert call["url"] == "https://models.example.invalid/api/v1/chat/completions"
    body = json.loads(call["body"])  # type: ignore[arg-type]
    assert body["model"] == "openai/gpt-4o"
    assert body["messages"][0]["content"] == "be brief."
    # The Authorization header carries the key; the URL never does.
    assert call["headers"]["Authorization"] == f"Bearer {CREDENTIALS.key}"
    assert "sk-tenant" not in call["url"]
    # 1000 input at $1.50/M + 200 output at $7.50/M = $0.003.
    record = provider.budget.calls[0]
    assert record.actual_usd == Decimal("0.0030")


def test_a_reported_usage_cost_is_never_read_on_the_tenant_path():
    """The pin the plan demands (D81 §4): the endpoint's own cost
    figures -- `usage.cost` and `cost_details.upstream_inference_cost`
    -- are not the tenant path's accounting. A hostile endpoint that
    reports $0.00 (or anything) cannot change what the tokens priced."""
    provider, _transport = _provider(
        [
            (
                200,
                _completion_body(
                    prompt_tokens=1000,
                    completion_tokens=200,
                    cost="0.00",
                    upstream="0.00",
                ),
            )
        ]
    )
    provider.preflight()
    provider.complete(PROMPT)
    record = provider.budget.calls[0]
    assert record.actual_usd == Decimal("0.0030")


def test_a_deflated_reported_count_changes_only_the_settled_total():
    """The second pin: the reservation comes from operator inputs (the
    byte bound and the operator's caps), before the endpoint answers; a
    deflated reported count can only shrink the settled figure -- the
    tenant's own ledger number -- never the reservation."""
    provider, _transport = _provider(
        [(200, _completion_body(prompt_tokens=1, completion_tokens=1))]
    )
    provider.preflight()
    provider.complete(PROMPT)
    (record,) = provider.budget.calls
    assert record.reserved_usd > Decimal("0.10")
    assert record.actual_usd == Decimal("0.000009")
    assert record.reserved_usd > record.actual_usd


def test_a_zero_priced_model_settles_at_zero():
    provider, _transport = _provider(
        [(200, _completion_body(prompt_tokens=5000, completion_tokens=900))],
        catalog=lambda _path: _catalog_doc(prompt="0", completion="0"),
    )
    provider.preflight()
    provider.complete(PROMPT)
    (record,) = provider.budget.calls
    assert record.actual_usd == 0


def test_an_auth_error_names_itself_and_never_the_key():
    provider, _transport = _provider([(401, b'{"error": "bad key"}')])
    provider.preflight()
    with pytest.raises(BoundaryError) as exc:
        provider.complete(PROMPT)
    assert "auth error (HTTP 401" in str(exc.value)
    assert CREDENTIALS.key not in str(exc.value)


def test_a_quota_error_names_itself():
    provider, _transport = _provider([(402, b'{"error": "no credits"}')])
    provider.preflight()
    with pytest.raises(BoundaryError) as exc:
        provider.complete(PROMPT)
    assert "quota error (HTTP 402" in str(exc.value)
    assert CREDENTIALS.key not in str(exc.value)


def test_an_endpoint_error_names_the_status():
    provider, _transport = _provider([(503, b"down")])
    provider.preflight()
    with pytest.raises(BoundaryError) as exc:
        provider.complete(PROMPT)
    assert "HTTP 503" in str(exc.value)


def test_a_transport_failure_names_the_endpoint():
    provider, _transport = _provider([BoundaryError("connect refused: 127.0.0.1:9")])
    provider.preflight()
    with pytest.raises(BoundaryError) as exc:
        provider.complete(PROMPT)
    # The failure raised is the transport's own named reason; the
    # settle line recorded it with the transport-error prefix, and the
    # key is in neither.
    assert "connect refused" in str(exc.value)
    assert CREDENTIALS.key not in str(exc.value)
    assert "transport error: connect refused" in provider.budget.calls[0].outcome


def test_a_redirect_is_refused_by_name():
    provider, _transport = _provider([(302, b"", {"Location": "https://other/"})])
    provider.preflight()
    with pytest.raises(BoundaryError) as exc:
        provider.complete(PROMPT)
    assert "redirects are refused" in str(exc.value)


def test_an_egress_refusal_fails_the_call_named():
    """The transport's refusal -- a blocked address, a rebinding double
    -- is the review's named failure; it is never retried into a
    fallback."""
    provider, _transport = _provider(
        [EgressRefused("egress refused: the endpoint's address is in 10.0.0.0/8")]
    )
    provider.preflight()
    with pytest.raises(BoundaryError) as exc:
        provider.complete(PROMPT)
    assert "egress refused" in str(exc.value)


def test_a_retryable_status_retries_within_the_call_cap():
    provider, transport = _provider(
        [(500, b"boom"), (200, _completion_body())], sleep=lambda _s: None
    )
    provider.preflight()
    provider.complete(PROMPT)
    assert len(transport.calls) == 2


def test_a_missing_usage_keeps_the_full_reservation():
    provider, _transport = _provider(
        [(200, _completion_body(prompt_tokens=None, completion_tokens=None))]
    )
    provider.preflight()
    provider.complete(PROMPT)
    (record,) = provider.budget.calls
    assert record.actual_usd is None
    assert record.committed_usd == record.reserved_usd


# ------------------------------------------------------------ the adapter


def _request(*messages, tools=(), system="lens body", prefix=None, cap=None):
    return TurnRequest(
        system=system,
        messages=messages,  # type: ignore[arg-type]
        tools=tools,
        prefix=prefix,
        max_output_tokens=cap,
    )


def _resolved():
    terms = terms_from_catalog(_catalog_doc(), "openai/gpt-4o")
    return resolve_per_call(AgenticLimits().resolve(), terms)


def test_the_adapter_turn_returns_a_final_reply_priced_from_tokens():
    provider, transport = _provider(
        [(200, _completion_body(prompt_tokens=1000, completion_tokens=200))]
    )
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    reply = model.turn(_request(UserText("go")))
    assert isinstance(reply, FinalReply)
    assert reply.cost_usd == Decimal("0.0030")
    (call,) = transport.calls
    assert call["url"] == "https://models.example.invalid/api/v1/chat/completions"


def test_the_adapter_turn_parses_tool_calls():
    body = json.dumps(
        {
            "model": "openai/gpt-4o",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "diff_file",
                                    "arguments": '{"path": "a.py"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    ).encode()
    provider, _transport = _provider([(200, body)])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    turn = model.turn(_request(UserText("go")))
    assert isinstance(turn, ToolCalls)
    assert turn.calls == (ToolRequest("diff_file", {"path": "a.py"}),)
    assert turn.cost_usd == Decimal("0.0000525")


def test_the_adapter_settles_tool_work_without_reading_usage_cost():
    body = json.dumps(
        {
            "model": "openai/gpt-4o",
            "choices": [
                {
                    "message": {"content": "done"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "cost": "999.99",
                "cost_details": {"upstream_inference_cost": "999.99"},
            },
        }
    ).encode()
    provider, _transport = _provider([(200, body)])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    reply = model.turn(_request(UserText("go")))
    assert reply.cost_usd == Decimal("0.0000525")


def test_the_adapter_refuses_a_served_model_mismatch_by_name():
    provider, _transport = _provider([(200, _completion_body(model="other/model"))])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    with pytest.raises(BoundaryError) as exc:
        model.turn(_request(UserText("go")))
    assert "served 'other/model'" in str(exc.value)


def test_the_adapter_refuses_an_output_length_stop():
    provider, _transport = _provider([(200, _completion_body(finish="length"))])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    from atlas_reviewer.limit_stop import LimitRefused

    with pytest.raises(LimitRefused):
        model.turn(_request(UserText("go")))


def test_the_adapter_names_an_auth_error_and_keeps_the_key_out():
    provider, _transport = _provider([(401, b"{}")])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    with pytest.raises(BoundaryError) as exc:
        model.turn(_request(UserText("go")))
    assert "auth error (HTTP 401" in str(exc.value)
    assert CREDENTIALS.key not in str(exc.value)


def test_the_adapter_wraps_an_egress_refusal_as_the_named_failure():
    provider, _transport = _provider(
        [EgressRefused("egress refused: the endpoint's address is in 10.0.0.0/8")]
    )
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    with pytest.raises(TransportError) as exc:
        model.turn(_request(UserText("go")))
    assert "egress refused" in str(exc.value)


def test_the_adapter_worst_case_comes_from_operator_inputs():
    """The reservation is the byte bound of the actual request priced at
    the operator's table and caps -- computed before the endpoint
    answers, never from a tenant-reported figure."""
    provider, _transport = _provider([])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    request = _request(UserText("x" * 10_000))
    worst = model.worst_case_usd(request)
    terms = terms_from_catalog(_catalog_doc(), "openai/gpt-4o")
    bounds = _bounds(model.per_call, terms, request)
    from atlas_reviewer.tenant_provider import _tenant_payload

    whole = len(json.dumps(_tenant_payload(request, terms, bounds)))
    # The meter's byte bound for the first call: the whole serialized
    # request plus the overhead, at the operator's input rate; the
    # operator's output cap at the higher output rate.
    expected = (whole + 64) * terms.input_rate + bounds.max_output_tokens * max(
        terms.completion_rate, terms.reasoning_rate
    )
    assert worst == expected


def test_the_adapter_output_cap_on_a_zero_priced_model_is_the_resolved_cap():
    """No dollar rate to divide by: the resolved cap stands, and the
    call caps and walls are the bound (D81's Q3 answer)."""
    provider, _transport = _provider(
        [],
        catalog=lambda _path: _catalog_doc(prompt="0", completion="0"),
    )
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    request = _request(UserText("x" * 10_000))
    assert (
        model.output_tokens_within(request, Decimal("0.01"))
        == _resolved().max_output_tokens
    )


def test_the_adapter_output_cap_fits_the_budget():
    provider, _transport = _provider([])
    provider.preflight()
    model = TenantLensModel(provider, per_call=_resolved())
    request = _request(UserText("x" * 10_000))
    cap = model.output_tokens_within(request, Decimal("1.00"))
    assert 0 < cap <= _resolved().max_output_tokens
    # An input alone over the budget leaves no room: below 1, the same
    # documented outcome the operator adapter's arithmetic has.
    assert model.output_tokens_within(request, Decimal("0.0001")) < 1


def test_the_adapter_name_carries_the_endpoint_class():
    provider, _transport = _provider([])
    assert provider.name == "tenant-endpoint:openai/gpt-4o"
    model = TenantLensModel(provider)
    assert model.name == "tenant-endpoint:openai/gpt-4o"


def test_the_adapter_usage_lines_name_the_tenant_endpoint():
    provider, _transport = _provider([])
    provider.preflight()
    lines = provider.usage_lines()
    assert lines[0].startswith(
        "model `openai/gpt-4o` via the installation's own endpoint (tenant-supplied)"
    )
    assert CREDENTIALS.key not in " ".join(lines)
