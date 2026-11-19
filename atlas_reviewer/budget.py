# SPDX-License-Identifier: MIT
"""Per-review model-call budget. Pure.

Every attempt -- first call or retry -- must `reserve` its worst-case cost
before it is sent. A reservation is refused if it would be call number
`max_calls + 1`, or if it would push committed spend (settled actuals,
reserved worst cases where the actual is unknown, plus this reservation)
past `budget_usd`. A failed or unparseable attempt keeps its full
reservation as spent, since it may still have been billed.

The per-tenant daily spend bounds (config slice S9, D81) live here too:
the day's committed-spend ledger and the refusal the bounds produce. The
ledger is one append-only `<state root>/spend/<owner>-<repo>-<UTC
date>.jsonl` file per repo per UTC day -- the same append-only pattern
D74's per-PR round logs use -- where the owner and repo segments are
percent-encoded with every byte outside `[A-Za-z0-9]` escaped, so two
distinct owner/repo pairs never share a file (`a-b/c` and `a/b-c` are
distinct, and the joining `-` is unambiguous because a literal `-` inside
a segment always reads `%2D`). The date in the file name makes the UTC
reset structural, and a lost file loses only the day's total. The counted
spend is what the review child's own accounting committed -- reported
token counts priced at the operator's price table -- never a
tenant-reported dollar figure.

`InputTokenMeter` bounds a growing agentic conversation's next prompt from
the last response's reported `prompt_tokens` plus the bytes of the
messages added since at one token per byte, instead of the
one-token-per-byte bound on the whole payload, which overcounts by about
2.8x on live data. The enforced input cap value
is unchanged; only the measurement of the prompt against it changed, and
the meter reports the basis every bound came from.

Worst case of one call = input tokens x highest input rate (cache write
included) + max output tokens x the highest of the completion and
reasoning rates + any per-request fee. OpenRouter's `reasoning.max_tokens`
is a hint,
not a cap: a provider can return more reasoning tokens than the hint, up
to `max_tokens`, and still bill them
(https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
A reasoning token is one of the turn's output tokens, not an addition to
them: OpenRouter's reasoning-tokens guide (fetched 2026-11-18) says to
subtract the reported reasoning count from `completion_tokens` to get
the visible tokens, and that reasoning tokens "are considered output
tokens and charged accordingly" -- on most providers they also count
against the request's output cap, and both providers the pinned routes
reach do (OpenAI's reasoning guide, fetched 2026-11-18: reasoning tokens
"are billed as output tokens" and `max_output_tokens` caps the total
"including reasoning tokens"; Anthropic's extended-thinking page,
fetched 2026-11-18: thinking tokens "count toward the `max_tokens`
limit" and `max_tokens` "remains the hard ceiling on total output"). One
token cannot be billed at two rates at once, so the per-token worst case
is the higher of the two rates, not
their sum -- the sum double-billed every reasoning token and made each
large-context call reserve about twice its output term (issue #750).
`_actual_cost` prices a reported reasoning count as the subset of the
completion count it is, and falls back to the higher rate for the whole
completion count when the count is missing, so a settle can never price
a token at more than the reservation's per-token worst case. The
reservation does not depend on the hint. The hint is still
sent.
"""

from __future__ import annotations

import json
import os
import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from atlas_reviewer.ledger import make_private_dirs
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


def estimated_input_tokens(last_prompt_tokens: int, new_bytes: int) -> int:
    """An upper bound on the next prompt's tokens when the last response
    reported its own: that reported count, plus the bytes of the messages
    added since at one token per byte, plus `MESSAGE_OVERHEAD_TOKENS` for
    the framing the raw bytes miss. One token per byte is the same
    assumption `input_token_bound` makes and no tokenizer violates -- a
    token encodes at least one byte, so the delta bound holds for dense
    content such as base64 or minified fixtures, which ordinary
    bytes-per-token ratios (the trials measured 2.47-4.50) do not cover.
    The reported baseline carries the conversation's measured cost; only
    the one turn's delta is estimated."""
    return last_prompt_tokens + new_bytes + MESSAGE_OVERHEAD_TOKENS


