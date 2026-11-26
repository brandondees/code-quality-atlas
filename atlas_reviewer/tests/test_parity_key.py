# SPDX-License-Identifier: MIT
"""The parity key: the seven graded protocol Minors, #801's four secret-echo
Majors, and the loader that refuses a bad record."""

import json
from itertools import count
from pathlib import Path

import pytest

from atlas_reviewer.eval_harness import EvalFormatError
from atlas_reviewer.parity_key import (
    BODY,
    FOUND,
    KEY_DIR,
    LOST,
    PARTIAL,
    CitedFinding,
    KeyFinding,
    Span,
    grade_findings,
    load_key,
)

_COMMIT = "28854775e5965eb554b368cc3a543969a635b681"
_QUEUE = "0fe45e5ea79f3abd8e07488a01b623186df96692"
_ECHO = "186e09f2944e561815462eb5d9795dba4229c488"
_FUNDING = "atlas_reviewer/funding.py"
_KEY_IDS = (
    "640-m1",
    "640-m2",
    "640-m3",
    "661-m1",
    "661-m2",
    "661-m3",
    "661-m4",
    "801-m1",
    "801-m2",
    "801-m3",
    "801-m4",
)
_CI = "`gate` on `61273b4f` (run 43429340358)"
_STACK = "pre-rebase head `61273b4f`"


def _span(path: str = "a.py", line: int = 4, end: int = 4) -> dict[str, object]:
    return {"path": path, "line": line, "end_line": end}


def _finding(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "1-m1",
        "severity": "minor",
        "summary": "a defect",
        "source": "the span is the defect line, and the function contains it",
        "lenses": ["tracing-correctness-and-invariants"],
        "needs": ["read"],
        "spans": [_span()],
        "encloses": [_span(line=1, end=10)],
        "citations": [],
    }
    body.update(over)
    return body


def _body_finding(**over: object) -> dict[str, object]:
    body = _finding(spans=[{"path": BODY}], encloses=[], citations=[_CI])
    body.update(over)
    return body


def _document(
    findings: list[dict[str, object]] | object | None = None,
) -> dict[str, object]:
    return {
        "pr": 1,
        "reviewed_commit": _COMMIT,
        "source": "a plan row",
        "findings": [_finding()] if findings is None else findings,
    }


