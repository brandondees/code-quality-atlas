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
    # A missing file (OSError), malformed JSON (JSONDecodeError), a JSON body
    # missing a required key (KeyError), or a non-object body such as a bare
    # array/scalar (TypeError from subscripting) must all surface as EvalError so
    # the CLI's `except EvalError` handler renders a clean "INVALID:" line instead
    # of leaking a raw traceback to the operator.
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.loads(fh.read())
        return EvalDoc(skills=data["skills"], scenarios=data["scenarios"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise EvalError(f"{path}: {exc}") from exc


def validate_evals(doc: EvalDoc) -> None:
    if len(doc.scenarios) < 3:
        raise EvalError("a skill must ship at least 3 eval scenarios")
    for i, s in enumerate(doc.scenarios):
        if not s.get("query"):
            raise EvalError(f"scenario {i}: missing query")
        if not s.get("expected_behavior"):
            raise EvalError(f"scenario {i}: missing expected_behavior")
