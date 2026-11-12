# SPDX-License-Identifier: MIT
"""Per-review model-call budget. Pure.

Every attempt -- first call or retry -- must `reserve` its worst-case cost
before it is sent. A reservation is refused if it would be call number
`max_calls + 1`, or if it would push committed spend (settled actuals,
reserved worst cases where the actual is unknown, plus this reservation)
past `budget_usd`. A failed or unparseable attempt keeps its full
reservation as spent, since it may still have been billed.

Worst case of one call = input tokens x highest input rate (cache write
included) + max output tokens x (completion rate + any separate reasoning
rate) + any per-request fee. OpenRouter's `reasoning.max_tokens` is a hint,
not a cap: a provider can return more reasoning tokens than the hint, up
to `max_tokens`, and still bill them
(https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
`_actual_cost` prices completion tokens at the completion rate and
reasoning tokens at the reasoning rate, and both counts can be as large
as the output cap. The reservation prices the whole output cap at the
sum of those rates, so it does not depend on the hint. The hint is still
sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.pricing import ModelTerms


class TokenLimits(Protocol):
    """The three per-call token fields `check_tokens` and `worst_case_usd` read.

    Read-only, so a frozen limit object satisfies it."""

    @property
    def max_input_tokens(self) -> int: ...

    @property
    def max_output_tokens(self) -> int: ...

    @property
    def reasoning_max_tokens(self) -> int: ...


MESSAGE_OVERHEAD_TOKENS = 64
# The pinned model's context window as the operator states it (Sonnet,
# 200k tokens). Planning with it is stricter than a catalog that reports more.
ASSUMED_CONTEXT_TOKENS = 200_000


class BudgetRefusedError(BoundaryError):
    """A model call was refused before sending: call cap, cost cap, or a
    token bound the model cannot honour."""


class TokenBoundError(BudgetRefusedError):
    """A prompt, output or context bound. `limit` is the field that bound
    it; the message stays the one-shot text those callers already match."""

    def __init__(
        self, message: str, *, limit: str, configured: object, observed: object
    ) -> None:
        super().__init__(message)
        self.limit = limit
        self.configured = configured
        self.observed = observed


# D25's hard ceilings: a caller may tighten them, never loosen them.
MAX_CALLS_CEILING = 3
BUDGET_CEILING_USD = Decimal("3.00")


@dataclass(frozen=True)
class CallLimits:
    max_calls: int = MAX_CALLS_CEILING
    max_input_tokens: int = 200_000
    max_output_tokens: int = 24_000
    reasoning_max_tokens: int = 12_000
    budget_usd: Decimal = BUDGET_CEILING_USD

    def __post_init__(self) -> None:
        if min(self.max_calls, self.max_input_tokens, self.reasoning_max_tokens) < 1:
            raise ValueError("call limits must be positive")
        if self.max_output_tokens <= self.reasoning_max_tokens:
            raise ValueError("max_output_tokens must exceed the reasoning budget")
        if self.budget_usd <= 0:
            raise ValueError("budget must be positive")
        if self.max_calls > MAX_CALLS_CEILING:
            raise ValueError(f"at most {MAX_CALLS_CEILING} model calls per review")
        if self.budget_usd > BUDGET_CEILING_USD:
            raise ValueError(f"budget is capped at ${BUDGET_CEILING_USD}")


def input_token_bound(text: str) -> int:
    """Upper bound on prompt tokens, assuming no token encodes less than one
    UTF-8 byte (true of byte-level BPE tokenizers; not verified against the
    model's own tokenizer). The response's reported usage is recorded so a
    violated assumption is visible."""
    return len(text.encode("utf-8")) + MESSAGE_OVERHEAD_TOKENS


def prompt_token_room(
    limits: CallLimits, context_tokens: int = ASSUMED_CONTEXT_TOKENS
) -> int:
    """The largest prompt bound `check_tokens` accepts under `limits` on a
    model with `context_tokens` of context. The controller sizes diff parts
    against it; `check_tokens` still runs on every call against the catalog's
    own `context_length`."""
    return min(limits.max_input_tokens, context_tokens - limits.max_output_tokens)


def check_tokens(input_tokens: int, terms: ModelTerms, limits: TokenLimits) -> None:
    if input_tokens > limits.max_input_tokens:
        raise TokenBoundError(
            f"prompt bound {input_tokens} tokens exceeds the "
            f"{limits.max_input_tokens}-token input cap",
            limit="max_input_tokens",
            configured=limits.max_input_tokens,
            observed=input_tokens,
        )
    if limits.max_output_tokens > terms.max_completion_tokens:
        raise TokenBoundError(
            f"max output {limits.max_output_tokens} exceeds the model's "
            f"{terms.max_completion_tokens}-token completion limit",
            limit="max_output_tokens",
            configured=limits.max_output_tokens,
            observed=terms.max_completion_tokens,
        )
    if input_tokens + limits.max_output_tokens > terms.context_length:
        raise TokenBoundError(
            f"prompt bound plus max output exceeds the {terms.context_length}-token context",
            limit="context_length",
            configured=terms.context_length,
            observed=input_tokens + limits.max_output_tokens,
        )


def worst_case_usd(
    input_tokens: int, terms: ModelTerms, limits: TokenLimits
) -> Decimal:
    """A cost that stays at least what `_actual_cost` would compute if every
    output token were also a reasoning token. Independent of
    `reasoning_max_tokens`: that field is only the hint sent on the request."""
    return (
        input_tokens * terms.input_rate
        + limits.max_output_tokens * (terms.completion_rate + terms.reasoning_rate)
        + terms.request_fee
    )


@dataclass
class CallRecord:
    reserved_usd: Decimal
    actual_usd: Decimal | None = None
    outcome: str = "in flight"
    usage: str = ""

    @property
    def committed_usd(self) -> Decimal:
        return self.reserved_usd if self.actual_usd is None else self.actual_usd


@dataclass
class ReviewBudget:
    limits: CallLimits = field(default_factory=CallLimits)
    calls: list[CallRecord] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    def committed_usd(self) -> Decimal:
        return sum((c.committed_usd for c in self.calls), Decimal(0))

    def reserve(
        self, worst_case: Decimal, ceiling_usd: Decimal | None = None
    ) -> CallRecord:
        """`ceiling_usd` lowers the cap for this reservation (e.g. to the
        key's remaining credit); it never raises it."""
        refusal = self._refusal(worst_case, ceiling_usd)
        if refusal:
            self.refusals.append(refusal)
            raise BudgetRefusedError(refusal)
        record = CallRecord(worst_case)
        self.calls.append(record)
        return record

    def _refusal(self, worst_case: Decimal, ceiling_usd: Decimal | None) -> str | None:
        if len(self.calls) >= self.limits.max_calls:
            return f"call cap reached: {self.limits.max_calls} model calls per review, retries included"
        cap = (
            self.limits.budget_usd
            if ceiling_usd is None
            else min(ceiling_usd, self.limits.budget_usd)
        )
        projected = self.committed_usd() + worst_case
        if projected > cap:
            return (
                f"cost cap: worst case ${worst_case:.4f} would bring this review to "
                f"${projected:.4f}, over ${cap:.2f}"
            )
        return None

    @staticmethod
    def settle(
        record: CallRecord, outcome: str, actual: Decimal | None = None, usage: str = ""
    ) -> None:
        record.outcome, record.actual_usd, record.usage = outcome, actual, usage

    def report(self) -> tuple[str, ...]:
        lines = [
            f"call {i}: {c.outcome}; reserved ${c.reserved_usd:.4f}; "
            + (
                f"actual ${c.actual_usd:.4f}"
                if c.actual_usd is not None
                else "actual unknown (counted at the reservation)"
            )
            + (f"; {c.usage}" if c.usage else "")
            for i, c in enumerate(self.calls, 1)
        ]
        lines.extend(f"refused: {r}" for r in self.refusals)
        lines.append(
            f"committed ${self.committed_usd():.4f} of ${self.limits.budget_usd:.2f}; "
            f"{len(self.calls)} of {self.limits.max_calls} calls used"
        )
        return tuple(lines)
