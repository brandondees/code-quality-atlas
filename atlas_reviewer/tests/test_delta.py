# SPDX-License-Identifier: MIT
"""The delta review's pieces (#702): the prior findings parsed back from
the round record, the reply's contract, the carry-forward's composition,
and the delta scope. Each behavior is a test that fails when reverted;
the mutant each kills is named. The quote check itself is the
re-assessment judge's (shared, not re-pinned here); what is pinned here
is what the delta review does around it."""

import json

import pytest

from atlas_reviewer.attestation import CheckedFinding
from atlas_reviewer.delta import (
    apply_carry,
    carry_system,
    carry_turn,
    delta_paths,
    delta_review_diff,
    parse_carry_reply,
    parse_prior_line,
)
from atlas_reviewer.domain import PrEvent
from atlas_reviewer.lens_contract import (
    Attribution,
    ContractError,
    Finding,
    LineRange,
    Route,
    Severity,
    Valence,
    WholeFile,
)
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.prompt import RepoText, UntrustedBlock

OLD = "a" * 40
NEW = "b" * 40
EVENT = PrEvent("example-org/example-app", 42, NEW, delta_from=OLD)

# A nonce fence's marker pair, as `fence` renders it.
NONCE = "f00dfeed"


def _line(identifier: str, severity: str, location: str, text: str) -> str:
    return f"{identifier} {severity} {location} {text}"


# ------------------------------------------------------- the prior lines


def test_a_record_finding_line_parses_back():
    found = parse_prior_line(
        _line(
            "L1-F1",
            "major",
            "calc.py:2",
            "rounds each item before summing, so totals drift",
        )
    )
    # Mutant: the parse loosened (severity or id unvalidated), which
    # would carry a garbled line as a finding.
    assert found is not None
    identifier, finding = found
    assert identifier == "L1-F1"
    assert finding.severity is Severity.MAJOR
    assert finding.location == LineRange("calc.py", 2, 2)
    assert finding.finding == "rounds each item before summing, so totals drift"


def test_a_carried_label_parses_back_too():
    found = parse_prior_line(
        _line("P3", "blocker", "src/auth.py:10-12", "token compared unsafely")
    )
    assert found is not None
    identifier, finding = found
    assert identifier == "P3"
    assert finding.severity is Severity.BLOCKER
    assert finding.location == LineRange("src/auth.py", 10, 12)


def test_a_whole_file_location_parses_as_whole_file():
    found = parse_prior_line(_line("P2", "nit", "README.md", "the example is stale"))
    assert found is not None
    assert found[1].location == WholeFile("README.md")


def test_a_line_that_is_not_a_record_finding_parses_to_none():
    # Not four space-separated parts, an unknown severity, and an id
    # outside the two shapes. The location token is always one token by
    # the record's own format, so any token parses as a whole-file path;
    # the id and the severity are the closed sets the parse enforces.
    assert parse_prior_line("L1-F1 major") is None
    assert parse_prior_line("L1-F1 urgent calc.py:2 text") is None
    assert parse_prior_line("nope major calc.py:2 text") is None


def test_a_carried_finding_is_reconstructed_defect_introduced():
    """A prior finding set the earlier review's verdict once; the carry
    reconstructs it so it still counts for the verdict (the conservative
    direction), with no fix or evidence text, because the record stores
    neither."""
    found = parse_prior_line(_line("P1", "major", "calc.py:2", "rounds early"))
    assert found is not None
    finding = found[1]
    assert finding.sets_verdict is True
    assert finding.fix == ""
    assert finding.evidence == ""


# -------------------------------------------------------- the reply


def _carry(
    findings: list[dict[str, str]], withdrawn: list[dict[str, str]] | None = None
) -> str:
    payload: dict[str, object] = {"findings": findings}
    if withdrawn is not None:
        payload["withdrawn"] = withdrawn
    return json.dumps(payload)


def test_the_carry_reply_parses_findings_and_withdrawals():
    reply = parse_carry_reply(
        _carry(
            [
                {
                    "location": "calc.py:2",
                    "evidence": "return sum(round(x, 2) for x in xs)",
                    "severity": "major",
                    "valence": "defect",
                    "route": "eng",
                    "attribution": "introduced",
                    "finding": "still rounds early",
                    "fix": "round once",
                    "revises": "P1",
                    "reason": "the delta did not touch the rounding",
                }
            ],
            [{"id": "P2", "reason": "the delta replaced the unsafe call"}],
        )
    )
    assert len(reply.findings) == 1
    assert reply.findings[0].revises == "P1"
    assert reply.findings[0].reason
    assert reply.withdrawn == (("P2", "the delta replaced the unsafe call"),)


