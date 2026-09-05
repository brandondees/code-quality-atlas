# SPDX-License-Identifier: MIT
# tooling/run_evals.py
"""Run a skill's eval scenarios against a local model.

This is the cross-model eval harness (spec phase-2 §7). It assembles the
progressive-disclosure context a model with the skill loaded would see
(SKILL.md + reference/*.md, excluding the deeper tool-rules.md/sources.md +
examples.md), sends each scenario's query to the model, and prints the
response next to its expected_behavior so a human/judge can grade. Two
backends: the Ollama API (`--api ollama`) and any OpenAI-compatible
/v1/chat/completions server such as llama-server (`--api openai`). Network
calls are isolated in `query_*` so tests mock them (no model server needed
in CI).
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from tooling.evals import load_evals

OLLAMA_HOST = "http://localhost:11434"
OPENAI_HOST = "http://localhost:8080"  # llama-server default

# Named rather than a bare 600 repeated at each of query_ollama/query_openai/
# run_skill_evals's own default and the CLI's --timeout default (#371) --
# one place to widen it for a slow model rather than four literals a future
# edit could update inconsistently.
DEFAULT_TIMEOUT_SECONDS = 600

# Ollama defaults to a 2048-token context and *silently truncates* anything
# longer — which drops the head of the assembled skill context (SKILL.md's
# discipline + Top checks), so the model reviews against a partial prompt and
# the run looks valid while being meaningless. Pin a window with real headroom
# over the largest assembled context. The OpenAI-compatible path sets its
# window server-side (llama-server -c), so this only applies to Ollama.
# Revisit if a skill's assembled context outgrows this — `len(
# assemble_context(skill_dir)) // 4` estimates its tokens; bump well above the
# largest before it can clip.
#
# `num_ctx` is the budget for the prompt *and* the generation, so sizing it
# against the assembled context alone understates it. Measured 2026-09-05
# across all 44 standalone skills: the largest assembled context
# (tracing-correctness-and-invariants) is ~8,971 estimated tokens — already
# past the previous 8,192 ceiling *before any generation*, meaning the head
# truncation this constant exists to prevent was silently happening on that
# skill's evals. 28 of 44 skills exceed half the old window. Separately,
# measured 2026-08-08 on `reviewing-concurrency-and-async`: one scenario that
# had answered in ~800 tokens instead ran away to 7,300+ and crossed the
# ceiling (`truncated = 1` in llama-server's slot log) rather than finishing.
# Both failure modes are deterministic — the same prompt reproduces them. A
# context-window truncation surfaces to the caller only as a request timeout
# (or, worse, a clean-looking partial response — see the stop-reason check in
# query_ollama/query_openai, added for exactly this), which `run_skill_evals`
# records on `ScenarioRun.error` and `main` reports with a non-zero exit, so
# the run is not graded as a miss; what a bare timeout hides is the *cause*,
# which reads as a transport failure rather than as a window too small. The
# server's own `n_decoded` counter (or Ollama's `done_reason`) is what
# distinguishes the two. When editing a lens's `examples.md`, re-check this
# ceiling against prompt + the longest generation the suite provokes, not
# against the prompt alone (#371).
OLLAMA_NUM_CTX = 32768

_REVIEWER_DIRECTIVE = (
    "\n\n---\n\nYou are a code reviewer applying the skill above. Review the "
    "user's code change and report concrete findings (or state there are none). "
    "Be concise."
)


# Excluded from assemble_context's reference/ glob below: both are a
# deliberately *deeper*, on-demand disclosure level per the standalone
# skill's own progressive-disclosure model (SKILL.md's "Going deeper" links),
# not what a model reviewing with the skill loaded sees by default -- the
# same reason a hardcoded "reference/heuristics.md" was wrong for an
# artifact-shaped lens (whose checklist lives in reference/<slug>.md
# instead, #371), rather than a reason to bundle everything in reference/.
_DEEPER_REFERENCE_FILES = {"tool-rules.md", "sources.md"}


def assemble_context(skill_dir: Path) -> str:
    """The content a model with this skill loaded would have available.

    reference/*.md is globbed rather than hardcoded to heuristics.md: an
    artifact-shaped lens (e.g. reviewing-artifact-conventions) has no
    heuristics.md at all -- its checklist lives in one bundled rubric file
    per artifact, reference/<slug>.md -- so the hardcoded path silently
    evaluated it with an empty checklist (#371). Sorted for a deterministic
    prompt across runs. Raises if nothing at all was found to assemble,
    rather than silently sending the model a directive with no skill
    content behind it."""
    parts = [(skill_dir / "SKILL.md").read_text(encoding="utf-8")]
    reference_dir = skill_dir / "reference"
    if reference_dir.is_dir():
        for p in sorted(reference_dir.glob("*.md")):
            if p.name not in _DEEPER_REFERENCE_FILES:
                parts.append(p.read_text(encoding="utf-8"))
    examples = skill_dir / "examples.md"
    if examples.exists():
        parts.append(examples.read_text(encoding="utf-8"))
    if len(parts) < 2:
        raise RuntimeError(
            f"{skill_dir}: assembled context has no checklist content beyond "
            "SKILL.md itself (no reference/*.md, no examples.md) -- refusing "
            "to run evals against a context this thin"
        )
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
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    num_ctx: int = OLLAMA_NUM_CTX,
    think: bool | None = None,
    max_tokens: int | None = None,
) -> str:
    """Ollama /api/chat with sampling pinned and the context window widened so
    the full skill prompt isn't silently truncated (see OLLAMA_NUM_CTX).

    `num_ctx` is overridable per call: thinking-capable models (e.g. qwen3.5)
    spend a large, variable token budget on a `<think>` block before the final
    answer, and the default can leave no room for the answer itself once
    that overhead is added to a real skill-context-sized prompt (observed as an
    empty `content` field, not an error). `think` maps to Ollama's per-request
    `"think"` switch when set; left `None`, the model's own default applies.
    `max_tokens` maps to Ollama's `num_predict` generation cap when set — a
    ceiling on worst-case latency/cost, distinct from num_ctx (the window a
    generation can run away *inside*, #371).

    Raises if the response's `done_reason` is `"length"`: the generation hit
    num_ctx or num_predict and was cut off mid-answer, which is HTTP 200 with
    a syntactically valid but truncated `content` — indistinguishable from a
    genuine short answer by content alone, and would otherwise be graded as
    if the model had actually finished (#371)."""
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
    if max_tokens is not None:
        payload["options"]["num_predict"] = max_tokens
    data = _post_json(f"{host}/api/chat", payload, timeout, "Ollama")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Ollama API error: {data['error']}")
    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        # RuntimeError (not TypeError) is deliberate: consistent with _post_json's
        # failure-wrapping convention, every failure mode in this module wraps into
        # RuntimeError so callers can use a single except clause; tests assert on
        # RuntimeError specifically.
        raise RuntimeError(f"unexpected Ollama response shape: {data!r}")  # noqa: TRY004
    if isinstance(data, dict) and data.get("done_reason") == "length":
        raise RuntimeError(
            "Ollama generation was truncated (done_reason=length) -- the "
            "response was cut off mid-answer by num_ctx or num_predict, not "
            "a genuine complete response; widen num_ctx/--max-tokens rather "
            "than grade this as a real answer"
        )
    return content


def query_openai(
    model: str,
    system: str,
    user: str,
    host: str = OPENAI_HOST,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_tokens: int | None = None,
) -> str:
    """OpenAI-compatible /v1/chat/completions (llama-server, vLLM, ...).

    `max_tokens` caps the generation length, same intent as query_ollama's
    (a worst-case latency/cost ceiling). Raises if `finish_reason` is
    `"length"` -- see query_ollama's docstring for why a truncated
    generation must never be silently graded as a complete answer (#371)."""
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
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
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
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"unexpected OpenAI-compatible response shape: {data!r}"
        ) from e
    if not isinstance(content, str):
        # RuntimeError (not TypeError) is deliberate: see the matching comment in
        # query_ollama above — a single except clause covers every failure mode.
        raise RuntimeError(f"unexpected OpenAI-compatible response shape: {data!r}")  # noqa: TRY004
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        raise RuntimeError(
            "OpenAI-compatible generation was truncated (finish_reason=length) "
            "-- the response was cut off mid-answer, not a genuine complete "
            "response; widen the context window/--max-tokens rather than "
            "grade this as a real answer"
        )
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


def is_no_findings(text: str) -> bool:
    """Whether a scenario response amounts to "no findings", across the
    headline formats models actually use: `**No findings**`, `## No
    findings`, or `No findings:` with the lens's own healthy-scan sentence
    appended. The runbook's own naive baseline (case-sensitive
    `response.startswith("no findings")`) misses all three; a
    case-insensitive `text.lower().startswith("no findings")` catches the
    plain form but still misses the two markdown-prefixed ones.
    docs/runbooks/cross-model-re-gate.md records two re-gates that
    each inflated a reported result because this was retyped by hand instead
    of imported (the second bug: stripping markdown with a regex leaves a
    leading space that breaks `startswith` a second time) -- moved here, with
    tests over the observed formattings, so it stops being retyped.
    """
    return (
        re.sub(r"[*_#\s]+", " ", text.strip())
        .strip()[:60]
        .lower()
        .startswith("no findings")
    )


DEFAULT_HOSTS = {"ollama": OLLAMA_HOST, "openai": OPENAI_HOST}


def run_skill_evals(
    skill_dir: Path,
    model: str,
    host: str | None = None,
    api: str = "ollama",
    num_ctx: int = OLLAMA_NUM_CTX,
    think: bool | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_tokens: int | None = None,
) -> list[ScenarioRun]:
    if api not in DEFAULT_HOSTS:
        # Fail fast on an unrecognized api regardless of whether host is also
        # passed explicitly — `host or DEFAULT_HOSTS[api]` alone would skip this
        # check whenever host is truthy, silently misrouting to the else branch.
        raise ValueError(
            f"unknown api: {api!r} (expected one of {sorted(DEFAULT_HOSTS)})"
        )
    if api != "ollama" and think is not None:
        # num_ctx has its own OpenAI-compatible meaning (the server sets its
        # window at startup, `-c`), so silently accepting it there wouldn't be
        # wrong so much as a no-op -- but `think` has no OpenAI-compatible
        # equivalent at all, and silently dropping it previously left an
        # operator believing they'd forced thinking on/off when nothing was
        # sent (#371).
        raise ValueError(
            f"--think/--no-think is ollama-only, not valid with api={api!r}"
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
                    max_tokens=max_tokens,
                )
            else:
                response = query_openai(
                    model,
                    system,
                    s["query"],
                    host=host,
                    timeout=timeout,
                    max_tokens=max_tokens,
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
        default=None,
        help="Ollama context window (ollama only); widen for "
        "thinking-capable models, whose reasoning overhead "
        "can otherwise leave no room for the final answer "
        f"(default: {OLLAMA_NUM_CTX})",
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
        default=DEFAULT_TIMEOUT_SECONDS,
        help="per-scenario request timeout in seconds; widen for "
        "thinking-mode models under a large num_ctx",
    )
    ap.add_argument(
        "--max-tokens",
        type=_positive_int,
        default=None,
        help="generation cap (Ollama's num_predict / OpenAI-compatible's "
        "max_tokens) -- a worst-case latency/cost ceiling, distinct from "
        "--num-ctx (the window a generation can run away inside). A "
        "generation cut off by either is treated as a hard failure, never "
        "graded as a real answer",
    )
    args = ap.parse_args(argv)

    if args.api != "ollama" and args.num_ctx is not None:
        # An explicit `None` default (like --think's) distinguishes "the
        # user passed --num-ctx" from "the untouched default applies" --
        # a concrete int default here would silently accept
        # `--num-ctx <the current OLLAMA_NUM_CTX value>` as if it were the
        # untouched default, defeating this very check for the one value
        # that value happens to coincide with (round-1 review finding).
        # OLLAMA_NUM_CTX has no OpenAI-compatible equivalent request field at
        # all (that server sets its window at startup via -c), so silently
        # accepting an override here would leave an operator believing
        # they'd widened the window when nothing was sent (#371).
        ap.error("--num-ctx is ollama-only, not valid with --api openai")
    num_ctx = OLLAMA_NUM_CTX if args.num_ctx is None else args.num_ctx

    skill_dir = Path(args.skills_root, args.skill)
    runs = run_skill_evals(
        skill_dir,
        args.model,
        host=args.host,
        api=args.api,
        num_ctx=num_ctx,
        think=args.think,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
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
