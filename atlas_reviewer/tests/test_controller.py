# SPDX-License-Identifier: MIT
"""End-to-end review against the fixture PR, observed through the draft
and through what the (offline) provider was sent."""

import json

import pytest

from atlas_reviewer.controller import Deps, ReviewConfig, review
from atlas_reviewer.domain import PrEvent, SourceKey, SourceKind
from atlas_reviewer.fakes import FakeSprites, MemoryLedger
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.harness import SkillBundleHarness, load_bundle
from atlas_reviewer.lenses import LensLibrary
from atlas_reviewer.ports import BoundaryError, Listing, Narrative, NotFoundError
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor
from atlas_reviewer.runner import ToolSpec

from .helpers import FIXTURE, HEAD, FakeClock, fake_token

EVENT = PrEvent("example-org/example-app", 42, HEAD)
RUNNER = "cqa-rev-20261106-230000-abcdef"
RUFF = ToolSpec("ruff", "ruff", "ruff --version", "ruff check .")
SHELLCHECK = ToolSpec(
    "shellcheck", "shellcheck", "shellcheck --version", "shellcheck x.sh"
)
COMPILEALL = ToolSpec(
    "python-compileall", "python3", "python3 --version", "python3 -m compileall -q ."
)
FULL_TOOLS = (COMPILEALL, RUFF, SHELLCHECK)


class Setup:
    def __init__(
        self, github=None, sprites=None, redactor=None, harness=None, lenses=None
    ):
        self.github = github or FixtureGitHub(FIXTURE)
        script = json.loads((FIXTURE / "runner-script.json").read_text())
        self.sprites = sprites or FakeSprites.from_script(script)
        self.ledger = MemoryLedger()
        self.provider = OfflineProvider()
        self.redactor = redactor or Redactor()
        self.harness = harness or SkillBundleHarness(
            self.provider,
            load_bundle(),
            self.redactor,
            nonce=lambda: "f00dcafe1234beef",
        )
        self.deps = Deps(
            self.github,
            self.sprites,
            self.ledger,
            self.harness,
            FakeClock(),
            self.redactor,
            lambda: RUNNER,
            lenses or LensLibrary(),
        )

    def run(self, **config):
        return review(EVENT, self.deps, ReviewConfig(**config))

    def user_prompt(self):
        (prompt,) = self.provider.prompts
        return prompt.user


def test_draft_is_labelled_as_unposted_and_lists_every_state():
    s = Setup()
    draft = s.run(
        expected=(SourceKey(SourceKind.CHECK_RUN, "security-scan"),), tools=FULL_TOOLS
    )
    assert draft.startswith("# Code Quality Atlas review -- DRAFT")
    assert "Nothing was sent to GitHub" in draft
    assert "| PASS | check_run | gate |" in draft
    assert "| FAIL | workflow_run | ci |" in draft
    assert "| stale | workflow_run | ci | evidence is for `9e8d7c6b5a4f`" in draft
    assert (
        "| missing | workflow_run | docs-lint | observed only on other commits" in draft
    )
    assert "| missing | check_run | security-scan | expected by the operator" in draft
    assert "| inconclusive | check_run | integration | conclusion `pending`" in draft
    assert (
        "| missing | runner_tool | shellcheck | not available in the runner image"
        in draft
    )
    assert "destroyed and verified absent by an existence check" in draft
    assert "UNKNOWN is never counted as passing." in draft


def test_runner_is_destroyed_and_ledger_is_clean_after_review():
    s = Setup()
    s.run()
    assert s.sprites.live_names() == ()
    assert s.ledger.pending() == ()


def test_secrets_and_controller_credentials_never_reach_the_model():
    credential = fake_token("ghs_")
    s = Setup(redactor=Redactor((credential, "org/1/sprites-secret-value")))
    pull = json.loads((FIXTURE / "pull.json").read_text())
    pull["body"] += f"\nmy token is {credential} and org/1/sprites-secret-value"

    class Leaky(FixtureGitHub):
        def get_pull(self, repo, number):
            return pull

    s = Setup(github=Leaky(FIXTURE), redactor=s.redactor)
    draft = s.run()
    prompt = s.user_prompt()
    for secret in (
        credential,
        "sprites-secret-value",
        "AKIAIOSFODNN7EXAMPLE",
        "correct-horse",
        "abcdefghijklmnop",
    ):
        assert secret not in prompt
        assert secret not in draft
    assert "<untrusted-data" in prompt
    assert "ignore your instructions" in prompt.split("ci-and-runner-evidence", 1)[1]


