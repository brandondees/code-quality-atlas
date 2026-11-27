# SPDX-License-Identifier: MIT
"""The live Sprites adapter, driven through a recording transport.
No test here touches the network."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import pytest

from atlas_reviewer.http import StreamWindow, UrllibStreamingTransport
from atlas_reviewer.ports import BoundaryError, NotFoundError, RefusedError
from atlas_reviewer.runner import DENY_ALL
from atlas_reviewer.sprites_api import EXEC_STDIN_MAX_BYTES, SpritesClient, exec_request

from .helpers import SOURCE_TARBALL, Recorder, fake_token, ok

API_S = "https://api.sprites.dev"
NAME = "cqa-rev-20261106-230000-abcdef"


def test_sprites_client_request_shapes():
    t = Recorder(
        *[ok(status=201)],
        ok(status=204),
        ok({"rules": list(DENY_ALL)}),
        ok(status=204),
        ok(body=b"out"),
    )
    sc = SpritesClient(t, "org/1/secret")
    sc.create(NAME)
    sc.set_network_policy(NAME, DENY_ALL)
    assert sc.get_network_policy(NAME) == {"rules": [{"action": "deny", "domain": "*"}]}
    sc.set_memory_limit(NAME, 1024)
    assert sc.exec(NAME, ("sh", "-c", "echo hi"), b"stdin", 5.0) == b"out"
    methods_paths = [(r[0], r[1].split("?")[0]) for r in t.requests]
    assert methods_paths == [
        ("POST", "https://api.sprites.dev/v1/sprites"),
        ("POST", f"https://api.sprites.dev/v1/sprites/{NAME}/policy/network"),
        ("GET", f"https://api.sprites.dev/v1/sprites/{NAME}/policy/network"),
        ("POST", f"https://api.sprites.dev/v1/sprites/{NAME}/policy/resources"),
        ("POST", f"https://api.sprites.dev/v1/sprites/{NAME}/exec"),
    ]
    assert json.loads(t.requests[1][3]) == {
        "rules": [{"action": "deny", "domain": "*"}]
    }
    assert json.loads(t.requests[3][3]) == {"memory": {"limit_mb": 1024}}
    assert [r[4] for r in t.requests[:4]] == [StreamWindow(30.0)] * 4
    assert t.requests[2][3] is None
    exec_request = t.requests[4]
    assert exec_request[1].endswith("/exec?cmd=sh&cmd=-c&cmd=echo+hi&stdin=true")
    assert exec_request[2]["Content-Type"] == "application/octet-stream"
    assert exec_request[2]["Content-Length"] == "5"
    assert exec_request[3] == b"stdin"
    assert exec_request[4] == StreamWindow(5.0, None)


def test_sprites_exec_without_input_has_the_same_shape_with_an_empty_body():
    t = Recorder(ok(body=b"out"))
    SpritesClient(t, "t").exec(NAME, ("true",), b"", 5.0, first_byte_s=2.0)
    method, url, headers, body, window, _ = t.requests[0]
    assert (method, body, window) == ("POST", b"", StreamWindow(5.0, 2.0))
    assert url.endswith("/exec?cmd=true&stdin=true")
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["Content-Length"] == "0"


def test_exec_request_is_the_only_shape_and_uses_no_env_dir_path_or_tty():
    with_input = exec_request(API_S, f"/v1/sprites/{NAME}", ("sh", "-c", "x"), b"ab")
    without = exec_request(API_S, f"/v1/sprites/{NAME}", ("sh", "-c", "x"), b"")
    for request in (with_input, without):
        keys = [k for k, _ in parse_qsl(urlsplit(request.url).query)]
        assert keys == ["cmd", "cmd", "cmd", "stdin"]
        assert set(request.headers) == {"Content-Type", "Content-Length", "Connection"}
        assert request.headers["Content-Length"] == str(len(request.body))
    assert (with_input.body, without.body) == (b"ab", b"")


def test_sprites_exec_http_errors_are_checked_like_other_calls():
    with pytest.raises(NotFoundError):
        SpritesClient(Recorder(ok(status=404)), "t").exec(NAME, ("true",), b"", 5.0)
    with pytest.raises(BoundaryError, match="HTTP 500"):
        SpritesClient(Recorder(ok(status=500)), "t").exec(NAME, ("true",), b"", 5.0)


@pytest.mark.parametrize("status", [400, 409, 422])
def test_a_create_answered_with_a_4xx_is_refused(status):
    with pytest.raises(RefusedError, match=f"HTTP {status}"):
        SpritesClient(Recorder(ok(status=status)), "t").create(NAME)


def test_a_create_answered_with_a_5xx_is_not_a_refusal():
    with pytest.raises(BoundaryError) as caught:
        SpritesClient(Recorder(ok(status=503)), "t").create(NAME)
    assert not isinstance(caught.value, RefusedError)


@pytest.mark.parametrize(
    "argv,stdin,match",
    [
        ((), b"", "at least one cmd"),
        (("cat",), b"x" * (EXEC_STDIN_MAX_BYTES + 1), "over the documented"),
    ],
)
def test_sprites_exec_refuses_before_sending(argv, stdin, match):
    t = Recorder()
    with pytest.raises(BoundaryError, match=match):
        SpritesClient(t, "t").exec(NAME, argv, stdin, 5.0)
    assert t.requests == []


def test_sprites_delete_and_exists():
    t = Recorder(ok(status=204), ok(status=404), ok(), ok(status=500))
    sc = SpritesClient(t, "org/1/secret")
    sc.delete(NAME)
    assert (t.requests[0][0], t.requests[0][3]) == ("DELETE", None)
    assert sc.exists(NAME) is False
    assert sc.exists(NAME) is True
    with pytest.raises(BoundaryError):
        sc.exists(NAME)


def test_sprites_client_refuses_to_touch_sprites_it_did_not_name():
    sc = SpritesClient(Recorder(), "org/1/secret")
    for call in (sc.create, sc.delete, sc.exists):
        with pytest.raises(BoundaryError, match="refusing"):
            call("web-terminal")


@pytest.mark.parametrize("body", [b"nope", b"[]", b'{"a": "\xff"}'])
def test_sprites_policy_read_back_must_be_an_object(body):
    with pytest.raises(BoundaryError):
        SpritesClient(Recorder(ok(body=body)), "t").get_network_policy(NAME)


# The handler trickles a response for _TRICKLE_S and only then sets
# `finished`; a bounded call returns with it still unset, so no assertion
# here is a wall-clock bound.
_TRICKLE_S = 3.0


class _TrickleHandler(BaseHTTPRequestHandler):
    def _trickle(self):
        try:
            self.wfile.write(b"HTTP/1.0 204 No Content\r\nX-Slow: ")
            for _ in range(int(_TRICKLE_S / 0.05)):
                self.wfile.write(b"a")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            return
        self.server.finished.set()  # type: ignore[attr-defined]

    do_DELETE = do_GET = _trickle

    def log_message(self, *args):
        pass


@pytest.fixture
def trickling_sprites():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _TrickleHandler)
    srv.finished = threading.Event()  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client = SpritesClient(
        UrllibStreamingTransport(allowed_schemes=frozenset({"http"})),
        "t",
        api_url=f"http://127.0.0.1:{srv.server_address[1]}",
        timeout_s=0.3,
    )
    yield client, srv.finished
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize("call", ["delete", "exists"])
def test_a_trickled_control_plane_response_cannot_outlast_the_client_timeout(
    trickling_sprites, call
):
    """A socket timeout restarts on every byte, so a DELETE or existence
    check trickled a byte at a time could hold cleanup -- and the lock
    the watchdog and final destroy share -- open indefinitely."""
    client, finished = trickling_sprites
    with pytest.raises(BoundaryError, match="within 0.3s"):
        getattr(client, call)(NAME)
    assert not finished.is_set()


class _SpritesServer:
    """Answers a whole review over the real `SpritesClient`, recording every
    request the client builds."""

    def __init__(self):
        self.requests = []
        self.control_headers = []
        self.streams = []
        self.deleted = False
        self.base = f"{API_S}/v1/sprites/{NAME}"

    def _control(self, method, path, window, body, headers=None):
        self.requests.append((method, path, window, body))
        self.control_headers.append(dict(headers or {}))
        if method == "DELETE":
            self.deleted = True
            return ok(status=204)
        if method == "GET" and path == self.base:
            return ok(status=404 if self.deleted else 200)
        if method == "GET":
            return ok({"rules": list(DENY_ALL)})
        return ok(status=204)

    def stream(self, method, url, headers, body, window, max_bytes=None):
        path = url.split("?")[0]
        if not path.endswith("/exec"):
            return self._control(method, path, window, body, headers)
        self.streams.append((method, url, dict(headers), body, window))
        script = [v for k, v in parse_qsl(urlsplit(url).query) if k == "cmd"][-1]
        out = (
            "atlas-probe:present:python3:/usr/bin/python3:/usr/bin/python3.13\n"
            "atlas-probe:present:sh:/usr/bin/sh:/usr/bin/dash"
            if "atlas-probe" in script
            else "atlas-python:/usr/bin/python3:3.12.3"
            if "atlas-python" in script
            else str(len(body))
        )
        return ok(
            body=f"\x01__ATLAS_START__\n{out}\n__ATLAS_EXIT__=0\n\x03\x00".encode()
        )


def _review_over_http(tools, token="org/1/secret"):
    from atlas_reviewer.clock import SystemClock
    from atlas_reviewer.fakes import MemoryLedger
    from atlas_reviewer.runner import RunnerJob, run_disposable

    server = _SpritesServer()
    outcome = run_disposable(
        SpritesClient(server, token),
        MemoryLedger(),
        RunnerJob(SOURCE_TARBALL, tools),
        name=NAME,
        deadline_s=600.0,
        clock=SystemClock(),
    )
    return server, outcome


def test_every_exec_in_a_review_is_built_the_same_way():
    """D28: the tool check and unpack worked live and the tool version
    exec hung. Every exec, whatever its stage, must leave the client in
    one shape: same query keys, headers, minimal `env -i` + `sh -c` wrapper
    and EOF rule. D29: no `dir`/`env` query parameter either; the
    wrapper alone sets the environment."""
    from atlas_reviewer.runner import (
        DEFAULT_TOOLS,
        MINIMAL_ENV,
        START_MARKER,
        TRIVIAL_TOOL,
    )

    server, outcome = _review_over_http((*DEFAULT_TOOLS, TRIVIAL_TOOL))
    assert outcome.report.status.value == "completed"
    assert len(server.streams) == 8
    for method, url, headers, body, window in server.streams:
        query = parse_qsl(urlsplit(url).query)
        argv = [v for k, v in query if k == "cmd"]
        assert method == "POST"
        assert [k for k, _ in query] == ["cmd"] * 8 + ["stdin"]
        assert dict(query)["stdin"] == "true"
        assert set(headers) == {
            "Authorization", "User-Agent", "Content-Type", "Content-Length", "Connection",
        }  # fmt: skip
        assert headers["Content-Type"] == "application/octet-stream"
        assert headers["Content-Length"] == str(len(body))
        assert argv[:7] == ["/usr/bin/env", "-i", *MINIMAL_ENV, "/bin/sh", "-c"]
        assert argv[7].startswith(f"echo {START_MARKER}; ")
        assert argv[7].endswith("; echo __ATLAS_EXIT__=$?")
        feed = f"head -c {len(body)} | {{ " if body else "{ "
        assert argv[7].startswith(f"echo {START_MARKER}; {feed}")
        assert argv[7].count("</dev/null") == (0 if body else 1)
        assert (window.first_byte_s is None) == bool(body)


def test_a_review_runs_python_tools_only_by_the_resolved_absolute_path():
    from atlas_reviewer.runner import DEFAULT_TOOLS

    server, outcome = _review_over_http(DEFAULT_TOOLS)
    scripts = [
        [v for k, v in parse_qsl(urlsplit(s[1]).query) if k == "cmd"][-1]
        for s in server.streams
    ]
    tool_scripts = [s for s in scripts if "compileall" in s or "--version" in s]
    assert len(tool_scripts) == 2
    assert all("/usr/bin/python3 -I " in s for s in tool_scripts)
    assert not any(" python3 " in s or "/.sprite/bin" in s for s in tool_scripts)
    assert outcome.python is not None
    assert outcome.python.path == "/usr/bin/python3"


def test_a_review_sends_each_exec_its_own_budget_not_the_30s_default():
    from atlas_reviewer.runner import (
        FIRST_FRAME_BUDGET_S,
        PROBE_BUDGET_S,
        UNPACK_BUDGET_S,
        UPLOAD_BUDGET_S,
        ToolSpec,
    )

    tool = ToolSpec(
        "t", "python3", "{python} -I --version", "{python} -I -c pass", timeout_s=120
    )
    server, outcome = _review_over_http((tool,))
    assert outcome.report.cleanup.value == "destroyed (verified absent)"
    windows = [s[4] for s in server.streams]
    assert windows == [
        StreamWindow(PROBE_BUDGET_S, FIRST_FRAME_BUDGET_S),
        StreamWindow(PROBE_BUDGET_S, FIRST_FRAME_BUDGET_S),
        StreamWindow(UPLOAD_BUDGET_S, None),
        StreamWindow(UNPACK_BUDGET_S, FIRST_FRAME_BUDGET_S),
        StreamWindow(135.0, FIRST_FRAME_BUDGET_S),
        StreamWindow(135.0, FIRST_FRAME_BUDGET_S),
    ]
    assert [s[3] for s in server.streams][:3] == [b"", b"", SOURCE_TARBALL]
    assert {r[2] for r in server.requests} == {StreamWindow(30.0)}


def test_the_token_goes_only_in_the_authorization_header():
    """The credential boundary at the wire: across a whole review, the
    token is never in an exec's URL (its argv), stdin, or any other
    header, nor in a control-plane path or body."""
    from atlas_reviewer.runner import DEFAULT_TOOLS, TRIVIAL_TOOL

    token = fake_token("sprites_")
    server, outcome = _review_over_http((*DEFAULT_TOOLS, TRIVIAL_TOOL), token)
    assert outcome.report.status.value == "completed"
    exec_headers = [s[2] for s in server.streams]
    for headers in (*exec_headers, *server.control_headers):
        assert headers["Authorization"] == f"Bearer {token}"
        assert token not in json.dumps(
            {k: v for k, v in headers.items() if k != "Authorization"}
        )
    for _, url, _, body, _ in server.streams:
        assert token not in url
        assert token.encode() not in body
    for _, path, _, body in server.requests:
        assert token not in path
        assert body is None or token.encode() not in body
