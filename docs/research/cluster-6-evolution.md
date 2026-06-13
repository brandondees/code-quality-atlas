# Research — Cluster VI: Evolution & humans (Maintainability & Process)
>
> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Drafted 2026-06-08 (from model knowledge, web-less subagent); **web-verified 2026-06-09 from the main loop.** Standards spines (WCAG 2.2 SCs, Conventional Commits, Diátaxis, ADR, Keep a Changelog, SPDX/AGPL copyleft, REUSE, EAA, GDPR) and high-traffic tool rule IDs (axe-core, eslint-plugin-jsx-a11y, commitlint, the SmartBear/Cisco review-size study) are confirmed against live sources. Residual `(verify)` marks niche/less-stable tool rule names (some SonarQube squids, formatjs/i18next/html-validate plugin rules) to confirm at skill-build time.

---

## #21 Maintainability & evolvability

Scope: change amplification (one change → many edits); blast radius / ripple effects; refactorability (safe to change); tech-debt visibility & accounting; onboarding cost; bus factor / knowledge concentration.

### Key references

- **John Ousterhout — *A Philosophy of Software Design*** (2018/2021). `(verify)` URL.
  → mine: "change amplification" and "cognitive load" as named symptoms of complexity; the *deep module* (simple interface, substantial implementation) as the antidote — a diff that widens a shallow module's interface is a maintainability smell.
- **Martin Fowler — "Technical Debt Quadrant"** — martinfowler.com/bliki/TechnicalDebtQuadrant.html `(verify)`.
  → mine: two axes — reckless↔prudent and deliberate↔inadvertent — to *classify* a debt note, not just flag it. "Prudent/deliberate" debt is acceptable if tracked; "reckless/inadvertent" is the danger zone.
- **Martin Fowler — *Refactoring* (2nd ed.)** and "Is High Quality Software Worth the Cost?" `(verify)`.
  → mine: refactorability requires test coverage as a safety net; the "design stamina hypothesis" — internal quality pays off past a short payback period. A change to under-tested code raises blast-radius risk.
- **Meir Lehman — Laws of Software Evolution** (continuing change; increasing complexity) `(verify)`.
  → mine: software that is used *must* change, and absent deliberate work its complexity rises — so maintainability is a moving target, and "no change needed here" is itself a claim to check.
