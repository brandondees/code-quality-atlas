# SPDX-License-Identifier: MIT
"""CI evidence gathering: page caps, per-review caps and download limits
each become an explicit omission, and whatever they left unread is UNKNOWN."""

import io
import zipfile

import pytest

from atlas_reviewer.archive import ArchiveLimits
from atlas_reviewer.classify import REASON_ONLY_OTHER_SHAS, classify, tally
from atlas_reviewer.domain import Missing, Outcome, PrEvent, SourceKind, outcome
from atlas_reviewer.gather import Collected, IngestConfig, gather_ci
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.ports import BoundaryError, Listing, ResponseTooLargeError
from atlas_reviewer.redact import Redactor

from .helpers import FIXTURE, HEAD, NOW, OLD, fake_token

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
    evidence = classify(HEAD, out.items, failures=out.failures)
    assert tally(evidence, out.links).unread == 1
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


def test_job_log_cap_counts_action_required_as_failing():
    class ActionRequired(FixtureGitHub):
        def list_run_jobs(self, repo, run_id):
            failing, passing = super().list_run_jobs(repo, run_id).items
            blocked = {**passing, "conclusion": "action_required"}
            return Listing(({**failing, "conclusion": "success"}, blocked), False, 1)

    gh = ActionRequired(FIXTURE)
    gather(gh, max_job_logs=1)
    assert [c[2] for c in calls(gh, "get_job_logs")] == ["7002"]


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


