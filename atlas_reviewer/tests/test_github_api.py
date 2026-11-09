# SPDX-License-Identifier: MIT
"""The live GitHub adapter, driven through a recording transport.
No test here touches the network."""

import pytest

from atlas_reviewer.fakes import StaticToken
from atlas_reviewer.github_api import GitHubClient
from atlas_reviewer.pagination import next_link
from atlas_reviewer.ports import BoundaryError, NotFoundError

from .helpers import HEAD, Recorder, fake_token, ok

TOKEN = fake_token("ghs_")
API = "https://api.github.com"


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
    assert "event=" not in t.requests[3][1]
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
        ("list_workflow_runs_at", "workflow_runs"),
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


def test_workflow_runs_at_a_sha_are_filtered_by_head_sha_server_side():
    t = Recorder(page("workflow_runs", []))
    github(t).list_workflow_runs_at("o/r", HEAD)
    assert t.requests[0][1] == (
        f"{API}/repos/o/r/actions/runs?per_page=100&head_sha={HEAD}"
    )


def test_pull_commits_are_a_paginated_array():
    link = {"Link": f'<{API}/next?page=2>; rel="next"'}
    t = Recorder(ok([{"sha": "a"}], headers=link), ok([{"sha": "b"}]))
    listing = github(t).list_pull_commits("o/r", 42)
    assert [c["sha"] for c in listing.items] == ["a", "b"]
    assert t.requests[0][1] == f"{API}/repos/o/r/pulls/42/commits?per_page=100"


def test_pull_commits_that_are_not_an_array_are_refused():
    with pytest.raises(BoundaryError, match="non-array"):
        github(Recorder(ok({"sha": "a"}))).list_pull_commits("o/r", 42)


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
        (f'<{API}/a?page=2>; title="a, b"; rel="next"', f"{API}/a?page=2"),
        (
            (
                f'<{API}/a?page=1>; title="x, <{API}/evil>; rel=next", '
                f'<{API}/a?page=3>; rel="next"'
            ),
            f"{API}/a?page=3",
        ),
        (f'<{API}/a?page=2>; title="say \\"hi\\", ok"; rel=next', f"{API}/a?page=2"),
        (f'<{API}/a?page=2>; rel="NEXT"', f"{API}/a?page=2"),
        (f'<{API}/a?page=2>; rel="prev"; rel="next"', None),
        (f'<{API}/a?q=a,b&page=2>; rel="next"', f"{API}/a?q=a,b&page=2"),
        (f'junk, <{API}/a?page=2>; rel="next"', f"{API}/a?page=2"),
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


def redirect(location, status=301):
    return ok(status=status, body=b"", headers={"Location": location})


def test_a_redirect_within_the_api_keeps_its_headers():
    moved = f"{API}/repositories/99/pulls/1"
    t = Recorder(redirect(moved), ok(body=b"diff"))
    assert github(t).get_pull_diff("o/r", 1) == "diff"
    follow = t.requests[1]
    assert follow[1] == moved
    assert follow[2]["Authorization"] == f"Bearer {TOKEN}"
    assert follow[2]["Accept"] == "application/vnd.github.diff"


def test_credentials_stay_dropped_once_a_redirect_chain_leaves_the_api():
    t = Recorder(
        redirect(f"{API}/repositories/99/actions/jobs/5/logs"),
        redirect("https://blob.example/logs.txt?sig=1", status=302),
        redirect(f"{API}/back-again", status=302),
        ok(body=b"logbytes"),
    )
    assert github(t).get_job_logs("o/r", 5, max_bytes=50) == b"logbytes"
    assert "Authorization" in t.requests[1][2]
    assert all("Authorization" not in r[2] for r in t.requests[2:])


def test_a_redirect_chain_is_bounded():
    t = Recorder(*[redirect(f"{API}/loop")] * 5)
    with pytest.raises(BoundaryError, match="HTTP 301"):
        github(t).get_pull("o/r", 1)
    assert len(t.requests) == 4


@pytest.mark.parametrize(
    "response,error",
    [
        (ok(status=404), NotFoundError),
        (ok(status=403), BoundaryError),
        (ok(body=b"<html>"), BoundaryError),
        (ok(body=b'{"a": "\xff"}'), BoundaryError),
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
