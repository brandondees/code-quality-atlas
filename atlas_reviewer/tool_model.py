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
write rate uses the reservation's input rate). The output count is
priced as one token, one rate (issue #750): a reported reasoning count
is the subset of the completion count it sits in -- OpenRouter's
reasoning-tokens guide, fetched 2026-11-18, says to subtract it from
`completion_tokens` to get the visible tokens -- so the split prices the
rest at the completion rate and the reasoning tokens at the reasoning
rate, or, when the catalog lists no reasoning rate, at the completion
rate a missing rate stands for. With no reported count the whole
completion count is priced at the higher of the two rates, so a response
that omits the count still settles instead of keeping its full
reservation as spent -- the keep that held the review at its dollar
ceiling after a few calls on a large pull request. A count that claims
to sit outside the completion count is not a usable split and keeps the
reservation, the way the prompt split treats counts that sum past
`prompt_tokens`. A readable cost is used as reported, including when the
reasoning-token count is missing. A cost that is still unreadable is a
non-finite `Decimal`, which the tracker keeps at the worst case, as are
an unreadable upstream charge, a BYOK call with no upstream charge, and
a turn with neither a readable cost nor usable token counts. This module
does not touch that tracker's rules, and it does not reserve on the
one-shot `ReviewBudget` (that budget's ceiling is the one-shot 3 calls
and $3).

When the loop hands the adapter a shared prefix (D65), the request opens
with it: the prefix's system text, then one user message whose first
part is the fenced whole diff and carries the explicit `cache_control`
breakpoint where the route takes one, then the lens skill and the first
turn as further parts of that message. A route without `cache_control`
support gets the same layout with no marker on any part.

Tool calls are parsed and handed back. The loop runs them through the
bridge, which rejects an unknown tool or bad arguments before anything
executes and returns that refusal, nonce-fenced, as the next tool
result. This module does not execute a tool and sends one request per
turn: a read timeout raises `TransportTimeoutError`, and the loop owns
the retries -- the timed-out request's one retry, and a failed call's
retries (D49) -- each priced and reserved again as its own call against
the shared budget.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any

from atlas_reviewer.attestation import body_markers
from atlas_reviewer.budget import (
    InputTokenMeter,
    TokenBoundError,
    check_tokens,
    input_token_bound,
    worst_case_usd,
)
from atlas_reviewer.cache_stats import CacheLedger, CacheSession
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
    ToolResults,
    ToolSchema,
    TurnRequest,
    UserText,
    default_reasoning_tokens,
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
    key_refusal_or_boundary,
    optional_parameters,
    provider_preferences,
    sends_cache_control,
)
from atlas_reviewer.ports import (
    BoundaryError,
    ByokRefusedError,
    ResponseTooLargeError,
    TransportError,
    TransportTimeoutError,
)
from atlas_reviewer.pricing import ModelTerms

# Not a price. `Spend.settle` keeps the reservation when the cost is not
# a finite Decimal greater than or equal to zero.
UNPRICED = Decimal("Infinity")


