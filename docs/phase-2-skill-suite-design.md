# Phase 2 — Skill-Suite Architecture (design)

**Status:** design, 2026-06-09. Awaiting review before implementation planning.
**Depends on:** phase-1 research (taxonomy v0.2 + verified `docs/research/cluster-*.md`).
**Governing decisions:** D6 (docs are source of truth; skills derived & regenerable), D7 (Agent-Skills best practices: progressive disclosure, auto-trigger, model portability), D8 (eval-first). See [`open-questions.md`](open-questions.md).

---

## 1. Purpose

Turn the verified research into a **suite of code-review & maintenance agent skills** that:
1. are **derived from** and **traceable to** the taxonomy + research (the canonical source);
2. **regenerate/refine** as the research improves — async doc critique compounds into better skills, instead of skills drifting;
3. follow **Agent-Skills best practices** and work **across models down to ~8B local** (not Claude-only);
4. stay **easy to re-granularize** as model capability and cost change.

Non-goal: build all behaviors at once, or hand-author skills that lose their link to the research.

## 2. Core architecture

Four moving parts, with one **adaptation lever** (the manifest):

```
 SOURCE OF TRUTH                 ADAPTATION LEVER            DERIVED ARTIFACTS
 docs/taxonomy.md        ┐                                   skills/<gerund>/
 docs/research/          ├──▶  skills/manifest.yaml  ──gen──▶   SKILL.md (+provenance)
   cluster-*.md          ┘     (behavior↔category map)          reference/*.md
                                                                examples.md, evals/
```

### 2.1 The skill manifest — `skills/manifest.yaml` (the adaptation point)

One file declares the whole suite. Re-granularizing = editing this file + regenerating; the research and (mostly) the hand-refined prose are untouched.

```yaml
skills:
  - name: hunting-silent-failures          # gerund, lowercase-hyphen, no "claude"/"anthropic"
    description: >                          # 3rd person, ≤1024 chars, explicit triggers — see D7
      Reviews changes for swallowed errors, empty catch/rescue blocks, silent
      fallbacks, and missing timeouts/retries. Use when reviewing error handling,
      try/catch, rescue, promise rejection, fallback, or resilience code.
    shape: diff                            # diff | repo (cron-shaped, map-gaps G7)
    wave: 1                                 # build order
    built_from:                            # provenance — the drift-checker watches these
      - { category: 2, source: docs/research/cluster-1-correctness.md#2 }
      - { category: 4, source: docs/research/cluster-1-correctness.md#4 }
```

The `built_from` set is the many-to-many behavior→category mapping made machine-checkable. It is the single source for both generation and drift detection.

### 2.2 Generator — `tooling/generate.*`

Input: the manifest + the referenced research sections. Output per skill: a `SKILL.md` (lean) + `reference/*.md` (pulled from the declared research sections) + draft `evals/eval.json`, with each source section's **hash stamped into `SKILL.md` provenance**. Deterministic and re-runnable.

### 2.3 Refinement (human + agent)

