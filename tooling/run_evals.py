# SPDX-License-Identifier: MIT
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
import http.client
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tooling.evals import load_evals

OLLAMA_HOST = "http://localhost:11434"
OPENAI_HOST = "http://localhost:8080"  # llama-server default

# Ollama defaults to a 2048-token context and *silently truncates* anything
# longer — which drops the head of the assembled skill context (SKILL.md's
# discipline + Top checks), so the model reviews against a partial prompt and
# the run looks valid while being meaningless. Pin a window that comfortably
# fits the largest assembled context (~3k tokens today) with headroom. The
# OpenAI-compatible path sets its window server-side (llama-server -c), so this
# only applies to Ollama. (The llama.cpp runbook uses -c 16384 for the same
# reason.)
OLLAMA_NUM_CTX = 8192

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


def _post_json(url: str, payload: dict, timeout: int, label: str) -> object:
    """POST `payload` as JSON and parse the JSON reply, turning network failures
    and non-JSON bodies into a RuntimeError that names the backend — so a single
    transient or an error page doesn't abort the run with a raw traceback.

    Returns whatever JSON the server sent (json.loads can yield a list, str, None,
    etc.); callers must narrow with isinstance before any dict access."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        # OSError covers URLError/TimeoutError (connection refused, DNS, timeout);
        # HTTPException covers malformed responses from the server side.
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError(f"{label} request to {url} failed: {e}") from e
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"{label} returned a non-JSON response: {e}") from e


def query_ollama(model: str, system: str, user: str,
                 host: str = OLLAMA_HOST, timeout: int = 600) -> str:
    """Ollama /api/chat with sampling pinned and the context window widened so
    the full skill prompt isn't silently truncated (see OLLAMA_NUM_CTX)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # evals must be reproducible — never inherit a server's sampling default;
        # num_ctx must fit the whole skill context or Ollama silently truncates it.
        "options": {"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
    }
    data = _post_json(f"{host}/api/chat", payload, timeout, "Ollama")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Ollama API error: {data['error']}")
    content = data.get("message", {}).get("content") if isinstance(data, dict) else None
    if not isinstance(content, str):
        raise RuntimeError(f"unexpected Ollama response shape: {data!r}")
    return content


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
    data = _post_json(f"{host}/v1/chat/completions", payload, timeout,
                      "OpenAI-compatible")
    if isinstance(data, dict) and data.get("error"):
        # OpenAI-compatible errors are objects ({"error": {"message": ...}});
        # surface the message text rather than the dict repr.
        err = data["error"]
        if isinstance(err, dict):
            err = err.get("message", err)
        raise RuntimeError(f"OpenAI-compatible API error: {err}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"unexpected OpenAI-compatible response shape: {data!r}") from e
    if not isinstance(content, str):
        raise RuntimeError(f"unexpected OpenAI-compatible response shape: {data!r}")
    return content


@dataclass
class ScenarioRun:
    query: str
    expected_behavior: list[str]
    response: str


DEFAULT_HOSTS = {"ollama": OLLAMA_HOST, "openai": OPENAI_HOST}


def run_skill_evals(skill_dir: Path, model: str,
                    host: str | None = None, api: str = "ollama") -> list[ScenarioRun]:
    query = {"ollama": query_ollama, "openai": query_openai}[api]
    host = host or DEFAULT_HOSTS[api]
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

    skill_dir = Path(args.skills_root, args.skill)
    runs = run_skill_evals(skill_dir, args.model, host=args.host, api=args.api)
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
