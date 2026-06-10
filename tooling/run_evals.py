# tooling/run_evals.py
"""Run a skill's eval scenarios against a local model.

This is the cross-model eval harness (spec phase-2 §7). It assembles the
progressive-disclosure context a model with the skill loaded would see
(SKILL.md + reference/heuristics.md + examples.md), sends each scenario's
query to the model, and prints the response next to its expected_behavior so
a human/judge can grade. Two backends: the Ollama API (`--api ollama`) and
any OpenAI-compatible /v1/chat/completions server such as llama-server
(`--api openai`). Network calls are isolated in `query_*` so tests mock
them (no model server needed in CI).
"""
from __future__ import annotations
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tooling.evals import load_evals

OLLAMA_HOST = "http://localhost:11434"
OPENAI_HOST = "http://localhost:8080"  # llama-server default

_REVIEWER_DIRECTIVE = (
    "\n\n---\n\nYou are a code reviewer applying the skill above. Review the "
    "user's code change and report concrete findings (or state there are none). "
    "Be concise."
)


def assemble_context(skill_dir: Path) -> str:
    """The content a model with this skill loaded would have available."""
    parts = [(skill_dir / "SKILL.md").read_text(encoding="utf-8")]
    for rel in ("reference/heuristics.md", "examples.md"):
        p = skill_dir / rel
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def query_ollama(model: str, system: str, user: str,
                 host: str = OLLAMA_HOST, timeout: int = 180) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # evals must be reproducible — never inherit a server's sampling default
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


def query_openai(model: str, system: str, user: str,
                 host: str = OPENAI_HOST, timeout: int = 600) -> str:
    """OpenAI-compatible /v1/chat/completions (llama-server, vLLM, ...)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # evals must be reproducible — never inherit a server's sampling default
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{host}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


@dataclass
class ScenarioRun:
    query: str
    expected_behavior: list[str]
    response: str


def run_skill_evals(skill_dir: Path, model: str,
                    host: str = OLLAMA_HOST, api: str = "ollama") -> list[ScenarioRun]:
    query = {"ollama": query_ollama, "openai": query_openai}[api]
    system = assemble_context(skill_dir) + _REVIEWER_DIRECTIVE
    doc = load_evals(str(skill_dir / "evals" / "eval.json"))
    runs: list[ScenarioRun] = []
    for s in doc.scenarios:
        response = query(model, system, s["query"], host=host)
        runs.append(ScenarioRun(s["query"], s["expected_behavior"], response))
    return runs


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="run-evals")
    ap.add_argument("--skill", required=True)
    ap.add_argument("--skills-root", default="skills")
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--api", choices=["ollama", "openai"], default="ollama")
    ap.add_argument("--host", default=None,
                    help="defaults to the chosen api's local port")
    args = ap.parse_args(argv)
    host = args.host or {"ollama": OLLAMA_HOST, "openai": OPENAI_HOST}[args.api]

    skill_dir = Path(args.skills_root, args.skill)
    runs = run_skill_evals(skill_dir, args.model, host=host, api=args.api)
    for i, r in enumerate(runs, 1):
        print(f"\n{'=' * 72}\nSCENARIO {i}")
        print(f"QUERY:\n{r.query}\n")
        print(f"--- {args.model} RESPONSE ---\n{r.response}\n")
        print("EXPECTED BEHAVIOR:")
        for b in r.expected_behavior:
            print(f"  - {b}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
