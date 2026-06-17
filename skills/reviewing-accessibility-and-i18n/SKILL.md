---
name: reviewing-accessibility-and-i18n
description: 'Reviews UI changes for accessibility and internationalization: semantic
  HTML vs div-with-onclick, keyboard operability and focus management, accessible
  names on icon buttons and inputs, contrast, ARIA misuse, hardcoded user-facing strings,
  naive pluralization, non-locale-aware number/date/currency formatting, and RTL-unsafe
  layout. Use when reviewing components, templates, markup, forms, modals, UI text,
  or anything user-facing. Skip when the change has no user-facing surface — backend,
  CLI, library, or infra code with no rendered UI or localized strings.'
provenance:
  taxonomy_version: v0.4
  built_from:
  - category: 23
    source: docs/research/cluster-6-evolution.md#23
    hash: a02904ad82b6ea769857880ee0150fd9d19c068d1c8aa3be15ae113b891ad420
---

# reviewing-accessibility-and-i18n

*Can everyone use this UI? Keyboard, screen readers, contrast, locales, RTL.*

## When to use

Reviews UI changes for accessibility and internationalization: semantic HTML vs div-with-onclick, keyboard operability and focus management, accessible names on icon buttons and inputs, contrast, ARIA misuse, hardcoded user-facing strings, naive pluralization, non-locale-aware number/date/currency formatting, and RTL-unsafe layout. Use when reviewing components, templates, markup, forms, modals, UI text, or anything user-facing. Skip when the change has no user-facing surface — backend, CLI, library, or infra code with no rendered UI or localized strings.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

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

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
