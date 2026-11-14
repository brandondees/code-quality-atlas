# SPDX-License-Identifier: MIT
"""The live tool-calling model, on the controller, over OpenRouter.

One `LensModel` turn is one Chat Completions request. It sends the same
pinned provider document as the one-shot adapter (`only`, no fallbacks,
`require_parameters`, `data_collection: deny`, no plugins and no
server tools). `zdr` is sent only when the route requires it.
`reasoning` is added only when every selected endpoint
lists it in `supported_parameters`. `cache_control` is sent on every
Anthropic-family route even when no endpoint lists it (D57). The lens loop
reserves the worst case and settles `_actual_cost` (BYOK upstream
included) through its own spend tracker. A turn with no readable cost
but usable token counts is priced from the selected endpoints: prompt
tokens at the highest of the prompt and cache-write rates, or, when the
response reports cache read or write counts, with those counts at the
endpoints' cache rates (a missing read rate uses the prompt rate, and a missing
write rate uses the reservation's input rate). A model with a reasoning
rate and a response that reports no reasoning-token count stays
unpriced. That missing-cost case is a non-finite
`Decimal`, which the tracker keeps at the worst case, as are an
unreadable upstream charge, a BYOK call with no upstream charge, and a
turn with neither a readable cost nor usable token counts. A readable
cost is used as reported, including when the reasoning-token count is
missing. This module does not touch that tracker's rules, and it does
not reserve on the one-shot `ReviewBudget` (that budget's ceiling is
the one-shot 3 calls and $3).

Tool calls are parsed and handed back. The loop runs them through the
bridge, which rejects an unknown tool or bad arguments before anything
executes and returns that refusal, nonce-fenced, as the next tool
result. This module does not execute a tool and does not retry a call:
a retry would be a second billed request under one reservation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from atlas_reviewer.budget import (
    TokenBoundError,
    check_tokens,
    input_token_bound,
    worst_case_usd,
)
from atlas_reviewer.call_facts import CallFacts, note_call
from atlas_reviewer.http import safe_url
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    AssistantCalls,
    AssistantText,
    FinalReply,
    Limits,
    Message,
    ModelTurn,
    ResolvedCall,
    ToolCalls,
    ToolRequest,
    ToolSchema,
    TurnRequest,
    UserText,
    resolve_per_call,
)
from atlas_reviewer.limit_stop import LimitRefused, hit
from atlas_reviewer.openrouter import (
    OpenRouterProvider,
    SelectedEndpoints,
    _actual_cost,
    _is_configured_model,
    _json_object,
    _no_byok_reason,
    _tokens,
    optional_parameters,
    provider_preferences,
)
from atlas_reviewer.ports import BoundaryError, ByokRefusedError
from atlas_reviewer.pricing import ModelTerms

# Not a price. `Spend.settle` keeps the reservation when the cost is not
# a finite Decimal greater than or equal to zero.
UNPRICED = Decimal("Infinity")


class OpenRouterLensModel:
    """The phase-3 `LensModel` port, backed by the one-shot OpenRouter client."""

    def __init__(
        self, provider: OpenRouterProvider, per_call: Limits | None = None
    ) -> None:
        self.provider = provider
        # None derives the per-call bounds from the selected endpoints.
        # The one-shot CallLimits on the provider stay the D25 ceilings
        # and are not the agentic input cap. `review_lens` refuses this
        # object when `per_call` is not the limits that review resolved.
        self.per_call = AgenticLimits().resolve() if per_call is None else per_call
        self._ready_for_turn: tuple[ModelTerms, bool, SelectedEndpoints] | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    def routing(self) -> tuple[bool, bool] | None:
        """ZDR required, and whether `cache_control` is on the request."""
        return self.provider.routing()

    def diagnosis(self) -> dict[str, str] | None:
        """Selected tags and the terms those rows set."""
        return self.provider.diagnosis()

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        terms, counts_byok, selected = self._ready()
        # The loop prices the turn and then places it. The endpoint
        # snapshot is loaded once for this provider and reused for later
        # turns in the review.
        self._ready_for_turn = (terms, counts_byok, selected)
        bounds = resolve_per_call(self.per_call, terms)
        payload = _payload(self.provider, request, terms, bounds, selected)
        bound = input_token_bound(json.dumps(payload))
        try:
            check_tokens(bound, terms, bounds)
        except TokenBoundError as exc:
            limit = exc.limit
            bound_by = ""
            prompt_binds = (
                terms.max_prompt_tokens is not None
                and bounds.max_input_tokens == terms.max_prompt_tokens
                and terms.max_prompt_tokens
                < terms.context_length - bounds.max_output_tokens
            )
            if limit == "max_input_tokens" and prompt_binds:
                limit = "max_prompt_tokens"
                bound_by = terms.prompt_limit_tags
            elif limit == "context_length":
                bound_by = terms.context_limit_tags
            elif limit == "max_output_tokens":
                bound_by = terms.completion_limit_tags
            elif limit == "max_prompt_tokens":
                bound_by = terms.prompt_limit_tags
            raise LimitRefused(
                hit(limit, exc.configured, exc.observed, bound_by=bound_by)
            ) from exc
        return worst_case_usd(bound, terms, bounds)

    def turn(self, request: TurnRequest) -> ModelTurn:
        """One request, no retry. The loop counts the call and settles the cost."""
        cached = self._ready_for_turn
        self._ready_for_turn = None
        terms, counts_byok, selected = self._ready() if cached is None else cached
        bounds = resolve_per_call(self.per_call, terms)
        payload = _payload(self.provider, request, terms, bounds, selected)
        url = f"{self.provider._api_url}/chat/completions"
        body = json.dumps(payload).encode()
        try:
            resp = self.provider._transport.request(
                "POST",
                url,
                self.provider._headers(authed=True, json_body=True),
                body,
                self.provider._timeout_s,
            )
        except BoundaryError as exc:
            raise BoundaryError(f"OpenRouter transport error: {exc}") from exc
        if resp.status != 200:
            raise BoundaryError(f"OpenRouter HTTP {resp.status} for {safe_url(url)}")
        try:
            data = _json_object(resp.body, "OpenRouter chat completion", BoundaryError)
        except BoundaryError:
            if not counts_byok:
                raise ByokRefusedError(
                    "refusing the review: this OpenRouter key does not count "
                    "BYOK spend against its credit limit, and the response "
                    "could not be parsed, so is_byok could not be checked"
                ) from None
            raise
        return _turn(
            data, terms, counts_byok, self.provider.model_id, bounds.max_output_tokens
        )

    def _ready(self) -> tuple[ModelTerms, bool, SelectedEndpoints]:
        if self.provider._key_status is None:
            self.provider.preflight()
        status = self.provider._key_status
        if status is None:
            raise BoundaryError("refusing inference: key preflight has not passed")
        terms, selected = self.provider.load_terms()
        return terms, status.counts_byok, selected


def _payload(
    provider: OpenRouterProvider,
    request: TurnRequest,
    terms: ModelTerms,
    limits: ResolvedCall,
    selected: SelectedEndpoints,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": provider.model_id,
        "messages": _messages(request),
        "tools": [_tool(tool) for tool in request.tools],
        # Always the configured output cap, even when the endpoint does
        # not list max_tokens. The reservation prices this cap.
        "max_tokens": limits.max_output_tokens,
        "stream": False,
        "provider": provider_preferences(
            selected.providers, terms, require_zdr=selected.require_zdr
        ),
    }
    payload.update(
        optional_parameters(
            selected.supported,
            limits.reasoning_max_tokens,
            model_id=provider.model_id,
        )
    )
    return payload


def _tool(tool: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _messages(request: TurnRequest) -> list[dict[str, Any]]:
    """History in OpenAI chat shape. Tool-call ids are assigned here, and
    the following tool results must line up with them. Result text is sent
    unchanged, fence included."""
    out: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
    pending: tuple[str, ...] | None = None
    for message in request.messages:
        pending = _one_message(out, message, pending)
    if pending is not None:
        raise BoundaryError("a tool result is missing")
    return out


def _one_message(
    out: list[dict[str, Any]], message: Message, pending: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    if isinstance(message, UserText):
        if pending is not None:
            raise BoundaryError("a tool result is missing")
        out.append({"role": "user", "content": message.text})
        return None
    if isinstance(message, AssistantText):
        if pending is not None:
            raise BoundaryError("a tool result is missing")
        out.append({"role": "assistant", "content": message.text})
        return None
    if isinstance(message, AssistantCalls):
        if pending is not None:
            raise BoundaryError("a tool result is missing")
        ids = tuple(f"call-{len(out)}-{n}" for n in range(len(message.calls)))
        out.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    _echo(call_id, call)
                    for call_id, call in zip(ids, message.calls, strict=True)
                ],
            }
        )
        return ids
    if pending is None or len(message.results) != len(pending):
        raise BoundaryError("tool results do not match the tool calls")
    for call_id, result in zip(pending, message.results, strict=True):
        out.append({"role": "tool", "tool_call_id": call_id, "content": result})
    return None


def _echo(call_id: str, call: ToolRequest) -> dict[str, Any]:
    arguments = "{}"
    if isinstance(call.args, Mapping):
        arguments = json.dumps(dict(call.args), sort_keys=True, ensure_ascii=True)
    name = call.tool if isinstance(call.tool, str) else ""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _turn(
    data: Mapping[str, Any],
    terms: ModelTerms,
    counts_byok: bool,
    model_id: str,
    output_cap: int,
) -> ModelTurn:
    usage = data.get("usage")
    usage_obj = usage if isinstance(usage, dict) else {}
    if not counts_byok and _no_byok_reason(usage_obj) is not None:
        raise ByokRefusedError(
            "refusing the review: this OpenRouter key does not count BYOK "
            f"spend against its credit limit, and {_no_byok_reason(usage_obj)}"
        )
    cost = _cost(usage_obj, terms)
    served = data.get("model")
    if not isinstance(served, str) or not _is_configured_model(served, model_id):
        raise BoundaryError(f"OpenRouter served {served!r}, not {model_id}")
    choice = _choice(data)
    finish = choice.get("finish_reason")
    _remember(data, usage_obj, served, finish)
    if finish == "length":
        raise LimitRefused(hit("max_output_tokens", output_cap, "finish_reason=length"))
    message = choice.get("message")
    if not isinstance(message, dict):
        raise BoundaryError("model response has no message")
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        if finish not in ("tool_calls", "stop"):
            raise BoundaryError(
                f"model tool calls did not finish (finish_reason={finish})"
            )
        return ToolCalls(tuple(_one_call(call) for call in calls), cost)
    if finish != "stop":
        raise BoundaryError(f"model turn did not finish (finish_reason={finish})")
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise BoundaryError(f"model returned no text (finish_reason={finish})")
    return FinalReply(text, cost)


def _remember(
    data: Mapping[str, Any], usage: Mapping[str, Any], served: object, finish: object
) -> None:
    """Stash token counts before a length stop raises, so the span still
    records them. A scripted model never calls this."""
    details = usage.get("completion_tokens_details")
    prompt_details = usage.get("prompt_tokens_details")
    finish_reason = finish if isinstance(finish, str) else None
    provider, endpoint = _served_host(data.get("provider"))
    note_call(
        CallFacts(
            model=served if isinstance(served, str) else "",
            prompt_tokens=_tokens(usage, "prompt_tokens"),
            completion_tokens=_tokens(usage, "completion_tokens"),
            reasoning_tokens=(
                _tokens(details, "reasoning_tokens")
                if isinstance(details, dict)
                else None
            ),
            finish_reason=finish_reason,
            limit_stop="output-token limit" if finish_reason == "length" else None,
            cache_read_tokens=(
                _tokens(prompt_details, "cached_tokens")
                if isinstance(prompt_details, dict)
                else None
            ),
            cache_write_tokens=(
                _tokens(prompt_details, "cache_write_tokens")
                if isinstance(prompt_details, dict)
                else None
            ),
            provider=provider,
            provider_endpoint=endpoint,
        )
    )


def _served_host(raw: object) -> tuple[str, str]:
    """The provider that served the call, and a more specific endpoint
    when the response names one. Both are untrusted text."""
    if isinstance(raw, str):
        return raw, ""
    if not isinstance(raw, dict):
        return "", ""
    return _text(raw, ("name", "slug", "id")), _text(raw, ("endpoint", "host"))


def _text(raw: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str):
            return value
    return ""


def _choice(data: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise BoundaryError("model response has no choice")
    return choices[0]


def _cost(usage: Mapping[str, Any], terms: ModelTerms) -> Decimal:
    actual, _summary = _actual_cost(usage, terms)
    return actual if actual is not None else UNPRICED


def _one_call(raw: Any) -> ToolRequest:
    """A call the bridge can refuse. A shape that is not one function call
    with a JSON-object argument string comes back with arguments the bridge
    rejects, so it is never executed."""
    if not isinstance(raw, dict):
        return ToolRequest("", ())
    if (
        raw.get("type") != "function"
        or not isinstance(raw.get("id"), str)
        or not raw.get("id")
    ):
        return ToolRequest("", ())
    function = raw.get("function")
    if not isinstance(function, dict):
        return ToolRequest("", ())
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return ToolRequest("", ())
    return ToolRequest(name, _strict_args(function.get("arguments")))


def _strict_args(raw: Any) -> Any:
    if not isinstance(raw, str):
        return ()
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        _finite(value)
    except (json.JSONDecodeError, ValueError, UnicodeError, RecursionError):
        return ()
    if not isinstance(value, dict):
        return ()
    return value


def _finite(value: Any) -> None:
    """Refuse a non-finite number anywhere in the arguments."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _pairs(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in out:
            raise ValueError("duplicate or non-string key")
        out[key] = value
    return out
