# SPDX-License-Identifier: MIT
"""Live OpenRouter model provider, pinned to the approved pilot settings.

- Model `anthropic/claude-sonnet-5.5` only: no `models` fallback list, no
  plugins, no web search, and a response from any other model is rejected.
- Provider routing is pinned (`provider.only`, `allow_fallbacks: false`,
  `require_parameters`, `zdr`, `data_collection: deny`, and `max_price` at
  the catalog's highest prices) per
  https://openrouter.ai/docs/guides/routing/provider-selection (fetched
  2026-11-07). That page's "Base Slug Matching" says a bare provider slug
  in `only` matches every eligible endpoint of that provider, regions
  included. A read-only check of the public provider list the same day
  found no bare `google-vertex` endpoint, only `google-vertex/global`,
  `google-vertex/us`, and `google-vertex/europe`, and found Amazon Bedrock
  as the base slug `amazon-bedrock` plus region slugs it did not name.
  `PINNED_PROVIDERS` is exactly those named slugs. A slug outside
  `LISTED_PROVIDER_SLUGS` is refused before any request, so a doc example
  (`google-vertex/us-east5`, `amazon-bedrock/eu-west-1`) or the bare
  Vertex slug cannot widen routing. Bedrock's unnamed region slugs are
  not pinned. https://openrouter.ai/docs/guides/features/in-region-routing
  ("Regional Endpoints on the Global Domain") says a bare
  `amazon-bedrock` does not pin that provider's regional-surcharge
  endpoints.
- `preflight()` must pass before any inference: it reads the key's own
  status (`GET /api/v1/key`) and refuses unless the key has a hard credit
  limit of at most `KEY_LIMIT_MAX_USD`, with credit left.
- Before each completion the public catalog entry is re-fetched (without
  the key) and every limit is checked in code before a request is sent;
  each attempt, retries included, reserves its worst-case cost in a
  per-review `ReviewBudget` first, capped at the lower of the review
  budget and the key's remaining credit as read by the preflight. Actual usage and cost are read from the
  response's `usage` object.
- The key's own usage counter (`GET /api/v1/key`) is read once, by the
  preflight, and never after inference. It can lag a completion by about 90
  seconds (one owner-reported pilot observation, not checked against
  OpenRouter's documentation), so a $0 readback right after a call is
  expected and is not a mismatch with the per-response cost recorded here.
  Spend is reconciled from the response, never from that counter:
  `usage.cost`, plus `cost_details.upstream_inference_cost` when an
  upstream charge is reported (on a BYOK call `usage.cost` is only
  OpenRouter's fee). A BYOK call that omits the upstream charge, or an
  upstream charge that cannot be read, keeps its full reservation. A key
  whose `include_byok_in_limit` is not true is refused at preflight: its
  credit limit would not cover that upstream charge.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
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
# Slugs named by the 2026-11-07 public-list check and the routing docs.
# Not an inventory of every Bedrock region: those were reported, not named.
LISTED_PROVIDER_SLUGS = frozenset(
    {
        "amazon-bedrock",
        "google-vertex/europe",
        "google-vertex/global",
        "google-vertex/us",
    }
)
PINNED_PROVIDERS = (
    "amazon-bedrock",
    "google-vertex/europe",
    "google-vertex/global",
    "google-vertex/us",
)
KEY_LIMIT_MAX_USD = Decimal("5.00")
RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})
_PER_MILLION = Decimal(1_000_000)


def _require_listed(slugs: Sequence[str]) -> tuple[str, ...]:
    """Refuse before any request when a slug is not on the reviewed list.

    An empty allowlist is refused too: `only: []` would drop the pin.
    """
    if not slugs:
        raise BudgetRefusedError("refusing inference: provider allowlist is empty")
    unknown = [slug for slug in slugs if slug not in LISTED_PROVIDER_SLUGS]
    if unknown:
        raise BudgetRefusedError(
            "refusing unlisted provider slugs: " + ", ".join(unknown)
        )
    return tuple(dict.fromkeys(slugs))


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
        providers: Sequence[str] = PINNED_PROVIDERS,
    ) -> None:
        self._transport = transport
        self._key = api_key
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._providers = _require_listed(providers)
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
                "only": list(self._providers),
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
    except (json.JSONDecodeError, UnicodeDecodeError):
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
    if finish != "stop":
        ReviewBudget.settle(
            record, f"incomplete review (finish_reason={finish})", actual, summary
        )
        if finish == "length":
            raise BoundaryError("model review stopped at the output-token limit")
        raise BoundaryError(f"model review did not finish (finish_reason={finish})")
    ReviewBudget.settle(record, f"ok (finish_reason={finish})", actual, summary)
    return text


_DATED_REVISION = re.compile(re.escape(MODEL_ID) + r"-\d{8}")


def _is_pinned_model(served: str) -> bool:
    return served == MODEL_ID or _DATED_REVISION.fullmatch(served) is not None


def _message(data: Json) -> tuple[str, str]:
    choices = data.get("choices")
    first: Any = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    finish = first.get("finish_reason") if isinstance(first, dict) else None
    return (content if isinstance(content, str) else ""), str(finish)


def _tokens(usage: Json, key: str) -> int | None:
    value = usage.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


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
        upstream = _upstream_cost(usage)
    except PricingUnknownError:
        return None, summary
    if usage.get("is_byok") is True and upstream is None:
        return None, f"{summary} (BYOK upstream cost not reported)"
    try:
        base = money(usage["cost"], "usage.cost")
    except (KeyError, PricingUnknownError):
        if prompt_t is None or completion_t is None:
            return None, summary
        base = (
            prompt_t * terms.input_rate
            + completion_t * terms.completion_rate
            + terms.request_fee
        )
        summary = f"{summary} (cost computed at the highest catalog rates)"
    if upstream is not None:
        base += upstream
    return base, summary


def _upstream_cost(usage: Json) -> Decimal | None:
    """The provider's own charge, reported beside OpenRouter's fee."""
    details = usage.get("cost_details")
    if not isinstance(details, dict) or "upstream_inference_cost" not in details:
        return None
    return money(
        details["upstream_inference_cost"],
        "usage.cost_details.upstream_inference_cost",
    )