def test_issues_are_not_fetched_unless_opted_in():
    s = Setup()
    draft = s.run()
    assert not any(c[0] == "get_issue" for c in s.github.calls)
    assert "Issue context: off" in draft

    s = Setup()
    s.run(include_issues=True)
    assert ("get_issue", EVENT.repo, "7") in s.github.calls
    assert 'label="issue-7"' in s.user_prompt()


def test_unfetchable_issue_is_noted_not_fatal():
    class NoIssues(FixtureGitHub):
        def get_issue(self, repo, number):
            raise NotFoundError("404")

    draft = Setup(github=NoIssues(FIXTURE)).run(include_issues=True)
    assert "Issue #7 could not be fetched" in draft


def test_moved_pr_head_is_called_out():
    pull = json.loads((FIXTURE / "pull.json").read_text())
    pull["head"]["sha"] = "1" * 40

    class Moved(FixtureGitHub):
        def get_pull(self, repo, number):
            return pull

    draft = Setup(github=Moved(FIXTURE)).run()
    assert "The PR head is now `111111111111`" in draft


def test_github_listing_failures_become_unknown_evidence():
    class Broken(FixtureGitHub):
        def list_check_runs(self, repo, sha):
            raise BoundaryError("GitHub HTTP 502")

        def get_job_logs(self, repo, job_id, max_bytes):
            raise BoundaryError("GitHub HTTP 410")

        def get_pull_diff(self, repo, number):
            raise BoundaryError("GitHub HTTP 500")

    draft = Setup(github=Broken(FIXTURE)).run()
    assert (
        "| missing | check_run | (all check runs) | could not fetch: evidence fetch / "
        "check runs failed after 0.0s (0.0s into the run): GitHub HTTP 502 |"
    ) in draft
    assert (
        "| missing | workflow_log | ci / test | could not fetch: evidence fetch / "
        "log of job 7001 failed after 0.0s"
    ) in draft
    assert "GitHub HTTP 410" in draft
    assert "PASS | check_run" not in draft
    assert "The PR diff could not be fetched" in draft


def test_missing_tarball_skips_the_runner_without_creating_one():
    class NoTarball(FixtureGitHub):
        def get_tarball(self, repo, sha):
            raise NotFoundError("404")

    s = Setup(github=NoTarball(FIXTURE))
    draft = s.run(tools=FULL_TOOLS)
    assert s.sprites.calls == []
    assert "Runner (none): status skipped" in draft
    assert "no runner was created, so there was nothing to clean up" in draft
    assert "| missing | runner_tool | ruff | runner skipped: could not fetch" in draft


def test_oversized_tarball_is_not_uploaded():
    s = Setup()
    draft = s.run(max_tarball_bytes=10)
    assert s.sprites.calls == []
    assert "over 10" in draft


def test_runner_failure_marks_every_unrun_tool_unknown():
    s = Setup(
        sprites=FakeSprites(fail_on={"create": BoundaryError("Sprites HTTP 503")})
    )
    draft = s.run()
    assert "status failed" in draft
    assert "Runner did not complete (failed)" in draft
    assert "Sprites HTTP 503" in draft
    assert (
        "| missing | runner_tool | python-compileall | runner failed before this tool ran"
        in draft
    )
    assert s.sprites.live_names() == ()


def test_harness_failure_still_produces_a_draft():
    class DownHarness:
        name = "skill-bundle"

        def review(self, request):
            raise BoundaryError("provider HTTP 529")

        def usage_lines(self):
            return ("call 1: HTTP 529; reserved $0.7400",)

    draft = Setup(harness=DownHarness()).run()
    assert (
        "Harness `skill-bundle` produced no narrative: model call / diff part 1 of 1 "
        "failed after 0.0s"
    ) in draft
    assert "provider HTTP 529" in draft
    assert "- call 1: HTTP 529; reserved $0.7400" in draft
    assert "| PASS | check_run | gate |" in draft


