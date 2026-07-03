# SPDX-License-Identifier: MIT
# tooling/evals.py
from __future__ import annotations
from dataclasses import dataclass
import json


class EvalError(Exception):
    pass


@dataclass
class EvalDoc:
    skills: list[str]
    scenarios: list[dict]


def load_evals(path: str) -> EvalDoc:
    # A missing file (OSError), malformed JSON (JSONDecodeError), a non-object
    # body (array/scalar), or a missing required key (KeyError) must all surface
    # as EvalError so the CLI's `except EvalError` handler renders a clean
    # "INVALID:" line instead of leaking a raw traceback to the operator. The
    # explicit isinstance check gives a non-object body an actionable message
    # rather than Python's raw "list indices must be integers" TypeError text.
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.loads(fh.read())
        if not isinstance(data, dict):
            raise EvalError(
                f"{path}: eval doc must be a JSON object, got {type(data).__name__}")
        return EvalDoc(skills=data["skills"], scenarios=data["scenarios"])
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise EvalError(f"{path}: {exc}") from exc


def validate_evals(doc: EvalDoc) -> None:
    if len(doc.scenarios) < 3:
        raise EvalError("a skill must ship at least 3 eval scenarios")
    for i, s in enumerate(doc.scenarios):
        if not s.get("query"):
            raise EvalError(f"scenario {i}: missing query")
        if not s.get("expected_behavior"):
            raise EvalError(f"scenario {i}: missing expected_behavior")
