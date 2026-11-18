# SPDX-License-Identifier: MIT
"""The delta review's pieces (#702): the prior findings parsed back from
the round record, the reply's contract, the carry-forward's composition,
the delta scope and its resolution gate, and the evidence a resolution
must carry. Each behavior is a test that fails when reverted; the mutant
each kills is named. The quote check itself is the re-assessment judge's
(shared, not re-pinned here); what is pinned here is what the delta
review does around it."""

import json

import pytest

from atlas_reviewer.attestation import CheckedFinding
from atlas_reviewer.coordinator import CARRY_DIFF_CHARS, _capped
from atlas_reviewer.delta import (
    _patch_removed,
    apply_carry,
    carry_system,
    carry_turn,
    delta_scope,
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
from atlas_reviewer.quotes import QuoteSource
from atlas_reviewer.redact import TRUNCATION_MARKER

OLD = "a" * 40
NEW = "b" * 40
EVENT = PrEvent("example-org/example-app", 42, NEW, delta_from=OLD)

# A nonce fence's marker pair, as `fence` renders it.
NONCE = "f00dfeed"


def _finding(text: str, path: str = "calc.py", start: int = 2) -> Finding:
    return Finding(
        LineRange(path, start, start),
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        text,
        "",
    )


def _prior(identifier: str, text: str, path: str = "calc.py") -> tuple[str, Finding]:
    return identifier, _finding(text, path)


def _checked(finding: Finding, verified: bool = True) -> CheckedFinding:
    if verified:
        return CheckedFinding(finding, QuoteSource.HEAD)
    return CheckedFinding(finding, problem="the quote does not verify")


def _line(identifier: str, severity: str, location: str, text: str) -> str:
    return f"{identifier} {severity} {location} {text}"


# ------------------------------------------------------- the prior lines


def test_a_record_finding_line_parses_back():
    found = parse_prior_line(
        _line(
            "L1-F1",
            "major",
            '"calc.py:2"',
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
        _line("P3", "blocker", '"src/auth.py:10-12"', "token compared unsafely")
    )
    assert found is not None
    identifier, finding = found
    assert identifier == "P3"
    assert finding.severity is Severity.BLOCKER
    assert finding.location == LineRange("src/auth.py", 10, 12)


def test_a_quoted_whole_file_location_parses_as_whole_file():
    found = parse_prior_line(_line("P2", "nit", '"README.md"', "the example is stale"))
    assert found is not None
    assert found[1].location == WholeFile("README.md")


def test_the_unquoted_legacy_form_still_parses_a_line_range():
    """Records written before the location quote keep parsing: a
    space-free line-range token is unambiguous."""
    found = parse_prior_line(_line("L1-F1", "major", "calc.py:2", "rounds early"))
    assert found is not None
    assert found[1].location == LineRange("calc.py", 2, 2)


def test_an_ambiguous_unquoted_location_is_refused_not_mis_parsed():
    """A legacy line whose third token could be either a whole-file path
    or the first word of a location that contains a space is refused:
    the caller names it and carries it as raw text. Mutant: the refusal
    dropped into a whole-file guess, which would corrupt the finding
    silently (round-1 M3)."""
    assert (
        parse_prior_line(_line("L1-F1", "major", "my", "file.py:12 is wrong")) is None
    )
    assert parse_prior_line(_line("L1-F1", "major", "'weird", "location text")) is None


def test_a_quoted_location_with_a_space_parses_whole():
    found = parse_prior_line(
        _line("P1", "minor", '"my file.py:12-14"', "the span drifts")
    )
    assert found is not None
    assert found[1].location == LineRange("my file.py", 12, 14)


def test_a_line_that_is_not_a_record_finding_parses_to_none():
    # Not four space-separated parts, an unknown severity, and an id
    # outside the two shapes. The id and the severity are the closed
    # sets the parse enforces.
    assert parse_prior_line("L1-F1 major") is None
    assert parse_prior_line("L1-F1 urgent calc.py:2 text") is None
    assert parse_prior_line("nope major calc.py:2 text") is None


def test_a_carried_finding_is_reconstructed_defect_introduced():
    """A prior finding set the earlier review's verdict once; the carry
    reconstructs it so it still counts for the verdict (the conservative
    direction), with no fix or evidence text, because the record stores
    neither."""
    found = parse_prior_line(_line("P1", "major", '"calc.py:2"', "rounds early"))
    assert found is not None
    finding = found[1]
    assert finding.sets_verdict is True
    assert finding.fix == ""
    assert finding.evidence == ""


# -------------------------------------------------------- the reply


def _restated(**overrides: str) -> dict[str, str]:
    base = {
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
    return {**base, **overrides}


def _carry(
    findings: list[dict[str, str]],
    withdrawn: list[dict[str, str]] | None = None,
) -> str:
    payload: dict[str, object] = {"findings": findings}
    if withdrawn is not None:
        payload["withdrawn"] = withdrawn
    return json.dumps(payload)


def _resolution(identifier: str, reason: str, evidence: str) -> dict[str, str]:
    """The reply's withdrawn entry as JSON holds it (for the parse tests);
    the composition tests pass the parsed `(id, reason, evidence)`
    tuples directly."""
    return {"id": identifier, "reason": reason, "evidence": evidence}


def test_the_carry_reply_parses_findings_and_resolutions():
    reply = parse_carry_reply(
        _carry(
            [_restated()],
            [_resolution("P2", "the delta replaced the unsafe call", "old_call(x)")],
        )
    )
    assert len(reply.findings) == 1
    assert reply.findings[0].revises == "P1"
    assert reply.findings[0].reason
    assert reply.withdrawn == (
        ("P2", "the delta replaced the unsafe call", "old_call(x)"),
    )


def test_a_resolution_without_evidence_is_refused():
    # Mutant: the evidence requirement dropped -- a resolution would then
    # stand on the model's say-so alone (round-1 M2).
    for broken in (
        {"id": "P1", "reason": "fixed"},
        {"id": "P1", "reason": "fixed", "evidence": ""},
        {"id": "P1", "reason": "", "evidence": "code()"},
        {"id": "P1", "reason": "fixed", "evidence": "code()", "extra": "x"},
    ):
        with pytest.raises(ContractError):
            parse_carry_reply(_carry([], [broken]))


def test_a_revision_without_a_reason_is_refused():
    raw = _restated(reason="")
    with pytest.raises(ContractError):
        parse_carry_reply(_carry([raw]))


def test_an_unknown_severity_is_dropped_not_fatal():
    raw = _restated(severity="urgent")
    reply = parse_carry_reply(_carry([raw]))
    assert reply.findings == ()
    assert len(reply.dropped) == 1


def test_the_reply_must_name_its_keys():
    with pytest.raises(ContractError):
        parse_carry_reply(json.dumps({}))
    with pytest.raises(ContractError):
        parse_carry_reply("not json at all")


# ------------------------------------------------------- the composition


def test_a_restated_prior_that_verifies_is_carried():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [_checked(_finding("rounds early, restated"))],
        [(1, "P1", "unchanged code")],
        (),
        frozenset({"calc.py"}),
        {},
    )
    # Mutant: the composition dropped the re-anchored restatement, which
    # would carry the stale original wording instead.
    assert result.carried == (("P1", _checked(_finding("rounds early, restated"))),)
    assert result.unanchored == ()
    assert result.resolved == ()


def test_a_restated_prior_that_does_not_verify_is_carried_as_recorded():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [_checked(_finding("not the code"), verified=False)],
        [(1, "P1", "moved")],
        (),
        frozenset(),
        {},
    )
    # Mutant: an unverified restatement carried as verified, which would
    # post a finding whose quote does not verify at this head.
    assert result.carried == ()
    assert result.unanchored == (("P1", prior[0][1]),)


def test_a_silent_prior_is_carried_as_recorded():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(prior, [], [], (), frozenset({"calc.py"}), {})
    # Mutant: silence read as resolution, which would let PR content
    # suppress a finding by saying nothing about it.
    assert result.unanchored == (("P1", prior[0][1]),)
    assert result.resolved == ()


def _removed(*entries: tuple[int, str]) -> dict[str, tuple[tuple[int, str], ...]]:
    """The range's removed-line pool as a patch yields it: `(old-side
    line number, text)` pairs for one file."""
    return {"calc.py": entries}


def test_a_resolution_with_evidence_on_a_delta_path_is_accepted():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "the delta replaced the rounding", "return sum(xs)")],
        frozenset({"calc.py"}),
        _removed((2, "    return sum(xs)"), (7, "    other = 1")),
        tolerance=3,
    )
    # The quoted code is among the lines the delta removed: real evidence
    # the new commits took the cited code out (round-1 M2).
    assert result.resolved == (("P1", "the delta replaced the rounding", prior[0][1]),)
    assert result.unanchored == ()