def _write(directory: Path, name: str, payload: object) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_the_checked_in_key_grades_every_recorded_finding():
    findings = load_key(KEY_DIR)
    by_id = {item.id: item for item in findings}
    assert list(by_id) == list(_KEY_IDS)
    missing = [item for item in _KEY_IDS if item not in by_id]
    assert missing == []
    note = (KEY_DIR / "640.json").read_text(encoding="utf-8")
    assert "not a record" not in note
    note661 = (KEY_DIR / "661.json").read_text(encoding="utf-8")
    assert "not a record" not in note661
    cancel = by_id["640-m1"]
    assert cancel.reviewed_commit == _QUEUE
    assert cancel.spans[0] == Span("atlas_reviewer/service_queue.py", 329, 329)
    assert cancel.lenses == ("reviewing-test-quality",)
    assert cancel.needs == ("mutate",)
    hook = by_id["640-m2"]
    assert hook.spans[0] == Span("atlas_reviewer/service_post.py", 229, 231)
    assert hook.encloses[0] == Span("atlas_reviewer/service_post.py", 217, 236)
    assert hook.lenses == ("hunting-silent-failures",)
    assert "check is not None" in hook.source
    decision = by_id["640-m3"]
    assert [span.path for span in decision.spans] == [
        "docs/open-questions.md",
        "atlas_reviewer/README.md",
    ]
    assert decision.spans[0] == Span("docs/open-questions.md", 62, 62)
    assert decision.spans[1] == Span("atlas_reviewer/README.md", 13, 15)
    assert "amends D48" in decision.source
    assert decision.lenses == ("reviewing-decision-lifecycle",)
    body = by_id["661-m1"]
    assert body.reviewed_commit == _COMMIT
    assert body.spans[0] == Span(BODY)
    assert body.citations == (_CI, _STACK)
    assert body.needs == ("ci",)
    assert body.lenses == ("reviewing-pr-and-process-hygiene",)
    unreadable = by_id["661-m2"]
    assert unreadable.spans == (
        Span("atlas_reviewer/coordinator.py", 734, 735),
        Span("atlas_reviewer/rounds.py", 202, 203),
    )
    assert unreadable.encloses == (
        Span("atlas_reviewer/coordinator.py", 712, 752),
        Span("atlas_reviewer/rounds.py", 162, 220),
    )
    assert "6ff2ed04" in unreadable.source
    assert by_id["661-m3"].spans[0] == Span("atlas_reviewer/rounds.py", 180, 182)
    assert by_id["661-m3"].needs == ("run_tests", "mutate")
    assert by_id["661-m4"].spans[0] == Span("atlas_reviewer/rounds.py", 207, 215)
    assert all(item.severity == "minor" for item in findings if item.pr != 801)
    assert all(item.citations == () for item in findings if item.id != "661-m1")
    for echo_id, start, end in (
        ("801-m1", 129, 131),
        ("801-m2", 207, 207),
        ("801-m3", 219, 222),
        ("801-m4", 267, 267),
    ):
        echo = by_id[echo_id]
        assert echo.reviewed_commit == _ECHO
        assert echo.spans[0] == Span(_FUNDING, start, end)
        assert echo.severity == "major"
        assert echo.lenses == ("sweeping-for-security",)
        assert echo.needs == ("read",)
    assert "{source.name!r}" in by_id["801-m1"].source
    assert by_id["801-m1"].encloses[0] == Span(_FUNDING, 93, 146)
    assert "{key!r}" in by_id["801-m2"].source
    assert by_id["801-m2"].encloses[0] == Span(_FUNDING, 197, 209)
    assert "sorted(extra)" in by_id["801-m3"].source
    assert by_id["801-m3"].encloses[0] == Span(_FUNDING, 212, 239)
    assert "{slug!r}" in by_id["801-m4"].source
    assert by_id["801-m4"].encloses[0] == Span(_FUNDING, 259, 269)


def test_an_end_line_equal_to_the_line_is_kept(tmp_path: Path):
    _write(tmp_path, "one.json", _document([_finding(spans=[_span(line=4, end=4)])]))
    loaded = load_key(tmp_path)
    assert loaded[0].spans[0].line_end == 4


