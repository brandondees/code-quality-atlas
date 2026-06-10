# Examples — reviewing-accessibility-and-i18n

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