def test_a_resolution_whose_evidence_still_stands_is_refused():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "claims the fix", "unrelated_line()")],
        frozenset({"calc.py"}),
        _removed((2, "    return sum(xs)")),
        tolerance=3,
    )
    # Mutant: the evidence check dropped -- a resolution would be
    # accepted for code the delta never removed (round-1 M2).
    assert result.resolved == ()
    assert result.unanchored == (("P1", prior[0][1]),)
    assert any("not among the lines" in note for note in result.notes)


def test_a_resolution_whose_evidence_partially_matches_is_refused():
    """Every quoted line must be among the removed lines: a resolution
    quoting one removed and one still-standing line is ambiguous, and
    ambiguity keeps the finding."""
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "partial rewrite", "return sum(xs)\n    kept = 2")],
        frozenset({"calc.py"}),
        _removed((2, "    return sum(xs)")),
        tolerance=3,
    )
    assert result.resolved == ()
    assert result.unanchored == (("P1", prior[0][1]),)


def test_a_resolution_off_the_delta_is_recorded_as_a_proposal():
    prior = [_prior("P1", "rounds early", path="docs/notes.md")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "claims the delta fixed it", "gone()")],
        frozenset({"calc.py"}),
        {},
    )
    # Mutant: the delta-touched gate dropped, which would let PR content
    # resolve a finding on a file the new commits never changed.
    assert result.resolved == ()
    assert result.unanchored == (("P1", prior[0][1]),)
    assert any("did not touch" in note for note in result.notes)


