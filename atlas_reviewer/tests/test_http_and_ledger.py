# SPDX-License-Identifier: MIT
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from atlas_reviewer.http import HttpResponse, UrllibTransport, safe_url
from atlas_reviewer.ledger import FileLedger, ReviewInProgressError, single_review_lock
from atlas_reviewer.ports import BoundaryError


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
