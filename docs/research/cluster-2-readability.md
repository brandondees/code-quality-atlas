# Research — Cluster II: Readability & Clarity
> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Generated 2026-06-08 via web research. Citations best-effort; uncertainty flagged inline.

> **Sourcing note for this file:** during this session all live web-fetch channels (WebSearch, WebFetch, GitHub MCP, browser tools, outbound `curl`) were unavailable/denied, so URLs could not be re-verified at point of writing. Per the README escape valve ("add a URL only when confident it's correct; else omit, or mark `(verify)`"), references below are given in `author — title` form with URLs omitted unless stable and well-known, and any rule ID or factual claim I could not re-confirm against a live source is marked `(verify)`. No URLs, quotes, or rule IDs were fabricated; uncertain ones are flagged or omitted. Several anchors here were already filed in ../references.md (Belshee; cognitive-complexity rationale; "comments say why"; style guides as heuristic sources) and are extended rather than re-derived. A re-pass with live web access should confirm the `(verify)` items and add stable URLs.

---

## #5 Naming — intention-revealing, consistent, domain language, progressive refinement

### Key references
- **Arlo Belshee — "Naming as a Process" / "Naming is a Process"** (digdeeproots.com; also the `naming-as-process` skill in this repo's prior art).
  → mine: names improve in *stages*, not in one leap — you don't need the perfect name to make progress. The progression runs roughly **Missing → Nonsense → Honest → Honest-and-Complete → Does-the-Right-Thing → Intent-revealing → Domain-abstraction** (exact stage labels: `(verify)` against the source). The reviewable behavior: identify *which stage* a name is at and nudge it one stage better, rather than demanding perfection.
- **Robert C. Martin — *Clean Code*, ch. 2 "Meaningful Names"** → mine: the concrete naming smells — use intention-revealing names, avoid disinformation, make meaningful distinctions (no `a1`/`a2`, no noise words like `Info`/`Data`/`Manager` that add nothing), use pronounceable & searchable names, class = noun, method = verb. Mine the *checks*; treat the rules as heuristics, not law.
- **Eric Evans — *Domain-Driven Design* (Ubiquitous Language)** + **Vaughn Vernon — *Implementing DDD*** → mine: names should come from the domain's shared vocabulary; a mismatch between code names and the language domain experts use is itself a defect. Reviewer check: does this identifier use a term a domain expert would recognize, or a programmer-invented synonym?
- **Steve McConnell — *Code Complete* (2nd ed.), ch. 11 "The Power of Variable Names"** → mine: name length should scale with scope (short-lived loop index `i` is fine; a module-level name must be descriptive); name to the *problem*, not the solution; consistent antonym pairs (`begin`/`end`, `first`/`last`, `min`/`max`); avoid numerically-suffixed series.
- **Phil Karlton (widely attributed) — "There are only two hard things in Computer Science: cache invalidation and naming things."** → mine: a cultural anchor — naming is hard enough to deserve explicit review attention, not an afterthought. (Attribution is folklore-level; cite as "widely attributed", do not over-claim a source.)
- **Felienne Hermans — *The Programmer's Brain*** → mine: cognitive-science backing for why good names reduce working-memory load; supports the claim that naming is a *readability* (comprehension) lever, not mere style. (Specific chapter `(verify)`.)

### Tooling rules worth lifting
- **ESLint `id-length`** — flags identifiers shorter/longer than configured min/max; enforces "scope-appropriate length" mechanically.
- **ESLint `camelcase`** — enforces casing convention for identifiers (catches cross-convention drift, e.g. `snake_case` leaking into JS).
- **ESLint `id-match`** — identifiers must match a configurable regex (lets a team encode a naming convention as a rule).
- **ESLint `id-denylist` / `id-blacklist`** (older name) — bans specific low-information names project-wide (e.g. `data`, `err`, `cb`, `temp`). The denylist is itself a reusable "vague-name" seed list. (Rule-name aliasing across versions: `(verify)`.)
- **Pylint `invalid-name` (C0103)** — identifier doesn't match the naming style for its kind (module/class/const/var/arg); the per-kind regex config is a good model for "different name shapes for different roles."
- **Pylint `disallowed-name` (C0104)** — flags "blacklisted" placeholder names; default list historically included `foo`, `bar`, `baz`, `toto`, `tutu`, `tata` `(verify exact default list)`. Direct hit on the "placeholder/vague name" facet.
- **RuboCop `Naming/MethodName`, `Naming/VariableName`, `Naming/ClassAndModuleCamelCase`, `Naming/ConstantName`** — enforce Ruby naming conventions per identifier kind.
- **RuboCop `Naming/PredicateMethod` / `Naming/PredicateName`** — predicate (boolean) methods should read as questions and avoid redundant `is_`/`has_` prefixes in Ruby idiom; encodes "names should reveal the kind of thing returned."
- **RuboCop `Naming/AccessorMethodName`** — getters/setters shouldn't be prefixed `get_`/`set_` in Ruby; an idiom-specific intention-revealing check. (Cross-links #8.)
- **golangci-lint `revive` / `golint` exported-name rules** — flag stutter (`http.HTTPServer`), non-idiomatic initialisms (`Url` vs `URL`), and missing-doc-comment-on-exported-name; Go's `var-naming` rule encodes community naming idiom.
- **Reek `UncommunicativeVariableName`, `UncommunicativeMethodName`, `UncommunicativeModuleName`** — flag single-letter/numeric-suffixed/low-information names (Ruby). Strong direct mapping to "vague/placeholder name."
- **clang-tidy `readability-identifier-naming`** — highly configurable per-kind naming convention enforcement for C/C++.

### Reviewable heuristics (skill-checklist seeds)
- Does each name state *intent* (what/why) rather than *mechanism* or type? (`activeUsers` over `userListFiltered`; `retryBudget` over `n`.)
- Is name length proportional to scope? (One-letter is fine for a 3-line loop; a field or exported symbol needs a descriptive name.)
- Any placeholder/temporary names surviving into the diff? (`tmp`, `data`, `data2`, `obj`, `foo`, `handleStuff`, `doProcess`, `Manager`, `Helper`, `Util`.) Flag as "stage: nonsense/honest-incomplete — refine one stage."
- Do booleans read as predicates? (`isReady`, `hasAccess`, `canRetry` — not `flag`, `status`, `check`.)
- Do collections read as plurals and scalars as singulars? (`users` vs `user`; mismatch signals a type/contents confusion.)
- Is domain language used, and used *consistently*? (Pick one of `customer`/`client`/`account` and don't mix synonyms for the same concept across the codebase.)
- Are units/qualifiers in the name when ambiguous? (`timeoutMs`, `sizeBytes`, `priceCents` — cross-links #4 and #6 magic-number naming.)
- No disinformation: name doesn't imply a type/structure it isn't (`accountList` that's actually a `Set`/`Map`).
- Consistent antonym pairs and verb tense across the API surface (`open`/`close`, `enable`/`disable`; not `start`/`end` in one place and `begin`/`stop` in another).
- Abbreviations are domain-standard or spelled out — not idiosyncratic (`cust`, `usr`, `cnt`); initialisms cased per language idiom (`URL`, `ID`).
- Does the name avoid encoding the *how* (implementation) so it survives refactors? (`fetchUser` over `userViaHttpGet`.)
- When a name is hard to choose, is that a smell pointing at an over-broad responsibility? (A function you can't name in a verb phrase often does >1 thing — cross-links #6 single-responsibility.)

---

## #6 Local readability — length/SRP, complexity, nesting, magic values, altitude, symmetry

### Key references
- **G. Ann Campbell / SonarSource — "Cognitive Complexity: A new way of measuring understandability"** (white paper).
  → mine: the metric that powers modern linters. Three guiding rules: (1) **ignore** structures that let multiple statements be read as one (e.g. a method itself, null-coalescing); (2) **increment (+1)** for each break in linear control flow (`if`, `else if`, `else`, ternary, `switch`, loops, `catch`, sequences of mixed boolean operators, labelled `break`/`continue`, recursion `(verify)`); (3) **increment more** for nesting — each level of nesting adds to the increment of the structure inside it. Net effect: a flat `switch` scores low, deeply nested conditionals score high — closer to *felt* difficulty than cyclomatic complexity. Default "too complex" function threshold in Sonar is **15** `(verify the current default)`.
- **Thomas J. McCabe — "A Complexity Measure" (1976)** → mine: cyclomatic complexity = number of linearly independent paths (≈ decision points + 1); the original objective complexity metric and a *lower bound on test cases needed*. Mine the threshold convention (commonly: 1–10 simple, 11–20 moderate, 21–50 high-risk, >50 untestable — `(verify exact bands)`).
- **Robert C. Martin — *Clean Code*, ch. 3 "Functions"** → mine: functions should be small, "do one thing," operate at a single level of abstraction (the **altitude / "one level of abstraction per function"** rule), prefer few arguments (0–2; 3+ needs justification, flag arg-objects), no flag arguments, no side-effect surprises. Mine the *checks*, push back on the dogmatic "4 lines" extreme.
- **John Ousterhout — *A Philosophy of Software Design*** → mine: complexity is the enemy; it accumulates from *dependencies* and *obscurity*; "deep modules" (simple interface, substantial behavior) over many shallow ones. Counter-mines Clean Code's "lots of tiny functions" — relevant to not over-splitting. Also "define errors out of existence" reduces local branching.
- **Martin Fowler — *Refactoring* (2nd ed.)** → mine: the smell→refactoring catalog for this category — *Long Function*, *Long Parameter List*, *Magic Number* → Replace Magic Literal with Symbolic Constant; *Nested Conditional* → Replace Nested Conditional with Guard Clauses (the **early-return** move); Decompose Conditional; Extract Function. These are the concrete fix names a review should suggest.
- **Kent Beck — *Tidy First?*** → mine: small, safe, local readability tidyings (guard clauses, explaining variables, dead-code removal, reorder for reading order, normalize symmetries) and *when* they pay off; the "symmetry" idea — express parallel things in parallel form — is explicit here. (Specific tidying list `(verify)`.)
- **Linus Torvalds / Linux kernel CodingStyle — "if you need more than 3 levels of indentation, you're screwed anyway"** → mine: a blunt, real heuristic that nesting depth ≈ complexity; supports an indentation-depth check.

### Tooling rules worth lifting
- **SonarQube `S3776` — "Cognitive Complexity of functions should not be too high."** Squid/rule key `S3776` (shared across language analyzers). The flagship cognitive-complexity gate; default threshold 15 `(verify)`.
- **ESLint `complexity`** — flags functions whose **cyclomatic** complexity exceeds a threshold (default 20; teams often set 10).
- **ESLint `max-depth`** — limits block nesting depth (default 4). Direct nesting-depth check.
- **ESLint `max-lines-per-function`**, **`max-lines`**, **`max-statements`** — function length / statement-count limits (the "Long Function" smell, mechanized).
- **ESLint `max-params`** — limits parameter count (the "Long Parameter List" smell; default 3).
- **ESLint `max-nested-callbacks`** — limits callback nesting ("pyramid of doom").
- **ESLint `no-magic-numbers`** — disallows unnamed numeric literals (with allow-lists, e.g. `0`/`1`); the canonical magic-number check. (No built-in magic-*string* rule; `sonarjs` / custom rules cover strings — `(verify)`.)
- **`eslint-plugin-sonarjs` `cognitive-complexity`** — brings Sonar's cognitive-complexity metric into ESLint.
- **RuboCop `Metrics/AbcSize`** — Assignments-Branches-Conditions size metric; a per-method complexity proxy (default threshold ~17 `(verify)`).
- **RuboCop `Metrics/CyclomaticComplexity`, `Metrics/PerceivedComplexity`, `Metrics/MethodLength`, `Metrics/BlockLength`, `Metrics/ParameterLists`** — the Ruby suite of length/complexity caps. `PerceivedComplexity` is Rubocop's cognitive-style metric.
- **Reek `TooManyStatements`, `NestedIterators`, `ControlParameter`, `TooManyBranches`** — method-too-long, deep-nesting, flag-argument, and branch-heavy smells (Ruby).
- **Pylint `too-many-branches` (R0912)**, **`too-many-statements` (R0915)**, **`too-many-nested-blocks` (R1702)**, **`too-many-arguments` (R0913)**, **`too-many-locals` (R0914)** — Python's local-complexity caps; `R1702` is a direct nesting-depth gate.
- **Pylint `magic-value-comparison` (R2004)** — flags comparisons against magic literals `(verify rule code)`. **`no-else-return` (R1705)** / **`inconsistent-return-statements` (R1710)** — nudge toward guard-clause / early-return symmetry.
- **golangci-lint linters: `gocyclo`** (cyclomatic), **`gocognit`** (cognitive), **`nestif`** (deeply-nested `if`), **`funlen`** (function length), **`cyclop`** (package+func cyclomatic), **`mnd`** (magic-number detector, formerly `gomnd`). A near-complete map of this category in one toolchain.
- **PMD `CyclomaticComplexity`, `CognitiveComplexity`, `NPathComplexity`, `ExcessiveMethodLength`, `ExcessiveParameterList`, `NPathComplexity`, `AvoidDeeplyNestedIfStmts`** (Java) — including **NPath** (count of acyclic execution paths), a stricter cousin of cyclomatic.
- **Lizard / radon** — language-agnostic cyclomatic-complexity + token-count + function-length reporters; radon also grades maintainability index (MI). Good for "metrics across the whole diff" framing.

### Reviewable heuristics (skill-checklist seeds)
- Does this function do *one* thing at *one* level of abstraction? (Altitude check: if it mixes a high-level policy step with low-level byte-twiddling/string-formatting, extract the low-level part.)
- Can you state the function's job in a single verb phrase without "and"? If not, it likely violates SRP — split it.
- Nesting depth ≤ ~3? Replace arrow-shaped nesting with **guard clauses / early returns**; invert conditions to de-nest the happy path.
- Any unexplained literal (number or string) that isn't `0`/`1`/`""`/obvious? Promote to a named constant whose name carries the *why* (`MAX_RETRIES`, `HTTP_TOO_MANY_REQUESTS`, `DEFAULT_PAGE_SIZE`).
- Cyclomatic complexity within budget (team threshold, commonly ≤10) and cognitive complexity ≤ ~15? Flag outliers for decomposition.
- Parameter count ≤ ~3; if more, is there a natural parameter object / options struct? No boolean flag parameters that fork the body into two behaviors (split into two functions instead).
- Is the **happy path** the un-indented main line, with errors/edge cases handled and returned early at the top?
- **Symmetry of expression**: parallel concepts written in parallel form (all branches `return x`, or all assign-then-fall-through — don't mix); paired operations adjacent and mirror-shaped (`acquire`/`release`, `open`/`close`); consistent ordering of similar arguments across sibling calls.
- Are there "explaining variables" for opaque sub-expressions, or is a dense boolean/arithmetic expression left to decode inline?
- No long runs of near-duplicated lines that beg for a loop or extracted helper (local DRY — but watch the #11 premature-abstraction counterweight: extract only on real, not coincidental, repetition).
- Does control flow avoid surprising jumps (deep `break`/`continue`/`goto`, mid-function `return` buried in nesting) that a reader can't track?
- Function length is "screenful-ish" and decomposes at natural seams — but resist splitting into so many one-line helpers that the reader must page-hop to follow one idea (Ousterhout counterweight to Clean Code).

---

## #7 Comments & inline docs — why-not-what, docstring accuracy, comment rot, dead code

### Key references
- **Robert C. Martin — *Clean Code*, ch. 4 "Comments"** → mine: "comments do not make up for bad code"; the *good* comments (intent, warning of consequences, TODO, legal, amplification, public-API docs) vs. the *bad* (redundant, misleading, mandated/noise, commented-out code, journal/attribution comments now handled by VCS). The "explain *why*, not *what*" thesis in operational form.
- **The canonical "comments should say WHY, not WHAT"** (community canon; also in *The Pragmatic Programmer*, McConnell, Stack Overflow / Coding Horror essays) → mine: the *what* is the code's job; comments earn their keep by capturing intent, rationale, constraints, and the road-not-taken. Reviewer check: does this comment restate the code (delete) or explain a decision (keep)?
- **Andrew Hunt & David Thomas — *The Pragmatic Programmer*** → mine: DRY applies to comments — a comment that duplicates code is a second source of truth that *will* drift; prefer making the code self-documenting and reserving comments for the non-obvious *why*. Also the "comments as a code smell when over-needed" framing.
- **Steve McConnell — *Code Complete*, ch. 32 "Self-Documenting Code"** → mine: a taxonomy of comment kinds (repeat, explain, marker, summary, intent), and the rule that good comments operate at the level of *intent*; bad comments document at the level of code. Also: comments should be maintained as first-class code.
- **Empirical "comment rot / inconsistent comments" research** (e.g. studies on comment–code inconsistency and "fraco"/`@param` staleness; specific authors/venues `(verify)`) → mine: comments drift from code measurably over a codebase's life; stale `@param`/`@return`/docstrings are a real, detectable defect class. Motivates an automated "doc mentions a parameter/return that no longer exists" check.
- **Language docstring conventions — PEP 257 (Python docstrings), JSDoc, Javadoc, rustdoc, KDoc** → mine: what "complete" looks like per ecosystem (summary line, params, returns, raises/throws, examples) so a reviewer can judge *completeness & accuracy*, not just presence.

### Tooling rules worth lifting
- **Pylint `missing-function-docstring` (C0116)**, **`missing-class-docstring` (C0115)**, **`missing-module-docstring` (C0112)** — presence-of-docstring gates.
- **Pylint `fixme` (W0511)** — flags `TODO`/`FIXME`/`XXX` markers; lets a team track (and forbid in release) outstanding-work comments.
- **pydocstyle / Ruff `D` rules (pydocstyle, `D1xx`–`D4xx`)** — enforce PEP 257 docstring *style and completeness* (e.g. `D100` missing module docstring, `D103` missing function docstring, `D417` missing argument descriptions in docstring). `D417` is a direct "docstring doesn't document all params" check.
- **Ruff/flake8 `eradicate` (`ERA001`)** / **`flake8-eradicate`** — detects **commented-out code** specifically. Direct hit on the "commented-out code" facet.
- **Ruff/flake8 `flake8-todos` / `flake8-fixme` (`T00x`/`FIX`)** — flag `TODO`/`FIXME`/`XXX`/`HACK` comments, sometimes requiring an author or issue link.
- **ESLint `no-warning-comments`** — flags `TODO`/`FIXME` (configurable terms); **`no-inline-comments`**, **`capitalized-comments`**, **`multiline-comment-style`** — comment-style consistency (cross-links #8).
- **ESLint `valid-jsdoc` (deprecated) / `eslint-plugin-jsdoc` rules** — e.g. `jsdoc/require-param`, `jsdoc/check-param-names`, `jsdoc/require-returns`, `jsdoc/no-undefined-types`. **`jsdoc/check-param-names`** catches docstring–signature drift (a stale `@param` name) — the comment-rot check, mechanized.
- **RuboCop `Style/CommentAnnotation`** (TODO/FIXME keyword formatting), **`Style/CommentedKeyword`**, **`Migration/DepartmentName`** `(verify last)` — comment hygiene; some setups add custom cops for commented-out code.
- **golangci-lint `godot`** (comments end with a period), **`godox`** (flags TODO/FIXME/BUG/HACK), **`revive` `exported`** (exported symbols must have a doc comment starting with the symbol name), **`misspell`** (typos in comments/strings). `godox` + `revive exported` together cover marker-comments and missing-API-doc.
- **SonarQube `S125` — "Sections of code should not be commented out."** Direct, language-agnostic commented-out-code rule. Also **`S1135`** (track `TODO` tags) and **`S1134`** (`FIXME` tags) — flag work-marker comments. **`S100`-series** include comment/doc rules `(verify exact squids)`.
- **Vulture (Python)** — dead-code detector (unused functions/vars/imports) — adjacent to commented-out code as "should-be-deleted" cruft.

### Reviewable heuristics (skill-checklist seeds)
- Does each comment explain **why** (intent, constraint, trade-off, gotcha, link to issue/spec) rather than restate **what** the code already says? Delete pure restatements.
- Is there any **commented-out code**? Delete it — version control is the archive. (Flag every block; commented-out code is near-universally noise.)
- Do docstrings/JSDoc/Javadoc **match the current signature**? Every documented `@param`/`@return`/`@raises` exists and is accurate; no parameter is undocumented; no documented param was renamed/removed (comment rot).
- For public/exported API, is the doc **complete**: one-line summary, params, return, errors/exceptions, and an example where non-trivial?
- Does the comment **agree with the code**? A comment that says "// retries 3 times" next to a loop bound of 5 is worse than no comment — flag contradictions as bugs.
- Are `TODO`/`FIXME`/`HACK` markers attributed and/or linked to a tracking issue, and is the count not silently growing? (Unowned TODOs rot.)
- No "journal"/changelog/author comments that VCS already tracks; no banner/noise comments that add zero information.
- Is a *needed* warning present? (Non-obvious side effects, ordering requirements, thread-safety, units, "do not call before X" — these are high-value comments to *request* when missing.)
- When a comment is required to explain confusing code, ask first whether **renaming/restructuring** would remove the need (self-documenting code over apologetic comment) — cross-links #5/#6.
- Are units, ranges, and invariants documented where the type system can't express them? (cross-links #4, #10.)
- Are licensing/attribution/provenance comments correct and present where required? (cross-links #27.)

---

## #8 Consistency & idiom — project conventions, idiomatic language/framework use, pattern consistency

### Key references
- **Language & org style guides** (the canonical heuristic sources) — **PEP 8** (Python), **Google Style Guides** (C++, Java, Python, Shell, TypeScript, Go, etc., at google.github.io/styleguide), **Airbnb JavaScript Style Guide**, **Effective Go / Go Code Review Comments**, **The Rust API Guidelines**, **Ruby Style Guide (rubocop-hq)**. → mine: each is a curated, battle-tested list of "in this ecosystem, do it *this* way" rules — the rawest source of idiom checks. We don't adopt one; we mine the *recurring* checks.
- **Effective Go + "Go Code Review Comments" (golang/go wiki)** → mine: the model of an *idiom* guide written as review comments (error handling shape, naming, receiver names, interface size, `gofmt` non-negotiable). A template for the "idiomatic use" half of this category.
- **Andrew Hunt & David Thomas — *The Pragmatic Programmer* ("Orthogonality", "DRY", "principle of least surprise")** → mine: consistency is least-surprise; a reader who has learned one part of the codebase should be able to predict the rest. Pattern inconsistency taxes that.
- **Martin Fowler — *Refactoring* + "patterns of enterprise..." canon** → mine: when a codebase has *chosen* a pattern (Repository, Result type, error-as-value, hexagonal ports), new code should conform; divergence without reason is a smell. The check is "is this the way this codebase already solves this problem?"
- **Sandi Metz / "the wrong abstraction"** (cross-links #11) → mine: consistency is good *until* it forces the wrong shape; flag inconsistency, but don't demand uniformity that papers over genuinely different cases. A counterweight to over-zealous "make it match."
- **Opinionated-reviewer prior art** (from ../prior-art.md): `dhh-rails-reviewer`, `kieran-rails/typescript/python-reviewer`, `pattern-recognition-specialist` → mine: the *named-perspective* pattern — a reviewer with strong, ecosystem-specific taste catches idiom violations a generic linter misses. Worth replicating per ecosystem in the skill suite.

### Tooling rules worth lifting
- **Formatters as the floor: Prettier, Black, gofmt/goimports, rustfmt, `clang-format`, `dotnet format`.** → not "rules" with IDs but the strongest consistency mechanism: mechanical, non-negotiable formatting removes whole classes of consistency nits from review. The heuristic to lift: *if a formatter exists for the ecosystem and isn't applied, that's the finding.*
- **Biome / Ruff / golangci-lint / RuboCop as aggregate "is the code idiomatic" gates** — each bundles dozens of idiom rules; the *meta*-rule to lift is "the project's own linter config is the source of truth for its conventions — read it, then check the diff against it."
- **RuboCop `Style/*` department** (hundreds of cops, e.g. `Style/GuardClause`, `Style/StringLiterals`, `Style/HashSyntax`, `Style/FrozenStringLiteralComment`, `Style/NumericLiterals`, `Style/SymbolArray`) — Ruby idiom enforcement; `Style/GuardClause` (prefer early-return) bridges to #6.
- **ESLint `consistent-return`** (a function always or never returns a value), **`prefer-const`**, **`no-var`**, **`prefer-template`** (template literals over `+`), **`object-shorthand`**, **`prefer-arrow-callback`**, **`dot-notation`** — each encodes "the idiomatic modern-JS way." `consistent-return` also bridges to #6 symmetry.
- **`@typescript-eslint` idiom rules** — `prefer-nullish-coalescing`, `prefer-optional-chain`, `consistent-type-imports`, `array-type` (consistent `T[]` vs `Array<T>`), `naming-convention` (project-wide casing per symbol kind). `naming-convention` cross-links #5.
- **Pylint `consider-using-*` family** (e.g. `consider-using-with` R1732, `consider-using-enumerate` C0200, `consider-using-f-string`, `consider-using-dict-items`) — nudge toward idiomatic Python constructs over clumsy equivalents.
- **Ruff `UP` (pyupgrade) rules** — flag outdated idioms vs. modern Python (`%`-format → f-string, `typing.List` → `list`, etc.) — "is this written in the current idiom?"
- **golangci-lint `gofmt`/`gofumpt`** (formatting), **`revive`/`stylecheck` (`ST1xxx`)** — Go style/idiom checks (e.g. error strings shouldn't be capitalized or end with punctuation: `ST1005`); **`errcheck`**, **`errorlint`** (idiomatic error wrapping `%w`), **`whitespace`**, **`tagliatelle`** (consistent struct-tag casing).
- **SonarQube consistency rules** — e.g. **`S3457`** (format strings), naming-convention rules **`S100`/`S101`/`S117`** (method/type/variable naming match a regex), **`S1192`** ("string literals should not be duplicated" — pushes toward a shared constant; cross-links #6 magic-strings and pattern consistency). `(verify squids)`
- **EditorConfig + commit/format pre-commit gates** — `.editorconfig` (charset, indent, line-ending consistency) and `pre-commit`/`lint-staged` running the above; the *presence and enforcement* of these is itself the consistency control to check for.

### Reviewable heuristics (skill-checklist seeds)
- Does the change **follow the project's own conventions**? Read the existing `.eslintrc`/`.rubocop.yml`/`ruff.toml`/`.editorconfig`/style guide first; the codebase's established choice wins over personal preference.
- Is the code **formatted** by the project's formatter? (If Prettier/Black/gofmt exists, unformatted code is an automatic finding — don't spend review attention on what a formatter should fix.)
- Does it use the **idiomatic construct** for this language/framework, or a clumsy non-native equivalent? (e.g. list comprehension vs. manual loop in Python; `Result`/error-as-value vs. exceptions in a codebase that chose one; framework's router/ORM idiom vs. hand-rolled.)
- **Pattern consistency**: does this solve a recurring problem the *same way* the codebase already solves it? (Same error-handling shape, same DTO/serialization approach, same dependency-injection style, same test layout.) Divergence needs a stated reason.
- Are **naming/casing conventions** uniform across the symbol kind (files, classes, constants, test names)? No mixed `snake_case`/`camelCase` for the same role. (cross-links #5.)
- Is import ordering / module structure / file layout consistent with siblings? (New file placed where a reader would expect it.)
- Are **strings/messages/log formats** consistent with existing ones (capitalization, punctuation, error-message shape)? (cross-links #16.)
- Does the change avoid introducing a **second way to do the same thing** (a parallel util, a competing abstraction) when one already exists? (cross-links #11/#9.)
- When the existing convention is genuinely worse, is the change either fully migrating to the better one (not adding a third style) or explicitly flagged as a deliberate, scoped exception? (Avoid "consistency with a bad pattern" *and* avoid silent divergence — pick one and say so.)
- Framework idiom: are lifecycle/hooks/decorators/middleware used the framework-blessed way, not fought against? (e.g. React hooks rules, Rails callbacks vs. service objects per the app's chosen style, dependency-injection per the framework.)
- Is configuration-as-convention respected (folder-by-feature vs. folder-by-type, test-file naming, public-API surface) so the next engineer "falls into the pit of success"? (cross-links #9 caller ergonomics.)
- Counterweight check: am I demanding consistency that erases a *meaningful* difference between two cases (forcing the wrong abstraction)? If the cases truly differ, divergence is correct — don't flag it.

---

## Open threads   (gaps / mis-placements / sub-topics worth deeper research)

- **Live-source verification debt (highest priority).** This file was produced without live web access; every `(verify)` tag and every omitted URL should be re-checked in a pass that can reach: the SonarSource Cognitive Complexity white paper (default threshold + which constructs increment), Belshee's "Naming as a Process" (exact stage labels/order), Pylint/RRuboCop/golangci-lint rule IDs and current defaults, and SonarQube squid numbers (`S3776`, `S125`, `S1135/S1134`, `S1192`, `S100/S101/S117`). Treat all rule IDs here as high-confidence-but-unverified.
- **#6 ↔ #11 boundary (decomposition vs. over-decomposition).** Clean Code's "many tiny functions" vs. Ousterhout's "deep modules" is a genuine tension that lands across #6 (local readability) and #11 (abstraction/simplicity). The skill suite needs an explicit stance so a "split this function" reviewer and a "stop over-abstracting" reviewer don't fight. Flagged as a design question, not just a reference gap.
- **Magic *strings* are under-tooled vs. magic numbers.** ESLint has `no-magic-numbers` but no built-in magic-string rule; coverage comes from Sonar `S1192` (duplicated literals) and plugins. Worth a dedicated heuristic since config keys, routes, and event names are common magic-string offenders.
- **Naming and consistency overlap heavily (#5 ↔ #8).** Casing/convention checks (`id-match`, `naming-convention`, Pylint `invalid-name`) sit on the seam. Suggest treating *intention-revealing-ness* as #5 and *uniformity of convention* as #8 to avoid double-coverage; noted inline but worth a taxonomy decision.
- **Comment-rot empirical literature needs real citations.** The "comments drift / inconsistent-comment detection" research is asserted from general knowledge; the specific studies (authors, venues, the comment–code inconsistency detection tools) must be sourced before this becomes a skill claim. Marked `(verify)` in #7.
- **"Altitude / level-of-abstraction mixing" is poorly tooled.** No linter cleanly detects high+low-level mixing in one function; it's a judgment heuristic. This is a candidate for an *LLM-reviewer* behavior (where pattern-matching beats static rules) rather than a lint rule — relevant to phase-2 skill design.
- **Symmetry-of-expression** similarly has no direct linter; `consistent-return` and guard-clause cops touch it but don't capture parallel-structure symmetry. Another likely LLM-reviewer-only heuristic.
- **Opinionated per-ecosystem reviewers** (dhh/kieran-style, from prior-art) suggest #8 may not be one generic skill but a *family* of idiom reviewers (one per language/framework) sharing a common "read the project config, then check the diff against it" spine. Composition question for phase 2.