def test_an_unestablished_delta_refuses_every_resolution():
    """The gate fails closed (#702 round-1 M1): when the delta could not
    be established -- an unfetchable range, a diverged history, a cut
    comparison -- `resolution_paths` is empty, and no resolution is
    accepted however well-evidenced its quote looks, because the
    evidence's meaning depends on the delta being the delta."""
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "claims the fix", "return sum(xs)")],
        frozenset(),
        _removed((2, "    return sum(xs)")),
        gate_reason="the delta range could not be established",
    )
    # Mutant: the empty gate treated as "everything is touchable", which
    # would accept resolutions on the fallback path (round-1 M1).
    assert result.resolved == ()
    assert result.unanchored == (("P1", prior[0][1]),)
    assert any("could not be established" in note for note in result.notes)


def test_no_prior_finding_is_dropped_by_the_composition():
    prior = [
        _prior("P1", "rounds early"),
        _prior("P2", "second finding", path="docs/notes.md"),
    ]
    result = apply_carry(
        prior,
        [_checked(_finding("restated"))],
        [(1, "P1", "same")],
        [("P2", "unfounded", "gone()")],
        frozenset(),
        {},
    )
    seen = (
        {identifier for identifier, _ in result.carried}
        | {identifier for identifier, _ in result.unanchored}
        | {identifier for identifier, _reason, _finding in result.resolved}
    )
    assert seen == {"P1", "P2"}


def test_a_reply_addition_is_dropped_and_named():
    """The assessor's job is dispositions, not new findings: an entry
    with no `revises` key is dropped from the buckets and named, because
    the lenses report the delta's findings (round-1 m5)."""
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [_checked(_finding("a new finding the assessor added"))],
        [],
        [],
        frozenset({"calc.py"}),
        {},
    )
    assert result.carried == ()
    assert result.unanchored == (("P1", prior[0][1]),)
    assert any("added" in note for note in result.notes)


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


PR_DIFF = (
    "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
    "@@ -1,1 +1,1 @@\n-old\n+new\n"
    "diff --git a/settings.ini b/settings.ini\n--- a/settings.ini\n+++ b/settings.ini\n"
    "@@ -1,1 +1,1 @@\n-a\n+b\n"
)


