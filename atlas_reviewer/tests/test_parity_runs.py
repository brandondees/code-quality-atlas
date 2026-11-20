# SPDX-License-Identifier: MIT
"""Recorded run files, and the offline command that scores them."""

import io
import json
import math
import shutil
from pathlib import Path

import pytest

from atlas_reviewer import cli
from atlas_reviewer.eval_harness import EvalFormatError
from atlas_reviewer.parity_key import load_runs

_SHA = "674071a91513b4774c82350fb757d9c085f10baf"
_OFFLINE = Path(__file__).resolve().parents[1] / "fixtures" / "parity-offline"


def _payload(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "pr": 661,
        "model": "recorded-fixture",
        "repetition": 1,
        "head_sha": _SHA,
        "coverage_complete": True,
        "lenses_run": ["reviewing-test-quality"],
        "lenses_not_run": [],
        "lenses_failed": [],
        "limit_stops": [],
        "findings": [
            {
                "severity": "minor",
                "path": "a.py",
                "quote": "the line",
                "verified": True,
                "line": 3,
                "end_line": 3,
                "lens": "reviewing-test-quality",
            }
        ],
    }
    body.update(over)
    return body


def test_a_run_directory_round_trips_and_optional_counts_may_be_null(tmp_path: Path):
    (tmp_path / "b.json").write_text(
        json.dumps(
            _payload(
                repetition=2, cost_usd=None, false_positive_majors=0, wall_seconds=0
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "a.json").write_text(json.dumps(_payload(cost_usd=1)), encoding="utf-8")
    runs = load_runs(tmp_path)
    assert [item.name for item in runs] == ["a.json", "b.json"]
    assert runs[0].cost_usd == 1.0
    cited = runs[0].findings[0]
    assert cited.quote == "the line"
    assert cited.verified is True
    assert cited.line == 3
    assert cited.end_line == 3
    assert cited.lens == "reviewing-test-quality"
    assert runs[0].false_positive_majors is None
    assert runs[1].false_positive_majors == 0
    assert runs[1].wall_seconds == 0.0
    assert runs[1].cache_read_tokens is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda body: body.update(coverage_complete="yes"), "must be true or false"),
        (lambda body: body.update(cost_usd=-1), "finite number"),
        (lambda body: body.update(cost_usd=math.nan), "finite number"),
        (lambda body: body.update(cost_usd=True), "finite number"),
        (
            lambda body: body.update(false_positive_majors=True),
            "integer that is at least 0",
        ),
        (
            lambda body: body.update(false_positive_majors=-1),
            "integer that is at least 0",
        ),
        (lambda body: body.update(note=1), "unknown key"),
        (lambda body: body.update(unreviewed_files=0), "unknown key"),
        (lambda body: body.update(findings="nope"), "needs a findings list"),
        (lambda body: body["findings"].__setitem__(0, "nope"), "is not an object"),
        (
            lambda body: body["findings"][0].update(severity="critical"),
            "severity must be",
        ),
        (
            lambda body: body["findings"][0].update(severity=["minor"]),
            "severity must be",
        ),
        (
            lambda body: body["findings"][0].pop("verified"),
            "verified must be true or false",
        ),
        (
            lambda body: body["findings"][0].update(verified=1),
            "verified must be true or false",
        ),
        (lambda body: body["findings"][0].update(quote=None), "quote must be a string"),
        (lambda body: body["findings"][0].update(end_line=1), "end_line must be"),
        (lambda body: body["findings"][0].pop("line"), "end_line must be"),
        (lambda body: body["findings"][0].update(lens="  "), "lens must be"),
        (lambda body: body.update(model="  "), "model must be a non-empty string"),
        (
            lambda body: body.update(head_sha="72c56eb"),
            "head_sha must be 40 lowercase hex",
        ),
    ],
)
def test_a_malformed_run_is_refused(tmp_path: Path, mutate, message: str):
    body = _payload()
    mutate(body)
    (tmp_path / "one.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(EvalFormatError, match=message):
        load_runs(tmp_path)


def test_a_repeated_repetition_and_an_empty_directory_are_refused(tmp_path: Path):
    with pytest.raises(EvalFormatError, match="no JSON files"):
        load_runs(tmp_path)
    payload = tmp_path / "one.json"
    payload.write_text("{}", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="not a directory"):
        load_runs(payload)
    payload.unlink()
    (tmp_path / "a.json").write_text(json.dumps(_payload()), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(EvalFormatError, match="repeats repetition"):
        load_runs(tmp_path)


def test_a_null_lens_is_absent(tmp_path: Path):
    body = _payload()
    body["findings"][0]["lens"] = None
    (tmp_path / "one.json").write_text(json.dumps(body), encoding="utf-8")
    assert load_runs(tmp_path)[0].findings[0].lens is None


def test_an_unreadable_run_file_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "bad.json"
    target.write_text("{}", encoding="utf-8")
    original = Path.read_text

    def deny(self: Path, *args: object, **kwargs: object) -> str:
        if self == target:
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(EvalFormatError, match="cannot be read"):
        load_runs(tmp_path)
    code, out, err = _cli("eval-parity", "--runs", str(tmp_path))
    assert code == 2
    assert out == ""
    assert "cannot be read" in err


def test_a_run_headed_at_the_merged_commit_does_not_pass(tmp_path: Path):
    runs = tmp_path / "runs"
    shutil.copytree(_OFFLINE, runs)
    merged = "72c56eb24d16025719c4d58ba921eadef94bb8a8"
    for name in ("640-1.json", "640-2.json", "640-3.json"):
        path = runs / name
        body = json.loads(path.read_text(encoding="utf-8"))
        body["head_sha"] = merged
        path.write_text(json.dumps(body), encoding="utf-8")
    code, out, err = _cli("eval-parity", "--runs", str(runs))
    assert code == 1
    assert err == ""
    assert f"head_sha {merged} is not the reviewed commit" in out


def test_a_run_file_that_is_not_json_is_refused(tmp_path: Path):
    (tmp_path / "bad.json").write_bytes(b"\xff")
    with pytest.raises(EvalFormatError, match="cannot be read"):
        load_runs(tmp_path)
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(EvalFormatError, match="is not JSON"):
        load_runs(tmp_path)


def _cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), env={}, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_the_checked_in_runs_pass_and_are_not_a_model_measurement():
    code, out, err = _cli("eval-parity", "--runs", str(_OFFLINE))
    assert code == 0, err
    report = json.loads(out)
    assert report["gate_pass"] is True
    assert report["failures"] == []
    assert [item["id"] for item in report["findings"]] == [
        "640-m1",
        "640-m2",
        "640-m3",
        "661-m1",
        "661-m2",
        "661-m3",
        "661-m4",
    ]
    assert all(
        item["passed"] is True and item["found"] == 3 for item in report["findings"]
    )
    assert all(
        item["extras"] == 1 and item["cost_usd"] is None for item in report["runs"]
    )
    readme = (_OFFLINE / "README.md").read_text(encoding="utf-8")
    assert "not a measurement" in readme
    assert "scorer fixtures" in readme


def test_a_named_key_directory_is_the_one_scored(tmp_path: Path):
    key = tmp_path / "key"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "fixtures" / "parity-key", key
    )
    (key / "661.json").unlink()
    code, out, err = _cli("eval-parity", "--runs", str(_OFFLINE), "--key", str(key))
    assert code == 1
    assert err == ""
    assert "pull request 661, which is not in the key" in out


def test_a_finding_missed_in_two_runs_exits_1(tmp_path: Path):
    shutil.copytree(_OFFLINE, tmp_path, dirs_exist_ok=True)
    for name in ("661-1.json", "661-2.json"):
        path = tmp_path / name
        body = json.loads(path.read_text(encoding="utf-8"))
        body["findings"] = [
            item for item in body["findings"] if item.get("path") != "pull_request.body"
        ]
        path.write_text(json.dumps(body), encoding="utf-8")
    code, out, err = _cli("eval-parity", "--runs", str(tmp_path))
    assert code == 1
    assert err == ""
    report = json.loads(out)
    assert any("661-m1 found in 1 of 3" in item for item in report["failures"])


def test_a_malformed_run_directory_exits_2(tmp_path: Path):
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    code, out, err = _cli("eval-parity", "--runs", str(tmp_path))
    assert code == 2
    assert out == ""
    assert "is not JSON" in err