def _observed(exc: TokenBoundError, note: str) -> str:
    """The refusal's observed value, with the bound's basis on the input
    cap, where the bound is the meter's estimate rather than a model
    response. The refusal travels to the draft and the ledger, so the
    basis is what an operator reads there. `exc.limit` is the
    `check_tokens` name ("max_input_tokens" for the meter's bound); the
    adapter may relabel the refusal to "max_prompt_tokens" afterwards, so
    this function reads `exc.limit` and both names count as the input
    cap."""
    if exc.limit not in ("max_input_tokens", "max_prompt_tokens"):
        return str(exc.observed)
    return f"{exc.observed} (bound from {note})"


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
        self._meter = InputTokenMeter()
        self._bound_note = ""
        self._last_system: str | None = None
        self._cache = CacheLedger()
        self._session_system: str | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    def routing(self) -> tuple[bool, bool] | None:
        """ZDR required, and whether `cache_control` is on the request."""
        return self.provider.routing()

    def diagnosis(self) -> dict[str, str] | None:
        """Selected tags and the terms those rows set."""
        return self.provider.diagnosis()

    def cache_sessions(self) -> tuple[CacheSession, ...]:
        """Every prompt-cache session this adapter served, in order (issue
        #695). The run summary renders them; a dry run's scripted model
        records none."""
        return self._cache.sessions()

    @property
    def bound_note(self) -> str:
        """How the last worst-case input bound was computed: from the last
        response's reported usage plus an estimate for the new messages, or
        from bytes when there was no usable report. The trace records it."""
        return self._bound_note

    def prefix_room_tokens(self) -> int:
        """The model's resolved per-call input cap: the room the loop
        budgets the shared diff prefix against (D65), a share of which it
        leaves for the lens's work. Loading the endpoint terms here is the
        same read `worst_case_usd` makes on the first turn, and it is
        cached on the provider."""
        terms, _counts_byok, _selected = self._ready()
        bounds = resolve_per_call(self.per_call, terms)
        return bounds.max_input_tokens

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        terms, counts_byok, selected = self._ready()
        # The loop prices the turn and then places it. The endpoint
        # snapshot is loaded once for this provider and reused for later
        # turns in the review.
        self._ready_for_turn = (terms, counts_byok, selected)
        bounds = _bounds(self.per_call, terms, request)
        payload = _payload(self.provider, request, terms, bounds, selected)
        if request.system != self._last_system:
            # A different system prompt is a different conversation (a
            # retry attempt names the previous refusal; a continuation a
            # new scope), so the last reported baseline prices content
            # that is no longer there: reset to the byte bound.
            self._meter.reset()
        # The meter needs what the messages added since the last reported
        # response weigh: the whole payload serialized, and the same
        # serialization cut back to the messages that response already
        # priced. `_payload` is deterministic, so the difference is exactly
        # the new messages' bytes.
        prefix = replace(
            request, messages=request.messages[: self._meter.sent_messages]
        )
        bound, self._bound_note = self._meter.bound(
            len(json.dumps(payload)),
            len(json.dumps(_payload(self.provider, prefix, terms, bounds, selected))),
            len(request.messages),
        )
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
                hit(
                    limit,
                    exc.configured,
                    _observed(exc, self._bound_note),
                    bound_by=bound_by,
                )
            ) from exc
        return worst_case_usd(bound, terms, bounds)

    @property
    def timeout_s(self) -> float:
        """The per-request timeout this adapter sends with, for the loop's
        retry gate (review M2): one more timeout must fit the clocks."""
        return self.provider._timeout_s

    def output_tokens_within(self, request: TurnRequest, budget_usd: Decimal) -> int:
        """An output cap, up to the resolved one, whose worst case for this
        request stays within `budget_usd` -- safety first; the cap is the
        largest within the fit's own whole-payload arithmetic, not
        globally: the worst case is not monotonic in the cap across the
        reasoning-hint halving regime (`default_reasoning_tokens` caps the
        hint at `REASONING_HINT_CAP`), and the adapter's metered bound can
        realize a token more headroom than this whole-payload bound, so
        the realized maximum may sit one token higher. Below 1 when the
        input alone does not fit. The input bound is taken with the
        resolved cap in the payload, and a smaller cap is never more
        bytes, so the worst case of the returned cap is within the budget
        at these prices. The rate is the per-token worst case
        `budget.worst_case_usd` prices: the higher of the completion and
        reasoning rates, one rate per token, not their sum (issue #750)."""
        terms, _, selected = self._ready()
        uncapped = replace(request, max_output_tokens=None)
        bounds = _bounds(self.per_call, terms, uncapped)
        payload = _payload(self.provider, uncapped, terms, bounds, selected)
        fixed = input_token_bound(json.dumps(payload)) * terms.input_rate
        left = budget_usd - fixed - terms.request_fee
        # The rate is positive by parse: `parse_model_terms` refuses a zero
        # completion rate (`PricingUnknownError`), so the higher of the two
        # rates is positive -- no zero-division and no free-output branch
        # to reach here.
        rate = max(terms.completion_rate, terms.reasoning_rate)
        return min(bounds.max_output_tokens, math.floor(left / rate))

    def turn(self, request: TurnRequest) -> ModelTurn:
        """One request, no retry. A read timeout raises
        `TransportTimeoutError`, and the loop owns the one retry: it
        reserves the retry as its own call against the shared budget and
        counts it, which a retry inside the adapter could not do. Any
        other transport failure, and every failure after a response
        arrived, is one request, no retry. The loop counts the call and
        settles the cost."""
        cached = self._ready_for_turn
        self._ready_for_turn = None
        terms, counts_byok, selected = self._ready() if cached is None else cached
        bounds = _bounds(self.per_call, terms, request)
        payload = _payload(self.provider, request, terms, bounds, selected)
        url = f"{self.provider._api_url}/chat/completions"
        body = json.dumps(payload).encode()
        resp = self._send(
            url,
            self.provider._headers(authed=True, json_body=True),
            body,
            self.provider._timeout_s,
        )
        if resp.status != 200:
            raise key_refusal_or_boundary(
                resp.status,
                f"OpenRouter HTTP {resp.status} for {safe_url(url)}",
                body=resp.body,
                byok=self.provider.byok_source,
            )
        try:
            data = _json_object(resp.body, "OpenRouter chat completion", BoundaryError)
        except BoundaryError as exc:
            if not counts_byok:
                raise ByokRefusedError(
                    "refusing the review: this OpenRouter key does not count "
                    "BYOK spend against its credit limit, and the response "
                    "could not be parsed, so is_byok could not be checked"
                ) from None
            # The response arrived; nothing in it priced. The settle keeps
            # the reservation (D43), the served call's own rule (D92's fix
            # round).
            exc.reported_cost = UNPRICED
            raise
        usage = data.get("usage")
        usage_obj = usage if isinstance(usage, dict) else {}
        # The reported prompt tokens are the meter's next baseline, taken
        # before any later check raises, so a refused turn still leaves the
        # data behind for the retry attempt. The system prompt of that
        # request is what the baseline priced.
        self._meter.observe(_tokens(usage_obj, "prompt_tokens"), len(request.messages))
        self._last_system = request.system
        # The cache diagnostic rides the same usage (issue #695). A changed
        # system prompt is a new conversation, so the session closes there;
        # a retried or nudged turn keeps its session.
        if request.system != self._session_system:
            self._cache.start_session(_session_label(request.system))
            self._session_system = request.system
        prompt_details = usage_obj.get("prompt_tokens_details")
        self._cache.observe(
            _tokens(usage_obj, "prompt_tokens"),
            _tokens(prompt_details, "cached_tokens")
            if isinstance(prompt_details, dict)
            else None,
            _tokens(prompt_details, "cache_write_tokens")
            if isinstance(prompt_details, dict)
            else None,
        )
        return _turn(
            data,
            terms,
            counts_byok,
            self.provider.model_id,
            bounds.max_output_tokens,
            bounds.reasoning_max_tokens,
        )

    def _send(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_s: float
    ) -> Any:
        """The request, once. A timeout raises `TransportTimeoutError` for
        the loop's retry; a failure before any response arrived is a
        `TransportError`; a response that arrived but was too large is a
        model-level error, not a transport one (review Minor 2)."""
        try:
            return self.provider._transport.request(
                "POST", url, headers, body, timeout_s
            )
        except TransportTimeoutError:
            raise
        except ResponseTooLargeError as exc:
            # The response arrived -- the provider served it and may have
            # billed it -- so the converted error is served-but-unpriced:
            # the settle keeps the reservation (D43), it does not release
            # at $0 (D92's fix round 3).
            raise _priced(
                BoundaryError(f"OpenRouter response too large: {exc}"), UNPRICED
            ) from exc
        except BoundaryError as exc:
            raise TransportError(f"OpenRouter transport error: {exc}") from exc

    def _ready(self) -> tuple[ModelTerms, bool, SelectedEndpoints]:
        if self.provider._key_status is None:
            self.provider.preflight()
        status = self.provider._key_status
        if status is None:
            raise BoundaryError("refusing inference: key preflight has not passed")
        try:
            terms, selected = self.provider.load_terms()
        except BoundaryError as exc:
            # The one-shot path records this refusal in `complete`; the
            # adapter reaches `load_terms` directly (review round 1 of
            # PR #687, Minor 3), so it records it here instead: why no lens
            # call could be made. One entry per failed read, like the
            # budget's own refusals.
            self.provider.budget.refusals.append(str(exc))
            raise
        return terms, status.counts_byok, selected

    def remaining_credit_usd(self) -> Decimal | None:
        """The key's remaining credit as the preflight read it (D92), or
        None when this adapter names no usable figure. The preflight ran
        at wiring time and again on this adapter's first read, so the
        figure is the key's own `/key` answer -- one read, never after
        inference -- and it can lag a completion by about 90 seconds."""
        try:
            self._ready()
        except BoundaryError:
            # A credit figure this adapter cannot read refuses nothing:
            # the per-call reservations and the refusals govern, and the
            # calls' own classification is the loud failure.
            return None
        status = self.provider._key_status
        return None if status is None else status.limit_remaining

    def largest_call_reservation(self) -> Decimal | None:
        """The worst case the review's largest allowed call reserves (D92):
        the per-call input cap priced at the endpoint's rates, output cap
        included. This is the largest single reservation the plan holds
        against the key before any settle, and so the smallest credit the
        review must be able to fund to start at all. None when the
        endpoint's terms cannot be read or the per-call limits do not
        resolve against them -- the credit check then accepts, and the
        lens loop reports the limit the same way the turn path does
        (D92's fix round 4)."""
        try:
            terms, _, _selected = self._ready()
            bounds = resolve_per_call(self.per_call, terms)
        except BoundaryError:
            return None
        return worst_case_usd(bounds.max_input_tokens, terms, bounds)


