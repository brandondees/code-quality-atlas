# SPDX-License-Identifier: MIT
"""Live GitHub and Sprites adapters, driven through a recording transport.
No test here touches the network."""

import json

import pytest

from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.ports import BoundaryError, NotFoundError
from atlas_reviewer.runner import DENY_ALL
from atlas_reviewer.sprites_api import SpritesClient

from .helpers import HEAD, fake_token

TOKEN = fake_token("ghs_")
NAME = "cqa-rev-20261106-230000-abcdef"


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, headers, body, timeout_s):
        self.requests.append((method, url, dict(headers), body, timeout_s))
        return self.responses.pop(0)


def ok(payload=None, status=200, body=None, headers=None):
    raw = (
        body
        if body is not None
        else json.dumps(payload if payload is not None else {}).encode()
    )
    return HttpResponse(status, headers or {}, raw)


def test_github_client_only_ever_sends_get():
    t = Recorder(*[ok({"x": 1}) for _ in range(8)])
    gh = GitHubClient(t, TOKEN)
    gh.get_pull("o/r", 1)
    gh.get_pull_diff("o/r", 1)
    gh.list_check_runs("o/r", HEAD)
    gh.list_workflow_runs("o/r", "feat/a b")
    gh.list_run_artifacts("o/r", 5)
    gh.get_run_logs("o/r", 5)
    gh.get_tarball("o/r", HEAD)
    gh.get_issue("o/r", 7)
    assert {r[0] for r in t.requests} == {"GET"}
    assert all(r[3] is None for r in t.requests)
    assert t.requests[0][2]["Authorization"] == f"Bearer {TOKEN}"
    assert t.requests[1][2]["Accept"] == "application/vnd.github.diff"
    assert "branch=feat%2Fa%20b" in t.requests[3][1]


def test_redirects_are_followed_without_credentials():
    t = Recorder(
        ok(
            status=302,
            body=b"",
            headers={"Location": "https://blob.example/logs.zip?sig=1"},
        ),
        ok(body=b"zipbytes"),
    )
    assert GitHubClient(t, TOKEN).get_run_logs("o/r", 5) == b"zipbytes"
    follow = t.requests[1]
    assert follow[1] == "https://blob.example/logs.zip?sig=1"
    assert "Authorization" not in follow[2]


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
        GitHubClient(Recorder(response), TOKEN).get_pull("o/r", 1)


def test_github_error_messages_do_not_carry_query_strings():
    with pytest.raises(BoundaryError) as info:
        GitHubClient(Recorder(ok(status=500)), TOKEN).list_check_runs("o/r", HEAD)
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
    assert "cmd=sh&cmd=-c&cmd=echo+hi" in exec_request[1]
    assert exec_request[3] == b"stdin"
    assert exec_request[4] == 5.0


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
