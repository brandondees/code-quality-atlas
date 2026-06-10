# Tool rules to triage — reviewing-pr-and-process-hygiene

## Contents
- From category #24
- From category #22

## From category #24

### Tooling rules worth lifting
- **commitlint (`@commitlint/config-conventional`)** — `type-enum`, `subject-empty`, `subject-full-stop`, `header-max-length` (72), `body-leading-blank`, `footer-leading-blank` — enforce Conventional Commits. *(`@commitlint/config-conventional` `type-enum`: build, chore, ci, docs, feat, fix, perf, refactor, revert, style, test — verified.)*
- **gitlint** — `title-max-length`, `title-must-not-contain-word` (e.g. "WIP"), `body-min-length`, `title-imperative-mood` `(verify)` — Python-side commit hygiene.
- **Danger / Danger JS** — custom PR rules: warn on large diffs, missing tests for changed src, missing CHANGELOG entry, PR description present, no `fixup!`/`WIP` commits. `(verify)`.
- **GitHub branch protection / rulesets** — required reviews, required CODEOWNERS review, required status checks, linear history, signed commits, dismiss-stale-approvals. `(verify)`.
- **`pre-commit` framework hooks** — `no-commit-to-branch`, `check-merge-conflict`, `forbid-new-submodules`, `check-added-large-files`, conventional-commit hook — gate before push.
- **PR-size labelers** — `pascalgn/size-label-action` / GitHub `size/*` labels (XS–XXL by LOC) — make oversized PRs visible. `(verify)`.
- **`git-absorb` / autosquash (`--fixup`/`--autosquash`)** — keep history atomic when addressing review comments. `(verify)`.
- **`actionlint` / required-checks** — ensure CI/lint/test gates are part of "definition of done" enforcement, not optional.
- **CODEOWNERS validators** (e.g. `mszostok/codeowners-validator`) — detect unowned files, invalid owners, duplicate patterns — keep ownership real. `(verify)`.

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