def test_a_second_key_file_is_loaded_in_name_order(tmp_path: Path):
    _write(tmp_path, "b.json", _document())
    later = _document([_finding(id="9-m1", severity="blocker")])
    later["pr"] = 9
    _write(tmp_path, "a.json", later)
    loaded = load_key(tmp_path)
    assert [item.id for item in loaded] == ["9-m1", "1-m1"]
    assert loaded[0].pr == 9
    assert loaded[0].severity == "blocker"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda body: body.pop("pr"), "pr must be a positive integer"),
        (lambda body: body.update(pr=True), "pr must be a positive integer"),
        (lambda body: body.update(pr=0), "pr must be a positive integer"),
        (
            lambda body: body.update(reviewed_commit="674071A9"),
            "reviewed_commit must be 40 lowercase hex",
        ),
        (
            lambda body: body.update(reviewed_commit=1),
            "reviewed_commit must be 40 lowercase hex",
        ),
        (lambda body: body.update(source="  "), "source must be a non-empty string"),
        (lambda body: body.update(findings=[]), "non-empty findings list"),
        (lambda body: body.update(findings="nope"), "non-empty findings list"),
        (lambda body: body.update(note="x"), "unknown key"),
        (
            lambda body: body["findings"][0].update(severity=["minor"]),
            "severity must be",
        ),
        (
            lambda body: body["findings"][0].update(severity="critical"),
            "severity must be",
        ),
        (lambda body: body["findings"][0].update(id="has space"), "underscores"),
        (lambda body: body["findings"][0].update(id=1), "underscores"),
        (lambda body: body["findings"][0].update(summary=""), "summary must be"),
        (lambda body: body["findings"][0].update(lenses=[]), "needs a lens"),
        (lambda body: body["findings"][0].update(lenses=["", "x"]), "lenses must be"),
        (lambda body: body["findings"][0].update(needs=["guess"]), "needs must list"),
        (lambda body: body["findings"][0].update(needs=[]), "needs must list"),
        (lambda body: body["findings"][0].update(needs="read"), "needs must be a list"),
        (lambda body: body["findings"][0].update(spans=[]), "needs a span"),
        (lambda body: body["findings"][0].update(spans="a.py"), "must be a list"),
        (
            lambda body: body["findings"][0].update(
                spans=[{"path": "a.py", "line": 4}]
            ),
            "end_line must be",
        ),
        (
            lambda body: body["findings"][0].update(
                spans=[{"path": "a.py", "line": 8, "end_line": 4}]
            ),
            "end_line must be",
        ),
        (
            lambda body: body["findings"][0].update(
                spans=[{"path": "a.py", "line": True, "end_line": 4}]
            ),
            "line must be a positive",
        ),
        (
            lambda body: body["findings"][0].update(spans=[{"path": BODY, "line": 4}]),
            "body span has no line",
        ),
        (
            lambda body: body["findings"][0].update(citations=["a line"]),
            "file record has no citation",
        ),
        (
            lambda body: body["findings"][0].update(encloses=[]),
            "outside its enclosing function",
        ),
        (
            lambda body: body["findings"][0].update(
                encloses=[{"path": "other.py", "line": 1, "end_line": 10}]
            ),
            "outside its enclosing function",
        ),
        (
            lambda body: body["findings"][0].update(
                encloses=[{"path": "a.py", "line": 1, "end_line": 2}]
            ),
            "outside its enclosing function",
        ),
        (
            lambda body: body["findings"][0].update(
                encloses=[
                    {"path": "a.py", "line": 1, "end_line": 10},
                    {"path": "other.py", "line": 1, "end_line": 4},
                ]
            ),
            "covers no defect",
        ),
        (
            lambda body: body["findings"][0].update(
                spans=[{"path": "a.py", "line": 4, "end_line": 4, "note": 1}]
            ),
            "unknown key",
        ),
        (
            lambda body: body["findings"][0].update(
                spans=[{"path": "", "line": 1, "end_line": 1}]
            ),
            "path must be",
        ),
        (
            lambda body: body["findings"][0].update(encloses=[{"path": BODY}]),
            "not the pull request body",
        ),
        (lambda body: body["findings"][0].update(extra=1), "unknown key"),
        (lambda body: body["findings"][0].update(source=" "), "source must be"),
    ],
)
def test_a_malformed_key_file_is_refused(tmp_path: Path, mutate, message: str):
    body = _document()
    mutate(body)
    _write(tmp_path, "one.json", body)
    with pytest.raises(EvalFormatError, match=message):
        load_key(tmp_path)


def test_two_body_spans_are_refused(tmp_path: Path):
    finding = _body_finding(spans=[{"path": BODY}, {"path": BODY}])
    _write(tmp_path, "one.json", _document([finding]))
    with pytest.raises(EvalFormatError, match="needs one span and a citation"):
        load_key(tmp_path)


def test_a_body_record_without_a_citation_is_refused(tmp_path: Path):
    _write(tmp_path, "one.json", _document([_body_finding(citations=[])]))
    with pytest.raises(EvalFormatError, match="needs one span and a citation"):
        load_key(tmp_path)


def test_a_body_record_with_an_enclosing_span_is_refused(tmp_path: Path):
    _write(tmp_path, "one.json", _document([_body_finding(encloses=[_span()])]))
    with pytest.raises(EvalFormatError, match="has no enclosing span"):
        load_key(tmp_path)


