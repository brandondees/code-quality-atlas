# SPDX-License-Identifier: MIT
"""Token and finish facts for the model call that just returned.

`tool_model._turn` records them. The span wrapper reads them. A scripted
model records nothing, and the span then omits the token attributes.
The facts live in a context variable so the loop's `LensModel` return
type stays `ModelTurn`.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

_FACTS: ContextVar[CallFacts | None] = ContextVar("atlas_call_facts", default=None)


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


def note_call(facts: CallFacts) -> None:
    _FACTS.set(facts)


def take_call() -> CallFacts | None:
    facts = _FACTS.get()
    _FACTS.set(None)
    return facts
