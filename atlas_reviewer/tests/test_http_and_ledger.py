# SPDX-License-Identifier: MIT
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def test_a_zero_byte_cap_is_a_cap_not_the_default(server, stream_server):
    with pytest.raises(BoundaryError, match="exceeded 0 bytes"):
        _transport().request("GET", f"{server}/ok", {}, None, 5, max_bytes=0)
    with pytest.raises(BoundaryError, match="exceeded 0 bytes"):
        _stream(f"{stream_server}/stream", StreamWindow(5.0), max_bytes=0)


def test_transport_refuses_plain_http_by_default_and_wraps_connection_errors():
    with pytest.raises(BoundaryError, match="scheme"):
        UrllibTransport().request("GET", "http://127.0.0.1:1/x", {}, None, 1)
    with pytest.raises(BoundaryError, match="failed"):
        _transport().request("GET", "http://127.0.0.1:1/x?secret=1", {}, None, 1)


def test_safe_url_drops_query_and_header_lookup_is_case_insensitive():
    assert safe_url("https://h/p?token=1") == "https://h/p"
    assert safe_url("https://user:pa%40ss@h:8443/p") == "https://h:8443/p"
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


@pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="/proc/self/fd is how this test maps an fsynced fd to a path",
)
def test_ledger_writes_and_their_directory_are_synced(tmp_path, monkeypatch):
    import os

    synced: set[Path] = set()
    real = os.fsync

    def fsync(fd):
        synced.add(Path(os.readlink(f"/proc/self/fd/{fd}")))
        real(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    state = tmp_path / "state"
    path = state / "nested" / "runners.ledger"
    ledger = FileLedger(path)
    ledger.record("a")
    assert synced == {tmp_path, state, state / "nested", path}
    synced.clear()
    ledger.clear("a")
    assert synced == {state / "nested", state / "nested" / "runners.ledger.clearing"}
    assert ledger.pending() == ()


def test_a_ledger_named_like_its_temp_file_still_clears(tmp_path):
    ledger = FileLedger(tmp_path / "runners.tmp")
    ledger.record("a")
    ledger.record("b")
    ledger.clear("a")
    assert ledger.pending() == ("b",)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["runners.tmp"]


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


# A slow route sleeps _SLOW_S (or trickles about that long) and only then
# sets `slow_finished`. A cutoff test passes when the client has already
# returned with that still unset, so the assertion is not a wall-clock bound.
_SLOW_S = 3.0
_TRICKLE_BYTES = int(_SLOW_S / 0.05)


class _StreamHandler(BaseHTTPRequestHandler):
    """HTTP/1.0, close-delimited bodies, so each write reaches the client
    as it happens. `slow_finished` is set only once a slow route has run
    its full delay."""

    def _finish_slow(self) -> None:
        done = getattr(self.server, "slow_finished", None)
        if done is not None:
            done.set()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            self._route(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _route(self, body):
        if self.path.startswith("/trickle-headers"):
            self.wfile.write(b"HTTP/1.0 200 OK\r\nX-Slow: ")
            for _ in range(_TRICKLE_BYTES):
                self.wfile.write(b"a")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"\r\n\r\nlate body")
            self._finish_slow()
            return
        if self.path.startswith("/trickle-first-chunk"):
            self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            for _ in range(_TRICKLE_BYTES):
                self.wfile.write(b"0")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"5\r\n\x01late\r\n0\r\n\r\n")
            self._finish_slow()
            return
        if self.path.startswith("/trickle-chunks"):
            close = b"Connection: close\r\n" if "close" in self.path else b""
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n" + close + b"\r\n"
                b"5\r\n\x01part\r\n"
            )
            for _ in range(_TRICKLE_BYTES):
                self.wfile.write(b"0")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"\r\n\r\n")
            self._finish_slow()
            return
        if self.path.startswith("/silent"):
            time.sleep(_SLOW_S)
            self._finish_slow()
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
            time.sleep(_SLOW_S)
            self._finish_slow()

    def log_message(self, *args):
        pass


class _Running:
    """The URL, plus the server's own finished-event, so one test's still
    trickling handler cannot set the next test's."""

    def __init__(self, url: str, slow_finished: threading.Event) -> None:
        self.url = url
        self.slow_finished = slow_finished

    def __str__(self) -> str:
        return self.url


