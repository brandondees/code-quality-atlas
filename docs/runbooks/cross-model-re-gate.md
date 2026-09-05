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

**Send a throwaway warm-up request before every run, not just after a cold
restart.** Observed across multiple sessions (most recently 2026-08-15, see
[`../session-log.md`](../session-log.md)) — scenario 1 of an otherwise-clean
run fails with `HTTP Error 500: Internal Server Error`, every other scenario
in the same run succeeds. Timed it directly on the 2026-08-15 occurrence: a
trivial one-word chat request took **17.9s** on a freshly `ollama serve`d
host — that's the model loading into memory, not answering — and the
harness's real first request, competing with that load time plus its own
generation time, is what trips. A no-op request first absorbs the load
time on its own:

```sh
curl -s http://127.0.0.1:11434/api/chat -d \
  '{"model":"qwen2.5-coder:7b","messages":[{"role":"user","content":"hi"}],"stream":false}' \
  > /dev/null
```

Cheap enough to run unconditionally before every suite, whether or not
Ollama was just (re)started — no observed downside, and it has fully
prevented the scenario-1 failure every time it's been tried.

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

Verified 2026-08-08 on one configuration — `qwen2.5-coder:7b` via Ollama,
CPU-only, `temperature: 0`, `num_ctx` 8192 — two runs of the same suite, same
model, same prompt produced **byte-identical responses on all 24 scenarios**.
No run-to-run variance appeared there, so on that substrate a difference between
two runs is caused by whatever you changed, and one run is enough to measure a
tuning delta. Re-check this if you change backend, accelerator, batching, or
sampling: the guarantee is a property of the configuration, not of the harness.

The corollary is less comfortable: with no observed noise to absorb it, an
`examples.md` edit aimed at one behavior **can** flip unrelated scenarios, and
did twice in the 2026-08-08 tuning attempt. Adding
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

## Two grading traps, both fallen into

**Counting "did it fire" is not grading.** A firing counter is cheap and it is the
same metric that rates a model which flags everything as perfect recall — the
exact failure `gemma3:4b` demonstrates. On 2026-08-09 a "Be concise" experiment
was reported as a strict improvement on the strength of a firing count (config
11/24 → 15/24, no losses); reading the five newly-firing responses showed two
correct findings, one self-contradictory, one naming the wrong defect, and one
echoing the input diff back. **Read the responses before claiming a delta.** The
counter tells you where to look, not what you found.

