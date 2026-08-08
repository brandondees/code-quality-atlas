# Runbook — cross-model eval re-gate

How to stand up a local-model substrate and run a hardened Q21 eval suite against
it. Written 2026-08-08, after the campaign's first re-gate performed inside a
remote cloud session — every prior entry deferred this step with "no Ollama or
local-model substrate in this session," which turned out to be a setup gap
rather than an environment limitation.

## Why this exists

A hardened suite ([Q21](../open-questions.md)) is only as meaningful as the bar
it is measured against. The suites are authored against a strong model and then
re-gated against the **floor of record** — the weakest model the suite is
expected to be useful on. Without the re-gate, `eval_min: 26` asserts that 26
scenarios exist, not that any of them discriminate.

## Setup (remote container, CPU-only)

```sh
apt-get install -y zstd                       # the installer needs it to extract
curl -fsSL https://ollama.com/install.sh | sh # warns about systemd; harmless
OLLAMA_MAX_LOADED_MODELS=1 ollama serve &     # see the OOM note below
ollama pull qwen2.5-coder:7b                  # the floor of record
```

**`OLLAMA_MAX_LOADED_MODELS=1` is not optional on a memory-constrained host.**
Ollama keeps a model resident for 5 minutes after its last request, so starting
a second model's run inside that window loads both at once. On a 15.7 GiB host,
loading a 9 GB model while a 4.7 GB one is still resident gets the new
`llama-server` OOM-killed, and the API returns HTTP 500 per request until the
first model ages out:

```text
Load failed ... error="llama-server process has terminated: signal: killed"
```

Observed 2026-08-08: 15 of 24 scenarios failed this way before the remaining 9
ran normally.

## Running a suite

```sh
python -m tooling.run_evals --skill reviewing-concurrency-and-async \
    --model qwen2.5-coder:7b
```

Useful flags: `--num-ctx` (widen for thinking-capable models), `--think` /
`--no-think`, `--timeout`. For a thinking-mode model, read the `qwen3.5:4b`
findings in [`../open-questions.md`](../open-questions.md) first — the campaign
has twice measured non-convergence rather than a context-size problem.

**Check the exit code.** `run_evals` exits non-zero when any scenario's request
failed, and prints which ones. A failed scenario has an empty response, which is
byte-identical to a model that answered nothing — grading a partial run scores
dead scenarios as "no findings" misses and reports a broken run as a bad model.

Expect roughly 10-30 minutes per 24-scenario suite on 4 CPU cores, dominated by
how much the model chooses to write rather than by its size.

## Grading

Score each scenario against its `expected_behavior`, and **report recall and
precision separately** rather than one total:

- **recall** — of the scenarios that plant a defect, how many did the model find?
- **precision** — of the scenarios whose code is correct (the E-group), how many
  did it correctly leave alone?

A single total hides the distinction, and the distinction is the whole result. In
the 2026-08-08 four-model comparison, `gemma3:4b` tied the floor model's 10/24
while scoring 10/20 recall and **0/4** precision: 15 of its 24 responses opened
with the same canned "check-then-act across an await" finding regardless of the
code under review. A model that emits one defect class constantly earns real
recall on any suite where that class is common, and is worthless as a reviewer.
Precision on the clean scenarios is what separates a reviewer from a stopped
clock — which is the strongest argument for keeping E-group scenarios in every
hardened suite.

Also worth recording, because they do not show up in a score:

- **self-contradiction** — a verdict of "No findings" followed by prose
  describing the defect (`qwen3.5:4b`, scenario 1).
- **non-convergence** — a response that argues with itself until the context
  runs out (`qwen3.5:4b`, scenario 11: 861s, 21,481 characters, trailing off
  mid-sentence).
- **claim capture** — accepting an in-diff assertion as evidence. `gemma3:4b` on
  the sycophancy scenario echoed "verified under production-scale load" back and
  invented a justification for it, crediting "Redis atomic increment" for code
  that plainly does `GET` then `SET`.

## The harness is deterministic — deltas are signal

Verified 2026-08-08: two runs of the same suite, same model, same prompt
produced **byte-identical responses on all 24 scenarios**. Sampling is pinned
(`temperature: 0`), and it holds end to end. So a difference between two runs is
caused by whatever you changed, and a single run is enough to measure a tuning
delta — you do not need repeats to average out noise, because there is none.

The corollary is less comfortable: because every difference is real, an
`examples.md` edit aimed at one behavior **will** flip unrelated scenarios, and
you will not find out unless you look. In the 2026-08-08 tuning attempt, adding
a guard-check step to the concurrency lens's decision rule newly cleared the
*lock-ordering deadlock* scenario on the floor model — a false negative created
by prose written to reduce false positives — and a narrower version of the same
edit instead lost the seat-reservation scenario while recovering lock ordering.

**So: after editing any lens's `examples.md`, re-run its whole suite against the
floor model, not just the scenario you were aiming at.** A spot check on the
target scenario cannot see the collateral damage, and the collateral damage is
where the recall goes.

## Watch the generation budget, not just the prompt

`OLLAMA_NUM_CTX` covers prompt **and** generation. Growing an `examples.md` eats
the generation half. Measured in the same session: +766 prompt tokens took one
scenario from an ~800-token answer to a 7,300+-token runaway that crossed the
ceiling (`truncated = 1` in llama-server's slot log) instead of finishing.

It reaches the harness as a **request timeout**, so a re-gate records it as a
failed scenario and — before the exit-code guard existed — would have graded it
as a miss. If a scenario that used to answer starts timing out after a prompt
edit, check `n_decoded` in the server log before blaming the machine: a runaway
generation and a slow host look identical from the client side.
