# Executing Cited Checks — Phase 1 Implementation Plan

**Status: implemented (2026-09-01).** Built directly (no subagent task-by-task
execution) — the change is small and reversible enough that a full checkbox
plan would itself be the ceremony [`docs/executing-cited-checks.md`](../executing-cited-checks.md)
warns against. This doc is the dated, `built_from`-clean record the design
doc's closing section asked for.

**Goal:** Ship Phase 1 of the [`executing-cited-checks.md`](../executing-cited-checks.md)
proposal for [`open-questions.md`](../open-questions.md) Q22 — M1, the
standing-dispute check — plus a meta-review eval seed, so the synthesizer
stops affirming a claim that is already disputed on the record instead of
silently re-deriving it.

**Architecture:** `synthesizing-review-findings` is generated purely from
`skills/manifest.yaml` (`built_from: []`, D12) via `build_synthesizer_md` in
[`tooling/generate_synthesizer.py`](../../tooling/generate_synthesizer.py).
That one function is reused by both the standalone skill and
`generate_collapsed.py`'s `reference/synthesis.md` bundle for all four
collapsed entrypoints, so a single prose edit there reaches every surface —
no manifest schema change needed, matching how the Q15 decision-record
checklist shipped as generator-level prose. Eval scenarios live in
`skills/synthesizing-review-findings/evals/eval.json`, already above D8's
3-scenario baseline (9 scenarios), so no `eval_min` change was required —
`python -m tooling.cli eval` uses the D8 default floor for this skill.

**Tech Stack:** Python 3.11+, PyYAML, pytest; generated artifacts are plain
markdown + JSON (D7).

---

## What shipped

1. **`tooling/generate_synthesizer.py`** — added a paragraph to the
   `## Reviewer discipline` section: before affirming any claim not
   independently re-derived, scan the PR's existing comment threads and
   prior review rounds for a standing dispute of that exact claim; if one
   exists, treat the claim as unresolved rather than settled. Explicitly
   does not flip to "defer to the disputing comment automatically" — the
   review still adjudicates, it just cannot skip the adjudication. This is
   M1 from the design doc, placed exactly where the doc recommended
   (`synthesizing-review-findings`, a `Reviewer discipline` bullet) and
   rejected the two alternatives it considered (a per-entrypoint
   `tool-evidence.md` copy; a new shared reference file).
2. **`skills/synthesizing-review-findings/evals/eval.json`** — added 3 new
   scenarios in the meta-review / transcript-input shape the design doc's
   "How would we know it worked?" sub-question anticipated:
   - a direct reconstruction of PR [#253](https://github.com/brandondees/code-quality-atlas/pull/253)
     (an S3 canned-ACL claim already disputed by a standing comment minutes
     before the affirmation) — the target the design doc names as this
     phase's cheapest, most mechanically-preventable case;
   - a precision check that the discipline does not invent phantom
     disputes or add ceremony to a finding that was never previously
     affirmed or disputed;
   - a boundary check distinguishing a **resolved** historical objection
     (superseded by a later fix and a confirming comment) from a **standing**
     one, so the check does not freeze on stale history.
3. Regenerated (`python -m tooling.cli generate`), re-vendored
   (`tooling/vendor-skills.sh .`), and verified: `tooling.cli drift` reports
   no drift, `tooling.cli eval --skill synthesizing-review-findings` passes
   at 12 scenarios, `pytest` (451/451) and `markdownlint-cli2` (0 issues) are
   clean on the touched files.

## Not in this phase

Everything the design doc scoped to Phase 2 or out of scope: M2
(falsification attempts on affirmatively-applied, greppable rule classes,
e.g. authoring rule 1's absolutes) stays deferred pending Phase 1 producing
signal and a non-self-authored instance (or an eval standing in for one); no
change to lens selection or to any other skill; no manifest schema change.

## Cross-model re-gate

Not run as part of this phase. The design doc frames M1's evidence bar as
"Phase 1 producing signal," not a pre-ship gate the way a new lens's
`eval_min` raise is gated — this is 3 scenarios added to an already-baseline
skill, not a hardened floor claim. A cross-model re-gate remains a
reasonable follow-up once real usage (or a dedicated re-gate session with
Ollama access) is available, consistent with how several other lenses in
this repo's history shipped a cross-model gate as a same-day or later
follow-up rather than a hard prerequisite.
