# SPDX-License-Identifier: MIT
"""OpenTelemetry spans for one agentic review, in OpenInference's shape.

Export is off unless ``ATLAS_OTEL_ENDPOINT`` is set. The endpoint is the
OTLP HTTP base (``https://host:6006``) or the traces URL
(``https://host:6006/v1/traces``). Loopback may use
``http://127.0.0.1:6006``. The installed
``opentelemetry-exporter-otlp-proto-http`` 1.45.2 treats the ``endpoint``
argument as the full traces URL and does not append ``/v1/traces``, so
this module appends that path when the URL has none.
``ATLAS_OTEL_HEADERS`` is ``name=value`` pairs separated by commas, the
same shape as ``OTEL_EXPORTER_OTLP_HEADERS``. It is handed to the
exporter and is not stored on the trace object. Prompt and completion
bodies are span attributes only when ``ATLAS_OTEL_EXPORT_BODIES`` is
``1``. Every string attribute goes through ``scrub`` first.

The existing JSONL telemetry is a separate sink and is not changed here.

Attribute names are the OpenInference semantic conventions
(https://arize-ai.github.io/openinference/spec/semantic_conventions.html):
``openinference.span.kind``, ``session.id``, ``metadata``, ``agent.name``,
``llm.model_name``, ``llm.token_count.*``, ``llm.token_count.prompt_details.cache_read``,
``llm.token_count.prompt_details.cache_write``, ``llm.provider``,
``llm.cost.total``, ``llm.finish_reason``, ``input.value``, ``output.value``,
``tool.name``, ``tool.parameters``. ``atlas.*`` attributes are this
service's own, including ``atlas.provider_endpoint``, ``atlas.cost_usd``,
and ``atlas.reservation_usd``.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token, copy_context
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Status, StatusCode, Tracer

from atlas_reviewer.bridge import Bridge, BridgeResult
from atlas_reviewer.bridge import Status as ToolStatus
from atlas_reviewer.call_facts import take_call
from atlas_reviewer.lens_loop import (
    FinalReply,
    LensModel,
    ToolCalls,
    TurnRequest,
    UserText,
)
from atlas_reviewer.redact import redact

ENDPOINT = "ATLAS_OTEL_ENDPOINT"
HEADERS = "ATLAS_OTEL_HEADERS"
BODIES = "ATLAS_OTEL_EXPORT_BODIES"
_TRACES_PATH = "/v1/traces"
_KIND = "openinference.span.kind"
_ARG_CHARS = 240
_ERROR_CHARS = 200
_FLUSH_MS = 1000
_MIN_SECRET = 8
_AMBIENT_HEADERS = (
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
)
_LIMITS = frozenset(
    {
        "the per-lens turn cap was reached",
        "the review's model-call cap was reached",
        "the review's dollar reservation was reached",
        "the per-lens wall clock ran out",
        "the review wall clock ran out",
    }
)

Scrub = Callable[[str], str]
ClockFn = Callable[[], float]
_REVIEW: ContextVar[_Note | None] = ContextVar("atlas_review_span", default=None)


@dataclass(frozen=True)
class ExportPlan:
    """What would be exported. ``headers`` is not part of ``repr``."""

    endpoint: str
    headers: Mapping[str, str]
    bodies: bool

    def __repr__(self) -> str:
        return (
            f"ExportPlan(endpoint={self.endpoint!r}, "
            f"headers_set={bool(self.headers)}, bodies={self.bodies})"
        )


def export_plan(env: Mapping[str, str]) -> ExportPlan | None:
    """None when export is off. A bad endpoint or header raises ValueError
    and the message does not include the header value."""
    endpoint = env.get(ENDPOINT, "").strip()
    if not endpoint:
        return None
    return ExportPlan(
        _traces_url(endpoint),
        _headers(env.get(HEADERS, "")),
        env.get(BODIES, "") == "1",
    )


def _traces_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("ATLAS_OTEL_ENDPOINT must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("ATLAS_OTEL_ENDPOINT must not carry a user or password")
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("ATLAS_OTEL_ENDPOINT must use https except for loopback")
    path = parsed.path.rstrip("/")
    if not path:
        path = _TRACES_PATH
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def _headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw.strip():
        return headers
    for part in raw.split(","):
        if "=" not in part:
            raise ValueError("ATLAS_OTEL_HEADERS has an entry without '='")
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("ATLAS_OTEL_HEADERS has an empty name")
        headers[name] = value.strip()
    return headers


def limit_label(cause_values: tuple[str, ...] | list[str], detail: str) -> str:
    """The configured limit that stopped the lens, or "" when none did."""
    hit = [value for value in sorted(cause_values) if value in _LIMITS]
    if hit:
        return "; ".join(hit)
    if "output-token limit" in detail:
        return "output-token limit"
    if "prompt bound" in detail:
        return "prompt bound"
    return ""


class _Note:
    def __init__(self, span: Any, owner: ReviewTrace) -> None:
        self._span = span
        self._owner = owner

    def set(self, key: str, value: str | float | bool) -> None:
        if self._span is None:
            return
        if isinstance(value, str):
            value = self._owner.scrub(value)
        self._span.set_attribute(key, value)

    def error(self, text: str) -> None:
        if self._span is None:
            return
        self._span.set_status(
            Status(StatusCode.ERROR, self._owner.scrub(text)[:_ERROR_CHARS])
        )

    def trace_id(self) -> str:
        """The span's trace id as 32 hex characters, or "" when unrecorded."""
        if self._span is None:
            return ""
        context = self._span.get_span_context()
        if context is None or not context.trace_id:
            return ""
        return format(context.trace_id, "032x")


