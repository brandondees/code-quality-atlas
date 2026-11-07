# SPDX-License-Identifier: MIT
"""CI evidence gathering: page caps, per-review caps and download limits
each become an explicit omission, and whatever they left unread is UNKNOWN."""

import io
import zipfile

from atlas_reviewer.archive import ArchiveLimits
from atlas_reviewer.classify import classify
from atlas_reviewer.domain import Missing, Outcome, PrEvent, outcome
from atlas_reviewer.gather import Collected, IngestConfig, gather_ci
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.ports import BoundaryError, Listing, ResponseTooLargeError
from atlas_reviewer.redact import Redactor

from .helpers import FIXTURE, HEAD, NOW, OLD

EVENT = PrEvent("example-org/example-app", 42, HEAD)


def gather(github, **config):
    out = Collected()
    gather_ci(
        EVENT, "feature", github, lambda: NOW, Redactor(), IngestConfig(**config), out
    )
    return out


def calls(github, name):
    return [c for c in github.calls if c[0] == name]


def missing_reasons(out):
    return {f.key.name: f.reason for f in out.failures}


def test_fixture_ingests_jobs_logs_and_artifact_text_at_the_head_sha():
    gh = FixtureGitHub(FIXTURE)
    out = gather(gh)
    ids = {i.provenance.source_id for i in out.items}
    assert {
        "job:7001",
        "job:7002",
        "job_log:7001",
        "job_log:7002",
        "artifact:9001:zip",
    } <= ids
    contents = next(
        i for i in out.items if i.provenance.source_id == "artifact:9001:zip"
    )
    assert "calc.py       12      1    92%" in contents.detail.text
    assert "curl" not in contents.detail.text
    assert [(o.source, o.limit) for o in out.omissions] == [
        ("artifact:9001", "archive entry skipped")
    ]
    assert "upload.sh: file type not on the text allowlist" in out.omissions[0].detail
    assert calls(gh, "list_run_jobs") == [("list_run_jobs", EVENT.repo, "5001")]


def test_page_cap_hit_is_an_omission_and_the_remainder_is_unknown():
    class Capped(FixtureGitHub):
        def list_check_runs(self, repo, sha):
            full = super().list_check_runs(repo, sha)
            return Listing(full.items, truncated=True, pages_read=10)

    out = gather(Capped(FIXTURE))
    omission = next(o for o in out.omissions if o.source == "check runs")
    assert omission.limit == "page cap (10 pages)"
    reason = missing_reasons(out)["(check runs beyond page 10)"]
    assert reason.startswith("not read: page cap (10 pages)")
    evidence = classify(HEAD, out.items, failures=out.failures)
    beyond = next(
        e for e in evidence if isinstance(e, Missing) and "beyond" in e.key.name
    )
    assert outcome(beyond) is Outcome.UNKNOWN


def test_logs_and_artifacts_are_fetched_only_for_the_head_sha():
    class Mixed(FixtureGitHub):
        def list_run_jobs(self, repo, run_id):
            jobs = list(super().list_run_jobs(repo, run_id).items)
            jobs.append({**jobs[0], "id": 7999, "head_sha": OLD})
            return Listing(tuple(jobs), False, 1)

        def list_run_artifacts(self, repo, run_id):
            (art,) = super().list_run_artifacts(repo, run_id).items
            stale = {**art, "id": 9002, "workflow_run": {"id": 1, "head_sha": OLD}}
            expired = {**art, "id": 9003, "expired": True}
            return Listing((art, stale, expired), False, 1)

    gh = Mixed(FIXTURE)
    gather(gh)
    assert {c[2] for c in calls(gh, "get_job_logs")} == {"7001", "7002"}
    assert {c[2] for c in calls(gh, "download_artifact")} == {"9001"}
    assert all(c[2] == "5001" for c in calls(gh, "list_run_jobs"))


def test_job_log_cap_reads_failing_jobs_first_and_notes_the_rest():
    gh = FixtureGitHub(FIXTURE)
    out = gather(gh, max_job_logs=1)
    assert [c[2] for c in calls(gh, "get_job_logs")] == ["7001"]
    cap = next(o for o in out.omissions if o.source == "job logs")
    assert (cap.limit, cap.detail) == ("per-review cap of 1", "1 of 2 not ingested")


def test_run_cap_is_noted():
    class TwoRuns(FixtureGitHub):
        def list_workflow_runs(self, repo, branch):
            (run, *rest) = super().list_workflow_runs(repo, branch).items
            return Listing((run, {**run, "id": 5002}, *rest), False, 1)

    out = gather(TwoRuns(FIXTURE), max_runs=1)
    assert any(o.source == "workflow runs at the head SHA" for o in out.omissions)


def test_oversized_job_log_is_an_omission_and_unknown():
    out = gather(FixtureGitHub(FIXTURE), max_log_bytes=10)
    assert {o.source for o in out.omissions} >= {"log of job:7001", "log of job:7002"}
    assert missing_reasons(out)["ci / test"].startswith(
        "not read: 10-byte download cap"
    )
    assert not any(i.provenance.source_id.startswith("job_log:") for i in out.items)


def test_listed_size_over_the_cap_is_never_downloaded():
    gh = FixtureGitHub(FIXTURE)
    out = gather(gh, archive=ArchiveLimits(max_compressed_bytes=1000))
    assert calls(gh, "download_artifact") == []
    omission = next(o for o in out.omissions if o.source == "artifact:9001")
    assert omission.detail == "listed at 48213 bytes; not downloaded"
    assert "coverage-report (contents)" in missing_reasons(out)


def test_download_that_overruns_the_cap_is_an_omission():
    class Lying(FixtureGitHub):
        def download_artifact(self, repo, artifact_id, max_bytes):
            raise ResponseTooLargeError("too big")

    out = gather(Lying(FIXTURE))
    assert any(o.detail == "download exceeded the cap" for o in out.omissions)


def test_archive_bomb_is_rejected_and_its_contents_unknown():
    class Bomb(FixtureGitHub):
        def download_artifact(self, repo, artifact_id, max_bytes):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for i in range(5):
                    zf.writestr(f"f{i}.txt", "x")
            return buf.getvalue()

    out = gather(Bomb(FIXTURE), archive=ArchiveLimits(max_entries=3))
    omission = next(o for o in out.omissions if o.limit == "archive rejected")
    assert omission.detail == "5 entries, over the 3-entry cap"
    assert "coverage-report (contents)" in missing_reasons(out)


def test_fetch_failures_become_missing_not_fatal():
    class Flaky(FixtureGitHub):
        def list_run_jobs(self, repo, run_id):
            raise BoundaryError("GitHub HTTP 502")

        def download_artifact(self, repo, artifact_id, max_bytes):
            raise BoundaryError("GitHub HTTP 410")

    out = gather(Flaky(FIXTURE))
    reasons = missing_reasons(out)
    assert reasons["(all jobs of ci)"] == "could not fetch: GitHub HTTP 502"
    assert reasons["coverage-report (contents)"] == "could not fetch: GitHub HTTP 410"


def test_secrets_in_logs_and_artifacts_are_redacted():
    out = gather(FixtureGitHub(FIXTURE))
    log = next(i for i in out.items if i.provenance.source_id == "job_log:7001")
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in log.detail.text
    assert log.detail.redaction_count >= 1