def test_a_record_cannot_be_a_body_and_a_file(tmp_path: Path):
    finding = _finding(spans=[{"path": BODY}, _span()], citations=[_CI], encloses=[])
    _write(tmp_path, "one.json", _document([finding]))
    with pytest.raises(EvalFormatError, match="a body record or a file record"):
        load_key(tmp_path)


def test_a_duplicate_id_is_refused_across_files(tmp_path: Path):
    _write(tmp_path, "a.json", _document())
    other = _document()
    other["pr"] = 2
    _write(tmp_path, "b.json", other)
    with pytest.raises(EvalFormatError, match="repeats finding id"):
        load_key(tmp_path)


def test_a_key_that_is_not_json_or_not_an_object_is_refused(tmp_path: Path):
    _write(tmp_path, "bad.json", [1, 2])
    with pytest.raises(EvalFormatError, match="is not an object"):
        load_key(tmp_path)
    (tmp_path / "bad.json").unlink()
    (tmp_path / "worse.json").write_text("{", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="is not JSON"):
        load_key(tmp_path)


def test_a_key_file_that_is_not_utf8_is_refused(tmp_path: Path):
    (tmp_path / "bad.json").write_bytes(b"\xff")
    with pytest.raises(EvalFormatError, match="cannot be read"):
        load_key(tmp_path)


def test_an_empty_directory_and_a_file_path_are_refused(tmp_path: Path):
    with pytest.raises(EvalFormatError, match="no JSON files"):
        load_key(tmp_path)
    payload = tmp_path / "one.json"
    payload.write_text("{}", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="not a directory"):
        load_key(payload)


def test_a_finding_that_is_not_an_object_is_refused(tmp_path: Path):
    _write(tmp_path, "one.json", _document(["nope"]))
    with pytest.raises(EvalFormatError, match="is not an object"):
        load_key(tmp_path)


def test_a_span_that_is_not_an_object_is_refused(tmp_path: Path):
    _write(tmp_path, "one.json", _document([_finding(spans=["a.py"])]))
    with pytest.raises(EvalFormatError, match="is not an object"):
        load_key(tmp_path)


def _key(finding_id: str) -> KeyFinding:
    return next(item for item in load_key(KEY_DIR) if item.id == finding_id)


def _cite(
    path: str,
    line: int | None = None,
    *,
    quote: str = "the line",
    severity: str = "minor",
    verified: bool = True,
    end_line: int | None = -1,
    lens: str | None = None,
) -> CitedFinding:
    resolved = line if end_line == -1 else end_line
    return CitedFinding(path, quote, severity, verified, line, resolved, lens)


_ROUNDS = "atlas_reviewer/rounds.py"


def test_quoting_the_ci_line_finds_the_stale_body():
    finding = _key("661-m1")
    quoted = _cite(BODY, None, quote=f"Tests: {_CI}", end_line=None)
    assert grade_findings([finding], [quoted]).grades == (FOUND,)
    stack = _cite(BODY, None, quote=f"from the {_STACK}", end_line=None)
    assert grade_findings([finding], [stack]).grades == (FOUND,)


def test_the_stacked_branch_is_stale_does_not_find_the_ci_lines():
    finding = _key("661-m1")
    paraphrase = _cite(BODY, None, quote="the stacked branch is stale", end_line=None)
    assert grade_findings([finding], [paraphrase]).grades == (LOST,)
    sha_only = _cite(BODY, None, quote="61273b4f", end_line=None)
    assert grade_findings([finding], [sha_only]).grades == (LOST,)
    shouted = _cite(BODY, None, quote=_CI.upper(), end_line=None)
    assert grade_findings([finding], [shouted]).grades == (LOST,)


def test_an_unverified_citation_is_not_found():
    finding = _key("661-m1")
    quoted = _cite(BODY, None, quote=_CI, verified=False, end_line=None)
    assert grade_findings([finding], [quoted]).grades == (LOST,)
    nit = _cite(BODY, None, quote=_CI, severity="nit", end_line=None)
    assert grade_findings([finding], [nit]).grades == (PARTIAL,)
    elsewhere = _cite(_ROUNDS, 207, quote=_CI)
    assert grade_findings([finding], [elsewhere]).grades == (LOST,)


