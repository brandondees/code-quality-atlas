# SPDX-License-Identifier: MIT
"""The offline scorer: protocol parsing, finding match, and the APPROVE gate."""

import io
import json
from pathlib import Path

import pytest

from atlas_reviewer import cli
from atlas_reviewer.eval_harness import (
    CandidateReview,
    EvalFinding,
    EvalFormatError,
    EvalReview,
    ReferenceRow,
    coverage_lenses,
    example_json,
    findings_expected,
    gate_failures,
    load_directory,
    load_reference_set,
    protocol_review,
    run_mode,
    score,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "eval-score"

PROTOCOL = """\
## Round 1 — Minor findings, not blocking merge
<!-- atlas-review round:1 layer-diff:abc -->

**Verdict:** no Blocker and no Major.
"""

APPROVE = """\
## Round 2 — APPROVE (own-PR, posted as comment)
<!-- atlas-review round:2 layer-diff:def -->
"""

COMMENT = {
    "path": "atlas_reviewer/openrouter.py",
    "line": None,
    "original_line": 314,
    "body": (
        "**Minor · tracing-correctness-and-invariants / hunting-silent-failures"
        " (fail-safe default)**\n\nThe fail-closed choice is sound. "
        "token = 'ghp_" + ("a" * 36) + "'\n"
    ),
}

RABBIT = {
    "path": "atlas_reviewer/openrouter.py",
    "line": 10,
    "body": "<!-- coderabbit-ai-generated:v1 -->\n\n**Minor · Functional Correctness**\n",
}


def test_protocol_review_reads_the_round_heading_and_redacts_the_summary():
    parsed = protocol_review(
        PROTOCOL, [COMMENT, RABBIT, {"body": "thanks", "path": "a.py"}]
    )
    assert parsed is not None
    number, review = parsed
    assert number == 1
    assert review.verdict == "COMMENT"
    (finding,) = review.findings
    assert finding.severity == "minor"
    assert finding.path == "atlas_reviewer/openrouter.py"
    assert finding.line_start == 314
    assert finding.lenses == (
        "tracing-correctness-and-invariants",
        "hunting-silent-failures",
    )
    assert "ghp_" not in finding.summary
    assert "[REDACTED:" in finding.summary


def test_run_mode_flags_a_coordinator_verified_round_and_reads_a_lens_list():
    fan = (
        PROTOCOL + "\n**Coverage.** Lenses run: `reviewing-test-quality`, loaded from "
        "the vendored skills.\n"
    )
    partial = (
        PROTOCOL + "\n**Coverage.** This round is coordinator-verified. "
        "It did not complete lens fan-out. Lenses run: `hunting-silent-failures`.\n"
    )
    assert run_mode(fan) == "lens-fan-out"
    assert coverage_lenses(fan) == ("reviewing-test-quality",)
    assert run_mode(partial) == "coordinator-verified"
    assert run_mode(PROTOCOL) == "unrecorded"
    reran = (
        "## Round 2 — notes\n**Coverage:** I re-ran `auditing-documentation-health`.\n"
    )
    assert run_mode(reran) == "lens-fan-out"
    assert coverage_lenses(reran) == ("auditing-documentation-health",)
    assert run_mode("## Round 2 — notes\ncoordinator verified the partial pass\n") == (
        "coordinator-verified"
    )


def test_extras_and_a_different_verdict_do_not_fail_and_a_stopped_lens_does():
    reference = EvalReview(
        "REQUEST_CHANGES",
        (EvalFinding("major", "a.py", "bug", 10, 12, ("sweeping-for-security",)),),
    )
    candidate = CandidateReview(
        "APPROVE",
        (
            EvalFinding("nit", "a.py", "nearby", 14, 14),
            EvalFinding("blocker", "z.py", "extra", 1, 1),
        ),
        True,
        0,
        ("a.py",),
        ("sweeping-for-security",),
    )
    scored = score(reference, candidate)
    assert scored.matched == 1
    assert scored.extras == 1
    assert scored.recall == 1.0
    assert scored.verdict_agrees is False
    assert gate_failures(reference, candidate, scored) == ()
    stopped = CandidateReview(
        "APPROVE",
        (EvalFinding("nit", "a.py", "nearby", 14, 14),),
        True,
        0,
        ("a.py",),
        ("sweeping-for-security",),
        ("reviewing-test-quality",),
        ("hunting-silent-failures",),
    )
    failures = gate_failures(reference, stopped, score(reference, stopped))
    assert any("NOT RUN" in item for item in failures)
    assert any("failed" in item for item in failures)


def test_split_headings_body_findings_ranges_and_approved_state_are_kept():
    parsed = protocol_review(
        "## Round 1 — Minor findings, not blocking merge\n<!-- atlas-review round:1 -->\n",
        [
            {
                "path": "docs/plan.md",
                "line": 4,
                "start_line": 1,
                "body": (
                    "**Minor** · `reviewing-pr-and-process-hygiene` / "
                    "`auditing-documentation-health` · the index omits D33\n"
                ),
            }
        ],
    )
    assert parsed is not None
    finding = parsed[1].findings[0]
    assert finding.severity == "minor"
    assert finding.line_start == 1 and finding.line_end == 4
    assert "reviewing-pr-and-process-hygiene" in finding.lenses
    body = (
        "## Round 1 — Major findings, not blocking merge\n"
        "<!-- atlas-review round:1 -->\n"
        "### Major\n"
        "**`atlas_reviewer/tests/test_domain.py:88`: unused suppression**\n"
    )
    major = protocol_review(body, [])
    assert major is not None
    assert major[1].findings[0].path == "atlas_reviewer/tests/test_domain.py"
    assert major[1].findings[0].line_start == 88
    anchored = protocol_review(
        "## Round 2 — Major finding, not blocking merge\n"
        "**Major · `pyproject.toml:28` (not in this diff) · stale version pin**\n",
        [],
    )
    assert anchored is not None
    assert anchored[1].findings[0].path == "pyproject.toml"
    approved = protocol_review(
        "## Round 1 — no new findings at or above this round's floor\n",
        [],
        state="APPROVED",
    )
    assert approved is not None and approved[1].verdict == "APPROVE"
    clean = protocol_review(
        "## Round 2 — no new findings at or above this round's floor\n",
        [],
        state="COMMENTED",
    )
    assert clean is not None and clean[1].verdict == "APPROVE"
    assert run_mode("the notes say this is not coordinator-verified\n") == "unrecorded"
    covered = (
        "## Round 1 — notes\n### Coverage\n"
        "- **Lenses:** `reviewing-test-quality`, loaded from the vendored copy.\n"
    )
    assert run_mode(covered) == "lens-fan-out"


def test_one_easy_pair_beside_unscored_references_does_not_open_the_gate(tmp_path):
    (tmp_path / "ref.json").write_text(
        json.dumps({"output": {"verdict": "APPROVE", "findings": []}}),
        encoding="utf-8",
    )
    (tmp_path / "easy.json").write_text(
        json.dumps(_passing_pair("abc123")),
        encoding="utf-8",
    )
    report = load_directory(tmp_path, head="abc123")
    assert report["gate_pass"] is False
    assert any("no candidate" in item for item in report["gate_failures"])


def test_a_full_directory_passes_only_with_the_head_and_an_over_context_pair(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "atlas_reviewer.eval_harness.load_reference_set",
        lambda: {
            ("o/r", 1, 1, "abc123"): ReferenceRow(EvalReview("APPROVE", ()), False)
        },
    )
    pair = _passing_pair("abc123")
    pair["input"]["repo"] = "o/r"
    (tmp_path / "pair.json").write_text(json.dumps(pair), encoding="utf-8")
    assert load_directory(tmp_path, head="abc123")["gate_pass"] is False
    pair["metadata"]["over_context_window"] = True
    (tmp_path / "pair.json").write_text(json.dumps(pair), encoding="utf-8")
    assert load_directory(tmp_path, head="abc123")["gate_pass"] is True
    assert load_directory(tmp_path, head="other")["gate_pass"] is False
    pair["input"]["pr"] = 99
    (tmp_path / "pair.json").write_text(json.dumps(pair), encoding="utf-8")
    missed = load_directory(tmp_path, head="abc123")
    assert missed["gate_pass"] is False
    assert any("calibration row o/r#1" in item for item in missed["gate_failures"])
    pair["input"]["pr"] = 1
    pair["input"]["head_sha"] = "b" * 40
    (tmp_path / "pair.json").write_text(json.dumps(pair), encoding="utf-8")
    spoofed = load_directory(tmp_path, head="b" * 40)
    assert spoofed["gate_pass"] is False
    assert any("no passing pair for head" in item for item in spoofed["gate_failures"])
    fresh = _passing_pair("c" * 40)
    fresh["input"]["repo"] = "other/app"
    fresh["input"]["pr"] = 9
    fresh["candidate"]["lenses_run"] = ["reviewing-test-quality"]
    fresh["metadata"]["run"] = "lens-fan-out"
    (tmp_path / "head.json").write_text(json.dumps(fresh), encoding="utf-8")
    opened = load_directory(tmp_path, head="c" * 40)
    assert opened["gate_pass"] is True


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda pair: pair["metadata"].__setitem__("run", "one-shot"),
            "must record lens-fan-out",
        ),
        (
            lambda pair: pair["candidate"].__setitem__("lenses_run", []),
            "does not record a lens that ran",
        ),
        (
            lambda pair: pair["candidate"].__setitem__(
                "lenses_not_run", ["reviewing-test-quality"]
            ),
            "was NOT RUN",
        ),
        (
            lambda pair: pair["candidate"].__setitem__(
                "lenses_failed", ["reviewing-test-quality"]
            ),
            "lens reviewing-test-quality failed",
        ),
    ],
)
def test_a_new_head_fails_each_operational_guard(
    tmp_path, monkeypatch, change, message
):
    monkeypatch.setattr(
        "atlas_reviewer.eval_harness.load_reference_set",
        lambda: {
            ("o/r", 1, 1, "abc123"): ReferenceRow(EvalReview("APPROVE", ()), False)
        },
    )
    calibration = _passing_pair("abc123")
    calibration["input"]["repo"] = "o/r"
    calibration["metadata"]["over_context_window"] = True
    (tmp_path / "pair.json").write_text(json.dumps(calibration), encoding="utf-8")
    head = _passing_pair("c" * 40)
    head["input"]["repo"] = "other/app"
    head["input"]["pr"] = 9
    head["candidate"]["lenses_run"] = ["reviewing-test-quality"]
    head["metadata"]["run"] = "lens-fan-out"
    change(head)
    (tmp_path / "head.json").write_text(json.dumps(head), encoding="utf-8")
    report = load_directory(tmp_path, head="c" * 40)
    assert report["gate_pass"] is False
    assert any(message in item for item in report["gate_failures"])


