# Team Preferences Overlay — design

**Status:** design, 2026-06-12. Awaiting review before implementation planning.
**Depends on:** phase-3 skill suite (23 lenses + `choosing-review-lenses` router + `synthesizing-review-findings`), D6 (docs are source of truth; skills derived & regenerable), D7 (model portability), D9 (plugin packaging), D12 (the synthesizer — where `acknowledge`d deviations land in the verdict).
**Decisions captured (user, 2026-06-12):** tiered precedence; both bootstrap paths (template + inference) but inference is **proposal-only, never auto-applied**. See open-questions Q13.
**Added (user, 2026-06-14, [`map-gaps.md`](map-gaps.md) G26):** an **improvement-valence verbosity** dial (§4.6) — the defect-only guard is a team *preference*, default strict — plus a built-in **anti-churn / convergence** discipline (§4a) the overlay cannot relax.

---

## 1. The gap

The suite is research-derived: it pushes a codebase toward standards that are, as far
as the atlas can establish them, *objectively* better. What it has no home for is the
**codebase owner's / team's considered opinion** — the deliberate local choices that a
generic "better quality" sweep would otherwise nag against.

There is exactly one precedent for bending to a team today: `checking-idioms-and-consistency`
reads `.eslintrc` / `.rubocop.yml` / `.editorconfig` / style guides and rules that *"the
codebase's established choice wins over personal preference."* That covers only the opinions
a team has already encoded **in a linter config**, and only for that one lens.

Everything else has nowhere to live:

- **Judgment-level opinions** no linter captures — "fat service objects are fine here,"
  "we don't do dependency injection," "long parser functions are acceptable."
- **Lens selection / weighting** — "internal tool, deprioritize a11y"; "security is always blocking."
- **Threshold tuning** — complexity ceilings, coverage targets, function length, PR size.
- **Local exceptions + rationale** — "`legacy/` is frozen, don't flag it"; a domain reason a
  given finding is simply wrong here.

This doc designs a **team preferences overlay**: a per-repo layer that lets owner-blessed
opinion modulate the defaults, without compromising the floor of genuinely-objective findings,
and without polluting the generated skills or their provenance.

## 2. Where it lives

The overlay belongs in the **reviewed** repository, not in this atlas — it travels with the
code it describes, exactly as `.eslintrc` does. The atlas ships the *machinery to read it*;
each adopting team owns *its own* overlay.

```text
 their-repo/
   .code-quality-atlas/
     preferences.md         # the overlay (human-authored, owner-ratified)
   src/ ...
```

Single human-readable markdown file (plus optional light front-matter for the machine-checkable
bits — lens enable/disable, thresholds). Markdown over a rigid DSL because the suite is
LLM-judgment-heavy and must stay portable down to ~8B local models (D7): directives are read and
applied by the model, not parsed by a validator. A linter config the team already maintains stays
a valid *source* the overlay can point at ("our style is whatever `.rubocop.yml` says"); the
overlay adds the judgment-level opinions linters can't encode.

**It is never baked into the generated `SKILL.md`s.** Per D6 the skills are derived artifacts with
provenance hashes and a drift-checker; an in-skill preference would pollute provenance and be
overwritten on regeneration. The overlay is a **runtime input read at review time**, orthogonal to
the atlas's own regeneration loop.

## 3. Tiered precedence (the core rule)

A team's opinion is allowed to move the defaults, but not to silently erase the suite's reason to
exist. The line runs through the *kind of claim a finding makes*, not the topic:

- **Preference-tier** — the finding asserts the code is *suboptimal by a contestable standard*:
  naming taste, module-shape opinions, restraint thresholds, idiom choices, doc depth, PR size,
  a11y priority for an internal tool.
- **Floor-tier** — the finding asserts the code is *wrong or unsafe*: it will break, corrupt,
  leak, expose, or lose data. Security (`sweeping-for-security`), correctness
  (`tracing-correctness-and-invariants`), data/migration safety, concurrency-correctness, and the
  hard parts of silent-failure hunting.

Each check already knows which it is (a check is floor-tier if it claims *broken/unsafe*, else
preference-tier). The overlay then has three verbs, and what they may touch differs:

