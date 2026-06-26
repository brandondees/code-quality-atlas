# reviewing-accessibility-and-i18n

Can everyone use this UI? Keyboard, screen readers, contrast, locales, RTL.

## When to use

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Checklist

## From category #23

### Reviewable heuristics (skill-checklist seeds)

- **Semantic-first:** is a real `<button>`/`<a>`/`<nav>`/`<main>`/heading used, or a `<div>` with a click handler? Native element = keyboard + role + focus for free.
- **Keyboard operable:** can every interactive element be reached and activated by Tab/Shift-Tab/Enter/Space/Escape/arrows as appropriate? No mouse-only handlers (click without key handler).
- **Focus management:** after opening a modal/menu/route change, does focus move sensibly and return on close? Is focus trapped in the dialog? Is `:focus-visible` styling present (not `outline:none` with no replacement)?
- **Name/role/value:** do icon-only buttons, inputs, and custom widgets have accessible names (label, `aria-label`, `aria-labelledby`)? No empty buttons/links.
- **Contrast:** does new text/UI meet 4.5:1 (or 3:1 large / non-text)? Check both themes if dark mode exists.
- **Images & media:** meaningful images have descriptive `alt`; decorative images have empty `alt=""`; videos have captions/transcript where required.
- **ARIA discipline:** is ARIA only used where native HTML can't express it, with all required states (e.g. `aria-expanded`, `aria-selected`) wired and *updated*? No redundant/conflicting roles.
- **No hardcoded user-facing strings:** is every new UI string going through the i18n catalog (no literal JSX/template text)? Includes aria-labels, placeholders, error messages, pluralized/templated text.
- **Pluralization & interpolation:** are plurals/gender handled via ICU/`Intl.PluralRules` (not `count + "s"`), and do interpolation placeholders match across all locale files?
- **Locale-aware formatting:** are numbers/dates/currency/units formatted via `Intl`/CLDR with explicit locale + currency, not hand-built strings or assumed `en-US`/`USD`? (cross-links #4 money/units correctness.)
- **RTL & expansion:** does layout use logical properties / direction-agnostic CSS, and tolerate ~30–40% text expansion and longer words without clipping/overlap? Mirrored icons where directional.
- **Responsive/edge layouts:** does it hold up at small/large viewports, 200% zoom, and long-content edge cases without loss of content or function (WCAG 1.4.10 Reflow, 1.4.4 Resize Text)? `(verify)`.
- **Target size:** are interactive targets ≥24×24px (WCAG 2.2 2.5.8) with adequate spacing? `(verify)`.
- **Document language:** is `<html lang>` set/updated, and per-element `lang` on foreign-language runs?
- **Design fidelity vs. spec:** does the implementation match the design/spec for spacing, states (hover/focus/disabled/error), and content — flag silent deviations.

---

## Examples

## Bad → finding

**Input (diff):**

```jsx
<div className="btn" onClick={save} style={{ outline: "none" }}>
  <SaveIcon />
</div>
<img src={chart} />
```

**Expected finding:** Non-semantic interactive element: a `<div>` with `onClick` has
no keyboard activation, no focusability, and no role — use `<button>` (native gives
all three for free). Icon-only control has no accessible name — add an `aria-label`
(from the i18n catalog, not a literal). `outline: none` removes the focus indicator
with no replacement (WCAG 2.4.7 Focus Visible). The chart `<img>` has no `alt`:
describe it if meaningful, `alt=""` if decorative.

## Bad → finding

**Input (diff):**

```jsx
function CartBadge({ count, price }) {
  return (
    <span>
      You have {count} item{count === 1 ? "" : "s"} — total ${price.toFixed(2)}
    </span>
  );
}
```

**Expected finding:** Hardcoded user-facing string — route it through the i18n
catalog. `count + "s"` pluralization breaks in most locales (many have more than
two plural forms) — use ICU MessageFormat / `Intl.PluralRules`. `"$" + toFixed(2)`
hand-builds a money string assuming USD and en-US formatting — use
`Intl.NumberFormat(locale, { style: "currency", currency })` with both passed in,
never assumed.

## Good → no finding

**Input (diff):**

```jsx
<button onClick={save} aria-label={t("editor.save")}>
  <SaveIcon aria-hidden="true" />
</button>
<p>{new Intl.NumberFormat(locale, { style: "currency", currency }).format(total)}</p>
```

**Expected finding:** None — native `<button>` (keyboard + role + focus), an
accessible name from the i18n catalog, the decorative icon hidden from assistive
tech, and locale-aware currency formatting with locale and currency as inputs.
Report "No findings". Do NOT demand ARIA on elements whose native semantics already
express the role (no `role="button"` on `<button>`), and do NOT flag the icon's
`aria-hidden` — hiding a decorative icon is correct, not an omission.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