@pytest.fixture
def stream_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StreamHandler)
    srv.slow_finished = threading.Event()  # type: ignore[attr-defined]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield _Running(f"http://127.0.0.1:{srv.server_address[1]}", srv.slow_finished)
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
    with pytest.raises(
        StreamTimeoutError, match="no response byte within 0.2s"
    ) as info:
        _stream(f"{stream_server}{path}", StreamWindow(5.0, 0.2))
    assert not stream_server.slow_finished.is_set()
    assert info.value.first_byte is True
    assert info.value.received == b""


def test_a_stalled_response_keeps_the_bytes_that_arrived(stream_server):
    with pytest.raises(StreamTimeoutError, match="incomplete after 5 byte") as info:
        _stream(f"{stream_server}/stall", StreamWindow(0.4, 0.2))
    assert info.value.first_byte is False
    assert info.value.received == b"\x01part"


def test_without_a_first_byte_window_only_the_total_applies(stream_server):
    with pytest.raises(
        StreamTimeoutError, match=r"response incomplete after 0 byte\(s\) within 0.3s"
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


@pytest.mark.parametrize(
    ("window", "first_byte"),
    [(StreamWindow(5.0, 0.3), True), (StreamWindow(0.3), False)],
)
def test_trickled_headers_cannot_outlast_the_deadline(
    stream_server, window, first_byte
):
    """Pilot 3, transport finding: every header byte restarted the socket
    timeout, so headers trickled over 2 s passed a 0.3 s window."""
    with pytest.raises(StreamTimeoutError, match="within 0.3s") as info:
        _stream(f"{stream_server}/trickle-headers", window)
    assert not stream_server.slow_finished.is_set()
    assert info.value.first_byte is first_byte
    assert info.value.received == b""


@pytest.mark.parametrize("path", ["/trickle-chunks", "/trickle-chunks?close"])
def test_trickled_chunk_framing_cannot_outlast_the_total_deadline(stream_server, path):
    """A chunk-size line trickled one byte at a time restarted the socket
    timeout on every byte inside one `read1`, past the window. With
    `Connection: close`, getresponse() clears `conn.sock`, so the cutoff
    must hold the socket itself."""
    with pytest.raises(StreamTimeoutError, match="within 0.4s") as info:
        _stream(f"{stream_server}{path}", StreamWindow(0.4, 0.2))
    assert not stream_server.slow_finished.is_set()
    assert info.value.received == b"\x01part"


def test_a_trickled_first_chunk_line_fails_at_the_first_byte_deadline(
    stream_server,
):
    """Headers on time, then the first chunk-size line trickled: the body's
    first byte must still arrive within the first-byte window, not the
    total."""
    with pytest.raises(
        StreamTimeoutError, match="no response byte within 0.2s"
    ) as info:
        _stream(f"{stream_server}/trickle-first-chunk", StreamWindow(5.0, 0.2))
    assert not stream_server.slow_finished.is_set()
    assert info.value.first_byte is True
    assert info.value.received == b""


def test_a_per_request_limit_below_the_transport_cap_is_enforced(stream_server):
    transport = _streaming(max_bytes=1000)
    url = f"{stream_server}/big"
    assert len(transport.stream("POST", url, {}, b"", StreamWindow(5.0)).body) == 100
    with pytest.raises(BoundaryError, match="exceeded 10 bytes"):
        transport.stream("POST", url, {}, b"", StreamWindow(5.0), max_bytes=10)
    with pytest.raises(BoundaryError, match="exceeded 0 bytes"):
        transport.stream("POST", url, {}, b"", StreamWindow(5.0), max_bytes=0)


def test_a_fast_exchange_is_not_cut_and_leaves_no_timer_running(stream_server):
    """No sleep. A cancelled timer has `finished` set while its thread is
    still unwinding, so the check is the armed ones, not a thread count
    taken after a fixed pause."""
    baseline = {t for t in threading.enumerate() if isinstance(t, threading.Timer)}
    for _ in range(5):
        assert _stream(f"{stream_server}/stream", StreamWindow(5.0, 1.0)).status == 200
    armed = [
        t
        for t in threading.enumerate()
        if isinstance(t, threading.Timer)
        and t not in baseline
        and not t.finished.is_set()
    ]
    assert armed == []


def test_the_cutoff_marks_itself_fired_even_before_a_socket_exists():
    import http.client

    from atlas_reviewer.http import _Cutoff

    conn = http.client.HTTPConnection("127.0.0.1", 1)
    with _Cutoff(lambda: conn.sock, 0.0) as cutoff:
        assert cutoff.fired.wait(1.0)
    assert conn.sock is None