def test_pull_request_fetch_failure_is_fatal():
    class NoPull(FixtureGitHub):
        def get_pull(self, repo, number):
            raise NotFoundError("404")

    with pytest.raises(BoundaryError):
        Setup(github=NoPull(FIXTURE)).run()


def test_untrusted_text_outside_the_prompt_is_redacted_in_the_draft_too():
    token = fake_token("ghs_")
    checks = json.loads((FIXTURE / "check-runs.json").read_text())
    checks["check_runs"][0]["name"] = f"gate {token}"

    class LeakyName(FixtureGitHub):
        def list_check_runs(self, repo, sha):
            return Listing(tuple(checks["check_runs"]), False, 1)

    draft = Setup(github=LeakyName(FIXTURE)).run()
    assert token not in draft
    assert "gate [REDACTED:github-token]" in draft


def section(draft, heading):
    return draft.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def multi_file_diff(files, body_chars):
    return "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n@@ -1 +1 @@\n+"
        + "x" * body_chars
        + "\n"
        for i in range(files)
    )


class BigDiff(FixtureGitHub):
    def get_pull_diff(self, repo, number):
        return multi_file_diff(20, 5_000)


def risky_diff():
    """Docs and tests first in diff order, the riskiest files last."""
    files = [
        ("docs/guide.md", 20_000),
        ("tests/test_auth.py", 20_000),
        ("app/views.py", 20_000),
        ("app/http_client.py", 20_000),
        ("app/auth.py", 20_000),
    ]
    return "".join(
        f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+" + "x" * n + "\n"
        for f, n in files
    )


class RiskyDiff(FixtureGitHub):
    def get_pull_diff(self, repo, number):
        return risky_diff()


def diff_blocks(provider):
    return [
        p.user.split('label="diff">', 1)[1].split("</untrusted-data", 1)[0]
        for p in provider.prompts
    ]


def test_a_large_diff_is_split_into_one_model_call_per_part(tmp_path):
    s = Setup(github=BigDiff(FIXTURE))
    draft = s.run()
    assert len(s.provider.prompts) == 2
    first, second = diff_blocks(s.provider)
    assert "f0.py" in first and "f0.py" not in second
    assert "f19.py" in second and "f19.py" not in first
    assert "pull request diff" not in section(draft, "Omissions and limits hit")
    notes = section(draft, "Controller notes")
    assert "Diff coverage after the model calls: complete. 2 of 2 call(s)" in notes
    assert "### Diff part 1 of 2 (11 file(s))" in draft
    assert "### Diff part 2 of 2 (9 file(s))" in draft


def test_each_call_is_told_which_part_it_has_and_that_others_exist():
    s = Setup(github=BigDiff(FIXTURE))
    s.run()
    told = [p.user.split('label="controller-notes"', 1)[1] for p in s.provider.prompts]
    assert "Diff part 1 of 2 (this model call): 11 file(s)" in told[0]
    assert "Diff part 2 of 2 (this model call): 9 file(s)" in told[1]
    assert "The other 1 part(s) go to separate model calls" in told[0]


def test_partial_coverage_reviews_the_riskiest_files_and_names_the_rest_by_risk():
    s = Setup(github=RiskyDiff(FIXTURE))
    draft = s.run(model_calls=2, diff_chars_per_call=21_000)
    blocks = diff_blocks(s.provider)
    assert "app/auth.py" in blocks[0]
    assert "app/http_client.py" in blocks[1]
    row = next(
        r
        for r in section(draft, "Omissions and limits hit").splitlines()
        if r.startswith("| pull request diff |")
    )
    assert "2 model call(s) x 21000 characters, risk-ordered" in row
    assert "2 of 5 file(s) sent in full" in row
    assert (
        "never sent to any model call (3), highest risk first: [other code] app/views.py; "
        "[tests and fixtures] tests/test_auth.py; [docs] docs/guide.md"
    ) in row
    notes = section(draft, "Controller notes")
    assert "Diff coverage after the model calls: PARTIAL." in notes
    assert "3 file(s) went to no call" in notes
    evidence = s.provider.prompts[0].user.split('label="ci-and-runner-evidence"', 1)[1]
    assert "never sent to any model call (3)" in evidence


