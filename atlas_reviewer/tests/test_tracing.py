# SPDX-License-Identifier: MIT
"""OpenInference spans: parentage, redaction, bodies opt-in, export off."""

import json
from decimal import Decimal

import pytest
from opentelemetry.sdk.trace.export import SpanExportResult

from atlas_reviewer.bridge import BridgeResult, Status
from atlas_reviewer.call_facts import CallFacts, note_call, take_call
from atlas_reviewer.lens_loop import (
    FinalReply,
    ToolCalls,
    ToolRequest,
    TurnRequest,
    UserText,
)
from atlas_reviewer.limit_stop import LimitRefused
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.pricing import ModelTerms
from atlas_reviewer.prompt import RepoText
from atlas_reviewer.redact import Redactor, redact
from atlas_reviewer.tool_model import _turn
from atlas_reviewer.tracing import export_plan, limit_label, memory_trace

from .agentic import LENS, READ_ALL, final
from .helpers import fake_token
from .test_openrouter import MODEL_ID

SECRET = fake_token("ghp_")


def scrub(text: str) -> str:
    return redact(text).text


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 0.25
        return self.t


class _Model:
    name = "scripted"

    def __init__(self, step, facts=None):
        self.step = step
        self.facts = facts

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        return Decimal("0.10")

    def turn(self, request: TurnRequest):
        if self.facts is not None:
            note_call(self.facts)
        if isinstance(self.step, Exception):
            raise self.step
        return self.step


class _Bridge:
    def __init__(self, result: BridgeResult) -> None:
        self.result = result
        self.calls = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        return self.result


def _attrs(span):
    return dict(span.attributes or {})


def test_spans_nest_under_the_review_and_omit_bodies_and_secrets():
    clock = _Clock()
    trace, exporter = memory_trace(scrub, clock=clock)
    request = TurnRequest("system " + SECRET, (UserText("look"),), ())
    result = BridgeResult(
        "read_file",
        json.dumps({"path": "a.py", "token": SECRET}),
        Status.OK,
        RepoText("TOKEN = " + SECRET),
        None,
        20,
        20,
        1,
        False,
        0.01,
    )
    try:
        with trace.review("example-org/example-app", 7, "abc") as review:
            with trace.lens(LENS) as lens:
                trace.wrap_model(
                    _Model(
                        FinalReply("done " + SECRET, Decimal("0.020")),
                        CallFacts(
                            "anthropic/claude-sonnet-5.5", 11, 4, 2, "stop", None
                        ),
                    )
                ).turn(request)
                trace.wrap_bridge(_Bridge(result)).call(
                    "read_file", {"path": "a.py", "token": SECRET}
                )
                lens.set("atlas.lens.state", "clean")
            review.set("atlas.review_event", "COMMENT")
    finally:
        trace.shutdown()
    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}
    review_span, lens_span = by_name["review"], by_name["lens"]
    model_span, tool_span = by_name["completion"], by_name["tool"]
    assert lens_span.parent.span_id == review_span.context.span_id
    assert model_span.parent.span_id == lens_span.context.span_id
    assert tool_span.parent.span_id == lens_span.context.span_id
    assert model_span.parent.span_id != tool_span.context.span_id
    model_attrs, tool_attrs = _attrs(model_span), _attrs(tool_span)
    assert model_attrs["openinference.span.kind"] == "LLM"
    assert model_attrs["llm.model_name"] == "anthropic/claude-sonnet-5.5"
    assert model_attrs["llm.token_count.prompt"] == 11
    assert model_attrs["llm.token_count.completion"] == 4
    assert model_attrs["llm.token_count.completion_details.reasoning"] == 2
    assert model_attrs["llm.token_count.total"] == 15
    assert model_attrs["llm.finish_reason"] == "stop"
    assert model_attrs["llm.cost.total"] == pytest.approx(0.02)
    assert Decimal(model_attrs["atlas.cost_usd"]) == Decimal("0.02")
    assert model_attrs["atlas.latency_s"] > 0
    assert "input.value" not in model_attrs
    assert "output.value" not in model_attrs
    assert tool_attrs["tool.name"] == "read_file"
    assert tool_attrs["atlas.tool.result_bytes"] == 20
    assert tool_attrs["atlas.tool.status"] == "ok"
    assert SECRET not in json.dumps({k: str(v) for k, v in model_attrs.items()})
    assert SECRET not in json.dumps({k: str(v) for k, v in tool_attrs.items()})
    assert "[REDACTED:" in tool_attrs["tool.parameters"]
    assert _attrs(review_span)["atlas.head_sha"] == "abc"
    assert _attrs(review_span)["session.id"] == "example-org/example-app#7@abc"
    assert json.loads(_attrs(review_span)["metadata"])["pr"] == 7
    assert _attrs(review_span)["atlas.pr"] == 7
    assert isinstance(_attrs(review_span)["atlas.pr"], int)


def test_bodies_are_exported_only_when_asked_and_still_scrubbed():
    trace, exporter = memory_trace(scrub, bodies=True)
    try:
        with trace.lens(LENS):
            trace.wrap_model(
                _Model(FinalReply("answer " + SECRET, Decimal("0.01")))
            ).turn(TurnRequest("prompt " + SECRET, (), ()))
    finally:
        trace.shutdown()
    attrs = _attrs(
        next(s for s in exporter.get_finished_spans() if s.name == "completion")
    )
    assert "prompt " in attrs["input.value"]
    assert "answer " in attrs["output.value"]
    assert SECRET not in attrs["input.value"]
    assert SECRET not in attrs["output.value"]
    assert "[REDACTED:" in attrs["input.value"]


