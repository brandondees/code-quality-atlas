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

def test_validate_requires_expected_behavior(tmp_path):
    doc = _good(); doc["scenarios"][0].pop("expected_behavior")
    with pytest.raises(EvalError, match="expected_behavior"):
        validate_evals(load_evals(_write(tmp_path, doc)))