def test_a_wrong_line_in_the_right_file_is_not_found():
    finding = _key("661-m2")
    assert grade_findings([finding], [_cite(_ROUNDS, 202)]).grades == (FOUND,)
    assert grade_findings([finding], [_cite(_ROUNDS, 170)]).grades == (PARTIAL,)
    assert grade_findings([finding], [_cite(_ROUNDS, 226)]).grades == (LOST,)
    assert grade_findings(
        [finding], [_cite("atlas_reviewer/coordinator.py", 735)]
    ).grades == (FOUND,)
    assert grade_findings(
        [finding], [_cite("atlas_reviewer/coordinator.py", 740)]
    ).grades == (PARTIAL,)
    assert grade_findings(
        [finding], [_cite("atlas_reviewer/coordinator.py", 700)]
    ).grades == (LOST,)
    unchecked = _cite(_ROUNDS, 203, verified=False, quote="{unreadable} line(s)")
    assert grade_findings([finding], [unchecked]).grades == (LOST,)


def test_the_line_before_the_omitted_findings_gate_does_not_find_it():
    gate = _key("661-m4")
    assert grade_findings([gate], [_cite(_ROUNDS, 206)]).grades == (PARTIAL,)
    both = grade_findings([_key("661-m2"), gate], [_cite(_ROUNDS, 202)])
    assert both.grades == (FOUND, LOST)


def test_the_queue_cancel_check_is_graded_on_its_line():
    cancel = _key("640-m1")
    queue = "atlas_reviewer/service_queue.py"
    assert grade_findings([cancel], [_cite(queue, 329)]).grades == (FOUND,)
    assert grade_findings([cancel], [_cite(queue, 330)]).grades == (PARTIAL,)
    assert grade_findings([cancel], [_cite(queue, 317)]).grades == (LOST,)


def test_the_secret_echo_refusals_are_graded_on_their_spans():
    name_echo = _key("801-m1")
    assert grade_findings([name_echo], [_cite(_FUNDING, 130)]).grades == (FOUND,)
    assert grade_findings([name_echo], [_cite(_FUNDING, 129, end_line=131)]).grades == (
        FOUND,
    )
    assert grade_findings([name_echo], [_cite(_FUNDING, 132)]).grades == (PARTIAL,)
    assert grade_findings([name_echo], [_cite(_FUNDING, 93, end_line=146)]).grades == (
        PARTIAL,
    )
    assert grade_findings([name_echo], [_cite(_FUNDING, 207)]).grades == (LOST,)
    field_echo = _key("801-m2")
    assert grade_findings([field_echo], [_cite(_FUNDING, 207)]).grades == (FOUND,)
    assert grade_findings([field_echo], [_cite(_FUNDING, 206)]).grades == (PARTIAL,)
    extra_echo = _key("801-m3")
    assert grade_findings([extra_echo], [_cite(_FUNDING, 221)]).grades == (FOUND,)
    assert grade_findings(
        [extra_echo], [_cite(_FUNDING, 219, end_line=222)]
    ).grades == (FOUND,)
    assert grade_findings([extra_echo], [_cite(_FUNDING, 223)]).grades == (PARTIAL,)
    slug_echo = _key("801-m4")
    assert grade_findings([slug_echo], [_cite(_FUNDING, 267)]).grades == (FOUND,)
    assert grade_findings([slug_echo], [_cite(_FUNDING, 266)]).grades == (PARTIAL,)
    assert grade_findings([slug_echo], [_cite(_FUNDING, 259, end_line=269)]).grades == (
        PARTIAL,
    )
    assert grade_findings([slug_echo], [_cite(_FUNDING, 244)]).grades == (LOST,)