def _bounds(per_call: Limits, terms: ModelTerms, request: TurnRequest) -> ResolvedCall:
    """The resolved bounds, with the output cap tightened to the request's
    own cap when it names a smaller one. A reasoning hint that no longer
    fits that cap becomes half of it, so the reply still has the other half."""
    bounds = resolve_per_call(per_call, terms)
    cap = request.max_output_tokens
    if cap is None or cap >= bounds.max_output_tokens:
        return bounds
    hint = bounds.reasoning_max_tokens
    if hint >= cap:
        hint = default_reasoning_tokens(cap)
    return ResolvedCall(bounds.max_input_tokens, cap, hint)


def _payload(
    provider: OpenRouterProvider,
    request: TurnRequest,
    terms: ModelTerms,
    limits: ResolvedCall,
    selected: SelectedEndpoints,
) -> dict[str, Any]:
    if not request.tools and _carries_tool_work(request.messages):
        raise BoundaryError(
            "a request carrying tool calls or results cannot go out with "
            "an empty tools array: the pinned routes are documented to "
            "reject tool history next to no toolConfig (Bedrock "
            "Converse's toolConfig rule), so the adapter refuses the "
            "shape instead of failing the call mid-review"
        )
    caching = sends_cache_control(provider.model_id, selected.supported)
    payload: dict[str, Any] = {
        "model": provider.model_id,
        "messages": _messages(request, caching),
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


def _carries_tool_work(messages: tuple[Message, ...]) -> bool:
    """Whether the history holds assistant tool calls or tool results.
    The adapter's shape invariant: a request with them and an empty tools
    array is one the pinned routes reject -- Bedrock Converse requires a
    `toolConfig` when `toolUse` and `toolResult` blocks are present -- so
    the only tool-less request that may go out is one whose history has
    none, like the re-assessment call's single user turn."""
    return any(
        isinstance(message, AssistantCalls | ToolResults) for message in messages
    )


def _messages(request: TurnRequest, caching: bool) -> list[dict[str, Any]]:
    """History in OpenAI chat shape. Tool-call ids are assigned here, and
    the following tool results must line up with them. Result text is sent
    unchanged, fence included.

    With a shared prefix, the request opens with the prefix's system text,
    then one user message whose first part is the fenced whole diff and
    carries the explicit `cache_control` breakpoint when the route takes
    one, then the lens skill and the first turn as further parts of that
    same message, so the shared block is a byte-identical prefix across
    the review's lenses and across a lens's retry (issue #696, D65). A
    route without `cache_control` support gets the same layout with no
    marker on any part."""
    if request.prefix is not None:
        return _prefixed_messages(request, caching)
    out: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
    pending: tuple[str, ...] | None = None
    for message in request.messages:
        pending = _one_message(out, message, pending)
    if pending is not None:
        raise BoundaryError("a tool result is missing")
    return out


def _prefixed_messages(request: TurnRequest, caching: bool) -> list[dict[str, Any]]:
    prefix = request.prefix
    assert prefix is not None
    parts = [_diff_part(prefix.diff, caching)]
    head = request.messages[0] if request.messages else None
    parts.append({"type": "text", "text": request.system})
    rest = request.messages
    if isinstance(head, UserText):
        parts.append({"type": "text", "text": head.text})
        rest = request.messages[1:]
    out: list[dict[str, Any]] = [
        {"role": "system", "content": prefix.system},
        {"role": "user", "content": parts},
    ]
    pending: tuple[str, ...] | None = None
    for message in rest:
        pending = _one_message(out, message, pending)
    if pending is not None:
        raise BoundaryError("a tool result is missing")
    return out


def _diff_part(diff: str, caching: bool) -> dict[str, Any]:
    """The fenced diff as the prefix's first content part. The breakpoint
    sits on this part, so everything before it -- the tools, the shared
    system text and the diff itself -- is the cached prefix."""
    part: dict[str, Any] = {"type": "text", "text": diff}
    if caching:
        part["cache_control"] = {"type": "ephemeral"}
    return part


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
    reasoning_hint: int | None = None,
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
        raise _priced(
            BoundaryError(f"OpenRouter served {served!r}, not {model_id}"), cost
        )
    try:
        choice = _choice(data)
    except BoundaryError as exc:
        # A 200 that priced and then named no choice is a served call:
        # the refusal carries the cost it just computed (D92's fix round
        # 2), so the settle books the bill instead of releasing it.
        raise _priced(exc, cost) from None
    finish = choice.get("finish_reason")
    _remember(
        data, usage_obj, served, finish, reasoning_hint=reasoning_hint
    )  # fmt: skip
    if finish == "length":
        raise LimitRefused(hit("max_output_tokens", output_cap, "finish_reason=length"))
    message = choice.get("message")
    if not isinstance(message, dict):
        raise _priced(BoundaryError("model response has no message"), cost)
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        if finish not in ("tool_calls", "stop"):
            raise _priced(
                BoundaryError(
                    f"model tool calls did not finish (finish_reason={finish})"
                ),
                cost,
            )
        return ToolCalls(tuple(_one_call(call) for call in calls), cost)
    if finish != "stop":
        raise _priced(
            BoundaryError(f"model turn did not finish (finish_reason={finish})"), cost
        )
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise _priced(
            BoundaryError(f"model returned no text (finish_reason={finish})"), cost
        )
    return FinalReply(text, cost)


def _priced(exc: BoundaryError, cost: Decimal) -> BoundaryError:
    """`exc` with the served response's priced cost attached (D92's fix
    round): the settle at the raise site books the real bill the usage
    priced instead of treating a served call as a refused one. The cost is
    `UNPRICED` when the response carried no usable usage -- the settle
    then keeps the reservation (D43), the served call's own rule."""
    exc.reported_cost = cost
    return exc


def _remember(
    data: Mapping[str, Any],
    usage: Mapping[str, Any],
    served: object,
    finish: object,
    *,
    reasoning_hint: int | None = None,
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
            reasoning_hint=reasoning_hint,
        )
    )


# Built from `body_markers` so the pattern cannot drift from the marker
# the controller actually writes. The lens name inside the marker is
# controller text (a library name), not PR-controlled.
_SESSION_LABEL = re.compile(
    re.escape(body_markers("{lens}", "{digest}")[0])
    .replace(re.escape("{lens}"), "(.+?)")
    .replace(re.escape("{digest}"), r"[0-9a-f]{64}")
)


def _session_label(system: str) -> str:
    """The lens a system prompt's body marker names, for the cache
    session's label. Empty when the prompt carries no marker."""
    match = _SESSION_LABEL.search(system)
    return match.group(1) if match else ""


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
