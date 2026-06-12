# Tool rules to triage — reviewing-naming-and-readability

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents
- From category #5
- From category #6
- From category #7

## From category #5

### Tooling rules worth lifting
- **ESLint `id-length`** — identifiers shorter/longer than a configured min/max (scope-appropriate length).
- **ESLint `camelcase`** — casing convention (catches `snake_case` leaking into JS).
- **ESLint `id-match`** — identifiers must match a configurable regex (encode a naming convention as a rule).
- **ESLint `id-denylist`** (formerly `id-blacklist`) — bans specific low-information names project-wide (`data`, `err`, `cb`, `temp`). The denylist is itself a reusable "vague-name" seed list.
- **Pylint `invalid-name` (C0103)** — identifier doesn't match the naming style for its kind (module/class/const/var/arg); per-kind regex config models "different name shapes for different roles." ([docs](https://pylint.readthedocs.io/en/latest/user_guide/messages/convention/invalid-name.html))
- **Pylint `disallowed-name` (C0104)** — flags placeholder names; **default `bad-names` = `foo`, `bar`, `baz`** (configurable). ([docs](https://pylint.pycqa.org/en/latest/user_guide/messages/convention/disallowed-name.html)) Direct hit on the "placeholder/vague name" facet.
- **RuboCop `Naming/MethodName`, `Naming/VariableName`, `Naming/ClassAndModuleCamelCase`, `Naming/ConstantName`** — Ruby naming conventions per identifier kind.
- **RuboCop `Naming/PredicateName`, `Naming/PredicateMethod`** — predicate methods should read as questions, avoid redundant `is_`/`has_` prefixes (Ruby idiom).
- **RuboCop `Naming/AccessorMethodName`** — getters/setters shouldn't be `get_`/`set_`-prefixed in Ruby (idiom-specific; cross-links #8).
- **golangci-lint `revive` (`var-naming`) / legacy `golint`** — flag stutter (`http.HTTPServer`), non-idiomatic initialisms (`Url` vs `URL`), missing doc-comment on exported names.
- **Reek `UncommunicativeVariableName`, `UncommunicativeMethodName`, `UncommunicativeModuleName`** — single-letter/numeric-suffixed/low-information names (Ruby). Strong direct mapping to "vague name."
- **clang-tidy `readability-identifier-naming`** — highly configurable per-kind naming convention enforcement (C/C++).

## From category #6

### Tooling rules worth lifting
- **SonarQube `S3776`** — "Cognitive Complexity of functions should not be too high"; language-agnostic; **default threshold 15**.
- **ESLint `complexity`** — cyclomatic complexity over a threshold (default 20; teams often set 10).
- **ESLint `max-depth`** (default 4) — block nesting depth. **`max-lines-per-function` / `max-lines` / `max-statements`** — length/statement caps (the Long Function smell). **`max-params`** (default 3) — Long Parameter List. **`max-nested-callbacks`** — pyramid of doom.
- **ESLint `no-magic-numbers`** — unnamed numeric literals (allow-lists for `0`/`1`). *No built-in magic-string rule* — strings come from `eslint-plugin-sonarjs` / Sonar `S1192`.
- **`eslint-plugin-sonarjs` `cognitive-complexity`** — Sonar's metric inside ESLint.
- **RuboCop `Metrics/AbcSize`** (Assignments-Branches-Conditions; **default Max 17**), **`Metrics/PerceivedComplexity`** (**Max 8**; Ruby's cognitive-style metric), **`Metrics/CyclomaticComplexity`** (Max 7 `(verify current)`), **`Metrics/MethodLength`, `Metrics/BlockLength`, `Metrics/ParameterLists`**.
- **Reek `TooManyStatements`, `NestedIterators`, `ControlParameter`, `TooManyBranches`** — long-method, deep-nesting, flag-argument, branch-heavy smells (Ruby).
- **Pylint `too-many-branches` (R0912)`, `too-many-statements` (R0915)`, `too-many-nested-blocks` (R1702)`, `too-many-arguments` (R0913)`, `too-many-locals` (R0914)`** — Python local-complexity caps; R1702 is a direct nesting gate.
- **Pylint `magic-value-comparison` (R2004)** — comparisons against magic literals; **opt-in extension** (`pylint.extensions.magic_value`); `valid-magic-values` default `(0, -1, 1, "", "__main__")`. Ruff equivalent **`PLR2004`**. **`no-else-return` (R1705)`, `inconsistent-return-statements` (R1710)`** — nudge toward guard-clause / symmetry.
- **golangci-lint: `gocyclo`** (cyclomatic), **`gocognit`** (cognitive), **`nestif`** (deeply-nested if), **`funlen`** (function length), **`cyclop`** (func+package cyclomatic), **`mnd`** (magic-number detector; **replaces the old `gomnd`**). A near-complete map of this category in one toolchain.
- **PMD `CyclomaticComplexity`, `CognitiveComplexity`, `NPathComplexity`, `ExcessiveMethodLength`, `ExcessiveParameterList`, `AvoidDeeplyNestedIfStmts`** (Java) — incl. **NPath** (acyclic execution paths), a stricter cousin of cyclomatic.
- **Lizard / radon** — language-agnostic cyclomatic + token-count + function-length reporters; radon grades a Maintainability Index. Good "metrics across the diff" framing.

## From category #7

### Tooling rules worth lifting
- **Pylint `missing-function-docstring` (C0116)`, `missing-class-docstring` (C0115)`, `missing-module-docstring` (C0112)`** — presence gates. **`fixme` (W0511)** — flags `TODO`/`FIXME`/`XXX`.
- **Ruff / pydocstyle `D` rules (D1xx–D4xx, PEP 257)** — docstring style & completeness. **`undocumented-param` (D417)** — docstring doesn't document all params (only fires when an `Args` section exists; on the google convention). ([Ruff D417](https://docs.astral.sh/ruff/rules/undocumented-param/))
- **Ruff `commented-out-code` (ERA001)** (from PyCQA `eradicate`) — detects **commented-out code** specifically. ([Ruff ERA001](https://docs.astral.sh/ruff/rules/commented-out-code/)) Direct hit on that facet.
- **Ruff/flake8 `flake8-todos` / `flake8-fixme`** — flag `TODO`/`FIXME`/`XXX`/`HACK`, sometimes requiring author/issue link.
- **ESLint `no-warning-comments`** (TODO/FIXME), **`no-inline-comments`, `capitalized-comments`, `multiline-comment-style`** — comment-style consistency (cross-links #8).
- **`eslint-plugin-jsdoc`** — `jsdoc/require-param`, **`jsdoc/check-param-names`** (catches a stale `@param` name — comment-rot mechanized), `jsdoc/require-returns`, `jsdoc/no-undefined-types`.
- **RuboCop `Style/CommentAnnotation`** (TODO/FIXME keyword formatting), **`Style/CommentedKeyword`**.
- **golangci-lint `godot`** (comments end with a period), **`godox`** (flags TODO/FIXME/BUG/HACK), **`revive` `exported`** (exported symbols need a doc comment starting with the symbol name), **`misspell`** (typos in comments/strings).
- **SonarQube `S125`** — "Sections of code should not be commented out" (language-agnostic; in TS aliased `no-commented-code`). **`S1135`** (track `TODO`) and **`S1134`** (track `FIXME`) `(verify squids)`.
- **Vulture (Python)** — dead-code detector; adjacent to commented-out code as deletable cruft.