def test_the_missing_hook_is_found_on_the_check_that_skips_it():
    hook = _key("640-m2")
    poster = "atlas_reviewer/service_post.py"
    assert grade_findings([hook], [_cite(poster, 230)]).grades == (FOUND,)
    assert grade_findings([hook], [_cite(poster, 229, end_line=231)]).grades == (FOUND,)
    assert grade_findings([hook], [_cite(poster, 233)]).grades == (PARTIAL,)
    assert grade_findings([hook], [_cite(poster, 217, end_line=236)]).grades == (
        PARTIAL,
    )
    assert grade_findings([hook], [_cite("atlas_reviewer/service.py", 420)]).grades == (
        LOST,
    )


def test_either_line_that_omits_the_d48_amendment_is_found():
    finding = _key("640-m3")
    assert grade_findings([finding], [_cite("docs/open-questions.md", 62)]).grades == (
        FOUND,
    )
    assert grade_findings(
        [finding], [_cite("atlas_reviewer/README.md", 14)]
    ).grades == (FOUND,)
    assert grade_findings([finding], [_cite("docs/open-questions.md", 61)]).grades == (
        LOST,
    )
    assert grade_findings(
        [finding], [_cite("atlas_reviewer/README.md", 12)]
    ).grades == (LOST,)


def test_a_citation_wider_than_the_defect_is_partial():
    finding = _key("661-m3")
    assert grade_findings([finding], [_cite(_ROUNDS, 181)]).grades == (FOUND,)
    assert grade_findings([finding], [_cite(_ROUNDS, 180, end_line=182)]).grades == (
        FOUND,
    )
    whole_function = _cite(_ROUNDS, 162, end_line=220)
    whole_file = _cite(_ROUNDS, 1, end_line=5000)
    assert grade_findings([finding], [whole_function]).grades == (PARTIAL,)
    assert grade_findings([finding], [whole_file]).grades == (PARTIAL,)


def test_a_major_or_a_blocker_on_the_span_is_found():
    finding = _key("640-m1")
    queue = "atlas_reviewer/service_queue.py"
    assert grade_findings([finding], [_cite(queue, 329, severity="major")]).grades == (
        FOUND,
    )
    assert grade_findings(
        [finding], [_cite(queue, 329, severity="blocker")]
    ).grades == (FOUND,)
    assert grade_findings([finding], [_cite(queue, 329, severity="nit")]).grades == (
        PARTIAL,
    )
    assert grade_findings(
        [finding], [_cite(queue, 329, severity="critical")]
    ).grades == (LOST,)
    assert grade_findings([finding], [_cite(queue, 329, severity="Minor")]).grades == (
        FOUND,
    )
    assert grade_findings([finding], [_cite(queue, 329, severity="Nit")]).grades == (
        PARTIAL,
    )


def test_two_lenses_on_one_span_count_once_and_a_blocker_is_not_a_major():
    finding = _key("640-m1")
    queue = "atlas_reviewer/service_queue.py"
    graded = grade_findings(
        [finding],
        [
            _cite(queue, 329, lens="reviewing-test-quality"),
            _cite(queue, 329, lens="hunting-silent-failures", severity="blocker"),
        ],
    )
    assert graded.grades == (FOUND,)
    assert graded.extras == 1
    assert graded.extra_majors == 0
    unused = grade_findings([finding], [_cite(queue, 1, severity="Major")])
    assert unused.grades == (LOST,)
    assert unused.extras == 1
    assert unused.extra_majors == 1
    blocker = grade_findings([finding], [_cite(queue, 1, severity="Blocker")])
    assert blocker.extras == 1
    assert blocker.extra_majors == 0


def _span_finding(finding_id: str, start: int, end: int) -> KeyFinding:
    return KeyFinding(
        finding_id,
        1,
        _COMMIT,
        "synthetic",
        "minor",
        "overlap",
        (Span("a.py", start, end),),
        (Span("a.py", 1, 40),),
        (),
        ("tracing-correctness-and-invariants",),
        ("read",),
    )