def test_a_length_stop_is_named_on_the_model_span():
    trace, exporter = memory_trace(scrub)
    try:
        with (
            trace.lens(LENS),
            pytest.raises(BoundaryError, match="output-token limit"),
        ):
            trace.wrap_model(
                _Model(BoundaryError("model turn stopped at the output-token limit"))
            ).turn(TurnRequest("prompt", (), ()))
    finally:
        trace.shutdown()
    attrs = _attrs(
        next(s for s in exporter.get_finished_spans() if s.name == "completion")
    )
    assert attrs["atlas.limit_stop"] == "output-token limit"
    assert attrs["llm.model_name"] == "scripted"


def test_a_tool_error_is_recorded_without_the_result_body():
    trace, exporter = memory_trace(scrub, bodies=True)
    result = BridgeResult(
        "grep",
        "{}",
        Status.TIMED_OUT,
        RepoText(SECRET),
        redact("stderr " + SECRET),
        0,
        10,
        0,
        True,
        1.0,
    )
    try:
        with trace.lens(LENS):
            trace.wrap_bridge(_Bridge(result)).call("grep", {"pattern": "x"})
    finally:
        trace.shutdown()
    attrs = _attrs(next(s for s in exporter.get_finished_spans() if s.name == "tool"))
    assert attrs["atlas.tool.status"] == "timed out"
    assert "stderr " in attrs["atlas.tool.error"]
    assert SECRET not in attrs["atlas.tool.error"]
    assert "output.value" not in attrs


def test_tool_calls_are_the_completion_body_when_bodies_are_on():
    trace, exporter = memory_trace(scrub, bodies=True)
    reply = ToolCalls((ToolRequest("diff_file", {"path": "a.py"}),), Decimal("0.01"))
    try:
        with trace.lens(LENS):
            trace.wrap_model(_Model(reply)).turn(
                TurnRequest("sys", (UserText("u"),), ())
            )
    finally:
        trace.shutdown()
    attrs = _attrs(
        next(s for s in exporter.get_finished_spans() if s.name == "completion")
    )
    assert attrs["llm.finish_reason"] == "tool_calls"
    assert "diff_file" in attrs["output.value"]
    assert "sys" in attrs["input.value"] and "u" in attrs["input.value"]


def test_export_is_off_by_default_and_headers_stay_out_of_repr():
    assert export_plan({}) is None
    assert (
        export_plan({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example:4318"})
        is None
    )
    secret = "Bearer " + SECRET
    plan = export_plan(
        {
            "ATLAS_OTEL_ENDPOINT": "https://phoenix.internal:6006",
            "ATLAS_OTEL_HEADERS": f"Authorization={secret}",
            "ATLAS_OTEL_EXPORT_BODIES": "1",
        }
    )
    assert plan is not None
    assert plan.endpoint == "https://phoenix.internal:6006/v1/traces"
    assert plan.bodies is True
    assert plan.headers["Authorization"] == secret
    assert SECRET not in repr(plan)
    full = export_plan({"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal/v1/traces"})
    assert full is not None
    assert full.endpoint == "https://phoenix.internal/v1/traces"
    with pytest.raises(ValueError, match="without '='") as caught:
        export_plan(
            {
                "ATLAS_OTEL_ENDPOINT": "https://phoenix.internal",
                "ATLAS_OTEL_HEADERS": secret,
            }
        )
    assert SECRET not in str(caught.value)
    with pytest.raises(ValueError, match="user or password"):
        export_plan({"ATLAS_OTEL_ENDPOINT": f"http://user:{SECRET}@phoenix.internal"})


def test_a_bad_endpoint_or_header_name_is_refused_without_echoing_it():
    with pytest.raises(ValueError, match="http\\(s\\) URL"):
        export_plan({"ATLAS_OTEL_ENDPOINT": "phoenix.internal"})
    with pytest.raises(ValueError, match="empty name") as caught:
        export_plan(
            {
                "ATLAS_OTEL_ENDPOINT": "https://phoenix.internal",
                "ATLAS_OTEL_HEADERS": f"={SECRET}",
            }
        )
    assert SECRET not in str(caught.value)


def test_trace_from_env_hands_the_endpoint_to_the_exporter(monkeypatch):
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_mod

    built: dict[str, object] = {}

    class Exporter:
        def __init__(
            self,
            *,
            endpoint: str,
            headers: dict[str, str],
            timeout: float | None = None,
        ) -> None:
            built["endpoint"] = endpoint
            built["headers"] = headers

        def export(self, spans: object) -> SpanExportResult:
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            built["shutdown"] = True

        def force_flush(self, timeout_millis: int | None = None) -> bool:
            return True

    monkeypatch.setattr(exporter_mod, "OTLPSpanExporter", Exporter)
    from atlas_reviewer.tracing import trace_from_env

    trace = trace_from_env(
        {
            "ATLAS_OTEL_ENDPOINT": "https://phoenix.internal:6006",
            "ATLAS_OTEL_HEADERS": f"Authorization=Bearer {SECRET}",
        },
        scrub,
    )
    try:
        assert trace.enabled is True
        assert built["endpoint"] == "https://phoenix.internal:6006/v1/traces"
        assert SECRET not in repr(trace)
    finally:
        trace.shutdown()
    assert built.get("shutdown") is True


def test_an_exception_message_is_scrubbed_on_every_span_it_leaves():
    known = "s3cr3tVALUEabcdefghijklmnop"
    redactor = Redactor((known,), (), ())
    trace, exporter = memory_trace(lambda text: redactor(text).text)

    class Boom:
        def call(self, tool: object, args: object) -> BridgeResult:
            raise RuntimeError("bridge " + known)

    try:
        with (
            pytest.raises(RuntimeError),
            trace.review("example-org/example-app", 1, "abc"),
            trace.lens(LENS),
        ):
            trace.wrap_model(_Model(RuntimeError("upstream said key=" + known))).turn(
                TurnRequest("prompt", (), ())
            )
        with (
            trace.review("example-org/example-app", 1, "abc"),
            trace.lens(LENS),
            pytest.raises(RuntimeError),
        ):
            trace.wrap_bridge(Boom()).call("grep", {})  # type: ignore[arg-type]
    finally:
        trace.shutdown()
    spans = exporter.get_finished_spans()
    for span in spans:
        assert known not in (span.status.description or "")
        for event in span.events:
            assert known not in str(event.attributes)
    errored = [
        span
        for span in spans
        if span.name in {"review", "lens"} and span.status.status_code.name == "ERROR"
    ]
    assert len(errored) >= 2


def test_a_prompt_bound_and_a_failed_tool_are_errors_on_their_spans():
    trace, exporter = memory_trace(scrub)

    class Boom:
        def call(self, tool: object, args: object) -> BridgeResult:
            raise RuntimeError("bridge down")

    try:
        with trace.lens(LENS):
            with pytest.raises(BoundaryError, match="prompt bound"):
                trace.wrap_model(
                    _Model(BoundaryError("prompt bound 10 exceeds the cap"))
                ).turn(TurnRequest("p", (), ()))
            with pytest.raises(RuntimeError, match="bridge down"):
                trace.wrap_bridge(Boom()).call(None, {"path": "a.py"})  # type: ignore[arg-type]
    finally:
        trace.shutdown()
    model = next(s for s in exporter.get_finished_spans() if s.name == "completion")
    tool = next(s for s in exporter.get_finished_spans() if s.name == "tool")
    assert _attrs(model)["atlas.limit_stop"] == "prompt bound"
    assert tool.status.status_code.name == "ERROR"
    assert "bridge down" in (tool.status.description or "")


def test_trace_from_env_stays_off_without_the_atlas_endpoint(monkeypatch):
    from atlas_reviewer.tracing import opening_trace, trace_from_env

    monkeypatch.delenv("ATLAS_OTEL_ENDPOINT", raising=False)
    disabled = trace_from_env(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example"}, scrub
    )
    assert disabled.enabled is False
    same = opening_trace(disabled, scrub)
    assert same.enabled is False
    assert same is not disabled
    fresh = opening_trace(None, scrub)
    assert fresh.enabled is False


def test_limit_label_names_a_cap_and_an_output_limit():
    assert limit_label(["the per-lens turn cap was reached"], "") == (
        "the per-lens turn cap was reached"
    )
    assert limit_label([], "model turn stopped at the output-token limit") == (
        "output-token limit"
    )
    assert limit_label(["a finding's quote was not found at the head SHA"], "") == ""


def test_a_length_response_notes_tokens_before_the_stop():
    terms = ModelTerms(
        MODEL_ID,
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(0),
        200_000,
        8000,
    )
    data = {
        "model": MODEL_ID,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "completion_tokens_details": {"reasoning_tokens": 3},
            "prompt_tokens_details": {"cached_tokens": 6, "cache_write_tokens": 2},
            "cost": "0.01",
            "is_byok": False,
        },
        "provider": "Amazon Bedrock",
        "choices": [{"finish_reason": "length", "message": {"content": "x"}}],
    }
    with pytest.raises(LimitRefused):
        _turn(data, terms, True, 8000)
    facts = take_call()
    assert facts is not None
    assert (facts.prompt_tokens, facts.completion_tokens, facts.reasoning_tokens) == (
        10,
        4,
        3,
    )
    assert (facts.cache_read_tokens, facts.cache_write_tokens) == (6, 2)
    assert facts.provider == "Amazon Bedrock"
    assert facts.provider_endpoint == ""
    assert facts.finish_reason == "length"
    assert facts.limit_stop == "output-token limit"
    assert facts.model == MODEL_ID


def test_the_agentic_loop_emits_one_review_span_around_the_lens(tmp_path):
    from .test_coordinator import review

    trace, exporter = memory_trace(scrub)
    try:
        result, _, _ = review(tmp_path, [READ_ALL, final()], trace=trace)
    finally:
        trace.shutdown()
    spans = exporter.get_finished_spans()
    names = [span.name for span in spans]
    assert names.count("review") == 1
    assert names.count("lens") == 1
    assert "tool" in names
    assert "completion" in names
    review_span = next(span for span in spans if span.name == "review")
    lens_span = next(span for span in spans if span.name == "lens")
    tool_span = next(span for span in spans if span.name == "tool")
    assert lens_span.parent.span_id == review_span.context.span_id
    assert tool_span.parent.span_id == lens_span.context.span_id
    assert _attrs(tool_span)["tool.name"] == "diff_file"
    assert _attrs(lens_span)["agent.name"] == LENS
    assert result.trace_id == format(review_span.context.trace_id, "032x")
    from atlas_reviewer.coordinator import status_line

    assert result.trace_id in status_line(result)
    blob = json.dumps(
        [{key: str(value) for key, value in _attrs(span).items()} for span in spans]
    )
    assert SECRET not in blob


def test_bodies_are_on_only_for_the_value_1_and_http_is_loopback_only():
    base = {"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}
    assert export_plan(base).bodies is False
    assert export_plan({**base, "ATLAS_OTEL_EXPORT_BODIES": "0"}).bodies is False
    assert export_plan({**base, "ATLAS_OTEL_EXPORT_BODIES": "true"}).bodies is False
    assert export_plan({**base, "ATLAS_OTEL_EXPORT_BODIES": "1"}).bodies is True
    local = export_plan({"ATLAS_OTEL_ENDPOINT": "http://127.0.0.1:6006"})
    assert local is not None
    assert local.endpoint == "http://127.0.0.1:6006/v1/traces"
    with pytest.raises(ValueError, match="https except for loopback"):
        export_plan({"ATLAS_OTEL_ENDPOINT": "http://phoenix.internal"})


def test_with_scrub_replaces_the_scrubber_and_parameters_stay_json():
    trace, exporter = memory_trace(lambda text: text)
    view = trace.with_scrub(scrub)
    long_secret = {"pattern": "y" * 500, "token": SECRET}
    result = BridgeResult(
        "grep",
        "{}",
        Status.OK,
        RepoText("body"),
        redact("ok"),
        3,
        3,
        0,
        False,
        0.1,
    )
    try:
        with view.lens(LENS):
            view.wrap_bridge(_Bridge(result)).call("grep", long_secret)
    finally:
        trace.shutdown()
    attrs = _attrs(next(s for s in exporter.get_finished_spans() if s.name == "tool"))
    loaded = json.loads(attrs["tool.parameters"])
    assert loaded["truncated"] is True
    assert SECRET not in attrs["tool.parameters"]
    assert SECRET not in attrs["tool.name"]


def test_every_secret_shape_is_scrubbed_on_the_span_paths():
    openrouter = fake_token("sk-or-v1-", 40)
    install = fake_token("ghs_")
    sprites = fake_token("spritekey", 40)
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + ("Ab1" * 20)
        + "\n-----END RSA PRIVATE KEY-----"
    )
    secrets = (openrouter, install, sprites, pem)
    redactor = Redactor((sprites,), (), ())

    def scrubber(text: str) -> str:
        return redactor(text).text

    trace, exporter = memory_trace(scrubber, bodies=True)
    blob = " ".join(secrets)
    result = BridgeResult(
        "grep",
        "{}",
        Status.FAILED,
        RepoText("body"),
        redact("err " + blob, (sprites,)),
        0,
        4,
        0,
        False,
        0.1,
    )

    class Boom:
        def call(self, tool: object, args: object) -> BridgeResult:
            raise RuntimeError("down " + blob)

    try:
        with trace.review("o/r", 1, "abc"), trace.lens(LENS):
            trace.wrap_model(
                _Model(FinalReply("answer " + blob, Decimal("0.01")))
            ).turn(TurnRequest("prompt " + blob, (), ()))
            trace.wrap_bridge(_Bridge(result)).call(blob, {"q": blob})
        with (
            pytest.raises(RuntimeError),
            trace.review("o/r", 1, "abc"),
            trace.lens(LENS),
        ):
            trace.wrap_bridge(Boom()).call("grep", {})  # type: ignore[arg-type]
    finally:
        trace.shutdown()
    for span in exporter.get_finished_spans():
        rendered = span.name + (span.status.description or "")
        rendered += json.dumps({key: str(value) for key, value in _attrs(span).items()})
        for secret in secrets:
            assert secret not in rendered


def test_a_worker_thread_keeps_the_review_span():
    from concurrent.futures import ThreadPoolExecutor

    from atlas_reviewer.tracing import current_review, submit_with_review_context

    trace, exporter = memory_trace(scrub)

    def work() -> bool:
        with trace.lens(LENS):
            return current_review() is not None

    try:
        with trace.review("o/r", 1, "abc"), ThreadPoolExecutor(max_workers=1) as pool:
            assert submit_with_review_context(pool, work).result() is True
            assert pool.submit(current_review).result() is None
    finally:
        trace.shutdown()
    spans = exporter.get_finished_spans()
    review_span = next(span for span in spans if span.name == "review")
    lens_span = next(span for span in spans if span.name == "lens")
    assert lens_span.parent.span_id == review_span.context.span_id


def test_ambient_otlp_headers_are_not_visible_while_the_exporter_is_built(
    monkeypatch,
):
    import os

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_mod

    seen: dict[str, object] = {}

    class Exporter:
        def __init__(
            self,
            *,
            endpoint: str,
            headers: dict[str, str],
            timeout: float | None = None,
        ) -> None:
            seen["ambient"] = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")
            seen["traces"] = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS")

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(exporter_mod, "OTLPSpanExporter", Exporter)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=ambient-secret")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "X-Token=ambient-secret")
    from atlas_reviewer.tracing import trace_from_env

    trace = trace_from_env({"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}, scrub)
    trace.shutdown()
    assert seen["ambient"] is None
    assert seen["traces"] is None
    assert os.environ["OTEL_EXPORTER_OTLP_HEADERS"] == "Authorization=ambient-secret"


def test_collector_header_values_are_scrubbed(monkeypatch):
    from atlas_reviewer.cli import _Credentials
    from atlas_reviewer.tracing import opening_trace

    token = fake_token("collector", 24)
    monkeypatch.setenv("ATLAS_OTEL_HEADERS", f"X-Api-Key={token}")
    assert token not in _Credentials(
        {"ATLAS_OTEL_HEADERS": f"X-Api-Key={token}"}
    ).scrub("sent " + token)
    trace, exporter = memory_trace(lambda text: text)
    view = opening_trace(trace, lambda text: text)
    result = BridgeResult(
        "grep", "{}", Status.OK, RepoText("body"), redact("ok"), 1, 1, 0, False, 0.1
    )
    try:
        with view.lens(LENS):
            view.wrap_bridge(_Bridge(result)).call("grep", {"pattern": token})
    finally:
        trace.shutdown()
    rendered = json.dumps(
        {
            key: str(value)
            for key, value in _attrs(
                next(s for s in exporter.get_finished_spans() if s.name == "tool")
            ).items()
        }
    )
    assert token not in rendered


def test_process_exit_flushes_spans_to_a_local_sink():
    import os
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    posts: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            posts.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = (
        "from atlas_reviewer.tracing import opening_trace\n"
        "trace = opening_trace(None, lambda text: text)\n"
        "with trace.review('o/r', 1, 'abc'):\n"
        "    pass\n"
    )
    env = os.environ.copy()
    env["ATLAS_OTEL_ENDPOINT"] = f"http://127.0.0.1:{port}"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            timeout=20,
            check=False,
            capture_output=True,
        )
    finally:
        server.shutdown()
    assert completed.returncode == 0, completed.stderr
    assert posts == ["/v1/traces"]


def test_cache_counts_are_omitted_when_the_reply_does_not_report_them():
    present = CallFacts(
        "m", 10, 4, None, "stop", None, cache_read_tokens=0, cache_write_tokens=3
    )
    absent = CallFacts("m", 10, 4, None, "stop", None)
    trace, exporter = memory_trace(scrub)
    try:
        with trace.lens(LENS):
            trace.wrap_model(_Model(FinalReply("a", Decimal("0.01")), present)).turn(
                TurnRequest("p", (), ())
            )
            trace.wrap_model(_Model(FinalReply("b", Decimal("0.01")), absent)).turn(
                TurnRequest("p", (), ())
            )
    finally:
        trace.shutdown()
    spans = [s for s in exporter.get_finished_spans() if s.name == "completion"]
    reported = _attrs(spans[0])
    assert reported["llm.token_count.prompt_details.cache_read"] == 0
    assert reported["llm.token_count.prompt_details.cache_write"] == 3
    omitted = _attrs(spans[1])
    assert "llm.token_count.prompt_details.cache_read" not in omitted
    assert "llm.token_count.prompt_details.cache_write" not in omitted


def test_the_serving_host_is_scrubbed_and_capped():
    secret = fake_token("zq", 24)
    host = secret + ("x" * 200)
    facts = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider=host,
        provider_endpoint="https://bedrock.example/" + secret,
    )
    trace, exporter = memory_trace(lambda text: redact(text, (secret,)).text)
    try:
        with trace.lens(LENS):
            trace.wrap_model(_Model(FinalReply("a", Decimal("0.01")), facts)).turn(
                TurnRequest("p", (), ())
            )
    finally:
        trace.shutdown()
    attrs = _attrs(
        next(s for s in exporter.get_finished_spans() if s.name == "completion")
    )
    assert secret not in attrs["llm.provider"]
    assert secret not in attrs["atlas.provider_endpoint"]
    assert len(attrs["llm.provider"]) <= 120
    assert attrs["atlas.provider_endpoint"].startswith("https://bedrock.example/")


def test_the_reservation_is_the_worst_case_and_is_omitted_without_one():
    trace, exporter = memory_trace(scrub)
    held = _Model(FinalReply("a", Decimal("0.02")))
    bare = _Model(FinalReply("b", Decimal("0.02")))
    try:
        with trace.lens(LENS):
            wrapped = trace.wrap_model(held)
            assert wrapped.worst_case_usd(TurnRequest("p", (), ())) == Decimal("0.10")
            wrapped.turn(TurnRequest("p", (), ()))
            trace.wrap_model(bare).turn(TurnRequest("p", (), ()))
    finally:
        trace.shutdown()
    spans = [s for s in exporter.get_finished_spans() if s.name == "completion"]
    assert _attrs(spans[0])["atlas.reservation_usd"] == "0.10"
    assert "atlas.reservation_usd" not in _attrs(spans[1])


def test_a_provider_object_keeps_its_endpoint():
    terms = ModelTerms(
        MODEL_ID,
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(0),
        200_000,
        8000,
    )
    data = {
        "model": MODEL_ID,
        "provider": {"name": "amazon-bedrock", "endpoint": "us-east-1"},
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "cost": "0.01",
            "is_byok": False,
        },
        "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
    }
    assert _turn(data, terms, True, 8000).text == "ok"
    facts = take_call()
    assert facts is not None
    assert (facts.provider, facts.provider_endpoint) == ("amazon-bedrock", "us-east-1")
    assert facts.cache_read_tokens is None
    assert facts.cache_write_tokens is None


def test_export_is_not_an_sdk_exit_hook_and_the_flush_is_one_second(monkeypatch):
    from atlas_reviewer import tracing

    assert tracing._FLUSH_MS <= 1000
    seen: dict[str, bool] = {}
    real = tracing.TracerProvider

    def wrapped(*args: object, shutdown_on_exit: bool = True, **kwargs: object):
        seen["shutdown_on_exit"] = shutdown_on_exit
        return real(*args, shutdown_on_exit=shutdown_on_exit, **kwargs)

    monkeypatch.setattr(tracing, "TracerProvider", wrapped)
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_mod

    class Exporter:
        def __init__(
            self,
            *,
            endpoint: str,
            headers: dict[str, str],
            timeout: float | None = None,
        ) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(exporter_mod, "OTLPSpanExporter", Exporter)
    tracing.trace_from_env({"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}, scrub)
    assert seen["shutdown_on_exit"] is False


def test_main_builds_the_shared_exporter_before_the_handler(tmp_path, monkeypatch):
    from atlas_reviewer import cli, tracing

    saved = (
        tracing._SHARED,
        tracing._SHARED_ENDPOINT,
        tracing._HOLDERS,
        list(tracing._RETIRED),
    )
    seen: dict[str, bool] = {}

    def fake(env: object, scrubber: object) -> tracing.ReviewTrace:
        trace, _exporter = memory_trace(lambda text: text)
        return trace

    def handler(args: object, run: object) -> int:
        seen["ready"] = (
            tracing._SHARED is not None and tracing._SHARED._provider is not None
        )
        return 0

    monkeypatch.setattr(tracing, "trace_from_env", fake)
    monkeypatch.setattr(cli, "_cmd_eval", handler)
    tracing._SHARED = None
    tracing._SHARED_ENDPOINT = None
    tracing._HOLDERS = 0
    tracing._RETIRED.clear()
    try:
        code = cli.main(
            ["eval", "--fixtures", str(tmp_path)],
            env={"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"},
        )
    finally:
        if tracing._SHARED is not None and tracing._SHARED is not saved[0]:
            tracing._SHARED.shutdown()
        tracing._SHARED, tracing._SHARED_ENDPOINT, tracing._HOLDERS = saved[:3]
        tracing._RETIRED[:] = saved[3]
    assert code == 0
    assert seen["ready"] is True


def test_a_scrub_view_shutdown_leaves_the_shared_provider(monkeypatch):
    from atlas_reviewer import tracing

    saved = (
        tracing._SHARED,
        tracing._SHARED_ENDPOINT,
        tracing._HOLDERS,
        list(tracing._RETIRED),
    )
    exporter_box: list[object] = []

    def fake(env: object, scrubber: object) -> tracing.ReviewTrace:
        trace, exporter = memory_trace(scrub)
        exporter_box.append(exporter)
        return trace

    monkeypatch.setattr(tracing, "trace_from_env", fake)
    tracing._SHARED = None
    tracing._SHARED_ENDPOINT = None
    tracing._HOLDERS = 0
    tracing._RETIRED.clear()
    try:
        view = tracing.shared_trace(
            {"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}, scrub
        )
        owner = tracing._SHARED
        assert owner is not None and owner._provider is not None
        view.shutdown()
        assert owner._provider is not None
        with view.lens(LENS):
            pass
        assert any(span.name == "lens" for span in exporter_box[0].get_finished_spans())
    finally:
        if tracing._SHARED is not None and tracing._SHARED is not saved[0]:
            tracing._SHARED.shutdown()
        tracing._SHARED, tracing._SHARED_ENDPOINT, tracing._HOLDERS = saved[:3]
        tracing._RETIRED[:] = saved[3]


def test_a_provider_endpoint_drops_userinfo_and_a_known_host_maps():
    secret = "user:s3cret"
    facts = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider="Amazon Bedrock",
        provider_endpoint=f"https://{secret}@bedrock.example/invoke",
    )
    trace, exporter = memory_trace(scrub)
    try:
        with trace.lens(LENS):
            trace.wrap_model(_Model(FinalReply("a", Decimal("0.01")), facts)).turn(
                TurnRequest("p", (), ())
            )
    finally:
        trace.shutdown()
    attrs = _attrs(
        next(s for s in exporter.get_finished_spans() if s.name == "completion")
    )
    assert attrs["llm.provider"] == "aws"
    assert attrs["atlas.provider"] == "Amazon Bedrock"
    assert secret not in attrs["atlas.provider_endpoint"]
    assert attrs["atlas.provider_endpoint"] == "https://bedrock.example/invoke"


def test_a_regional_vertex_slug_maps_and_userinfo_stays_off_the_name():
    facts = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider="google-vertex/europe",
        provider_endpoint="https://user@bedrock.example/a@b",
    )
    named = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider="team@amazon.com",
        provider_endpoint="https://h.example/a@b",
    )
    trace, exporter = memory_trace(scrub)
    try:
        with trace.lens(LENS):
            model = trace.wrap_model(_Model(FinalReply("a", Decimal("0.01")), facts))
            model.turn(TurnRequest("p", (), ()))
            trace.wrap_model(_Model(FinalReply("b", Decimal("0.01")), named)).turn(
                TurnRequest("q", (), ())
            )
    finally:
        trace.shutdown()
    spans = [s for s in exporter.get_finished_spans() if s.name == "completion"]
    regional, plain = _attrs(spans[0]), _attrs(spans[1])
    assert regional["llm.provider"] == "google"
    assert regional["atlas.provider"] == "google-vertex/europe"
    assert regional["atlas.provider_endpoint"] == "https://bedrock.example/a@b"
    assert plain["llm.provider"] == "team@amazon.com"
    assert plain["atlas.provider"] == "team@amazon.com"
    assert plain["atlas.provider_endpoint"] == "https://h.example/a@b"


def test_an_unencoded_at_in_userinfo_is_stripped_through_the_last_at():
    facts = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider="amazon-bedrock",
        provider_endpoint="https://us@er:pass@host.example/",
    )
    trace, exporter = memory_trace(scrub)
    try:
        with trace.lens(LENS):
            trace.wrap_model(_Model(FinalReply("a", Decimal("0.01")), facts)).turn(
                TurnRequest("p", (), ())
            )
    finally:
        trace.shutdown()
    attrs = _attrs(
        next(s for s in exporter.get_finished_spans() if s.name == "completion")
    )
    assert attrs["atlas.provider_endpoint"] == "https://host.example/"
    assert "pass" not in attrs["atlas.provider_endpoint"]


def test_a_bare_userinfo_endpoint_is_dropped_and_a_region_stays():
    bare = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider="amazon-bedrock",
        provider_endpoint="user:pass@host.example",
    )
    region = CallFacts(
        "m",
        1,
        1,
        None,
        "stop",
        None,
        provider="amazon-bedrock",
        provider_endpoint="us-east-1",
    )
    trace, exporter = memory_trace(scrub)
    try:
        with trace.lens(LENS):
            trace.wrap_model(_Model(FinalReply("a", Decimal("0.01")), bare)).turn(
                TurnRequest("p", (), ())
            )
            trace.wrap_model(_Model(FinalReply("b", Decimal("0.01")), region)).turn(
                TurnRequest("q", (), ())
            )
    finally:
        trace.shutdown()
    spans = [s for s in exporter.get_finished_spans() if s.name == "completion"]
    dropped, kept = _attrs(spans[0]), _attrs(spans[1])
    assert "atlas.provider_endpoint" not in dropped
    assert "pass" not in "".join(str(value) for value in dropped.values())
    assert kept["atlas.provider_endpoint"] == "us-east-1"


def test_a_bearer_collector_token_is_scrubbed_without_its_prefix(monkeypatch):
    from atlas_reviewer.tracing import opening_trace

    token = fake_token("zq", 24)
    for prefix in ("Bearer ", "bearer ", "Basic ", "token ", "Bearer  "):
        monkeypatch.setenv("ATLAS_OTEL_HEADERS", f"Authorization={prefix}{token}")
        result = BridgeResult(
            "grep",
            "{}",
            Status.FAILED,
            RepoText("body"),
            redact("tool failed " + token),
            0,
            4,
            0,
            False,
            0.1,
        )
        trace, exporter = memory_trace(lambda text: text, bodies=True)
        view = opening_trace(trace, lambda text: text)
        try:
            with view.lens(LENS):
                view.wrap_model(
                    _Model(FinalReply("answer " + token, Decimal("0.01")))
                ).turn(TurnRequest("prompt " + token, (), ()))
                view.wrap_bridge(_Bridge(result)).call("grep", {"pattern": token})
        finally:
            trace.shutdown()
        rendered = ""
        for span in exporter.get_finished_spans():
            rendered += span.status.description or ""
            rendered += json.dumps(
                {key: str(value) for key, value in _attrs(span).items()}
            )
        assert token not in rendered, prefix
        assert "prompt " in rendered