| Verb | Effect | Allowed on preference-tier | Allowed on floor-tier |
|---|---|---|---|
| **set / tune** | change a threshold or lens selection *before findings exist* | yes | yes (e.g. pick lenses) — but cannot disable a floor check's *detection* |
| **suppress** | drop a finding silently | yes | **no** |
| **acknowledge** | accept a known deviation | n/a (just suppress) | yes — finding **still surfaces**, tagged `acknowledged deviation: <reason>`, not counted as blocking |

So a team can mute a naming-style finding outright, retune the complexity ceiling, or skip the
a11y lens — silently and fully. But it can never make a SQL-injection or a lost-update finding
*vanish*; the strongest it can do is record `acknowledged deviation: <reason>`, which keeps the
finding visible (and auditable) while removing its blocking weight. This is the "tiered" choice
from Q13: full flexibility on taste, an honest paper trail on safety.

## 4. What the overlay can express

Five directive kinds, each mapping onto the verbs above:

1. **Lens selection / weighting** — enable/disable lenses, or mark some advisory vs blocking.
   (`set`, capped by the router's 2-4 rule — preferences re-rank within the cap, they don't lift it.)
2. **Threshold tuning** — per-check numeric knobs (function length, complexity, coverage, PR LOC).
   (`set`.)
3. **House conventions** — judgment-level idiom rulings that override the lens's generic taste
   ("fat service objects are intentional"; "no DI"). (`suppress` on the matching preference-tier
   findings.)
4. **Scoped exemptions** — path- or area-scoped mutes ("`legacy/**` is frozen";
   "generated/** is not reviewed"). (`suppress` for preference-tier; `acknowledge` for floor-tier.)
5. **Standing acknowledgements** — known, accepted floor-tier deviations with rationale
   ("we ship our own crypto for <documented reason>, escalated and accepted"). (`acknowledge`.)
6. **Improvement-valence verbosity** *(added 2026-06-14; see [`map-gaps.md`](map-gaps.md) G26)* — how
   much *improvement*-valence (vs *defect*-valence) the suite surfaces. Every lens ships defect-only by
   construction (the guard *"do not suggest changes to code that is already correct"*); G26 adds a
   `valence: defect | improvement` axis so a lens *can* offer opt-in, nit-level tidyings (reorder for
   cohesion, remove dead code, bump a stale-but-working dep). This directive sets the policy per
   repo/team: **`defects-only`** (the default — preserves the earned "clean PR → No findings" trust),
   **`improvements-opt-in`** (surface improvement nits, `route: implementer`, apply/defer/ignore), or
   finer per-lens settings. (`set`, preference-tier — a team that wants a quiet review keeps the
   default; a team that wants active tidy-up dials it up. Floor-tier defects are unaffected.)

### 4a. The anti-churn discipline (built-in, not a knob)

Independent of the verbosity setting above, improvement-valence findings obey a **convergence floor the
overlay cannot relax** (a team can turn verbosity up, but cannot configure the suite to churn):

- **Value + confidence bar.** An improvement suggestion must *improve*, not merely offer an equivalent
  alternative — no change-for-change's-sake. A non-functional reorder is admissible only when it raises
  readability/cohesion, not when it trades one acceptable arrangement for another.
- **Convergence / termination.** Once a dimension is "as good as we can confidently make it," there is
  no further suggestion on it; never a lateral re-order to an equivalent state; never oscillation
  (suggest A→B one round, B→A the next). This is the same termination guarantee `REVIEW.md` convergence
  gives the review loop (escalating severity floor, round cap), applied to improvement nits — without
  it, an improvement-capable reviewer never settles, which is exactly the failure the original guard
  was protecting against.

## 5. How skills consume it

The router is the natural reader. `choosing-review-lenses` already runs first and routes; it gains
a first step: *"if `.code-quality-atlas/preferences.md` exists, load it; apply selection/weighting
directives to the lens choice; pass the remaining directives down to each selected lens as context."*
Each lens applies the directives relevant to its own checks at finding-emission time, honoring the
tier rules in §3. The downstream `synthesizing-review-findings` skill (D12) is where the tiers cash
out in the verdict: `suppress`ed preference findings never reach it; `acknowledge`d floor findings
arrive tagged, so the synthesizer lists them but does not let them drive a *block* — they sit below
the live Blockers as recorded, accepted deviations.