def test_the_reference_set_fails_closed_and_a_pair_cannot_replace_it(
    tmp_path, monkeypatch
):
    assert load_reference_set()
    trusted = load_reference_set()
    identity, row = next(item for item in trusted.items() if item[1].review.findings)
    repo, pr, round_number, commit = identity
    pair = _passing_pair(commit)
    pair["input"] = {
        "repo": repo,
        "pr": pr,
        "round": round_number,
        "reviewed_commit": commit,
        "head_sha": commit,
    }
    pair["reference"] = {"verdict": "APPROVE", "findings": []}
    pair["metadata"] = {"over_context_window": True}
    (tmp_path / "pair.json").write_text(json.dumps(pair), encoding="utf-8")
    report = load_directory(tmp_path, head=commit)
    assert report["gate_pass"] is False
    assert any("recall" in item for item in report["gate_failures"])
    assert row.review.findings
    root = tmp_path / "refs"
    monkeypatch.setattr("atlas_reviewer.eval_harness._REFERENCES", root)
    with pytest.raises(EvalFormatError, match="missing"):
        load_reference_set()
    root.mkdir()
    with pytest.raises(EvalFormatError, match="empty"):
        load_reference_set()
    (root / "pr-1.json").write_text("[]", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="not an object"):
        load_reference_set()
    (root / "pr-1.json").write_text("{", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="not JSON"):
        load_reference_set()
    (root / "pr-1.json").write_text(
        json.dumps({"input": {}, "output": {"verdict": "APPROVE", "findings": []}}),
        encoding="utf-8",
    )
    with pytest.raises(EvalFormatError, match="well-formed"):
        load_reference_set()


