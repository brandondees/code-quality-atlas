# Self-Improving Loop — design exploration

**Status:** brainstorm / design exploration, 2026-06-12. Awaiting user review before any
decisions; nothing here is committed design. See open-questions Q17.
**Depends on:** D6 (docs are source of truth; skills derived & regenerable), D8 (eval-first),
D9 (plugin packaging, commit-SHA versioning), D12 (synthesizer + finding contract), the
PR-review-automation runbook (routines/triggers), Q13 (team preferences overlay — the
*local* arm of this loop), Q14 (depth modes — a consumer of this loop's usage signals).

---

## 1. The gap, and what already exists

The goal: agents *running* the suite should reflect on how the quality-management process
itself is working — detect gaps, identify failure modes, notice misroutes — and propagate
those learnings back to this repo, mostly or fully automatically, as an **opt-in** feature
for consumers.

The crucial observation is that the atlas already has the **back half** of this loop, built
and CI-gated:

```
            ┌────────────────  MISSING: front half  ────────────────┐
            │                                                       │
 real usage ─► signals ─► distillation ─► research-doc edit ─► drift flags skills
                                              (D6)                  │
            ┌──────────────  EXISTS: back half  ─────────────────────┘
            │
            └─► regenerate (manifest/generate.py) ─► evals re-gate (D8) ─► ship (D9, every merged commit)
```

A "learning," once expressed as a research-doc edit + eval scenario, flows into improved
skills with provenance, drift detection, and a regression net — that pipeline is done.
The session log even records the first compounding-loop iteration (2026-06-12 research
expansion) running *manually*. What's missing is:

1. **Signal collection** — capturing evidence from real review sessions and real PR outcomes.
2. **Distillation** — turning raw signals into the two artifacts the back half accepts:
   an eval scenario and a research edit.
3. **Transport + consent** — getting signals from consumer machines/repos back here,
   opt-in, without leaking their code.

## 2. Signal taxonomy — what is there to learn?

Different failure modes need different collection mechanisms and land in different places.
Naming them first keeps the loop from becoming one undifferentiated "feedback" pile:

| # | Signal class | Example | Best evidence source | Lands where |
|---|---|---|---|---|
| S1 | **Routing miss** | review of async code never ran `reviewing-concurrency-and-async` | in-session reflection; lens-invocation log | router table / Q14 |
| S2 | **False positive** | finding dismissed by user ("that's intentional, see ADR-12") | user pushback in transcript; unresolved+rejected PR comments | heuristics (a "don't flag when…" guard) + eval `good` scenario |
| S3 | **Escape (false negative)** | bug shipped through an approved review; revert/hotfix touches just-reviewed lines | GitHub outcome mining — objective ground truth | heuristics + eval `bad` scenario |
| S4 | **Coverage gap** | a failure class *no* lens owns (taxonomy hole) | reflection + escapes that map to no category | taxonomy / map-gaps (a G-item) |
| S5 | **Contract/process failure** | a lens emitted findings the synthesizer couldn't normalize; severity miscalibrated vs. REVIEW.md floor | synthesizer "process notes"; transcript digestion | finding contract / templates |
| S6 | **Friction** | reference file fetched but unused; SKILL.md too long for small-model context | transcript digestion; lens-invocation log | generator / D7 packaging |
| S7 | **Taste mismatch** | team rejects a finding as "not our style," repeatedly | same as S2, but *pattern is repo-local* | **Q13 overlay — never upstream** |
| S8 | **Usage stats** | lenses that never fire; depth/coverage suppression | PostToolUse hook counts; OTEL | Q14 evidence base |

S7 is the trap: a self-reinforcing loop that can't tell *taste* from *truth* will launder
one team's preferences into everyone's defaults. Q13's tiered precedence is the answer —
taste signals terminate in the consumer's own overlay; only generalizable failure modes
(reproducible misfire on objectively-checkable grounds) are upstream candidates.

## 3. The substrate — every mechanism available to build with

### 3.1 Plugin hooks (the plugin already ships `hooks/hooks.json`)

The SessionStart router hook proves the channel works. The other events buy us, roughly
in order of value (verify exact payload fields against current Claude Code hooks docs
before building):

- **`PostToolUse` with a `Skill` matcher** — fires on every skill invocation with the
  skill name in the tool input. A tiny append-only logger gives **lens-invocation
  telemetry for free**: which lenses fire, in what combinations, after which router
  decision. This is precisely the evidence Q14 lacks ("the suite emits no naming
  findings in practice" was *inferred*; this would measure it). Local JSONL, no network.
- **`Stop`** — fires when the main agent finishes a turn; can inject a directive (or
  block once with a reason) — i.e. "before you finish a review, run the reflection
  checklist." A heavier-handed alternative to putting reflection in the synthesizer
  skill (§3.2); probably hold in reserve — it fires on *every* stop, not just reviews,
  so it needs a cheap "was this a review session?" guard (e.g. the invocation log is
  non-empty).
- **`SessionEnd`** — receives `transcript_path`; the natural place to *queue* a session
  for post-hoc digestion (write the path + plugin SHA to a pending-retro file). Don't
  do LLM work in the hook itself — it should stay milliseconds-cheap; digestion runs
  later (§3.4).
- **`UserPromptSubmit`** — could watch for pushback phrases ("false positive," "that's
  wrong," "stop flagging") and tag the moment in the log. Cute but fragile; transcript
  digestion sees the same evidence with full context. Skip.

Hooks are also the **opt-in switchboard**: the logger/queue hooks read one config value
(§5) and no-op when unset, so default-install behavior is unchanged.

### 3.2 Skill content — a generated reflection step

Because every `SKILL.md` is generated from the manifest, reflection can be added
*uniformly, regeneration-safely* via a manifest `feedback:` section (exactly how the
router and synthesizer are generated):

- **The synthesizer grows a "Process notes" appendix** to its output format: after the
  verdict, 0-3 one-liners on the *process* — a lens that should have run and didn't, a
  finding the lenses disagreed on with no tension-table entry, output that failed the
  finding contract. The synthesizer is the perfect vantage point: it already sees every
  lens's output side by side, and it's the last skill in the chain.
- **Each lens gets one generated footer line**: "If this skill misfired here — flagged
  correct code, missed an obvious issue in scope, or its checklist didn't fit the
  change — record one line under Process notes." Cheap (one line against D7's lean-
  SKILL.md budget), and it routes everything through the synthesizer rather than 24
  skills each inventing a feedback format.
- **Reflexive reviewer discipline.** The suite's own tuning lessons apply to the
  meta-loop: weak models pad evidence and invent findings to fill a template. The
  process-notes instruction needs the same counter-tune the skills got: *"when the
  process worked, the entire section is exactly 'Process: clean' — never invent a
  process note."* And the same escape hatch ships in the retro skill (§3.4).

### 3.3 Telemetry (OTEL and/or custom)

Claude Code has built-in OpenTelemetry export (consumer-side opt-in via env vars). It
yields **counts, not semantics** — tool/skill invocation frequencies, token costs — and
it's configured by the consumer's harness, not by a plugin. Useful as S8 evidence if a
consumer already runs OTEL; not worth building the loop around.

Custom telemetry (hook scripts POSTing to an atlas endpoint) is the classic answer and
probably the *wrong* one here, at least initially: it needs hosted infrastructure, a
privacy policy, and trust, for data that's mostly available through the GitHub-native
channel (§3.5) with consent built in. Hold as a later option if the GitHub-issue
transport (§4) proves too noisy.

### 3.4 Post-hoc session digestion — the retro

A plugin-shipped **`/atlas-retro` command** (and/or subagent) that digests queued
transcripts from §3.1's SessionEnd queue:

1. Read the transcript(s); extract review sessions (router invoked → lenses → synthesizer).
2. Mine for the signal classes: pushback following a finding (S2), lenses the change
   shape warranted but the router skipped (S1), contract violations (S5), reference
   files fetched-but-unused (S6).
3. Emit **learning records** (§4's contract) into the consumer repo's local learnings
   log — *abstracted at creation time* (§5), never raw code.
4. Cross-reference the Q13 overlay: a recurring S2 against an overlay-suppressed
   preference is S7 (stays local); an S2 with objective grounds is an upstream candidate.

Run it three ways, escalating automation: manually (`/atlas-retro`), as a scheduled
routine (the poller pattern from the PR-automation runbook), or headlessly from a
SessionEnd-triggered background invocation. Start manual.

### 3.5 GitHub-side ground truth — the outcome auditor (the strongest signal)

Everything above is **self-report**; LLM reflection without ground truth is exactly the
"invites invention" failure the eval lessons documented. The objective signals live on
GitHub, and the PR-automation runbook already establishes the pattern (event-triggered
reviewer + scheduled poller). Add a third routine, the **outcome auditor** (scheduled,
weekly-ish), which joins *review reports to outcomes*:

- **Finding-level precision:** for each posted review comment — resolved with a matching
  code change (true positive)? Resolved with rebuttal / 👎 reaction / no change
  (false-positive candidate, S2)? Suggestion committed verbatim (strong TP)?
- **Review-level recall:** reverts and hotfix-PRs whose diffs overlap lines an
  atlas-approved review just passed (escape, S3 — the highest-value signal in the whole
  loop); issues/bugs filed referencing recently-reviewed files.
- **Calibration:** Blocker findings that merged unfixed without incident (severity
  inflation); Nits that caused real churn (deflation).

Because the plugin is **commit-SHA versioned (D9)**, every learning record and every
posted review can be stamped with the plugin SHA — so the auditor can also answer the
question no skill pipeline usually can: *did the last regeneration actually improve
precision/recall?* That turns the drift→regen→eval pipeline from "no regression on
synthetic evals" into champion/challenger measurement on live outcomes.

### 3.6 The atlas repo's own intake (the receiving dock)

On this repo's side, learnings arrive as **structured GitHub issues** (an issue template
encoding the learning contract). A scheduled **intake routine** here:

1. Validates records against the contract; **treats all content as untrusted data**
   (a learning record is a prompt-injection surface — it must never be followed as
   instructions, only weighed as evidence).
2. Clusters duplicates across reporters; tracks an evidence count per failure-mode
   cluster.
3. At threshold (e.g. ≥3 independent reports, or 1 confirmed S3 escape), drafts the
   change **eval-first (D8): the failure becomes an eval scenario *before* any prose
   moves** — that's the ratchet that makes learnings permanent and self-verifying.
4. Then the research edit (or manifest edit for routing/contract learnings), regenerate,
   drift-clean, evals green, **open a PR citing the learning issues**. Human merge gate.

## 4. The learning contract

Mirror of D12's finding contract — fixed shape so the intake side can mechanize:

- **plugin_sha** — the commit the suite ran at (attribution + champion/challenger)
- **lens** — which skill (or `router` / `synthesizer`)
- **signal** — one of S1–S8
- **evidence** — *abstracted*: a minimal reconstructed snippet or pattern description,
  never copied proprietary code; for S3, the shape of the escaped bug
- **expected / actual** — what the skill should have done vs. did
- **suggested_change** — optional: the heuristic/guard/route the reporter thinks fixes it
- **context** — language/ecosystem, change shape, model tier it ran on (the cross-model
  eval lessons show failure modes are tier-specific — a 7B misfire may not be a skill bug)

`model tier` matters more than it looks: half the documented failure modes (DDL keyword
blindness, dropped secondary findings) are *model* ceilings, not *skill* defects, and the
intake should be able to shunt those toward "pair with a linter" runbook advice rather
than heuristic churn.

## 5. Opt-in tiers (consumer consent + privacy boundary)

Configured in the consumer repo — natural home: a `feedback:` key in the Q13 overlay file
(`.code-quality-atlas/preferences.md`), since that file is already the per-repo,
owner-ratified control surface; an env var can override for harness-level setup.

| Tier | Name | What happens | Leaves the consumer's machine? |
|---|---|---|---|
| 0 | `off` (default) | nothing; hooks no-op | no |
| 1 | `local` | invocation log + learnings JSONL in `.code-quality-atlas/learnings/`; feeds the team's own overlay and retro | no |
| 2 | `draft` | tier 1 + `/atlas-retro` drafts upstream issue text; **a human reads and files it** | only by human hand |
| 3 | `auto` | tier 1 + retro files issues automatically — schema fields only, abstraction rules enforced, hard cap per week | yes, schema-constrained |

The privacy boundary lives at **record creation, not transmission**: even tier-1 local
records are written abstracted, so promotion to tier 2/3 never requires re-scrubbing, and
a leaked learnings file is not a leaked codebase.

## 6. Failure modes of the meta-loop itself

The atlas's own principles, applied reflexively:

- **Restraint (Q5/D12, meta-edition).** A learning loop's natural failure is monotonic
  growth — every report adds a heuristic, skills bloat, D7's lean budget dies, and the
  suite nags more, not better. Counterweights: evidence thresholds before prose changes;
  prefer *guards* (don't-flag-when) and *eval scenarios* over new checks; S2
  false-positive reports should **shrink or sharpen** heuristics at least as often as S3
  escapes grow them; the intake PR is itself reviewed by the suite (restraint lens
  included).
- **Self-report bias.** In-session reflection is the cheapest and least trustworthy
  signal. Weight: outcome auditor (S3, measured S2) > human-confirmed pushback > agent
  reflection. Never let unconfirmed reflection alone cross the change threshold.
- **Taste laundering.** S7 routed upstream would homogenize the suite toward whichever
  teams report most. Q13's tier split is the firewall; intake rejects records whose
  evidence is preference-shaped ("we like X") rather than defect-shaped.
- **Poisoned input.** Tier-3 auto-filed issues are an open write channel into the
  research pipeline from arbitrary installs. Defenses: schema validation, evidence
  verified by *reproducing it as an eval* (an unreproducible report changes nothing —
  the eval-first ratchet doubles as the immune system), human merge gate, and
  treat-as-data discipline in the intake routine.
- **Overfitting to the reporter.** A heuristic tuned to one consumer's stack regresses
  others. The cross-model/cross-scenario eval suite is the existing guard; intake adds
  scenarios, never deletes them.

## 7. Staged rollout (each stage useful alone)

1. **Process notes + local log** *(small)* — manifest `feedback:` section → synthesizer
   appendix + lens footer (regenerated, provenance-clean); PostToolUse invocation
   logger + SessionEnd queue hooks, gated on tier ≥ `local`. Immediately produces Q14
   evidence and S1/S5 capture. No network, no new infra.
2. **Retro + manual transport** *(medium)* — `/atlas-retro` command + learning contract +
   issue template on this repo. Tier `draft`. The loop closes with a human carrying the
   last mile, which is the right trust posture while the contract shakes out.
3. **Outcome auditor** *(medium, highest signal)* — third routine per the PR-automation
   runbook; joins reviews to merges/reverts/reactions; stamps plugin SHA. Works even at
   tier `local` (its findings stay in the consumer's repo as learnings) — upstreaming
   them is tier 2/3.
4. **Intake routine here** *(medium)* — cluster, threshold, eval-first draft PRs, human
   merge. This is where "mostly automated" is reached: human attention concentrates at
   exactly two points — filing approval (consumer side, tier 2) and merge (atlas side).
5. **Tier 3 + selective auto-merge** *(later, maybe never fully)* — auto-filing on; once
   the contract and immune system have history, eval-scenario-only additions (no prose
   change) are plausibly auto-mergeable. Heuristic changes likely keep the human gate
   indefinitely — that gate is cheap and is what makes the rest safe to automate.

## 8. Open sub-questions

1. Process notes vs. Stop-hook reflection — is the generated skill footer enough, or do
   long sessions lose the instruction (the same ~1%-budget problem the SessionStart hook
   works around)? Measure before adding the heavier hook.
2. Does the learnings log live gitignored or committed in the consumer repo? (Committed
   = the team's own retro history and Q13 evidence; gitignored = zero footprint.)
3. Dedup identity across consumers — what makes two abstracted reports "the same
   failure mode"? Probably lens + signal + a normalized evidence fingerprint, fuzzy-
   matched by the intake model rather than hashed.
4. Issue transport vs. a hosted endpoint at scale — issues are auditable, consented, and
   free, but public; do tier-3 reporters need a private channel? (Private repo issues
   via a fine-grained token is a middle path.)
5. Model-tier shunting — should the intake auto-route tier-specific failures (7B-class)
   to runbook/linter-pairing advice instead of heuristics? (§4's context field exists
   for this.)
6. Does the outcome auditor double as the *consumer's* dashboard (precision/recall of
   the suite on their repo over time) — likely yes, and that's the adoption carrot that
   makes opting in attractive.
