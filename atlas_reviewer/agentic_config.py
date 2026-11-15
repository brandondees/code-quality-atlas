# SPDX-License-Identifier: MIT
"""The one place the controller and the CLI read agentic limits.

A flag wins over its environment variable, and an unset value keeps the
default. The five review limits refuse a cleared or unparseable value.
The three per-call token limits stay unset here when the operator does
not name them; `resolve_per_call` then takes them from the model.
`diff_prefix_share` (D65) is the share of the model's input room the
shared diff prefix may take; 0 turns the shared prefix off. The
quote-repair bound and the quote-checker window (D64) are bounded here
too: `ATLAS_QUOTE_REPAIRS` is 0 to 3 repair turns per attempt, and
`ATLAS_QUOTE_TOLERANCE` is the window in lines, 0 to 8. The
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
    "no_progress_turns": "ATLAS_NO_PROGRESS_TURNS",
    "duplicate_calls": "ATLAS_DUPLICATE_CALLS",
    "quote_repairs": "ATLAS_QUOTE_REPAIRS",
    "quote_tolerance": "ATLAS_QUOTE_TOLERANCE",
    "max_input_tokens": "ATLAS_MAX_INPUT_TOKENS",
    "max_output_tokens": "ATLAS_MAX_OUTPUT_TOKENS",
    "reasoning_max_tokens": "ATLAS_REASONING_MAX_TOKENS",
    "pool_size": "ATLAS_POOL_SIZE",
    "diff_prefix_share": "ATLAS_DIFF_PREFIX_SHARE",
    "create_retries": "ATLAS_CREATE_RETRIES",
    "create_concurrency": "ATLAS_CREATE_CONCURRENCY",
}


def load_agentic_limits(
    env: Mapping[str, str],
    **flags: str | None,
) -> AgenticLimits:
    """`flags` are the CLI strings, keyed by the limit name. None means
    the flag was omitted, so the environment variable is read. An empty
    flag is a value and is refused, so it cannot fall through to the
    variable. An empty variable is still omitted. `resolve` then refuses
    a value that is not a usable limit."""
    unknown = set(flags) - set(ENV)
    if unknown:
        raise ValueError("unknown agentic limit: " + ", ".join(sorted(unknown)))
    limits = AgenticLimits()
    for name, variable in ENV.items():
        if name in flags:
            raw = flags[name]
            if raw is None:
                raw = env.get(variable)
            elif raw == "":
                raise ValueError(f"{name} was given an empty value")
        else:
            raw = env.get(variable)
        if raw is None or raw == "":
            continue
        limits = _apply(limits, name, raw)
    limits.resolve()
    return limits


def _apply(limits: AgenticLimits, name: str, raw: str) -> AgenticLimits:
    if name == "reservation_usd":
        return replace(limits, reservation_usd=_amount(raw))
    applied = _apply_positive_int(limits, name, raw)
    if applied is not None:
        return applied
    if name == "lens_wall_s":
        return replace(limits, lens_wall_s=_positive_seconds(name, raw))
    if name == "review_wall_s":
        return replace(limits, review_wall_s=_positive_seconds(name, raw))
    if name == "quote_repairs":
        return replace(limits, quote_repairs=_bounded_int(name, raw, 3))
    if name == "quote_tolerance":
        return replace(limits, quote_tolerance=_bounded_int(name, raw, 8))
    if name == "create_retries":
        return replace(limits, create_retries=_int_in_range(name, raw, 0, 24))
    if name == "create_concurrency":
        return replace(limits, create_concurrency=_int_in_range(name, raw, 1, 64))
    if name == "diff_prefix_share":
        return replace(limits, diff_prefix_share=_share(raw))
    raise ValueError(f"unknown agentic limit {name}")  # pragma: no cover


def _apply_positive_int(
    limits: AgenticLimits, name: str, raw: str
) -> AgenticLimits | None:
    """The plain positive-integer limits, applied; None for any other
    name. Split from `_apply` so each stays under the complexity gate."""
    if name == "max_calls":
        return replace(limits, max_calls=_positive_int(name, raw))
    if name == "max_turns":
        return replace(limits, max_turns=_positive_int(name, raw))
    if name == "no_progress_turns":
        return replace(limits, no_progress_turns=_positive_int(name, raw))
    if name == "duplicate_calls":
        return replace(limits, duplicate_calls=_positive_int(name, raw))
    if name == "max_input_tokens":
        return replace(limits, max_input_tokens=_positive_int(name, raw))
    if name == "max_output_tokens":
        return replace(limits, max_output_tokens=_positive_int(name, raw))
    if name == "reasoning_max_tokens":
        return replace(limits, reasoning_max_tokens=_positive_int(name, raw))
    if name == "pool_size":
        return replace(limits, pool_size=_positive_int(name, raw))
    return None


def _amount(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(
            f"reservation_usd must be a positive amount, not {raw!r}"
        ) from None


def _positive_int(name: str, raw: str) -> int:
    return _int_in_range(name, raw, 1, None)


def _int_in_range(name: str, raw: str, low: int, high: int | None) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, not {raw!r}") from None
    if value < low or (high is not None and value > high):
        span = f"from {low} to {high}" if high is not None else f"of at least {low}"
        raise ValueError(f"{name} must be an integer {span}, not {raw!r}")
    return value


def _bounded_int(name: str, raw: str, hi: int) -> int:
    """A non-negative integer at most `hi` (D64): 0 disables the guard it
    bounds, and a value past `hi` is the runaway the guard exists to
    prevent."""
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"{name} must be an integer from 0 to {hi}, not {raw!r}"
        ) from None
    if not 0 <= value <= hi:
        raise ValueError(f"{name} must be an integer from 0 to {hi}, not {raw!r}")
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


def _share(raw: str) -> float:
    """The shared diff prefix's share of the model's input room. 0 turns
    the shared prefix off; anything above 1 cannot leave room for the
    lens's work."""
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"diff_prefix_share must be a number from 0 to 1, not {raw!r}"
        ) from None
    if not 0 <= value <= 1:
        raise ValueError(f"diff_prefix_share must be a number from 0 to 1, not {raw!r}")
    return value