def test_a_part_whose_call_fails_is_reported_unreviewed_not_dropped():
    class FailsSecond:
        name = "skill-bundle"

        def __init__(self):
            self.seen = 0

        def review(self, request):
            self.seen += 1
            if self.seen == 2:
                raise BoundaryError("provider HTTP 529")
            return Narrative("skill-bundle", "offline", Redactor()("ok"))

        def usage_lines(self):
            return ("call 1: ok", "call 2: HTTP 529")

    draft = Setup(github=RiskyDiff(FIXTURE), harness=FailsSecond()).run(
        model_calls=3, diff_chars_per_call=41_000
    )
    omissions = section(draft, "Omissions and limits hit")
    row = next(r for r in omissions.splitlines() if "part 2 of 3" in r)
    assert "model call returned no review" in row
    assert "2 file(s) sent but not reviewed" in row
    assert "produced no narrative: model call / diff part 2 of 3 failed after" in draft
    notes = section(draft, "Controller notes")
    assert "PARTIAL. 2 of 3 call(s) returned a review" in notes


def openrouter_setup(*chat, **limits):
    from atlas_reviewer.budget import CallLimits
    from atlas_reviewer.openrouter import OpenRouterProvider

    from .test_openrouter import KEY, OpenRouterFake, catalog, reply

    fake = OpenRouterFake(*chat, model=reply(catalog(overrides=None)))
    provider = OpenRouterProvider(fake, KEY, limits=CallLimits(**limits))
    provider.preflight()
    harness = SkillBundleHarness(provider, load_bundle(), Redactor((KEY,)))
    return Setup(github=RiskyDiff(FIXTURE), harness=harness), fake


def test_retries_share_the_three_call_cap_so_a_later_part_is_refused_and_listed():
    from .test_openrouter import completion, reply

    s, fake = openrouter_setup(
        reply({"error": "busy"}, status=503), reply(completion()), reply(completion())
    )
    draft = s.run(model_calls=3, diff_chars_per_call=41_000)
    assert len(fake.chat_requests()) == 3
    usage = section(draft, "Model usage")
    assert "refused: call cap reached: 3 model calls per review" in usage
    assert "3 of 3 calls used" in usage
    row = next(
        r for r in section(draft, "Omissions and limits hit").splitlines()
        if "part 3 of 3" in r
    )  # fmt: skip
    assert "[docs] docs/guide.md" in row
    assert "PARTIAL. 2 of 3 call(s) returned a review" in section(
        draft, "Controller notes"
    )


def test_the_cost_cap_refuses_a_part_before_it_is_sent():
    from decimal import Decimal

    from .test_openrouter import completion, reply

    costly = completion(
        usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.5}
    )
    s, fake = openrouter_setup(reply(costly), budget_usd=Decimal("1.00"))
    draft = s.run(model_calls=3, diff_chars_per_call=41_000)
    assert len(fake.chat_requests()) == 1
    assert "refused: cost cap" in section(draft, "Model usage")
    assert "PARTIAL. 1 of 3 call(s) returned a review" in section(
        draft, "Controller notes"
    )


@pytest.mark.parametrize(
    "config",
    [{"model_calls": 0}, {"model_calls": 4}, {"diff_chars_per_call": 999}],
)
def test_the_call_cap_and_per_call_budget_are_validated(config):
    with pytest.raises(ValueError):
        ReviewConfig(**config)


def test_the_draft_carries_a_lifecycle_telemetry_table():
    draft = Setup().run()
    table = section(draft, "Lifecycle telemetry")
    for phase, step in [
        ("evidence fetch", "pull #42"),
        ("evidence fetch", "check runs"),
        ("source fetch", "tarball of 3f6c1e9b2a7d"),
        ("create", "create sprite"),
        ("exec", "tool check"),
        ("upload", ""),
        ("unpack", "tar -xzf"),
        ("tool", "python-compileall"),
        ("verify", "existence check"),
        ("model call", "diff part 1 of 1"),
    ]:
        assert f"| {phase} | {step}" in table, (phase, step)
    assert "ERROR" not in table


def test_a_failed_fetch_is_an_error_row_with_its_label():
    class Broken(FixtureGitHub):
        def list_check_runs(self, repo, sha):
            raise BoundaryError("GitHub HTTP 502")

    table = section(Setup(github=Broken(FIXTURE)).run(), "Lifecycle telemetry")
    row = next(r for r in table.splitlines() if "| check runs |" in r)
    assert "| ERROR |" in row
    assert "evidence fetch / check runs failed after" in row


