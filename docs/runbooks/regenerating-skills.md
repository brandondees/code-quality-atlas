# Runbook — Regenerating skills after a docs change

The taxonomy + `docs/research/cluster-*.md` are the source of truth. Skills are
derived. After you critique/improve a research section, flow it into the skills:

1. **See what's affected:** `python -m tooling.cli drift`
   Lists every skill whose source sections changed (by `#n`).
2. **Regenerate:** `python -m tooling.cli generate`
   Rebuilds each skill's `SKILL.md` + `reference/*` from current docs and
   re-stamps provenance hashes. `examples.md` and `evals/eval.json` are NOT
   overwritten (hand-refined content is preserved).
3. **Re-validate evals:** for each affected skill, re-run its `evals/eval.json`
   scenarios against your model tiers (see the skill's evals). Fix regressions
   by tightening `reference/heuristics.md` (via the docs) or `examples.md`.
4. **Confirm sync:** `python -m tooling.cli drift` → "No drift".
5. **Commit** the regenerated skills with the docs change.

Adapting granularity later: edit `skills/manifest.yaml` (merge/split skills or
re-map `built_from` categories), then run steps 2–4. No research edits needed.

## Cross-model evals (the portability gate, D7/D8)

Validate eval *structure* (≥3 scenarios) for one or all skills:

```
python -m tooling.cli eval                 # all skills
python -m tooling.cli eval --skill <name>  # one skill
```

Run a skill's scenarios against a local model via Ollama and read the responses
next to their `expected_behavior` (the harness assembles the same context a
model with the skill loaded would see: SKILL.md + reference/heuristics.md +
examples.md):

```
python -m tooling.run_evals --skill <name> --model llama3.2:3b
```

**No Ollama available?** (e.g. a sandboxed cloud session): any OpenAI-compatible
server works via `--api openai`. The lightest path is llama.cpp's `llama-server`
with a GGUF from Hugging Face — no install, just a prebuilt binary:

```
curl -sLO https://github.com/ggml-org/llama.cpp/releases/download/<tag>/llama-<tag>-bin-ubuntu-x64.tar.gz
tar xzf llama-<tag>-bin-ubuntu-x64.tar.gz
curl -sLO https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf
./llama-<tag>/llama-server -m qwen2.5-coder-7b-instruct-q4_k_m.gguf -c 16384 --port 8080 &
python -m tooling.run_evals --skill <name> --model qwen2.5-coder-7b --api openai
```

Verify what you downloaded before running it: check the binary against the
checksum/digest on the llama.cpp release page (`gh release view <tag>` or the
asset's `digest` in the releases API) and the GGUF against the SHA256 shown on
its Hugging Face file page — these are unsigned third-party artifacts.

CPU-only inference is slow (~5 tok/s on 4 cores for a 7B Q4) but fine for
eval-scenario volumes; `llama-server` caches the shared system prefix across a
skill's scenarios.

Grade each response against `expected_behavior`. Skills must be tested on at
least two tiers (a strong model and a small/local one). Known failure mode on
small models: **over-flagging clean code** (inventing issues on the "good"
scenario). Fix by strengthening that skill's `examples.md` (good→no-finding
pairs carry the most weight for weak models) and/or adding an explicit
"don't invent issues; report no finding when the code is correct" guard.

**Tuning lessons (from `hunting-silent-failures` on `llama3.2:3b`, 3B):**
- The suite-wide "Reviewer discipline" guard (in every generated `SKILL.md`) must be
  **recall-safe**: a blanket "prefer reporting nothing over a false positive" made the
  3B model under-report on a genuinely bad case. Keep "report no findings when the code
  is correct, *but still report every genuine issue with full detail*."
- Targeted `examples.md` good-to-no-finding pairs reliably kill **specific** false-positive
  classes (e.g. "don't recommend broadening a narrow `except`").
- **Model-capability ceiling:** a 3B model misreads control flow (e.g. that an early
  `return` prevents a later line) even when an example states it explicitly — prompt
  tuning can't close this. Treat **~7-8B as the practical floor** for *clean-code
  precision* (no-finding reliability); below that, detection still works but expect
  over-flagging on correct code. For high-stakes correctness, pair the skill with a
  deterministic check rather than trusting a tiny model's "no findings".

**Tuning lessons (from the full 6-skill pass on `qwen2.5-coder-7b` Q4, llama-server):**
- The 7-8B floor holds: the clean-code scenario that broke the 3B passes here, and
  most skills pass all scenarios outright. Repo-shaped scans are the exception (below).
- **"What should we act on?" invites invention.** On a healthy repo-scan table the
  model recommended refactoring the biggest *healthy* file. Targeted fix that worked:
  an explicit **decision rule** in `examples.md` ("a maximum is not a finding"; rough
  numeric bounds for when factors compound into a hotspot) plus the exact no-finding
  sentence to emit. Repo-shaped skills need decision rules, not just example pairs.
- **Pin sampling.** The eval harness sends `temperature: 0`; before that, llama-server's
  default (0.8) made scenario results flip between runs — one run flagged 3/3 expected
  findings, the next found 1/3 on the same input. Never grade an unpinned run.
- **Remaining 7B-class gap: secondary findings get dropped.** The model reports the
  primary one-or-two findings and stops. Two flavors seen, both stable at temp 0 and
  both resistant to example-prose tuning: (a) findings that need data-flow reasoning
  ("this module-level cache is shared mutable state across users"); (b) the third
  independent finding in a multi-issue diff (caught the comment/code contradiction
  and the commented-out code, never the mechanism-encoding name). Same family as the
  3B control-flow ceiling, one level up. Known gap; don't chase it with more prose —
  expect ~"top findings only" recall from 7B-class models and pair with linters for
  exhaustiveness.
- Weak models **mimic the examples' output format** (echoing "**Expected finding:**"
  as a literal prefix). Cosmetic, but means `examples.md` is effectively the output
  template — keep its finding prose in exactly the shape you want responses to take.

