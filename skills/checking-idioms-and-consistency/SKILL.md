---
name: checking-idioms-and-consistency
description: 'Checks that a change follows the project''s own conventions and the
  language/framework''s idioms: formatter applied, idiomatic constructs over clumsy
  equivalents, recurring problems solved the same way the codebase already does, no
  second parallel way to do the same thing, consistent naming/casing/imports/file
  layout. Use when reviewing style, conventions, idioms, framework usage, or consistency
  with the rest of the codebase.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 8
    source: docs/research/cluster-2-readability.md#8
    hash: a934a90b32a30d4a4239c9285e13651166bb062db40fc06ecc68e356b54d4c79
---

# checking-idioms-and-consistency

## When to use

Checks that a change follows the project's own conventions and the language/framework's idioms: formatter applied, idiomatic constructs over clumsy equivalents, recurring problems solved the same way the codebase already does, no second parallel way to do the same thing, consistent naming/casing/imports/file layout. Use when reviewing style, conventions, idioms, framework usage, or consistency with the rest of the codebase.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