def test_overlapping_spans_are_both_found_in_either_candidate_order():
    findings = (_span_finding("a", 10, 20), _span_finding("b", 15, 25))
    wide = _cite("a.py", 18)
    narrow = _cite("a.py", 12)
    assert grade_findings(findings, [wide, narrow]).grades == (FOUND, FOUND)
    assert grade_findings(findings, [narrow, wide]).grades == (FOUND, FOUND)
    # The wide finding can move off the line the narrow one needs.
    crowded = (_span_finding("a", 10, 12), _span_finding("b", 10, 30))
    assert grade_findings(crowded, [_cite("a.py", 11), _cite("a.py", 20)]).grades == (
        FOUND,
        FOUND,
    )


def test_a_span_with_no_line_and_an_inverted_range_are_lost():
    bare = KeyFinding(
        "bare",
        1,
        _COMMIT,
        "no line",
        "minor",
        "bare",
        (Span("a.py"),),
        (Span("b.py", 1, 10),),
        (),
        ("tracing-correctness-and-invariants",),
        ("read",),
    )
    assert grade_findings([bare], [_cite("a.py", 4)]).grades == (LOST,)
    inverted = _cite(_ROUNDS, 203, end_line=200)
    assert grade_findings([_key("661-m2")], [inverted]).grades == (LOST,)
    open_end = _cite(_ROUNDS, 202, end_line=None)
    assert grade_findings([_key("661-m2")], [open_end]).grades == (FOUND,)
    assert grade_findings((), ()).extras == 0


def test_liveness_specs_load_and_refuse_bad_shapes(tmp_path: Path):
    finding = _finding(
        liveness=[
            {
                "kind": "mutant",
                "file": "a.py",
                "old": "if a:",
                "new": "if b:",
            }
        ]
    )
    loaded = load_key(_write_key(tmp_path, finding))[0]
    assert loaded.liveness[0].kind == "mutant"
    assert loaded.liveness[0].old == "if a:"
    quote = _finding(liveness=[{"kind": "quote", "file": "a.py", "text": "x"}])
    assert load_key(_write_key(tmp_path, quote))[0].liveness[0].text == "x"
    absent = _finding(liveness=[{"kind": "absent", "file": "a.py", "text": "x"}])
    assert load_key(_write_key(tmp_path, absent))[0].liveness[0].kind == "absent"
    for bad in (
        {"kind": "splice", "file": "a.py", "old": "a", "new": "b"},
        {"kind": "mutant", "file": "a.py", "old": "a", "new": "a"},
        {"kind": "mutant", "file": "a.py", "old": "a", "new": "b", "text": "x"},
        {"kind": "mutant", "file": "a.py", "old": "", "new": "b"},
        {"kind": "quote", "file": "a.py", "text": ""},
        {"kind": "quote", "file": "a.py", "text": "x", "old": "a"},
        {"kind": "quote", "file": "a.py", "old": "a", "new": "b"},
        [],
        [{"kind": "quote", "file": "a.py", "text": 3}],
    ):
        with pytest.raises(EvalFormatError):
            load_key(_write_key(tmp_path, _finding(liveness=bad)))


_KEY_DIRS = iter(count())


def _write_key(directory: Path, finding: dict[str, object]) -> Path:
    key_dir = directory / f"key-{next(_KEY_DIRS)}"
    key_dir.mkdir()
    path = key_dir / "key.json"
    path.write_text(
        json.dumps(
            {
                "pr": 1,
                "reviewed_commit": _COMMIT,
                "source": "a plan row",
                "findings": [finding],
            }
        ),
        encoding="utf-8",
    )
    return key_dir


