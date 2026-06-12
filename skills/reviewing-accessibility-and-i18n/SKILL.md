---
name: reviewing-accessibility-and-i18n
description: 'Reviews UI changes for accessibility and internationalization: semantic
  HTML vs div-with-onclick, keyboard operability and focus management, accessible
  names on icon buttons and inputs, contrast, ARIA misuse, hardcoded user-facing strings,
  naive pluralization, non-locale-aware number/date/currency formatting, and RTL-unsafe
  layout. Use when reviewing components, templates, markup, forms, modals, UI text,
  or anything user-facing. Skip on changes with no user-facing surface — backend,
  CLI, library, or infra code with no rendered UI or localized strings.'
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 23
    source: docs/research/cluster-6-evolution.md#23
    hash: 1d4b12bc8ee70d17f5cd6ce9cb93b33ebc902036e220f3e16f5c3cd6dd7bd98e
---

# reviewing-accessibility-and-i18n

*Can everyone use this UI? Keyboard, screen readers, contrast, locales, RTL.*

## When to use

Reviews UI changes for accessibility and internationalization: semantic HTML vs div-with-onclick, keyboard operability and focus management, accessible names on icon buttons and inputs, contrast, ARIA misuse, hardcoded user-facing strings, naive pluralization, non-locale-aware number/date/currency formatting, and RTL-unsafe layout. Use when reviewing components, templates, markup, forms, modals, UI text, or anything user-facing. Skip on changes with no user-facing surface — backend, CLI, library, or infra code with no rendered UI or localized strings.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Semantic-first:** is a real `<button>`/`<a>`/`<nav>`/`<main>`/heading used, or a `<div>` with a click handler? Native element = keyboard + role + focus for free.
- **Keyboard operable:** can every interactive element be reached and activated by Tab/Shift-Tab/Enter/Space/Escape/arrows as appropriate? No mouse-only handlers (click without key handler).
- **Focus management:** after opening a modal/menu/route change, does focus move sensibly and return on close? Is focus trapped in the dialog? Is `:focus-visible` styling present (not `outline:none` with no replacement)?
- **Name/role/value:** do icon-only buttons, inputs, and custom widgets have accessible names (label, `aria-label`, `aria-labelledby`)? No empty buttons/links.
- **Contrast:** does new text/UI meet 4.5:1 (or 3:1 large / non-text)? Check both themes if dark mode exists.
- **Images & media:** meaningful images have descriptive `alt`; decorative images have empty `alt=""`; videos have captions/transcript where required.
- **ARIA discipline:** is ARIA only used where native HTML can't express it, with all required states (e.g. `aria-expanded`, `aria-selected`) wired and *updated*? No redundant/conflicting roles.
- **No hardcoded user-facing strings:** is every new UI string going through the i18n catalog (no literal JSX/template text)? Includes aria-labels, placeholders, error messages, pluralized/templated text.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
