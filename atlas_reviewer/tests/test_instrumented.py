# SPDX-License-Identifier: MIT
"""`InstrumentedGitHub`: every read is one telemetry event labelled with
controller-side identifiers only, and a failed read is recorded and
re-raised."""

import pytest

from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.instrumented import InstrumentedGitHub
from atlas_reviewer.ports import GitHubReader, Listing, NotFoundError
from atlas_reviewer.telemetry import Telemetry

from .helpers import FIXTURE, HEAD, FakeClock

REPO = "example-org/example-app"


def test_every_read_is_one_event_with_its_size():
    t = Telemetry(FakeClock())
    inner = FixtureGitHub(FIXTURE)
    gh = InstrumentedGitHub(inner, t)
    gh.get_pull(REPO, 42)
    gh.get_pull_diff(REPO, 42)
    gh.list_pull_commits(REPO, 42)
    gh.list_check_runs(REPO, HEAD)
    gh.list_workflow_runs(REPO, "feature/secret-branch-name")
    gh.list_workflow_runs_at(REPO, HEAD)
    gh.list_run_jobs(REPO, 5001)
    gh.list_run_artifacts(REPO, 5001)
    log = gh.get_job_logs(REPO, 7001, 1_000_000)
    archive = gh.download_artifact(REPO, 9001, 1_000_000)
    gh.get_tarball(REPO, HEAD)
    gh.get_issue(REPO, 7)
    steps = [(e.phase, e.step) for e in t.events]
    assert steps == [
        ("evidence fetch", "pull #42"),
        ("evidence fetch", "diff of #42"),
        ("evidence fetch", "commits of #42"),
        ("evidence fetch", "check runs"),
        ("evidence fetch", "workflow runs"),
        ("evidence fetch", f"workflow runs at {HEAD[:12]}"),
        ("evidence fetch", "jobs of run 5001"),
        ("evidence fetch", "artifacts of run 5001"),
        ("evidence fetch", "log of job 7001"),
        ("evidence fetch", "artifact 9001"),
        ("source fetch", f"tarball of {HEAD[:12]}"),
        ("evidence fetch", "issue #7"),
    ]
    assert all("secret-branch-name" not in str(e.as_json()) for e in t.events)
    by_step = {e.step: e.fields for e in t.events}
    assert set(by_step["check runs"]) == {"items", "pages", "truncated"}
    assert "chars" in by_step["diff of #42"]
    assert "bytes" in by_step["log of job 7001"]
    assert log == inner.get_job_logs(REPO, 7001, 1_000_000)
    assert archive == inner.download_artifact(REPO, 9001, 1_000_000)
    assert log and archive


def test_a_failed_read_is_recorded_and_re_raised():
    class NoIssues(FixtureGitHub):
        def get_issue(self, repo, number):
            raise NotFoundError("GitHub 404")

    t = Telemetry(FakeClock())
    with pytest.raises(NotFoundError):
        InstrumentedGitHub(NoIssues(FIXTURE), t).get_issue(REPO, 7)
    (event,) = t.events
    assert event.step == "issue #7"
    assert event.status != "ok"
    assert "GitHub 404" in event.error


class _Marked(FixtureGitHub):
    """Every listing comes back cut off at page 7, so a wrapper that
    rebuilds or replaces the Listing cannot match it by chance."""

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if not name.startswith("list_"):
            return attr
        return lambda *a: Listing(attr(*a).items, True, 7)


READS = [
    ("get_pull", (REPO, 42)),
    ("get_pull_diff", (REPO, 42)),
    ("list_pull_commits", (REPO, 42)),
    ("list_check_runs", (REPO, HEAD)),
    ("list_workflow_runs", (REPO, "fix/discount-rounding")),
    ("list_workflow_runs_at", (REPO, HEAD)),
    ("list_run_jobs", (REPO, 5001)),
    ("list_run_artifacts", (REPO, 5001)),
    ("get_job_logs", (REPO, 7001, 1_000_000)),
    ("download_artifact", (REPO, 9001, 1_000_000)),
    ("get_tarball", (REPO, HEAD)),
    ("get_issue", (REPO, 7)),
]


def test_reads_cover_every_github_reader_method():
    assert {n for n, _ in READS} == {
        n for n in vars(GitHubReader) if not n.startswith("_")
    }


@pytest.mark.parametrize("name,args", READS, ids=[n for n, _ in READS])
def test_every_read_returns_what_the_inner_reader_returned(name, args):
    inner = _Marked(FIXTURE)
    got = getattr(InstrumentedGitHub(inner, Telemetry(FakeClock())), name)(*args)
    want = getattr(inner, name)(*args)
    assert got == want
    if isinstance(want, Listing):
        assert want.items and (want.truncated, want.pages_read) == (True, 7)