**Tuning lessons (wave 2, same model):**
- **Numbered findings lists are the single highest-leverage example format.** With
  flowing-paragraph examples the model reported 1 of 3–4 findings in multi-issue
  diffs; rewriting the examples' expected findings as numbered lists lifted recall
  immediately (migration rename scenario went 1/3 → 3/3, test-quality went 1/4 →
  3/4). Since examples are the output template, a list template forces enumeration.
- **The cold-path decision rule transfers.** Performance initially "optimized" a
  weekly cron loop; an explicit decision rule (hot-path required before flagging,
  exact no-finding sentence) fixed it — same playbook as the hotspots fix.
- **7B ceiling, new instance: DDL keyword blindness.** Migration safety pattern-
  matches `ALTER TABLE ... ADD` and emits the memorized "NOT NULL with no default"
  finding even when the diff adds a *nullable* column with a `NOT VALID` constraint
  (the safe expand step) — three runs, three identical misfires, immune to an
  explicit "quote the keyword or the finding is invented" rule. Same family:
  pattern-match beats reading. For migration safety, treat the 7B tier as
  detection-only and pair with a deterministic linter (squawk, strong_migrations)
  for the safe/unsafe-variant distinction.
- **Multi-sink tracking is part of the dropped-findings gap:** one untrusted value
  flowing to two sinks (shell + filesystem) yields only the first sink's finding;
  security sweeps on small models need a deterministic scanner (semgrep/bandit)
  alongside for exhaustiveness.

**Tuning lessons (wave 3 + wave-1 retrofit, same model):**
- **The numbered-list template can backfire on clean code.** Retrofitting wave-1
  examples to numbered lists left bad-case recall unchanged but made two skills
  start *filling in* numbered findings on correct code (inventing issues to have a
  list). Counter-tune that fixed it: every preamble now ends with — when the input
  is correct, the entire response is exactly "No findings"; never produce a
  numbered list for correct code. Ship the template and the escape hatch together.
- **Scan-table hallucination:** given a dependency table with an empty `cves`
  column, the model invented a CVE and a fix version. Repo-shaped decision rules
  must say "cite only signals present in the scan" explicitly — for audit skills
  the input table is the whole evidence base, and weak models will pad it.
- **Range-arithmetic ceiling:** `range(len(x) - n, len(x))` going negative when
  `n > len(x)` produced a confidently wrong off-by-one diagnosis — same family as
  the 3B control-flow ceiling. For tracing-correctness on small models, pair with
  property-based tests rather than trusting the diagnosis.
- The repo-shaped audits otherwise transferred well: with decision rules + exact
  no-finding sentences in place from the start, all five passed their healthy-scan
  scenarios on the first run.
