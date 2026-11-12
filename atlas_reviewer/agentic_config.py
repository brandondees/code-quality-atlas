# SPDX-License-Identifier: MIT
"""The one place the controller and the CLI read agentic limits.

A flag wins over its environment variable, and an unset value keeps the
default. The five review limits refuse a cleared or unparseable value.
The three per-call token limits stay unset here when the operator does
not name them; `resolve_per_call` then takes them from the model. The
one-shot review does not read this: its 3 calls, $3 and 200k input cap
stay D25's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from atlas_reviewer.lens_loop import AgenticLimits

ENV = {
    "reservation_usd": "ATLAS_RESERVATION_USD",
    "max_calls": "ATLAS_MAX_CALLS",
    "max_turns": "ATLAS_MAX_TURNS",
    "lens_wall_s": "ATLAS_LENS_WALL_S",
    "review_wall_s": "ATLAS_REVIEW_WALL_S",
    "max_input_tokens": "ATLAS_MAX_INPUT_TOKENS",
    "max_output_tokens": "ATLAS_MAX_OUTPUT_TOKENS",
    "reasoning_max_tokens": "ATLAS_REASONING_MAX_TOKENS",
}


def load_agentic_limits(
    env: Mapping[str, str],
    **flags: str | None,
) -> AgenticLimits:
    """`flags` are the CLI strings, keyed by the limit name. None means
    the flag was omitted, so the environment variable is read. An empty
    variable is omitted too. `resolve` then refuses a value that is not
    a usable limit."""
    unknown = set(flags) - set(ENV)
    if unknown:
        raise ValueError("unknown agentic limit: " + ", ".join(sorted(unknown)))
    limits = AgenticLimits()
    for name, variable in ENV.items():
        raw = flags.get(name)
        if raw is None:
            raw = env.get(variable)
        if raw is None or raw == "":
            continue
        limits = _apply(limits, name, raw)
    limits.resolve()
    return limits


def _apply(limits: AgenticLimits, name: str, raw: str) -> AgenticLimits:
    if name == "reservation_usd":
        return replace(limits, reservation_usd=_amount(raw))
    if name == "max_calls":
        return replace(limits, max_calls=_positive_int(name, raw))
    if name == "max_turns":
        return replace(limits, max_turns=_positive_int(name, raw))
    if name == "lens_wall_s":
        return replace(limits, lens_wall_s=_positive_seconds(name, raw))
    if name == "review_wall_s":
        return replace(limits, review_wall_s=_positive_seconds(name, raw))
    if name == "max_input_tokens":
        return replace(limits, max_input_tokens=_positive_int(name, raw))
    if name == "max_output_tokens":
        return replace(limits, max_output_tokens=_positive_int(name, raw))
    if name == "reasoning_max_tokens":
        return replace(limits, reasoning_max_tokens=_positive_int(name, raw))
    raise ValueError(f"unknown agentic limit {name}")  # pragma: no cover


def _amount(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(
            f"reservation_usd must be a positive amount, not {raw!r}"
        ) from None


def _positive_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive integer, not {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be a positive integer, not {raw!r}")
    return value


def _positive_seconds(name: str, raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{name} must be a positive number of seconds, not {raw!r}"
        ) from None
    if value <= 0:
        raise ValueError(f"{name} must be a positive number of seconds, not {raw!r}")
    return value
