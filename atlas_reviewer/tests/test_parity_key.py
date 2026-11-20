# SPDX-License-Identifier: MIT
"""The parity key: the seven protocol Minors and the loader that refuses a bad record."""

import json
from pathlib import Path

import pytest

from atlas_reviewer.eval_harness import EvalFormatError
from atlas_reviewer.parity_key import KEY_DIR, load_key

_COMMIT = "674071a91513b4774c82350fb757d9c085f10baf"
_QUEUE = "72c56eb24d16025719c4d58ba921eadef94bb8a8"


def _finding(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "1-m1",
        "severity": "minor",
        "path": "a.py",
        "line": 10,
        "summary": "a defect",
        "lenses": ["tracing-correctness-and-invariants"],
        "markers": ["defect"],
        "needs": ["read"],
        "match": "place",
    }
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


def test_the_checked_in_key_is_the_seven_protocol_minors():
    findings = load_key(KEY_DIR)
    by_id = {item.id: item for item in findings}
    assert list(by_id) == [
        "640-m1",
        "640-m2",
        "640-m3",
        "661-m1",
        "661-m2",
        "661-m3",
        "661-m4",
    ]
    assert by_id["640-m1"].reviewed_commit == _QUEUE
    anchor = by_id["640-m1"].as_eval()
    assert anchor.path == "atlas_reviewer/service_queue.py"
    assert anchor.line_start == 329
    assert anchor.line_end is None
    assert anchor.lenses == ("reviewing-test-quality",)
    assert by_id["640-m1"].needs == ("mutate",)
    assert by_id["640-m2"].path == "unlocated"
    assert by_id["640-m2"].line_start is None
    assert by_id["640-m2"].match == "unscored"
    assert by_id["640-m2"].markers == ()
    assert by_id["640-m2"].lenses == ()
    assert "mt14/report-draft.md" in by_id["640-m2"].source
    assert by_id["640-m3"].match == "unscored"
    assert by_id["640-m3"].markers == ()
    assert by_id["640-m3"].lenses == ("reviewing-decision-lifecycle",)
    assert by_id["661-m1"].reviewed_commit == _COMMIT
    assert by_id["661-m1"].path == "pull_request.body"
    assert by_id["661-m1"].needs == ("ci",)
    assert "CI and stack lines are stale" in by_id["661-m1"].summary
    assert by_id["661-m1"].markers == ("CI and stack lines are stale",)
    assert by_id["661-m2"].line_start == 207
    assert by_id["661-m2"].path == "atlas_reviewer/rounds.py"
    assert 'unreadable shown as "1 line"' in by_id["661-m2"].summary
    assert by_id["661-m3"].line_start == 186
    assert by_id["661-m3"].needs == ("run_tests", "mutate")
    assert by_id["661-m4"].line_start == 211
    assert all(item.severity == "minor" for item in findings)
    for record in (by_id["640-m3"], by_id["661-m1"]):
        with pytest.raises(EvalFormatError, match="has no place to grade"):
            record.as_eval()


def test_a_second_key_file_is_loaded_in_name_order(tmp_path: Path):
    _write(tmp_path, "b.json", _document())
    later = _document([_finding(id="9-m1", line=4, end_line=8, severity="blocker")])
    later["pr"] = 9
    _write(tmp_path, "a.json", later)
    loaded = load_key(tmp_path)
    assert [item.id for item in loaded] == ["9-m1", "1-m1"]
    assert loaded[0].pr == 9
    assert loaded[0].line_end == 8
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
        (lambda body: body.update(source="  "), "source must be a non-empty string"),
        (lambda body: body.update(findings=[]), "non-empty findings list"),
        (lambda body: body.update(findings="nope"), "non-empty findings list"),
        (lambda body: body.update(note="x"), "unknown key"),
        (
            lambda body: body["findings"][0].update(match="fuzzy"),
            "place, markers or unscored",
        ),
        (
            lambda body: body["findings"][0].update(match=["place"]),
            "place, markers or unscored",
        ),
        (
            lambda body: body["findings"][0].update(match={}),
            "place, markers or unscored",
        ),
        (
            lambda body: body["findings"][0].update(severity="critical"),
            "severity must be",
        ),
        (lambda body: body["findings"][0].pop("line"), "place match needs a line"),
        (lambda body: body["findings"][0].update(line=True), "line must be a positive"),
        (lambda body: body["findings"][0].update(end_line=9), "end_line must be"),
        (
            lambda body: body["findings"][0].update(match="markers", markers=[]),
            "marker match needs a marker",
        ),
        (lambda body: body["findings"][0].update(needs=["guess"]), "needs must list"),
        (lambda body: body["findings"][0].update(needs=[]), "needs must list"),
        (lambda body: body["findings"][0].update(id="has space"), "underscores"),
        (lambda body: body["findings"][0].update(path=""), "path must be"),
        (lambda body: body["findings"][0].update(lenses=["", "x"]), "lenses must be"),
        (lambda body: body["findings"][0].update(extra=1), "unknown key"),
    ],
)
def test_a_malformed_key_file_is_refused(tmp_path: Path, mutate, message: str):
    body = _document()
    mutate(body)
    _write(tmp_path, "one.json", body)
    with pytest.raises(EvalFormatError, match=message):
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


def test_an_end_line_equal_to_the_line_is_kept(tmp_path: Path):
    _write(tmp_path, "one.json", _document([_finding(line=4, end_line=4)]))
    loaded = load_key(tmp_path)
    assert loaded[0].line_end == 4


def test_an_unscored_record_with_markers_is_refused(tmp_path: Path):
    body = _document()
    findings = body["findings"]
    assert isinstance(findings, list)
    finding = findings[0]
    assert isinstance(finding, dict)
    finding.update(match="unscored", markers=["skipped"], line=None)
    _write(tmp_path, "one.json", body)
    with pytest.raises(EvalFormatError, match="1-m1 is unscored and cannot carry"):
        load_key(tmp_path)


def test_an_end_line_without_a_line_is_refused(tmp_path: Path):
    _write(
        tmp_path,
        "one.json",
        _document([_finding(match="markers", line=None, end_line=4)]),
    )
    with pytest.raises(EvalFormatError, match="end_line must be"):
        load_key(tmp_path)
