# Tool rules to triage — auditing-documentation-health

## Contents
- From category #22

## From category #22

### Tooling rules worth lifting
- **Vale (prose linter)** — style/terminology/readability rules over Markdown/docs; enforce a project glossary and banned terms. `(verify)`.
- **markdownlint** — `MD013` line length, `MD041` first line top-level heading, `MD034` bare URLs, `MD024` duplicate headings — structural doc hygiene. `(verify)` rule numbers.
- **ESLint `require-jsdoc` / `valid-jsdoc`** (deprecated in core) and **`eslint-plugin-jsdoc`** — `jsdoc/require-param`, `jsdoc/require-returns`, `jsdoc/check-param-names`, `jsdoc/require-description` — docstring completeness/accuracy vs. signature. `(verify)`.
- **Python — `pydocstyle` / Ruff `D` rules (pydocstyle)** — `D100` missing module docstring, `D103` missing function docstring, `D417` missing argument descriptions; **`interrogate`** for docstring *coverage* %. `(verify)`.
- **`darglint` (Python)** — checks docstring matches actual params/returns/raises (drift detector). `(verify)`.
- **Go — `golint`/`revive` `exported` rule** — exported identifiers must have a doc comment starting with the name; **`godoc`/`pkgsite`** renders it. `(verify)`.
- **Rust — `missing_docs` lint + `cargo doc`/rustdoc doctests** — examples in `///` docs are compiled and *run* as tests, preventing example rot. `(verify)`.
- **`adr-tools` (Nygard) / `log4brains`** — scaffold, number, and supersede ADRs; enforce the ADR template and an index. `(verify)`.
- **Doc-link / dead-link checkers** — `lychee`, `markdown-link-check` — fail CI on broken internal/external links. `(verify)`.
- **`commitlint` + `conventional-changelog` / `release-please` / `git-cliff`** — generate changelog entries from conventional commits, keeping CHANGELOG in lockstep with releases. `(verify)`.