Sharpen `SKILL.md` `description` (triggering) and the top-level checklist; add concrete `examples.md`. `reference/*` stays close to source so regeneration stays clean. (Mirrors the doc's Claude-A-authors / Claude-B-tests loop.)

### 2.4 Drift-checker — `tooling/drift.*`

Recompute each `built_from` section's hash against the current docs. Mismatch ⇒ report: *"skill X built from sections that changed (§2, §4) — regenerate `reference/*` + re-run evals."* Runs on demand / in CI / on a schedule. **This is the bridge from async doc-critique to skill updates.**

### 2.5 Evals as the regeneration safety net (D8)

Each skill ships ≥3 scenarios (`query` + `expected_behavior`, with a no-skill baseline). Regeneration loop: **docs change → drift flags skill → regenerate → re-run evals → green = restamp, red = flag human.** Evals are written before skill prose.

## 3. Skill anatomy (D7 — progressive disclosure + portability)

```
skills/hunting-silent-failures/
├── SKILL.md            # LEAN entry point (<500 lines, aim ≪) — loaded on trigger
│                       #   frontmatter: name · description · provenance{taxonomy_version, built_from[]{category,source,hash}}
│                       #   body: when-to-use · short top-level checklist · one-level-deep links ↓
├── reference/
│   ├── heuristics.md   # full reviewable-heuristics checklist   ← research §heuristics
│   ├── tool-rules.md   # static-analysis rules to triage        ← research §tooling
│   └── sources.md      # references / "what to mine"            ← research §references
├── examples.md         # concrete good/bad input→finding pairs
└── evals/eval.json     # ≥3 scenarios + baseline
```

Rules (from best-practices doc):
- `SKILL.md` body **< 500 lines**; references **one level deep**; reference files **>100 lines get a ToC**.
- `description`: third person, specific, "what it does AND when," explicit trigger keywords.
- `name`: gerund, lowercase-hyphen, ≤64 chars, no `claude`/`anthropic`.
- Forward-slash paths only; no time-sensitive text (use an "old patterns" `<details>` block); consistent terminology.
- **Portability:** `SKILL.md` lean for cheap context + crisp triggering (helps weak selectors); the explicit, concrete, checklist-style detail an ~8B model needs lives in `reference/*`, loaded only on fire. Provide one default approach, not option-menus. Concrete `examples.md` carries the most weight for weak models.
- **Degrees of freedom:** high-freedom prose for judgment skills (e.g. restraint, readability); low-freedom exact checklists/scripts for fragile, high-stakes ones (e.g. migration safety).

## 4. The behaviors (from Section B)

22 behaviors covering all 27 categories. ★ = build-first (LLM-judgment where linters don't help, map-gaps G5). The manifest holds the authoritative list; this is the seed.

**Diff-shaped (run on a change):**
1. Tracing correctness & invariants — #1,#4
2. ★ Hunting silent failures & resilience — #2 (#4)
3. Reviewing concurrency & async — #3
4. ★ Reviewing naming & readability — #5,#6,#7
5. Checking idioms & consistency — #8 (+ecosystem packs, G6)
6. ★ Reviewing module design & types — #9,#10
7. ★ Checking restraint ("is this too much?") — #11,#15-cw
8. Reviewing API & contract safety — #13
9. Sweeping for security — #14
10. Reviewing performance & efficiency — #15
11. Reviewing observability & operability — #16
12. ★ Reviewing LLM integration — #25 (#27)
13. Reviewing test quality — #17
14. Reviewing migration & data safety — #20 (#2,#3)
15. Reviewing accessibility & i18n — #23
16. Reviewing PR & process hygiene — #24,#22

**Repo/cron-shaped (run on the whole repo, scheduled — G7):**
17. Auditing architecture conformance — #12
18. Auditing dependencies & supply chain — #18,#27
19. ★ Finding maintainability hotspots — #21 (VCS-aware)
20. Auditing config & build hygiene — #19,#26
21. Auditing documentation health — #22
22. Auditing compliance & provenance — #27 (detect + escalate, G8)

**Build waves:** Wave 1 = the 6 ★ (highest unique value). Wave 2 = high-stakes triage (security, migration, performance, tests, a11y). Wave 3 = remainder + cron-shaped. Each wave regenerates from the same docs; the manifest sets `wave`.

## 5. Repo additions

```
skills/
├── manifest.yaml            # the adaptation lever
└── <gerund-name>/ …         # generated + refined skills
tooling/
├── generate.*               # manifest + research → skills
├── drift.*                  # provenance hashes vs current docs → drift report
└── run-evals.*              # execute a skill's evals vs baseline
docs/ …                      # unchanged source of truth
```

Skills are plain markdown+files — **harness/model-agnostic**; optionally wrapped as a Claude Code plugin later for one-command install (Q12).

## 6. How adaptation works (the thing we're paving for)

- **Research improves** (async critique) → `drift.*` lists affected skills → regenerate `reference/*` → `run-evals.*` → restamp or flag. Compounding loop.
- **Granularity changes** (model/cost shift) → edit `manifest.yaml` (merge/split skills, re-map categories) → regenerate. No research edits, minimal prose loss.
- **New category / taxonomy bump** → update `built_from` references → regenerate affected skills.
- **New model target** (e.g. an 8B) → add to the eval matrix; tighten `reference/*` explicitness where evals regress.

## 7. Open questions to resolve in planning

- **Q10/Q11 mechanics:** generator + drift-checker implementation language/format (likely a small script set; hashing granularity = per `#n` section).
- **Q12 packaging:** in-repo `skills/` now; plugin-wrap when/if. Versioning scheme (repo tags + `taxonomy_version` in provenance).
- **Naming finalization:** gerund names per skill (manifest).
- **G1 single-owner enforcement:** encode "who owns CVE / PII / feature-flags" so two skills don't double-report (manifest can mark a `primary` owner; others `cross_ref`).
- **Eval harness:** the best-practices doc notes there's no built-in runner — we define `run-evals.*` and the rubric format.
- **Cross-cutting "old patterns" / deprecations:** none yet; keep the `<details>` convention ready.

## 8. Definition of done for phase 2 (wave 1)

- `skills/manifest.yaml` with the 6 ★ skills fully specified (name, description, `built_from`, evals listed).
- `tooling/generate.*` + `tooling/drift.*` + `run-evals.*` working end-to-end on those 6.
- 6 skills generated, refined, with ≥3 passing evals each, tested on at least two model tiers (incl. one small/local-class model).
- A documented "regenerate after a docs change" runbook proving the compounding loop (edit a research section → drift → regenerate → evals green).
