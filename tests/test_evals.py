# SPDX-License-Identifier: MIT
# tests/test_evals.py
import json, pytest
from tooling.evals import load_evals, validate_evals, EvalError

def _write(tmp_path, doc):
    p = tmp_path / "eval.json"
    p.write_text(json.dumps(doc))
    return str(p)

def _good():
    return {"skills": ["hunting-silent-failures"], "scenarios": [
        {"query": "review this diff", "expected_behavior": ["flags empty rescue"]},
        {"query": "review this diff 2", "expected_behavior": ["flags missing timeout"]},
        {"query": "review this diff 3", "expected_behavior": ["flags swallowed error"]},
    ]}

def test_load_and_validate_good_evals(tmp_path):
    evals = load_evals(_write(tmp_path, _good()))
    validate_evals(evals)  # no raise
    assert len(evals.scenarios) == 3

def test_validate_requires_at_least_three(tmp_path):
    doc = _good(); doc["scenarios"] = doc["scenarios"][:2]
    with pytest.raises(EvalError, match="at least 3"):
        validate_evals(load_evals(_write(tmp_path, doc)))

def test_validate_honors_a_raised_min_scenarios(tmp_path):
    # Q21: a lens can opt into a higher bar than D8's baseline via the
    # manifest's eval_min; validate_evals must enforce whatever the caller
    # passes, not just the hardcoded default.
    evals = load_evals(_write(tmp_path, _good()))  # 3 scenarios
    with pytest.raises(EvalError, match="at least 5"):
        validate_evals(evals, min_scenarios=5)

def test_validate_min_scenarios_defaults_to_three(tmp_path):
    doc = _good(); doc["scenarios"] = doc["scenarios"][:2]
    with pytest.raises(EvalError, match="at least 3"):
        validate_evals(load_evals(_write(tmp_path, doc)))  # no min_scenarios passed

def test_validate_requires_expected_behavior(tmp_path):
    doc = _good(); doc["scenarios"][0].pop("expected_behavior")
    with pytest.raises(EvalError, match="expected_behavior"):
        validate_evals(load_evals(_write(tmp_path, doc)))

def test_load_evals_wraps_bad_json_as_eval_error(tmp_path):
    """Malformed JSON must surface as a clean, path-tagged EvalError, not a raw
    JSONDecodeError that escapes the CLI's `except EvalError` handler."""
    p = tmp_path / "eval.json"
    p.write_text("{not valid json")
    with pytest.raises(EvalError, match="eval.json"):
        load_evals(str(p))

def test_load_evals_wraps_missing_key_as_eval_error(tmp_path):
    """A JSON file missing a required top-level key must raise EvalError, not a
    bare KeyError."""
    p = tmp_path / "eval.json"
    p.write_text(json.dumps({"scenarios": []}))  # missing "skills"
    with pytest.raises(EvalError, match="skills"):
        load_evals(str(p))

def test_load_evals_wraps_missing_file_as_eval_error(tmp_path):
    """An unreadable/absent file must raise EvalError, not a raw OSError."""
    with pytest.raises(EvalError):
        load_evals(str(tmp_path / "does_not_exist.json"))

def test_load_evals_wraps_non_utf8_as_eval_error(tmp_path):
    """A non-UTF-8 eval.json raises UnicodeDecodeError (a ValueError, not OSError)
    on read; it must still surface as EvalError, not a raw traceback."""
    p = tmp_path / "eval.json"
    p.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(EvalError, match="eval.json"):
        load_evals(str(p))

def test_load_evals_wraps_non_object_json_as_eval_error(tmp_path):
    """Valid JSON that isn't an object (a bare array/scalar) must raise EvalError
    with an actionable message, not a raw TypeError from subscripting."""
    p = tmp_path / "eval.json"
    p.write_text("[1, 2, 3]")
    with pytest.raises(EvalError, match="must be a JSON object"):
        load_evals(str(p))
