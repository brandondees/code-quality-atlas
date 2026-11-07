# SPDX-License-Identifier: MIT
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from atlas_reviewer.http import (
    HttpResponse,
    StreamWindow,
    UrllibStreamingTransport,
    UrllibTransport,
    safe_url,
)
from atlas_reviewer.ledger import FileLedger, ReviewInProgressError, single_review_lock
from atlas_reviewer.ports import BoundaryError, StreamTimeoutError


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {
            "/ok": (200, {}, b"hello"),
            "/missing": (404, {}, b"nope"),
            "/redirect": (302, {"Location": "/ok"}, b""),
            "/big": (200, {}, b"x" * 100),
        }
        status, headers, body = routes[self.path]
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _transport(**kwargs):
    return UrllibTransport(allowed_schemes=frozenset({"http"}), **kwargs)


def test_transport_returns_success_and_error_responses(server):
    t = _transport()
    assert t.request("GET", f"{server}/ok", {}, None, 5).body == b"hello"
    assert t.request("GET", f"{server}/missing", {}, None, 5).status == 404


def test_transport_never_follows_redirects(server):
    resp = _transport().request(
        "GET", f"{server}/redirect", {"Authorization": "Bearer x"}, None, 5
    )
    assert resp.status == 302
    assert resp.header("location") == "/ok"


def test_transport_caps_response_size(server):
    with pytest.raises(BoundaryError, match="exceeded"):
        _transport(max_bytes=10).request("GET", f"{server}/big", {}, None, 5)


def test_transport_refuses_plain_http_by_default_and_wraps_connection_errors():
    with pytest.raises(BoundaryError, match="scheme"):
        UrllibTransport().request("GET", "http://127.0.0.1:1/x", {}, None, 1)
    with pytest.raises(BoundaryError, match="failed"):
        _transport().request("GET", "http://127.0.0.1:1/x?secret=1", {}, None, 1)


def test_safe_url_drops_query_and_header_lookup_is_case_insensitive():
    assert safe_url("https://h/p?token=1") == "https://h/p"
    assert HttpResponse(200, {"Content-Type": "a"}, b"").header("content-type") == "a"


def test_file_ledger_round_trip(tmp_path):
    ledger = FileLedger(tmp_path / "state" / "runners.ledger")
    assert ledger.pending() == ()
    ledger.record("cqa-rev-a")
    ledger.record("cqa-rev-b")
    ledger.record("cqa-rev-a")
    assert ledger.pending() == ("cqa-rev-a", "cqa-rev-b")
    ledger.clear("cqa-rev-a")
    assert FileLedger(tmp_path / "state" / "runners.ledger").pending() == ("cqa-rev-b",)


def test_only_one_review_at_a_time(tmp_path):
    lock = tmp_path / "review.lock"
    with (
        single_review_lock(lock),
        pytest.raises(ReviewInProgressError),
        single_review_lock(lock),
    ):
        pass
    with single_review_lock(lock):
        pass


class _StreamHandler(BaseHTTPRequestHandler):
    """HTTP/1.0, close-delimited bodies, so each write reaches the client
    as it happens."""

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            self._route(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _route(self, body):
        if self.path.startswith("/silent"):
            time.sleep(1.0)
            return
        status = 500 if self.path.startswith("/error") else 200
        self.send_response(status)
        self.end_headers()
        self.wfile.flush()
        steps = {
            "/stream": [b"\x01one\n", b"\x01two\n"],
            "/headers-only": [],
            "/stall": [b"\x01part"],
            "/echo": [f"{self.headers['Content-Length']}:".encode() + body],
            "/big": [b"x" * 100],
            "/error": [b"nope"],
        }[self.path.split("?")[0]]
        for chunk in steps:
            self.wfile.write(chunk)
            self.wfile.flush()
            time.sleep(0.05)
        if self.path.split("?")[0] in {"/headers-only", "/stall"}:
            time.sleep(1.0)

    def log_message(self, *args):
        pass


@pytest.fixture
def stream_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StreamHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _streaming(**kwargs):
    return UrllibStreamingTransport(allowed_schemes=frozenset({"http"}), **kwargs)


def _stream(url, window, body=b"", **kwargs):
    return _streaming(**kwargs).stream("POST", url, {}, body, window)


def test_stream_reads_a_body_written_in_pieces(stream_server):
    resp = _stream(f"{stream_server}/stream", StreamWindow(5.0, 1.0))
    assert (resp.status, resp.body) == (200, b"\x01one\n\x01two\n")


def test_stream_sends_the_body_with_its_length(stream_server):
    resp = _stream(f"{stream_server}/echo?x=1", StreamWindow(5.0), body=b"abc")
    assert resp.body == b"3:abc"
    assert _stream(f"{stream_server}/echo", StreamWindow(5.0)).body == b"0:"


@pytest.mark.parametrize("path", ["/silent", "/headers-only"])
def test_a_silent_response_fails_at_the_first_byte_deadline(stream_server, path):
    started = time.monotonic()
    with pytest.raises(
        StreamTimeoutError, match="no response byte within 0.2s"
    ) as info:
        _stream(f"{stream_server}{path}", StreamWindow(5.0, 0.2))
    assert time.monotonic() - started < 0.9
    assert info.value.first_byte is True
    assert info.value.received == b""


def test_a_stalled_response_keeps_the_bytes_that_arrived(stream_server):
    with pytest.raises(StreamTimeoutError, match="incomplete after 5 byte") as info:
        _stream(f"{stream_server}/stall", StreamWindow(0.4, 0.2))
    assert info.value.first_byte is False
    assert info.value.received == b"\x01part"


def test_without_a_first_byte_window_only_the_total_applies(stream_server):
    with pytest.raises(
        StreamTimeoutError, match="no response byte|within 0.3s"
    ) as info:
        _stream(f"{stream_server}/silent", StreamWindow(0.3))
    assert info.value.first_byte is False


def test_stream_caps_size_returns_errors_and_refuses_other_schemes(stream_server):
    with pytest.raises(BoundaryError, match="exceeded"):
        _stream(f"{stream_server}/big", StreamWindow(5.0), max_bytes=10)
    assert _stream(f"{stream_server}/error", StreamWindow(5.0)).status == 500
    with pytest.raises(BoundaryError, match="scheme"):
        UrllibStreamingTransport().stream(
            "POST", f"{stream_server}/stream", {}, b"", StreamWindow(1.0)
        )
    with pytest.raises(BoundaryError, match="failed"):
        _stream("http://127.0.0.1:1/x?secret=1", StreamWindow(1.0))


def test_stream_window_waits_are_measured_from_the_request_start():
    window = StreamWindow(10.0, 3.0)
    assert window.wait_s(1.0, got_any=False) == 2.0
    assert window.wait_s(1.0, got_any=True) == 9.0
    assert StreamWindow(10.0).wait_s(4.0, got_any=False) == 6.0