def test_a_same_line_heading_keeps_its_summary_and_a_plain_lens_list_counts():
    parsed = protocol_review(
        "## Round 1 — notes\n<!-- atlas-review round:1 -->\n",
        [
            {
                "path": "atlas_reviewer/lens_loop.py",
                "line": 12,
                "body": (
                    "**Minor · reviewing-test-quality.** D42 states the rule.\n\n"
                    "---\n_Generated by [Claude Code](https://claude.ai/code)_\n"
                ),
            }
        ],
    )
    assert parsed is not None
    finding = parsed[1].findings[0]
    assert finding.summary.startswith("D42 states")
    assert "Generated by" not in finding.summary
    assert finding.lenses == ("reviewing-test-quality",)
    body = (
        "## Round 1 — notes\n**Coverage**\n"
        "- Lenses (vendored): tracing-correctness-and-invariants, "
        "hunting-silent-failures.\n"
        "- Tool grounding: `markdownlint-cli2` clean.\n"
    )
    assert run_mode(body) == "lens-fan-out"
    assert coverage_lenses(body) == (
        "tracing-correctness-and-invariants",
        "hunting-silent-failures",
    )


def test_zero_findings_are_a_gap_unless_the_round_says_there_are_none():
    from atlas_reviewer.eval_harness import reference_row

    quiet = reference_row(
        {"number": 1, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {"state": "APPROVED", "commit_id": "abc", "body": "## Round 1 — APPROVE\n"},
        [],
    )
    assert quiet is not None and quiet["metadata"]["parse_gap"] is True
    stated = reference_row(
        {"number": 1, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {
            "state": "COMMENTED",
            "commit_id": "abc",
            "body": "## Round 2 — APPROVE\n\nNo new findings at or above the floor.\n",
        },
        [],
    )
    assert stated is not None and stated["metadata"]["parse_gap"] is False
    nothing = reference_row(
        {"number": 1, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {
            "state": "COMMENTED",
            "commit_id": "abc",
            "body": "## Round 2 — APPROVE\n\nNothing new at or above this round's floor.\n",
        },
        [],
    )
    assert nothing is not None and nothing["metadata"]["parse_gap"] is False
    earlier = reference_row(
        {"number": 1, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {
            "state": "COMMENTED",
            "commit_id": "abc",
            "body": "## Round 1 — 3 findings\n\nLast round had no findings.\n",
        },
        [],
    )
    assert earlier is not None and earlier["metadata"]["parse_gap"] is True
    titled = reference_row(
        {"number": 1, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {
            "state": "APPROVED",
            "commit_id": "abc",
            "body": "## Round 1 — no new findings at or above this round's floor\n",
        },
        [],
    )
    assert titled is not None and titled["metadata"]["parse_gap"] is False
    assert findings_expected("APPROVE — no findings", "unrelated body") is False
    assert (
        findings_expected("3 findings", "Last round had no findings at or above.")
        is True
    )
    assert (
        findings_expected(
            "3 findings",
            "## Round 2 — 3 findings\n\n"
            "Nothing new at or above this round's floor. "
            "Last round had no findings at or above.",
        )
        is False
    )
    assert (
        findings_expected(
            "3 findings",
            "Last round had no findings at or above. "
            "Nothing new at or above this round's floor.",
        )
        is True
    )
    for probe in (
        "Round 4 had no findings at or above.",
        "The round-3 review found nothing new at or above.",
        "Earlier rounds had no findings at or above.",
        "Saying no findings at or above would be wrong; the parser missed them.",
    ):
        assert findings_expected("3 findings", probe) is True, probe
    for sentence in (
        "No findings at or above this round's floor (Nit).",
        "**No new findings at or above this round's floor.**",
    ):
        rebuilt = reference_row(
            {
                "number": 1,
                "head": {"sha": "abc"},
                "base": {"repo": {"full_name": "o/r"}},
            },
            {
                "state": "COMMENTED",
                "commit_id": "abc",
                "body": f"## Round 1 — APPROVE\n\n{sentence}\n",
            },
            [],
        )
        assert rebuilt is not None and rebuilt["metadata"]["parse_gap"] is False, (
            sentence
        )
    buried = reference_row(
        {"number": 1, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {
            "state": "COMMENTED",
            "commit_id": "abc",
            "body": (
                "## Round 1 — APPROVE\n\n"
                "`6cdc050` adds the path. Nothing new at or above "
                "this round's floor (Major).\n"
            ),
        },
        [],
    )
    assert buried is not None and buried["metadata"]["parse_gap"] is True
    colon = protocol_review(
        "## Round 1 — notes\n<!-- atlas-review round:1 -->\n",
        [
            {
                "path": "docs/open-questions.md",
                "line": 4,
                "body": (
                    "**Nit · reviewing-decision-lifecycle: D43 names no revisit trigger.**\n"
                    "\nBefore this PR.\n"
                ),
            }
        ],
    )
    assert colon is not None
    assert colon[1].findings[0].lenses == ("reviewing-decision-lifecycle",)
    assert colon[1].findings[0].summary.startswith("D43")


def test_coverage_none_unreviewed_files_and_a_reused_finding_fail():
    finding = EvalFinding("major", "a.py", "bug", 10, 12, ())
    reference = EvalReview("REQUEST_CHANGES", (finding, finding))
    one = CandidateReview(
        "REQUEST_CHANGES",
        (EvalFinding("nit", "a.py", "nearby", 11, 11),),
        True,
        0,
        ("a.py",),
        (),
    )
    scored = score(reference, one)
    assert (scored.matched, scored.missed) == (1, 1)
    unread = CandidateReview("REQUEST_CHANGES", (finding,), True, 2, ("a.py",), ())
    assert any(
        "unreviewed_files" in item
        for item in gate_failures(
            reference, unread, score(EvalReview("REQUEST_CHANGES", (finding,)), unread)
        )
    )
    unknown = CandidateReview("REQUEST_CHANGES", (finding,), None, 0, ("a.py",), ())
    single = EvalReview("REQUEST_CHANGES", (finding,))
    assert any(
        "coverage_complete" in item
        for item in gate_failures(single, unknown, score(single, unknown))
    )


def test_a_reference_without_a_candidate_reports_a_parse_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "atlas_reviewer.eval_harness.load_reference_set",
        lambda: {("o/r", 1, 1, "abc"): ReferenceRow(EvalReview("COMMENT", ()), False)},
    )
    (tmp_path / "gap.json").write_text(
        json.dumps(
            {
                "input": {
                    "repo": "o/r",
                    "pr": 1,
                    "round": 1,
                    "reviewed_commit": "abc",
                    "head_sha": "abc",
                },
                "output": {"verdict": "COMMENT", "findings": []},
                "metadata": {"parse_gap": True},
            }
        ),
        encoding="utf-8",
    )
    report = load_directory(tmp_path, head="abc")
    assert any(
        "heading announces findings that were not parsed" in item
        for item in report["gate_failures"]
    )
    outside = _passing_pair("c" * 40)
    outside["input"]["repo"] = "other/app"
    outside["input"]["pr"] = 9
    outside["candidate"]["lenses_run"] = ["reviewing-test-quality"]
    outside["metadata"]["run"] = "lens-fan-out"
    outside["metadata"]["parse_gap"] = True
    (tmp_path / "head.json").write_text(json.dumps(outside), encoding="utf-8")
    scored = load_directory(tmp_path, head="c" * 40)
    assert any(
        "head.json: heading announces findings that were not parsed" in item
        for item in scored["gate_failures"]
    )
    (tmp_path / "bad.json").write_bytes(b"\xff")
    with pytest.raises(EvalFormatError, match="cannot be read"):
        load_directory(tmp_path)


def test_reference_row_records_the_commit_the_state_and_a_parse_gap():
    from atlas_reviewer.eval_harness import reference_row

    row = reference_row(
        {"number": 608, "head": {"sha": "abc"}, "base": {"repo": {"full_name": "o/r"}}},
        {
            "state": "COMMENTED",
            "commit_id": "def",
            "html_url": "https://example.test/r",
            "body": (
                "## Round 1 — Minor findings, not blocking merge\n"
                "<!-- atlas-review round:1 -->\n"
            ),
        },
        [],
    )
    assert row is not None
    assert row["input"]["reviewed_commit"] == "def"
    assert row["metadata"]["review_state"] == "COMMENTED"
    assert row["metadata"]["parse_gap"] is True
    assert row["output"]["verdict"] == "COMMENT"


def _passing_pair(head: str) -> dict:
    return {
        "input": {"head_sha": head, "reviewed_commit": head, "pr": 1, "round": 1},
        "reference": {"verdict": "APPROVE", "findings": []},
        "candidate": {
            "verdict": "APPROVE",
            "findings": [],
            "coverage_complete": True,
            "unreviewed_files": 0,
            "changed_files": [],
            "lenses_run": [],
        },
        "metadata": {"run": "lens-fan-out", "over_context_window": False},
    }


def test_an_approve_heading_is_approve_and_a_non_round_is_skipped():
    parsed = protocol_review(APPROVE, [])
    assert parsed is not None
    assert parsed[0] == 2
    assert parsed[1].verdict == "APPROVE"
    assert parsed[1].findings == ()
    assert protocol_review("looks fine", []) is None


def test_the_hand_built_fixture_scores_the_overlap_the_miss_and_the_false_positive():
    report = load_directory(FIXTURE)
    assert report["examples"] == 1
    assert report["scored"] == 1
    (row,) = report["results"]
    assert row["score"]["matched"] == 2
    assert row["score"]["missed"] == 1
    assert row["score"]["extras"] == 1
    assert row["score"]["verdict_agrees"] is False
    assert report["gate_pass"] is False
    assert any("recall" in item for item in row["gate_failures"])
    assert not any("extra" in item for item in row["gate_failures"])
    assert not any("verdict" in item for item in row["gate_failures"])
    assert any("coverage_complete" in item for item in row["gate_failures"])
    assert any(
        "reviewing-naming-and-readability" in item for item in row["gate_failures"]
    )


def test_a_clean_pair_passes_the_gate_and_a_missed_major_does_not():
    finding = EvalFinding("major", "a.py", "bug", 4, 4, ("sweeping-for-security",))
    reference = EvalReview("REQUEST_CHANGES", (finding,))
    candidate = CandidateReview(
        "REQUEST_CHANGES",
        (finding,),
        True,
        0,
        ("a.py",),
        ("sweeping-for-security",),
        (),
    )
    assert gate_failures(reference, candidate, score(reference, candidate)) == ()
    missed = CandidateReview(
        "APPROVE",
        (),
        True,
        0,
        ("a.py",),
        ("sweeping-for-security",),
        (),
    )
    failures = gate_failures(reference, missed, score(reference, missed))
    assert any("recall" in item and "unmatched" in item for item in failures)


def test_matching_does_not_depend_on_candidate_order():
    reference = EvalReview(
        "COMMENT",
        (
            EvalFinding("major", "a.py", "", 1, 1),
            EvalFinding("major", "a.py", "", 10, 10),
        ),
    )
    near = EvalFinding("nit", "a.py", "", 5, 5)
    exact = EvalFinding("nit", "a.py", "", 1, 1)
    for findings in ((near, exact), (exact, near)):
        candidate = CandidateReview("COMMENT", findings, True, 0, ("a.py",), ())
        assert score(reference, candidate).recall == 1.0


def test_the_tool_pre_pass_is_not_part_of_the_lens_list():
    body = (
        "## Round 1 — notes\n**Coverage:**\n"
        "`reviewing-test-quality` ran.\n"
        "- **Tool pre-pass:** the repo's `markdownlint-cli2` passes on head "
        "(0 errors). `hunting-silent-failures`\n"
    )
    assert coverage_lenses(body) == ("reviewing-test-quality",)


def test_a_line_matches_loosely_and_ignores_severity():
    left = EvalFinding("major", "a.py", "", 1, 3)
    assert left.same_issue(EvalFinding("nit", "a.py", "", 8, 8))
    assert not left.same_issue(EvalFinding("major", "a.py", "", 9, 9))
    assert not left.same_issue(EvalFinding("major", "a.py", "", None, None))
    assert EvalFinding("nit", "a.py", "", None, None).same_issue(
        EvalFinding("major", "a.py", "", 4, 4)
    )
    assert not left.same_issue(EvalFinding("major", "b.py", "", 1, 3))
    assert not left.same_issue(EvalFinding("major", "a.py", "", 20, 20))


def test_the_cli_prints_the_score_and_gate_exits_1(tmp_path):
    code, out, err = _cli("eval", "--fixtures", str(FIXTURE))
    assert code == 0
    assert err == ""
    assert json.loads(out)["totals"]["extras"] == 1
    gated, _, gated_err = _cli("eval", "--fixtures", str(FIXTURE), "--gate")
    assert gated == 1
    assert gated_err == ""
    empty = tmp_path / "empty"
    empty.mkdir()
    usage, _, usage_err = _cli("eval", "--fixtures", str(empty))
    assert usage == cli.EXIT_USAGE
    assert "no JSON fixtures" in usage_err


def test_a_reference_only_directory_fails_the_gate_closed(tmp_path):
    row = example_json(
        repo="example-org/example-app",
        pr=7,
        head_sha="abc",
        round_number=1,
        review=EvalReview("COMMENT", ()),
        review_url="https://example.test/review/1",
    )
    (tmp_path / "round.json").write_text(json.dumps(row), encoding="utf-8")
    report = load_directory(tmp_path)
    assert (report["examples"], report["scored"], report["gate_pass"]) == (1, 0, False)


def test_a_marker_without_a_heading_and_a_request_changes_heading_parse():
    marker_only = "<!-- atlas-review round:3 -->\nno heading"
    parsed = protocol_review(marker_only, [])
    assert parsed is not None
    assert parsed[0] == 3
    assert parsed[1].verdict == "COMMENT"
    requested = protocol_review(
        "## Round 4 — REQUEST_CHANGES\n<!-- atlas-review round:4 -->\n", []
    )
    assert requested is not None
    assert requested[1].verdict == "REQUEST_CHANGES"
    assert (
        protocol_review("<!-- atlas-review round:4 -->", [{"body": "nope"}])[1].findings
        == ()
    )


def test_a_comment_without_a_path_or_a_line_is_dropped_or_lineless():
    dropped = protocol_review(
        "## Round 1 — notes\n<!-- atlas-review round:1 -->\n",
        [{"body": "**Nit · reviewing-naming-and-readability**\n\nnit", "path": ""}],
    )
    assert dropped is not None
    assert dropped[1].findings == ()
    lineless = protocol_review(
        "## Round 1 — notes\n<!-- atlas-review round:1 -->\n",
        [{"body": "**Nit · reviewing-naming-and-readability**\n\nnit", "path": "a.py"}],
    )
    assert lineless is not None
    assert lineless[1].findings[0].line_start is None


def test_example_json_keeps_a_line_range():
    review = EvalReview(
        "COMMENT",
        (
            EvalFinding(
                "nit", "a.py", "blank", 1, 3, ("reviewing-naming-and-readability",)
            ),
        ),
    )
    row = example_json(
        repo="example-org/example-app",
        pr=1,
        head_sha="abc",
        round_number=1,
        review=review,
    )
    finding = row["output"]["findings"][0]
    assert (finding["line"], finding["end_line"]) == (1, 3)
    one_line = EvalReview("COMMENT", (EvalFinding("nit", "a.py", "blank", 4, 4),))
    dumped = example_json(
        repo="example-org/example-app",
        pr=1,
        head_sha="abc",
        round_number=1,
        review=one_line,
    )
    assert "end_line" not in dumped["output"]["findings"][0]


def test_the_gate_names_a_missing_coverage_record():
    finding = EvalFinding("nit", "a.py", "", 1, 1)
    reference = EvalReview("COMMENT", (finding,))
    bare = CandidateReview("COMMENT", (finding,))
    failures = gate_failures(reference, bare, score(reference, bare))
    assert any("lenses_run" in item for item in failures)
    partial = CandidateReview("COMMENT", (finding,), True, 0, ("a.py",), ())
    assert gate_failures(reference, partial, score(reference, partial)) == ()


def test_a_lens_state_list_records_not_run_and_failed(tmp_path):
    payload = {
        "input": {"repo": "o/r", "pr": 1, "head_sha": "abc", "round": 1},
        "reference": {"verdict": "COMMENT", "findings": []},
        "candidate": {
            "verdict": "COMMENT",
            "findings": [],
            "coverage_complete": True,
            "unreviewed_files": 0,
            "lenses": [
                {"name": "sweeping-for-security", "state": "clean"},
                {"name": "reviewing-test-quality", "state": "not_run"},
                {"name": "hunting-silent-failures", "state": "failed"},
            ],
        },
    }
    path = tmp_path / "pair.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    row = load_directory(tmp_path)["results"][0]
    assert any("NOT RUN" in item for item in row["gate_failures"])
    assert any("failed" in item for item in row["gate_failures"])
    payload["candidate"]["lenses"] = [
        {"name": "reviewing-naming-and-readability", "state": "partial"}
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    partial = load_directory(tmp_path)["results"][0]
    assert not any("NOT RUN" in item for item in partial["gate_failures"])
    payload["candidate"]["lenses"] = [{"state": "clean"}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvalFormatError, match="lenses need a name"):
        load_directory(tmp_path)


def test_a_lens_with_a_missing_or_unknown_state_does_not_count_as_run():
    from atlas_reviewer.eval_harness import _parse_candidate

    for lenses in (
        [{"name": "reviewing-test-quality"}],
        [{"name": "reviewing-test-quality", "state": ""}],
        [{"name": "reviewing-test-quality", "state": "pending"}],
    ):
        parsed = _parse_candidate(
            {"verdict": "COMMENT", "findings": [], "lenses": lenses},
            "pair",
        )
        assert parsed.lenses_run == ()
        assert parsed.lenses_not_run == ("reviewing-test-quality",)


def test_a_fixture_that_is_not_an_object_is_an_error(tmp_path):
    (tmp_path / "bad.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="not an object"):
        load_directory(tmp_path)
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="not JSON"):
        load_directory(tmp_path)


@pytest.mark.parametrize(
    ("candidate", "match"),
    [
        ({"verdict": "SHIP", "findings": []}, "verdict"),
        ({"verdict": "APPROVE", "findings": "nope"}, "findings must be a list"),
        ({"verdict": "APPROVE", "findings": ["x"]}, "not an object"),
        (
            {"verdict": "APPROVE", "findings": [{"severity": "huge", "path": "a.py"}]},
            "severity",
        ),
        (
            {"verdict": "APPROVE", "findings": [{"severity": "nit", "path": ""}]},
            "needs a path",
        ),
        (
            {
                "verdict": "APPROVE",
                "findings": [{"severity": "nit", "path": "a.py", "lenses": [1]}],
            },
            "lenses",
        ),
        (
            {
                "verdict": "APPROVE",
                "findings": [{"severity": "nit", "path": "a.py", "line": "1"}],
            },
            "line",
        ),
        (
            {"verdict": "APPROVE", "findings": [], "coverage_complete": "yes"},
            "coverage_complete",
        ),
        (
            {"verdict": "APPROVE", "findings": [], "changed_files": "a.py"},
            "changed_files",
        ),
    ],
)
def test_a_candidate_with_a_bad_field_is_refused(tmp_path, candidate, match):
    (tmp_path / "pair.json").write_text(
        json.dumps(
            {
                "reference": {"verdict": "APPROVE", "findings": []},
                "candidate": candidate,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalFormatError, match=match):
        load_directory(tmp_path)


def test_an_omitted_coverage_list_parses_and_fails_the_gate(tmp_path):
    (tmp_path / "pair.json").write_text(
        json.dumps(
            {
                "reference": {"verdict": "APPROVE", "findings": []},
                "candidate": {"verdict": "APPROVE", "findings": []},
            }
        ),
        encoding="utf-8",
    )
    report = load_directory(tmp_path)
    (row,) = report["results"]
    assert any("lenses_run" in item for item in row["gate_failures"])


def test_a_pair_without_a_reference_object_is_refused(tmp_path):
    (tmp_path / "pair.json").write_text(
        json.dumps({"candidate": {"verdict": "APPROVE", "findings": []}}),
        encoding="utf-8",
    )
    with pytest.raises(EvalFormatError, match="no reference"):
        load_directory(tmp_path)


def _cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), env={}, out=out, err=err)
    return code, out.getvalue(), err.getvalue()
