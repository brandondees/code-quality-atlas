# Tool rules to triage — checking-idioms-and-consistency

## Contents
- From category #8

## From category #8

### Tooling rules worth lifting
- **Formatters as the floor: Prettier, Black, gofmt/goimports, rustfmt, clang-format, dotnet format** → the strongest consistency mechanism: mechanical, non-negotiable. Heuristic to lift: *if a formatter exists and isn't applied, that's the finding* — don't spend review attention on it.
- **Biome / Ruff / golangci-lint / RuboCop as aggregate idiom gates** → meta-rule: *the project's own linter config is the source of truth for its conventions — read it, then check the diff against it.*
- **RuboCop `Style/*` department** (`Style/GuardClause`, `Style/StringLiterals`, `Style/HashSyntax`, `Style/FrozenStringLiteralComment`, `Style/NumericLiterals`) — Ruby idiom; `Style/GuardClause` bridges to #6.
- **ESLint `consistent-return`, `prefer-const`, `no-var`, `prefer-template`, `object-shorthand`, `prefer-arrow-callback`, `dot-notation`** — "the idiomatic modern-JS way"; `consistent-return` bridges to #6 symmetry.
- **`@typescript-eslint` idiom rules** — `prefer-nullish-coalescing`, `prefer-optional-chain`, `consistent-type-imports`, `array-type` (`T[]` vs `Array<T>`), **`naming-convention`** (project-wide casing per symbol kind; cross-links #5).
- **Pylint `consider-using-*`** (`consider-using-with` R1732, `consider-using-enumerate` C0200, `consider-using-f-string`, `consider-using-dict-items`) — nudge toward idiomatic Python.
- **Ruff `UP` (pyupgrade) rules** — outdated idioms vs. modern Python (`%`-format → f-string, `typing.List` → `list`).
- **golangci-lint `gofmt`/`gofumpt`** (formatting), **`revive`**, **staticcheck's stylecheck checks (`ST1xxx`)** — e.g. **`ST1005`** (error strings shouldn't be capitalized or end with punctuation); **`errorlint`** (idiomatic `%w` wrapping), **`whitespace`**, **`tagliatelle`** (consistent struct-tag casing). *(Note: `stylecheck` isn't a standalone golangci-lint linter; its ST-codes ship via staticcheck.)*
- **SonarQube `S1192`** — "String literals should not be duplicated" (**default: 3 duplications, literals <5 chars excluded**); pushes toward a shared constant (cross-links #6 magic-strings). Naming-convention rules `S100`/`S101`/`S117` `(verify squids)`.
- **EditorConfig + pre-commit/lint-staged gates** — `.editorconfig` (charset, indent, line-ending) and hooks running the above; *presence and enforcement* is itself the control to check for.
