# SPDX-License-Identifier: MIT
"""The tenant-supplied model endpoint: the S10 BYOK client an
installation's own reviews run on (D81 §7; part A of config slice S10).

The installation supplies an OpenAI- or OpenRouter-compatible base URL,
an API key, and a model through the operator-hosted settings page (part
B); the store (`installation_store.py`) holds them; the review child
receives them through the three environment variables
`ATLAS_TENANT_MODEL_KEY` (the key -- the one credential variable the
child env allowlist gains), `ATLAS_TENANT_BASE_URL` and
`ATLAS_TENANT_MODEL` (settings). The operator's key never rides a
tenant review: the service drops `ATLAS_OPENROUTER_API_KEY` from a
tenant child's environment.

This is a separate code path from the operator-key OpenRouter handling
(D41): that handling -- `usage.is_byok`, `ByokRefusedError`, the key
credit preflight -- stays untouched, and the two never share a runtime
path. What the two paths do share is the accounting's shape: the
reservation is `budget.worst_case_usd` over the operator's price table,
and the settle is reported **token counts priced at the operator's
price table** -- never the endpoint's own cost figures. The tenant path
never reads `usage.cost` or `cost_details.upstream_inference_cost`; a
tenant-reported figure can move only the tenant's own settled total,
never a reservation or an operator-protective bound (D81's 5:13 PM CT
answers).

Pricing comes from the OpenRouter public catalog entry for the chosen
model -- the operator's price table -- read without any key. A model
with no entry there is refused with the named reason; a **zero-priced**
model is allowed (D81's 5:13 PM CT answer to Q3): its dollar bounds
accumulate nothing, so the per-review call caps and walls are what
bound it.

Every failure names itself plainly -- an auth error, a quota error, an
endpoint down, an egress refusal, an unknown price -- and the key is
never echoed. A redirect is refused by name (`egress.py` never follows
one). The endpoint's answers are untrusted model output, bounded by the
same byte cap and timeouts as every other request.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any

from atlas_reviewer.budget import (
    BudgetRefusedError,
    CallLimits,
    CallRecord,
    InputTokenMeter,
    ReviewBudget,
    TokenBoundError,
    check_tokens,
    input_token_bound,
    worst_case_usd,
)
from atlas_reviewer.cache_stats import CacheLedger
from atlas_reviewer.egress import TenantEndpointTransport
from atlas_reviewer.http import HttpResponse, UrllibTransport, safe_url
from atlas_reviewer.installation_store import TenantCredentials
from atlas_reviewer.lens_loop import (
    AgenticLimits,
    FinalReply,
    Limits,
    ModelTurn,
    ResolvedCall,
    ToolCalls,
    TurnRequest,
)
from atlas_reviewer.limit_stop import LimitRefused, hit
from atlas_reviewer.ports import (
    KEY_AUTH_REFUSED,
    KEY_OUT_OF_CREDIT,
    BoundaryError,
    Json,
    KeyRefusedError,
    ResponseTooLargeError,
    TransportError,
    TransportTimeoutError,
)
from atlas_reviewer.pricing import (
    ModelTerms,
    PricingUnknownError,
    max_rate,
    optional_rate,
    tiers,
)
from atlas_reviewer.prompt import Prompt
from atlas_reviewer.tool_model import (
    UNPRICED,
    _bounds,
    _carries_tool_work,
    _choice,
    _messages,
    _one_call,
    _priced,
    _remember,
    _session_label,
    _tokens,
    _tool,
)

ENV_TENANT_MODEL_KEY = "ATLAS_TENANT_MODEL_KEY"
ENV_TENANT_BASE_URL = "ATLAS_TENANT_BASE_URL"
ENV_TENANT_MODEL = "ATLAS_TENANT_MODEL"
# The operator's price table is the OpenRouter public catalog; the
# read goes out without any credential.
CATALOG_API_URL = "https://openrouter.ai/api/v1"
CATALOG_TIMEOUT_S = 30.0
RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})
# 401 only (D92's fix round 3): a 403 from an arbitrary OpenAI-compatible
# endpoint can be a per-request refusal of the request or its content, not
# a key problem, so it stays a plain per-call BoundaryError and the review
# keeps going; only the authentication refusal stops the review.
AUTH_STATUSES = frozenset({401})
QUOTA_STATUSES = frozenset({402})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_RETRY_WAIT = 8.0
_PER_MILLION = Decimal(1_000_000)


def tenant_environment(env: Mapping[str, str]) -> TenantCredentials | None:
    """The tenant credentials the child environment carries, or None
    when it carries none. A partially-set set is a wiring error and
    refuses loudly: the three variables travel together, and half of
    them must never silently mean the operator path."""
    key = env.get(ENV_TENANT_MODEL_KEY, "")
    base = env.get(ENV_TENANT_BASE_URL, "")
    model = env.get(ENV_TENANT_MODEL, "")
    if not key and not base and not model:
        return None
    missing = [
        name
        for name, value in (
            (ENV_TENANT_MODEL_KEY, key),
            (ENV_TENANT_BASE_URL, base),
            (ENV_TENANT_MODEL, model),
        )
        if not value
    ]
    if missing:
        raise BoundaryError(
            "refusing inference: the tenant endpoint environment is "
            "incomplete (missing " + ", ".join(missing) + ")"
        )
    return TenantCredentials(base, key, model)


def terms_from_catalog(data: Json, model_id: str) -> ModelTerms:
    """The operator's price table entry for one model, from the public
    catalog document (`GET /api/v1/model/{id}`). The same parse the
    operator path runs, with one difference the decided answer requires:
    a **zero** prompt or completion rate is a priced model here, not a
    refusal -- the dollar bounds accumulate nothing for it, so the call
    caps and walls bound it. A missing entry, a missing limit, or a
    negative rate refuses with the named reason."""
    model = data.get("data")
    if not isinstance(model, dict):
        raise PricingUnknownError("the price table has no entry for this model")
    if model.get("id") != model_id:
        raise PricingUnknownError(
            f"the price table returned model {model.get('id')!r}, not {model_id!r}"
        )
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        raise PricingUnknownError("the price table entry has no pricing object")
    priced = tiers(pricing)
    prompt = max_rate(priced, "prompt", required=True)
    completion = max_rate(priced, "completion", required=True)
    if prompt < 0 or completion < 0:
        raise PricingUnknownError("the price table entry has a negative rate")
    cache_write = max(
        max_rate(priced, "input_cache_write", required=False),
        max_rate(priced, "input_cache_write_1h", required=False),
    )
    top = model.get("top_provider")
    return ModelTerms(
        model_id=model_id,
        input_rate=max(prompt, cache_write),
        prompt_rate=prompt,
        completion_rate=completion,
        reasoning_rate=max_rate(priced, "internal_reasoning", required=False),
        request_fee=max_rate(priced, "request", required=False),
        context_length=_count(model.get("context_length"), "context_length"),
        max_completion_tokens=_count(
            top.get("max_completion_tokens") if isinstance(top, dict) else None,
            "top_provider.max_completion_tokens",
        ),
        cache_read_rate=optional_rate(priced, "input_cache_read"),
        cache_write_rate=cache_write,
    )


def _count(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PricingUnknownError(f"the price table entry's {what} is unusable")
    return value


class TenantEndpointProvider:
    """The model client for one installation's own endpoint.

    `preflight` reads the operator's price table for the chosen model
    and refuses -- before any call, with the named reason -- when the
    model has no entry there. `complete` reserves its worst case from
    the operator's caps and that table, sends an OpenAI-compatible chat
    completion to the endpoint over the egress-guarded transport, and
    settles from the reported token counts priced at the same table.
    """

    def __init__(
        self,
        transport: TenantEndpointTransport,
        credentials: TenantCredentials,
        *,
        limits: CallLimits | None = None,
        timeout_s: float = 300.0,
        sleep: Callable[[float], None] = lambda _s: None,
        catalog: Callable[[str], Json] | None = None,
    ) -> None:
        self._transport = transport
        self._credentials = credentials
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._catalog = catalog if catalog is not None else _catalog_document
        self.budget = ReviewBudget(limits or CallLimits())
        self._terms: ModelTerms | None = None
        self.name = f"tenant-endpoint:{credentials.model}"

    @property
    def model_id(self) -> str:
        return self._credentials.model

    def preflight(self) -> ModelTerms:
        """The price table for the chosen model, cached for the review.

        This is the tenant path's preflight: the operator-key preflight
        (`GET /key`, the credit ceiling) is the operator key's own
        guard and does not run here."""
        if self._terms is None:
            self._terms = terms_from_catalog(
                self._catalog(f"/model/{self._credentials.model}"),
                self._credentials.model,
            )
        return self._terms

    def usage_lines(self) -> tuple[str, ...]:
        terms = self._terms
        line = (
            f"model `{self.model_id}` via the installation's own endpoint "
            "(tenant-supplied)"
        )
        if terms is not None:
            line += (
                f"; priced at the operator's price table "
                f"(prompt ${_per_million(terms.prompt_rate)}/M, completion "
                f"${_per_million(terms.completion_rate)}/M)"
            )
        return (line, *self.budget.report())

    def complete(self, prompt: Prompt) -> str:
        if self._terms is None:
            self._refused(
                BoundaryError(
                    "refusing inference: the tenant endpoint's price table "
                    "has not been read (preflight has not passed)"
                )
            )
        terms = self._terms
        assert terms is not None
        tokens = input_token_bound(prompt.system + prompt.user)
        try:
            check_tokens(tokens, terms, self.budget.limits)
        except BudgetRefusedError as exc:
            self._refused(exc)
        worst = worst_case_usd(tokens, terms, self.budget.limits)
        return self._attempts(prompt, terms, worst)

    def _refused(self, exc: BoundaryError) -> None:
        """Record a refusal that spent nothing and was not sent."""
        self.budget.refusals.append(str(exc))
        raise exc

    def _attempts(self, prompt: Prompt, terms: ModelTerms, worst: Decimal) -> str:
        last: BoundaryError | None = None
        retry_after: str | None = None
        for attempt in range(self.budget.limits.max_calls):
            if attempt:
                self._sleep(_retry_wait(retry_after, attempt))
            try:
                record = self.budget.reserve(worst)
            except BudgetRefusedError as refusal:
                raise (last or refusal) from refusal
            result = self._send(prompt, terms, record)
            if isinstance(result, str):
                return result
            last, retry_after = result
        raise last or BoundaryError("no model call was made")

    def _send(
        self, prompt: Prompt, terms: ModelTerms, record: CallRecord
    ) -> str | tuple[BoundaryError, str | None]:
        url = f"{self._credentials.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": self._credentials.model,
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                # Always the configured output cap, the way the operator
                # path sends it: the reservation prices this cap.
                "max_tokens": self.budget.limits.max_output_tokens,
                "stream": False,
            }
        ).encode()
        try:
            resp = self._transport.request(
                "POST",
                url,
                _headers(self._credentials.key),
                body,
                self._timeout_s,
            )
        except ResponseTooLargeError as exc:
            # The body arrived and then exceeded the read cap. The
            # provider served it and may have billed it, so the
            # reservation is the bill (D43), the same rule the lens
            # adapter applies. It is not a hold.
            ReviewBudget.settle(record, f"response too large: {exc}")
            return exc, None
        except BoundaryError as exc:
            # Written and never answered: the reservation stays, and it
            # is a hold, not a bill (D58 item 5, D93).
            ReviewBudget.hold(record, f"transport error: {exc}")
            return exc, None
        return _response(resp, terms, record, self.model_id, url)


def _headers(key: str) -> dict[str, str]:
    return {
        "User-Agent": "code-quality-atlas-reviewer",
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _tenant_payload(
    request: TurnRequest, terms: ModelTerms, limits: ResolvedCall
) -> dict[str, Any]:
    """The request body an OpenAI-compatible endpoint takes: the model,
    the message history, the tools, the output cap. No OpenRouter
    routing document (`provider`, `zdr`, `max_price`) and no
    `cache_control` marker -- those are the operator-key path's policy,
    and an arbitrary compatible endpoint can reject fields it does not
    know. The empty-tools invariant is the same shape rule the operator
    adapter enforces, stated for this path."""
    if not request.tools and _carries_tool_work(request.messages):
        raise BoundaryError(
            "a request carrying tool calls or results cannot go out with "
            "an empty tools array: the adapter refuses the shape instead "
            "of failing the call mid-review"
        )
    return {
        "model": terms.model_id,
        "messages": _messages(request, caching=False),
        "tools": [_tool(tool) for tool in request.tools],
        # Always the configured output cap, even when the endpoint does
        # not list max_tokens. The reservation prices this cap.
        "max_tokens": limits.max_output_tokens,
        "stream": False,
    }


class TenantLensModel:
    """The agentic `LensModel` port, backed by the tenant endpoint
    client.

    The turn shape, the meter, the cache bookkeeping and the per-call
    bounds are the operator adapter's (D68, D65, #695); the code path is
    not: no OpenRouter routing document, no ZDR list, no key-credit
    preflight, no `usage.cost` read, no `ByokRefusedError` -- the
    settlement prices reported token counts at the operator's price
    table, so a tenant-reported figure can move only the tenant's own
    settled total (D81's 5:13 PM CT answers). A zero-priced model
    settles at $0: its dollar bounds accumulate nothing, and the call
    caps and walls bound it."""

    def __init__(
        self, provider: TenantEndpointProvider, per_call: Limits | None = None
    ) -> None:
        self.provider = provider
        self.per_call = AgenticLimits().resolve() if per_call is None else per_call
        self._ready_for_turn: tuple[ModelTerms, ResolvedCall] | None = None
        self._meter = InputTokenMeter()
        self._bound_note = ""
        self._last_system: str | None = None
        self._cache = CacheLedger()
        self._session_system: str | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def bound_note(self) -> str:
        """How the last worst-case input bound was computed (the trace
        records it), the same record the operator adapter keeps."""
        return self._bound_note

    def cache_sessions(self) -> tuple[Any, ...]:
        """Every prompt-cache session this adapter served, in order. A
        tenant endpoint that does not report cache counts records none."""
        return self._cache.sessions()

    def _terms(self) -> ModelTerms:
        if self.provider._terms is None:
            self.provider.preflight()
        terms = self.provider._terms
        assert terms is not None
        return terms

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        terms = self._terms()
        self._ready_for_turn = (terms, _bounds(self.per_call, terms, request))
        bounds = self._ready_for_turn[1]
        payload = _tenant_payload(request, terms, bounds)
        if request.system != self._last_system:
            # A different system prompt is a different conversation (a
            # retry attempt names the previous refusal; a continuation a
            # new scope), so the last reported baseline prices content
            # that is no longer there: reset to the byte bound.
            self._meter.reset()
        prefix = replace(
            request, messages=request.messages[: self._meter.sent_messages]
        )
        bound, self._bound_note = self._meter.bound(
            len(json.dumps(payload)),
            len(json.dumps(_tenant_payload(prefix, terms, bounds))),
            len(request.messages),
        )
        try:
            check_tokens(bound, terms, bounds)
        except TokenBoundError as exc:
            raise LimitRefused(
                hit(
                    exc.limit,
                    exc.configured,
                    exc.observed,
                )
            ) from exc
        return worst_case_usd(bound, terms, bounds)

    def output_tokens_within(self, request: TurnRequest, budget_usd: Decimal) -> int:
        """An output cap, up to the resolved one, whose worst case for
        this request stays within `budget_usd` -- the same arithmetic the
        operator adapter runs. On a zero-priced model the per-token rate
        is $0, so every cap fits and the resolved cap stands: the call
        caps and walls are what bound it."""
        terms = self._terms()
        uncapped = replace(request, max_output_tokens=None)
        bounds = _bounds(self.per_call, terms, uncapped)
        payload = _tenant_payload(uncapped, terms, bounds)
        fixed = input_token_bound(json.dumps(payload)) * terms.input_rate
        left = budget_usd - fixed - terms.request_fee
        rate = max(terms.completion_rate, terms.reasoning_rate)
        if rate <= 0:
            return bounds.max_output_tokens
        return min(bounds.max_output_tokens, math.floor(left / rate))

    def turn(self, request: TurnRequest) -> ModelTurn:
        """One request, no retry -- the loop owns the retries, exactly as
        on the operator path. The failure texts are this path's fixed
        phrases: auth error, quota error, endpoint down, egress refusal.
        The key is never in any of them."""
        cached = self._ready_for_turn
        self._ready_for_turn = None
        if cached is None:
            terms = self._terms()
            bounds = _bounds(self.per_call, terms, request)
        else:
            terms, bounds = cached
        payload = _tenant_payload(request, terms, bounds)
        url = f"{self.provider._credentials.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(payload).encode()
        resp = self._send(url, body)
        _refuse_status(resp, self.provider.model_id)
        self._observe(resp, request)
        return _tenant_turn(resp.body, terms, self.provider.model_id, bounds)

    def _send(self, url: str, body: bytes) -> HttpResponse:
        """The request, once. A timeout raises `TransportTimeoutError`
        for the loop's retry; any other failure before a response
        arrived is a `TransportError`; an arrived-but-too-large response
        is a model-level error, not a transport one."""
        try:
            return self.provider._transport.request(
                "POST",
                url,
                _headers(self.provider._credentials.key),
                body,
                self.provider._timeout_s,
            )
        except TransportTimeoutError:
            raise
        except ResponseTooLargeError as exc:
            # The response arrived and may have been billed: served but
            # unpriced, so the settle keeps the reservation (D43, D92's
            # fix round 3).
            raise _priced(
                BoundaryError(f"the tenant endpoint's response: {exc}"), UNPRICED
            ) from exc
        except BoundaryError as exc:
            raise TransportError(f"the tenant endpoint transport error: {exc}") from exc

    def _observe(self, resp: HttpResponse, request: TurnRequest) -> None:
        """The reported usage recorded as the meter's next baseline and
        the cache diagnostics, taken before any later check raises -- the
        same bookkeeping the operator adapter runs (issue #695). A
        non-200 response has no usage to observe; the status refusal ran
        first."""
        if resp.status != 200:
            return
        try:
            data = _json_object(resp.body)
        except BoundaryError:
            return
        usage = data.get("usage")
        usage_obj = usage if isinstance(usage, dict) else {}
        self._meter.observe(_tokens(usage_obj, "prompt_tokens"), len(request.messages))
        self._last_system = request.system
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


def _refuse_status(resp: HttpResponse, model_id: str) -> None:
    """A non-200 response is the named failure it is: a redirect is
    refused (the transport never followed it), an auth status names the
    key refusal, a quota status names the quota, and anything else names
    the endpoint's failure. The key is never in any message."""
    if resp.status == 200:
        return
    if resp.status in REDIRECT_STATUSES:
        raise BoundaryError(
            "the tenant endpoint redirected "
            f"(HTTP {resp.status}); redirects are refused"
        )
    if resp.status in AUTH_STATUSES:
        raise KeyRefusedError(
            f"the tenant endpoint refused the key: auth error (HTTP {resp.status})",
            review_error=KEY_AUTH_REFUSED,
        )
    if resp.status in QUOTA_STATUSES:
        raise KeyRefusedError(
            f"the tenant endpoint refused the call: quota error (HTTP {resp.status})",
            review_error=KEY_OUT_OF_CREDIT,
        )
    raise BoundaryError(
        f"the tenant endpoint failed: HTTP {resp.status} for model {model_id}"
    )


def _tenant_turn(
    raw: bytes, terms: ModelTerms, model_id: str, bounds: ResolvedCall
) -> ModelTurn:
    """One 200 response as a turn. The settlement reads only token
    counts -- never `usage.cost` or `cost_details.upstream_inference_cost`
    (D81 §4) -- priced at the operator's price table; a missing or
    unusable split keeps the call's full reservation as spent, through
    `UNPRICED`, the way the operator path keeps it."""
    try:
        data = _json_object(raw)
    except BoundaryError:
        # The 200 arrived -- the provider served it and may have billed it
        # -- so the error is served-but-unpriced: the settle keeps the
        # reservation (D43), it does not release at $0 (D92's fix round 3).
        raise _priced(
            BoundaryError("the tenant endpoint returned a non-JSON response"),
            UNPRICED,
        ) from None
    usage = data.get("usage")
    usage_obj = usage if isinstance(usage, dict) else {}
    actual, _summary = _tenant_actual_cost(usage_obj, terms)
    cost = actual if actual is not None else UNPRICED
    served = data.get("model")
    if (
        isinstance(served, str)
        and served
        and served != model_id
        and not _is_dated_revision(served, model_id)
    ):
        raise _priced(
            BoundaryError(f"the tenant endpoint served {served!r}, not {model_id!r}"),
            cost,
        )
    try:
        choice = _choice(data)
    except BoundaryError as exc:
        # The same priced-refusal rule as the operator path (D92's fix
        # round 2): the response was served and priced at the operator's
        # table, so the refusal carries that cost.
        raise _priced(exc, cost) from None
    finish = choice.get("finish_reason")
    _remember(data, usage_obj, served, finish)
    if finish == "length":
        raise LimitRefused(
            hit("max_output_tokens", bounds.max_output_tokens, "finish_reason=length")
        )
    message = choice.get("message")
    if not isinstance(message, dict):
        raise _priced(
            BoundaryError("the tenant endpoint's response has no message"), cost
        )
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        if finish not in ("tool_calls", "stop"):
            raise _priced(
                BoundaryError(
                    f"the tenant endpoint's tool calls did not finish "
                    f"(finish_reason={finish})"
                ),
                cost,
            )
        return ToolCalls(tuple(_one_call(call) for call in calls), cost)
    if finish != "stop":
        raise _priced(
            BoundaryError(
                f"the tenant endpoint's turn did not finish (finish_reason={finish})"
            ),
            cost,
        )
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise _priced(
            BoundaryError(
                f"the tenant endpoint returned no review text (finish_reason={finish})"
            ),
            cost,
        )
    return FinalReply(text, cost)


def _response(
    resp: HttpResponse,
    terms: ModelTerms,
    record: CallRecord,
    model_id: str,
    url: str,
) -> str | tuple[BoundaryError, str | None]:
    """One response: settle it, refuse it by name, or return its text.

    The settlement reads only token counts -- never `usage.cost` or
    `cost_details.upstream_inference_cost`, whose values on the tenant
    path are the endpoint's own account of its own charges and are not
    the operator's accounting (D81 §4)."""
    if resp.status in REDIRECT_STATUSES:
        ReviewBudget.release(record, f"HTTP {resp.status} (redirect refused)")
        raise BoundaryError(
            f"the tenant endpoint redirected (HTTP {resp.status} for "
            f"{safe_url(url)}); redirects are refused"
        )
    if resp.status in AUTH_STATUSES:
        ReviewBudget.release(record, f"HTTP {resp.status} (auth error)")
        raise KeyRefusedError(
            f"the tenant endpoint refused the key: auth error (HTTP {resp.status} "
            f"for {safe_url(url)})",
            review_error=KEY_AUTH_REFUSED,
        )
    if resp.status in QUOTA_STATUSES:
        ReviewBudget.release(record, f"HTTP {resp.status} (quota error)")
        raise KeyRefusedError(
            f"the tenant endpoint refused the call: quota error (HTTP {resp.status} "
            f"for {safe_url(url)})",
            review_error=KEY_OUT_OF_CREDIT,
        )
    if resp.status in RETRYABLE:
        ReviewBudget.release(record, f"HTTP {resp.status} (retryable)")
        return (
            BoundaryError(f"the tenant endpoint returned HTTP {resp.status}"),
            resp.header("Retry-After"),
        )
    if resp.status != 200:
        ReviewBudget.release(record, f"HTTP {resp.status}")
        raise BoundaryError(
            f"the tenant endpoint failed: HTTP {resp.status} for {safe_url(url)}"
        )
    try:
        data = _json_object(resp.body)
    except BoundaryError:
        ReviewBudget.settle(record, "unparseable response")
        raise
    usage = data.get("usage")
    usage_obj = usage if isinstance(usage, dict) else {}
    actual, summary = _tenant_actual_cost(usage_obj, terms)
    served = data.get("model")
    if (
        isinstance(served, str)
        and served
        and served != model_id
        and not _is_dated_revision(served, model_id)
    ):
        ReviewBudget.settle(record, f"rejected: served by {served!r}", actual, summary)
        raise BoundaryError(f"the tenant endpoint served {served!r}, not {model_id!r}")
    text, finish = _message(data)
    if not text.strip():
        ReviewBudget.settle(
            record, f"empty review (finish_reason={finish})", actual, summary
        )
        raise BoundaryError(
            f"the tenant endpoint returned no review text (finish_reason={finish})"
        )
    if finish != "stop":
        ReviewBudget.settle(
            record, f"incomplete review (finish_reason={finish})", actual, summary
        )
        if finish == "length":
            raise BoundaryError("the model review stopped at the output-token limit")
        raise BoundaryError(f"the model review did not finish (finish_reason={finish})")
    ReviewBudget.settle(record, f"ok (finish_reason={finish})", actual, summary)
    return text


def _is_dated_revision(served: str, model_id: str) -> bool:
    return re.fullmatch(re.escape(model_id) + r"-\d{8}", served) is not None


def _message(data: Json) -> tuple[str, str]:
    choices = data.get("choices")
    first: Any = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    finish = first.get("finish_reason") if isinstance(first, dict) else None
    return (content if isinstance(content, str) else ""), str(finish)


def _json_object(raw: bytes) -> Json:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise BoundaryError(
            "the tenant endpoint returned a non-JSON response"
        ) from None
    if not isinstance(data, dict):
        raise BoundaryError("the tenant endpoint returned a non-object response")
    return data


def _tenant_actual_cost(usage: Json, terms: ModelTerms) -> tuple[Decimal | None, str]:
    """The settle from reported token counts priced at the operator's
    price table.

    The endpoint's own cost figures are not read: `usage.cost` and
    `cost_details.upstream_inference_cost` are the endpoint's account of
    its own charges, and the tenant path's one accounting is token
    counts times the operator's table (D81 §4). Counts that are
    missing, unreadable, or that do not split cleanly keep the call's
    full reservation -- a settle never prices below what the call may
    have cost. A zero-priced model settles at $0 with reported counts:
    its dollar bounds accumulate nothing, and the call caps and walls
    are its bound."""
    prompt_t = _tokens(usage, "prompt_tokens")
    completion_t = _tokens(usage, "completion_tokens")
    details = usage.get("completion_tokens_details")
    reasoning_t = (
        _tokens(details, "reasoning_tokens") if isinstance(details, dict) else None
    )
    summary = f"tokens in={prompt_t} out={completion_t} reasoning={reasoning_t}"
    if prompt_t is None or completion_t is None:
        return None, summary
    prompt_cost = _prompt_cost(usage, terms, prompt_t)
    if prompt_cost is None:
        return None, summary
    output_cost = _output_cost(completion_t, reasoning_t, terms)
    if output_cost is None:
        return None, summary
    cost = prompt_cost + output_cost + terms.request_fee
    note = "priced at the operator's price table"
    return cost, f"{summary} ({note})"


def _prompt_cost(usage: Json, terms: ModelTerms, prompt_t: int) -> Decimal | None:
    """The prompt side of the settle. With no reported cache split,
    every prompt token is charged at `input_rate`, which already takes
    the higher of the prompt rate and any cache-write rate. Reported
    cache counts are subsets of `prompt_tokens`; counts that sum past
    it are not a usable split and keep the reservation."""
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        return prompt_t * terms.input_rate
    cached = _tokens(details, "cached_tokens")
    written = _tokens(details, "cache_write_tokens")
    if cached is None and written is None:
        return prompt_t * terms.input_rate
    cached_n = 0 if cached is None else cached
    written_n = 0 if written is None else written
    if cached_n + written_n > prompt_t:
        return None
    read_rate = (
        terms.prompt_rate if terms.cache_read_rate is None else terms.cache_read_rate
    )
    write_rate = (
        terms.input_rate if terms.cache_write_rate is None else terms.cache_write_rate
    )
    fresh = prompt_t - cached_n - written_n
    return cached_n * read_rate + written_n * write_rate + fresh * terms.prompt_rate


def _output_cost(
    completion_t: int, reasoning_t: int | None, terms: ModelTerms
) -> Decimal | None:
    """The output side of the settle. A reported reasoning count is a
    subset of the completion count; a count larger than the count it
    sits in is not a usable split and keeps the reservation. With no
    reported count the whole completion count is priced at the higher
    of the completion and reasoning rates -- the same bound
    `budget.worst_case_usd` reserves against."""
    reasoning_rate = (
        terms.reasoning_rate if terms.reasoning_rate > 0 else terms.completion_rate
    )
    if reasoning_t is None:
        return completion_t * max(terms.completion_rate, reasoning_rate)
    if reasoning_t > completion_t:
        return None
    return (completion_t - reasoning_t) * terms.completion_rate + (
        reasoning_t * reasoning_rate
    )


def _retry_wait(header: str | None, attempt: int) -> float:
    backoff = 2.0**attempt
    if header is None:
        return backoff
    try:
        seconds = float(header.strip())
    except ValueError:
        return backoff
    if seconds < 0 or not math.isfinite(seconds):
        return backoff
    return min(seconds, _MAX_RETRY_WAIT)


def _per_million(rate: Decimal) -> str:
    return f"{rate * _PER_MILLION:.2f}"


def _catalog_document(path: str) -> Json:
    """The operator's price table document: one unauthenticated GET to
    the OpenRouter public catalog. A transport failure or a non-200 is
    the unknown-price refusal it is."""
    transport = UrllibTransport()
    resp = transport.request(
        "GET",
        f"{CATALOG_API_URL}{path}",
        {"User-Agent": "code-quality-atlas-reviewer", "Accept": "application/json"},
        None,
        CATALOG_TIMEOUT_S,
    )
    if resp.status != 200:
        raise PricingUnknownError(
            f"the operator's price table has no readable entry for this model "
            f"(HTTP {resp.status})"
        )
    try:
        data = json.loads(resp.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PricingUnknownError(
            "the operator's price table returned a non-JSON response"
        ) from None
    if not isinstance(data, dict):
        raise PricingUnknownError(
            "the operator's price table returned a non-object response"
        )
    return data