def test_a_withdrawal_without_a_reason_is_refused():
    with pytest.raises(ContractError):
        parse_carry_reply(_carry([], [{"id": "P1", "reason": ""}]))


def test_a_revision_without_a_reason_is_refused():
    raw = {
        "location": "calc.py:2",
        "evidence": "the line",
        "severity": "major",
        "valence": "defect",
        "route": "eng",
        "attribution": "introduced",
        "finding": "x",
        "fix": "y",
        "revises": "P1",
    }
    with pytest.raises(ContractError):
        parse_carry_reply(_carry([raw]))


def test_an_unknown_severity_is_dropped_not_fatal():
    raw = {
        "location": "calc.py:2",
        "evidence": "the line",
        "severity": "urgent",
        "valence": "defect",
        "route": "eng",
        "attribution": "introduced",
        "finding": "x",
        "fix": "y",
    }
    reply = parse_carry_reply(_carry([raw]))
    assert reply.findings == ()
    assert len(reply.dropped) == 1


def test_the_reply_must_name_its_keys():
    with pytest.raises(ContractError):
        parse_carry_reply(json.dumps({}))
    with pytest.raises(ContractError):
        parse_carry_reply("not json at all")


# ------------------------------------------------------- the composition


def _checked(finding: Finding, verified: bool = True) -> CheckedFinding:
    from atlas_reviewer.quotes import QuoteSource

    if verified:
        return CheckedFinding(finding, QuoteSource.HEAD)
    return CheckedFinding(finding, problem="the quote does not verify")


def _prior(identifier: str, text: str, path: str = "calc.py") -> tuple[str, Finding]:
    finding = Finding(
        LineRange(path, 2, 2),
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        text,
        "",
    )
    return identifier, finding


def test_a_restated_prior_that_verifies_is_carried():
    prior = [_prior("P1", "rounds early")]
    reply_finding = Finding(
        LineRange("calc.py", 2, 2),
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "rounds early, restated",
        "round once",
    )
    result = apply_carry(
        prior,
        [_checked(reply_finding)],
        [(1, "P1", "unchanged code")],
        (),
        frozenset({"calc.py"}),
    )
    # Mutant: the composition dropped the re-anchored restatement, which
    # would carry the stale original wording instead.
    assert result.carried == (("P1", _checked(reply_finding)),)
    assert result.unanchored == ()
    assert result.resolved == ()


def test_a_restated_prior_that_does_not_verify_is_carried_as_recorded():
    prior = [_prior("P1", "rounds early")]
    unverified = Finding(
        LineRange("calc.py", 2, 2),
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "not the code",
        "",
    )
    result = apply_carry(
        prior,
        [_checked(unverified, verified=False)],
        [(1, "P1", "moved")],
        (),
        frozenset(),
    )
    # Mutant: an unverified restatement carried as verified, which would
    # post a finding whose quote does not verify at this head.
    assert result.carried == ()
    assert result.unanchored == (("P1", prior[0][1]),)


def test_a_silent_prior_is_carried_as_recorded():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(prior, [], [], (), frozenset({"calc.py"}))
    # Mutant: silence read as resolution, which would let PR content
    # suppress a finding by saying nothing about it.
    assert result.unanchored == (("P1", prior[0][1]),)
    assert result.resolved == ()


def test_a_resolution_on_a_path_the_delta_touched_is_accepted():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "the delta replaced the rounding with integer math")],
        frozenset({"calc.py"}),
    )
    assert result.resolved == (
        ("P1", "the delta replaced the rounding with integer math", prior[0][1]),
    )
    assert result.unanchored == ()


def test_a_resolution_off_the_delta_is_recorded_as_a_proposal():
    prior = [_prior("P1", "rounds early", path="docs/notes.md")]
    result = apply_carry(
        prior, [], [], [("P1", "claims the delta fixed it")], frozenset({"calc.py"})
    )
    # Mutant: the delta-touched gate dropped, which would let PR content
    # resolve a finding on a file the new commits never changed.
    assert result.resolved == ()
    assert result.unanchored == (("P1", prior[0][1]),)
    assert any("did not touch" in note for note in result.notes)


def test_no_prior_finding_is_dropped_by_the_composition():
    prior = [
        _prior("P1", "rounds early"),
        _prior("P2", "second finding", path="docs/notes.md"),
    ]
    result = apply_carry(
        prior,
        [_checked(_prior("P1", "restated")[1])],
        [(1, "P1", "same")],
        [("P2", "unfounded")],
        frozenset(),
    )
    seen = (
        {identifier for identifier, _ in result.carried}
        | {identifier for identifier, _ in result.unanchored}
        | {identifier for identifier, _reason, _finding in result.resolved}
    )
    assert seen == {"P1", "P2"}


