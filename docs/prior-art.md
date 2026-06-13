# Prior Art

Existing skills, plugins, linters, and review tools that already cover parts of [the map](taxonomy.md). We mine these for **heuristics, checklists, and behaviors** — we do not inherit their boundaries.

Two kinds of prior art:

1. **Agent skills / plugins** — closest in form to what we're building; study how they scope, trigger, and report.
2. **Static-analysis & review tooling** — decades of encoded heuristics; a goldmine of concrete checks per category.

---

## Agent skills & plugins (observed in this environment)

Mapped to taxonomy categories. "Author's own" = present under `~/.claude/skills` / `~/.agents/skills`. "Plugin" = installed marketplace plugins (e.g. `pr-review-toolkit`, `compound-engineering`, `code-review`).

| Category | Prior-art skill/plugin | Notes to mine |
|---|---|---|
| 2 Error handling | `safeguarding`, `zero-bugs` (own); `silent-failure-hunter` (plugin) | Silent-failure hunting is a sharp, self-contained behavior — good model for a focused skill. |
| 3 Concurrency | `julik-frontend-races-reviewer` (plugin) | Frontend timing/DOM-lifecycle races as a dedicated lens. |
| 5 Naming | `naming-as-process` (own) | Progressive naming stages; already first-principles. |
| 6 Local readability | `core-refactorings`, `read-by-refactoring` (own); `code-simplifier` (plugin) | Refactoring-as-comprehension. |
| 7 Comments | `comment-analyzer` (plugin) | Comment accuracy / rot detection. |
| 8 Consistency & idiom | `dhh-rails-reviewer`, `kieran-rails/typescript/python-reviewer`, `pattern-recognition-specialist` (plugins) | Opinionated, idiom-specific reviewers — a pattern worth replicating per-ecosystem. |
| 10 Type & data modeling | `type-design-analyzer` (plugin) | Encapsulation/invariant ratings; quantitative scoring approach. |
| 11 Abstraction & simplicity | `dependency-elimination`, `core-refactorings` (own); `code-simplicity-reviewer` (plugin) | Removal-over-addition; YAGNI enforcement. |
| 12 System architecture | `architecture-strategist` (plugin) | Pattern compliance, structural integrity. |
| 14 Security | `security-sentinel` (plugin); `security-review` (built-in command) | OWASP coverage; auth/secrets. |
| 15 Performance | `performance-oracle` (plugin) | Complexity, queries, memory, scalability. |
| 17 Test quality | `microtesting`, `testing-principles`, `test-driven-development` (own); `pr-test-analyzer` (plugin) | Coverage *quality* vs. quantity. |
| 19 Build/CI & tooling | `lint` (plugin) | Pre-push lint/quality gate orchestration. |
| 20 Data & persistence | `data-integrity-guardian`, `data-migration-expert`, `schema-drift-detector`, `deployment-verification-agent` (plugins) | Migration safety is unusually well-covered — strong checklists to borrow. |
| 22 Documentation | `superdocs`, `agentsmd-generator` (own) | Generating durable context docs. |
| 23 Accessibility & i18n | `wcag-audit-patterns` (own); `design-implementation-reviewer` (plugin) | WCAG audit patterns; design-fidelity comparison. |
| 24 Process & collaboration | `commit-notation` (own); `agent-native-reviewer` (plugin) | Risk signaling; agent-native parity check. |

**Meta-skills worth studying for *how* to build the suite** (not category coverage, but craft): `skill-builder`, `skill-creator`, `designing-workflow-skills`, `writing-skills`, plus the multi-agent review orchestrators (`pr-review-toolkit:review-pr`, `compound-engineering:workflows:review`, `code-review`).

### Coverage read

~13 of 24 categories have *some* agent-skill prior art. The notably **thin / uncovered**: #1 functional correctness, #4 resource & state, #13 API/contract design, #16 observability, #18 dependencies/supply-chain, #21 maintainability-as-a-whole, plus all the candidate additions (esp. AI/LLM-specific quality). These are the greenfield zones.

---

## Static analysis & review tooling (heuristic goldmine)

Each encodes hundreds of concrete checks. To be expanded with *specific rules worth lifting*.

- **General/multi-language:** SonarQube/SonarLint, Semgrep, CodeClimate, PMD, Codacy, DeepSource, Qodana.
- **JS/TS:** ESLint (+ typescript-eslint), Biome, `eslint-plugin-security`, `eslint-plugin-jsx-a11y`.
- **Python:** Ruff, Pylint, mypy/pyright, Bandit (security), Vulture (dead code).
- **Ruby:** RuboCop, Reek (smells), Brakeman (security), Bullet (N+1).
- **Go:** `go vet`, staticcheck, golangci-lint.
- **Security-specific:** CodeQL, Snyk, Trivy, Gitleaks/TruffleHog (secrets), Dependabot/Renovate (deps).
- **Complexity/metrics:** Lizard, radon, SciTools Understand; connascence/coupling analyzers.
- **Accessibility:** axe-core, Pa11y, Lighthouse.
- **Architecture:** dependency-cruiser, ArchUnit, import-linter.

> **TODO:** for each tool, extract the *rule categories* that map cleanly onto a taxonomy category — those are pre-validated, real-world heuristics. The point isn't to wrap the tools, but to learn what experienced teams decided was worth flagging.

---

## What to actually learn from prior art

1. **Behaviors that work as self-contained skills** — e.g. silent-failure hunting, N+1 detection, secret scanning, migration-safety review. These have crisp triggers and outputs.
2. **The opinionated-reviewer pattern** — `dhh-rails`, `kieran-*` show value in a *named perspective* with strong taste, not just a checklist.
3. **Quantitative scoring** — `type-design-analyzer` rates dimensions; consider whether the suite reports scores or only findings.
4. **Orchestration** — how multi-agent review toolkits fan out and synthesize; relevant to phase 2 composition.
