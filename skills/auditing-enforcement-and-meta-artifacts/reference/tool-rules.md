# Tool rules to triage — auditing-enforcement-and-meta-artifacts

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #30

## From category #30

### Tooling rules worth lifting

- **ESLint** — `--report-unused-disable-directives` (CI flag); `eslint-comments/no-unlimited-disable`, `/no-unused-disable`, `/require-description`, `/no-aggregating-enable`.
- **Ruff `RUF100`**, **flake8-noqa**, **pygrep-hooks** `python-check-blanket-noqa` (PGH004) + `python-check-blanket-type-ignore` (PGH003) — ban blanket suppressions in pre-commit.
- **mypy** `warn_unused_ignores`, **pyright** `reportUnnecessaryTypeIgnoreComment` — sweep dead ignores; **TypeScript** `@ts-expect-error` (errors if unused) over `@ts-ignore`.
- **Baseline trackers** — detekt `baseline`, Android `lint-baseline.xml`, ESLint bulk-suppressions, `betterer` — and a CI check that the baseline count is **non-increasing**.
- **`pint` / `promtool check rules`** — alert-rule linters (missing `for:`/labels/runbook, broken PromQL); **grafana/dashboard linters**; **`terraform validate`/`plan`** for monitors-as-code drift.
- **Codegen drift gate** — `make generate && git diff --exit-code` (or `go generate`, `buf generate`, `sqlc diff`) as a required CI job; `linguist-generated`/`.gitattributes` to mark and exclude generated files from review noise.
