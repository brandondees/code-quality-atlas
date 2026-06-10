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
    data = json.loads(open(path, encoding="utf-8").read())
    return EvalDoc(skills=data["skills"], scenarios=data["scenarios"])


def validate_evals(doc: EvalDoc) -> None:
    if len(doc.scenarios) < 3:
        raise EvalError("a skill must ship at least 3 eval scenarios")
    for i, s in enumerate(doc.scenarios):
        if not s.get("query"):
            raise EvalError(f"scenario {i}: missing query")
        if not s.get("expected_behavior"):
            raise EvalError(f"scenario {i}: missing expected_behavior")
