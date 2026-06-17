# Research — Cluster II: Readability & Clarity

> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Drafted 2026-06-08 (from model knowledge, web-less subagent); **web-verified 2026-06-09 from the main loop.** Rule IDs, thresholds, and URLs below are confirmed against live sources except where marked `(verify)`.

---

## #5 Naming — intention-revealing, consistent, domain language, progressive refinement

### Key references

- **Arlo Belshee — "Good Naming Is a Process, Not a Single Step" / "Naming is a Process" series** — https://arlobelshee.com/good-naming-is-a-process-not-a-single-step/ → mine: names improve in **stages**, not one leap — you don't need the perfect name to make progress. The 7 stages: **Missing → Nonsense → Honest → Honest-and-Complete → Does-the-Right-Thing → Intent → Domain Abstraction** (final stage: ["Intent to Domain Abstraction"](https://arlobelshee.com/naming-is-a-process-part-7-intent-to-domain-abstraction/)). Key insight to lift: *dishonest* names (look meaningful, aren't) are more dangerous than honest-nonsense ones; the reviewer behavior is "identify the stage, nudge it one stage better," not "demand perfection."
- **Robert C. Martin — *Clean Code*, ch. 2 "Meaningful Names"** → mine: intention-revealing names; avoid disinformation; meaningful distinctions (no `a1`/`a2`, no noise words `Info`/`Data`/`Manager`); pronounceable & searchable; class = noun, method = verb. Mine the *checks*, treat as heuristics not law.
- **Eric Evans — *Domain-Driven Design* (Ubiquitous Language)** + **Vaughn Vernon — *Implementing DDD*** → mine: names should come from the domain's shared vocabulary; a mismatch between code names and domain-expert language is itself a defect.
- **Steve McConnell — *Code Complete* (2nd ed.), ch. 11 "The Power of Variable Names"** → mine: name length scales with scope; name to the *problem* not the solution; consistent antonym pairs (`begin`/`end`, `first`/`last`); avoid numerically-suffixed series.
- **Phil Karlton — "two hard things: cache invalidation and naming things"** (widely attributed) → mine: a cultural anchor that naming deserves explicit review attention. (Folklore-level attribution; cite as such.)
- **Felienne Hermans — *The Programmer's Brain*** → mine: cognitive-science backing — good names reduce working-memory load; naming is a *comprehension* lever, not mere style.

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

### Reviewable heuristics (skill-checklist seeds)

