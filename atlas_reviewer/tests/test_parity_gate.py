# SPDX-License-Identifier: MIT
"""The parity gate: 2 of 3, and an automatic fail that a find does not waive."""

import pytest

from atlas_reviewer.eval_harness import EvalFormatError
from atlas_reviewer.parity_key import (
    BODY,
    FOUND_IN_AT_LEAST,
    KEY_DIR,
    PARTIAL_COUNTS_AS_FOUND,
    RUNS_REQUIRED,
    CitedFinding,
    KeyFinding,
    ParityRun,
    Span,
    load_key,
    score_parity,
)

_SHA = "674071a91513b4774c82350fb757d9c085f10baf"


def _hit(finding: KeyFinding) -> CitedFinding:
    span = finding.spans[0]
    if span.path == BODY:
        return CitedFinding(BODY, finding.citations[0], "minor", True)
    return CitedFinding(
        span.path, "the line", "minor", True, span.line_start, span.line_start
    )


def _partial(finding: KeyFinding) -> CitedFinding:
    for outer in finding.encloses:
        if outer.line_start is None or outer.line_end is None:
            continue
        for line in range(outer.line_start, outer.line_end + 1):
            on_span = any(
                span.path == outer.path
                and span.line_start is not None
                and span.line_end is not None
                and span.line_start <= line <= span.line_end
                for span in finding.spans
            )
            if not on_span:
                return CitedFinding(outer.path, "near", "minor", True, line, line)
    raise AssertionError(finding.id)


def _lenses(findings: tuple[KeyFinding, ...] | list[KeyFinding]) -> tuple[str, ...]:
    names: list[str] = []
    for finding in findings:
        for name in finding.lenses:
            if name not in names:
                names.append(name)
    return tuple(names)


def _run(
    findings: list[KeyFinding],
    repetition: int,
    *,
    candidates: tuple[CitedFinding, ...] | None = None,
    name: str | None = None,
    pr: int | None = None,
    coverage_complete: bool = True,
    lenses_run: tuple[str, ...] | None = None,
    lenses_not_run: tuple[str, ...] = (),
    lenses_failed: tuple[str, ...] = (),
    limit_stops: tuple[str, ...] = (),
    model: str = "recorded-fixture",
    head_sha: str | None = None,
    false_positive_majors: int | None = None,
    lenses_clean: int | None = None,
    lenses_planned: int | None = None,
    cost_usd: float | None = None,
    wall_seconds: float | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    previous_turn_misses: int | None = None,
) -> ParityRun:
    number = findings[0].pr if pr is None else pr
    return ParityRun(
        f"{number}-{repetition}.json" if name is None else name,
        number,
        model,
        repetition,
        findings[0].reviewed_commit if head_sha is None else head_sha,
        tuple(_hit(item) for item in findings) if candidates is None else candidates,
        coverage_complete,
        _lenses(findings) if lenses_run is None else lenses_run,
        lenses_not_run,
        lenses_failed,
        limit_stops,
        false_positive_majors,
        lenses_clean,
        lenses_planned,
        cost_usd,
        wall_seconds,
        cache_read_tokens,
        cache_write_tokens,
        previous_turn_misses,
    )


def _of(pr: int) -> list[KeyFinding]:
    return [item for item in load_key(KEY_DIR) if item.pr == pr]


def _report(
    findings: list[KeyFinding],
    runs: list[ParityRun],
    *,
    runs_required: int = RUNS_REQUIRED,
    found_in_at_least: int = FOUND_IN_AT_LEAST,
    partial_counts_as_found: bool = PARTIAL_COUNTS_AS_FOUND,
) -> dict[str, object]:
    return score_parity(
        findings,
        runs,
        runs_required=runs_required,
        found_in_at_least=found_in_at_least,
        partial_counts_as_found=partial_counts_as_found,
    )


def test_a_finding_found_in_two_of_three_passes():
    findings = _of(661)
    runs = [_run(findings, 1), _run(findings, 2), _run(findings, 3, candidates=())]
    report = _report(findings, runs)
    assert report["gate_pass"] is True
    row = next(item for item in report["findings"] if item["id"] == "661-m3")
    assert row == {
        "id": "661-m3",
        "pr": 661,
        "found": 2,
        "partial": 0,
        "lost": 1,
        "of": 3,
        "passed": True,
    }
    assert report["defaults"] == {
        "runs_required": RUNS_REQUIRED,
        "found_in_at_least": FOUND_IN_AT_LEAST,
        "partial_counts_as_found": PARTIAL_COUNTS_AS_FOUND,
    }