class ReviewTrace:
    """One tracer for a review. ``enabled`` is false when nothing is exported
    and no span is recorded."""

    def __init__(
        self,
        tracer: Tracer | None,
        scrub: Scrub,
        bodies: bool,
        provider: TracerProvider | None = None,
        clock: ClockFn = time.perf_counter,
        processor: Any = None,
    ) -> None:
        self._tracer = tracer
        self.scrub = scrub
        self._bodies = bodies
        self._provider = provider
        self._clock = clock
        self._processor = processor

    @classmethod
    def disabled(cls, scrub: Scrub) -> ReviewTrace:
        return cls(None, scrub, False)

    @property
    def enabled(self) -> bool:
        return self._tracer is not None

    def __repr__(self) -> str:
        return f"ReviewTrace(enabled={self.enabled}, bodies={self._bodies})"

    def shutdown(self) -> None:
        processor = self._processor
        provider = self._provider
        self._processor = None
        self._provider = None
        # BatchSpanProcessor.shutdown() takes no timeout. On SDK 1.45.2 the
        # deadline is on the private BatchProcessor it wraps.
        batch = getattr(processor, "_batch_processor", None)
        if processor is not None and batch is None:
            raise RuntimeError("span processor has no bounded flush")
        if batch is not None:
            batch.shutdown(timeout_millis=_FLUSH_MS)
        if provider is not None:
            provider.shutdown()

    def flush(self) -> None:
        """Export queued spans without stopping the provider."""
        processor = self._processor
        if processor is not None and hasattr(processor, "force_flush"):
            processor.force_flush(_FLUSH_MS)

    def with_scrub(self, scrub: Scrub, *, bodies: bool | None = None) -> ReviewTrace:
        """A view with this scrubber. It does not own the provider, so
        shutting the view down does not flush or stop export.

        ``bodies`` is this caller's setting. The shared provider keeps
        whichever value it was built with, and that value is not reused.
        """
        return ReviewTrace(
            self._tracer,
            scrub,
            self._bodies if bodies is None else bodies,
            None,
            self._clock,
        )

    @contextmanager
    def review(self, repo: str, pr: int, head_sha: str) -> Iterator[_Note]:
        yield from self._span(
            "review",
            {
                _KIND: "CHAIN",
                "session.id": f"{repo}#{pr}@{head_sha}",
                "metadata": json.dumps(
                    {"repo": repo, "pr": pr, "head_sha": head_sha},
                    separators=(",", ":"),
                ),
                "atlas.repo": repo,
                "atlas.pr": pr,
                "atlas.head_sha": head_sha,
            },
        )

    @contextmanager
    def lens(self, name: str) -> Iterator[_Note]:
        yield from self._span("lens", {_KIND: "AGENT", "agent.name": name})

    def wrap_model(self, model: LensModel) -> LensModel:
        if self._tracer is None:
            return model
        return cast("LensModel", _TracedModel(model, self))

    def wrap_bridge(self, bridge: Bridge) -> Bridge:
        if self._tracer is None:
            return bridge
        return _TracedBridge(bridge, self)  # type: ignore[return-value]

    def _span(
        self, name: str, attributes: Mapping[str, str | float]
    ) -> Iterator[_Note]:
        if self._tracer is None:
            note = _Note(None, self)
            token = _mark_review(name, note)
            try:
                yield note
            finally:
                _unmark_review(token)
            return
        with self._tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        ) as span:
            note = _Note(span, self)
            for key, value in attributes.items():
                note.set(key, value)
            token = _mark_review(name, note)
            try:
                yield note
            except Exception as exc:
                note.error(str(exc))
                raise
            finally:
                _unmark_review(token)