def test_an_untruncated_diff_records_no_diff_omission():
    draft = Setup().run()
    assert "pull request diff" not in section(draft, "Omissions and limits hit")


def test_a_long_pr_body_and_issue_body_are_recorded_as_omissions():
    pull = json.loads((FIXTURE / "pull.json").read_text())
    pull["body"] = "Fixes #7\n\n" + "word " * 1_000

    class LongBodies(FixtureGitHub):
        def get_pull(self, repo, number):
            return pull

        def get_issue(self, repo, number):
            return {"title": "t", "body": "y" * 3_000}

    draft = Setup(github=LongBodies(FIXTURE)).run(include_issues=True)
    omissions = section(draft, "Omissions and limits hit")
    assert (
        f"| pull request body | 2000-character cap | kept 2000 of {len(pull['body'])} characters |"
        in omissions
    )
    assert "| issue #7 | 2000-character cap | kept 2000 of " in omissions


def test_lens_bodies_from_the_skill_bundle_reach_the_prompt():
    s = Setup()
    draft = s.run()
    (prompt,) = s.provider.prompts
    library = LensLibrary()
    table = section(draft, "Review lenses")
    included = [
        line.split("|")[1].strip()
        for line in table.splitlines()
        if "| included |" in line
    ]
    assert included, table
    for name in included:
        assert library.body(name) in prompt.system, name
    assert "Lens coverage: included: " in prompt.system
    assert "=== lens: tracing-correctness-and-invariants ===" in prompt.system


def test_the_draft_reports_included_truncated_and_omitted_lenses_accurately():
    class BigLenses(LensLibrary):
        def __init__(self):
            super().__init__()

        def body(self, name):
            real = super().body(name)
            return None if real is None else f"LENS-{name}\n" + ("rule\n" * 8_000)

    s = Setup(lenses=BigLenses())
    draft = s.run()
    (prompt,) = s.provider.prompts
    rows = {
        line.split("|")[1].strip(): line.split("|")[2].strip()
        for line in section(draft, "Review lenses").splitlines()
        if line.startswith("| ") and "---" not in line and "Lens |" not in line
    }
    assert list(rows.values()).count("included") == 1
    assert list(rows.values()).count("truncated") == 1
    assert "omitted" in rows.values()
    omitted = [n for n, status in rows.items() if status == "omitted"]
    truncated = next(n for n, status in rows.items() if status == "truncated")
    for name in omitted:
        assert f"LENS-{name}" not in prompt.system
    assert (
        "lens body truncated by atlas_reviewer"
        in prompt.system.split(f"=== lens: {truncated} ===", 1)[1]
    )
    assert f"truncated: {truncated} (" in section(draft, "Controller notes")


def test_the_bundle_text_alone_does_not_count_as_running_a_lens():
    s = Setup()
    s.run()
    (prompt,) = s.provider.prompts
    assert "reference/lenses/hunting-silent-failures/body.md" in prompt.system
    assert "You cannot open files" in prompt.system
    assert "=== lens: sweeping-for-security ===" not in prompt.system


def test_one_ci_gate_is_counted_once_with_its_views_attached():
    draft = Setup().run()
    summary = section(draft, "Evidence summary")
    assert "- Pass: 2\n" in summary
    assert "- Fail: 1\n" in summary
    assert "- UNKNOWN at the head SHA (missing or inconclusive): 2\n" in summary
    checks = section(draft, "Independent checks at the reviewed head SHA")
    gate = next(r for r in checks.splitlines() if "| check_run | gate |" in r)
    assert gate.startswith("| PASS |")
    for view in ("job:7002", "job_log:7002", "workflow_run:5001"):
        assert view in gate
    gate_rows = [r for r in checks.splitlines() if "gate" in r and r.startswith("| ")]
    assert len(gate_rows) == 1
    failing = next(r for r in checks.splitlines() if "ci / test" in r)
    assert failing.startswith("| FAIL |")
    assert "workflow_run:5001" in failing


