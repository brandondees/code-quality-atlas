---
name: reviewing-accessibility-and-i18n
description: 'Reviews UI changes for accessibility and internationalization: semantic
  HTML vs div-with-onclick, keyboard operability and focus management, accessible
  names on icon buttons and inputs, contrast, ARIA misuse, hardcoded user-facing strings,
  naive pluralization, non-locale-aware number/date/currency formatting, and RTL-unsafe
  layout. Use when reviewing components, templates, markup, forms, modals, UI text,
  or anything user-facing.'
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 23
    source: docs/research/cluster-6-evolution.md#23
    hash: 1d4b12bc8ee70d17f5cd6ce9cb93b33ebc902036e220f3e16f5c3cd6dd7bd98e
---

# reviewing-accessibility-and-i18n

## When to use

Reviews UI changes for accessibility and internationalization: semantic HTML vs div-with-onclick, keyboard operability and focus management, accessible names on icon buttons and inputs, contrast, ARIA misuse, hardcoded user-facing strings, naive pluralization, non-locale-aware number/date/currency formatting, and RTL-unsafe layout. Use when reviewing components, templates, markup, forms, modals, UI text, or anything user-facing.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
