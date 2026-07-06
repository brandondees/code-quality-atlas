---
name: checking-idioms-and-consistency
description: 'Checks that a change follows the project''s own conventions and the
  language/framework''s idioms: formatter applied, idiomatic constructs over clumsy
  equivalents, recurring problems solved the same way the codebase already does, no
  second parallel way to do the same thing, consistent naming/casing/imports/file
  layout. Use when reviewing style, conventions, idioms, framework usage, or consistency
  with the rest of the codebase.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 8
    source: docs/research/cluster-2-readability.md#8
    hash: 26d5c0f70c305c571b1ae79d07106c45872ee33c0d456c2ee51a997dab0ddf1a
---

# checking-idioms-and-consistency

*Does this look like the rest of the codebase? Conventions, idioms, no second parallel way.*

## When to use

Checks that a change follows the project's own conventions and the language/framework's idioms: formatter applied, idiomatic constructs over clumsy equivalents, recurring problems solved the same way the codebase already does, no second parallel way to do the same thing, consistent naming/casing/imports/file layout. Use when reviewing style, conventions, idioms, framework usage, or consistency with the rest of the codebase.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Does the change **follow the project's own conventions**? Read `.eslintrc`/`.rubocop.yml`/`ruff.toml`/`.editorconfig`/style guide first; the codebase's established choice wins over personal preference.
- Is the code **formatted** by the project's formatter? (Unformatted code where Prettier/Black/gofmt exists is an automatic finding.)
- Does it use the **idiomatic construct** for this language/framework, or a clumsy non-native equivalent? (comprehension vs. manual loop; `Result`/error-as-value vs. exceptions where one was chosen; framework router/ORM idiom vs. hand-rolled.)
- **Pattern consistency**: does this solve a recurring problem the *same way* the codebase already does (error shape, DTO/serialization, DI style, test layout)? Divergence needs a stated reason.
- Are **naming/casing conventions** uniform across the symbol kind? No mixed `snake_case`/`camelCase` for one role (cross-links #5).
- Import ordering / module structure / file layout consistent with siblings? (New file where a reader expects it.)
- Are strings/messages/log formats consistent with existing ones (cross-links #16)?
- Does it avoid introducing a **second way to do the same thing** (a parallel util, competing abstraction) when one exists (cross-links #11/#9)?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
