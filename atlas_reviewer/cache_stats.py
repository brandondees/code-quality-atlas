# SPDX-License-Identifier: MIT
"""Per-session prompt-cache accounting from a model's reported usage.

The agentic loop's turns grow one conversation, so a turn's prompt
extends the previous turn's prompt and an endpoint that kept the
session's prompt cache serves most of the turn from it. When the route
spreads a conversation across endpoints, each endpoint keeps its own
cache, and a turn pays to write what an earlier turn already wrote
(issue #695). The diagnostic a run needs is therefore per session: how
many turns failed to read the previous turn's prompt from cache, and
how much each session wrote against the context it ended with. With
working prefix caching the total cache writes sit close to the total
final context; a sum of writes well above it, or many missed turns,
says the route is still spreading.

A *session* is one conversation: the turns between one system prompt
and the next. A turn is a cache *hit* when the response reports at
least as many cached prompt tokens as the previous turn's prompt
tokens carried; anything else is a *miss*, including a turn whose
response reports no cache counts at all, because the run cannot show
it hit. The first turn of a session has no previous turn to hit and is
never a miss.

The numbers are whatever the model reported. A turn with no reported
prompt tokens contributes nothing to the final-context figure, and a
session whose turns report no cache counts shows its misses as all of
its turns after the first. `OpenRouterLensModel` feeds this tracker;
the tracker itself is model-agnostic, and any other model
implementation that reads the same usage fields can use it unchanged.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class CacheTurn:
    """One turn's reported prompt usage. `None` is unreported."""

    prompt_tokens: int | None
    cached_tokens: int | None
    cache_write_tokens: int | None


@dataclass(frozen=True)
class CacheSession:
    """One conversation's turns, labeled by the session opener."""

    label: str
    turns: tuple[CacheTurn, ...]

    @property
    def misses(self) -> int:
        """Turns that did not read the previous turn's prompt from cache.

        A turn whose cache read is unreported counts as a miss, as does
        one whose previous turn reported no prompt count to compare
        against."""
        return sum(1 for _ in _missed_pairs(self.turns))

    @property
    def cache_write_tokens(self) -> int:
        """The sum of the reported cache-write counts. Unreported writes
        add nothing, so this is a floor."""
        return sum(turn.cache_write_tokens or 0 for turn in self.turns)

    @property
    def final_prompt_tokens(self) -> int | None:
        """The session's last reported prompt count: the context the
        session ended with. None when no turn reported one."""
        for turn in reversed(self.turns):
            if turn.prompt_tokens is not None:
                return turn.prompt_tokens
        return None


def _missed_pairs(
    turns: tuple[CacheTurn, ...],
) -> Iterator[tuple[CacheTurn, CacheTurn]]:
    """The (previous, turn) pairs that are cache misses."""
    for previous, turn in pairwise(turns):
        if (
            turn.cached_tokens is None
            or previous.prompt_tokens is None
            or turn.cached_tokens < previous.prompt_tokens
        ):
            yield previous, turn


class CacheLedger:
    """The sessions one model conversation stream produced.

    Thread-safe: a pooled review runs one lens per thread, and the
    thread that observes a session is the one that opened it, so each
    session's turns arrive from one thread even when several lenses run
    at once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed: list[CacheSession] = []
        self._open: list[CacheTurn] = []
        self._label = ""
        self._started = False

    def start_session(self, label: str = "") -> None:
        """Close any open session and open a new one under `label`."""
        with self._lock:
            self._close_locked()
            self._label = label
            self._started = True

    def observe(
        self,
        prompt_tokens: int | None,
        cached_tokens: int | None,
        cache_write_tokens: int | None,
    ) -> None:
        """Record one turn's reported usage. An observation with no open
        session opens an unlabeled one, so a caller that never names a
        session still reports."""
        with self._lock:
            if not self._started:
                self._label = ""
                self._started = True
            self._open.append(
                CacheTurn(prompt_tokens, cached_tokens, cache_write_tokens)
            )

    def sessions(self) -> tuple[CacheSession, ...]:
        """Every session so far, in order, with the open one closed.

        End-of-run reading: the call closes the open session, so a read
        mid-run would split the conversation still running, and a later
        turn would open an unlabeled session after it. `OpenRouterLensModel`
        reads it once, when the review's draft is rendered."""
        with self._lock:
            self._close_locked()
            return tuple(self._closed)

    def _close_locked(self) -> None:
        if self._open:
            self._closed.append(CacheSession(self._label or "", tuple(self._open)))
        self._open = []
        self._label = ""
        self._started = False


def by_label(sessions: Iterable[CacheSession]) -> tuple[CacheSession, ...]:
    """Sessions ordered by label, stable: a pooled review creates its
    adapters in the pool's scheduling order, so the summary orders them
    by the lens each session's system prompt named, and same-label
    sessions — one lens's attempts, in run order — keep their relative
    order."""
    return tuple(sorted(sessions, key=lambda session: session.label))


def session_lines(
    sessions: Iterable[CacheSession],
    *,
    label_of: Callable[[CacheSession, int], str] | None = None,
) -> tuple[str, ...]:
    """The run summary's lines for these sessions: one per session, then
    the run total that the #695 confirmation check reads — the total
    cache writes sit against the total final context, and the missed
    turns should be near zero.

    `label_of` names a session from itself and its 1-based position; the
    default names each `session <n>`. A renderer that quotes untrusted
    text passes its own, so the summary and the draft share one
    formatting rule.
    """
    every = tuple(sessions)
    name = label_of if label_of is not None else _default_label
    lines = [
        f"{name(session, number)}: {_session_text(session)}"
        for number, session in enumerate(every, 1)
    ]
    if len(lines) > 1:
        lines.append(f"total: {_total_text(every)}")
    return tuple(lines)


def _default_label(session: CacheSession, number: int) -> str:
    return (
        f"session {number}"
        if not session.label
        else f"session {number} ({session.label})"
    )


def _session_text(session: CacheSession) -> str:
    return (
        f"{len(session.turns)} turn(s), {session.misses} cache miss(es), "
        f"{session.cache_write_tokens} cache-write token(s), final context "
        f"{_counted(session.final_prompt_tokens)}."
    )


def _total_text(sessions: tuple[CacheSession, ...]) -> str:
    """The run total the #695 confirmation check reads: the sum of the
    cache writes against the sum of the sessions' final contexts. The
    misses are the sessions' own — a session's first turn never counts
    against the previous session's last turn."""
    finals = [
        session.final_prompt_tokens
        for session in sessions
        if session.final_prompt_tokens is not None
    ]
    context = f"{sum(finals)} token(s)" if finals else "no reported tokens"
    return (
        f"{sum(len(session.turns) for session in sessions)} turn(s), "
        f"{sum(session.misses for session in sessions)} cache miss(es), "
        f"{sum(session.cache_write_tokens for session in sessions)} cache-write "
        f"token(s) against {context} of final context."
    )


def _counted(tokens: int | None) -> str:
    return "no reported tokens" if tokens is None else f"{tokens} token(s)"


__all__ = ["CacheLedger", "CacheSession", "CacheTurn", "by_label", "session_lines"]
