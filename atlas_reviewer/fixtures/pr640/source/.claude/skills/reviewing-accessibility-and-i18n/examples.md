# Examples — reviewing-accessibility-and-i18n

Accessibility and internationalization sit in one lens because they fail the same
way: the code works for the author's keyboard, locale, and eyesight. Name each
barrier separately — the inputs below each carry several — saying who it excludes
and citing the standard where one applies (a WCAG success criterion, an ICU or
`Intl` API). Two things are deliberately **not** findings, and the examples say so
rather than leaving it to inference: native semantics that already express a role
need no ARIA on top, and a decorative icon hidden from assistive tech is correct.
"No findings" means the change has a user-facing surface and every applicable
check passes; a change that renders no UI and localizes no strings is out of scope
entirely — say the lens did not apply, in one line, rather than reaching for
something.

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

## Good → no finding (skipped — no rendered surface, no localized strings)

**Input (diff):** a change to a job queue's retry/backoff policy and its metrics
labels. No components, no templates, no user-facing copy.

**Expected finding:**

```text
reviewing-accessibility-and-i18n: not applicable — no rendered surface and no
user-facing strings in this change (queue retry policy and metric labels only).
```

One line, and stop. A backend diff will yield *something* if you hunt for it —
a log message that "should be translated", a metric label that "users might
see" — and manufacturing those is the fastest way to get this lens muted before
the change that needed it. Note the boundary: **operator-facing** output (logs,
metrics, error text read by an on-call engineer) is not user-facing copy and
does not belong to this lens.

<!-- GENERATED — do not hand-edit this file. Vendored by tooling/vendor-skills.sh
     from skills/reviewing-accessibility-and-i18n/examples.md in code-quality-atlas.
     Edit that file and re-run tooling/vendor-skills.sh to refresh this copy. -->
