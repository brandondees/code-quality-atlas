# References to mine — auditing-enforcement-and-meta-artifacts

## Contents

- From category #30

## From category #30

### Key references

- **ESLint — disable-directive hygiene** — `--report-unused-disable-directives`; `eslint-comments` plugin (`no-unlimited-disable`, `no-unused-disable`, `require-description`).
  → mine: a file-wide `/* eslint-disable */` with no rule list disables *everything*; require rule-scoped (`eslint-disable-next-line rule-name`), described, and unused-directive-swept suppressions.
- **Ruff / flake8 / pygrep-hooks — `noqa` discipline** — Ruff `RUF100` (unused noqa); pre-commit `python-check-blanket-noqa` (PGH004) and `python-check-blanket-type-ignore` (PGH003).
  → mine: a bare `# noqa` suppresses *all* lints on the line; require `# noqa: E501` (code-specific) with a reason. Bare `# type: ignore` likewise hides newly-introduced type errors.
- **mypy / pyright — unused-ignore detection** — mypy `warn_unused_ignores = true`; pyright `reportUnnecessaryTypeIgnoreComment`.
  → mine: a stale `# type: ignore` masks the *next* real type error at that spot; sweep unused ignores. Require error-code form `# type: ignore[arg-type]`.
- **Lint baselines & the ratchet pattern** — detekt `baseline.xml`, Android `lint-baseline.xml`, ESLint bulk-suppressions, `betterer` ("quality ratchet").
  → mine: a baseline *freezes* existing violations so new code is clean; it is healthy only while it **shrinks**. A growing baseline is silent debt accrual — track the entry count as a *trend*, and gate "new suppression needs a reason / issue link / expiry."
- **Google SRE — "Alerting on SLOs" (SRE Workbook ch. 5) + Rob Ewaschuk, "My Philosophy on Alerting"** — https://sre.google/workbook/alerting-on-slos/ .
  → mine: alert on **symptoms** (user-visible SLO/error-budget burn), not causes (raw CPU); every page must be **actionable** and link a runbook; unactionable/noisy alerts train responders to ignore the pager.
- **Prometheus rule & dashboard linting** — Cloudflare `pint`, `promtool check rules`, Grafana/Datadog monitors-as-code (Terraform, grafonnet).
  → mine: lint alert rules for missing `for:`, missing severity/labels, broken queries, and absent runbook annotations; define monitoring **as code** so it is versioned, reviewable, and restorable rather than click-ops that drift.
- **Codegen freshness gate** — the `go generate ./... && git diff --exit-code` pattern; protobuf/`buf`, OpenAPI, sqlc, Prisma codegen.
  → mine: a checked-in generated artifact must be regenerated and `git diff --exit-code`-verified in CI; without that gate it silently diverges from its source/spec. Mark generated files as generated (`linguist-generated`) so humans don't hand-patch what the next regen clobbers.
