# SPDX-License-Identifier: MIT
"""Live GitHub and Sprites adapters, driven through a recording transport.
No test here touches the network."""

import json

import pytest

from atlas_reviewer.fakes import StaticToken
from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.pagination import next_link
from atlas_reviewer.ports import BoundaryError, NotFoundError
from atlas_reviewer.runner import DENY_ALL
from atlas_reviewer.sprites_api import EXEC_STDIN_MAX_BYTES, SpritesClient

from .helpers import HEAD, fake_token

TOKEN = fake_token("ghs_")
API = "https://api.github.com"
NAME = "cqa-rev-20261106-230000-abcdef"


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, headers, body, timeout_s, max_bytes=None):
        self.requests.append((method, url, dict(headers), body, timeout_s, max_bytes))
        return self.responses.pop(0)


def ok(payload=None, status=200, body=None, headers=None):
    raw = (
        body
        if body is not None
        else json.dumps(payload if payload is not None else {}).encode()
    )
    return HttpResponse(status, headers or {}, raw)


def github(transport, **kw):
    return GitHubClient(transport, StaticToken(TOKEN), **kw)


def page(key, items, next_url=None):
    headers = {"Link": f'<{next_url}>; rel="next", <{API}/x?page=9>; rel="last"'}
    return ok({key: items}, headers=headers if next_url else None)


def test_github_client_only_ever_sends_get():
    t = Recorder(
        ok({"x": 1}),
        ok(body=b"diff"),
        page("check_runs", []),
        page("workflow_runs", []),
        page("jobs", []),
        page("artifacts", []),
        ok(body=b"log"),
        ok(body=b"zip"),
        ok(body=b"tar"),
        ok({"x": 1}),
    )
    gh = github(t)
    gh.get_pull("o/r", 1)
    gh.get_pull_diff("o/r", 1)
    gh.list_check_runs("o/r", HEAD)
    gh.list_workflow_runs("o/r", "feat/a b")
    gh.list_run_jobs("o/r", 5)
    gh.list_run_artifacts("o/r", 5)
    assert gh.get_job_logs("o/r", 7, max_bytes=100) == b"log"
    assert gh.download_artifact("o/r", 9, max_bytes=200) == b"zip"
    gh.get_tarball("o/r", HEAD)
    gh.get_issue("o/r", 7)
    assert {r[0] for r in t.requests} == {"GET"}
    assert all(r[3] is None for r in t.requests)
    assert t.requests[0][2]["Authorization"] == f"Bearer {TOKEN}"
    assert t.requests[1][2]["Accept"] == "application/vnd.github.diff"
    assert "branch=feat%2Fa%20b" in t.requests[3][1]
    assert t.requests[4][1] == f"{API}/repos/o/r/actions/runs/5/jobs?per_page=100"
    assert (t.requests[6][1], t.requests[6][5]) == (
        f"{API}/repos/o/r/actions/jobs/7/logs",
        100,
    )
    assert (t.requests[7][1], t.requests[7][5]) == (
        f"{API}/repos/o/r/actions/artifacts/9/zip",
        200,
    )


@pytest.mark.parametrize(
    "method,key",
    [
        ("list_check_runs", "check_runs"),
        ("list_workflow_runs", "workflow_runs"),
        ("list_run_jobs", "jobs"),
        ("list_run_artifacts", "artifacts"),
    ],
)
def test_every_list_follows_link_headers_to_the_last_page(method, key):
    t = Recorder(
        page(key, [{"id": 1}], f"{API}/next?page=2"),
        page(key, [{"id": 2}], f"{API}/next?page=3"),
        page(key, [{"id": 3}]),
    )
    listing = getattr(github(t), method)("o/r", "5")
    assert [i["id"] for i in listing.items] == [1, 2, 3]
    assert (listing.truncated, listing.pages_read) == (False, 3)
    assert [r[1] for r in t.requests[1:]] == [
        f"{API}/next?page=2",
        f"{API}/next?page=3",
    ]
    assert all(r[2]["Authorization"] == f"Bearer {TOKEN}" for r in t.requests)


