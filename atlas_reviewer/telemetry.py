# SPDX-License-Identifier: MIT
"""Lifecycle telemetry: one structured event per step of a review or probe.

Every event goes to one `EventSink` (a JSONL file in live use, nothing in
tests) and is also kept in memory for the summary table that the draft and
`probe-runner` (both later in this stack) print. Field values are numbers,
booleans or labels the controller chose. Free text (error messages, which
can quote URLs or runner output) goes through `scrub`, the controller's
redactor, before any sink sees it, so no event carries a credential; a
sink cannot be attached without one.

`span` times one step. A `BoundaryError` raised inside it is re-raised as
the same object, its message prefixed with the phase, the step, how long
the step took and how far into the run it failed, so no failure surfaces
as a bare "The read operation timed out". The innermost span labels the error; any
enclosing span records its own event but keeps that label.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from atlas_reviewer.ports import BoundaryError, Clock
from atlas_reviewer.redact import redact

FieldValue = str | int | float | bool | None
Fields = Mapping[str, FieldValue]
OK, ERROR = "ok", "error"
_LABELLED = "atlas_step_label"


@dataclass(frozen=True)
class Event:
    seq: int
    phase: str
    step: str
    status: str
    start_s: float
    duration_s: float
    fields: Fields = field(default_factory=dict)
    error: str = ""

    def as_json(self) -> dict[str, FieldValue]:
        head: dict[str, FieldValue] = {
            "seq": self.seq,
            "phase": self.phase,
            "step": self.step,
            "status": self.status,
            "start_s": self.start_s,
            "duration_s": self.duration_s,
        }
        return {**head, **self.fields, **({"error": self.error} if self.error else {})}


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class NullSink:
    def emit(self, event: Event) -> None:
        return None


class JsonlSink:
    """Appends one JSON object per line, opening and closing the file for
    each event, so a crashed or killed run still leaves every event up to
    the crash on disk."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def emit(self, event: Event) -> None:
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(event.as_json()) + "\n")


def _redact_shapes(text: str) -> str:
    return redact(text).text


def _no_fields(_result: object) -> Fields:
    return {}


class Telemetry:
    """Thread-safe: the runner watchdog destroys from its own thread.

    Writing events anywhere needs `scrub`, the controller's redactor bound
    to its own credentials. Without a sink, events stay in memory and are
    still scrubbed of secret-shaped values by pattern."""

    def __init__(
        self,
        clock: Clock,
        sink: EventSink | None = None,
        scrub: Callable[[str], str] | None = None,
    ) -> None:
        if sink is not None and scrub is None:
            raise TypeError(
                "a telemetry sink needs scrub, the controller's redactor bound "
                "to its credentials"
            )
        self._clock = clock
        self._sink = sink or NullSink()
        self._scrub = scrub or _redact_shapes
        self._start = clock.monotonic()
        self._events: list[Event] = []
        self._lock = threading.Lock()

    @property
    def sink(self) -> EventSink:
        return self._sink

    @property
    def events(self) -> tuple[Event, ...]:
        with self._lock:
            return tuple(self._events)

    def elapsed(self) -> float:
        return self._clock.monotonic() - self._start

    def scrub(self, text: str) -> str:
        """The same redaction events get, for text leaving by another way
        (a runner report's note)."""
        return self._scrub(text)

    def record(
        self,
        phase: str,
        step: str,
        fields: Fields | None = None,
        *,
        status: str = OK,
        start_s: float | None = None,
        error: str = "",
    ) -> Event:
        start = self.elapsed() if start_s is None else start_s
        duration = max(self.elapsed() - start, 0.0)
        clean = {k: self._clean(v) for k, v in (fields or {}).items()}
        with self._lock:
            event = Event(
                len(self._events) + 1,
                phase,
                step,
                status,
                round(start, 3),
                round(duration, 3),
                clean,
                self._scrub(error),
            )
            self._events.append(event)
            self._sink.emit(event)
        return event

    def span[T](
        self,
        phase: str,
        step: str,
        fn: Callable[[], T],
        fields: Fields | None = None,
        after: Callable[[T], Fields] = _no_fields,
    ) -> T:
        start = self.elapsed()
        try:
            result = fn()
        except BoundaryError as exc:
            _label(exc, phase, step, start, self.elapsed())
            self.record(
                phase, step, fields, status=ERROR, start_s=start, error=str(exc)
            )
            raise
        except Exception as exc:
            self.record(
                phase, step, fields, status=ERROR, start_s=start,
                error=f"{type(exc).__name__}: {exc}",
            )  # fmt: skip
            raise
        self.record(phase, step, {**(fields or {}), **after(result)}, start_s=start)
        return result

    def _clean(self, value: FieldValue) -> FieldValue:
        return self._scrub(value) if isinstance(value, str) else value


def _label(exc: BoundaryError, phase: str, step: str, start: float, now: float) -> None:
    """Relabels `exc` itself rather than building a copy: a copy loses the
    attributes a subclass promises (`StreamTimeoutError.received`) and
    cannot be built at all when its constructor needs more arguments."""
    if getattr(exc, _LABELLED, False):
        return
    prefix = (
        f"{phase} / {step} failed after {now - start:.1f}s ({now:.1f}s into the run): "
    )
    exc.args = (f"{prefix}{exc}",)
    setattr(exc, _LABELLED, True)


SUMMARY_HEADERS = (
    "#",
    "Phase",
    "Step",
    "Status",
    "Start (s)",
    "Duration (s)",
    "Detail",
)


def summary_rows(events: tuple[Event, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (
            str(e.seq),
            e.phase,
            e.step,
            e.status.upper() if e.status == ERROR else e.status,
            f"{e.start_s:.1f}",
            f"{e.duration_s:.1f}",
            _detail(e),
        )
        for e in events
    )


def _detail(event: Event) -> str:
    pairs = "; ".join(f"{k}={v}" for k, v in event.fields.items())
    return "; ".join(part for part in (pairs, event.error) if part)