def current_review() -> _Note | None:
    """The open review span, when the caller already entered ``trace.review``."""
    return _REVIEW.get()


def _mark_review(name: str, note: _Note) -> Token[_Note | None] | None:
    if name != "review":
        return None
    return _REVIEW.set(note)


def _unmark_review(token: Token[_Note | None] | None) -> None:
    if token is not None:
        _REVIEW.reset(token)


def trace_from_env(env: Mapping[str, str], scrub: Scrub) -> ReviewTrace:
    """A disabled trace when ``ATLAS_OTEL_ENDPOINT`` is unset. An ambient
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` does not turn export on."""
    plan = export_plan(env)
    if plan is None:
        return ReviewTrace.disabled(_and_headers(scrub, env))
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    # The HTTP exporter merges these process-wide variables in its
    # constructor. cli.main builds this exporter on the main thread,
    # before the command handler runs, so the clear is not inside a lens.
    saved = {
        name: os.environ.pop(name) for name in _AMBIENT_HEADERS if name in os.environ
    }
    try:
        exporter = OTLPSpanExporter(
            endpoint=plan.endpoint, headers=dict(plan.headers), timeout=1.0
        )
    finally:
        os.environ.update(saved)
    provider = TracerProvider(shutdown_on_exit=False)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    return ReviewTrace(
        provider.get_tracer("atlas_reviewer"),
        _and_headers(scrub, env),
        plan.bodies,
        provider,
        processor=processor,
    )