@dataclass
class InputTokenMeter:
    """The input-token bound of one growing model conversation, measured
    from reported usage where possible.

    The byte bound `input_token_bound` overcounts tokens by about 2.8x on
    the 2026-11-13 live-trial calls, which cut every lens off far before
    its real limit. Once a response has reported `prompt_tokens`, the
    meter bounds the next request from that count plus the bytes of the
    messages added since (`estimated_input_tokens`); the first request,
    a conversation that restarts, an unreadable or missing count, a zero
    count, and a count implausibly far below the bytes of the conversation
    it claims to price all fall back to the byte bound. `bound` returns
    the basis each bound came from, so a trace and a limit refusal can
    show it."""

    last_prompt_tokens: int | None = None
    sent_messages: int = 0

    def observe(self, prompt_tokens: int | None, sent_messages: int) -> None:
        """Record a completed request: its reported `prompt_tokens` (None
        when the response's usage was unreadable, missing, or zero -- a
        zero prompt cannot have produced a reply) and how many messages
        that request carried."""
        usable = (
            isinstance(prompt_tokens, int)
            and not isinstance(prompt_tokens, bool)
            and prompt_tokens > 0
        )
        self.last_prompt_tokens = prompt_tokens if usable else None
        self.sent_messages = sent_messages

    def reset(self) -> None:
        """Forget the baseline: the next bound is the byte bound."""
        self.last_prompt_tokens = None
        self.sent_messages = 0

    def bound(
        self, whole_bytes: int, prefix_bytes: int, messages: int
    ) -> tuple[int, str]:
        """The next request's input-token bound and the basis it came from.

        `whole_bytes` is the request serialized whole; `prefix_bytes` the
        same serialization of its first `sent_messages` messages, the
        conversation the last reported response already priced. Their
        difference is what the messages added since weigh. `messages` is
        the request's message count, so a restarted conversation is
        visible. A reported count below an eighth of the prefix's bytes is
        implausible -- the trials' densest prompt was 2.47 bytes per token,
        so under one token per eight bytes is not a tokenizer, it is a
        provider miscount -- and falls back to the byte bound. The basis
        text is controller text for the ledger and the trace."""
        baseline = self.last_prompt_tokens
        if (
            baseline is None
            or messages < self.sent_messages
            or baseline * 8 < prefix_bytes
        ):
            why = (
                "no reported usage yet"
                if baseline is None
                else "the conversation restarted"
                if messages < self.sent_messages
                else "the reported count is implausibly low for the bytes it priced"
            )
            return (
                whole_bytes + MESSAGE_OVERHEAD_TOKENS,
                f"bytes {whole_bytes} + overhead {MESSAGE_OVERHEAD_TOKENS} ({why})",
            )
        new_bytes = max(whole_bytes - prefix_bytes, 0)
        bound = estimated_input_tokens(baseline, new_bytes)
        note = (
            f"usage {baseline} + {new_bytes} new bytes at 1 token per byte "
            f"+ overhead {MESSAGE_OVERHEAD_TOKENS} = {bound}"
        )
        return bound, note


def prompt_token_room(
    limits: CallLimits, context_tokens: int = ASSUMED_CONTEXT_TOKENS
) -> int:
    """The largest prompt bound `check_tokens` accepts under `limits` on a
    model with `context_tokens` of context. The controller sizes diff parts
    against it; `check_tokens` still runs on every call against the catalog's
    own `context_length`."""
    return min(limits.max_input_tokens, context_tokens - limits.max_output_tokens)