Implementation-wise this is a manifest-driven addition (D10's pattern): a new top-level concern in
`manifest.yaml` that regenerates a short, shared **"applying-team-preferences"** reference block
inlined into the router (and referenced, not duplicated, by lenses). No per-lens hand-editing; the
tier classification of checks rides along in the heuristics the generator already emits. Like the
router itself, this block is manifest-derived (`built_from: []`) so atlas docs-drift never flags it.

Absent the file, behavior is exactly today's: pure research defaults. No overlay is ever
auto-created (see §6).

## 6. Bootstrap — and the guardrail that matters most

Teams won't author this cold, so we offer two ways in. But the inference path carries a specific
hazard the user flagged: a **vibe-coded or haphazard codebase can *look* like it encodes deliberate
owner decisions when each "decision" was an unconsidered approve-click.** Naively inferring
preferences from such a repo would launder accidents into ratified standards — the worst possible
failure for a quality suite. The guardrail is therefore non-negotiable:

> **Inference is proposal-only. Nothing enters `preferences.md` without an explicit, per-item human
> decision.** The inference skill does not write the overlay. It produces an **interview**: a list of
> *candidate* preferences, each paired with the evidence it was inferred from and framed as a
> question — *"your code does X in ~80% of cases. Is that a deliberate house decision, or just how it
> ended up? If deliberate, say why."* The human ratifies (or rejects) each item; only ratified items
> are written.

Concretely:

- **Two entry paths, one safe default.**
  - *Template* — a documented `preferences.md` skeleton with commented examples of every directive
    kind. Hand-authored. Always available.
  - *Inference* — an opt-in skill (`proposing-team-preferences`, working name) that reads the repo
    (existing linter configs, recurring patterns, `CLAUDE.md`, ADRs) and emits a **proposal
    document**, never the live overlay.
- **Inference never runs by accident.** It is explicitly invoked ("help me set up my preferences");
  it is not triggered by a normal review, and the absence of an overlay never prompts auto-generation.
- **Descriptive ≠ prescriptive.** The proposal must separate *what the code does* (observation) from
  *what the rule should be* (recommendation), and force the human to ratify the jump. "Observed" is
  never silently promoted to "endorsed."
- **The file testifies to deliberation.** Each entry records provenance — a one-line rationale and a
  `decided` marker — so the overlay itself is evidence that each item was a considered choice, not a
  scraped pattern. (Optional `proposed:` staging entries can sit in the file commented-out until
  ratified, but only `decided` entries take effect.)

This directly answers the user's concern: the inference convenience exists, but it is structurally
incapable of writing a standard the owner didn't consciously choose.

## 7. Interaction with the regeneration loop

- The overlay lives in **someone else's repo**; the atlas's drift-checker, provenance hashes, and
  manifest never see it. No coupling.
- The *reader* (the router's preference block + per-check tier tags) is generated from
  `manifest.yaml` like everything else, so improving the research still regenerates cleanly.
- Tier classification (floor vs preference) becomes a small per-check attribute the generator emits
  from the heuristics — additive, doesn't disturb existing provenance.

## 8. Non-goals / out of scope (for this pass)

- No scoring or numeric "preference compliance %" — keeps Q4's vanity-metric failure mode out.
- No cross-repo / org-wide preference inheritance yet (a repo's overlay is self-contained; org
  defaults can come later as an include).
- No automatic enforcement that an `acknowledge` rationale is *true* — it's a recorded human claim,
  surfaced for audit, not adjudicated.
- The overlay does not let a team *add* novel checks the atlas doesn't have; it only modulates
  existing lenses. (New behaviors still come through the manifest/research pipeline.)

## 9. Open questions

- **Granularity of the tier tag.** Per-check is cleanest but adds manifest surface. Could start
  coarser (whole-lens floor/preference) and refine. → resolve during implementation planning.
- **Conflict between overlay and linter config** (e.g. overlay says "long functions fine," but
  `.rubocop.yml` caps method length). Proposed default: the *machine-enforced* config wins for
  things it actually gates in CI; the overlay governs the judgment layer above it. Needs a stated rule.
- **Discovery & precedence of multiple files** (root vs nested `.code-quality-atlas/` in a monorepo).
  Defer until someone needs monorepo scoping.
- **Whether `acknowledge` entries should expire / require periodic re-ratification** so standing
  exceptions don't rot. Lean: optional `review_by:` date, surfaced when stale. Defer.