def test_page_cap_stops_and_reports_truncation():
    t = Recorder(
        *[page("jobs", [{"id": i}], f"{API}/next?page={i + 2}") for i in range(3)]
    )
    listing = github(t, max_pages=2).list_run_jobs("o/r", 5)
    assert [i["id"] for i in listing.items] == [0, 1]
    assert (listing.truncated, listing.pages_read) == (True, 2)
    assert len(t.requests) == 2


def test_pagination_link_off_the_api_is_refused_before_sending_the_token():
    t = Recorder(page("jobs", [], "https://evil.example/steal?page=2"))
    with pytest.raises(BoundaryError, match="off the API: https://evil.example/steal"):
        github(t).list_run_jobs("o/r", 5)
    assert len(t.requests) == 1


def test_max_pages_must_be_positive():
    with pytest.raises(ValueError):
        github(Recorder(), max_pages=0)


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("", None),
        (f'<{API}/a?page=2>; rel="next"', f"{API}/a?page=2"),
        (
            f'<{API}/a?page=1>; rel="prev", <{API}/a?page=3>; rel="next"',
            f"{API}/a?page=3",
        ),
        (f'<{API}/a?page=5>; rel="last"', None),
        (f"<{API}/a?page=2>; REL=next", f"{API}/a?page=2"),
        (f'<{API}/a?page=2>; rel="next last"', f"{API}/a?page=2"),
        ("garbage", None),
    ],
)
def test_next_link_parsing(header, expected):
    assert next_link(header) == expected


def test_list_without_its_array_is_a_boundary_error():
    with pytest.raises(BoundaryError, match="no 'jobs' array"):
        github(Recorder(ok({"jobs": "nope"}))).list_run_jobs("o/r", 5)


def test_redirects_are_followed_without_credentials():
    t = Recorder(
        ok(
            status=302,
            body=b"",
            headers={"Location": "https://blob.example/logs.txt?sig=1"},
        ),
        ok(body=b"logbytes"),
    )
    assert github(t).get_job_logs("o/r", 5, max_bytes=50) == b"logbytes"
    follow = t.requests[1]
    assert follow[1] == "https://blob.example/logs.txt?sig=1"
    assert "Authorization" not in follow[2]
    assert follow[5] == 50


@pytest.mark.parametrize(
    "response,error",
    [
        (ok(status=404), NotFoundError),
        (ok(status=403), BoundaryError),
        (ok(body=b"<html>"), BoundaryError),
        (ok(body=b"[1]"), BoundaryError),
        (
            ok(status=302, body=b"", headers={"Location": "http://insecure.example/x"}),
            BoundaryError,
        ),
    ],
)
def test_github_errors_are_boundary_errors(response, error):
    with pytest.raises(error):
        github(Recorder(response)).get_pull("o/r", 1)


def test_github_error_messages_do_not_carry_query_strings():
    with pytest.raises(BoundaryError) as info:
        github(Recorder(ok(status=500))).list_check_runs("o/r", HEAD)
    assert "per_page" not in str(info.value)


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
    exec_request = t.requests[4]
    assert exec_request[1].endswith("/exec?cmd=sh&cmd=-c&cmd=echo+hi&stdin=true")
    assert exec_request[2]["Content-Type"] == "application/octet-stream"
    assert exec_request[3] == b"stdin"
    assert exec_request[4] == 5.0


def test_sprites_exec_without_stdin_sends_no_body_and_no_stdin_flag():
    t = Recorder(ok(body=b"out"))
    SpritesClient(t, "t").exec(NAME, ("true",), b"", 5.0)
    assert t.requests[0][1].endswith("/exec?cmd=true")
    assert t.requests[0][3] is None
    assert "Content-Type" not in t.requests[0][2]


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
    assert t.requests[0][0] == "DELETE"
    assert sc.exists(NAME) is False
    assert sc.exists(NAME) is True
    with pytest.raises(BoundaryError):
        sc.exists(NAME)


def test_sprites_client_refuses_to_touch_sprites_it_did_not_name():
    sc = SpritesClient(Recorder(), "org/1/secret")
    for call in (sc.create, sc.delete, sc.exists):
        with pytest.raises(BoundaryError, match="refusing"):
            call("web-terminal")


@pytest.mark.parametrize("body", [b"nope", b"[]"])
def test_sprites_policy_read_back_must_be_an_object(body):
    with pytest.raises(BoundaryError):
        SpritesClient(Recorder(ok(body=body)), "t").get_network_policy(NAME)
