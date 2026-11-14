# SPDX-License-Identifier: MIT
"""Parse OpenRouter's live model catalog entry and key status. Pure;
fails closed.

Catalog shape: `GET /api/v1/model/{author}/{slug}` returns `{"data":
Model}` with `pricing` in USD per token as decimal strings, optional
`pricing.overrides` (conditional tiers such as long-context or time-of-day
prices), `context_length`, and `top_provider.max_completion_tokens`
(https://openrouter.ai/docs/guides/overview/models). Reservations use the
**highest** price for each key across the base entry and every override,
whatever its condition, so no tier can cost more than reserved.

Key shape: `GET /api/v1/key` returns `{"data": {"limit": number|null,
"limit_remaining": number|null, "usage": number, ...}}`
(https://openrouter.ai/docs/api_reference/limits).
`include_byok_in_limit` true means the key counts BYOK spend against that
limit. False or absent is accepted: `KeyStatus.counts_byok` is then false,
and the caller runs in no-BYOK mode. OpenRouter's key-limit guide says the
field defaults to false
(https://openrouter.ai/docs/guides/best-practices/capping-shared-agent-keys,
fetched 2026-11-11).

A price, a token limit, or the key's `limit`, `limit_remaining` or
`usage` that is missing, non-numeric, negative (the catalog uses -1 for
unknown), non-finite or of an unexpected type raises `PricingUnknownError`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from atlas_reviewer.ports import BoundaryError, Json

ZERO = Decimal(0)


class PricingUnknownError(BoundaryError):
    """Prices, limits or key status could not be established; refuse."""


@dataclass(frozen=True)
class ModelTerms:
    model_id: str
    input_rate: Decimal
    prompt_rate: Decimal
    completion_rate: Decimal
    reasoning_rate: Decimal
    request_fee: Decimal
    context_length: int
    max_completion_tokens: int
    # None when the catalog has no rate for that cache token. A reported
    # zero is a rate. The reservation still uses input_rate, which already
    # takes the higher of the prompt rate and any cache-write rate.
    cache_read_rate: Decimal | None = None
    cache_write_rate: Decimal | None = None
    # Smallest max_prompt_tokens among selected rows that set one.
    # None when no selected row sets it.
    max_prompt_tokens: int | None = None
    # Tags of the rows that set the minimum context, completion limit,
    # or prompt ceiling. Empty when the terms did not come from rows.
    context_limit_tags: str = ""
    completion_limit_tags: str = ""
    prompt_limit_tags: str = ""


@dataclass(frozen=True)
class KeyStatus:
    limit: Decimal
    limit_remaining: Decimal
    usage: Decimal
    # True only when `include_byok_in_limit` is boolean true. False, absent
    # or any other value means the limit does not cover BYOK spend.
    counts_byok: bool


def money(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise PricingUnknownError(f"{what} is missing or not a number")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise PricingUnknownError(f"{what} is not a number: {value!r}") from None
    if not parsed.is_finite() or parsed < ZERO:
        raise PricingUnknownError(f"{what} is unknown (negative or non-finite)")
    return parsed


def _count(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PricingUnknownError(f"{what} is missing or not a positive integer")
    return value


def tiers(pricing: Json) -> list[Json]:
    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list) or not all(
        isinstance(o, Mapping) for o in overrides
    ):
        raise PricingUnknownError("pricing.overrides is not a list of objects")
    return [pricing, *overrides]


def optional_rate(tiers: Iterable[Json], *keys: str) -> Decimal | None:
    """The highest rate among keys a tier actually carries, or None when
    none of them appear. Absence is not a free rate."""
    present = [
        money(tier[key], f"pricing.{key}")
        for key in keys
        for tier in tiers
        if key in tier
    ]
    if not present:
        return None
    return max(present)


def max_rate(tiers: Iterable[Json], key: str, required: bool) -> Decimal:
    present = [(i, t[key]) for i, t in enumerate(tiers) if key in t]
    if required and not any(i == 0 for i, _ in present):
        raise PricingUnknownError(f"pricing.{key} is missing")
    return max((money(v, f"pricing.{key}") for _, v in present), default=ZERO)


def parse_model_terms(data: Json, expected_id: str) -> ModelTerms:
    model = data.get("data")
    if not isinstance(model, Mapping):
        raise PricingUnknownError("catalog response has no data object")
    if model.get("id") != expected_id:
        raise PricingUnknownError(
            f"catalog returned model {model.get('id')!r}, not {expected_id!r}"
        )
    pricing = model.get("pricing")
    if not isinstance(pricing, Mapping):
        raise PricingUnknownError("catalog entry has no pricing object")
    priced = tiers(pricing)
    prompt = max_rate(priced, "prompt", required=True)
    if prompt == ZERO:
        raise PricingUnknownError("pricing.prompt is zero")
    completion = max_rate(priced, "completion", required=True)
    if completion == ZERO:
        raise PricingUnknownError("pricing.completion is zero")
    cache_write = max(
        max_rate(priced, "input_cache_write", required=False),
        max_rate(priced, "input_cache_write_1h", required=False),
    )
    top = model.get("top_provider")
    return ModelTerms(
        model_id=expected_id,
        input_rate=max(prompt, cache_write),
        prompt_rate=prompt,
        completion_rate=completion,
        reasoning_rate=max_rate(priced, "internal_reasoning", required=False),
        request_fee=max_rate(priced, "request", required=False),
        context_length=_count(model.get("context_length"), "context_length"),
        max_completion_tokens=_count(
            top.get("max_completion_tokens") if isinstance(top, Mapping) else None,
            "top_provider.max_completion_tokens",
        ),
        cache_read_rate=optional_rate(priced, "input_cache_read"),
        cache_write_rate=optional_rate(
            priced, "input_cache_write", "input_cache_write_1h"
        ),
    )


def parse_key_status(data: Json) -> KeyStatus:
    key = data.get("data")
    if not isinstance(key, Mapping):
        raise PricingUnknownError("key status response has no data object")
    if key.get("limit") is None:
        raise PricingUnknownError("the OpenRouter key has no credit limit (unlimited)")
    return KeyStatus(
        limit=money(key.get("limit"), "key limit"),
        limit_remaining=money(key.get("limit_remaining"), "key limit_remaining"),
        usage=money(key.get("usage"), "key usage"),
        counts_byok=key.get("include_byok_in_limit") is True,
    )