def test_a_finding_found_in_one_of_three_fails():
    findings = _of(661)
    runs = [
        _run(findings, 1),
        _run(findings, 2, candidates=()),
        _run(findings, 3, candidates=()),
    ]
    report = _report(findings, runs)
    assert report["gate_pass"] is False
    assert any("661-m3 found in 1 of 3" in item for item in report["failures"])


def test_partial_does_not_count_as_found_unless_the_caller_says_so():
    findings = _of(661)
    hidden = next(item for item in findings if item.id == "661-m3")
    mixed = tuple(
        _partial(item) if item.id == "661-m3" else _hit(item) for item in findings
    )
    runs = [
        _run(findings, 1),
        _run(findings, 2, candidates=mixed),
        _run(
            findings,
            3,
            candidates=tuple(_hit(item) for item in findings if item.id != "661-m3"),
        ),
    ]
    refused = _report(findings, runs)
    row = next(item for item in refused["findings"] if item["id"] == hidden.id)
    assert row["found"] == 1 and row["partial"] == 1 and row["lost"] == 1
    assert row["passed"] is False
    allowed = _report(findings, runs, partial_counts_as_found=True)
    allowed_row = next(item for item in allowed["findings"] if item["id"] == hidden.id)
    assert allowed_row["passed"] is True
    assert allowed["defaults"]["partial_counts_as_found"] is True
    assert (
        any("661-m3 credited in 2 of 3" in item for item in allowed["failures"])
        is False
    )


def test_a_partial_credit_that_still_misses_says_credited():
    findings = _of(661)
    mixed = tuple(
        _partial(item) if item.id == "661-m3" else _hit(item) for item in findings
    )
    runs = [
        _run(findings, 1, candidates=mixed),
        _run(findings, 2, candidates=()),
        _run(findings, 3, candidates=()),
    ]
    report = _report(findings, runs, partial_counts_as_found=True)
    assert any("661-m3 credited in 1 of 3" in item for item in report["failures"])


def test_two_runs_cannot_pass_the_three_run_sample():
    findings = _of(640)
    report = _report(findings, [_run(findings, 1), _run(findings, 2)])
    assert report["gate_pass"] is False
    assert any(
        "pull request 640 has 2 runs recorded" in item for item in report["failures"]
    )
    passed = {item["id"]: item["passed"] for item in report["findings"]}
    assert passed == {"640-m1": False, "640-m2": False, "640-m3": False}
    overridden = _report(
        findings, [_run(findings, 1), _run(findings, 2)], runs_required=2
    )
    assert overridden["gate_pass"] is True
    assert overridden["defaults"]["runs_required"] == 2


def test_every_recorded_finding_is_scored():
    findings = _of(640)
    report = _report(findings, [_run(findings, n) for n in (1, 2, 3)])
    assert report["gate_pass"] is True
    assert report["failures"] == []
    assert {item["id"]: item["passed"] for item in report["findings"]} == {
        "640-m1": True,
        "640-m2": True,
        "640-m3": True,
    }


def test_an_extra_finding_does_not_fail_the_gate():
    findings = _of(640)
    extra = CitedFinding("other.py", "an extra major", "major", True, 1, 1)
    runs = [
        _run(findings, n, candidates=tuple(_hit(item) for item in findings) + (extra,))
        for n in (1, 2, 3)
    ]
    report = _report(findings, runs)
    assert report["gate_pass"] is True
    assert report["runs"][0]["extras"] == 1
    assert report["runs"][0]["extra_majors"] == 1


