# SPDX-License-Identifier: MIT
"""Live OpenRouter model provider, pinned to the approved pilot settings.

- Model `anthropic/claude-sonnet-5.5` only: no `models` fallback list, no
  plugins, no web search, and a response from any other model is rejected.
- Provider routing is pinned (`provider.only`, `allow_fallbacks: false`,
  `require_parameters`, `zdr`, `data_collection: deny`, and `max_price` at
  the catalog's highest prices) per
  https://openrouter.ai/docs/guides/routing/provider-selection. The
  provider slugs are the ZDR endpoints the 2026-11-06 catalog research
  listed for this model; a slug that no longer serves it fails the call.
- `preflight()` must pass before any inference: it reads the key's own
  status (`GET /api/v1/key`) and refuses unless the key has a hard credit
  limit of at most `KEY_LIMIT_MAX_USD`, with credit left.
- Before each completion the public catalog entry is re-fetched (without
  the key) and every limit is checked in code before a request is sent;
  each attempt, retries included, reserves its worst-case cost in a
  per-review `ReviewBudget` first, capped at the lower of the review
  budget and the key's remaining credit as read by the preflight. Actual usage and cost are read from the
  response's `usage` object.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from atlas_reviewer.budget import (
    BudgetRefusedError,
    CallLimits,
    CallRecord,
    ReviewBudget,
    check_tokens,
    input_token_bound,
    worst_case_usd,
)
from atlas_reviewer.http import HttpResponse, Transport, safe_url
from atlas_reviewer.ports import BoundaryError, Json
from atlas_reviewer.pricing import (
    KeyStatus,
    ModelTerms,
    PricingUnknownError,
    money,
    parse_key_status,
    parse_model_terms,
)
from atlas_reviewer.prompt import Prompt

API_URL = "https://openrouter.ai/api/v1"
MODEL_ID = "anthropic/claude-sonnet-5.5"
PINNED_PROVIDERS = ("amazon-bedrock", "google-vertex")
KEY_LIMIT_MAX_USD = Decimal("5.00")
RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})
_PER_MILLION = Decimal(1_000_000)


class OpenRouterProvider:
    name = f"openrouter:{MODEL_ID}"

    def __init__(
        self,
        transport: Transport,
        api_key: str,
        *,
        limits: CallLimits | None = None,
        api_url: str = API_URL,
        timeout_s: float = 300.0,
        sleep: Callable[[float], None] = lambda _s: None,
    ) -> None:
        self._transport = transport
        self._key = api_key
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._sleep = sleep
        self.budget = ReviewBudget(limits or CallLimits())
        self._key_status: KeyStatus | None = None

    def preflight(self) -> KeyStatus:
        status = parse_key_status(self._get_json("/key", authed=True))
        if status.limit > KEY_LIMIT_MAX_USD:
            raise PricingUnknownError(
                f"the OpenRouter key's credit limit ${status.limit} is over the "
                f"${KEY_LIMIT_MAX_USD} pilot ceiling"
            )
        if status.limit_remaining <= 0:
            raise PricingUnknownError("the OpenRouter key has no credit remaining")
        self._key_status = status
        return status

    def usage_lines(self) -> tuple[str, ...]:
        return (f"model `{MODEL_ID}` via OpenRouter", *self.budget.report())

    def complete(self, prompt: Prompt) -> str:
        if self._key_status is None:
            raise BudgetRefusedError("refusing inference: key preflight has not passed")
        terms = parse_model_terms(self._get_json(f"/model/{MODEL_ID}"), MODEL_ID)
        tokens = input_token_bound(prompt.system + prompt.user)
        check_tokens(tokens, terms, self.budget.limits)
        worst = worst_case_usd(tokens, terms, self.budget.limits)
        return self._attempts(self._body(prompt, terms), terms, worst)

    def _attempts(self, body: bytes, terms: ModelTerms, worst: Decimal) -> str:
        remaining = self._key_status.limit_remaining if self._key_status else Decimal(0)
        last: BoundaryError | None = None
        for attempt in range(self.budget.limits.max_calls):
            if attempt:
                self._sleep(2.0**attempt)
            try:
                record = self.budget.reserve(worst, ceiling_usd=remaining)
            except BudgetRefusedError as refusal:
                raise (last or refusal) from refusal
            result = self._send(body, terms, record)
            if isinstance(result, str):
                return result
            last = result
        raise last or BoundaryError("no model call was made")

    def _send(
        self, body: bytes, terms: ModelTerms, record: CallRecord
    ) -> str | BoundaryError:
        url = f"{self._api_url}/chat/completions"
        try:
            resp = self._transport.request(
                "POST",
                url,
                self._headers(authed=True, json_body=True),
                body,
                self._timeout_s,
            )
        except BoundaryError as exc:
            ReviewBudget.settle(record, f"transport error: {exc}")
            return exc
        if resp.status in RETRYABLE:
            ReviewBudget.settle(record, f"HTTP {resp.status} (retryable)")
            return BoundaryError(f"OpenRouter HTTP {resp.status} for {safe_url(url)}")
        if resp.status != 200:
            ReviewBudget.settle(record, f"HTTP {resp.status}")
            raise BoundaryError(f"OpenRouter HTTP {resp.status} for {safe_url(url)}")
        return _completion(resp, terms, record)

    def _body(self, prompt: Prompt, terms: ModelTerms) -> bytes:
        limits = self.budget.limits
        payload = {
            "model": MODEL_ID,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "max_tokens": limits.max_output_tokens,
            "reasoning": {"max_tokens": limits.reasoning_max_tokens, "exclude": True},
            "stream": False,
            "provider": {
                "only": list(PINNED_PROVIDERS),
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
                "max_price": {
                    "prompt": float(terms.prompt_rate * _PER_MILLION),
                    "completion": float(terms.completion_rate * _PER_MILLION),
                },
            },
        }
        return json.dumps(payload).encode()

    def _headers(self, *, authed: bool, json_body: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": "code-quality-atlas-reviewer",
            "Accept": "application/json",
        }
        if authed:
            headers["Authorization"] = f"Bearer {self._key}"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _get_json(self, path: str, *, authed: bool = False) -> Json:
        url = f"{self._api_url}{path}"
        resp = self._transport.request(
            "GET", url, self._headers(authed=authed), None, self._timeout_s
        )
        if resp.status != 200:
            raise PricingUnknownError(
                f"OpenRouter HTTP {resp.status} for {safe_url(url)}"
            )
        return _json_object(resp.body, safe_url(url), PricingUnknownError)


def _json_object(raw: bytes, where: str, error: type[BoundaryError]) -> Json:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise error(f"non-JSON response from {where}") from None
    if not isinstance(data, dict):
        raise error(f"non-object response from {where}")
    return data


def _completion(resp: HttpResponse, terms: ModelTerms, record: CallRecord) -> str:
    try:
        data = _json_object(resp.body, "OpenRouter chat completion", BoundaryError)
    except BoundaryError:
        ReviewBudget.settle(record, "unparseable response")
        raise
    usage = data.get("usage")
    actual, summary = _actual_cost(usage if isinstance(usage, dict) else {}, terms)
    served = data.get("model")
    if not isinstance(served, str) or not _is_pinned_model(served):
        ReviewBudget.settle(record, f"rejected: served by {served!r}", actual, summary)
        raise BoundaryError(f"OpenRouter served {served!r}, not {MODEL_ID}")
    text, finish = _message(data)
    if not text.strip():
        ReviewBudget.settle(
            record, f"empty review (finish_reason={finish})", actual, summary
        )
        raise BoundaryError(f"model returned no review text (finish_reason={finish})")
    ReviewBudget.settle(record, f"ok (finish_reason={finish})", actual, summary)
    return text


def _is_pinned_model(served: str) -> bool:
    return served == MODEL_ID or served.startswith(f"{MODEL_ID}-")


def _message(data: Json) -> tuple[str, str]:
    choices = data.get("choices")
    first: Any = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    finish = first.get("finish_reason") if isinstance(first, dict) else None
    return (content if isinstance(content, str) else ""), str(finish)


def _tokens(usage: Json, key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _actual_cost(usage: Json, terms: ModelTerms) -> tuple[Decimal | None, str]:
    prompt_t, completion_t = (
        _tokens(usage, "prompt_tokens"),
        _tokens(usage, "completion_tokens"),
    )
    details = usage.get("completion_tokens_details")
    reasoning_t = (
        _tokens(details, "reasoning_tokens") if isinstance(details, dict) else None
    )
    summary = f"tokens in={prompt_t} out={completion_t} reasoning={reasoning_t}"
    try:
        return money(usage["cost"], "usage.cost"), summary
    except (KeyError, PricingUnknownError):
        pass
    if prompt_t is None or completion_t is None:
        return None, summary
    estimate = prompt_t * terms.input_rate + completion_t * terms.completion_rate
    return (
        estimate + terms.request_fee,
        f"{summary} (cost computed at the highest catalog rates)",
    )
