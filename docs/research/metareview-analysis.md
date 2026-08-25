# Research — metareview: an open-source, agent-native review harness

> Not a taxonomy cluster (#1–#37) and not a commercial-product pass like
> [`competitor-landscape.md`](competitor-landscape.md) — a **fourth kind of prior art**: an
> open-source, agent-orchestrated review *harness* (state machine, evidence receipts, persistent
> Markdown/JSONL learning) rather than a checklist of findings to mine or a SaaS product to
> benchmark against. Subject: [dsifry/metareview](https://github.com/dsifry/metareview), MIT.
> Generated 2026-08-24 by cloning the repo at commit `f0a389671b4f38113bad3ebecebd1113516a53c5`
> (package.json reports version `0.7.0`; the shipped README documents the 0.6.0 release) and
> reading primary source directly — README, rubrics, `internal/` package layout, and the
> project's own dogfooded review/learning artifacts under `docs/metareview/` — rather than
> summarizing rendered GitHub pages. All claims below are traceable to a specific file in that
> checkout. Feeds [`../map-gaps.md`](../map-gaps.md) G36. Time-sensitive: this is a fast-moving
> pre-1.0 project; re-verify before citing externally.

## Why this exists

[`prior-art.md`](../prior-art.md) mines lightweight agent skills/plugins and classic
static-analysis tools. [`competitor-landscape.md`](competitor-landscape.md) benchmarks the
suite's architecture against hosted SaaS reviewers (CodeRabbit, Copilot code review, Greptile).
metareview is neither: it is an **unhosted, git-native CLI + Claude Code/Codex plugin** that
implements a full review *lifecycle* — spec → plan → task → epic → PR → post-merge — as a chain
of deterministic gates with typed outcomes, JSON evidence receipts, and a persistent
accept/discard learning loop. It is the closest thing found so far to a second implementation of
"agent review harness" with real, inspectable runtime output (not just a design doc), which makes
it worth reading for mechanism even where the suite's own architecture (stateless Claude Code
skills invoked per PR, no CLI, no persistent state) differs on purpose.

## Coverage note (be honest about what this pass did and didn't confirm)

This pass read the actual repository content: `README.md`, `CLAUDE.md`/`AGENTS.md`, all six files
under `rubrics/`, the `skills/` and `commands/` directory listings, and — most valuable —
metareview's **own dogfooded output** under `docs/metareview/{reviews,learning,context}/`, which
are real `metareview review pr-ready` / `learn --post-merge` runs against metareview's own PRs, not
documentation examples. It did **not** build or run the Go binary, did not read `internal/`
package source beyond directory names, and did not clone or verify
[metaswarm](https://github.com/dsifry/metaswarm) (the sibling orchestration project metareview's
docs describe as its intended companion, and which its security rubric says one rubric was mined
from) — claims about metaswarm below are metareview's own stated description of it, not
independently verified against metaswarm's source.

---

## Architecture

### A five-state gate lifecycle, not a single review pass

metareview treats "review" as a chain of five distinct decision points, each with its own rubric
file. Each **lifecycle gate** returns one of four normalized verdicts (`README.md`, "Lifecycle gate
results have a small operating contract"):

| Gate | Command | Rubric | Decision it gates |
|---|---|---|---|
| `artifact` | `metareview review artifact <path>` | `artifact-review-rubric.md` | Is a spec/plan/design good enough to start implementation from? |
| `task-done` | `metareview review task-done <id> --base <ref> --evidence <file>` | `task-done-review-rubric.md` | Is one local, task-sized code change actually done? |
| `epic-ready` | `metareview review epic-ready <id> --base <ref> --evidence <file>` | `epic-ready-review-rubric.md` | Are all child tasks complete and is the parent ready to land? |
| `pr-ready` | `metareview review pr-ready --base <ref> --evidence <file>` | `pr-ready-review-rubric.md` | Is the branch ready to push / open as a PR / merge? |
| `learn --post-merge` | `metareview learn --post-merge <pr> --base <pre-merge-ref>` | `learning-review-rubric.md` | What should be kept as durable knowledge now that the PR is merged? |

Verdicts are fixed and machine-actionable, not prose (`README.md`):

- `PASS` — proceed.
- `PASS_ADVISORY` — proceed **only** if the review reports zero blocking findings.
- `NEEDS_REVISION` — fix blockers, re-run the *same* gate with `--previous-run <run-id>`.
- `ESCALATED` — stop autonomous retries; a human must narrow, split, or redesign the target.

These four are the **lifecycle-gate** contract. The per-lens **rubrics** use a related but distinct
verdict vocabulary — `PASS` / `NEEDS_REVISION` / `ESCALATE` (a human decision is required) /
`NOT_APPLICABLE` (the lens doesn't apply), with **no** `PASS_ADVISORY` and `ESCALATE` rather than
`ESCALATED` — which the gate normalizes into the four above. Don't read the two sets as identical:
a per-lens `NOT_APPLICABLE` or `ESCALATE` is a rubric-level outcome, not a gate verdict.

A real dogfooded example (`docs/metareview/reviews/mrv-20260705-223417096019000-pr-ready-branch-10d735e5.md`)
shows the shape this actually produces: a `pr-ready` run with six named reviewer roles
(`pr-readiness-reviewer`, `validation-reviewer`, `security-reviewer`, `code-quality-reviewer`,
`architecture-reviewer`, `external-reviewer`) reported in a table with per-reviewer verdict and
blocking count, one `NEEDS_REVISION` overall verdict driven by exactly one blocking finding
(`validation-reviewer`: "Missing validation evidence"), and a stable finding ID
(`mrvf-20260705223417096019000-pr-ready-branch-10d735e5-001`) that a later run can reference to
confirm it was fixed rather than re-litigated from scratch.

**→ mine:** the four-verdict contract (`PASS` / `PASS_ADVISORY` / `NEEDS_REVISION` / `ESCALATED`)
with an explicit "stop retrying, escalate to a human" terminal state is a sharper contract than
the atlas ships today. The atlas's entrypoints report findings with severity/tier, but nothing
in the manifest schema distinguishes "the agent should keep iterating against this same finding
set" from "this needs a human redesign, stop retrying" — that distinction only exists implicitly,
in whatever the calling harness (a CI loop, an agent's own judgment) decides to do with a
findings list. A named escalation state is a concrete, adoptable idea for any orchestration layer
built on top of the atlas's own review output (see Gap analysis, Tier 1).

### Structured evidence receipts instead of prose validation claims

metareview does not trust an agent's prose claim that "tests pass." `metareview evidence run --
<command>` wraps a validation command and records a JSON receipt; the real receipts embedded in
the dogfooded `pr-ready` review above have this shape (fields observed directly, not from
documentation; the absolute `cwd` path is anonymized here):

```json
{"schemaVersion":1,"kind":"validation","command":["bash","tests/run-all.sh"],
 "cwd":"<repo>/.worktrees/docs-0-6-release-notes",
 "exitCode":0,"startedAt":"2026-07-05T21:54:06.03Z","finishedAt":"2026-07-05T21:54:28.47Z",
 "stdoutSha256":"d936305a...","stderrSha256":"2bdaf97d...",
 "summary":"bash tests/run-all.sh exited 0"}
```

`metareview evidence import --github-checks <pr-number>` imports GitHub check results into the
same receipt schema (`kind: "ci-check"`, with a `covers` field naming the check), so CI status and
locally-run validation are evidence in one uniform, hash-verifiable format. `task-done` and
`pr-ready` parse these receipts as validation evidence rather than accepting a written claim.

**→ mine:** the receipt shape — command, cwd, exit code, start/end timestamps, **hashes of stdout
and stderr** rather than the raw output — is a specific, well-thought-through answer to "how do
you let a reviewer (LLM or human) trust that a claimed validation actually happened, without
storing potentially-huge or sensitive raw output." The hash lets a later run cheaply verify that an
output stream is **byte-identical** to a previous run's — or detect that it differs — without
re-embedding it. That is exact-equality verification, not a diff: a matching hash confirms nothing
changed, but a differing one cannot attribute *what* changed (for that you'd retain diffable
output). [`grounding-review-in-tool-output`](../../skills/grounding-review-in-tool-output)
already runs the repo's own tools and hands raw output to the lens as evidence for *this* PR, but
the atlas has no receipt/log format at all — nothing analogous exists for a *caller* (a CI wrapper,
an agent) to hand the atlas "here is proof I ran the tests" in a way a later invocation could
independently verify without re-running or re-reading full output.

### Rubrics as a small, fixed panel of adversarial reviewer lenses

Each gate's rubric names required lenses run as (per `README.md`) independent parallel subagents
by default, with an explicit degraded mode: "`in-session-emulated` fallback is weaker evidence and
must say the review is not independently adversarial." `artifact-review-rubric.md` names six
required lenses — **Feasibility**, **Completeness**, **Scope And Alignment**, **Architecture**,
**Intent Preservation**, **Security** — each with its own block conditions. (This six-lens count is
specific to the *artifact* rubric; the other gates' rubrics name their own, smaller lens sets.
metareview's own `README.md` still says the artifact review runs "the five required lenses" — the
original set before Security was added as the sixth per the security-rubric provenance note quoted
below; the README line wasn't updated to match, an internal inconsistency in metareview's docs.) The Architecture lens
is unusually deep for what is nominally one rubric section: it enumerates data-modeling smells
(N+1, unbounded materialization, "Jaywalking" columns, missing FK/UNIQUE/CHECK constraints),
concurrency/consistency smells (lost updates, TOCTOU check-then-insert, money-as-float), coupling
smells (business rules baked into schema shape, internal representation leaked into API contracts),
and a named "LLM-specific failure modes" section — cached columns nothing maintains, indexes that
don't match the queries *in this diff*, an invented FK relationship "plausible from training but
absent in the domain," docstrings describing behavior the code doesn't implement — explicitly
because, per the rubric's own framing, these are places to "be most suspicious where the code
looks most idiomatic."

The `security-review-rubric.md` header states its own provenance and cost reasoning directly:

> Mined from metaswarm's `rubrics/security-review-rubric.md` (OWASP Top 10, 2021 edition), scoped
> to the classes a diff review can verify: A01-A05, A07, A08, A10, plus XSS/escaping. A06
> (vulnerable/outdated components) and A09 (logging & monitoring failures) are deliberately
> excluded as non-diff-reviewable... Per docs/METAREVIEW_IMPROVEMENTS.md H1: metareview's original
> 5 lenses were all artifact-shape checks (Feasibility, Completeness, Scope, Architecture, Intent);
> none prompted a reviewer to look for vulnerabilities, so metareview under-recalled on security
> goldens vs vanilla. This 6th lens closes that gap at ~zero marginal cost (lenses are Haiku
> subagents — ~0.04% of cost; the orchestrator dominates...).

(`docs/METAREVIEW_IMPROVEMENTS.md` is not present in the metareview checkout itself — it is
presumably a metaswarm-side document; this claim is metareview's own rubric text, not
independently re-verified against that file.)

**→ mine:** two distinct, adoptable ideas here. First, a rubric that **explicitly names its own
coverage gaps by OWASP class** (which classes a diff review structurally cannot verify, and why)
is a stronger discipline than most security checklists, which tend to imply full coverage by
omission. `reviewing-*` lenses in this suite generally scope themselves to what a diff review can
see, but a rubric this explicit about *excluded* classes and the reasoning per class is worth
comparing against `sweeping-for-security`'s and `reviewing-llm-integration`'s own scoping language.
Second, the cost claim — "lenses are Haiku subagents, ~0.04% of cost; the orchestrator
dominates" — is a concrete data point (unverified against metaswarm's own numbers, but directionally
plausible for small-model fan-out) worth keeping in mind whenever this suite's own design considers
"is adding another parallel lens worth the token cost": the marginal lens is cheap; what's
expensive is the surrounding orchestration/synthesis, an argument *for* running more, narrower
lenses rather than fewer, broader ones, which is closer to this suite's own `choosing-review-lenses`
model than to a single monolithic reviewer prompt.

### An explicit non-overlap contract between deterministic gates and LLM lenses

The security rubric's injection section states the boundary directly: "Block on user input
reaching a query/command/eval without parameterization or validation. (Note: metareview's
deterministic `eval(` gate already covers bare `eval(` injection — do not double-report that; flag
injection the gate does not catch, e.g. SQL string interpolation.)" `task-done-review-rubric.md`
lists its own deterministic blockers plainly, ahead of and separate from any LLM judgment: "The
diff introduces unsafe execution such as `eval`," "The diff adds `TODO` or `FIXME` markers,"
"Diff context is truncated," "Unsafe untracked source files are present."

**→ mine:** this is the same shape [`grounding-review-in-tool-output`](../../skills/grounding-review-in-tool-output)
already ships (deterministic hits get disposed of — confirm/contextualize/dismiss — exactly once,
never re-derived from scratch by the LLM lens), but metareview's version is narrower and more
literal: a handful of the repo's *own* string/pattern gates (`eval(`, `TODO`/`FIXME`, untracked
files) sit ahead of the LLM rubric and the rubric text itself tells the LLM lens which specific
sub-case is already covered so it doesn't restate it. Worth checking whether the atlas's own
`prepass:`-routed tool findings are similarly named *inside* the lens prompts that receive them
(so a lens's own reference material says "don't restate rule X, it's already confirmed"), or
whether that non-duplication is left to the synthesizer alone.

### Fractal decomposition review and an explicit "intent preservation" gate

metareview's stated workflow (`README.md`'s mermaid diagram and prose) reviews **before**
implementation starts, not only at PR time: an `artifact` review gates a spec/plan, decomposition
into epics/tasks is itself reviewed recursively ("Fractal child-plan review... until every level is
implementation-ready"), and after the fractal loop converges, an **Intent Preservation** lens
compares "final artifact direction against original intent and accepted constraints. Block when
review iterations changed the objective without explicit human acceptance" (`artifact-review-rubric.md`).
The `pr-ready` rubric separately treats "Task, epic, or findings state still has unresolved
blockers" as its own block condition, chaining the gates rather than treating PR review as
independent of what came before.

**→ mine:** the suite's closest existing analog is [`reviewing-ai-authored-code`](../../skills/reviewing-ai-authored-code)'s
"over-helpful unrequested additions (scope creep as a generation artifact)" check and
[`reviewing-decision-lifecycle`](../../skills/reviewing-decision-lifecycle)'s ADR/RFC-stage review —
but both are diff-shaped: they look at a single artifact against itself, not explicitly at *this*
artifact against the *original written request* that motivated it, re-checked specifically *after*
one or more revision rounds. A dedicated "does the current state still match the original ask,
after N rounds of fixes" check — run once, late in a multi-round loop, rather than as one more
lens on every round — is a narrower and more specific mechanism than what "scope creep" detection
does today, and is the kind of check that matters most in exactly the agentic-loop scenario this
suite is increasingly reviewed in (an agent iterating against its own findings across several
turns, where small compounding fixes can quietly wander from the original ask).

### Post-merge learning: typed accept/discard curation with provenance back to the fixing run

`learn --post-merge <pr> --base <pre-merge-ref>` produces two files per run, both read directly:
an **accepted** learning doc and a **discarded** candidates doc. The real accepted-learning example
(`docs/metareview/learning/mrv-20260705-060735118392000-learn-post-merge-6-c1dfd96e-accepted.md`)
is not a vague lesson — it is one specific, actionable instruction ("For metareview changes that
generate durable docs/metareview artifacts, stage the intended source and artifact payload before
rerunning task-done or pr-ready...") carrying an explicit `Confidence: high` and **source refs
that point back to the exact finding ID that surfaced the problem and the exact run ID where it was
fixed** (`finding mrvf-...-001; fixed-run mrv-...`). The paired discarded-candidates file for the
same run keeps a one-line, *typed* rejection reason rather than silently dropping the candidate:
`follow-up-not-knowledge: Capture review-driven fix: Complete the work or convert the remaining
work into an explicit follow-up.` The acceptance bar is stated directly in
`skills/learn-post-merge/SKILL.md`: "Keep accepted knowledge only when it would change a future
reviewer's behavior on a similar task." (`rubrics/learning-review-rubric.md` states the same rule
in its own words — "Post-merge learning keeps only knowledge that changes future reviewer
behavior" — and enumerates the fixed discard reasons, `follow-up-not-knowledge` among them.)

**→ mine:** this is the single most distinctive mechanism in the whole project relative to this
suite's own design, and the most directly comparable to something the atlas already has in nascent
form. [`open-questions.md`](../open-questions.md)'s decision log and
[`session-log.md`](../session-log.md) are this repo's own accumulated-knowledge artifacts, but they
are narrative and human/agent-curated during *authoring* sessions — there is no equivalent of a
**gate that runs once after a PR merges**, specifically to ask "did anything happen in this PR's
review cycle that should change how a *future* review behaves," with (a) a forced accept/discard
split so noise doesn't silently accumulate, (b) a *typed* discard reason instead of a bare drop, and
(c) traceability from the accepted lesson back to the specific finding and the specific run that
resolved it. The closest the atlas has is ad hoc: a reviewer catches something, the fix ships, and
the lesson becomes a paragraph in `session-log.md` or a new line in `open-questions.md`'s standing
authoring rules (see the `README.md`'s own "Why this rule exists" provenance notes for categories
\#40/\#41 and \#42, which are structurally the same thing — a post-hoc "what should change
reviewer behavior next time" capture — done by hand, per incident, rather than as a standing gate
with a forced accept/discard/provenance shape). Whether a mechanized version of this is worth building for a
*review suite that has no runtime state between invocations* is a real open question (see Gap
analysis) — but the **shape** of the mechanism (forced dispositioning, typed discards, provenance
links) is worth reading even if this suite's own version stays a lighter-weight manual convention.

### Repository-knowledge priming to avoid duplicate work

On first use, metareview looks for existing architecture notes, service inventories, Beads
knowledge, prior sessions, and GitHub history, and can seed a `docs/SERVICE_INVENTORY.md` template
(`templates/SERVICE-INVENTORY.md`) if none exists, specifically so a reviewer (or an implementing
agent) can check "does this duplicate an existing service or code path" — `task-done-review-rubric.md`
lists "The change appears to duplicate an inventoried service or code path" as one of its blocking
conditions.

**→ mine:** narrower value for a stateless, per-invocation review suite — this is squarely a
project-memory feature for the *implementing* agent (avoid reinventing a service), not a review
*lens* concern this suite's taxonomy already owns. Noted for completeness, not promoted further.

---

## Gap analysis: code-quality-atlas vs. this architecture

Ranked by (my estimate of) value ÷ implementation cost, using the confirmed findings above. Unlike
[`competitor-landscape.md`](competitor-landscape.md)'s gaps, several of these are **orchestration/
harness** gaps rather than **review-content** gaps: they describe what a *caller* of this suite's
skills could build on top, not a new lens or checklist item.

### Tier 1 — high value, low cost, fits a stateless per-invocation skill

1. **A named terminal-escalation state, distinct from "more findings to fix."** metareview's
   `ESCALATED` verdict — stop automatic retries, a human must redesign the target — is a concrete,
   small addition: any orchestration wrapping this suite's review output (a CI retry loop, an
   agent driving its own fix cycle) currently has no standard signal for "this PR/diff needs a
   human, stop feeding it back to the agent," only a findings list it must itself decide how to
   interpret. This doesn't require persistent state — it's a synthesis-output field (e.g., "this
   round's findings look like the same root cause as N prior rounds" or "a `CRITICAL`
   architecture-level finding, not a mechanical fix" as the trigger), evaluable from the current
   round's findings plus whatever run history the caller already has. Compare
   [`synthesizing-review-findings`](../../skills/synthesizing-review-findings)'s current verdict
   contract to see whether an escalation signal fits there or belongs one layer up, in the calling
   runbook ([`runbooks/pr-review-automation.md`](../runbooks/pr-review-automation.md)).
2. **A non-duplication instruction embedded in lens prompts, naming the specific deterministic
   check already covered.** `grounding-review-in-tool-output` already routes deterministic hits to
   owning lenses and disposes of each exactly once at the *synthesis* layer; metareview's rubric
   text goes one step further and tells the **lens itself**, inline, which narrow sub-case a
   deterministic gate already owns (`eval(` gate → don't re-flag bare `eval(` injection, do flag
   SQL string interpolation). Worth checking whether `reference/tool-evidence.md` in each collapsed
   entrypoint already does this at the per-lens level or only at the synthesizer's dedup step —
   if only the latter, a lens can still independently raise a finding a deterministic gate already
   confirmed, costing a synthesis-time dedup pass rather than avoiding the duplicate at the source.

### Tier 2 — real value, but requires state this suite doesn't currently keep

1. **An evidence-receipt format for validation claims a caller hands in.** The atlas today reviews
   a diff (plus whatever the agent or reviewer chooses to read live); it has no standard shape for
   "here is proof this test suite passed, hashed so a later step can verify without re-running or
   re-embedding full output." This only matters to a caller that *wants* to hand in external
   validation evidence (a CI pipeline, an agent's own test run) as first-class input to a review —
   worth scoping to `runbooks/pr-review-automation.md`'s existing orchestration guidance rather
   than the lens layer, since it's an input-contract question, not a review-content one.
2. **A post-merge "what should change reviewer behavior next time" gate, mechanized rather than
   manual.** The suite already does this by hand (session-log entries, the standing authoring
   rules' own incident write-ups) — the open question is whether forcing it into a structured,
   per-PR accept/discard/provenance artifact is worth the overhead for a review suite with **no
   runtime state between invocations to feed it back into automatically**. metareview's version
   earns its keep because its calibration data feeds directly into the *next automated run* of the
   same CLI; this suite's equivalent would need a concrete answer to "where does an accepted
   learning actually get read on the next review" before the mechanism pays for itself — plausibly
   the still-unbuilt Q13 team-preferences overlay ([`team-preferences-overlay.md`](../team-preferences-overlay.md)),
   if a "reviewer calibration" tier were added alongside its existing preference tiers, rather than
   a new standalone mechanism.

### Tier 3 — architecturally out of scope for this suite as designed

1. **The gate lifecycle itself (spec/plan → task → epic → PR → post-merge), as a CLI with
   persistent local state (`.metareview/`, `docs/metareview/`).** This suite is deliberately a set
   of stateless Claude Code skills invoked per PR/diff, not a standalone tool with its own state
   directory, run-ID chaining, or `--previous-run` reconciliation. Adopting the *lifecycle
   coverage* (reviewing a spec/plan before code exists, reviewing task-sized chunks before a PR)
   is a legitimate scope question already covered by this repo's own shape/artifact routing
   (`taxonomy.md`, [`review-depth-modes.md`](../review-depth-modes.md)) and
   [`reviewing-decision-lifecycle`](../../skills/reviewing-decision-lifecycle) for the earliest
   stage — but adopting metareview's *mechanism* (a persistent run-chain, findings reconciled by
   stable ID across runs) would mean building genuinely new infrastructure, not a skill change.
2. **Repository-knowledge priming (service inventories, duplicate-service detection).** As noted
   above, this is implementing-agent memory, not a review-lens concern this repo's taxonomy owns.

### Not a gap (already covered or deliberately different by design)

- **Adversarial multi-lens review of one artifact** — this suite already runs multiple lenses per
  change and synthesizes across them; metareview's "independent reviewer lenses... against the
  same artifact" is the same pattern, not new coverage.
- **A deep, LLM-specific-failure-mode-aware architecture/data-modeling lens** — the depth
  metareview's Architecture lens reaches (schema invariants, TOCTOU, money-as-float, "be most
  suspicious where the code looks most idiomatic") reads as strong convergent validation of this
  suite's own `cluster-3-structure.md` / `reviewing-ai-authored-code` coverage rather than a gap.

---

## Open threads (follow-up research, not yet done)

1. **metaswarm itself** — metareview's docs describe it as the intended lifecycle-owning
   orchestrator (issue intake, Beads task graph, Superpowers TDD workflows, PR shepherding) that
   metareview plugs into as "the deeper review harness." Not cloned or verified in this pass; the
   security rubric's claim that it was "mined from metaswarm's `rubrics/security-review-rubric.md`"
   and the referenced `docs/METAREVIEW_IMPROVEMENTS.md` (goldens, recall-vs-vanilla measurement)
   are both metareview-side claims about a sibling repo, not independently confirmed.
2. **Real-world adoption / practitioner experience** — not researched here (no web search
   performed); this pass is a direct source read, not a reception/sentiment pass the way
   `competitor-landscape.md`'s Tier "Open threads" covers for the commercial products.
3. **Whether metareview's golden-eval / recall-measurement process** (referenced but not present in
   this checkout) resembles or differs from this suite's own `skills/*/evals/eval.json` approach —
   worth a dedicated comparison if `docs/METAREVIEW_IMPROVEMENTS.md` or its metaswarm-side source
   becomes available to read directly.