def memory_trace(
    scrub: Scrub, *, bodies: bool = False, clock: ClockFn = time.perf_counter
) -> tuple[ReviewTrace, InMemorySpanExporter]:
    """A trace that keeps finished spans in memory. Tests use this."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace = ReviewTrace(
        provider.get_tracer("atlas_reviewer"), scrub, bodies, provider, clock
    )
    return trace, exporter


class _TracedModel:
    def __init__(self, model: LensModel, owner: ReviewTrace) -> None:
        self._model = model
        self._owner = owner
        self._reservation: Decimal | None = None

    @property
    def name(self) -> str:
        return self._model.name

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        amount = self._model.worst_case_usd(request)
        self._reservation = (
            amount if isinstance(amount, Decimal) and amount.is_finite() else None
        )
        return amount

    def turn(self, request: TurnRequest) -> Any:
        tracer = self._owner._tracer
        assert tracer is not None
        start = self._owner._clock()
        reply: Any = None
        caught: Exception | None = None
        with tracer.start_as_current_span(
            "completion", record_exception=False, set_status_on_exception=False
        ) as span:
            note = _Note(span, self._owner)
            note.set(_KIND, "LLM")
            try:
                reply = self._model.turn(request)
            except Exception as exc:
                caught = exc
                raise
            finally:
                reservation = self._reservation
                self._reservation = None
                _model_attributes(
                    note, self._model, request, reply, take_call(),
                    self._owner._clock() - start, caught, self._owner._bodies,
                    reservation,
                )  # fmt: skip
        return reply


def _model_attributes(
    note: _Note,
    model: LensModel,
    request: TurnRequest,
    reply: Any,
    facts: Any,
    latency_s: float,
    caught: Exception | None,
    bodies: bool,
    reservation: Decimal | None,
) -> None:
    model_name = model.name
    if facts is not None and facts.model:
        model_name = facts.model
    note.set("llm.model_name", model_name)
    note.set("atlas.latency_s", latency_s)
    if facts is not None:
        _tokens(note, facts)
        if facts.finish_reason:
            note.set("llm.finish_reason", facts.finish_reason)
        if facts.limit_stop:
            note.set("atlas.limit_stop", facts.limit_stop)
        _record_provider(note, facts)
    elif isinstance(reply, FinalReply):
        note.set("llm.finish_reason", "stop")
    elif isinstance(reply, ToolCalls):
        note.set("llm.finish_reason", "tool_calls")
    cost = getattr(reply, "cost_usd", None)
    if isinstance(cost, Decimal) and cost.is_finite():
        note.set("llm.cost.total", float(cost))
        note.set("atlas.cost_usd", format(cost, "f"))
    if reservation is not None:
        note.set("atlas.reservation_usd", format(reservation, "f"))
    if caught is not None:
        text = str(caught)
        if "output-token limit" in text:
            note.set("atlas.limit_stop", "output-token limit")
        elif "prompt bound" in text:
            note.set("atlas.limit_stop", "prompt bound")
        note.error(text)
    if not bodies:
        return
    texts = [request.system]
    texts.extend(
        message.text for message in request.messages if isinstance(message, UserText)
    )
    note.set("input.value", "\n".join(texts))
    if isinstance(reply, FinalReply):
        note.set("output.value", reply.text)
    elif isinstance(reply, ToolCalls):
        note.set("output.value", _calls_json(reply))


def _openinference_provider(name: str) -> str | None:
    """A known OpenRouter slug, including a regional ``provider/region``."""
    key = name.strip().lower()
    mapped = _OPENINFERENCE_PROVIDER.get(key)
    if mapped:
        return mapped
    provider, separator, _region = key.partition("/")
    if separator:
        return _OPENINFERENCE_PROVIDER.get(provider)
    return None


def _record_provider(note: _Note, facts: Any) -> None:
    _host(note, "atlas.provider", facts.provider)
    served = _host(note, "llm.provider", facts.provider)
    mapped = _openinference_provider(served)
    if mapped:
        note.set("llm.provider", mapped)
    _host(note, "atlas.provider_endpoint", _strip_userinfo(facts.provider_endpoint))


def _tokens(note: _Note, facts: Any) -> None:
    prompt, completion = facts.prompt_tokens, facts.completion_tokens
    if prompt is not None:
        note.set("llm.token_count.prompt", prompt)
    if completion is not None:
        note.set("llm.token_count.completion", completion)
    if facts.reasoning_tokens is not None:
        note.set("llm.token_count.completion_details.reasoning", facts.reasoning_tokens)
    if facts.cache_read_tokens is not None:
        note.set("llm.token_count.prompt_details.cache_read", facts.cache_read_tokens)
    if facts.cache_write_tokens is not None:
        note.set("llm.token_count.prompt_details.cache_write", facts.cache_write_tokens)
    if prompt is not None and completion is not None:
        note.set("llm.token_count.total", prompt + completion)


_HOST_CHARS = 120
_OPENINFERENCE_PROVIDER = {
    "amazon-bedrock": "aws",
    "amazon bedrock": "aws",
    "bedrock": "aws",
    "anthropic": "anthropic",
    "google": "google",
    "google-vertex": "google",
    "google vertex": "google",
    "openai": "openai",
    "azure": "azure",
    "mistral": "mistralai",
    "cohere": "cohere",
    "groq": "groq",
}


def _strip_userinfo(value: str) -> str:
    """Drop userinfo through the last ``@`` in the authority.

    ``https://us@er:pass@host.example/`` becomes ``https://host.example/``.
    An ``@`` after the path stays. A region such as ``us-east-1`` stays.
    A value that contains ``@`` but has no ``//`` authority, such as
    ``user:pass@host``, is dropped.
    """
    match = re.match(r"((?:[a-z][a-z0-9+.-]*:)?//)([^/?#]*)(.*)$", value, re.IGNORECASE)
    if match is None:
        return "" if "@" in value else value
    if "@" not in match.group(2):
        return value
    return match.group(1) + match.group(2).rpartition("@")[2] + match.group(3)


def _host(note: _Note, key: str, value: str) -> str:
    """A serving-host string is untrusted. Scrub it, then cap it.

    Userinfo is stripped by the caller, and only for an endpoint. A
    provider name such as ``team@amazon.com`` stays intact.
    """
    if not value:
        return ""
    text = note._owner.scrub(value).replace("\n", " ")[:_HOST_CHARS]
    if text:
        note.set(key, text)
    return text


def _calls_json(reply: ToolCalls) -> str:
    return json.dumps(
        [{"tool": call.tool, "args": call.args} for call in reply.calls],
        default=str,
        sort_keys=True,
    )


class _TracedBridge:
    def __init__(self, bridge: Bridge, owner: ReviewTrace) -> None:
        self._bridge = bridge
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bridge, name)

    def call(self, tool: Any, args: Any) -> BridgeResult:
        tracer = self._owner._tracer
        assert tracer is not None
        label = tool if isinstance(tool, str) and tool else "tool"
        with tracer.start_as_current_span(
            "tool", record_exception=False, set_status_on_exception=False
        ) as span:
            note = _Note(span, self._owner)
            note.set(_KIND, "TOOL")
            note.set("tool.name", label)
            try:
                result = self._bridge.call(tool, args)
            except Exception as exc:
                note.error(str(exc))
                raise
            _tool_attributes(note, args, result)
            return result


def _tool_attributes(note: _Note, args: Any, result: BridgeResult) -> None:
    summary = (
        args if isinstance(args, str) else json.dumps(args, default=str, sort_keys=True)
    )
    scrubbed = note._owner.scrub(summary)
    if len(scrubbed) > _ARG_CHARS:
        scrubbed = json.dumps(
            {"truncated": True, "bytes": len(scrubbed)}, separators=(",", ":")
        )
    note.set("tool.parameters", scrubbed)
    note.set("atlas.tool.result_bytes", result.shown_bytes)
    note.set("atlas.tool.status", result.status.value)
    if result.status is not ToolStatus.OK:
        detail = result.status.value
        if result.error is not None:
            detail = f"{detail}: {result.error.text}"
        detail = note._owner.scrub(detail)
        note.set("atlas.tool.error", detail[:_ERROR_CHARS])
        note.error(detail)


# One exporter for the process. A per-lens provider made shutdown wait on
# the collector, and each lens became its own trace.
_SHARED: ReviewTrace | None = None
_SHARED_ENDPOINT: str | None = None
_HOLDERS = 0
_RETIRED: list[ReviewTrace] = []
_LOCK = threading.Lock()


def validate_export(env: Mapping[str, str]) -> ExportPlan | None:
    """Parse the export settings. Raises ValueError when they are unusable.
    Call this at process start so a bad setting stops the controller before
    a review, instead of inside every lens."""
    return export_plan(env)


def header_values(env: Mapping[str, str]) -> tuple[str, ...]:
    """Collector header values long enough to scrub. A bad header line
    yields none; ``validate_export`` is what refuses it."""
    try:
        parsed = _headers(env.get(HEADERS, ""))
    except ValueError:
        return ()
    found: list[str] = []
    for value in parsed.values():
        if len(value) >= _MIN_SECRET:
            found.append(value)
        scheme = re.match(r"(?i)^(bearer|basic|token)\s+(\S+)$", value.strip())
        if scheme is not None and len(scheme.group(2)) >= _MIN_SECRET:
            found.append(scheme.group(2))
    return tuple(dict.fromkeys(found))


def _and_headers(scrub: Scrub, env: Mapping[str, str]) -> Scrub:
    secrets = header_values(env)
    if not secrets:
        return scrub

    def wrapped(text: str) -> str:
        return redact(scrub(text), secrets).text

    return wrapped


def shutdown_shared() -> None:
    """Flush the process-wide exporter. The wait is ``_FLUSH_MS``.

    A review that still holds the provider is flushed and left running.
    A real shutdown clears the provider so the next caller builds a new
    one. ``TracerProvider(shutdown_on_exit=False)`` does not do this, so
    a process that exits inside the batch delay would drop the review span.
    """
    global _SHARED, _SHARED_ENDPOINT
    with _LOCK:
        if _HOLDERS:
            current: ReviewTrace | None = _SHARED
            dying = None
            retired: list[ReviewTrace] = []
        else:
            current = None
            dying = _SHARED
            _SHARED = None
            _SHARED_ENDPOINT = None
            retired = list(_RETIRED)
            _RETIRED.clear()
    if current is not None:
        current.flush()
        return
    if dying is not None:
        dying.shutdown()
    for old in retired:
        old.shutdown()


atexit.register(shutdown_shared)


def acquire_shared() -> None:
    """Count one review that holds the process-wide provider."""
    global _HOLDERS
    with _LOCK:
        _HOLDERS += 1


def release_shared() -> None:
    """Drop one hold. A provider replaced while a review held it is shut
    down only after the last hold is gone."""
    global _HOLDERS
    with _LOCK:
        if _HOLDERS:
            _HOLDERS -= 1
        if _HOLDERS:
            return
        retired = list(_RETIRED)
        _RETIRED.clear()
    for old in retired:
        old.shutdown()


def shared_trace(env: Mapping[str, str], scrub: Scrub) -> ReviewTrace:
    """The process-wide trace for ``env``. A later call with the same
    endpoint reuses the provider. The returned object is a scrub view and
    does not shut the provider down. A provider another review still holds
    is not shut down on an endpoint change."""
    global _SHARED, _SHARED_ENDPOINT
    plan = export_plan(env)
    endpoint = "" if plan is None else plan.endpoint
    scrub = _and_headers(scrub, env)
    retiring: ReviewTrace | None = None
    with _LOCK:
        if _SHARED is None or _SHARED_ENDPOINT != endpoint:
            previous = _SHARED
            _SHARED = trace_from_env(env, scrub)
            _SHARED_ENDPOINT = endpoint
            if previous is not None and _HOLDERS:
                _RETIRED.append(previous)
            elif previous is not None:
                retiring = previous
        bodies = False if plan is None else plan.bodies
        view = _SHARED.with_scrub(scrub, bodies=bodies)
    if retiring is not None:
        retiring.shutdown()
    return view


def submit_with_review_context(
    pool: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Submit ``fn`` on ``pool`` with this thread's review span.

    A worker thread does not inherit a ``ContextVar``. Copying the context
    is what keeps a lens span under the review span when ``pool_size`` is
    above one.
    """
    ctx = copy_context()
    return pool.submit(ctx.run, partial(fn, *args, **kwargs))


def opening_trace(trace: ReviewTrace | None, scrub: Scrub) -> ReviewTrace:
    """The trace for this lens. A caller-supplied trace is not mutated.
    The process-wide trace is used otherwise, and it is not shut down here."""
    scrub = _and_headers(scrub, os.environ)
    if trace is not None:
        return trace.with_scrub(scrub)
    return shared_trace(os.environ, scrub)