def test_the_delta_scope_is_the_range_paths_the_pr_diff_shows():
    github = _FakeGitHub(
        {
            "merge_base_commit": {"sha": OLD},
            "files": [{"filename": "calc.py"}, {"filename": "docs/from-main.md"}],
        }
    )
    scope = delta_scope(github, EVENT, PR_DIFF)
    # Mutant: the restriction dropped, which would hand the delta review
    # the whole pull request diff -- re-reviewing what the earlier
    # review already covered.
    assert scope.diff == PR_DIFF.split("diff --git a/settings.ini")[0]
    # The resolution gate is the range's own touched paths, not the
    # lens diff's intersection with them (round-5 review of #748): a
    # follow-up that deletes a file the earlier head added takes it out
    # of the net diff, and the range's patch is then the only place its
    # removal evidence lives. A gate path with no patch still refuses
    # on evidence, so the wider set cannot accept more.
    assert scope.resolution_paths == frozenset({"calc.py", "docs/from-main.md"})
    assert scope.note == ""
    assert github.calls == [
        ("get_compare", "example-org/example-app", f"{OLD}...{NEW}"),
    ]


def test_a_merge_only_push_yields_an_empty_trusted_scope():
    github = _FakeGitHub(
        {
            "merge_base_commit": {"sha": OLD},
            "files": [{"filename": "docs/from-main.md"}],
        }
    )
    scope = delta_scope(github, EVENT, PR_DIFF)
    assert scope.diff == ""
    # The gate is the range's own touched paths (round-5 review of
    # #748); this path has no patch in the comparison, so a resolution
    # against it still refuses on evidence.
    assert scope.resolution_paths == frozenset({"docs/from-main.md"})
    assert scope.note == ""


def test_an_unfetchable_range_falls_back_to_the_full_diff_and_refuses_resolutions():
    """The gate fails closed on the fallback (round-1 M1): the review
    still runs, on the full diff, but the scope's resolution paths are
    empty and the gap is named, because a full diff is not evidence of
    what the delta's commits touched. Mutant: the fallback's gate kept
    the full diff's paths, which would accept resolutions for files the
    new commits never changed."""

    class Failing:
        def get_pull(self, repo: str, number: int) -> dict[str, object]:
            return {}

        def get_compare(self, repo: str, base: str, head: str) -> dict[str, object]:
            raise BoundaryError("GitHub HTTP 404")

    scope = delta_scope(Failing(), EVENT, PR_DIFF)
    # Mutant: the fallback dropped, which would fail a whole review over
    # an unreadable range instead of reviewing the push in full.
    assert scope.diff == PR_DIFF
    assert scope.resolution_paths == frozenset()
    assert "could not be fetched" in scope.note
    assert scope.gate_reason


def test_a_diverged_history_refuses_resolutions_and_names_the_condition():
    """A rebase or force-push leaves `delta_from` a non-ancestor: the
    comparison's file list is then measured from the wrong base, so it is
    not the range's, and the resolution gate refuses (round-1 M1). The
    lens diff is not narrowed to that list either (round-5 review of
    #748): a wrong-base list cannot prove what the range touched, and a
    pull-request file it omits would reach no lens while the coverage
    read complete. Mutant: the narrowing restored, which drops those
    files from the review."""
    github = _FakeGitHub(
        {"merge_base_commit": {"sha": "e" * 40}, "files": [{"filename": "calc.py"}]}
    )
    scope = delta_scope(github, EVENT, PR_DIFF)
    # Mutant: the lens diff narrowed to the wrong-base list's paths.
    assert scope.diff == PR_DIFF
    assert scope.resolution_paths == frozenset()
    assert "diverged" in scope.note
    assert "full pull request diff" in scope.note
    assert "diverged" in scope.gate_reason


