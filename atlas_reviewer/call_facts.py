# SPDX-License-Identifier: MIT
"""Token and finish facts for the model call that just returned, and the
harness-injected turn that call answers.

`tool_model._turn` records the facts. The span wrapper reads them. A
scripted model records nothing, and the span then omits the token
attributes. The facts live in a context variable so the loop's `LensModel`
return type stays `ModelTurn`. The nudge label and the timeout-retry count
are the same mechanism on the request side: `lens_loop` names the injected
turn, or counts the retry, before building the next request, and the span
wrapper consumes them, so a trace shows which completion answered a nudge
or followed a retry without exporting bodies. Both are per-context state:
`reset_events` clears them, which `run_attempt` does at every attempt start
so a follow-up that never ran cannot stain the next attempt's span.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

_FACTS: ContextVar[CallFacts | None] = ContextVar("atlas_call_facts", default=None)
_NUDGE: ContextVar[str] = ContextVar("atlas_nudge", default="")
_RETRIES: ContextVar[int] = ContextVar("atlas_timeout_retries", default=0)


@dataclass(frozen=True)
class CallFacts:
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    finish_reason: str | None = None
    limit_stop: str | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    provider: str = ""
    provider_endpoint: str = ""
    reasoning_hint: int | None = None


def note_call(facts: CallFacts) -> None:
    _FACTS.set(facts)


def take_call() -> CallFacts | None:
    facts = _FACTS.get()
    _FACTS.set(None)
    return facts


def note_nudge(label: str) -> None:
    """Name the harness-injected turn the next model call answers: one of
    `unread-files`, `no-progress`, `duplicate-calls`."""
    _NUDGE.set(label)


def take_nudge() -> str:
    label = _NUDGE.get()
    _NUDGE.set("")
    return label


def note_timeout_retry() -> None:
    """Count one timeout retry the next model call follows (review M2)."""
    _RETRIES.set(_RETRIES.get() + 1)


def take_timeout_retries() -> int:
    retries = _RETRIES.get()
    _RETRIES.set(0)
    return retries


def reset_events() -> None:
    """Clear the request-side markers. `run_attempt` calls this at every
    attempt start: a follow-up turn that was queued but never ran must not
    stain the next attempt's spans (review Minor 5)."""
    _NUDGE.set("")
    _RETRIES.set(0)