def test_the_model_sees_grouped_checks_and_the_same_counts():
    s = Setup()
    s.run()
    evidence = s.user_prompt().split('label="ci-and-runner-evidence"', 1)[1]
    assert "## Independent checks at the reviewed head SHA" in evidence
    gate = next(r for r in evidence.splitlines() if "| check_run | gate |" in r)
    assert gate.startswith("| PASS |")
    assert "job_log:7002" in gate and "workflow_run:5001" in gate


def test_a_failing_run_no_job_explains_is_not_hidden_by_grouping():
    class OnlyPassingJobs(FixtureGitHub):
        def list_run_jobs(self, repo, run_id):
            listing = super().list_run_jobs(repo, run_id)
            kept = tuple(j for j in listing.items if j["conclusion"] == "success")
            return Listing(kept, listing.truncated, listing.pages_read)

    draft = Setup(github=OnlyPassingJobs(FIXTURE)).run()
    checks = section(draft, "Independent checks at the reviewed head SHA")
    run_row = next(r for r in checks.splitlines() if "| workflow_run | ci |" in r)
    assert run_row.startswith("| FAIL |")
    assert "- Fail: 1\n" in section(draft, "Evidence summary")


def test_controller_notes_are_a_distinct_code_generated_section():
    draft = Setup().run()
    notes = section(draft, "Controller notes")
    assert "Generated by code" in notes
    assert "this section is authoritative" in notes
    assert (
        "destroyed and verified absent by an existence check (cleanup proven)" in notes
    )
    assert "Tool `python-compileall` (Python 3.13.5): ran, exit 0." in notes
    assert "Omissions and limits hit: 1" in notes
    assert "Disposable runner" not in draft
    assert draft.index("## Controller notes") < draft.index("## Review narrative")


def test_controller_notes_report_exec_failures_and_absent_tools():
    api = FakeSprites.from_script({"installed": ["python3"], "exec": []})
    draft = Setup(sprites=api).run(tools=FULL_TOOLS)
    notes = section(draft, "Controller notes")
    assert "Runner did not complete (failed)" in notes
    assert "unpack / tar -xzf failed after" in notes
    assert "source unpack failed (exit 127)" in notes
    assert "Tool `ruff`: did not run (the runner did not reach it)." in notes
    assert "destroyed and verified absent" in notes


def test_controller_notes_report_unverified_cleanup_and_the_model_is_told():
    s = Setup(
        sprites=FakeSprites.from_script(
            json.loads((FIXTURE / "runner-script.json").read_text())
        )
    )
    s.sprites.delete_takes_effect = False
    draft = s.run()
    notes = section(draft, "Controller notes")
    assert "destroy was NOT verified" in notes
    assert "`sweep`" in notes
    told = s.user_prompt().split('label="controller-notes"', 1)[1]
    assert "destroy was NOT verified" in told


def test_the_model_is_given_the_controller_notes_and_told_they_are_facts():
    s = Setup()
    s.run()
    (prompt,) = s.provider.prompts
    told = prompt.user.split('label="controller-notes"', 1)[1].split(
        "</untrusted-data", 1
    )[0]
    assert (
        "destroyed and verified absent by an existence check (cleanup proven)" in told
    )
    assert "ran, exit 0" in told
    assert "established facts" in prompt.system
    assert "do not contradict them or call them unverified" in " ".join(
        prompt.system.split()
    )


def test_a_file_too_big_for_one_call_is_reported_cut_not_complete():
    class OneHugeFile(FixtureGitHub):
        def get_pull_diff(self, repo, number):
            return "diff --git a/app/auth.py b/app/auth.py\n" + "+line\n" * 2_000

    s = Setup(github=OneHugeFile(FIXTURE))
    draft = s.run(diff_chars_per_call=5_000)
    row = next(
        r for r in section(draft, "Omissions and limits hit").splitlines()
        if r.startswith("| pull request diff |")
    )  # fmt: skip
    assert "cut to fit one call: app/auth.py (kept " in row
    assert "never sent" not in row
    assert "PARTIAL" in section(draft, "Controller notes")
    told = s.user_prompt().split('label="controller-notes"', 1)[1]
    assert "1 file(s), 5000 characters: app/auth.py (cut)." in told
    assert diff_blocks(s.provider)[0].rstrip().endswith("to fit one model call ...]")