def test_a_cut_file_list_refuses_resolutions_and_names_the_cap():
    """A comparison at GitHub's files cap may be cut: what the range
    touched is then not fully known, so the gate refuses rather than
    silently shrinking the delta (round-1 m3). The lens diff does not
    narrow to the cut list either (round-5 review of #748, Major 1):
    files past the cap would reach no lens while `coverage_complete`
    stayed true, and `_lens_gap` does not read the delta note. Mutant:
    the narrowing restored, which hides the cap-tail files."""
    capped = [{"filename": f"src/f{n}.py"} for n in range(300)]
    github = _FakeGitHub({"merge_base_commit": {"sha": OLD}, "files": capped})
    scope = delta_scope(github, EVENT, PR_DIFF)
    # Mutant: the lens diff narrowed to the cut list's paths.
    assert scope.diff == PR_DIFF
    assert scope.resolution_paths == frozenset()
    assert "not fully known" in scope.note
    assert "full pull request diff" in scope.note
    assert scope.gate_reason


def test_a_malformed_files_entry_makes_the_list_incomplete():
    github = _FakeGitHub(
        {"merge_base_commit": {"sha": OLD}, "files": [{"filename": "calc.py"}, "junk"]}
    )
    scope = delta_scope(github, EVENT, PR_DIFF)
    assert scope.resolution_paths == frozenset()
    assert "not fully known" in scope.note


def test_a_comparison_without_a_files_array_is_untrusted():
    github = _FakeGitHub({"merge_base_commit": {"sha": OLD}})
    scope = delta_scope(github, EVENT, PR_DIFF)
    # Mutant: a missing files key read as an empty delta -- which would
    # be indistinguishable from a merge-only push and would silently
    # shrink the review (round-1 m3).
    assert scope.diff == PR_DIFF
    assert scope.resolution_paths == frozenset()
    assert "could not be fetched" in scope.note


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
    # The resolution's evidence requirement is in the instructions, so
    # the assessor knows a proposal carries the removed code's quote.
    assert "removed" in system


def test_the_instructions_do_not_invite_findings_the_composition_drops():
    """The instructions ask for dispositions only: an added finding is
    dropped and named by the composition, so the prompt must not request
    work the composition throws away (round-1 m5)."""
    system = carry_system("", NONCE)
    assert "add a finding the delta reveals" not in system


# ------------------------------------------------- round-2 fixes (#748)


def test_the_pool_is_the_range_patch_not_the_restricted_pr_diff():
    """Major A (round 2): the evidence pool comes from the comparison's
    per-file patches -- the `delta_from..head` range's own deletions --
    not from the pull request's `base...head` net diff restricted to
    range paths. A delta commit deleting PR-added code is invisible in
    the net diff (the line exists at neither end) and a pre-`delta_from`
    PR removal sits in the net diff while having nothing to do with the
    new commits. Mutant: the pool rebuilt from the restricted diff,
    which loses the deletion and keeps the stale one."""
    compare = {
        "merge_base_commit": {"sha": OLD},
        "files": [
            {
                "filename": "calc.py",
                "patch": (
                    "@@ -2,3 +2,2 @@\n"
                    " context\n"
                    "-deleted by the delta\n"
                    "+added by the delta\n"
                ),
            }
        ],
    }
    github = _FakeGitHub(compare)
    pr_diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-removed before the delta\n"
        "+kept by the delta\n"
    )
    scope = delta_scope(github, EVENT, pr_diff)
    assert scope.removed["calc.py"] == ((3, "deleted by the delta"),)
    assert "deleted by the delta" in scope.range_diff
    assert "removed before the delta" not in scope.range_diff
    # The pool and the restricted PR diff genuinely disagree: a
    # resolution quoting the PR diff's stale removal is refused, one
    # quoting the range's real deletion is accepted.
    prior = [_prior("P1", "rounds early")]
    refused = apply_carry(
        prior,
        [],
        [],
        [("P1", "quotes the stale net-diff removal", "removed before the delta")],
        scope.resolution_paths,
        scope.removed,
        tolerance=3,
    )
    assert refused.resolved == ()
    accepted = apply_carry(
        prior,
        [],
        [],
        [("P1", "quotes the range's deletion", "deleted by the delta")],
        scope.resolution_paths,
        scope.removed,
        tolerance=3,
    )
    assert accepted.resolved == (("P1", "quotes the range's deletion", prior[0][1]),)


