# SPDX-License-Identifier: MIT
"""The event sink: one structured, secret-free event per step, and no
error leaves a span without its phase, step and timing."""

import json

import pytest

from atlas_reviewer.ports import BoundaryError, NotFoundError, StreamTimeoutError
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

    original = NotFoundError("The read operation timed out")

    def times_out():
        clock.advance(60.0)
        raise original

    with pytest.raises(NotFoundError) as caught:
        t.span("exec", "tool check", times_out)
    assert str(caught.value) == (
        "exec / tool check failed after 60.0s (70.0s into the run): "
        "The read operation timed out"
    )
    assert caught.value is original
    (event,) = t.events
    assert event.status == "error"
    assert event.error == str(caught.value)


@pytest.mark.parametrize("first_byte", [False, True])
def test_a_relabelled_stream_timeout_keeps_its_bytes_and_first_byte_flag(first_byte):
    t = Telemetry(FakeClock())
    original = StreamTimeoutError("stalled", b"partial-bytes", first_byte=first_byte)

    def stalls():
        raise original

    with pytest.raises(StreamTimeoutError) as caught:
        t.span("exec", "source unpack", stalls)
    assert type(caught.value) is StreamTimeoutError
    assert (caught.value.received, caught.value.first_byte) == (
        b"partial-bytes",
        first_byte,
    )
    assert str(caught.value) == (
        "exec / source unpack failed after 0.0s (0.0s into the run): stalled"
    )


def test_a_boundary_error_whose_constructor_needs_more_arguments_is_still_labelled():
    class Rejected(BoundaryError):
        def __init__(self, message, status):
            super().__init__(message)
            self.status = status

    t = Telemetry(FakeClock())

    def rejects():
        raise Rejected("HTTP 409", 409)

    with pytest.raises(Rejected) as caught:
        t.span("create", "create sprite", rejects)
    assert caught.value.status == 409
    assert str(caught.value).endswith("into the run): HTTP 409")


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


def test_a_sink_without_a_credential_aware_scrub_is_refused(tmp_path):
    with pytest.raises(TypeError, match="scrub"):
        Telemetry(FakeClock(), JsonlSink(tmp_path / "events.jsonl"))


def test_without_a_scrub_token_shaped_values_are_still_redacted():
    token = fake_token("ghp_")
    t = Telemetry(FakeClock())
    t.record("tool", "ruff", {"version": f"ruff {token}"}, error=f"saw {token}")
    (event,) = t.events
    assert token not in f"{event.fields} {event.error}"
    assert "[REDACTED:" in str(event.fields["version"])
    assert t.scrub(f"note {token}") == event.error.replace("saw", "note")


def test_summary_rows_show_errors_loudly_with_their_detail():
    t = Telemetry(FakeClock())
    t.record("upload", "13-byte tarball", {"bytes": 13})
    t.record("exec", "tool check", status="error", error="timed out")
    rows = summary_rows(t.events)
    assert rows[0] == ("1", "upload", "13-byte tarball", "ok", "0.0", "0.0", "bytes=13")
    assert rows[1][3] == "ERROR"
    assert rows[1][6] == "timed out"


def _raise(exc):
    def fail():
        raise exc

    return fail


def test_one_exception_raised_in_two_spans_carries_each_spans_label():
    """A fake or caching adapter can raise the same object twice; each
    raise is labelled by the span it failed in, once, not by the first."""
    exc = StreamTimeoutError("HTTP 500", b"partial", first_byte=True)
    t = Telemetry(FakeClock())
    for n in (1, 2):
        with pytest.raises(StreamTimeoutError) as caught:
            t.span("destroy", f"delete attempt {n}", _raise(exc))
        assert caught.value is exc
        assert str(exc).startswith(f"destroy / delete attempt {n} failed after")
        assert str(exc).endswith("): HTTP 500")
        assert str(exc).count("failed after") == 1
    assert (exc.received, exc.first_byte) == (b"partial", True)
    assert [e.error.split(" failed")[0] for e in t.events] == [
        "destroy / delete attempt 1",
        "destroy / delete attempt 2",
    ]


def test_a_reused_exception_keeps_the_innermost_label_of_its_latest_raise():
    exc = BoundaryError("HTTP 500")
    t = Telemetry(FakeClock())

    def retries_then_gives_up():
        with pytest.raises(BoundaryError):
            t.span("destroy", "delete attempt 1", _raise(exc))
        t.span("destroy", "delete attempt 2", _raise(exc))

    with pytest.raises(BoundaryError):
        t.span("destroy", "all attempts", retries_then_gives_up)
    labels = [e.error.split(" failed")[0] for e in t.events]
    assert labels == [
        "destroy / delete attempt 1",
        "destroy / delete attempt 2",
        "destroy / delete attempt 2",
    ]