- Does each name state *intent* (what/why) rather than *mechanism* or type? (`activeUsers` over `userListFiltered`; `retryBudget` over `n`.)
- Is name length proportional to scope? (One letter fine for a 3-line loop; a field or exported symbol needs a descriptive name.)
- Any placeholder/temporary name surviving into the diff? (`tmp`, `data`, `data2`, `obj`, `foo`, `handleStuff`, `Manager`, `Helper`, `Util`.) Flag as "stage: nonsense/honest-incomplete — refine one stage."
- Do booleans read as predicates? (`isReady`, `hasAccess`, `canRetry` — not `flag`, `status`, `check`.)
- Do collections read as plurals and scalars as singulars? (mismatch signals type/contents confusion.)
- Is domain language used, and used *consistently*? (Pick one of `customer`/`client`/`account`; don't mix synonyms for one concept.)
- Are units/qualifiers in the name when ambiguous? (`timeoutMs`, `sizeBytes`, `priceCents` — cross-links #4, #6.)
- No disinformation: name doesn't imply a type/structure it isn't (`accountList` that's a `Map`).
- Consistent antonym pairs and verb tense across the API surface (`open`/`close`, `enable`/`disable`).
- Abbreviations domain-standard or spelled out (`cust`, `usr`); initialisms cased per language idiom (`URL`, `ID`).
- Does the name avoid encoding the *how* so it survives refactors? (`fetchUser` over `userViaHttpGet`.)
- When a name is hard to choose, is that a smell pointing at over-broad responsibility? (cross-links #6.)

---

## #6 Local readability — length/SRP, complexity, nesting, magic values, altitude, symmetry

### Key references

- **G. Ann Campbell / SonarSource — "Cognitive Complexity: A new way of measuring understandability" (white paper)** → mine: the metric powering modern linters. Rules: (1) **ignore** structures that read multiple statements as one; (2) **+1** for each break in linear flow (`if`/`else if`/`else`, ternary, `switch`, loops, `catch`, mixed boolean-operator sequences, labelled break/continue); (3) **increment more for nesting** — deeper nesting costs more. A flat `switch` scores low, nested conditionals score high — closer to *felt* difficulty than cyclomatic. **Sonar default "too complex" threshold = 15** (rule S3776).
- **Thomas J. McCabe — "A Complexity Measure" (1976)** → mine: cyclomatic complexity = linearly-independent paths (≈ decision points + 1); a *lower bound on test cases needed*. Common bands: 1–10 simple … >50 untestable `(verify exact bands)`.
- **Robert C. Martin — *Clean Code*, ch. 3 "Functions"** → mine: small functions, "do one thing," single level of abstraction (the **altitude** rule), few arguments (0–2), no flag arguments, no side-effect surprises. Mine the *checks*, push back on the dogmatic "4 lines."
- **John Ousterhout — *A Philosophy of Software Design*** → mine: complexity accumulates from *dependencies* and *obscurity*; "deep modules" (simple interface, substantial behavior) over many shallow ones. **Counterweight** to Clean Code's "lots of tiny functions" — central to not over-splitting (see map-gaps G3).
- **Martin Fowler — *Refactoring* (2nd ed.)** → mine: the smell→refactoring names a review should suggest — *Long Function*, *Long Parameter List*, *Magic Number* → Replace Magic Literal with Symbolic Constant, *Nested Conditional* → Replace Nested Conditional with Guard Clauses (the **early-return** move), Decompose Conditional, Extract Function.
- **Kent Beck — *Tidy First?*** → mine: small, safe, local tidyings (guard clauses, explaining variables, dead-code removal, reorder for reading order, normalize symmetries) and *when* they pay off; the **symmetry** idea — express parallel things in parallel form — is explicit here.
- **Linux kernel CodingStyle — "if you need more than 3 levels of indentation, you're screwed"** → mine: a blunt real heuristic that nesting depth ≈ complexity.

### Tooling rules worth lifting

- **SonarQube `S3776`** — "Cognitive Complexity of functions should not be too high"; language-agnostic; **default threshold 15**.
- **ESLint `complexity`** — cyclomatic complexity over a threshold (default 20; teams often set 10).
- **ESLint `max-depth`** (default 4) — block nesting depth. **`max-lines-per-function` / `max-lines` / `max-statements`** — length/statement caps (the Long Function smell). **`max-params`** (default 3) — Long Parameter List. **`max-nested-callbacks`** — pyramid of doom.
- **ESLint `no-magic-numbers`** — unnamed numeric literals (allow-lists for `0`/`1`). *No built-in magic-string rule* — strings come from `eslint-plugin-sonarjs` / Sonar `S1192`.
- **`eslint-plugin-sonarjs` `cognitive-complexity`** — Sonar's metric inside ESLint.
- **RuboCop `Metrics/AbcSize`** (Assignments-Branches-Conditions; **default Max 17**), **`Metrics/PerceivedComplexity`** (**Max 8**; Ruby's cognitive-style metric), **`Metrics/CyclomaticComplexity`** (Max 7 `(verify current)`), **`Metrics/MethodLength`, `Metrics/BlockLength`, `Metrics/ParameterLists`**.
- **Reek `TooManyStatements`, `NestedIterators`, `ControlParameter`, `TooManyBranches`** — long-method, deep-nesting, flag-argument, branch-heavy smells (Ruby).
- **Pylint `too-many-branches` (R0912)`,`too-many-statements`(R0915)`, `too-many-nested-blocks` (R1702)`,`too-many-arguments`(R0913)`, `too-many-locals` (R0914)`** — Python local-complexity caps; R1702 is a direct nesting gate.
- **Pylint `magic-value-comparison` (R2004)** — comparisons against magic literals; **opt-in extension** (`pylint.extensions.magic_value`); `valid-magic-values` default `(0, -1, 1, "", "__main__")`. Ruff equivalent **`PLR2004`**. **`no-else-return` (R1705)`,`inconsistent-return-statements`(R1710)`** — nudge toward guard-clause / symmetry.
- **golangci-lint: `gocyclo`** (cyclomatic), **`gocognit`** (cognitive), **`nestif`** (deeply-nested if), **`funlen`** (function length), **`cyclop`** (func+package cyclomatic), **`mnd`** (magic-number detector; **replaces the old `gomnd`**). A near-complete map of this category in one toolchain.
- **PMD `CyclomaticComplexity`, `CognitiveComplexity`, `NPathComplexity`, `ExcessiveMethodLength`, `ExcessiveParameterList`, `AvoidDeeplyNestedIfStmts`** (Java) — incl. **NPath** (acyclic execution paths), a stricter cousin of cyclomatic.
- **Lizard / radon** — language-agnostic cyclomatic + token-count + function-length reporters; radon grades a Maintainability Index. Good "metrics across the diff" framing.

### Reviewable heuristics (skill-checklist seeds)

- Does this function do *one* thing at *one* level of abstraction? (Altitude: if it mixes high-level policy with low-level byte/string twiddling, extract the low part.)
- Can you state the function's job in a single verb phrase without "and"? If not, likely SRP violation — split.
- Nesting depth ≤ ~3? Replace arrow-shaped nesting with **guard clauses / early returns**; invert conditions to de-nest the happy path.
- Any unexplained literal (number or string) beyond `0`/`1`/`""`/obvious? Promote to a named constant whose name carries the *why* (`MAX_RETRIES`, `HTTP_TOO_MANY_REQUESTS`).
- Cyclomatic within budget (commonly ≤10) and cognitive ≤ ~15? Flag outliers for decomposition.
- Parameter count ≤ ~3; else a parameter object? No boolean flag params that fork the body (split into two functions).
- Is the **happy path** the un-indented main line, with edge cases returned early at the top?
- ★ **Symmetry of expression**: parallel concepts in parallel form (all branches `return x`); paired operations adjacent and mirror-shaped (`acquire`/`release`); consistent argument ordering across sibling calls.
- Are there "explaining variables" for opaque sub-expressions?
- No long runs of near-duplicated lines begging for a loop/helper (local DRY — but watch the #11 premature-abstraction counterweight: extract only on *real* repetition).
- Does control flow avoid surprising jumps a reader can't track?
- Function length "screenful-ish," decomposing at natural seams — but resist so many one-line helpers that the reader page-hops (Ousterhout counterweight).

---

## #7 Comments & inline docs — why-not-what, docstring accuracy, comment rot, dead code

### Key references

- **Robert C. Martin — *Clean Code*, ch. 4 "Comments"** → mine: "comments don't make up for bad code"; *good* comments (intent, warning of consequences, TODO, legal, amplification, public-API docs) vs. *bad* (redundant, misleading, mandated noise, commented-out code, journal/attribution now in VCS). The "explain *why*, not *what*" thesis operationalized.
- **"Comments should say WHY, not WHAT"** (community canon; *Pragmatic Programmer*, McConnell, Coding Horror) → mine: the *what* is the code's job; comments earn their keep capturing intent, rationale, constraints, road-not-taken.
- **Andrew Hunt & David Thomas — *The Pragmatic Programmer*** → mine: DRY applies to comments — a comment duplicating code is a second source of truth that *will* drift; prefer self-documenting code, reserve comments for the non-obvious *why*.
- **Steve McConnell — *Code Complete*, ch. 32 "Self-Documenting Code"** → mine: taxonomy of comment kinds; good comments operate at the level of *intent*; comments are first-class code to maintain.
- **Comment–code inconsistency / "comment rot" research** (specific authors/venues `(verify)`) → mine: comments drift from code measurably; stale `@param`/`@return`/docstrings are a real, detectable defect class. Motivates "doc mentions a param/return that no longer exists" checks.
- **Docstring conventions — PEP 257, JSDoc, Javadoc, rustdoc, KDoc** → mine: what "complete" looks like per ecosystem (summary, params, returns, raises, examples) so a reviewer can judge *completeness & accuracy*.

### Tooling rules worth lifting

- **Pylint `missing-function-docstring` (C0116)`,`missing-class-docstring`(C0115)`, `missing-module-docstring` (C0112)`** — presence gates. **`fixme` (W0511)** — flags `TODO`/`FIXME`/`XXX`.
- **Ruff / pydocstyle `D` rules (D1xx–D4xx, PEP 257)** — docstring style & completeness. **`undocumented-param` (D417)** — docstring doesn't document all params (only fires when an `Args` section exists; on the google convention). ([Ruff D417](https://docs.astral.sh/ruff/rules/undocumented-param/))
- **Ruff `commented-out-code` (ERA001)** (from PyCQA `eradicate`) — detects **commented-out code** specifically. ([Ruff ERA001](https://docs.astral.sh/ruff/rules/commented-out-code/)) Direct hit on that facet.
- **Ruff/flake8 `flake8-todos` / `flake8-fixme`** — flag `TODO`/`FIXME`/`XXX`/`HACK`, sometimes requiring author/issue link.
- **ESLint `no-warning-comments`** (TODO/FIXME), **`no-inline-comments`, `capitalized-comments`, `multiline-comment-style`** — comment-style consistency (cross-links #8).
- **`eslint-plugin-jsdoc`** — `jsdoc/require-param`, **`jsdoc/check-param-names`** (catches a stale `@param` name — comment-rot mechanized), `jsdoc/require-returns`, `jsdoc/no-undefined-types`.
- **RuboCop `Style/CommentAnnotation`** (TODO/FIXME keyword formatting), **`Style/CommentedKeyword`**.
- **golangci-lint `godot`** (comments end with a period), **`godox`** (flags TODO/FIXME/BUG/HACK), **`revive` `exported`** (exported symbols need a doc comment starting with the symbol name), **`misspell`** (typos in comments/strings).
- **SonarQube `S125`** — "Sections of code should not be commented out" (language-agnostic; in TS aliased `no-commented-code`). **`S1135`** (track `TODO`) and **`S1134`** (track `FIXME`) `(verify squids)`.
- **Vulture (Python)** — dead-code detector; adjacent to commented-out code as deletable cruft.

### Reviewable heuristics (skill-checklist seeds)

- Does each comment explain **why** (intent, constraint, trade-off, gotcha, issue link) rather than restate **what**? Delete pure restatements.
- Any **commented-out code**? Delete it — VCS is the archive. Flag every block.
- Do docstrings/JSDoc/Javadoc **match the current signature**? Every `@param`/`@return`/`@raises` exists and is accurate; no param undocumented or renamed (comment rot).
- For public/exported API, is the doc **complete**: summary, params, return, errors, and an example where non-trivial?
- Does the comment **agree with the code**? "// retries 3 times" next to a bound of 5 is worse than no comment — flag contradictions as bugs.
- Are `TODO`/`FIXME`/`HACK` attributed/linked and not silently growing?
- No journal/changelog/author comments VCS already tracks; no banner/noise comments.
- Is a *needed* warning present? (Non-obvious side effects, ordering, thread-safety, units, "do not call before X.")
- When a comment is needed to explain confusing code, ask first whether **renaming/restructuring** removes the need (cross-links #5/#6).
- Are units, ranges, invariants documented where the type system can't express them (cross-links #4, #10)?
- Are licensing/attribution comments correct where required (cross-links #27)?

---

## #8 Consistency & idiom — project conventions, idiomatic language/framework use, pattern consistency

### Key references

- **Language & org style guides** — **PEP 8**, **Google Style Guides** (google.github.io/styleguide), **Airbnb JavaScript**, **Effective Go / Go Code Review Comments**, **Rust API Guidelines**, **Ruby Style Guide** → mine: each is a curated, battle-tested list of "in this ecosystem, do it *this* way." We don't adopt one; we mine the *recurring* checks.
- **Effective Go + "Go Code Review Comments"** → mine: an *idiom* guide written as review comments (error shape, naming, receiver names, interface size, `gofmt` non-negotiable) — a template for the "idiomatic use" half.
- **Andrew Hunt & David Thomas — *The Pragmatic Programmer* (Orthogonality, DRY, least surprise)** → mine: consistency is least-surprise; learning one part should predict the rest.
- **Martin Fowler — *Refactoring* / PoEAA** → mine: when a codebase has *chosen* a pattern (Repository, Result type, error-as-value, hexagonal ports), new code should conform; divergence without reason is a smell.
- **Sandi Metz — "The Wrong Abstraction"** (cross-links #11) → mine: consistency is good *until* it forces the wrong shape; flag inconsistency, but don't demand uniformity that papers over genuinely different cases. **Counterweight.**
- **Opinionated-reviewer prior art** (../prior-art.md): `dhh-rails`, `kieran-*`, `pattern-recognition-specialist` → mine: the *named-perspective* pattern — strong ecosystem-specific taste catches idiom violations a generic linter misses. Worth replicating per ecosystem (see map-gaps G6).

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

### Reviewable heuristics (skill-checklist seeds)

- Does the change **follow the project's own conventions**? Read `.eslintrc`/`.rubocop.yml`/`ruff.toml`/`.editorconfig`/style guide first; the codebase's established choice wins over personal preference.
- Is the code **formatted** by the project's formatter? (Unformatted code where Prettier/Black/gofmt exists is an automatic finding.)
- Does it use the **idiomatic construct** for this language/framework, or a clumsy non-native equivalent? (comprehension vs. manual loop; `Result`/error-as-value vs. exceptions where one was chosen; framework router/ORM idiom vs. hand-rolled.)
- **Pattern consistency**: does this solve a recurring problem the *same way* the codebase already does (error shape, DTO/serialization, DI style, test layout)? Divergence needs a stated reason.
- Are **naming/casing conventions** uniform across the symbol kind? No mixed `snake_case`/`camelCase` for one role (cross-links #5).
- Import ordering / module structure / file layout consistent with siblings? (New file where a reader expects it.)
- Are strings/messages/log formats consistent with existing ones (cross-links #16)?
- Does it avoid introducing a **second way to do the same thing** (a parallel util, competing abstraction) when one exists (cross-links #11/#9)?
- When the existing convention is genuinely worse, is the change either fully migrating (not adding a third style) or explicitly flagged as a deliberate scoped exception?
- Framework idiom used the blessed way (React hooks rules, Rails callbacks vs. service objects per app style, DI per framework)?
- Configuration-as-convention respected (folder-by-feature vs. -by-type, test-file naming, public-API surface) so the next engineer "falls into the pit of success" (cross-links #9)?
- **Counterweight check**: am I demanding consistency that erases a *meaningful* difference (forcing the wrong abstraction)? If the cases truly differ, divergence is correct — don't flag it.

---

## #35 Agent-legibility — the codebase as a working environment for AI maintainers

> **Promoted v0.5 (gap G20, vantage rotation — the AI agent as code-owner/reader).** Cluster II asks *"Can humans understand it?"* (#5–#8). The whole readability/clarity axis was never rotated to the reader an agent-run review most needs to serve: *"Can an **agent** understand, navigate, and safely modify this within a context budget?"* This lens is that rotation. It is the **mirror image of #34** — #34 reviews the *quality of AI-**authored** code*; #35 reviews the *quality of code **for** AI readers* — same axis, opposite direction, neither subsumes the other. It is also **the G11 pattern again**: the suite already optimizes its *own* artifacts for agent-legibility (progressive disclosure, context budget, model-portability — D7) but never made agent-legibility a **review behavior** for the codebases it reviews ("we hold ourselves to it but never review for it"). Natural shape: `diff` (is *this change* agent-legible and context-economical?); a whole-repo agent-navigability audit arm (navigable tree, repo-wide onboarding-file and `llms.txt` coverage) is a noted follow-up, mirroring the #32/#33 incremental precedent. Boundaries: it cross-links **#5–#8** (human-framed readability — same axis, different reader), **#21/#22** (human onboarding/README front-door — agent analog), **#24** (agent-native *operator* parity — a distinct vantage), and **#30** (AGENTS.md / SKILL.md *authoring* quality as an artifact). The seam with #30 is sharp: #30 asks *"is this artifact well-formed per its own published standard?"*; #35 asks *"does the repo give an agent good, scoped onboarding to work **here**?"* — content fit, not artifact conformance. This lens owns the **agent-as-reader vantage**, names the overlap, and defers the deep verdict to the owning lens.

### Key references

- **"Creating AI-friendly codebases" (D. Consonni, 2024)** — https://medium.com/@dconsonni/creating-ai-friendly-codebases-82cb3203c118 → mine: the practitioner framing for agent-legible structure — self-contained modules, clear boundaries, and naming/layout an agent can navigate without loading the whole tree. The spine of the diff-arm checks.
- **"Coding agents as a first-class consideration in project structures" (somedood, dev.to, 2024)** — https://dev.to/somedood/coding-agents-as-a-first-class-consideration-in-project-structures-2a6b → mine: the **"40% context rule"** (a change a reader must understand should fit well within a fraction of a working context window), **depth-first slices** (the function plus its key callees/types sit together rather than scattered), **self-contained modules**, and **AST-grounded agent interfaces** (structurally-addressable surfaces an agent can target). The concrete heuristics for context economy and navigability.
- **Liu et al. — "Lost in the Middle: How Language Models Use Long Contexts" (arXiv 2307.03172, 2023)** — https://arxiv.org/abs/2307.03172 → mine: the empirical grounding for *why* context economy is a legibility property, not a style preference — models retrieve far worse from the middle of a long context, so a change that forces a large, scattered read is genuinely harder (and less safe) to reason about. Justifies treating "needs the whole repo loaded to understand" as a defect for agent and human alike.
- **`llms.txt` proposal (J. Howard / Answer.AI, llmstxt.org, 2024)** — https://llmstxt.org/ → mine: the emerging machine-readable index standard — a top-level file pointing an agent at canonical entry points and docs. Adoption signal: requested/used across the ecosystem ([buildwithfern overview](https://buildwithfern.com/learn/docs/ai-features/llms-txt)). Grounds the index-presence check; surface as an improvement absent a stated agent-consumption need.
- **GitClear — "AI Copilot Code Quality" research (annual; 2024 and 2025 editions)** — https://www.gitclear.com → mine: the measured "**superficially clean but intrinsically complex**" signature of AI-assisted code (rising duplication and quickly-reverted churn). Read here from the *reader's* side: code that passes line-by-line but is expensive to reason about within a budget is an agent-legibility defect — the mirror of #34's authorship-side reading.
- **Anthropic — agent-skill / `AGENTS.md` authoring guidance** (the same best-practices spine #30/D7 builds on) → mine: what *good, scoped* agent onboarding looks like — the right run/test/convention commands and guardrails, progressively disclosed, not an absent file or a bloated dump. The rubric for the onboarding-file checks (authoring *conformance* stays #30; *fit for working in this repo* is here).

### Tooling rules worth lifting

*(Most of this signature is judgment, not lint — "can an agent reason about this within a budget" has no rule. The mechanical subset is about measuring size/structure and checking the onboarding files; named tools `(verify)` on your stack.)*

- **Context/size & token measurement** — repo-packers that show what an agent would actually have to read (`repomix`, `gitingest`) and token counters (`tiktoken`-based) to flag files or change-slices that blow a sensible context budget; a single giant file or a change spread thin across many files is the measurable form of the 40% rule.
- **Structural / AST navigation** — `ast-grep`, tree-sitter, `ctags`/LSP indexers: the agent's navigation substrate. If these cannot cleanly index a symbol (dynamic dispatch, stringly-typed indirection, generated megafiles), an agent navigating by retrieval can't either — treat an un-indexable surface as a navigability finding.
- **Onboarding-file health** — link-checkers (`lychee` / `markdown-link-check`) and markdown structure linting over `AGENTS.md` / `CLAUDE.md` / `llms.txt`: dead links, references to renamed commands, or a missing/empty file are mechanical tells; pair with a "does the documented build/test command actually run" smoke check (shared spirit with #22 runnable-examples).
- **Duplication / churn detectors** — `jscpd`, `pmd-cpd`, SonarQube duplication (shared with #34/#21): parallel copies make an agent edit the wrong one; surface duplicated blocks an agent would have to disambiguate.

### Reviewable heuristics (skill-checklist seeds)

- ★ **Context economy / self-containment (the 40% rule):** Can this change be understood — and safely modified — *without* loading the whole repo into context? Is the unit of change a **depth-first slice** (the function plus the key callees, types, and constants it depends on sit together or are reachable in one hop) rather than logic scattered across many files each needing the rest to make sense? A change that only makes sense after a large, fragmented read is a legibility defect for an agent *and* a human (models retrieve worst from the middle of a long context); prefer the self-contained shape.
- ★ **Agent-onboarding files present, accurate, and scoped (AGENTS.md / CLAUDE.md):** If the change alters the build/test/run/convention surface, does the repo's agent-instruction file still tell an agent the truth — and is it **scoped** (the right commands, conventions, and do-not-touch guardrails) rather than absent, stale, or a bloated everything-dump? This is the agent analog of #22's README front-door: file *drift* is #22/#24 and artifact *conformance* is #30, but *"does the repo provide good, scoped agent onboarding to work here"* is owned here. A missing or misleading onboarding file makes every later agent edit start from a worse prior.
- **Retrieval-friendly / discoverable structure (xref #5):** Would a grep / retrieval / AST query land on the right chunk? Are names, file paths, and module boundaries **intention-revealing for a reader who arrives by retrieval**, not by having read the whole tree — the file where a reader (human or agent) expects it, named for what it does? An agent reads by search; structure that defeats search defeats the agent.
- **Structurally-addressable interfaces (AST-navigable):** Does the change expose behavior through **stable, structurally-addressable surfaces** — named exports, typed signatures, clear module entry points an agent can target — rather than dynamic/stringly-typed indirection (reflection, runtime-assembled names, monkey-patching) that defeats static navigation and makes a safe edit guesswork?
- **Local self-explanation over whole-system context (xref #7):** Does the change carry the *why* an agent needs **in place** — a type, a docstring stating the contract, an invariant comment at the edit site — so an editor doesn't have to reconstruct intent from distant files? Distinct from #7's human "why-not-what": here the audience is a **context-bounded** reader, so locality of the explanation is the property, not just its presence.
- **LLM-centric readability — superficially clean, intrinsically complex (xref #6):** Does the code read fine line-by-line yet carry hidden reasoning cost — deep parameter coupling, long-range data dependencies, control flow that only resolves across several files? This is #34's "superficially clean but intrinsically complex" signature read from the *reader's* side; flag where a simpler shape lowers the cost of reasoning about it within a budget (route decomposition detail to #6, restraint counterweight to #11).
- **No agent-hostile patterns introduced:** Does the change add things that make the tree *harder* for an agent to work in — a giant single file that blows the context budget, generated scaffolding/config that bloats what an agent must scan, or duplicated parallel copies that invite editing the wrong one (xref #21 change-amplification, #34 duplication)? Surface these as legibility regressions even when each line is individually fine.
- **Scoped guardrails for autonomous edits:** Do the onboarding files (or equivalent) name the **do-not-touch zones, required checks, and project conventions** an agent must honor, so an autonomous edit *fails safe* rather than confidently wrong? Distinct from #32 runtime agent/tool-safety and #24 operator parity — this is the quality of the *written guidance content*, the agent analog of a good CONTRIBUTING guide.
- **`llms.txt`-style index for agent-consumed repos:** For a library/product that publishes for agent consumption, is there an `llms.txt` (or equivalent machine-readable map) pointing an agent at canonical entry points and docs — present and current, not stale? Emerging standard; surface as an improvement/nit absent a stated agent-consumption need, not a blocker.

---

## Open threads   (gaps / mis-placements / sub-topics worth deeper research)

- **Verification status (was top priority):** the bulk of this file's rule IDs/thresholds are now **web-verified (2026-06-09)**. Residual `(verify)`: exact McCabe risk bands; RuboCop `Metrics/CyclomaticComplexity` current default; Sonar `S1134`/`S1135` squids; the empirical comment-rot citations.
- **#6 ↔ #11 decomposition tension** (Clean Code tiny functions vs. Ousterhout deep modules) — a real design question the suite must take a stance on (map-gaps G3).
- **Magic *strings* under-tooled vs. magic numbers** — ESLint has `no-magic-numbers` but no built-in magic-string rule; coverage via Sonar `S1192` + plugins. Config keys, routes, event names are common offenders → worth a dedicated heuristic.
- **#5 ↔ #8 overlap** — casing/convention checks sit on the seam; treat *intention-revealing-ness* as #5 and *uniformity* as #8 (map-gaps G4).
- **"Altitude / level-of-abstraction mixing" and symmetry-of-expression are poorly tooled** — no linter cleanly detects them; both are LLM-reviewer-only heuristics (map-gaps G5) and good early skill targets.
- **#8 may be a *family*** of per-ecosystem idiom reviewers (dhh/kieran pattern) sharing a "read the project config, then check the diff" spine (map-gaps G6).
