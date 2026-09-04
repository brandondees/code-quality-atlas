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

import argparse
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
# reason.) Revisit if a skill's assembled context outgrows this — `len(
# assemble_context(skill_dir)) // 4` estimates its tokens; bump well above the
# largest before it can clip.
#
# `num_ctx` is the budget for the prompt *and* the generation, so sizing it
# against the assembled context alone understates it. Measured 2026-08-08 on
# `reviewing-concurrency-and-async`: adding ~766 tokens to `examples.md` took
# the assembled context from ~3.2k to ~4.0k, and one scenario that had answered
# in ~800 tokens instead ran away to 7,300+ and crossed the ceiling
# (`truncated = 1` in llama-server's slot log) rather than finishing. The
# failure is deterministic — the same prompt reproduces it. It surfaces to the
# caller only as a request timeout, which `run_skill_evals` records on
# `ScenarioRun.error` and `main` reports with a non-zero exit, so the run is not
# graded as a miss; what the timeout hides is the *cause*, which reads as a
# transport failure rather than as a window too small for the generation. The
# server's own `n_decoded` counter is what distinguishes the two. When editing a
# lens's `examples.md`, re-check this ceiling against prompt + the longest
# generation the suite provokes, not against the prompt alone.
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


def query_ollama(
    model: str,
    system: str,
    user: str,
    host: str = OLLAMA_HOST,
    timeout: int = 600,
    num_ctx: int = OLLAMA_NUM_CTX,
    think: bool | None = None,
) -> str:
    """Ollama /api/chat with sampling pinned and the context window widened so
    the full skill prompt isn't silently truncated (see OLLAMA_NUM_CTX).

    `num_ctx` is overridable per call: thinking-capable models (e.g. qwen3.5)
    spend a large, variable token budget on a `<think>` block before the final
    answer, and the default 8192 can leave no room for the answer itself once
    that overhead is added to a real skill-context-sized prompt (observed as an
    empty `content` field, not an error). `think` maps to Ollama's per-request
    `"think"` switch when set; left `None`, the model's own default applies."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # evals must be reproducible — never inherit a server's sampling default;
        # num_ctx must fit the whole skill context (+ thinking, if enabled) or
        # Ollama silently truncates it.
        "options": {"temperature": 0, "num_ctx": num_ctx},
    }
    if think is not None:
        payload["think"] = think
    data = _post_json(f"{host}/api/chat", payload, timeout, "Ollama")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Ollama API error: {data['error']}")
    content = data.get("message", {}).get("content") if isinstance(data, dict) else None
    if not isinstance(content, str):
        # RuntimeError (not TypeError) is deliberate: consistent with _post_json's
        # failure-wrapping convention, every failure mode in this module wraps into
        # RuntimeError so callers can use a single except clause; tests assert on
        # RuntimeError specifically.
        raise RuntimeError(f"unexpected Ollama response shape: {data!r}")  # noqa: TRY004
    return content


def query_openai(
    model: str, system: str, user: str, host: str = OPENAI_HOST, timeout: int = 600
) -> str:
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
    data = _post_json(
        f"{host}/v1/chat/completions", payload, timeout, "OpenAI-compatible"
    )
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
            f"unexpected OpenAI-compatible response shape: {data!r}"
        ) from e
    if not isinstance(content, str):
        # RuntimeError (not TypeError) is deliberate: see the matching comment in
        # query_ollama above — a single except clause covers every failure mode.
        raise RuntimeError(f"unexpected OpenAI-compatible response shape: {data!r}")  # noqa: TRY004
    return content


@dataclass
class ScenarioRun:
    query: str
    expected_behavior: list[str]
    response: str
    # Set when this scenario's request failed. A failed scenario has an empty
    # `response`, which is indistinguishable by content from a model that
    # genuinely answered "nothing here" — and grading it as a miss makes a
    # broken run look like a bad model. Observed 2026-08-08: 15 of 24 scenarios
    # returned HTTP 500 (`llama-server ... signal: killed`, the loaded model
    # OOM-killed while a second one loaded) and would have scored as 15 silent
    # misses. Callers must check this field before grading.
    error: str | None = None


DEFAULT_HOSTS = {"ollama": OLLAMA_HOST, "openai": OPENAI_HOST}


def run_skill_evals(
    skill_dir: Path,
    model: str,
    host: str | None = None,
    api: str = "ollama",
    num_ctx: int = OLLAMA_NUM_CTX,
    think: bool | None = None,
    timeout: int = 600,
) -> list[ScenarioRun]:
    if api not in DEFAULT_HOSTS:
        # Fail fast on an unrecognized api regardless of whether host is also
        # passed explicitly — `host or DEFAULT_HOSTS[api]` alone would skip this
        # check whenever host is truthy, silently misrouting to the else branch.
        raise ValueError(
            f"unknown api: {api!r} (expected one of {sorted(DEFAULT_HOSTS)})"
        )
    host = host or DEFAULT_HOSTS[api]
    system = assemble_context(skill_dir) + _REVIEWER_DIRECTIVE
    doc = load_evals(str(skill_dir / "evals" / "eval.json"))
    runs: list[ScenarioRun] = []
    for s in doc.scenarios:
        # One scenario's failure must not abort the suite: a re-gate is 20+
        # slow requests, and losing the completed ones to a single transient
        # (or to one scenario that hangs) is what made the 2026-07-27 run fall
        # back to a per-scenario diagnostic script. Record and continue; `main`
        # reports the failures and exits non-zero so a degraded run is never
        # mistaken for a complete one.
        try:
            if api == "ollama":
                response = query_ollama(
                    model,
                    system,
                    s["query"],
                    host=host,
                    num_ctx=num_ctx,
                    think=think,
                    timeout=timeout,
                )
            else:
                response = query_openai(
                    model, system, s["query"], host=host, timeout=timeout
                )
            error = None
        except RuntimeError as exc:
            # `str(RuntimeError())` is "" — fall back to repr so the operator
            # always gets something printable naming what failed.
            response, error = "", str(exc) or repr(exc)
        runs.append(ScenarioRun(s["query"], s["expected_behavior"], response, error))
    return runs


def _positive_int(value: str) -> int:
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run-evals")
    ap.add_argument("--skill", required=True)
    ap.add_argument("--skills-root", default="skills")
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--api", choices=["ollama", "openai"], default="ollama")
    ap.add_argument(
        "--host", default=None, help="defaults to the chosen api's local port"
    )
    ap.add_argument(
        "--num-ctx",
        type=_positive_int,
        default=OLLAMA_NUM_CTX,
        help="Ollama context window (ollama only); widen for "
        "thinking-capable models, whose reasoning overhead "
        "can otherwise leave no room for the final answer",
    )
    think_group = ap.add_mutually_exclusive_group()
    think_group.add_argument(
        "--think",
        dest="think",
        action="store_const",
        const=True,
        default=None,
        help="force thinking mode on (ollama only)",
    )
    think_group.add_argument(
        "--no-think",
        dest="think",
        action="store_const",
        const=False,
        help="force thinking mode off (ollama only)",
    )
    ap.add_argument(
        "--timeout",
        type=_positive_int,
        default=600,
        help="per-scenario request timeout in seconds; widen for "
        "thinking-mode models under a large num_ctx",
    )
    args = ap.parse_args(argv)

    skill_dir = Path(args.skills_root, args.skill)
    runs = run_skill_evals(
        skill_dir,
        args.model,
        host=args.host,
        api=args.api,
        num_ctx=args.num_ctx,
        think=args.think,
        timeout=args.timeout,
    )
    for i, r in enumerate(runs, 1):
        print(f"\n{'=' * 72}\nSCENARIO {i}")
        print(f"QUERY:\n{r.query}\n")
        if r.error is not None:
            print(f"--- {args.model} REQUEST FAILED ---\n{r.error}\n")
        else:
            print(f"--- {args.model} RESPONSE ---\n{r.response}\n")
        print("EXPECTED BEHAVIOR:")
        for b in r.expected_behavior:
            print(f"  - {b}")

    # `is not None`, not truthiness: `error` is the presence flag, and an
    # empty-message exception would make a failed scenario read as a clean
    # one — the exact silent-failure this guard exists to prevent.
    failed = [i for i, r in enumerate(runs, 1) if r.error is not None]
    if failed:
        # Non-zero so a partial run can't be graded as if it were complete —
        # the failed scenarios' empty responses look exactly like "no findings".
        print(f"\n{len(failed)}/{len(runs)} scenarios FAILED to run: {failed}")
        print("This run is incomplete — do not grade it as a model result.")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