def _one_text_entry(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("summary.txt", text)
    return buf.getvalue()


def test_secrets_in_logs_and_artifacts_are_redacted():
    secret = "opaque-" + fake_token("", 24)

    class Leaky(FixtureGitHub):
        def download_artifact(self, repo, artifact_id, max_bytes):
            return _one_text_entry(f"token used: {secret}\n")

    out = Collected()
    gather_ci(
        EVENT, "feature", Leaky(FIXTURE), lambda: NOW,
        Redactor((secret,)), IngestConfig(), out,
    )  # fmt: skip
    log = next(i for i in out.items if i.provenance.source_id == "job_log:7001")
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in log.detail.text
    assert log.detail.redaction_count >= 1
    contents = next(
        i for i in out.items if i.provenance.source_id == "artifact:9001:zip"
    )
    assert "token used: [REDACTED" in contents.detail.text
    assert secret not in contents.detail.text


def test_an_artifact_excerpt_cut_at_its_cap_is_an_omission_and_the_rest_unknown():
    class Long(FixtureGitHub):
        def download_artifact(self, repo, artifact_id, max_bytes):
            return _one_text_entry("line\n" * 2_000)

    out = gather(Long(FIXTURE))
    contents = next(
        i for i in out.items if i.provenance.source_id == "artifact:9001:zip"
    )
    assert outcome(classify(HEAD, [contents])[0]) is Outcome.INFO
    cut = next(o for o in out.omissions if o.limit.startswith("excerpt cap"))
    assert cut.source == "artifact:9001:zip"
    assert cut.detail.startswith(f"{contents.detail.truncated_from} characters")
    evidence = classify(HEAD, out.items, failures=out.failures)
    rest = next(
        e for e in evidence
        if isinstance(e, Missing) and e.key.name.startswith("coverage-report (contents")
    )  # fmt: skip
    assert rest.key.name == "coverage-report (contents past the excerpt cap)"
    assert outcome(rest) is Outcome.UNKNOWN


def test_an_artifact_excerpt_within_its_cap_records_no_cut():
    out = gather(FixtureGitHub(FIXTURE))
    assert not [o for o in out.omissions if o.limit.startswith("excerpt cap")]


def test_a_job_log_that_cannot_be_fetched_is_unknown():
    class NoLogs(FixtureGitHub):
        def get_job_logs(self, repo, job_id, max_bytes):
            raise BoundaryError("GitHub HTTP 500")

    out = gather(NoLogs(FIXTURE))
    logs = {
        f.key.name: f.reason
        for f in out.failures
        if f.key.kind is SourceKind.WORKFLOW_LOG
    }
    assert logs == {
        name: "could not fetch: GitHub HTTP 500" for name in ("ci / test", "ci / gate")
    }
    assert not any(i.provenance.source_id.startswith("job_log:") for i in out.items)
    evidence = classify(HEAD, out.items, failures=out.failures)
    assert all(
        outcome(e) is Outcome.UNKNOWN
        for e in evidence
        if isinstance(e, Missing) and e.key.kind is SourceKind.WORKFLOW_LOG
    )


def test_gather_records_the_links_between_views_of_one_check():
    out = gather(FixtureGitHub(FIXTURE))
    links = {(link.supporter, link.supported) for link in out.links}
    assert {
        ("workflow_run:5001", "job:7002"),
        ("job:7002", "check_run:7002"),
        ("job_log:7002", "job:7002"),
        ("workflow_run:5001", "job:7001"),
        ("job_log:7001", "job:7001"),
        ("artifact:9001:zip", "artifact:9001"),
    } <= links


def test_a_job_without_a_check_run_url_is_not_linked_to_any_check_run():
    out = gather(FixtureGitHub(FIXTURE))
    job_links = {link.supported for link in out.links if link.supporter == "job:7001"}
    assert job_links == set()


def test_a_malformed_entry_is_unknown_and_the_rest_are_still_ingested():
    class Malformed(FixtureGitHub):
        def list_check_runs(self, repo, sha):
            full = super().list_check_runs(repo, sha)
            return Listing(({"id": "x"}, *full.items), False, 1)

        def list_run_jobs(self, repo, run_id):
            full = super().list_run_jobs(repo, run_id)
            return Listing((*full.items, "not an object"), False, 1)

    out = gather(Malformed(FIXTURE))
    reasons = missing_reasons(out)
    assert reasons["(check runs entry 0)"].startswith("malformed: ")
    assert reasons["(jobs of ci entry 2)"].startswith("malformed: ")
    ids = {i.provenance.source_id for i in out.items}
    assert {"job:7001", "job_log:7001", "artifact:9001:zip"} <= ids
    assert any(i.provenance.source_id.startswith("check_run:") for i in out.items)
    evidence = classify(HEAD, out.items, failures=out.failures)
    bad = next(
        e for e in evidence if isinstance(e, Missing) and "entry 0" in e.key.name
    )
    assert outcome(bad) is Outcome.UNKNOWN


def test_count_caps_are_shared_across_runs_and_what_they_skip_is_unknown():
    class TwoRuns(FixtureGitHub):
        def list_workflow_runs(self, repo, branch):
            (run, *rest) = super().list_workflow_runs(repo, branch).items
            return Listing((run, {**run, "id": 5002}, *rest), False, 1)

        def list_run_jobs(self, repo, run_id):
            return super().list_run_jobs(repo, "5001")

        def list_run_artifacts(self, repo, run_id):
            return super().list_run_artifacts(repo, "5001")

    gh = TwoRuns(FIXTURE)
    out = gather(gh, max_job_logs=3, max_artifacts=1)
    assert len(calls(gh, "get_job_logs")) == 3
    assert len(calls(gh, "download_artifact")) == 1
    skipped = [f for f in out.failures if "per-review cap" in f.reason]
    assert {f.key.kind.value for f in skipped} == {"workflow_log", "artifact"}


def test_a_run_past_the_run_cap_leaves_its_jobs_unknown():
    class TwoRuns(FixtureGitHub):
        def list_workflow_runs(self, repo, branch):
            (run, *rest) = super().list_workflow_runs(repo, branch).items
            return Listing((run, {**run, "id": 5002, "name": "other"}, *rest), False, 1)

    out = gather(TwoRuns(FIXTURE), max_runs=1)
    assert missing_reasons(out)["(jobs of other)"] == "not read: per-review cap of 1"


def test_skipped_archive_entries_are_unknown_and_an_all_skipped_one_is_not_present():
    out = gather(FixtureGitHub(FIXTURE))
    assert missing_reasons(out)["coverage-report (skipped entry 0)"].startswith(
        "not read: archive entry skipped -- upload.sh"
    )

    class OnlyScripts(FixtureGitHub):
        def download_artifact(self, repo, artifact_id, max_bytes):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("run.sh", "echo")
            return buf.getvalue()

    out = gather(OnlyScripts(FIXTURE))
    assert not any(i.provenance.source_id.endswith(":zip") for i in out.items)
    reason = missing_reasons(out)["coverage-report (contents)"]
    assert reason == "not read: every archive entry skipped"


UNRELATED = "0123456789abcdef0123456789abcdef01234567"


class _SameNameBranch(FixtureGitHub):
    """The head branch's name is shared: the branch listing also returns
    another PR's (or the base repo's push) runs at commits not in this PR."""

    def list_workflow_runs(self, repo, branch):
        listed = super().list_workflow_runs(repo, branch)
        (run, *_) = listed.items
        foreign = (
            {**run, "id": 8001, "name": "deploy", "head_sha": UNRELATED},
            {**run, "id": 8002, "name": "nightly", "head_sha": UNRELATED},
        )
        return Listing((*listed.items, *foreign), False, 1)


def test_same_name_runs_outside_the_pr_are_not_reported_as_this_prs_commits():
    out = gather(_SameNameBranch(FIXTURE))
    evidence = classify(HEAD, out.items, failures=out.failures)
    reasons = {e.key.name: e.reason for e in evidence if isinstance(e, Missing)}
    assert "deploy" not in reasons and "nightly" not in reasons
    assert UNRELATED not in {i.head_sha for i in out.items}
    assert reasons["docs-lint"] == REASON_ONLY_OTHER_SHAS
    stale = {
        (i.provenance.key.name, i.head_sha) for i in out.items if i.head_sha == OLD
    }
    assert stale == {("ci", OLD), ("docs-lint", OLD)}
    assert any("2 workflow run(s)" in n for n in out.notes)


def test_without_the_prs_commits_only_head_sha_runs_are_used():
    class NoCommits(FixtureGitHub):
        def list_pull_commits(self, repo, number):
            raise BoundaryError("HTTP 502")

    out = gather(NoCommits(FIXTURE))
    assert {i.head_sha for i in out.items} == {HEAD}
    assert missing_reasons(out)["(all commits of this PR)"] == (
        "could not fetch: HTTP 502"
    )
    assert "job:7001" in {i.provenance.source_id for i in out.items}


def test_a_head_sha_run_the_branch_listing_did_not_reach_is_still_gathered():
    class BusyBranch(FixtureGitHub):
        def list_workflow_runs(self, repo, branch):
            listed = super().list_workflow_runs(repo, branch).items
            return Listing(tuple(r for r in listed if r["head_sha"] != HEAD), True, 10)

    out = gather(BusyBranch(FIXTURE))
    ids = {i.provenance.source_id for i in out.items}
    assert {"workflow_run:5001", "job_log:7001", "workflow_run:4001"} <= ids
    assert "(workflow runs beyond page 10)" in missing_reasons(out)


OPAQUE = "opaque-credential-" + fake_token("", 24)


class _SecretNames(FixtureGitHub):
    """Every free-text name GitHub reports carries a configured credential
    that no secret pattern would match."""

    @staticmethod
    def _named(listing, **fields):
        return Listing(
            tuple(
                {**e, **{k: f"{e.get(k, '')}-{OPAQUE}" for k in fields}}
                for e in listing.items
            ),
            listing.truncated,
            listing.pages_read,
        )

    def list_check_runs(self, repo, sha):
        listed = super().list_check_runs(repo, sha)
        named = self._named(listed, name=1)
        return Listing(
            tuple({**e, "app": {"slug": f"app-{OPAQUE}"}} for e in named.items),
            False,
            1,
        )

    def list_workflow_runs(self, repo, branch):
        return self._named(super().list_workflow_runs(repo, branch), name=1, path=1)

    def list_workflow_runs_at(self, repo, sha):
        return self._named(super().list_workflow_runs_at(repo, sha), name=1, path=1)

    def list_run_jobs(self, repo, run_id):
        return self._named(super().list_run_jobs(repo, run_id), name=1)

    def list_run_artifacts(self, repo, run_id):
        return self._named(super().list_run_artifacts(repo, run_id), name=1)

    def download_artifact(self, repo, artifact_id, max_bytes):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("summary.txt", "ok")
            zf.writestr(f"dump-{OPAQUE}.bin", "x")
        return buf.getvalue()


def _retained_text(out):
    for i in out.items:
        yield from (i.provenance.key.name, i.tool.name, i.tool.version, i.detail.text)
    for f in out.failures:
        yield from (f.key.name, f.reason)
    for o in out.omissions:
        yield from (o.source, o.limit, o.detail)
    yield from out.notes


def test_free_text_github_metadata_is_redacted_before_it_is_retained():
    out = Collected()
    gather_ci(
        EVENT, "feature", _SecretNames(FIXTURE), lambda: NOW,
        Redactor((OPAQUE,)), IngestConfig(), out,
    )  # fmt: skip
    retained = list(_retained_text(out))
    assert not [t for t in retained if OPAQUE in t]
    names = {i.provenance.key.name for i in out.items}
    assert any(n.startswith("ci-[REDACTED") for n in names)
    assert {i.provenance.source_id for i in out.items} >= {"job:7001", "job_log:7001"}
    assert any("dump-[REDACTED" in o.detail for o in out.omissions)


class _NoCommits(FixtureGitHub):
    def list_pull_commits(self, repo, number):
        raise BoundaryError("GitHub HTTP 403")


class _RunsCut(FixtureGitHub):
    def list_workflow_runs(self, repo, branch):
        return Listing(super().list_workflow_runs(repo, branch).items, True, 10)


class _ChecksCut(FixtureGitHub):
    def list_check_runs(self, repo, sha):
        return Listing(super().list_check_runs(repo, sha).items, True, 10)


class _BadCommit(FixtureGitHub):
    def list_pull_commits(self, repo, number):
        listed = super().list_pull_commits(repo, number)
        return Listing((*listed.items, {"sha": 7}), False, 1)


class _TwoHeadRuns(FixtureGitHub):
    def list_workflow_runs_at(self, repo, sha):
        (run,) = super().list_workflow_runs_at(repo, sha).items
        return Listing((run, {**run, "id": 5002, "name": "ci-again"}), False, 1)


@pytest.mark.parametrize(
    "github,config,name",
    [
        (_NoCommits, {}, "(all commits of this PR)"),
        (_RunsCut, {}, "(workflow runs beyond page 10)"),
        (_ChecksCut, {}, "(check runs beyond page 10)"),
        (_BadCommit, {}, "(commits of this PR entry 2)"),
        (_TwoHeadRuns, {"max_runs": 1}, "(jobs of ci-again)"),
    ],
)
def test_a_list_not_read_is_unknown_but_not_counted_as_a_check(github, config, name):
    """Tally.unknown counts checks without a result. A listing that failed,
    was cut off or skipped stands for no particular check, so it counts as
    unread, and it stays visible as UNKNOWN."""
    out = gather(github(FIXTURE), **config)
    evidence = classify(HEAD, out.items, failures=out.failures)
    (gap,) = [e for e in evidence if isinstance(e, Missing) and e.key.name == name]
    assert outcome(gap) is Outcome.UNKNOWN
    with_gap = tally(evidence, out.links)
    without = tally([e for e in evidence if e is not gap], out.links)
    assert (with_gap.unknown - without.unknown, with_gap.unread - without.unread) == (
        0,
        1,
    )