- **Adam Tornhill — *Your Code as a Crime Scene* / *Software Design X-Rays*; CodeScene** `(verify)`.
  → mine: behavioral code analysis — hotspots = high churn × high complexity; "knowledge maps" and bus-factor/abandoned-code via VCS authorship. Change-coupling (files that change together but don't reference each other) as a hidden-ripple signal.
- **Michael Feathers — *Working Effectively with Legacy Code*** `(verify)`.
  → mine: "legacy = code without tests"; *seams* and characterization tests as the precondition for safe change. A diff that adds behavior to untested code without first adding a pin-down test is risky.
- **Connascence (Meilir Page-Jones; connascence.io)** `(verify)`.
  → mine: a vocabulary for coupling strength (name → type → meaning → position → algorithm → execution-order → timing → value → identity) and *locality* (connascence across module boundaries is worse). Useful to name *why* a change amplifies.

### Tooling rules worth lifting

- **CodeScene** — *Hotspot* (high change-frequency × high complexity), *Change Coupling*, *Code Health* decline, *Knowledge Loss / off-boarded code*, *Brain Method / Brain Class* — VCS-aware maintainability signals. `(verify)` exact metric names.
- **SonarQube** — `Maintainability` rating (A–E), *Technical Debt Ratio* (remediation effort ÷ dev cost), *Code Smells* category, rule `java:S3776` Cognitive Complexity is too high, `java:S138` method too long. `(verify)` squids.
- **RuboCop** — `Metrics/AbcSize`, `Metrics/CyclomaticComplexity`, `Metrics/PerceivedComplexity`, `Metrics/MethodLength`, `Metrics/ClassLength` — proxies for change-difficulty.
- **Reek (Ruby)** — `FeatureEnvy`, `DataClump`, `TooManyInstanceVariables`, `RepeatedConditional` — smells that predict ripple edits.
- **ESLint** — `complexity`, `max-depth`, `max-lines`, `max-lines-per-function`, `max-params` — caps that bound per-unit change cost.
- **Lizard / radon (Python)** — cyclomatic complexity (CC), `radon mi` Maintainability Index, `radon cc` per-function — language-agnostic hotspot inputs.
- **PMD** — `CyclomaticComplexity`, `NPathComplexity`, `GodClass`, `ExcessiveImports`, `CouplingBetweenObjects` — fan-out / god-module ripple risk. `(verify)` rule names.
- **`git-of-theseus` / `hercules` / `git-quick-stats`** — repo-level churn, code age, and authorship/bus-factor analytics. `(verify)`.
- **TODO/FIXME/DEBT-tracking linters** (e.g. ESLint `no-warning-comments`, or a `todo-or-die`-style check) — surface *untracked* debt markers so debt is accounted, not invisible.

### Reviewable heuristics (skill-checklist seeds)

- **Change amplification:** did one conceptual change force edits in N>3 files/modules? If so, is that essential (one concept, many sites) or accidental (a missing abstraction / leaked detail)?
- **Shotgun surgery smell:** the same constant, enum case, validation, or shape is edited in multiple places in this diff — flag for consolidation.
- **Blast radius:** does the change touch a high fan-in module (many importers)? Is there a contract/compat note or test proving downstream callers still hold?
- **Refactorability gate:** is the changed code covered by tests *before* the change? If not, was a characterization/pin-down test added first?
- **Debt visibility:** new `TODO`/`FIXME`/`HACK` — does it link to a tracked issue and say *why* (Fowler quadrant: deliberate+prudent is OK if recorded)? Reject silent/untracked debt.
- **Knowledge concentration / bus factor:** does this PR touch a file with a single historical author or a long-abandoned area? Flag for a second reviewer / knowledge-spreading.
- **Onboarding cost:** would a new engineer understand *why* this exists from the code + nearby docs alone, or only from tribal knowledge?
- **Hidden coupling:** are two files that "shouldn't" know about each other being changed together again (change-coupling)? Name the implicit contract.
- **Connascence locality:** does the change introduce connascence (of position, meaning, value, timing…) that crosses a module boundary? Stronger/longer-distance connascence = higher amplification.
- **Reversibility:** is this change easy to undo, or does it bake in a one-way decision (data format, public API, migration)? One-way doors deserve more scrutiny.
- **Complexity trend:** does the diff raise cyclomatic/cognitive complexity of an already-hot function, or reduce it? Net direction matters more than absolute number.
- **Speculative generality (counterweight):** is added "flexibility" (config knobs, plugin points, abstract base) justified by a *present* second use, or is it pre-emptive and itself future maintenance cost?

---

## #22 Documentation & knowledge

Scope: API docs & docstrings; README / onboarding; architecture decision records (ADRs); runbooks; changelogs; usage examples & diagrams.

### Key references

- **Diátaxis (Daniele Procida) — https://diataxis.fr/**
  → mine: four distinct doc modes — **tutorials** (learning-oriented), **how-to guides** (task/goal-oriented), **reference** (information-oriented), **explanation** (understanding-oriented) — on two axes (action↔cognition, acquisition↔application). A doc that mixes modes (tutorial that drifts into reference) is a smell; missing a *whole quadrant* (e.g. no how-tos) is a gap.
- **Michael Nygard — "Documenting Architecture Decisions" (ADR, 2011)** — https://adr.github.io/ (overview: https://martinfowler.com/bliki/ArchitectureDecisionRecord.html)
  → mine: lightweight, immutable, append-only decision records with the fields **title, status, context, decision, consequences** (status: proposed/accepted/superseded). The *why* lives here, not in code comments. Superseding rather than editing preserves history.
- **Keep a Changelog — https://keepachangelog.com/ + Semantic Versioning — https://semver.org/**
  → mine: human-readable `CHANGELOG.md` grouped by Added/Changed/Deprecated/Removed/Fixed/Security, newest-first, `Unreleased` section; tie entries to SemVer bumps. "Don't let your friends dump git logs into changelogs" `(verify)` phrasing.
- **Google Developer Documentation Style Guide / "Docs as Code"** `(verify)`.
  → mine: docs live in the repo, reviewed in PRs, linted and built in CI; same change should update the doc that describes it. Treat doc drift like a failing test.
- **Write the Docs community / "documentation system" essays** `(verify)`.
  → mine: README-as-front-door checklist (what it is, why, install, minimal usage, where to go next); the "minimal runnable example" as the highest-leverage doc artifact.
- **The C4 model (Simon Brown) and Mermaid / PlantUML diagrams-as-code** `(verify)`.
  → mine: diagrams should be versioned text (Mermaid/PlantUML), not binary screenshots, so they're diffable and stay in sync; C4's Context→Container→Component levels give a "what level is this diagram" check.
- **AGENTS.md — open agent-instructions convention** — https://agents.md/ (introduced by OpenAI 2025-08; stewarded by the **Agentic AI Foundation** under the Linux Foundation since 2025-12, founded by Anthropic, OpenAI, and Block; adopted by tens of thousands of repos and the major coding agents).
  → mine: "a README for agents" — a repo-level Markdown file carrying build/test/lint commands, conventions, and layout for *automated* contributors, with **nearest-file-wins** precedence so monorepo subprojects ship tailored instructions. Establishes agent-facing docs as a first-class doc artifact — which means it inherits every doc obligation in this category, drift above all (a stale AGENTS.md actively misleads agents that, unlike humans, won't shrug it off).

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

### Reviewable heuristics (skill-checklist seeds)

- **API surface ↔ docs parity:** does every new/changed public function, endpoint, CLI flag, or config key have a docstring/doc updated in the same diff? Stale signature-vs-doc = drift.
- **Docstring accuracy:** do param names, types, return, and `raises`/`throws` in the docstring match the actual signature *after* this change? (params renamed but docstring not — flag.)
- **Diátaxis coverage:** for a new feature, is there at least the right *mode* of doc — a how-to for a task, reference for an API? Don't accept a tutorial as a substitute for reference.
- **README front-door:** does the README still answer what/why/install/minimal-example/next-steps after this change? New setup step but no README update = onboarding regression.
- **Runnable example:** does the example actually run against the new code (compiles, imports resolve, no removed API)? Prefer doctests/CI-checked snippets.
- **ADR for non-obvious decisions:** does an architecturally significant or surprising choice (new dependency, pattern, boundary, trade-off) have an ADR capturing context/decision/consequences? Code comments are not a substitute for the *why*.
- **Changelog discipline:** does a user-facing change add a CHANGELOG entry in the right category, and is the SemVer impact (patch/minor/major, esp. breaking) correct?
- **Runbook for operability:** for a new operational surface (job, queue, feature flag, alert), is there a runbook saying how to detect, diagnose, and remediate / roll back?
- **Diagrams as code & current:** are diagrams diffable text (Mermaid/PlantUML), and do they still reflect the components after this change, or are they now stale?
- **No orphaned/contradictory docs:** does this change delete or supersede docs it invalidates (removed endpoint still documented; deprecated path still in tutorial)?
- **Comment rot:** are nearby comments/docstrings that the change falsifies updated or removed (not left lying)?
- **Discoverability:** is the new doc linked from an index/nav/README, not just dropped in a folder?
- **Agent-instructions drift:** if the repo carries an agent-instructions file (AGENTS.md / CLAUDE.md / equivalent), does this change keep it true — build/test/lint commands still correct, conventions and layout still accurate, subproject files updated where nearest-file-wins applies? Same drift class as README rot, but higher blast radius: agents follow stale instructions literally (cross #24 agent-native parity).

---

## #23 Accessibility & i18n

Scope: WCAG conformance; semantic markup & ARIA; keyboard nav & focus; localization (no hardcoded strings, RTL, number/date/currency/unit formatting — correctness cross-links #4); responsive/edge layouts; design fidelity vs. spec.

### Key references

- **W3C — WCAG 2.2** — https://www.w3.org/TR/WCAG22/ — POUR: Perceivable, Operable, Understandable, Robust; conformance levels A / AA / AAA (AA is the common legal bar).
  → mine: AA is the common legal/contractual bar. High-value SCs to check: **1.1.1 Non-text Content** (alt text), **1.4.3 Contrast (Minimum)** (4.5:1 text / 3:1 large), **2.1.1 Keyboard** (all functionality via keyboard), **2.4.7 Focus Visible**, **2.4.3 Focus Order**, **4.1.2 Name, Role, Value**, **3.3.2 Labels or Instructions**, **1.3.1 Info and Relationships**, **2.5.3 Label in Name**, and 2.2-added **2.4.11 Focus Not Obscured (Minimum)** (AA), **2.5.8 Target Size (Minimum)** 24×24 CSS px (AA). *(SC numbers verified against w3.org/TR/WCAG22.)*
- **WAI-ARIA Authoring Practices Guide (APG)** `(verify)`.
  → mine: "first rule of ARIA — use native HTML if you can"; correct roles/states/keyboard interaction patterns for widgets (dialog, menu, combobox, tabs). Misused ARIA is worse than none.
- **MDN — Accessibility & Internationalization; `Intl` API** `(verify)`.
  → mine: use `Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.PluralRules`, `Intl.Collator` instead of hand-rolled formatting; locale + currency are inputs, never hardcoded. Cross-links #4 (money/units correctness).
- **Unicode CLDR / ICU MessageFormat** `(verify)`.
  → mine: locale data (plural categories beyond singular/plural, date/number patterns, RTL) belongs to CLDR; pluralization and gender/select via ICU MessageFormat, not string concatenation. Don't assume two plural forms.
- **EN 301 549 / ADA / Section 508 / European Accessibility Act (EAA)**
  → mine: accessibility is frequently a *legal* requirement (cross-links #27), typically anchored to WCAG 2.x AA. The **EAA (EU Directive 2019/882) came into full effect 2025-06-28**, applying to products/services sold into the EU regardless of where the company is based — raising the stakes materially for consumer products.
- **Deque "axe" rules / WebAIM (contrast, screen-reader surveys)** `(verify)`.
  → mine: the most common real-world failures cluster in low contrast, missing alt, empty links/buttons, missing form labels, missing document language — prioritize checks there.

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

### Reviewable heuristics (skill-checklist seeds)

- **Semantic-first:** is a real `<button>`/`<a>`/`<nav>`/`<main>`/heading used, or a `<div>` with a click handler? Native element = keyboard + role + focus for free.
- **Keyboard operable:** can every interactive element be reached and activated by Tab/Shift-Tab/Enter/Space/Escape/arrows as appropriate? No mouse-only handlers (click without key handler).
- **Focus management:** after opening a modal/menu/route change, does focus move sensibly and return on close? Is focus trapped in the dialog? Is `:focus-visible` styling present (not `outline:none` with no replacement)?
- **Name/role/value:** do icon-only buttons, inputs, and custom widgets have accessible names (label, `aria-label`, `aria-labelledby`)? No empty buttons/links.
- **Contrast:** does new text/UI meet 4.5:1 (or 3:1 large / non-text)? Check both themes if dark mode exists.
- **Images & media:** meaningful images have descriptive `alt`; decorative images have empty `alt=""`; videos have captions/transcript where required.
- **ARIA discipline:** is ARIA only used where native HTML can't express it, with all required states (e.g. `aria-expanded`, `aria-selected`) wired and *updated*? No redundant/conflicting roles.
- **No hardcoded user-facing strings:** is every new UI string going through the i18n catalog (no literal JSX/template text)? Includes aria-labels, placeholders, error messages, pluralized/templated text.
- **Pluralization & interpolation:** are plurals/gender handled via ICU/`Intl.PluralRules` (not `count + "s"`), and do interpolation placeholders match across all locale files?
- **Locale-aware formatting:** are numbers/dates/currency/units formatted via `Intl`/CLDR with explicit locale + currency, not hand-built strings or assumed `en-US`/`USD`? (cross-links #4 money/units correctness.)
- **RTL & expansion:** does layout use logical properties / direction-agnostic CSS, and tolerate ~30–40% text expansion and longer words without clipping/overlap? Mirrored icons where directional.
- **Responsive/edge layouts:** does it hold up at small/large viewports, 200% zoom, and long-content edge cases without loss of content or function (WCAG 1.4.10 Reflow, 1.4.4 Resize Text)? `(verify)`.
- **Target size:** are interactive targets ≥24×24px (WCAG 2.2 2.5.8) with adequate spacing? `(verify)`.
- **Document language:** is `<html lang>` set/updated, and per-element `lang` on foreign-language runs?
- **Design fidelity vs. spec:** does the implementation match the design/spec for spacing, states (hover/focus/disabled/error), and content — flag silent deviations.

---

## #24 Process & collaboration

Scope: PR size & reviewability; commit atomicity & message hygiene; risk signaling in commits/PRs; ownership (CODEOWNERS); definition of done; agent-native parity.

### Key references

- **Conventional Commits 1.0.0** — https://www.conventionalcommits.org/en/v1.0.0/ (feat→MINOR, fix→PATCH, `!`/`BREAKING CHANGE:`→MAJOR).
  → mine: `type(scope)!: subject` + body + footer; types `feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`perf`/`build`/`ci`; `!` or `BREAKING CHANGE:` footer signals SemVer-major. Machine-readable risk/intent → auto-changelog and release decisions (links #22).
- **Google Engineering Practices — "Code Review Developer Guide" (Small CLs; What to look for)** `(verify)`.
  → mine: prefer small, single-purpose changelists; review for design, functionality, complexity, tests, naming, comments; "approve when it definitely improves overall code health, even if not perfect."
- **SmartBear / Cisco code-review study** (10 months, 2,500 reviews, 3.2M LOC at Cisco) — smartbear.com "Best Practices for Peer Code Review".
  → mine: defect-detection density is highest **below 200 LOC** and falls off **above ~400 LOC**; best inspection rate **<300–500 LOC/hour** and within **60–90 min** before detection plummets (≈70–90% defect yield at that pace). Big PRs get rubber-stamped — size is itself a quality risk.
- **Tim Pope — "A Note About Git Commit Messages"** `(verify)`.
  → mine: imperative-mood subject ≤~50 chars, blank line, wrapped body explaining *why* not *what*; one logical change per commit. Atomic commits enable clean revert/bisect.
- **Chris Beams — "How to Write a Git Commit Message" (seven rules)** — https://cbea.ms/git-commit/ (50-char imperative subject, blank line, 72-wrapped body, why-not-how).
  → mine: the concrete subject/body rules; "If applied, this commit will <subject>." as the imperative test.
- **GitHub Docs — CODEOWNERS** `(verify)`.
  → mine: path-based required reviewers; ownership makes "who must approve this area" explicit and routes risk to the right people. Stale/missing CODEOWNERS = unowned blast radius.
- **Agent-native architecture (compound-engineering `agent-native-reviewer` prior art; "any action a user can take, an agent can too")** `(verify)`.
  → mine: parity check — new user-facing capabilities should also be reachable programmatically (API/CLI/tool), not UI-only, so agents and automation aren't second-class. (Project-specific principle; map to a reviewable check.)
- **AGENTS.md / Agentic AI Foundation (Linux Foundation, 2025-12)** — https://agents.md/ (see #22 for the doc-artifact side).
  → mine: industry grounding for treating agents as first-class contributors to the development process — the ecosystem now standardizes how repos onboard automated collaborators. Strengthens the agent-native-parity principle from "house rule" toward industry practice; the *docs* obligation lives in #22, the *process* stance (agents can do what contributors can do) lives here.

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

### Reviewable heuristics (skill-checklist seeds)

- **PR size & focus:** is the PR small and single-purpose (roughly ≤~400 net LOC, one concern)? If it mixes refactor + feature + format churn, suggest splitting — mixed diffs hide bugs.
- **Atomic commits:** does each commit represent one logical change that builds and (ideally) passes tests on its own, enabling clean `revert`/`bisect`? No "fix typo"/"wip"/"address review" noise left in final history.
- **Commit message hygiene:** imperative-mood subject within length limit; body explains *why* and trade-offs, not a restatement of the diff; links the issue/ticket.
- **Conventional type & scope:** is the commit/PR typed correctly (`fix` vs `feat` vs `refactor`) — because it drives versioning and changelog?
- **Breaking-change signaling:** if the change alters a public API/contract/schema/config, is it marked breaking (`!` / `BREAKING CHANGE:`) and is the migration noted? Silent breaking changes are a top review failure.
- **Risk signaling:** does the PR description state blast radius, rollback plan, feature-flag status, and what was/wasn't tested? Risky areas (auth, money, migrations, concurrency) called out for closer review.
- **Ownership routing:** do touched paths have CODEOWNERS, and are the right owners requested? Unowned critical paths flagged.
- **Definition of done:** tests added/updated, docs/changelog updated, lint/type/CI green, no debug/console/commented-out code, no TODOs without tracked issues — all present before merge.
- **Reviewability aids:** PR description, screenshots/recordings for UI, and a self-review pass; large mechanical changes separated from logic changes so reviewers can focus.
- **No drive-by scope creep:** unrelated reformatting/renames bundled into a feature PR — flag to separate so the diff stays reviewable.
- **Agent-native parity:** does a new user-facing action also have a programmatic path (API/CLI/tool), and is it documented for automation — not UI-only?
- **Secrets / artifacts in commits:** no credentials, `.env`, large binaries, or generated files committed (links #14/#19).

---

## #27 Compliance, licensing & provenance

Scope: dependency license compatibility & copyleft contamination; code provenance & attribution (incl. AI-generated code); regulatory & data-privacy obligations (GDPR/CCPA-style handling, residency, retention, consent); accessibility-as-legal-requirement; export/compliance constraints.

### Key references

- **SPDX — license identifiers + SBOM** — https://spdx.org/licenses/ (standard short IDs + permanent URLs).
  → mine: standard license IDs (`MIT`, `Apache-2.0`, `GPL-3.0-only`, `LGPL-3.0`, `AGPL-3.0-only`, `BSD-3-Clause`, `MPL-2.0`) and `SPDX-License-Identifier:` headers; SBOM (SPDX / CycloneDX) as the provenance artifact a review can check against.
- **FSF "copyleft" guidance + Blue Oak / choosealicense.com**
  → mine: copyleft strength ladder — permissive (MIT/BSD/Apache-2.0) → weak/file-level (MPL-2.0, LGPL) → strong (GPL) → network/strong (AGPL). **AGPL triggers on *network interaction*, not just distribution** — the classic SaaS surprise: modifying AGPL software and offering it as a service obliges you to provide its source to users who interact with it. Apache-2.0 carries an explicit patent grant; GPLv2-only ↔ Apache-2.0 is a known incompatibility.
- **OpenChain / OWASP Dependency-Track + CycloneDX** `(verify)`.
  → mine: continuous SBOM-based license + vulnerability + policy monitoring; treat license policy as a gate, not a one-time audit. (Vuln side cross-links #18.)
- **GDPR (EU 2016/679) & CCPA/CPRA**
  → mine: lawful basis + consent, **data minimization**, purpose limitation, storage-limitation/**retention**, data-subject rights (access/erasure/portability), **data residency**/cross-border transfer, breach-notification timelines. Code that collects/stores/transfers PII must map to these (cross-links #14 PII handling, #16 telemetry).
- **REUSE Specification (FSFE)** — https://reuse.software/spec/ (`reuse lint` makes per-file SPDX+copyright machine-checkable).
  → mine: every file should declare copyright + SPDX license (header or `.license` sidecar); `reuse lint` makes provenance machine-checkable. A new source file with no license header is a provenance gap.
- **DCO (Developer Certificate of Origin) / `Signed-off-by` + AI-codegen provenance debates** `(verify)`.
  → mine: contributor attestation of right-to-contribute; the open question of attribution/licensing for AI-generated code and training-data provenance — at minimum, label AI-assisted contributions and run license/secret/IP checks on them as untrusted input.
- **Accessibility-as-law: ADA / Section 508 / EN 301 549 / EAA (EU 2019/882, in force 2025-06-28)**
  → mine: WCAG 2.x AA conformance is the de facto legal yardstick (cross-links #23) — a11y findings can carry legal, not just UX, weight.

### Tooling rules worth lifting

- **`license-checker` / `license-checker-rseidelsohn` (npm)** — enumerate dependency licenses; `--failOn` / `--onlyAllow` to block disallowed licenses (e.g. GPL/AGPL) in a permissive project. `(verify)`.
- **FOSSA / Snyk / WhiteSource(Mend) / Black Duck** — license-policy gates, copyleft/contamination alerts, attribution-report generation, IP-snippet matching. `(verify)`.
- **ScanCode Toolkit + ScanCode.io** — detect licenses/copyrights/origin in source (provenance), emit SPDX. `(verify)`.
- **`reuse lint` (REUSE)** — fail when files lack SPDX license + copyright headers. `(verify)`.
- **`pip-licenses` (Python) / `cargo-deny` (Rust) / `go-licenses` (Go) / `licensee` (GitHub's repo license detector)** — per-ecosystem license inventory + allow/deny lists; `cargo-deny` also bans yanked/duplicate/vuln crates. `(verify)`.
- **Syft + Grype / Trivy / OWASP Dependency-Track** — generate SBOM (SPDX/CycloneDX) and run license **and** vuln policy; Trivy `--license-full` license scanning. `(verify)`.
- **DCO bot / `Signed-off-by` enforcement (`commit-msg` hook, GitHub DCO app)** — gate contributions on origin attestation. `(verify)`.
- **Secret scanners as provenance/compliance gate** — Gitleaks, TruffleHog, `detect-secrets` — block committed credentials/PII (overlaps #14) that create regulatory exposure.
- **Privacy/PII linters** — e.g. `semgrep` registry rules for PII logging / hardcoded keys; `eslint-plugin-no-secrets`; data-flow rules flagging PII to logs/3rd-party (overlaps #16/#25). `(verify)` exact rule ids.

### Reviewable heuristics (skill-checklist seeds)

- **New dependency license check:** does an added dependency (and its transitive tree) carry a license compatible with the project's distribution model? Block/strongly-flag GPL/AGPL pulled into a permissive or proprietary product.
- **Copyleft contamination / linkage:** does the change *link* or *combine* with copyleft code in a way that triggers obligations (esp. AGPL over a network service)? Static vs. dynamic linking and "mere aggregation" matter — flag for legal if unsure.
- **License/attribution preservation:** are upstream license texts, copyright notices, and NOTICE files retained when vendoring/copying code? Removed attribution = violation.
- **Provenance of copied code:** does this diff include code pasted from Stack Overflow, a blog, another repo, or AI generation without attribution/license clarity? Treat as untrusted: verify license, run secret/IP scan, label it.
- **Per-file license header:** do new source files have an `SPDX-License-Identifier` + copyright (REUSE)? Missing header = provenance gap.
- **PII data-flow:** does new code collect, store, log, or transmit personal data? If so — lawful basis/consent present, **minimized** to what's needed, not logged in plaintext, and not sent to a third party/region without basis (cross-links #14, #16, #25).
- **Retention & deletion:** is there a retention limit and an erasure path for new personal data (right-to-be-forgotten), or does it accumulate indefinitely?
- **Data residency / cross-border:** does the change move PII to a new region, vendor, or third-party model (incl. LLM APIs) — is that transfer permitted and documented? (cross-links #25 PII-to-model.)
- **Consent & purpose:** for new tracking/telemetry/analytics, is consent gating in place and is use limited to the stated purpose? No silent expansion of data use.
- **Accessibility-as-legal:** for regulated/consumer surfaces, does the change keep WCAG 2.x AA conformance (cross-links #23) given its legal weight?
- **Export / sanctions / crypto constraints:** does new cryptography, or distribution to restricted regions, hit export-control or compliance obligations? Flag for review (don't assume).
- **SBOM currency:** if dependencies changed, is the SBOM / license inventory regenerated so provenance stays accurate?

---

## #29 Decision lifecycle

Scope: decisions reviewed *as they are made* — adoption / build-vs-buy / technology selection; lock-in & exit cost; the decision record (ADR) and whether its assumptions still hold; revisit-triggers; planned retirement / deprecation / sunset. The **decision-time** review shape (see [`../decision-time-review-shape.md`](../decision-time-review-shape.md)): the artifact under review is an ADR / RFC / adoption PR / deprecation plan, not a diff of implementation code.

### Key references

- **Michael Nygard — "Documenting Architecture Decisions" (2011)** — the ADR format (context · decision · status · consequences); status proposed/accepted/superseded.
  → mine: a non-obvious or hard-to-reverse choice needs a recorded *why*, not just the *what*, so the next engineer inherits the reasoning; an accepted-but-unrecorded decision is unowned debt.
- **ThoughtWorks Technology Radar — Adopt / Trial / Assess / Hold rings** — https://www.thoughtworks.com/radar/faq (`verify` ring definitions).
  → mine: a technology's position is a *lifecycle* state, not a one-time yes/no; **Hold** = "don't start anything new with this." Selection should name where the chosen tech sits and where it's heading (rising vs. EOL).
- **Jeff Bezos — one-way vs. two-way door decisions (2015 Amazon shareholder letter)** `(verify)`.
  → mine: match scrutiny to reversibility — two-way doors (cheap to undo) decide fast and light; one-way doors (expensive to reverse) demand a recorded decision and an exit plan.
- **RFC 8594 — The Sunset HTTP Header Field (2019)** — https://www.rfc-editor.org/rfc/rfc8594 ; **RFC 8631** link relations (`deprecation`/`sunset`).
  → mine: deprecation is a *planned, dated* activity — signal end-of-life with a date and a migration path, not a silent removal discovered later as dead code.
- **Build-vs-buy / Total Cost of Ownership frameworks** `(verify)`.
  → mine: the bulk of a dependency's cost is *post-adoption* (integration, maintenance, eventual exit), so "we need it" is not a justification; "we weighed stdlib / a few lines / lib A / build, and chose X because…" is.
- **Vendor lock-in & reversible-exit literature** `(verify)`.
  → mine: exit cost can rival annual spend; the mitigations to check for are a **portability boundary/adapter** and **data exportability** — is the dependency silently load-bearing-and-irreplaceable?
- **Azure Well-Architected Framework — architecture decision records & maintenance** `(verify)`.
  → mine: periodically scan *accepted* ADRs for outdated or contradicted decisions; a stale decision log is worse than none. Decisions should name the assumptions and the conditions that reopen them.
- **Keep a Changelog — `Deprecated` / `Removed` sections** — https://keepachangelog.com/ .
  → mine: deprecation and removal are first-class, announced events with a window, not surprises.

### Tooling rules worth lifting

- **`adr-tools` / Log4brains / MADR templates** — scaffold and index ADRs; make "is there a decision record for this non-obvious choice?" mechanically checkable. `(verify)`.
- **`endoflife.date` (API) / `deps.dev` / OSV `(verify)`** — machine-readable lifecycle & maturity signals for an adopted dependency/runtime (is it approaching EOL?).
- **Dependency-weight inspectors — `npm why` / `cargo tree` / `pipdeptree` / `dependency-review-action`** — surface the transitive weight a new dependency drags in (part of adoption cost; cross #18).
- **API-deprecation encodings — `Deprecation`/`Sunset` response headers (RFC 8594/8631), OpenAPI `deprecated: true`, GraphQL `@deprecated(reason:)`** — put planned retirement into the contract (cross #13).
- **License / portability scanners (FOSSA, Snyk)** — flag proprietary / copyleft surface that raises exit cost and lock-in (cross #27).
- **Renovate/Dependabot with EOL feeds** — flag an adopted technology entering end-of-life so the retire decision is triggered, not missed.

### Reviewable heuristics (skill-checklist seeds)

- **Adoption justification recorded:** for a new dependency / framework / platform, is there a rationale weighed against the cheaper options (stdlib, a few lines, an existing in-house capability, a smaller library)? "We need X" is not a justification; an evaluated A/B/build comparison is.
- **Right-sizing (build-vs-buy):** does the chosen option's weight match the need? A 40-dependency framework for one screen, or a hand-rolled implementation where a maintained library exists, both warrant a second look (cross #11 restraint, #18 deps).
- **Lock-in & exit cost assessed:** is the cost of *leaving* considered — is data exportable, is the integration behind a portable boundary/adapter, or is this a one-way door into proprietary surface that's expensive to reverse?
- **Reversibility matched to scrutiny:** is this a two-way door (cheap to undo → decide fast) or a one-way door (expensive to undo → demand a recorded decision and an exit plan)? Flag heavy process on trivial reversible calls, and casual adoption of irreversible ones.
- **Decision record present & complete:** for a non-obvious choice, is there an ADR capturing context, options considered, decision, and consequences — the *why*, not just the *what*?
- **Assumptions stated and still valid:** does the decision name the assumptions it rests on (load, team size, vendor support, scale)? On revisit, do they still hold — or has a premise expired, making the decision stale debt?
- **Revisit-triggers named:** does the record state the conditions that should reopen it ("revisit if write volume > 10k/s"; "if the vendor drops Kafka")? A decision with no trigger rots silently.
- **Retirement planned on a schedule:** when something is deprecated, is removal *planned and clocked* — a `Deprecation`/`Sunset` header or `deprecated` marker, a sunset date, a consumer-migration path, and a tracked removal ticket — rather than left to surface later as dead code (cross #1, #13)?
- **Vendor adopt/exit symmetry:** does adopting a managed service / SaaS / model API record how we'd migrate off (second source, abstraction seam), so it isn't silently irreplaceable?
- **Escalate the governance slice:** build-vs-buy *TCO*, procurement, and contract terms are business calls — surface them with evidence and **escalate to humans**; detect and flag, don't adjudicate (cross #27, the G8 boundary).

---

## Open threads   (gaps / mis-placements / sub-topics worth deeper research)

- **Citation status (was a gap):** the standards spines and high-traffic tool IDs are now **web-verified (2026-06-09)** — WCAG 2.2 SCs (2.4.11, 2.5.8, 1.4.3), axe-core / jsx-a11y rule ids, Conventional Commits + commitlint, the SmartBear/Cisco review-size numbers, Diátaxis, ADR, Keep a Changelog, SPDX/AGPL, REUSE, EAA (2025-06-28), GDPR. Residual `(verify)`: some SonarQube squids and formatjs/i18next/html-validate plugin rule names — confirm at skill-build time.
- **#21 ↔ #15/#6 overlap.** Cyclomatic/cognitive complexity and god-modules appear here (as change-amplification proxies), in #6 (local readability), and #12 (architecture). The *maintainability* lens is specifically VCS-aware (churn × complexity, change-coupling, bus factor) — worth carving out as the distinguishing behavior so it doesn't collapse into generic complexity linting.
- **#22 ↔ #7 boundary.** "Comment rot" lives in #7 (comments) but doc-drift detection (docstring-vs-signature, example rot) is here. Suggest: #7 = in-code why-not-what; #22 = external/structured docs + ADR/changelog/runbook. Tools like `darglint`/`eslint-plugin-jsdoc` straddle both.
- **i18n money/units genuinely double-booked (#23 ↔ #4).** The *formatting* facet (Intl/CLDR, locale-aware output) is here; the *arithmetic correctness* facet (precision, overflow, currency math) is #4. The taxonomy already cross-links this; a single skill may need to own both ends to avoid a seam.
- **AI-generated-code provenance (#27) ↔ #25.** Provenance/attribution/licensing of AI output sits in #27; prompt-injection and output-validation sit in #25. A reviewer checking an AI-authored PR needs both lenses at once — candidate for a combined "AI-contribution review" behavior.
- **Privacy/telemetry is triple-booked** (#27 regulatory, #16 observability/logging-no-PII, #14 PII handling). The taxonomy's own residual-candidates note flags this. For the skill suite, recommend one PII-data-flow check that all three reference rather than three partial ones.
- **Agent-native parity (#24)** is a project-specific principle with thin external prior art (mainly the in-repo `agent-native-reviewer`). Worth deeper sourcing or treating as a house rule rather than an industry-standard heuristic. **Update (2026-06-12): partially sourced** — AGENTS.md (OpenAI 2025-08, stewarded by the Linux Foundation's Agentic AI Foundation since 2025-12) gives the *agent-facing docs* half industry-standard grounding (now filed in #22 + #24). The parity principle itself ("any user action is agent-reachable") remains a house stance, but the direction of the ecosystem supports it.
- **"Definition of done" and SLO/error-budget framing** straddle process (#24) and observability (#16); the taxonomy notes this. Decide whether DoD is a checklist owned by #24 that *includes* observability gates, or a cross-cutting meta-check.
- **Legal calls exceed an agent's authority.** Several #27 heuristics (copyleft linkage, export control, data-residency legality) should *flag for human/legal review* rather than assert a verdict — the skill design should encode that escalation, not pretend to adjudicate.
