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
    example_json,
    gate_failures,
    load_directory,
    protocol_review,
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
    assert row["score"] == {
        "matched": 2,
        "missed_major_or_above": 0,
        "false_positives": 1,
        "false_positives_major_or_above": 1,
        "verdict_agrees": False,
    }
    assert report["gate_pass"] is False
    assert any("unmatched Major+" in item for item in report["gate_failures"])
    assert any("verdict" in item for item in report["gate_failures"])
    assert any("coverage_complete" in item for item in report["gate_failures"])
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
    assert any(item.startswith("missed 1") for item in failures)


def test_a_reference_path_outside_the_diff_must_be_read():
    finding = EvalFinding("nit", "pkg/util.py", "name", 3, 3, ())
    reference = EvalReview("COMMENT", (finding,))
    candidate = CandidateReview(
        "COMMENT",
        (finding,),
        True,
        0,
        ("a.py",),
        (),
        (),
    )
    failures = gate_failures(reference, candidate, score(reference, candidate))
    assert any("pkg/util.py" in item for item in failures)


def test_a_line_range_does_not_match_a_different_path_or_a_lineless_finding():
    left = EvalFinding("major", "a.py", "", 1, 3)
    assert left.overlaps(EvalFinding("major", "a.py", "", 3, 5))
    assert not left.overlaps(EvalFinding("major", "b.py", "", 1, 3))
    assert not left.overlaps(EvalFinding("major", "a.py", "", None, None))
    assert not left.overlaps(EvalFinding("minor", "a.py", "", 1, 1))


def test_the_cli_prints_the_score_and_gate_exits_1(tmp_path):
    code, out, err = _cli("eval", "--fixtures", str(FIXTURE))
    assert code == 0
    assert err == ""
    assert json.loads(out)["totals"]["false_positives_major_or_above"] == 1
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
    named = gate_failures(reference, partial, score(reference, partial))
    assert any("outside_diff_reads" in item for item in named)


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
    assert any("lenses_run" in item for item in report["gate_failures"])


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
