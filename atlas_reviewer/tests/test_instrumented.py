# SPDX-License-Identifier: MIT
"""`InstrumentedGitHub`: every read is one telemetry event labelled with
controller-side identifiers only, and a failed read is recorded and
re-raised."""

import pytest

from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.instrumented import InstrumentedGitHub
from atlas_reviewer.ports import NotFoundError
from atlas_reviewer.telemetry import Telemetry

from .helpers import FIXTURE, HEAD, FakeClock

REPO = "example-org/example-app"


def test_every_read_is_one_event_with_its_size():
    t = Telemetry(FakeClock())
    gh = InstrumentedGitHub(FixtureGitHub(FIXTURE), t)
    gh.get_pull(REPO, 42)
    gh.get_pull_diff(REPO, 42)
    gh.list_check_runs(REPO, HEAD)
    gh.list_workflow_runs(REPO, "feature/secret-branch-name")
    gh.list_run_jobs(REPO, 5001)
    gh.list_run_artifacts(REPO, 5001)
    gh.get_job_logs(REPO, 7001, 1_000_000)
    gh.download_artifact(REPO, 9001, 1_000_000)
    gh.get_tarball(REPO, HEAD)
    gh.get_issue(REPO, 7)
    steps = [(e.phase, e.step) for e in t.events]
    assert steps == [
        ("evidence fetch", "pull #42"),
        ("evidence fetch", "diff of #42"),
        ("evidence fetch", "check runs"),
        ("evidence fetch", "workflow runs"),
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