def test_a_patch_is_parsed_with_its_old_side_numbers():
    """The pool carries old-side positions, so the span bound can check
    a quote against the coordinates the prior finding cites: hunks set
    the counter, `-` lines consume it, `+` lines and context do not."""
    patch = "@@ -10,4 +10,3 @@\n keep\n-first out\n ctx\n-second out\n+in\n"
    assert _patch_removed(patch) == ((11, "first out"), (13, "second out"))


def test_a_missing_merge_base_reads_as_diverged():
    """The one malformed shape the fail-closed rework missed (round-2
    a1): a comparison with no readable merge base must not have its file
    list trusted as the range's. Mutant: the missing sha read as
    not-diverged, which would trust the pool on a malformed reply."""
    github = _FakeGitHub(
        {"files": [{"filename": "calc.py", "patch": "@@ -1,1 +1,1 @@\n-x\n"}]}
    )
    scope = delta_scope(github, EVENT, PR_DIFF)
    assert scope.resolution_paths == frozenset()
    assert scope.removed == {}
    assert "diverged" in scope.note


def test_the_range_patches_render_into_the_turns_diff():
    """The carry turn's delta block is the range's own patches, with one
    `diff --git` header per file, so the assessor can quote what the
    commits between the heads actually changed."""
    compare = {
        "merge_base_commit": {"sha": OLD},
        "files": [
            {"filename": "calc.py", "patch": "@@ -1,1 +1,1 @@\n-a\n+b\n"},
            {"filename": "docs/x.md", "patch": "@@ -1,1 +1,1 @@\n-c\n+d\n"},
        ],
    }
    scope = delta_scope(_FakeGitHub(compare), EVENT, PR_DIFF)
    assert scope.range_diff.count("diff --git") == 2
    assert 'label="delta-diff"' not in scope.range_diff


def test_a_delta_over_its_cap_is_cut_with_the_marker():
    """The carry turn's delta block is capped with the truncation marker,
    never shipped oversized to the per-call token check (round-2 a4)."""
    text = _capped("x" * (CARRY_DIFF_CHARS + 100), CARRY_DIFF_CHARS)
    assert len(text) == CARRY_DIFF_CHARS
    assert text.endswith(TRUNCATION_MARKER)
    whole = _capped("x" * 10, CARRY_DIFF_CHARS)
    assert whole == "x" * 10


def test_evidence_outside_the_cited_span_is_refused():
    """The evidence check is bounded to the finding's cited span, widened
    by the tolerance: any removed line in the file -- down to a one-line
    deletion far from the finding -- does not clear the gate (round-2
    a2). Mutant: the span bound dropped, which accepts a resolution on
    an unrelated removal."""
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "claims the fix", "unrelated = 1")],
        frozenset({"calc.py"}),
        _removed((90, "    unrelated = 1")),
        tolerance=3,
    )
    assert result.resolved == ()
    assert result.unanchored == (("P1", prior[0][1]),)
    assert any("not among the lines" in note for note in result.notes)


def test_evidence_within_the_tolerance_of_the_span_is_accepted():
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "the fix", "shifted = 1")],
        frozenset({"calc.py"}),
        _removed((5, "    shifted = 1")),
        tolerance=3,
    )
    assert result.resolved == (("P1", "the fix", prior[0][1]),)


def test_a_whole_file_finding_takes_any_removed_line_of_the_file():
    prior = [
        (
            "P1",
            Finding(
                WholeFile("calc.py"),
                Severity.MAJOR,
                Valence.DEFECT,
                Route.ENG,
                Attribution.INTRODUCED,
                "this file is wrong",
                "",
            ),
        )
    ]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "the file is gone", "anything at all")],
        frozenset({"calc.py"}),
        _removed((4, "    anything at all")),
        tolerance=3,
    )
    assert result.resolved == (("P1", "the file is gone", prior[0][1]),)


# ----------------------------------------------------- round-3 fixes