# ---------------------------------------------------------- the scope


class _FakeGitHub:
    def __init__(self, compare: dict[str, object]) -> None:
        self._compare = compare
        self.calls: list[tuple[str, str, str]] = []

    def get_pull(self, repo: str, number: int) -> dict[str, object]:
        self.calls.append(("get_pull", repo, str(number)))
        return {}

    def get_compare(self, repo: str, base: str, head: str) -> dict[str, object]:
        self.calls.append(("get_compare", repo, f"{base}...{head}"))
        return self._compare


def test_the_delta_scope_is_the_range_paths_the_pr_diff_shows():
    github = _FakeGitHub(
        {"files": [{"filename": "calc.py"}, {"filename": "docs/from-main.md"}]}
    )
    pr_diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
        "@@ -1,1 +1,1 @@\n-old\n+new\n"
        "diff --git a/settings.ini b/settings.ini\n--- a/settings.ini\n+++ b/settings.ini\n"
        "@@ -1,1 +1,1 @@\n-a\n+b\n"
    )
    paths = delta_paths(github, EVENT, pr_diff)
    # Mutant: the restriction dropped, which would hand the delta review
    # the whole pull request diff -- re-reviewing what the earlier
    # review already covered.
    assert paths == ("calc.py",)
    assert github.calls == [
        ("get_compare", "example-org/example-app", f"{OLD}...{NEW}")
    ]


def test_a_merge_only_push_yields_an_empty_scope():
    github = _FakeGitHub({"files": [{"filename": "docs/from-main.md"}]})
    pr_diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
        "@@ -1,1 +1,1 @@\n-old\n+new\n"
    )
    assert delta_paths(github, EVENT, pr_diff) == ()


def test_a_comparison_without_files_is_an_empty_scope():
    github = _FakeGitHub({})
    assert delta_paths(github, EVENT, "diff --git a/x b/x\n") == ()


def test_a_malformed_files_array_is_a_boundary_error():
    github = _FakeGitHub({"files": "nope"})
    with pytest.raises(BoundaryError):
        delta_paths(github, EVENT, "")


def test_an_unfetchable_range_falls_back_to_the_full_diff_with_a_note():
    class Failing:
        def get_pull(self, repo: str, number: int) -> dict[str, object]:
            return {}

        def get_compare(self, repo: str, base: str, head: str) -> dict[str, object]:
            raise BoundaryError("GitHub HTTP 404")

    diff = "diff --git a/calc.py b/calc.py\n"
    review_diff, note = delta_review_diff(Failing(), EVENT, diff)
    # Mutant: the fallback dropped, which would fail a whole review over
    # an unreadable range instead of reviewing the push in full.
    assert review_diff == diff
    assert "could not be fetched" in note


def test_a_fetchable_range_returns_its_scope_with_no_note():
    github = _FakeGitHub({"files": []})
    review_diff, note = delta_review_diff(github, EVENT, "diff --git a/x b/x\n")
    assert review_diff == ""
    assert note == ""


# ------------------------------------------------------------- the turn


def test_the_carry_turn_fences_the_prior_findings_and_the_delta():
    prior = UntrustedBlock(
        "prior-findings", RepoText("P1 major calc.py:2 rounds early")
    )
    delta = UntrustedBlock("delta-diff", RepoText("diff --git a/calc.py b/calc.py"))
    text = carry_turn(EVENT, prior, delta, NONCE)
    assert text.startswith("Carry-forward target (from the controller):")
    # Mutant: either block shipped outside the fence, which would let
    # model- or PR-written text pose as controller instructions.
    assert 'label="prior-findings"' in text
    assert 'label="delta-diff"' in text
    assert text.count("</untrusted-data") == 2


def test_an_empty_delta_is_omitted_from_the_turn_not_rendered_empty():
    prior = UntrustedBlock(
        "prior-findings", RepoText("P1 major calc.py:2 rounds early")
    )
    text = carry_turn(EVENT, prior, None, NONCE)
    assert "delta-diff" not in text


def test_the_carry_system_carries_the_contract_and_the_fence_rule():
    system = carry_system("FINDING CONTRACT TEXT", NONCE)
    assert "carry-forward assessor" in system
    assert "FINDING CONTRACT TEXT" in system
    assert NONCE in system
