# SPDX-License-Identifier: MIT
"""A limit stop a draft and a status line can tell from a model failure.

The text names the limit, the configured value, the observed or needed
value, and the flag or environment variable that changes it. The ledger
stores the same four fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_reviewer.ports import BoundaryError

# Where an operator changes each limit. The catalog fields are not a
# setting; the text says so.
SETTINGS: dict[str, str] = {
    "reservation_usd": "--reservation-usd or ATLAS_RESERVATION_USD",
    "max_calls": "--max-calls or ATLAS_MAX_CALLS",
    "max_turns": "--max-turns or ATLAS_MAX_TURNS",
    "lens_wall_s": "--lens-wall-seconds or ATLAS_LENS_WALL_S",
    "review_wall_s": "--review-wall-seconds or ATLAS_REVIEW_WALL_S",
    "max_input_tokens": "--max-input-tokens or ATLAS_MAX_INPUT_TOKENS",
    "max_output_tokens": "--max-output-tokens or ATLAS_MAX_OUTPUT_TOKENS",
    "reasoning_max_tokens": "--reasoning-max-tokens or ATLAS_REASONING_MAX_TOKENS",
    "context_length": "the pinned endpoints' context_length",
    "max_completion_tokens": "the pinned endpoints' max_completion_tokens",
    "max_prompt_tokens": "the pinned endpoints' max_prompt_tokens",
}


@dataclass(frozen=True)
class LimitHit:
    """One limit that stopped a lens. `configured` and `observed` are
    controller text, already rendered."""

    limit: str
    configured: str
    observed: str
    setting: str

    def message(self) -> str:
        return (
            f"{self.limit} stopped the review: configured {self.configured}, "
            f"observed {self.observed}. Change it with {self.setting}."
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "limit": self.limit,
            "configured": self.configured,
            "observed": self.observed,
            "setting": self.setting,
        }


class LimitRefused(BoundaryError):
    """A per-call bound refused the request before it was sent."""

    def __init__(self, hit: LimitHit) -> None:
        super().__init__(hit.message())
        self.hit = hit


def hit(
    limit: str, configured: object, observed: object, *, bound_by: str = ""
) -> LimitHit:
    try:
        setting = SETTINGS[limit]
    except KeyError:
        raise ValueError(f"unknown limit {limit}") from None
    if bound_by:
        setting = f"{setting} (set by {bound_by})"
    return LimitHit(limit, str(configured), str(observed), setting)