def test_a_blocker_restated_as_a_nit_keeps_the_recorded_severity():
    """Major C (round 3): a verified re-statement cannot lower the
    recorded severity on model say-so -- the D73 rule. The composed
    carried finding keeps the recorded severity with the re-anchored
    location and wording, and the proposal is named. Mutant: the guard
    dropped -- a carried Blocker restated as a nit flips the verdict to
    approve."""
    prior_finding = Finding(
        LineRange("calc.py", 2, 2),
        Severity.BLOCKER,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "the rounding loses money",
        "",
    )
    restated = Finding(
        LineRange("calc.py", 2, 2),
        Severity.NIT,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "the rounding loses money, restated",
        "",
    )
    result = apply_carry(
        [("P1", prior_finding)],
        [_checked(restated)],
        [(1, "P1", "the delta added a guard")],
        (),
        frozenset({"calc.py"}),
        {},
    )
    # Mutant target: the composed severity the nit's.
    assert result.carried[0][1].finding.severity is Severity.BLOCKER
    assert result.carried[0][1].finding.location == LineRange("calc.py", 2, 2)
    assert result.carried[0][1].finding.finding == "the rounding loses money, restated"
    assert any("proposed lowering" in note for note in result.notes)


def test_a_restatement_raising_severity_is_taken():
    """The conservative direction takes a raise: a re-statement may make
    a finding worse, and the composed finding carries the raised
    severity."""
    prior_finding = Finding(
        LineRange("calc.py", 2, 2),
        Severity.MINOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "drift",
        "",
    )
    raised = Finding(
        LineRange("calc.py", 2, 2),
        Severity.BLOCKER,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "drift, worse",
        "",
    )
    result = apply_carry(
        [("P1", prior_finding)],
        [_checked(raised)],
        [(1, "P1", "the delta made it worse")],
        (),
        frozenset({"calc.py"}),
        {},
    )
    assert result.carried[0][1].finding.severity is Severity.BLOCKER
    assert result.notes == ()


def test_a_restatement_trading_the_verdict_shape_is_refused_the_same_way():
    """A re-statement that moves the finding off defect-introduced --
    `valence: improvement` or `attribution: pre-existing` -- drops out
    of the verdict-setting set the same way a lowering does, so the
    recorded shape stands (round-3 Major C's second half)."""
    prior_finding = Finding(
        LineRange("calc.py", 2, 2),
        Severity.MAJOR,
        Valence.DEFECT,
        Route.ENG,
        Attribution.INTRODUCED,
        "drift",
        "",
    )
    improved = Finding(
        LineRange("calc.py", 2, 2),
        Severity.MAJOR,
        Valence.IMPROVEMENT,
        Route.ENG,
        Attribution.INTRODUCED,
        "drift, restated",
        "",
    )
    result = apply_carry(
        [("P1", prior_finding)],
        [_checked(improved)],
        [(1, "P1", "an opinion")],
        (),
        frozenset({"calc.py"}),
        {},
    )
    assert result.carried[0][1].finding.valence is Valence.DEFECT
    assert any("proposed making it improvement" in note for note in result.notes)


def test_a_patch_parses_sql_comments_and_ignores_the_marker():
    r"""The patch parser's two fixes (round-3 a7): a removed line shaped
    like a `---` file header is content when it sits inside a hunk (a
    SQL or Lua comment), and the `\ No newline` marker moves no
    counter. Mutant: the blanket `---` exclusion ate the SQL line, and
    the marker shifted every later number."""
    patch = (
        "@@ -3,5 +3,4 @@\n"
        " keep\n"
        "--- a sql comment\n"
        "-- a lua comment\n"
        "\\ No newline at end of file\n"
        "-next real\n"
    )
    assert _patch_removed(patch) == (
        (4, "-- a sql comment"),
        (5, "- a lua comment"),
        (6, "next real"),
    )


def test_a_header_shaped_line_before_the_first_hunk_is_still_skipped():
    """A `--- ` line before any hunk is a file header, not content --
    the one place the exclusion still applies."""
    patch = "--- a/calc.py\n@@ -1,1 +1,1 @@\n-x\n"
    assert _patch_removed(patch) == ((1, "x"),)


# ------------------------------------------------- round-5 fixes (#748)


