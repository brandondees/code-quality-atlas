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
from atlas_reviewer.ports import BoundaryError, NotFoundError
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor

from .helpers import FIXTURE, HEAD, FakeClock, fake_token

EVENT = PrEvent("example-org/example-app", 42, HEAD)
RUNNER = "cqa-rev-20261106-230000-abcdef"


class Setup:
    def __init__(self, github=None, sprites=None, redactor=None, harness=None):
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
        )

    def run(self, **config):
        return review(EVENT, self.deps, ReviewConfig(**config))

    def user_prompt(self):
        (prompt,) = self.provider.prompts
        return prompt.user


def test_draft_is_labelled_as_unposted_and_lists_every_state():
    s = Setup()
    draft = s.run(expected=(SourceKey(SourceKind.CHECK_RUN, "security-scan"),))
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
    assert "Cleanup: destroyed (verified absent)" in draft
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

        def get_run_logs(self, repo, run_id):
            raise BoundaryError("GitHub HTTP 410")

        def get_pull_diff(self, repo, number):
            raise BoundaryError("GitHub HTTP 500")

    draft = Setup(github=Broken(FIXTURE)).run()
    assert (
        "| missing | check_run | (all check runs) | could not fetch: GitHub HTTP 502 |"
        in draft
    )
    assert "| missing | workflow_log | ci | could not fetch: GitHub HTTP 410 |" in draft
    assert "PASS | check_run" not in draft
    assert "The PR diff could not be fetched" in draft


def test_missing_tarball_skips_the_runner_without_creating_one():
    class NoTarball(FixtureGitHub):
        def get_tarball(self, repo, sha):
            raise NotFoundError("404")

    s = Setup(github=NoTarball(FIXTURE))
    draft = s.run()
    assert s.sprites.calls == []
    assert "Status: skipped" in draft
    assert "Cleanup: no runner was created" in draft
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
    assert "Status: failed" in draft
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

    draft = Setup(harness=DownHarness()).run()
    assert "Harness `skill-bundle` produced no narrative: provider HTTP 529" in draft
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
            return checks

    draft = Setup(github=LeakyName(FIXTURE)).run()
    assert token not in draft
    assert "gate [REDACTED:github-token]" in draft
