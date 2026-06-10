# Tool rules to triage — reviewing-accessibility-and-i18n

## Contents
- From category #23

## From category #23

### Tooling rules worth lifting
- **axe-core** rule ids — `color-contrast`, `image-alt`, `label`, `button-name`, `link-name`, `html-has-lang`, `aria-required-attr`, `aria-roles`, `aria-allowed-attr`, `duplicate-id-aria`, `frame-title`, `list`, `region`, `landmark-one-main`. *(core ids verified at dequeuniversity.com/rules/axe; full set is ~90+ rules.)*
- **eslint-plugin-jsx-a11y** — `alt-text`, `anchor-is-valid`, `aria-props`, `aria-role`, `role-has-required-aria-props`, `no-noninteractive-element-interactions`, `click-events-have-key-events`, `no-autofocus`, `label-has-associated-control`, `tabindex-no-positive`. *(verified at github.com/jsx-eslint/eslint-plugin-jsx-a11y; static JSX checker — pair with @axe-core/react for rendered-DOM checks.)*
- **Lighthouse / Pa11y / Pa11y-CI** — automated axe/HTML_CodeSniffer audits in CI with score thresholds; WCAG2AA ruleset selection. `(verify)`.
- **i18n string-extraction linters** — `eslint-plugin-i18next` `no-literal-string`; `eslint-plugin-formatjs` (`enforce-id`, `no-literal-string-in-jsx` `(verify)`); `eslint-plugin-react-intl` — flag hardcoded user-facing strings.
- **`i18n-ally` / `i18next-parser` / Pontoon-style checks** — detect missing/extra/untranslated keys, interpolation mismatches between locales. `(verify)`.
- **`eslint-plugin-formatjs` `no-multiple-plurals` / ICU syntax validation** — catch broken MessageFormat / plural usage. `(verify)`.
- **CSS logical-properties lints / `stylelint`** — prefer `margin-inline`/`padding-block` over `left/right` for RTL safety; **`csslint`/`stylelint`** `unit-no-unknown`. `(verify)`.
- **HTML validators (Nu Html Checker / `html-validate`)** — `element-required-attributes`, `no-implicit-button-type`, heading-order, `wcag/h37` (img needs alt), `wcag/h30`. `(verify)`.
- **Storybook a11y addon / `@storybook/addon-a11y`** — per-component axe checks in dev/CI. `(verify)`.