def test_a_resolution_for_a_file_the_followup_deletes_is_accepted():
    """The gate is the range's own touched paths (round-5 review of
    #748): a follow-up that deletes a file the earlier head added takes
    it out of the pull request's net diff entirely -- the lens diff's
    path intersection no longer contains it -- while the range's patch
    holds the cited removal. Mutant: the gate rebuilt from the
    intersection, which refuses the one resolution that is real."""
    github = _FakeGitHub(
        {
            "merge_base_commit": {"sha": OLD},
            "files": [
                {
                    "filename": "calc.py",
                    "patch": (
                        "@@ -1,3 +0,0 @@\n-def line_total():\n-    return sum(xs)\n"
                    ),
                }
            ],
        }
    )
    pr_diff = ""  # The net diff no longer shows the deleted file at all.
    scope = delta_scope(github, EVENT, pr_diff)
    # Mutant: the gate derived from the lens diff's paths (empty here).
    assert scope.resolution_paths == frozenset({"calc.py"})
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "the follow-up deleted the file", "    return sum(xs)")],
        scope.resolution_paths,
        scope.removed,
        tolerance=3,
    )
    assert result.resolved == (("P1", "the follow-up deleted the file", prior[0][1]),)


def test_a_renamed_files_removed_lines_are_keyed_by_the_old_path():
    """A rename's patch measures its old-side lines from the file the
    patch removes from -- `previous_filename` -- which is the path the
    earlier review's finding cites; keyed by the new name alone, a
    withdrawal of code the rename's commit deleted could never find its
    evidence (round-5 review of #748). Mutant: the pool keyed by the
    new name, which refuses the resolution."""
    github = _FakeGitHub(
        {
            "merge_base_commit": {"sha": OLD},
            "files": [
                {
                    "filename": "renamed.py",
                    "previous_filename": "calc.py",
                    "patch": "@@ -2,1 +2,0 @@\n-    return sum(xs)\n",
                }
            ],
        }
    )
    scope = delta_scope(github, EVENT, "diff --git a/renamed.py b/renamed.py\n")
    assert "calc.py" in scope.removed
    assert "renamed.py" not in scope.removed
    prior = [_prior("P1", "rounds early")]
    result = apply_carry(
        prior,
        [],
        [],
        [("P1", "the rename's commit removed the cited code", "    return sum(xs)")],
        scope.resolution_paths,
        scope.removed,
        tolerance=3,
    )
    assert result.resolved == (
        ("P1", "the rename's commit removed the cited code", prior[0][1]),
    )


def test_a_patch_line_with_a_unicode_line_separator_stays_one_line():
    """The patch is split on LF only (round-5 review of #748): a U+2028
    inside a context line is content, not a record boundary -- splitting
    on it would count an extra old-side line and shift every later
    number in the hunk, rejecting valid evidence at the span boundary.
    Mutant: `splitlines()` restored, which shifts the removal."""
    patch = (
        "@@ -1,3 +1,3 @@\n"
        " context\u2028 still one line\n"
        "-    return sum(xs)\n"
        "+    return total\n"
    )
    assert _patch_removed(patch) == ((2, "    return sum(xs)"),)


def test_a_location_with_a_double_quote_is_refused_at_the_contract():
    """The round record writes a finding's location quoted, so a quote
    inside the path would end the record's location at the wrong place
    on the next read (round-5 review of #748) -- the mint-side contract
    refuses it instead, and the record can never hold one. Mutant: the
    rejection dropped, which mints a location the next round misreads."""
    from atlas_reviewer.lens_contract import parse_location

    with pytest.raises(ContractError, match="double quote"):
        parse_location('pkg/a" b.py:7')
    with pytest.raises(ContractError, match="double quote"):
        parse_location('pkg/a"b.py')
    # Ordinary paths, spaces included, still parse.
    assert parse_location("pkg/a b.py:7") == LineRange("pkg/a b.py", 7, 7)


def test_a_quoted_location_with_a_space_round_trips_through_the_record():
    """The round-trip the record contract rests on: a location with a
    space parses back whole (the quotes exist for exactly this), and the
    reader still refuses the ambiguous legacy forms."""
    from atlas_reviewer.rounds import RoundRecord

    line = 'P1 major "pkg/a b.py:7" the finding text'
    record = RoundRecord("o/r", 7, NEW, "tracing", "COMMENT", (line,), False)
    assert record.findings == (line,)