**Detect "no findings" through markdown, and anchor it.** Models format the
verdict as `**No findings**`, `## No findings`, or `No findings:` with the
lens's own healthy-scan sentence appended. A naive
`response.startswith("no findings")` misses all three, and stripping markdown
with `re.sub(r'[*_#\s]+', ' ', t)` leaves a **leading space** that breaks
`startswith` a second time. Both bugs occurred in one session and each
inflated a reported result — each time because this check was retyped by hand
for that re-gate rather than imported. It now lives in
`tooling/run_evals.is_no_findings`, with unit tests over the three headline
formats above and both historical bugs (`tests/test_run_evals.py`) — import
it for a re-gate instead of retyping it again (issue #395).

## What the models can and cannot do (2026-08-09, seven models)

Across four vendors and five architectures, firing rate and false convictions
move together monotonically — but the two strongest models are correct on
93-100% of the defect scenarios they fire on, so this is not mere
trigger-happiness. The specific deficit is **guard recognition**: they identify
the risky *pattern* (read-then-write, check-then-act) and cannot evaluate
whether a conditional update, a lock spanning the critical section, or a
documented tolerance already neutralises it.

Two consequences for anyone tuning a lens here:

- **Shared prose has not supplied it.** Three rewrites aimed at guard
  recognition (a three-guard check, a narrowed version of it, then an
  operational not-applicable rule) were each measured and each failed; two were
  reverted. That is evidence about the rewrites tested, not proof that no
  phrasing works — but it is enough to stop reaching for prose first. The
  untested alternative is a lens-local worked example carrying the exact
  response, which is what the canned healthy-scan sentence appears to be doing
  when it survives a rule written to override it.
- **"Floor of record" is a point on a curve, not a model.** A team wanting no
  false convictions picks the low-firing end and finds a third of the defects; a
  team wanting coverage picks the high-firing end and audits the findings. State
  which end a re-gate is measuring against.

## The untested alternative worked, once the gap was a literal string match (2026-08-15)

The "shared prose has not supplied it" finding above was about **guard
recognition** — a fuzzy judgment call (is this check-then-act already
neutralized?) that three rewrites of shared prose failed to move. The
not-applicable-vs-"No findings" gap (six lenses failing it as of 2026-08-15)
turned out to be a different kind of problem: every lens's `examples.md`
already contains a literal, quoted canned sentence for the clean case
("Report exactly \"No findings: ...\""), and the model reproduces it
verbatim on out-of-scope input too — not because it can't tell the two
cases apart, but because only one of them had a concrete string to lock
onto. The generated `Reviewer discipline` rule already told it to say
something else; the rule was losing to the literal example every time.

Fix tested on three lenses (`reviewing-install-and-upgrade-experience`,
`checking-idioms-and-consistency`, `auditing-compliance-and-provenance`,
spanning both `diff` and `repo` shapes): added a **second literal quoted
sentence** — a `"Not applicable: ..."` worked example — so the model has an
equally concrete string for the other case. Full re-gate (not a spot check)
against `qwen2.5-coder:7b` on all three: **all three target scenarios
flipped from miss to hit**, reproducing the new sentence verbatim, plus two
bonus flips on an unrelated axis (the same-day exemption-claim-vs-
correctness-claim hypothesis — a false "skip this check" comment stopped
working on two scenarios it previously fooled). Aggregate across the three
suites: recall 34/52 → 39/52 (65%→75%), precision 14/19 → 15/19 (74%→79%).

**It also produced real collateral damage, in both directions being
possible at once.** Two scenarios flipped the other way: a no-established-
formatter restraint scenario that used to correctly say "No findings" now
invents a formatting complaint, and a correctly-guarded idempotent script
that used to be recognized as clean now gets a fabricated "not idempotent"
finding that directly contradicts the guard visible in the same prompt. Both
regressions happened on scenarios untouched by the edit's target — this is
the collateral-damage rule earlier in this document, now with a concrete
worked example of it happening even on a fix that clearly worked in
aggregate. **Always re-run the whole suite, and read the diff, not just the
target scenario's before/after.**

The generalizable lesson: **when the gap is "the model has one canned
string and not the other," give it the second string** — this is a cheaper,
more mechanical intervention than the guard-recognition rewrites, and it
worked on the first attempt where three fuzzy-judgment rewrites had failed.
It is not evidence that *every* prose gap is fixable this way — guard
recognition is still unmoved — but it is worth checking whether a given gap
has this literal-string shape before concluding a lens has hit a ceiling.

## Two follow-up fix attempts on the two regressions above: one inert, one actively harmful (2026-08-15)

Tried closing the two regressions from the section above, each with a new
worked example targeting the specific restraint case that broke, following
the same recipe that worked for the not-applicable gap.

**`checking-idioms-and-consistency` scenario 12** (invents a formatting
complaint on a codebase with no established formatter): added a "no
established convention" worked example, different language and axis
(Ruby, mixed naming/hash-key/conditional style) than the eval scenario
(JS, mixed indentation/quotes/`var`/`const`). Full re-gate: **no effect** —
scenario 12 still invents findings, now via a different hallucinated claim
(a comparison operator that doesn't appear anywhere in the code, plus a
false claim that "the project's linter enforces" a rule on a codebase the
scenario explicitly states has no linter). No other scenario changed grade.
Kept the new example anyway — it's still correct, useful content for the
restraint case it teaches, just not one this eval scenario happens to
exercise. This gap looks more like guard recognition (a judgment call) than
the not-applicable gap (a literal string) — worth trying a genuinely
different intervention shape before concluding it's a ceiling, not another
worked example in the same style.

**`reviewing-install-and-upgrade-experience` scenario 26** (fabricates an
"unguarded" finding on a script that's visibly guarded): added a worked
example of a different, already-idempotent script. Result: **not inert,
actively harmful.** The new example is thematically close to scenario 10 —
an *existing*, previously-correctly-graded scenario about an *unguarded*
init script — and the combination sent the model into a non-terminating
generation on scenario 10 specifically. Reproduced four times: twice as a
mid-suite transport failure, then isolated the exact request via direct
curl outside the harness and watched `n_decoded` climb past 2,400 tokens
and trigger a context-shift discard before being killed — a genuine runaway,
not a hang, exactly the "watch the generation budget" failure mode from
earlier in this document, now caused by an *unrelated* scenario's added
example rather than the target scenario's own growth. **Reverted the
addition entirely** (not just trimmed) — confirmed scenario 10 returns to
its normal 5-point response with the revert, verified via a full clean
re-gate with zero transport failures. Scenario 26 remains broken, exactly
as it was.

**The added lesson: a new worked example's risk isn't only "does it move the
target scenario" or "does it flip an unrelated scenario's verdict" — it can
also destabilize an unrelated scenario's *generation* outright if the two
are thematically close enough. A full re-gate catches this (a transport
failure is impossible to miss), but it's worth knowing this failure mode
exists before adding content near a lens's existing scenario themes,** not
just far from them token-budget-wise.