def test_a_lens_not_run_fails_even_when_every_finding_was_found():
    findings = _of(661)
    runs = [
        _run(findings, 1, lenses_not_run=("reviewing-observability-and-operability",)),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    assert report["gate_pass"] is False
    assert all(item["passed"] is True for item in report["findings"])
    assert report["runs"][0]["automatic_fail"] == [
        "lens reviewing-observability-and-operability was NOT RUN"
    ]


def test_a_failed_lens_fails_the_run():
    findings = _of(640)
    runs = [
        _run(findings, 1, lenses_failed=("reviewing-test-quality",)),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    assert any(
        "lens reviewing-test-quality failed" in item for item in report["failures"]
    )
    assert report["gate_pass"] is False


def test_coverage_complete_false_fails_the_run():
    findings = _of(640)
    runs = [
        _run(findings, 1, coverage_complete=False),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    assert any("coverage_complete is not true" in item for item in report["failures"])
    assert report["findings"][0]["found"] == 3


def test_a_limit_stop_fails_the_run():
    findings = _of(640)
    runs = [
        _run(findings, 1, limit_stops=("dollar ceiling",)),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    assert any("limit stop: dollar ceiling" in item for item in report["failures"])
    assert report["gate_pass"] is False


def test_a_lens_named_by_the_key_and_not_selected_fails_the_run():
    findings = _of(640)
    runs = [
        _run(findings, 1, lenses_run=("reviewing-test-quality",)),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    named = [
        item for item in report["failures"] if "named by the key was not run" in item
    ]
    assert named == [
        "640-1.json: lens hunting-silent-failures named by the key was not run",
        "640-1.json: lens reviewing-decision-lifecycle named by the key was not run",
    ]


def test_a_shared_lens_is_named_once():
    one = KeyFinding(
        "a-m1",
        1,
        _SHA,
        "a plan row",
        "minor",
        "one",
        (Span("a.py", 10, 10),),
        (Span("a.py", 1, 20),),
        (),
        ("reviewing-test-quality",),
        ("read",),
    )
    two = KeyFinding(
        "a-m2",
        1,
        _SHA,
        "a plan row",
        "minor",
        "two",
        (Span("b.py", 12, 12),),
        (Span("b.py", 1, 20),),
        (),
        ("reviewing-test-quality",),
        ("read",),
    )
    report = _report(
        [one, two],
        [_run([one, two], 1, lenses_run=())],
        runs_required=1,
        found_in_at_least=1,
    )
    named = [item for item in report["failures"] if "named by the key" in item]
    assert named == [
        "1-1.json: lens reviewing-test-quality named by the key was not run"
    ]


def test_a_second_pull_request_is_scored():
    first = _of(640)[:1]
    second = _of(661)[:1]
    report = _report(
        first + second,
        [_run(first, 1), _run(second, 1)],
        runs_required=1,
        found_in_at_least=1,
    )
    assert report["gate_pass"] is True
    assert [item["id"] for item in report["findings"]] == ["640-m1", "661-m1"]


def test_a_run_for_an_unknown_pull_request_fails_the_gate():
    findings = _of(640)
    stranger = _run(findings, 1, pr=999, name="stray.json")
    report = _report(
        findings, [_run(findings, 1), _run(findings, 2), _run(findings, 3), stranger]
    )
    assert any(
        "stray.json is for pull request 999" in item for item in report["failures"]
    )
    assert report["gate_pass"] is False


def test_the_report_carries_the_comparison_fields_and_echoes_an_explicit_count():
    findings = _of(640)
    runs = [
        _run(
            findings,
            n,
            false_positive_majors=2 if n == 1 else None,
            lenses_clean=4,
            lenses_planned=4,
            cost_usd=1.25,
            wall_seconds=30.0,
            cache_read_tokens=10,
            cache_write_tokens=0,
            previous_turn_misses=0,
        )
        for n in (1, 2, 3)
    ]
    report = _report(findings, runs)
    assert report["gate_pass"] is True
    first = report["runs"][0]
    assert first["false_positive_majors"] == 2
    assert first["lenses_clean"] == 4
    assert first["cost_usd"] == 1.25
    assert first["cache_write_tokens"] == 0
    assert report["runs"][1]["false_positive_majors"] is None
    assert report["runs"][1]["wall_seconds"] == 30.0
    blank = _report(findings, [_run(findings, n) for n in (1, 2, 3)])
    assert blank["runs"][0]["cost_usd"] is None
    assert blank["runs"][0]["previous_turn_misses"] is None


def test_the_sample_message_counts_zero_and_one_run():
    findings = _of(640)[:1]
    report = _report(findings, [])
    assert any(
        "pull request 640 has 0 runs recorded" in item for item in report["failures"]
    )
    report = _report(findings, [_run(findings, 1, candidates=())], runs_required=3)
    assert any("has 1 run recorded" in item for item in report["failures"])
    assert any("640-m1 found in 0 of 1" in item for item in report["failures"])


def test_a_run_of_another_commit_fails_the_gate():
    findings = _of(640)
    other = "674071a91513b4774c82350fb757d9c085f10baf"
    reviewed = findings[0].reviewed_commit
    assert reviewed != other
    runs = [_run(findings, n, head_sha=other) for n in (1, 2, 3)]
    report = _report(findings, runs)
    assert report["gate_pass"] is False
    assert all(item["passed"] is True for item in report["findings"])
    assert report["runs"][0]["automatic_fail"] == [
        f"head_sha {other} is not the reviewed commit {reviewed}"
    ]


def test_a_run_file_named_twice_is_refused():
    findings = _of(640)
    one = _run(findings, 1)
    with pytest.raises(EvalFormatError, match="640-1.json is recorded more than once"):
        score_parity(findings, [one, one, one])


def test_one_model_repetition_recorded_twice_is_refused():
    findings = _of(640)
    original = _run(findings, 1)
    copy = _run(findings, 1, name="640-copy.json")
    with pytest.raises(EvalFormatError, match="repetition 1 more than once"):
        score_parity(findings, [original, copy, _run(findings, 2)])


def test_a_sample_that_mixes_models_is_refused():
    findings = _of(640)
    runs = [
        _run(findings, 1, model="opus"),
        _run(findings, 2, model="opus"),
        _run(findings, 3, model="haiku"),
    ]
    with pytest.raises(EvalFormatError, match="mixes models opus and haiku"):
        score_parity(findings, runs)


def test_a_key_lens_already_not_run_is_not_reported_again():
    findings = _of(640)
    missing = "hunting-silent-failures"
    ran = tuple(name for name in _lenses(findings) if name != missing)
    runs = [
        _run(findings, 1, lenses_run=ran, lenses_not_run=(missing,)),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    assert report["runs"][0]["automatic_fail"] == [f"lens {missing} was NOT RUN"]


def test_a_key_lens_that_failed_is_not_also_named_missing():
    findings = _of(640)
    missing = "hunting-silent-failures"
    ran = tuple(name for name in _lenses(findings) if name != missing)
    runs = [
        _run(findings, 1, lenses_run=ran, lenses_failed=(missing,)),
        _run(findings, 2),
        _run(findings, 3),
    ]
    report = _report(findings, runs)
    assert report["runs"][0]["automatic_fail"] == [f"lens {missing} failed"]


def test_every_unrun_lens_a_finding_names_is_reported():
    finding = KeyFinding(
        "a-m1",
        1,
        _SHA,
        "a plan row",
        "minor",
        "one",
        (Span("a.py", 10, 10),),
        (Span("a.py", 1, 20),),
        (),
        ("reviewing-test-quality", "hunting-silent-failures"),
        ("read",),
    )
    report = _report(
        [finding],
        [_run([finding], 1, lenses_run=())],
        runs_required=1,
        found_in_at_least=1,
    )
    named = [item for item in report["failures"] if "named by the key" in item]
    assert named == [
        "1-1.json: lens reviewing-test-quality named by the key was not run",
        "1-1.json: lens hunting-silent-failures named by the key was not run",
    ]


def test_a_nonsense_pass_rule_is_refused():
    with pytest.raises(EvalFormatError, match="found_in_at_least cannot exceed"):
        score_parity([], [], runs_required=1, found_in_at_least=2)
    with pytest.raises(EvalFormatError, match="positive integers"):
        score_parity([], [], runs_required=True, found_in_at_least=1)  # type: ignore[arg-type]
    with pytest.raises(EvalFormatError, match="positive integers"):
        score_parity([], [], runs_required=1, found_in_at_least=True)  # type: ignore[arg-type]
    with pytest.raises(EvalFormatError, match="positive integers"):
        score_parity([], [], runs_required=0, found_in_at_least=1)
    with pytest.raises(EvalFormatError, match="positive integers"):
        score_parity([], [], runs_required=1, found_in_at_least=0)
    with pytest.raises(EvalFormatError, match="positive integers"):
        score_parity([], [], runs_required="3", found_in_at_least=1)  # type: ignore[arg-type]
    with pytest.raises(EvalFormatError, match="partial_counts_as_found"):
        score_parity([], [], partial_counts_as_found="false")  # type: ignore[arg-type]
    with pytest.raises(EvalFormatError, match="partial_counts_as_found"):
        score_parity([], [], partial_counts_as_found=1)  # type: ignore[arg-type]