def test_a_shallow_checkout_fetches_a_missing_anchor_before_reading_it(
    tmp_path, monkeypatch
):
    """The liveness checks' anchor reads work on CI's shallow checkout
    (round-4 CI on #846): `actions/checkout` fetches depth 2, so the
    anchor commits the key names are not in the object store, and `git
    show <anchor>:<file>` there answers with the misleading 'exists on
    disk, but not in <commit>' -- exactly what #846's first green-bound
    run died on, in the two 661-m2 quote specs that ran before any
    mutant spec had fetched their anchor. Every reader goes through
    `_ensure_commit`, which fetches a missing commit from origin first.

    The fixture is self-contained (the round-5 review's Major on #842):
    a small origin built in tmp_path whose anchor commit is reachable
    from no ref, a shallow clone of it as the checkout, and the helpers
    pointed at that clone -- so the test depends on no runner's clone
    depth and on no real anchor object. The fetch is served by the
    fixture origin's own `uploadpack.allowAnySHA1InWant`, the same
    setting that lets CI fetch the real anchors."""
    import importlib.util
    import os
    import subprocess

    spec = importlib.util.spec_from_file_location(
        "liveness_test",
        Path(__file__).resolve().parents[1]
        / "liveness"
        / "test_parity_key_liveness.py",
    )
    liveness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(liveness)

    origin = tmp_path / "origin"
    (origin / "atlas_reviewer").mkdir(parents=True)
    identity = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*argv: str) -> str:
        done = subprocess.run(
            ["git", *argv],
            cwd=origin,
            capture_output=True,
            text=True,
            check=True,
            env=identity,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    (origin / "atlas_reviewer" / "coordinator.py").write_text(
        '# SPDX-License-Identifier: MIT\n"""The agentic coordinator: run the'
        ' selected lens under the attestation ledger."""\n'
    )
    git("add", "-A")
    git("commit", "-qm", "base")
    (origin / "atlas_reviewer" / "coordinator.py").write_text(
        '# SPDX-License-Identifier: MIT\n"""The agentic coordinator: run the'
        " selected lens under the attestation ledger, verify its output and"
        ' synthesize the draft."""\n'
    )
    git("add", "-A")
    git("commit", "-qm", "anchor")
    anchor = git("rev-parse", "HEAD")
    base = git("rev-parse", "HEAD~1")
    # The anchor is reachable from no ref, the way the real round-5
    # anchor is not on any branch.
    git("checkout", "-q", "--detach", anchor)
    git("branch", "-f", "main", base)
    git("checkout", "-q", "main")
    git("config", "uploadpack.allowAnySHA1InWant", "true")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)],
        check=True,
    )
    missing = subprocess.run(
        ["git", "cat-file", "-e", f"{anchor}^{{commit}}"],
        cwd=shallow,
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0, "the fixture clone holds the anchor already"
    monkeypatch.setattr(liveness, "_REPO", shallow)
    content = liveness._anchored_text(anchor, "atlas_reviewer/coordinator.py")
    assert "verify its output and synthesize the draft" in content


def test_the_liveness_suite_refuses_a_run_that_never_reported_counts(
    tmp_path, monkeypatch
):
    """A crashed or empty anchor-suite run reports no failures, and the
    mutant comparison would then read as vacuously live (the round-1
    Minor: nothing asserted the suite actually ran). `_suite` refuses a
    run whose output carries no pytest summary with passed/failed
    counts, so the check fails loudly instead."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "liveness_test",
        Path(__file__).resolve().parents[1]
        / "liveness"
        / "test_parity_key_liveness.py",
    )
    liveness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(liveness)

    ran = tmp_path / "ran"
    ran.mkdir()
    (ran / "test_one.py").write_text("def test_one():\n    assert True\n")
    assert liveness._suite(ran) == frozenset()

    empty = tmp_path / "empty"
    empty.mkdir()
    try:
        liveness._suite(empty)
    except AssertionError as exc:
        assert "no pytest summary" in str(exc)
    else:
        raise AssertionError("an empty run was accepted as a baseline")


def test_the_liveness_suite_reports_the_failures_it_saw(tmp_path):
    """The guard keeps the failure extraction honest: a suite whose test
    fails yields exactly that test's id."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "liveness_test",
        Path(__file__).resolve().parents[1]
        / "liveness"
        / "test_parity_key_liveness.py",
    )
    liveness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(liveness)

    failing = tmp_path / "failing"
    failing.mkdir()
    (failing / "test_one.py").write_text("def test_one():\n    assert False\n")
    failures = liveness._suite(failing)
    assert failures == frozenset({"test_one.py::test_one"}) or any(
        "test_one" in f for f in failures
    )
