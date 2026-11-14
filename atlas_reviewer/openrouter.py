# SPDX-License-Identifier: MIT
"""Live OpenRouter model provider, pinned to the approved pilot settings.

- The model defaults to `anthropic/claude-sonnet-5.5`. `ATLAS_MODEL` or
  `--model` selects another id. No `models` fallback list, no plugins, no
  web search. A response is accepted only from the configured id, or from
  a dated revision of that id (`<id>-YYYYMMDD`).
- Provider routing stays pinned (`provider.only`, `allow_fallbacks:
  false`, `require_parameters: true`, `data_collection: deny`) per
  https://openrouter.ai/docs/guides/routing/provider-selection (fetched
  2026-11-07). `allow_fallbacks`, `require_parameters`, and
  `data_collection` are not configurable. `zdr: true` is the default
  and is turned off by `ATLAS_REQUIRE_ZDR=false` or `--no-require-zdr`
  (D57). `max_price` is the highest prompt and completion price among
  the selected endpoint rows, not the catalog headline. `only` defaults
  to the slugs named by the 2026-11-07 public-list check
  (`PINNED_PROVIDERS`). `ATLAS_PROVIDERS` or `--providers` replaces that
  list, and a single slug is a valid pin. That page's "Base Slug
  Matching" says a bare provider slug in `only` matches every eligible
  endpoint of that provider, regions included.
  https://openrouter.ai/docs/guides/features/in-region-routing
  ("Regional Endpoints on the Global Domain") says a bare
  `amazon-bedrock` does not pin that provider's regional-surcharge
  endpoints, so those region slugs are not part of the default pin.
- Before any completion the public endpoint list is read, without the
  key. With the ZDR requirement on (the default) that is
  `GET /api/v1/endpoints/zdr`. The guide that names that URL is
  https://openrouter.ai/docs/guides/features/zdr (fetched 2026-11-12).
  It says the list includes Safety Retention endpoints. Each row's
  `safety_retention` boolean was on that list the same day. A requested
  slug is eligible only when every row for this model and that exact
  tag has `safety_retention: false`, and every child tag
  (`<slug>/...`) on the list for this model does too. A child that is
  Safety Retention refuses the parent, because `only` of the parent can
  expand to it. A slug with no exact row is refused, and the error names
  child tags when the list has them (`deepinfra` is not a tag;
  `deepinfra/fp8` is). A non-boolean flag refuses the slug. No
  completion is sent. `zdr: true` still follows the account's Safety
  Retention choice, so the client does not rely on that choice to drop
  a listed child. `ATLAS_ALLOW_SAFETY_RETENTION=true` or
  `--allow-safety-retention` opts in to those rows. The default is off.
  With the ZDR requirement off, the read is
  `GET /api/v1/models/{author}/{slug}/endpoints` instead, so a row that
  is not on the ZDR list can still be selected. A missing
  `safety_retention` on that document is not a refusal. A row that sets
  the flag true is still refused unless the opt-in is on.
  `data_collection: deny` stays on either way. The list and the model
  catalog are read once per provider and reused for later completions
  in that review. The catalog confirms the model id. Prices, context
  and the completion limit come from the selected rows (D57).
- `reasoning` is sent only when every eligible row lists `reasoning` in
  `supported_parameters`. `cache_control` is sent on every
  Anthropic-family route (`anthropic/...`) even when no row lists it:
  OpenRouter does not advertise the parameter, and a ZDR Bedrock
  endpoint still honors it (D57, amending D51). Other models keep the
  intersection. `max_tokens` is always sent, at the configured output
  cap. `require_parameters` stays true.
- `preflight()` must pass before any inference: it reads the key's own
  status (`GET /api/v1/key`) and refuses unless the key has a hard credit
  limit of at most the configured ceiling (default `KEY_LIMIT_MAX_USD`),
  with credit left. A key whose `include_byok_in_limit` is false or
  absent is accepted. Raise the ceiling with `--key-ceiling-usd` or
  `ATLAS_KEY_CEILING_USD` when the key's own limit is higher.
- The public catalog entry is fetched once per provider for the review
  and reused, without the key. Every limit is checked in code before a
  request is sent;
  each attempt, retries included, reserves its worst-case cost in a
  per-review `ReviewBudget` first, capped at the lower of the review
  budget and the key's remaining credit as read by the preflight. Actual usage and cost are read from the
  response's `usage` object.
- The key's own usage counter (`GET /api/v1/key`) is read once, by the
  preflight, and never after inference. It can lag a completion by about 90
  seconds (one owner-reported pilot observation, not checked against
  OpenRouter's documentation), so a $0 readback right after a call is
  expected and is not a mismatch with the per-response cost recorded here.
  Spend is reconciled from the response, never from that counter.
  Settlement rule. When `usage.is_byok` is boolean false, the call settles
  `usage.cost` and a reported `cost_details.upstream_inference_cost` is not
  added, with two over-counts: an upstream amount larger than `usage.cost`
  settles at that amount, and an upstream value that is present, not null
  and unreadable keeps the full reservation. A null or absent upstream
  settles `usage.cost`; with no usable `usage.cost` it is priced from the
  highest selected-endpoint rates, or, when the response reports cache
  read or write counts, with those counts at those endpoints' cache rates
  (`_prompt_cost`), and upstream is still not added. For any other
  `is_byok` value a reported upstream cost is added. A call with `is_byok`
  true and no upstream cost keeps its full reservation. A present,
  non-null, unreadable upstream value keeps the reservation on any
  response, including an explicitly non-BYOK one. A null upstream
  keeps the reservation unless `is_byok` is exactly false. The
  settlement line records the raw upstream value on an explicit
  non-BYOK call, cut to 200 characters.
  The SDK says that on a BYOK request `cost` is the OpenRouter fee only
  (https://openrouter.ai/docs/client-sdks/typescript/models/decisionsresponseusage,
  fetched 2026-11-11). The usage-accounting page calls `cost` the total
  charged to the account and does not say whether a non-BYOK `cost`
  already includes the upstream amount
  (https://openrouter.ai/docs/cookbook/administration/usage-accounting,
  fetched 2026-11-11) (verify). The rule is policy: on PR #585 (2026-11-11)
  the key charge equalled `usage.cost` and the previous sum settled twice
  that. A key whose `include_byok_in_limit` is not true passes preflight
  and the run is in no-BYOK mode: a response is used only when
  `usage.is_byok` is boolean false. True, a missing field, any other
  value, or an HTTP 200 whose body cannot be parsed raises
  `ByokRefusedError` after the call is settled, so the review stops
  before another model call. OpenRouter's usage cookbook shows
  `is_byok: false` on its Responses API example and omits the field from
  its Chat Completions example, and the SDK types it as optional
  (https://openrouter.ai/docs/cookbook/administration/usage-accounting,
  fetched 2026-11-11), so a missing field is not evidence the call was
  non-BYOK.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, NoReturn

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
from atlas_reviewer.ports import BoundaryError, ByokRefusedError, Json
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
ENV_MODEL = "ATLAS_MODEL"
ENV_PROVIDERS = "ATLAS_PROVIDERS"
ENV_ALLOW_SAFETY_RETENTION = "ATLAS_ALLOW_SAFETY_RETENTION"
ENV_REQUIRE_ZDR = "ATLAS_REQUIRE_ZDR"
ENV_KEY_CEILING_USD = "ATLAS_KEY_CEILING_USD"
# Slugs named by the 2026-11-07 public-list check and the routing docs.
# Not an inventory of every Bedrock region: those were reported, not named.
# This is the default pin, not a closed set of slugs a request may name.
PINNED_PROVIDERS = (
    "amazon-bedrock",
    "google-vertex/europe",
    "google-vertex/global",
    "google-vertex/us",
)
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._+-]*/[a-z0-9][a-z0-9._+-]*$")
_PROVIDER_SLUG = re.compile(r"^[a-z0-9][a-z0-9._+-]*(?:/[a-z0-9][a-z0-9._+-]*)*$")
KEY_LIMIT_MAX_USD = Decimal("5.00")
RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})
_PER_MILLION = Decimal(1_000_000)
# A numeric Retry-After above this waits this long; the 3-call cap still bounds
# how many waits a review can make.
_MAX_RETRY_WAIT = 8.0


@dataclass(frozen=True)
class ModelRoute:
    """The model and provider pin for one provider instance."""

    model_id: str
    providers: tuple[str, ...]
    allow_safety_retention: bool
    require_zdr: bool = True


@dataclass(frozen=True)
class SelectedEndpoints:
    """Eligible rows for the route, and the parameters they all list."""

    providers: tuple[str, ...]
    supported: frozenset[str]
    rows: tuple[Mapping[str, Any], ...]
    require_zdr: bool


def _model_id(raw: str) -> str:
    model = raw.strip()
    if _MODEL_ID.fullmatch(model) is None:
        raise BudgetRefusedError(
            f"refusing inference: {model!r} is not an OpenRouter model id"
        )
    return model


def _provider_slugs(slugs: Sequence[str]) -> tuple[str, ...]:
    """Drop duplicates. An empty list, or a slug that is not a provider
    tag, is refused before any request: `only: []` would drop the pin."""
    if not slugs:
        raise BudgetRefusedError("refusing inference: provider allowlist is empty")
    cleaned: list[str] = []
    for slug in slugs:
        text = slug.strip()
        if _PROVIDER_SLUG.fullmatch(text) is None:
            raise BudgetRefusedError(
                f"refusing inference: {slug!r} is not a provider slug"
            )
        if text not in cleaned:
            cleaned.append(text)
    return tuple(cleaned)


def _split_providers(raw: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw.split(",")]
    if any(part == "" for part in parts):
        raise BudgetRefusedError(
            "refusing inference: provider allowlist has an empty slug"
        )
    return _provider_slugs(parts)


def _bool_flag(value: bool) -> bool:
    if not isinstance(value, bool):
        raise BudgetRefusedError(
            "refusing inference: allow_safety_retention must be a boolean"
        )
    return value


def _safety_retention_flag(raw: str | None) -> bool:
    """Unset is off. Only `true` and `false` (any case) are values."""
    if raw is None or raw.strip() == "":
        return False
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise BudgetRefusedError(
        f"{ENV_ALLOW_SAFETY_RETENTION} must be true or false, not {raw!r}"
    )


def _require_zdr_flag(raw: str | None) -> bool:
    """Unset is on. Only `true` and `false` (any case) are values."""
    if raw is None or raw.strip() == "":
        return True
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise BudgetRefusedError(f"{ENV_REQUIRE_ZDR} must be true or false, not {raw!r}")


def model_route(
    env: Mapping[str, str],
    *,
    model: str | None = None,
    providers: str | None = None,
    allow_safety_retention: bool = False,
    require_zdr: bool | None = None,
) -> ModelRoute:
    """A model or provider flag wins over its environment variable. An
    empty flag is refused. An empty variable is unset, so the default
    stands. Safety Retention is on when the flag is set or
    `ATLAS_ALLOW_SAFETY_RETENTION` is true. The flag is store_true, so
    it cannot turn a true environment variable off. The ZDR requirement
    stays on unless `require_zdr` is false (`--no-require-zdr`) or
    `ATLAS_REQUIRE_ZDR` is false. The flag wins, so a true environment
    variable does not keep the requirement on."""
    _bool_flag(allow_safety_retention)
    if require_zdr is None:
        required = _require_zdr_flag(env.get(ENV_REQUIRE_ZDR))
    elif isinstance(require_zdr, bool):
        required = require_zdr
    else:
        raise BudgetRefusedError("refusing inference: require_zdr must be a boolean")
    if model is not None:
        if model.strip() == "":
            raise BudgetRefusedError("refusing inference: model id is empty")
        model_id = _model_id(model)
    else:
        raw_model = env.get(ENV_MODEL)
        model_id = (
            MODEL_ID
            if raw_model is None or raw_model.strip() == ""
            else _model_id(raw_model)
        )
    if providers is not None:
        if providers.strip() == "":
            raise BudgetRefusedError("refusing inference: provider allowlist is empty")
        slugs = _split_providers(providers)
    else:
        raw_providers = env.get(ENV_PROVIDERS)
        slugs = (
            PINNED_PROVIDERS
            if raw_providers is None or raw_providers.strip() == ""
            else _split_providers(raw_providers)
        )
    allow = allow_safety_retention or _safety_retention_flag(
        env.get(ENV_ALLOW_SAFETY_RETENTION)
    )
    return ModelRoute(model_id, slugs, allow, required)


def _safety_flag(row: Json) -> bool | None:
    flag = row.get("safety_retention")
    if flag is True or flag is False:
        return flag
    return None


def _endpoint_rows(data: Json, model_id: str) -> list[Mapping[str, Any]]:
    """Rows from the ZDR list (`data` is an array) or from
    `GET /api/v1/models/{id}/endpoints` (`data.endpoints` is the array).

    Both documents are snake_case. `tag` is the provider slug.
    `provider_name` is a display name, such as ``Amazon Bedrock`` next
    to ``amazon-bedrock``, and is not read. A row for another model is
    ignored. A row with no model id on the nested document is this model.
    """
    payload = data.get("data")
    if isinstance(payload, list):
        rows: list[Mapping[str, Any]] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise PricingUnknownError("endpoint list has a non-object entry")
            rows.append(item)
        return rows
    if isinstance(payload, Mapping):
        listed = payload.get("id")
        if listed is not None and listed != model_id:
            raise PricingUnknownError(
                f"endpoint list is for {listed!r}, not {model_id!r}"
            )
        endpoints = payload.get("endpoints")
        if not isinstance(endpoints, list):
            raise PricingUnknownError("endpoint list has no endpoints array")
        rows = []
        for item in endpoints:
            if not isinstance(item, Mapping):
                raise PricingUnknownError("endpoint list has a non-object entry")
            row = dict(item)
            if row.get("model_id") in (None, model_id):
                row["model_id"] = model_id
                rows.append(row)
        return rows
    raise PricingUnknownError("endpoint list has no data array")


def _row_tag(row: Mapping[str, Any]) -> str | None:
    """The provider slug. `provider_name` is the display name, not a slug."""
    tag = row.get("tag")
    if isinstance(tag, str) and tag != "":
        return tag
    return None


def _row_parameters(row: Mapping[str, Any]) -> frozenset[str]:
    params = row.get("supported_parameters")
    if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
        return frozenset()
    return frozenset(params)


def select_endpoints(data: Json, route: ModelRoute) -> SelectedEndpoints:
    """Eligible rows for this route.

    With the ZDR requirement on, `data` is `GET /api/v1/endpoints/zdr`.
    With it off, `data` is `GET /api/v1/models/{id}/endpoints`. A slug is
    eligible when the list has at least one row for this model and that
    exact tag, and neither those rows nor any child tag (`<slug>/...`
    for the same model) is Safety Retention, unless the route opts in.
    On the ZDR list a missing or non-boolean `safety_retention` refuses
    the slug. On the full endpoint list a missing flag does not. A
    parent is refused when a child is Safety Retention, because
    `provider.only` of the parent can expand to that child. A slug with
    no exact row is refused, and the refusal names child tags when the
    list has them. `supported` intersects `supported_parameters` across
    the exact rows and those children. A parameter list that is missing
    or not a list of strings contributes an empty set, so the request
    omits `reasoning`. `cache_control` is not decided here: Anthropic-family
    routes send it anyway (D57). `max_tokens` is not optional.
    """
    items = _endpoint_rows(data, route.model_id)
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        if item.get("model_id") != route.model_id:
            continue
        tag = _row_tag(item)
        if tag is None:
            continue
        grouped.setdefault(tag, []).append(item)
    problems: list[str] = []
    chosen: list[Json] = []
    for tag in route.providers:
        rows = grouped.get(tag, [])
        children = sorted(child for child in grouped if child.startswith(tag + "/"))
        child_rows = [row for child in children for row in grouped[child]]
        if not rows:
            kind = "ZDR row" if route.require_zdr else "endpoint"
            if children:
                problems.append(
                    f"{tag} has no {kind} for {route.model_id}; pin an exact "
                    "tag (" + ", ".join(children[:8]) + ")"
                )
            else:
                problems.append(f"{tag} has no {kind} for {route.model_id}")
            continue
        scope = (*rows, *child_rows)
        if route.require_zdr and any(_safety_flag(row) is None for row in scope):
            problems.append(
                f"{tag} has a ZDR row whose safety_retention is not a boolean"
            )
            continue
        if not route.allow_safety_retention and any(
            _safety_flag(row) is True for row in scope
        ):
            problems.append(
                f"{tag} has a Safety Retention endpoint for {route.model_id}"
                + (
                    " (a child tag provider.only can expand to)"
                    if any(_safety_flag(row) is True for row in child_rows)
                    else ""
                )
            )
            continue
        chosen.extend(scope)
    if problems:
        if route.require_zdr:
            raise BudgetRefusedError(
                "refusing inference: no eligible zero-data-retention endpoint ("
                + "; ".join(problems)
                + "). zdr and data_collection deny stay on. Safety Retention "
                f"requires {ENV_ALLOW_SAFETY_RETENTION}=true or "
                "--allow-safety-retention."
            )
        raise BudgetRefusedError(
            "refusing inference: no eligible endpoint ("
            + "; ".join(problems)
            + "). data_collection deny stays on. Safety Retention "
            f"requires {ENV_ALLOW_SAFETY_RETENTION}=true or "
            "--allow-safety-retention."
        )
    supported = _parameter_intersection(chosen)
    return SelectedEndpoints(
        route.providers, supported, tuple(chosen), route.require_zdr
    )


def _parameter_intersection(rows: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    sets = [_row_parameters(row) for row in rows]
    if not sets:
        return frozenset()
    return frozenset.intersection(*sets)


def _per_million(rate: Decimal, what: str) -> float:
    value = float(rate * _PER_MILLION)
    if not math.isfinite(value):
        raise PricingUnknownError(f"{what} is not a finite per-million price")
    return value


def _positive_count(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PricingUnknownError(f"{what} is missing or not a positive integer")
    return value


def _optional_money(
    pricing: Mapping[str, Any], keys: Sequence[str], what: str
) -> list[Decimal]:
    return [money(pricing[key], f"{what} {key}") for key in keys if key in pricing]


def terms_from_endpoints(
    rows: Sequence[Mapping[str, Any]], model_id: str
) -> ModelTerms:
    """Prices and limits from the rows the route itself selected.

    Prompt and completion are the highest rate on any selected row, so
    `max_price` and the reservation cover the dearest pinned endpoint.
    Context and the completion limit are the smallest, so a tighter
    endpoint cannot be asked for more than it serves. A selected row
    with no pricing object, a zero required rate, or a missing limit
    refuses the call. Catalog headline numbers are not read here.
    """
    if not rows:
        raise PricingUnknownError("no endpoint rows to price")
    prompts: list[Decimal] = []
    completions: list[Decimal] = []
    contexts: list[int] = []
    outputs: list[int] = []
    requests: list[Decimal] = []
    reasonings: list[Decimal] = []
    cache_reads: list[Decimal] = []
    cache_writes: list[Decimal] = []
    for index, row in enumerate(rows):
        pricing = row.get("pricing")
        if not isinstance(pricing, Mapping):
            raise PricingUnknownError(f"endpoint row {index} has no pricing object")
        where = f"endpoint row {index} pricing"
        prompt = money(pricing.get("prompt"), f"{where}.prompt")
        completion = money(pricing.get("completion"), f"{where}.completion")
        if prompt == 0:
            raise PricingUnknownError(f"{where}.prompt is zero")
        if completion == 0:
            raise PricingUnknownError(f"{where}.completion is zero")
        prompts.append(prompt)
        completions.append(completion)
        contexts.append(
            _positive_count(
                row.get("context_length"),
                f"endpoint row {index} context_length",
            )
        )
        outputs.append(
            _positive_count(
                row.get("max_completion_tokens"),
                f"endpoint row {index} max_completion_tokens",
            )
        )
        requests.extend(_optional_money(pricing, ("request",), where))
        reasonings.extend(_optional_money(pricing, ("internal_reasoning",), where))
        cache_reads.extend(_optional_money(pricing, ("input_cache_read",), where))
        cache_writes.extend(
            _optional_money(
                pricing, ("input_cache_write", "input_cache_write_1h"), where
            )
        )
    prompt_rate = max(prompts)
    completion_rate = max(completions)
    cache_write = max(cache_writes) if cache_writes else Decimal(0)
    return ModelTerms(
        model_id=model_id,
        input_rate=max(prompt_rate, cache_write),
        prompt_rate=prompt_rate,
        completion_rate=completion_rate,
        reasoning_rate=max(reasonings) if reasonings else Decimal(0),
        request_fee=max(requests) if requests else Decimal(0),
        context_length=min(contexts),
        max_completion_tokens=min(outputs),
        cache_read_rate=max(cache_reads) if cache_reads else None,
        cache_write_rate=max(cache_writes) if cache_writes else None,
    )


def provider_preferences(
    providers: Sequence[str], terms: ModelTerms, *, require_zdr: bool
) -> dict[str, Any]:
    """The routing document.

    `allow_fallbacks` stays false, `require_parameters` stays true, and
    `data_collection` stays `deny`. `zdr` is sent only when the route
    requires zero data retention. `max_price` is the selected endpoints'
    highest prompt and completion rates. A rate that does not fit in a
    finite per-million JSON number is refused.
    """
    document: dict[str, Any] = {
        "only": list(providers),
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }
    if require_zdr:
        document["zdr"] = True
    document["max_price"] = {
        "prompt": _per_million(terms.prompt_rate, "pricing.prompt"),
        "completion": _per_million(terms.completion_rate, "pricing.completion"),
    }
    return document


def sends_cache_control(model_id: str, supported: frozenset[str]) -> bool:
    """Whether this request carries an Anthropic cache breakpoint.

    OpenRouter does not list `cache_control` in `supported_parameters`
    for any endpoint, ZDR or not, so D51's intersection never sends it.
    A ZDR Bedrock endpoint for an Anthropic model still honors the
    breakpoint when the request sends it with `require_parameters`
    true (probed 2026-11-13). Anthropic-family model ids
    (`anthropic/...`) therefore always send it. Any other model keeps
    the intersection.
    """
    if model_id.startswith("anthropic/"):
        return True
    return "cache_control" in supported


def optional_parameters(
    supported: frozenset[str], reasoning_max_tokens: int, *, model_id: str
) -> dict[str, Any]:
    """Parameters `require_parameters` would otherwise refuse.

    `reasoning` is included only when every selected endpoint lists it.
    The reasoning object, when sent, still carries the configured token
    hint and `exclude`. `cache_control` follows `sends_cache_control`.
    """
    extra: dict[str, Any] = {}
    if "reasoning" in supported:
        extra["reasoning"] = {"max_tokens": reasoning_max_tokens, "exclude": True}
    if sends_cache_control(model_id, supported):
        extra["cache_control"] = {"type": "ephemeral"}
    return extra


class OpenRouterProvider:
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
        model_id: str = MODEL_ID,
        allow_safety_retention: bool = False,
        key_ceiling: Decimal = KEY_LIMIT_MAX_USD,
    ) -> None:
        self._transport = transport
        self._key = api_key
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._sleep = sleep
        self.budget = ReviewBudget(limits or CallLimits())
        self._key_status: KeyStatus | None = None
        self.key_ceiling = key_ceiling
        self._loaded: tuple[ModelRoute, ModelTerms, SelectedEndpoints] | None = None
        self._route = ModelRoute(MODEL_ID, PINNED_PROVIDERS, False)
        self.name = f"openrouter:{MODEL_ID}"
        self.configure(
            ModelRoute(
                _model_id(model_id),
                _provider_slugs(providers),
                _bool_flag(allow_safety_retention),
            )
        )

    def configure(self, route: ModelRoute) -> None:
        self._route = route
        self.name = f"openrouter:{route.model_id}"
        self._loaded = None

    @property
    def model_id(self) -> str:
        return self._route.model_id

    @property
    def _providers(self) -> tuple[str, ...]:
        return self._route.providers

    def preflight(self) -> KeyStatus:
        status = parse_key_status(self._get_json("/key", authed=True))
        if status.limit > self.key_ceiling:
            raise PricingUnknownError(
                f"the OpenRouter key's credit limit ${status.limit} is over the "
                f"${self.key_ceiling} pilot ceiling configured by "
                "--key-ceiling-usd or ATLAS_KEY_CEILING_USD"
            )
        if status.limit_remaining <= 0:
            raise PricingUnknownError("the OpenRouter key has no credit remaining")
        self._key_status = status
        return status

    def usage_lines(self) -> tuple[str, ...]:
        line = f"model `{self.model_id}` via OpenRouter"
        found = self.routing()
        if found is not None:
            required, caching = found
            line += (
                f"; zdr required: {str(required).lower()}"
                f"; cache_control: {str(caching).lower()}"
            )
        return (line, *self.budget.report())

    def routing(self) -> tuple[bool, bool] | None:
        """Whether this run required ZDR, and whether `cache_control` was sent.

        None until the endpoint list has been read for the current route.
        """
        loaded = self._loaded
        if loaded is None or loaded[0] != self._route:
            return None
        selected = loaded[2]
        return (
            selected.require_zdr,
            sends_cache_control(self.model_id, selected.supported),
        )

    def load_terms(self) -> tuple[ModelTerms, SelectedEndpoints]:
        """Endpoint prices and the selected rows for this route. No completion.

        The first call reads the catalog, to confirm the model id, and
        the endpoint list. Later calls on this provider reuse them.
        `configure` drops the snapshot. Prices and limits come from the
        selected rows. A non-200 list, a transport error, or an
        unreadable body raises and no completion is sent.
        """
        cached = self._loaded
        if cached is not None and cached[0] == self._route:
            return cached[1], cached[2]
        parse_model_terms(self._get_json(f"/model/{self.model_id}"), self.model_id)
        if self._route.require_zdr:
            document = self._get_json("/endpoints/zdr")
        else:
            document = self._get_json(f"/models/{self.model_id}/endpoints")
        selected = select_endpoints(document, self._route)
        terms = terms_from_endpoints(selected.rows, self.model_id)
        self._loaded = (self._route, terms, selected)
        return terms, selected

    def complete(self, prompt: Prompt) -> str:
        if self._key_status is None:
            self._refused(
                BudgetRefusedError("refusing inference: key preflight has not passed")
            )
        try:
            terms, selected = self.load_terms()
            body = self._body(prompt, terms, selected)
        except (PricingUnknownError, BudgetRefusedError) as exc:
            self._refused(exc)
        tokens = input_token_bound(prompt.system + prompt.user)
        try:
            check_tokens(tokens, terms, self.budget.limits)
        except BudgetRefusedError as exc:
            self._refused(exc)
        worst = worst_case_usd(tokens, terms, self.budget.limits)
        return self._attempts(body, terms, worst)

    def _refused(self, exc: BoundaryError) -> NoReturn:
        """Record a refusal that spent nothing and was not sent, then raise it."""
        self.budget.refusals.append(str(exc))
        raise exc

    def _attempts(self, body: bytes, terms: ModelTerms, worst: Decimal) -> str:
        remaining = self._key_status.limit_remaining if self._key_status else Decimal(0)
        last: BoundaryError | None = None
        retry_after: str | None = None
        for attempt in range(self.budget.limits.max_calls):
            if attempt:
                self._sleep(_retry_wait(retry_after, attempt))
            try:
                record = self.budget.reserve(worst, ceiling_usd=remaining)
            except BudgetRefusedError as refusal:
                raise (last or refusal) from refusal
            result = self._send(body, terms, record)
            if isinstance(result, str):
                return result
            last, retry_after = result
        raise last or BoundaryError("no model call was made")

    def _send(
        self, body: bytes, terms: ModelTerms, record: CallRecord
    ) -> str | tuple[BoundaryError, str | None]:
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
            return exc, None
        if resp.status in RETRYABLE:
            ReviewBudget.settle(record, f"HTTP {resp.status} (retryable)")
            return (
                BoundaryError(f"OpenRouter HTTP {resp.status} for {safe_url(url)}"),
                resp.header("Retry-After"),
            )
        if resp.status != 200:
            ReviewBudget.settle(record, f"HTTP {resp.status}")
            raise BoundaryError(f"OpenRouter HTTP {resp.status} for {safe_url(url)}")
        counts_byok = self._key_status.counts_byok if self._key_status else False
        return _completion(resp, terms, record, self.model_id, counts_byok=counts_byok)

    def _body(
        self, prompt: Prompt, terms: ModelTerms, selected: SelectedEndpoints
    ) -> bytes:
        limits = self.budget.limits
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            # Always the configured output cap, even when the endpoint
            # does not list max_tokens. The reservation prices this cap.
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
                model_id=self.model_id,
            )
        )
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


def _retry_wait(header: str | None, attempt: int) -> float:
    """Seconds before the next attempt: a numeric Retry-After, capped, else
    exponential backoff. An HTTP-date or a negative value is not numeric."""
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


def _json_object(raw: bytes, where: str, error: type[BoundaryError]) -> Json:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise error(f"non-JSON response from {where}") from None
    if not isinstance(data, dict):
        raise error(f"non-object response from {where}")
    return data


def _completion(
    resp: HttpResponse,
    terms: ModelTerms,
    record: CallRecord,
    model_id: str,
    *,
    counts_byok: bool,
) -> str:
    try:
        data = _json_object(resp.body, "OpenRouter chat completion", BoundaryError)
    except BoundaryError:
        ReviewBudget.settle(record, "unparseable response")
        if not counts_byok:
            raise ByokRefusedError(
                "refusing the review: this OpenRouter key does not count BYOK "
                "spend against its credit limit, and the response could not be "
                "parsed, so is_byok could not be checked"
            ) from None
        raise
    usage = data.get("usage")
    usage_obj = usage if isinstance(usage, dict) else {}
    if not counts_byok:
        _refuse_unless_explicitly_non_byok(usage_obj, terms, record)
    actual, summary = _actual_cost(usage_obj, terms)
    served = data.get("model")
    if not isinstance(served, str) or not _is_configured_model(served, model_id):
        ReviewBudget.settle(record, f"rejected: served by {served!r}", actual, summary)
        raise BoundaryError(f"OpenRouter served {served!r}, not {model_id}")
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


def _is_configured_model(served: str, model_id: str) -> bool:
    """The configured id, or one dated revision of it. A different id, a
    second suffix, or a suffix that is not eight digits is rejected."""
    if served == model_id:
        return True
    return re.fullmatch(re.escape(model_id) + r"-\d{8}", served) is not None


def _message(data: Json) -> tuple[str, str]:
    choices = data.get("choices")
    first: Any = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    finish = first.get("finish_reason") if isinstance(first, dict) else None
    return (content if isinstance(content, str) else ""), str(finish)


def _refuse_unless_explicitly_non_byok(
    usage: Json, terms: ModelTerms, record: CallRecord
) -> None:
    """No-BYOK mode. Only boolean false is a non-BYOK response. True, a
    missing field, or any other value ends the review. The call is settled
    first, as a BYOK call would be, so an unreported upstream charge keeps
    the full reservation."""
    reason = _no_byok_reason(usage)
    if reason is None:
        return
    marked = usage if usage.get("is_byok") is True else {**usage, "is_byok": True}
    actual, summary = _actual_cost(marked, terms)
    ReviewBudget.settle(record, f"refused: {reason}", actual, summary)
    raise ByokRefusedError(
        "refusing the review: this OpenRouter key does not count BYOK spend "
        f"against its credit limit, and {reason}"
    )


def _no_byok_reason(usage: Json) -> str | None:
    if "is_byok" not in usage:
        return "the response usage has no is_byok field"
    flag = usage["is_byok"]
    if flag is False:
        return None
    if flag is True:
        return "the response usage.is_byok is true"
    return "the response usage.is_byok is not false"


def _prompt_cost(
    usage: Json, terms: ModelTerms, prompt_t: int
) -> tuple[Decimal | None, str]:
    """Price prompt tokens when `usage.cost` is absent.

    With no cache counts, every prompt token is charged at `input_rate`,
    which is already the higher of the prompt rate and any cache-write
    rate. When the response reports cache reads or writes, those counts
    are subsets of `prompt_tokens`: reads are charged at the catalog's
    cache-read rate (or the prompt rate when the catalog has none), and
    writes at the catalog's cache-write rate (or `input_rate` when the
    catalog has none). The rest are charged at the prompt rate when the
    write count is reported. When it is absent, a write could be hiding
    in the rest, so the rest is charged at `input_rate`. Counts that sum
    past `prompt_tokens` are not a usable split, and the turn stays
    unpriced."""
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        return prompt_t * terms.input_rate, ""
    if any(
        details.get(key) is not None and _tokens(details, key) is None
        for key in ("cached_tokens", "cache_write_tokens")
    ):
        return None, ""
    cached = _tokens(details, "cached_tokens")
    written = _tokens(details, "cache_write_tokens")
    if cached is None and written is None:
        return prompt_t * terms.input_rate, ""
    cached_n = 0 if cached is None else cached
    read_rate = (
        terms.prompt_rate if terms.cache_read_rate is None else terms.cache_read_rate
    )
    if written is None:
        if cached_n > prompt_t:
            return None, ""
        cost = cached_n * read_rate + (prompt_t - cached_n) * terms.input_rate
        return cost, f" cache_read={cached_n} cache_write=unreported"
    if cached_n + written > prompt_t:
        return None, ""
    fresh = prompt_t - cached_n - written
    write_rate = (
        terms.input_rate if terms.cache_write_rate is None else terms.cache_write_rate
    )
    cost = fresh * terms.prompt_rate + cached_n * read_rate + written * write_rate
    return cost, f" cache_read={cached_n} cache_write={written}"


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
    # Policy: boolean false settles usage.cost. OpenRouter's docs do not
    # say whether that cost already includes the upstream amount (verify).
    # PR #585 (2026-11-11) charged usage.cost and the old sum settled twice
    # that. Ambiguity over-counts: an upstream amount above usage.cost, or
    # one that is present and unreadable, is never settled below what it
    # could cost.
    explicitly_non_byok = usage.get("is_byok") is False
    raw = _upstream_raw(usage)
    try:
        upstream = _upstream_cost(raw, null_is_absent=explicitly_non_byok)
    except PricingUnknownError:
        if explicitly_non_byok:
            summary += f" (upstream {_shown(raw)} unreadable)"
        return None, summary
    if usage.get("is_byok") is True and upstream is None:
        return None, f"{summary} (BYOK upstream cost not reported)"
    from_usage_cost = True
    try:
        base = money(usage["cost"], "usage.cost")
    except (KeyError, PricingUnknownError):
        from_usage_cost = False
        if prompt_t is None or completion_t is None:
            return None, summary
        if terms.reasoning_rate > 0 and reasoning_t is None:
            return None, summary
        prompt_cost, cache_note = _prompt_cost(usage, terms, prompt_t)
        if prompt_cost is None:
            return None, summary
        reasoning = (reasoning_t or 0) * terms.reasoning_rate
        base = (
            prompt_cost
            + completion_t * terms.completion_rate
            + reasoning
            + terms.request_fee
        )
        rates = "endpoint rates" if cache_note else "the highest endpoint rates"
        summary = f"{summary}{cache_note} (cost computed at {rates})"
    if not explicitly_non_byok:
        if upstream is not None:
            base += upstream
    elif raw is not _ABSENT:
        if from_usage_cost and upstream is not None and upstream > base:
            summary += (
                f" (upstream {_shown(raw)} exceeds usage.cost {base}:"
                " settled at upstream)"
            )
            base = upstream
        else:
            summary += f" (upstream {_shown(raw)} reported, not added: is_byok false)"
    return base, summary


_ABSENT: Any = object()


def _upstream_raw(usage: Json) -> Any:
    """The reported `cost_details.upstream_inference_cost`, or `_ABSENT`."""
    details = usage.get("cost_details")
    if not isinstance(details, dict) or "upstream_inference_cost" not in details:
        return _ABSENT
    return details["upstream_inference_cost"]


def _upstream_cost(raw: Any, *, null_is_absent: bool) -> Decimal | None:
    """`raw` as money. Absent is None. A null is None only when the caller
    says so; any other value that cannot be read raises."""
    if raw is _ABSENT or (raw is None and null_is_absent):
        return None
    return money(raw, "usage.cost_details.upstream_inference_cost")


def _shown(raw: Any) -> str:
    return f"{raw!r:.200}"