def check_tokens(input_tokens: int, terms: ModelTerms, limits: TokenLimits) -> None:
    if (
        terms.max_prompt_tokens is not None
        and terms.max_prompt_tokens < limits.max_input_tokens
        and input_tokens > terms.max_prompt_tokens
    ):
        who = f" (set by {terms.prompt_limit_tags})" if terms.prompt_limit_tags else ""
        raise TokenBoundError(
            f"prompt bound {input_tokens} tokens exceeds the pinned endpoint's "
            f"{terms.max_prompt_tokens}-token max_prompt_tokens{who}",
            limit="max_prompt_tokens",
            configured=terms.max_prompt_tokens,
            observed=input_tokens,
        )
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
    """A cost that stays at least what `_actual_cost` would compute for
    any split of the turn's output between completion and reasoning
    tokens. Independent of
    `reasoning_max_tokens`: that field is only the hint sent on the request.

    The output term prices each output token at the higher of the
    completion and reasoning rates, not at their sum: a token is billed
    once, at whichever of the two rates applies to it, and the reported
    reasoning count sits inside the completion count on the providers
    whose usage OpenRouter normalizes (issue #750)."""
    output_rate = max(terms.completion_rate, terms.reasoning_rate)
    return (
        input_tokens * terms.input_rate
        + limits.max_output_tokens * output_rate
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
        if (
            isinstance(actual, Decimal)
            and actual.is_finite()
            and actual > record.reserved_usd
        ):
            # D82's tripwire (round-1 review of #757): the reported cost
            # came in above the worst case the reservation priced. The
            # accounting moves committed spend to the reported actual --
            # which can sit above the reservation -- and the note makes
            # the overrun visible in the usage report.
            record.usage = (record.usage + " " if record.usage else "") + (
                f"(settled ${actual:.4f} above its "
                f"${record.reserved_usd:.4f} reservation; D82's tripwire)"
            )

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


# --- The per-tenant daily spend bounds (config slice S9, D81) -------------

ENV_REPO_DAILY_BUDGET_USD = "ATLAS_REPO_DAILY_BUDGET_USD"
# The decided value (2026-11-18, 5:13 PM CT): $100 per repo per UTC day.
DEFAULT_REPO_DAILY_BUDGET_USD = Decimal("100.00")
# The fixed refusal texts. Plain, controller-made, and carrying nothing
# from the payload or the config: the record says what happened and never
# reads as a clean review.
BUDGET_REACHED = "skipped: daily budget reached"
CAP_REACHED = "skipped: installation daily cap reached"
# The fixed telemetry reason label, the way S4's skips carry theirs.
SKIP_BUDGET_REASON = "daily-budget"

InstallationCap = Callable[[str], "Decimal | None"]
"""The installation's daily cap (config slice S9/S10): an installation id
in, the cap in dollars, or None when no cap is set -- and no cap set means
none applies, the per-repo daily budgets remaining the bound. The store
side is S10's installation store; until it lands, production wires
`no_installation_cap`."""


def no_installation_cap(installation: str) -> Decimal | None:
    """The S9 production cap provider: until S10's installation store
    lands, no installation has a cap, so none applies."""
    del installation
    return None


def repo_daily_budget_usd(env: Mapping[str, str]) -> Decimal:
    """The operator's per-repo daily budget, `ATLAS_REPO_DAILY_BUDGET_USD`
    (S9): the decided $100 default when unset, and a `ValueError` naming
    the variable when a set value is not a positive dollar amount -- an
    operator setting that is unusable stops the deployment, the way the
    other operator variables' loaders do, instead of silently unbounding
    or zeroing every repo's day."""
    raw = env.get(ENV_REPO_DAILY_BUDGET_USD)
    if raw is None or raw == "":
        return DEFAULT_REPO_DAILY_BUDGET_USD
    try:
        value = Decimal(raw)
    except ArithmeticError:
        raise ValueError(
            f"{ENV_REPO_DAILY_BUDGET_USD} must be a positive dollar amount, not {raw!r}"
        ) from None
    if not value.is_finite() or value <= 0:
        raise ValueError(
            f"{ENV_REPO_DAILY_BUDGET_USD} must be a positive dollar amount, not {raw!r}"
        )
    return value


_ALLOWED_SEGMENT_BYTES = frozenset(
    (string.ascii_letters + string.digits).encode("ascii")
)


def spend_segment(raw: str) -> str:
    """One owner or repo name flattened into a file-name segment: every
    byte outside `[A-Za-z0-9]` percent-encoded, uppercase hex. A literal
    `-` inside a segment always reads `%2D`, so the single `-` that joins
    the owner, repo and date parts is unambiguous and two distinct
    owner/repo pairs can never share a file (`a-b/c` and `a/b-c` are
    distinct files; `%` itself reads `%25`, so the encoding is injective)."""
    return "".join(
        chr(byte) if byte in _ALLOWED_SEGMENT_BYTES else f"%{byte:02X}"
        for byte in raw.encode("utf-8")
    )


def spend_file(state_root: Path, repo: str, day: date) -> Path:
    """The day's spend file for one repository:
    `<state root>/spend/<owner>-<repo>-<UTC date>.jsonl`, append-only, one
    file per repo per UTC day -- the date in the name makes the UTC reset
    structural, and a lost file loses only that day's total."""
    owner, _, name = repo.partition("/")
    stem = f"{spend_segment(owner)}-{spend_segment(name)}-{day.isoformat()}"
    return state_root / "spend" / f"{stem}.jsonl"


def _utc_today() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True)
class DailySpend:
    """The day's committed-spend ledger and the per-tenant bounds read
    against it (config slice S9, D81).

    The ledger is the state volume's append-only per-repo-per-day JSONL
    file (`spend_file`); each record is one settled review's committed
    spend, the figure the review child's own accounting committed --
    reported token counts priced at the operator's price table -- never a
    tenant-reported dollar figure. `committed` reads the day's total; an
    unreadable record returns an unknown total with the gap that says so,
    and an unknown total refuses: a spend file this service cannot read
    must never open the budget. `refusal` applies the two bounds -- the
    per-repo daily budget and, when one is set, the installation's daily
    cap; the stricter of the two wins each check, and an unset cap means
    none applies. The check-then-act race between `refusal` and the next
    `record` is named and bounded (D81): two concurrent deliveries for
    one repo can both pass before either commits, so the overshoot past
    the day's budget is at most the in-flight reviews times each one's
    per-review ceiling -- at the decided values 32 in-flight reviews x the
    $25 operator max = $800 past a $100 budget -- and no per-repo lock is
    taken."""

    state_root: Path
    daily_budget_usd: Decimal = DEFAULT_REPO_DAILY_BUDGET_USD
    cap_for: InstallationCap = no_installation_cap
    today: Callable[[], date] = field(default_factory=lambda: _utc_today)

    def __post_init__(self) -> None:
        if self.daily_budget_usd <= 0:
            raise ValueError("the daily budget must be positive")

    def file(self, repo: str) -> Path:
        return spend_file(self.state_root, repo, self.today())

    def committed(self, repo: str) -> tuple[Decimal | None, str]:
        """The day's committed spend for one repository, as
        `(total, gap)`. No file reads as zero -- a lost file loses only
        the day's total (D81's stated degradation). A file this module
        cannot parse returns `(None, gap)`: the caller refuses, so a
        ledger this service cannot read never opens the budget."""
        try:
            text = self.file(repo).read_text(encoding="utf-8")
        except FileNotFoundError:
            return Decimal(0), ""
        except OSError as exc:
            return None, f"the day's spend file could not be read: {exc}"
        total = Decimal(0)
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            amount = _record_amount(line)
            if amount is None:
                return None, (
                    "the day's spend file has an unreadable record (line "
                    f"{number}), so the day's total is unknown and the "
                    "budget holds until the file is repaired"
                )
            total += amount
        return total, ""

    def record(
        self,
        repo: str,
        amount_usd: Decimal,
        calls: int,
        *,
        at: datetime | None = None,
    ) -> None:
        """Append one settled review's committed spend to the day's file.
        One `os.write` of one line under `O_APPEND` is the append; a
        write that raises leaves the file as it was and the caller names
        the gap."""
        if amount_usd < 0:
            raise ValueError("a settled spend cannot be negative")
        self._append(
            repo,
            {
                "recorded_at": (
                    at if at is not None else datetime.now(UTC)
                ).isoformat(),
                "calls": calls,
                "committed_usd": str(amount_usd),
            },
        )

    def record_once(
        self,
        repo: str,
        amount_usd: Decimal,
        calls: int,
        key: str,
        *,
        at: datetime | None = None,
    ) -> tuple[bool, str]:
        """Append one attempt's committed spend to the day's file **once
        per key**, as `(appended, gap)`.

        The key is the caller's identity for one attempt's spend -- for
        the crash backfill, the progress evidence's content hash. A key
        already present in the day's file is not appended again, so a
        recovery that runs twice against the same crashed attempt adds
        nothing, while a different attempt's evidence hashes differently
        and is recorded on its own; the dedupe lives in the ledger
        itself, so no crash between an append and a bookkeeping step can
        double-count. An unreadable ledger is not appended to -- its
        total is unknown and the refusal already holds -- and the gap is
        returned so the caller can name it."""
        if not key:
            raise ValueError("a once-only record needs a key")
        if amount_usd < 0:
            raise ValueError("a settled spend cannot be negative")
        total, gap = self.committed(repo)
        if total is None:
            return False, gap
        if self._has_key(repo, key):
            return False, ""
        self._append(
            repo,
            {
                "recorded_at": (
                    at if at is not None else datetime.now(UTC)
                ).isoformat(),
                "calls": calls,
                "committed_usd": str(amount_usd),
                "key": key,
            },
        )
        return True, ""

    def _has_key(self, repo: str, key: str) -> bool:
        """True when some record in the day's file already carries
        `key`. Lines that do not parse are skipped, not fatal: they are
        the unreadable-record case `committed` refuses on, and a
        half-written line cannot hide a key this module wrote whole."""
        try:
            text = self.file(repo).read_text(encoding="utf-8")
        except OSError:
            return False
        for line in text.splitlines():
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                continue
            if isinstance(data, dict) and data.get("key") == key:
                return True
        return False

    def _append(self, repo: str, record: dict[str, str | int]) -> None:
        """Write one ledger line: the whole line in one `os.write` under
        `O_APPEND`, and a partial write -- a short count is possible on
        a signal -- is written to completion before the file is closed,
        so a truncated line (which `committed` would fail closed on)
        cannot be left behind."""
        if int(record["calls"]) < 0:
            raise ValueError("a call count cannot be negative")
        path = self.file(repo)
        make_private_dirs(path.parent)
        data = (json.dumps(record) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
        finally:
            os.close(fd)

    def refusal(self, repo: str, installation: str) -> tuple[str, str]:
        """The bounds' refusal for one admission, as `(message, gap)`.

        An empty message means the delivery may proceed. The message is
        the plain refusal text -- `BUDGET_REACHED` or `CAP_REACHED` --
        never payload or config text; the gap, non-empty when the day's
        total was unreadable, names the ledger failure behind a
        fail-closed refusal. The per-repo daily budget and the
        installation's daily cap are each spent when the day's committed
        total has reached them, and the stricter of the two governs: a
        refusal on either refuses, and an unset cap (`cap_for` returns
        None) means none applies."""
        total, gap = self.committed(repo)
        if total is None:
            return BUDGET_REACHED, gap
        if total >= self.daily_budget_usd:
            return BUDGET_REACHED, ""
        cap = self.cap_for(installation)
        if cap is not None and total >= cap:
            return CAP_REACHED, ""
        return "", ""


def _record_amount(line: str) -> Decimal | None:
    """The `committed_usd` figure of one ledger line, or None when the
    line is not a record this module wrote: not JSON, not an object, the
    field missing or not a non-negative decimal string."""
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("committed_usd")
    if not isinstance(raw, str):
        return None
    try:
        amount = Decimal(raw)
    except ArithmeticError:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount
