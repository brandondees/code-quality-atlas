# SPDX-License-Identifier: MIT
"""The event sink: one structured, secret-free event per step, and no
error leaves a span without its phase, step and timing."""

import json

import pytest

from atlas_reviewer.ports import BoundaryError, NotFoundError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.telemetry import JsonlSink, Telemetry, summary_rows

from .helpers import FakeClock, fake_token


def test_a_span_records_its_fields_result_fields_and_duration():
    clock = FakeClock(start=100.0)
    t = Telemetry(clock)
    clock.advance(2.0)

    def work():
        clock.advance(1.5)
        return b"abc"

    assert (
        t.span(
            "exec", "tool check", work, {"timeout_s": 60}, lambda r: {"bytes": len(r)}
        )
        == b"abc"
    )
    (event,) = t.events
    assert (event.seq, event.phase, event.step, event.status) == (
        1,
        "exec",
        "tool check",
        "ok",
    )
    assert (event.start_s, event.duration_s) == (2.0, 1.5)
    assert event.fields == {"timeout_s": 60, "bytes": 3}


def test_a_boundary_error_is_relabelled_with_phase_step_and_timing_and_keeps_its_type():
    clock = FakeClock()
    t = Telemetry(clock)
    clock.advance(10.0)

    def times_out():
        clock.advance(60.0)
        raise NotFoundError("The read operation timed out")

    with pytest.raises(NotFoundError) as caught:
        t.span("exec", "tool check", times_out)
    assert str(caught.value) == (
        "exec / tool check failed after 60.0s (70.0s into the run): "
        "The read operation timed out"
    )
    assert isinstance(caught.value.__cause__, NotFoundError)
    (event,) = t.events
    assert event.status == "error"
    assert event.error == str(caught.value)


def test_nested_spans_label_once_at_the_innermost_step_but_both_record():
    t = Telemetry(FakeClock())

    def inner():
        raise BoundaryError("boom")

    with pytest.raises(BoundaryError) as caught:
        t.span(
            "upload", "13-byte tarball", lambda: t.span("exec", "source upload", inner)
        )
    assert str(caught.value).count("failed after") == 1
    assert str(caught.value).startswith("exec / source upload failed after")
    assert [(e.phase, e.status) for e in t.events] == [
        ("exec", "error"),
        ("upload", "error"),
    ]
    assert t.events[1].error == str(caught.value)


def test_other_exceptions_are_recorded_and_re_raised_unchanged():
    t = Telemetry(FakeClock())
    original = KeyError("x")

    def broken():
        raise original

    with pytest.raises(KeyError) as caught:
        t.span("tool", "ruff", broken)
    assert caught.value is original
    assert t.events[0].error == "KeyError: 'x'"


def test_events_are_scrubbed_before_any_sink_and_written_as_jsonl(tmp_path):
    token = fake_token("ghs_")
    redactor = Redactor((fake_token("sk-or-v1-"),))
    sink = JsonlSink(tmp_path / "deep" / "events.jsonl")
    t = Telemetry(FakeClock(), sink, scrub=lambda s: redactor(s).text)

    def leaks():
        raise BoundaryError(f"POST https://example.test failed: token {token}")

    t.record("create", "create sprite", {"runner": "cqa-rev-x", "note": token})
    with pytest.raises(BoundaryError):
        t.span("exec", "tool check", leaks, {"timeout_s": 60.0})
    raw = sink.path.read_text()
    assert token not in raw
    lines = [json.loads(line) for line in raw.splitlines()]
    assert [e["seq"] for e in lines] == [1, 2]
    assert lines[0]["runner"] == "cqa-rev-x"
    assert lines[1]["status"] == "error"
    assert lines[1]["timeout_s"] == 60.0
    assert "exec / tool check failed after" in lines[1]["error"]
    assert "[REDACTED:github-token]" in lines[1]["error"]
    JsonlSink(sink.path).emit(t.events[0])
    assert len(sink.path.read_text().splitlines()) == 3


def test_summary_rows_show_errors_loudly_with_their_detail():
    t = Telemetry(FakeClock())
    t.record("upload", "13-byte tarball", {"bytes": 13})
    t.record("exec", "tool check", status="error", error="timed out")
    rows = summary_rows(t.events)
    assert rows[0] == ("1", "upload", "13-byte tarball", "ok", "0.0", "0.0", "bytes=13")
    assert rows[1][3] == "ERROR"
    assert rows[1][6] == "timed out"
