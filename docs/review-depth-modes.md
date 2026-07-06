# Review-depth modes (Q14 resolution / D16)

**Status:** resolved (user, 2026-06-24); manifest/generator/synthesizer layer
**built 2026-06-26 (PR #80)**, folded into
[`collapsed-entrypoints-and-depth-modes.md`](collapsed-entrypoints-and-depth-modes.md)
— see `docs/open-questions.md` D16. The commands' and `REVIEW.md`'s surfacing
that lets `/atlas-review-pr` and `/atlas-code-review` actually select a mode from the
request landed later (issue #114) — both entrypoints now detect the mode and
apply its floor policy. Supersedes the open framing in
[`open-questions.md`](open-questions.md) Q14.

**Addendum (2026-07-06):** the review-mode default breadth widened from 2-4 to
**3-8**, and is explicitly non-strict — the reviewer selects additional lenses
beyond the ranked top-8 when the change's scope calls for it, the same way #3
below already described the cap as overridable rather than a turnstile. Two
change shapes also gained an **auto-include**: a docs-only change always pulls
in `auditing-documentation-health`, and an ADR/RFC/decision-record change
always pulls in `reviewing-decision-lifecycle` (plus
`auditing-decision-record-currency` when it touches an existing record), both
riding along additively like `reviewing-pr-and-process-hygiene` already did.
The rest of this document's "2-4" language is left as the historical record of
the original decision; treat **3-8, non-strict** as the current figure
wherever the two disagree.

## The problem this resolves

The router (D10) collapsed **two independent axes** onto one 2-4-lens list:

- **Relevance** — which lenses *apply* to this change (a bug fix needn't run a11y).
- **Depth** — *how much* to run right now (a quick gate vs. a full audit).

The 2-4 cap is a *depth* choice wearing a *relevance* mask. [`map-gaps.md`](map-gaps.md)
G9 measured the cost: capping every change to 2-4 lenses leaves the soft lenses
(naming/readability #5–#8, observability #16, restraint) unfired on most change shapes,
so their factors never produce findings — the suite emits **no naming findings in
practice** despite #5 being owned. The 2-4 cap was written as a *discovery aid* (fire the
right lenses without knowing the whole catalog), **not** as a coverage gate; the original
intent was the full suite in parallel for an extremely comprehensive review, with the
router as the on-ramp, not a turnstile.

## The decision

### 1. Separate the two axes

Relevance becomes a **ranked list** (every applicable lens, ordered by a relevance
signal); **depth decides how far down that list to run.** The single hard 2-4 cut is
replaced by "rank by relevance, then take as many as the depth mode asks for."

### 2. Three depth modes (discrete tiers; ranked relevance underneath)

| Mode | What runs | Severity floor | When |
|---|---|---|---|
| **triage** | the **critical tier** only — correctness, security, data-safety, concurrency | raised to **Major+** (blockers only) | fast pre-merge gate / smoke |
| **review** *(default)* | the relevance-ranked **top-N** (the 2-4 cap survives here as the default depth, overridable — widened to **3-8** per the 2026-07-06 addendum above) | today's **round-based escalation** | per-PR |
| **comprehensive** | **every applicable lens, uncapped** | pinned at **Nit** (no per-round escalation) | on-demand / scheduled |

The six repo-shaped audits are the **repo arm** of the comprehensive tier; comprehensive
adds the missing **diff arm** (every applicable diff lens in parallel).

### 3. The 2-4 cap survives — but only as the review-mode default depth

It is now a *default top-N*, overridable, not a hard turnstile. Triage = critical tier;
comprehensive = uncapped. (See the 2026-07-06 addendum: the default range is now 3-8,
and the reviewer is expected to select further lenses past that range when context
warrants — the cap was always meant as a recommendation, not a limit, and this made
that explicit rather than leaving it to be read as a hard number.)

### 4. The severity-floor interaction is the actual G9 fix

`REVIEW.md`'s round-based floor escalation is what silences Nit/Minor (readability-class)
findings after round 1. Running more lenses alone would not surface them — the floor would
still trim them. So **comprehensive mode pins the floor at Nit** (no per-round
escalation): that is where the soft lenses finally produce visible findings. Triage raises
the floor to Major+; review keeps today's escalation. **The floor policy is per-mode** —
this is the mechanism that closes G9, not merely the larger lens set.

### 5. Mode lives in a manifest `modes:` section

Source-of-truth is a manifest `modes:` section the router generates from (like the router
and synthesizer today: `built_from: []`, so docs-drift never flags it; manifest edits
regenerate it). This keeps D7 plain-markdown portability — a "mode" is just *which subset
of the ranked list the router emits* plus *which floor policy the synthesizer applies*; the
agent still fans out advisory-style (D12), no harness orchestration assumed.

Surfaced through thin entry points: commands (`/atlas-triage`, `/atlas-review-pr` = the
review default, `/atlas-audit-comprehensive`) and/or a `--depth` argument. Commands are
wrappers over the manifest modes, not the source of truth.

### 6. Q13 hook

The team-preferences overlay (Q13, designed/[`team-preferences-overlay.md`](team-preferences-overlay.md))
sets the **per-repo default mode** and the **critical-tier definition** when it is built.
Until then the defaults are: review mode, and the critical tier = correctness + security +
data/migration safety + concurrency (the same floor-tier set Q13 already names as
never-silently-droppable).

## Relation to prior decisions

Refines **D10** (the router gains a depth axis and a ranked relevance list; the 2-4 cap is
re-scoped to review-mode default) and **D12** (the synthesizer gains a per-mode floor
policy). Consistent with **D7** (plain markdown, advisory fan-out) and the manifest-derived
generation of the two composition skills. Resolves the coverage half of **G9** (the router
under-selection); the budget half — surfacing deep factors via the `★` inline-priority
marker — already shipped.

## Open implementation sub-questions (for the build pass)

These are deliberately left to implementation planning, not blocking the decision:

- **Critical-tier membership** — exact lens list for triage (start: tracing-correctness,
  sweeping-for-security, reviewing-migration-and-data-safety, reviewing-concurrency-and-async).
- **Relevance ranking** — keep the hand-authored `when → lenses` table as the initial
  ranking, evolving toward signal-based scoring (changed paths / languages / diff features
  → a per-lens score) later; the table is fine to start, scoring is a refinement (old Q14
  candidate-3).
- **Comprehensive cadence** — on-demand command vs. also scheduled (likely both: an
  on-demand command plus an optional cron, mirroring the repo audits).
- **Synthesizer / `REVIEW.md` changes** — how the per-mode floor policy is expressed and
  honored across review rounds (comprehensive must not re-escalate the floor between
  rounds).
- **Entry-point surface** — distinct commands vs. a single `--depth` arg on
  `/atlas-review-pr`; likely both, with the commands as the discoverable default.
- **Cross-model eval** — comprehensive mode's lowered floor must not turn into
  over-flagging noise on the 7-8B floor; re-gate the synthesizer's per-mode behavior.