def test_a_tool_error_is_scrubbed_before_it_is_cut():
    token = fake_token("zq", 24)
    prefix = "a" * 177
    result = BridgeResult(
        "grep",
        "{}",
        Status.FAILED,
        RepoText("body"),
        redact(prefix + token),
        0,
        4,
        0,
        False,
        0.1,
    )
    trace, exporter = memory_trace(lambda text: redact(text, (token,)).text)
    try:
        with trace.lens(LENS):
            trace.wrap_bridge(_Bridge(result)).call("grep", {})
    finally:
        trace.shutdown()
    error = _attrs(next(s for s in exporter.get_finished_spans() if s.name == "tool"))[
        "atlas.tool.error"
    ]
    assert token not in error
    assert token[:7] not in error


def test_shutdown_shared_leaves_a_held_provider_and_drops_a_stopped_one(monkeypatch):
    from atlas_reviewer import tracing

    saved = (
        tracing._SHARED,
        tracing._SHARED_ENDPOINT,
        tracing._HOLDERS,
        list(tracing._RETIRED),
    )
    built: list[int] = []

    def fake(env: object, scrubber: object) -> tracing.ReviewTrace:
        built.append(1)
        trace, _exporter = memory_trace(scrub)
        return trace

    monkeypatch.setattr(tracing, "trace_from_env", fake)
    tracing._SHARED = None
    tracing._SHARED_ENDPOINT = None
    tracing._HOLDERS = 0
    tracing._RETIRED.clear()
    try:
        env = {"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}
        tracing.acquire_shared()
        tracing.shared_trace(env, scrub)
        owner = tracing._SHARED
        assert owner is not None
        flushed: list[str] = []
        owner.flush = lambda: flushed.append("flush")  # type: ignore[method-assign]
        tracing.shutdown_shared()
        assert flushed == ["flush"]
        assert tracing._SHARED is owner
        tracing.release_shared()
        tracing.shutdown_shared()
        assert tracing._SHARED is None
        assert tracing._SHARED_ENDPOINT is None
        tracing.shared_trace(env, scrub)
        assert built == [1, 1]
    finally:
        if tracing._SHARED is not None and tracing._SHARED is not saved[0]:
            tracing._SHARED.shutdown()
        tracing._SHARED, tracing._SHARED_ENDPOINT, tracing._HOLDERS = saved[:3]
        tracing._RETIRED[:] = saved[3]


def test_a_later_caller_gets_its_own_bodies_setting(monkeypatch):
    from atlas_reviewer import tracing

    saved = (
        tracing._SHARED,
        tracing._SHARED_ENDPOINT,
        tracing._HOLDERS,
        list(tracing._RETIRED),
    )

    def fake(env: object, scrubber: object) -> tracing.ReviewTrace:
        trace, _exporter = memory_trace(lambda text: text, bodies=False)
        return trace

    monkeypatch.setattr(tracing, "trace_from_env", fake)
    tracing._SHARED = None
    tracing._SHARED_ENDPOINT = None
    tracing._HOLDERS = 0
    tracing._RETIRED.clear()
    try:
        endpoint = {"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}
        off = tracing.shared_trace(endpoint, lambda text: text)
        on = tracing.shared_trace(
            {**endpoint, "ATLAS_OTEL_EXPORT_BODIES": "1"}, lambda text: text
        )
        assert off._bodies is False
        assert on._bodies is True
    finally:
        if tracing._SHARED is not None and tracing._SHARED is not saved[0]:
            tracing._SHARED.shutdown()
        tracing._SHARED, tracing._SHARED_ENDPOINT, tracing._HOLDERS = saved[:3]
        tracing._RETIRED[:] = saved[3]


def test_a_processor_without_a_bounded_flush_fails_closed():
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    trace, _exporter = memory_trace(scrub)
    processor = BatchSpanProcessor(_exporter)
    try:
        processor._batch_processor.shutdown(timeout_millis=1)
    finally:
        processor.shutdown()
    trace._processor = object()
    with pytest.raises(RuntimeError, match="bounded flush"):
        trace.shutdown()


def test_a_dead_collector_does_not_hold_process_exit():
    import os
    import socket
    import subprocess
    import sys
    import threading
    import time

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    port = sock.getsockname()[1]
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _addr = sock.accept()
            except TimeoutError:
                continue
            held.append(conn)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    code = (
        "from atlas_reviewer.tracing import opening_trace\n"
        "trace = opening_trace(None, lambda text: text)\n"
        "with trace.review('o/r', 1, 'abc'):\n"
        "    pass\n"
    )
    env = os.environ.copy()
    env["ATLAS_OTEL_ENDPOINT"] = f"http://127.0.0.1:{port}"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            timeout=15,
            check=False,
            capture_output=True,
        )
    finally:
        stop.set()
        sock.close()
        for conn in held:
            conn.close()
    elapsed = time.perf_counter() - started
    assert completed.returncode == 0, completed.stderr
    assert elapsed < 2.5


def test_two_callers_share_one_provider_and_a_hold_blocks_shutdown(monkeypatch):
    from atlas_reviewer import tracing

    saved = (
        tracing._SHARED,
        tracing._SHARED_ENDPOINT,
        tracing._HOLDERS,
        list(tracing._RETIRED),
    )
    built: list[object] = []

    def fake(env: dict[str, str], scrubber: object) -> tracing.ReviewTrace:
        built.append(env.get("ATLAS_OTEL_ENDPOINT", ""))
        trace, _exporter = memory_trace(scrub)
        return trace

    monkeypatch.setattr(tracing, "trace_from_env", fake)
    tracing._SHARED = None
    tracing._SHARED_ENDPOINT = None
    tracing._HOLDERS = 0
    tracing._RETIRED.clear()
    shut: list[str] = []
    try:
        import threading

        env = {"ATLAS_OTEL_ENDPOINT": "https://phoenix.internal"}
        barrier = threading.Barrier(2)

        def once() -> None:
            barrier.wait()
            tracing.shared_trace(env, scrub)

        threads = [threading.Thread(target=once) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert built == ["https://phoenix.internal"]
        tracing.acquire_shared()
        first = tracing._SHARED
        assert first is not None
        first.shutdown = lambda: shut.append("first")  # type: ignore[method-assign]
        tracing.shared_trace({"ATLAS_OTEL_ENDPOINT": "https://other.example"}, scrub)
        assert shut == []
        tracing.release_shared()
        assert shut == ["first"]
    finally:
        tracing._SHARED, tracing._SHARED_ENDPOINT, tracing._HOLDERS = saved[:3]
        tracing._RETIRED[:] = saved[3]
