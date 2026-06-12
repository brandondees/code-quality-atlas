---
name: checking-idioms-and-consistency
description: 'Checks that a change follows the project''s own conventions and the
  language/framework''s idioms: formatter applied, idiomatic constructs over clumsy
  equivalents, recurring problems solved the same way the codebase already does, no
  second parallel way to do the same thing, consistent naming/casing/imports/file
  layout. Use when reviewing style, conventions, idioms, framework usage, or consistency
  with the rest of the codebase.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 8
    source: docs/research/cluster-2-readability.md#8
    hash: a934a90b32a30d4a4239c9285e13651166bb062db40fc06ecc68e356b54d4c79
---

# checking-idioms-and-consistency

*Does this look like the rest of the codebase? Conventions, idioms, no second parallel way.*

## When to use

Checks that a change follows the project's own conventions and the language/framework's idioms: formatter applied, idiomatic constructs over clumsy equivalents, recurring problems solved the same way the codebase already does, no second parallel way to do the same thing, consistent naming/casing/imports/file layout. Use when reviewing style, conventions, idioms, framework usage, or consistency with the rest of the codebase.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

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

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
