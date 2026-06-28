# Research — Cluster V: The system around the code (Verification & Supply)

> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Generated 2026-06-09 via web research from the main loop. Citations verified except where marked `(verify)`. Mirrors the section structure of [cluster-1-correctness.md](cluster-1-correctness.md).

---

## #17 Test quality & coverage

### Key references

- **Mike Cohn — *Succeeding with Agile* (the Test Pyramid)** → mine: more fast unit tests, fewer slow e2e; the cost/speed/stability gradient by test level.
- **Kent C. Dodds — "The Testing Trophy" (2018)**, building on **Guillermo Rauch — "Write tests. Not too many. Mostly integration."** → mine: integration tests give the best ROI — they test units collaborating without e2e fragility. The modern counter to a unit-heavy pyramid; use it to resist *both* over-mocked unit tests and over-heavy e2e.
- **Michael Feathers — *Working Effectively with Legacy Code*** → mine: "legacy code is code without tests"; seams, characterization tests, and **testability as a design property** (if it's hard to test, the design is the problem).
- **Claessen & Hughes — "QuickCheck: Lightweight Tools for Random Testing of Haskell Programs" (ICFP 2000)** → mine: **property-based testing** — assert invariants over generated inputs; the trio of *generators + properties + shrinking*. Ported as Hypothesis/fast-check/jqwik.
- **Mutation testing (PIT, Stryker, mutmut, cargo-mutants)** → mine: a **coverage-quality** signal — does the suite actually *catch injected bugs*? High line coverage + low mutation score = weak assertions. Cheapest and highest-signal on **pure, deterministic, fast-to-test** units (no I/O), where a run is minutes and surviving mutants are an exact list of unasserted behavior — there, prefer running the tool over only intuiting it.
- **"Test behavior, not implementation" (Dodds; Kent Beck)** → mine: tests coupled to internals break on refactor; assert observable behavior so tests survive refactoring (cross #21).
- **Martin Fowler — "Eradicating Non-Determinism in Tests"** `(verify URL)` → mine: flaky tests destroy trust; quarantine, then fix the root cause (time, order, concurrency, shared state).
- **Kent Beck — "Test Desiderata" (2019)** — https://kentbeck.github.io/TestDesiderata/ → mine: twelve properties a good test balances — isolated, composable, deterministic, fast, writable, readable, **behavioral**, **structure-insensitive**, automated, **specific**, predictive, inspiring. The *behavioral + structure-insensitive* pair is the canonical name for the behavior-vs-implementation axis (cross over-mocking); the under-surfaced ones are *specific* (a failure localizes its cause), *writable* (cheap to write), and *predictive* (green ⇒ prod works). Beck frames the twelve as sliders to trade off, not maxima — don't demand all twelve of every test.
- **Dave Farley — "Properties of Good Tests" (*Modern Software Engineering*, 2021)** — https://www.davefarley.net/ → mine: a good test is **Understandable** (asserts behaviour, not implementation), **Maintainable**, **Repeatable** (deterministic), **Atomic** (one reason to fail), **Necessary** (no redundant/tautological tests), **Granular**, and **Fast** — *seven* properties, not the "eight" some third-party summaries cite (the 8th, "test-first", is not in Farley's own list). *Atomic* and *Necessary* are the crisp net-new additions over Beck.
- **Hunt, Thomas & Langr — *Pragmatic Unit Testing*** → mine: the actionable mnemonic family. **Right-BICEP** = what to test (Right results, Boundary conditions, Inverse relationships, Cross-check against an independent oracle, Error conditions, Performance). **CORRECT** = boundary-condition enumeration (Conformance, Ordering, Range, Reference, Existence, Cardinality, Time) — the sharpest checklist for *which* edges. **FIRST** (Fast, Isolated, Repeatable, Self-validating, Timely — coined by Ottinger & Schuchert, popularized in *Clean Code* ch. 9) and **A-TRIP** overlap our isolation/determinism checks.
- **Gerard Meszaros — *xUnit Test Patterns* (2007)** + **van Deursen, Moonen, van den Bergh & Kok — "Refactoring Test Code" (XP2001)** + **tsDetect (Peruma et al., FSE 2020)** — http://xunitpatterns.com/Test%20Smells.html → mine: the named **test-smell** catalog that turns "this test smells" into specific, often mechanically-detectable findings — **Assertion Roulette** (many unexplained asserts; a failure doesn't localize), **Mystery Guest** (depends on a hidden external file/DB/fixture — not self-contained), **Eager Test** (one test exercises many behaviors), **Conditional Test Logic** (branches/loops in the test hide what runs), **Sensitive Equality** (asserts on a whole toString/serialized form — brittle), **Sleepy Test** (real-time `sleep` — flaky), **Resource Optimism** (assumes an external resource is present). tsDetect's 19 rules show most are lintable (cross tool-rules).
- **Martin Fowler — "Mocks Aren't Stubs"** — https://martinfowler.com/articles/mocksArentStubs.html → mine: the five **test-double** kinds (dummy, fake, stub, spy, mock) and *classicist vs mockist* / *sociable vs solitary* testing. Reach for the least-powerful double — a stub or fake — and reserve a behavior-verifying **mock** for genuine outgoing commands; mocking queries or value objects is the over-mocking that couples tests to implementation (cross #11).

### Tooling rules worth lifting

- **Coverage:** coverage.py (Python), Istanbul/nyc & V8 (JS), JaCoCo (Java), SimpleCov (Ruby), `go test -cover`, **cargo-llvm-cov / cargo-tarpaulin** (Rust). Lift: track **branch** coverage and the coverage **delta on the diff**, not a global %.
- **Mutation:** PIT/pitest (Java), **Stryker** (JS/TS, C#, Scala — https://stryker-mutator.io/), mutmut & cosmic-ray (Python), Mutant (Ruby), **cargo-mutants** (Rust — https://mutants.rs/), gremlins (Go — https://gremlins.dev/). For a pure crate/module with fast deterministic tests, a mutation run is cheap, and the surviving-mutant list makes a good CI gate.
- **Property-based:** Hypothesis (Python), fast-check (JS/TS), jqwik (Java), **proptest / quickcheck** (Rust), PropEr/QuickCheck.
- **Flaky control:** `pytest-randomly` (random order), `pytest-rerunfailures`, Jest `--detectOpenHandles`, Gradle/Maven retry, flaky trackers (BuildPulse, Datadog Test Optimization).
- **Test linters:** `eslint-plugin-jest` (`no-disabled-tests`, `no-focused-tests`, `expect-expect`, `no-conditional-expect`), `rubocop-rspec`, `flake8-pytest-style`.

### Reviewable heuristics (skill-checklist seeds)

- Do new/changed tests assert **observable behavior** (inputs→outputs, side effects), not internal calls/private state (refactor-resistant)?
- Is coverage **meaningful** on the new code — branches and edge cases, not just lines executed? Don't chase a % with assertion-free or **tautological** tests (asserting the mock, restating the framework, or a **Sensitive Equality** check on a whole serialized blob that breaks on unrelated change), and don't keep tests that pin no real requirement (Farley *necessary*).
- Bug fix → is there a **regression test** that fails before the fix and passes after?
- Are tests **isolated and deterministic** — no shared mutable state, order dependence, or real clock/network/unseeded random (flaky risk)?
- Is the test at the **right level** (pyramid/trophy) — logic in fast unit/integration, e2e reserved for critical journeys?
- **Over-mocking smell**: do mocks assert on implementation calls so a refactor breaks tests without behavior changing? Reach for the least-powerful **test double** — prefer a real collaborator, fake, or stub, and reserve a behavior-verifying mock for true outgoing commands (don't mock queries or value objects) (cross #11).
- Are **edge/boundary** cases covered (empty, null, max, error paths) — where the bugs live? Walk the **CORRECT** dimensions (Conformance, Ordering, Range, Reference, Existence, Cardinality, Time) to surface the missing edge (cross #1).
- Would the suite **catch a real bug**, not just execute lines? Apply mutation intuition — for a pure, deterministic, fast-to-test unit, prefer actually running a mutation tool (cheap, high-signal) over eyeballing it; otherwise high coverage masks weak assertions.
- Any disabled/focused/skipped tests (`.only`, `xit`, `@Disabled`) sneaking in?
- For nondeterministic/concurrent code, is the invariant property-tested and the concurrent path exercised (cross #3)?
- Is each test readable — clear arrange/act/assert, one behavior per test, name reads as a spec?
- ★ Does each test have a **single reason to fail** — assertions that localize the cause when it breaks? Flag **Assertion Roulette** (a pile of asserts with no messages, so a failure doesn't say which expectation broke) and tests that bundle several unrelated behaviors (Beck *specific*; Farley *atomic*).
- Is the test **self-contained**, or a **Mystery Guest** — does it lean on a hidden external resource (file, DB, network) or a fixture defined far from the test, obscuring what's exercised and risking nondeterminism (cross isolation)?
- Is the test **DAMP** (readable at a glance) rather than over-DRY'd — does **Conditional Test Logic** (branches/loops in the test) or deep helper/fixture indirection hide what actually runs? In tests, readability beats deduplication (Beck *writable*).
- Beyond the happy path, does the suite use **inverse/round-trip** checks (encode→decode), a **cross-check** against an independent oracle, and **forced error conditions** (Right-BICEP) — not a single positive assertion?

---

## #18 Dependencies & supply chain

### Key references

- **SLSA — Supply-chain Levels for Software Artifacts (OpenSSF)** — https://slsa.dev/ → mine: a build-integrity ladder (v1.0 Build L1–L3: provenance → signed/hosted → isolated/non-forgeable). Can you *prove* the artifact came from this source via this build?
- **OpenSSF Scorecard** — https://securityscorecards.dev/ `(verify URL)` → mine: 18+ automated checks of a dependency's security hygiene (branch protection, code review, maintained, pinned deps, fuzzing) — a vetting rubric for "should we depend on this?"
- **SBOM — SPDX & CycloneDX (OWASP)** — https://cyclonedx.org/ → mine: the component inventory (packages, versions, licenses, relationships); the basis for both vuln scanning and license review (cross #27).
- **OSV.dev / OSV-Scanner (Google), pip-audit, npm audit, govulncheck, OWASP Dependency-Check, Trivy, Grype, Snyk** → mine: known-CVE detection across declared *and transitive* deps.
- **Russ Cox — "Our Software Dependency Problem" (2019)** — https://research.swtch.com/deps `(verify URL)` → mine: a discipline for *evaluating* a dependency before adding it (cost, maintenance, transitive weight, security surface).
- **left-pad / event-stream / xz-utils (CVE-2024-3094)** → mine: the canonical cautionary tales — trivial dep removal breakage, account-takeover injection, a backdoor planted by a "maintainer."

### Tooling rules worth lifting

- **Dependabot** (GitHub, ~14 ecosystems) / **Renovate** (Mend, 30+ managers, groups PRs) — automated update PRs.
- **OSV-Scanner, pip-audit, npm audit, cargo-audit, govulncheck, bundler-audit, Trivy, Grype, Snyk** — CVE scanning.
- **Socket.dev** — *behavioral* supply-chain analysis (new install scripts, network/filesystem access) to catch malicious packages, not just known CVEs.
- **Lockfiles** (`package-lock.json`, `poetry.lock`, `Gemfile.lock`, `go.sum`) + `npm ci`/equivalent — reproducible, hash-pinned installs.
- **depcheck / knip / deptry** — unused & missing dependency detection.
- **license scanners** (license-checker, FOSSA, Trivy) — feed #27.

### Reviewable heuristics (skill-checklist seeds)

- Is the new dependency **necessary**, or could stdlib/a few lines do it (avoid trivial deps and transitive bloat)?
- Is it **healthy**: recently maintained, broadly used, reasonable Scorecard, not single-maintainer abandonware?
- Any **known CVEs** in it or its transitive tree (run the scanner)? Is the version **pinned via lockfile** and honored in CI (`npm ci`)?
- Does it pull in a large transitive subtree or **duplicate** an existing dependency's capability?
- License **compatible** with the project (cross #27)?
- Does the install run scripts or request network/filesystem access it shouldn't (malicious-package surface)?
- Are updates **automated** (Dependabot/Renovate) with the lockfile committed and enforced?
- Version bump → are breaking changes reviewed (changelog), especially across a major version?
- **Vendor lock-in**: does this couple us to a proprietary API where a standard/portable option exists?

---

## #19 Build, CI/CD & tooling

### Key references

- **Jez Humble & David Farley — *Continuous Delivery*** → mine: the deployment pipeline; **build once, promote the same artifact**; keep the build green; automate everything.
- **Forsgren, Humble, Kim — *Accelerate* / DORA** → mine: the **four key metrics** (deployment frequency, lead time for changes, change-failure rate, time-to-restore) — the outcomes CI/CD quality should move; speed and stability are *not* a trade-off.
- **Trunk-Based Development** — https://trunkbaseddevelopment.com/ → mine: short-lived branches, integrate continuously, hide incomplete work behind feature flags (cross #26).
- **Bazel / hermetic & reproducible builds** → mine: declared inputs only, sandboxed actions, content-addressed caching → identical inputs produce identical outputs; kills "works on my machine."
- **Martin Fowler — "Continuous Integration"** → mine: a slow or flaky CI is itself a quality defect; keep it fast and green, quarantine flakies.

### Tooling rules worth lifting

- **pre-commit** (multi-language hooks), **husky + lint-staged** (JS), **lefthook** — run lint/format/type-check before commit.
- **CI** (GitHub Actions/GitLab CI/Buildkite) — required status checks + branch protection as the merge gate.
- **Build** — Bazel/Buck (hermetic), Nix (reproducible envs), Docker multi-stage.
- **Gate the diff** with the project's linters + formatter (Prettier/Black/gofmt) + type-checker (tsc/mypy) — cross #8.
- **Deploy safety** — canary / blue-green / progressive delivery (Argo Rollouts, Flagger) + automated rollback.
- **hadolint** (Dockerfile) — `DL3006` always tag the image version explicitly, `DL3007` don't use `:latest`, `DL3008` pin versions in `apt-get install` (`DL3013` pip / `DL3016` npm / `DL3018` apk), `DL3002` last `USER` should not be root, `DL3004` no `sudo`, `DL3009` delete apt lists after installing. *(IDs verified against hadolint/hadolint README.)*
- **Checkov** (IaC scanner: Terraform/OpenTofu, CloudFormation, Kubernetes, Helm, Kustomize, Dockerfile, ARM/Bicep, Serverless, OpenAPI) — policy IDs like `CKV_AWS_20` (S3 ACL allows public READ) / `CKV_AWS_57` (public WRITE), with a published policy index mapping to CIS et al.; suppressions are inline and *reasoned* (`#checkov:skip=ID:why`).
- **tflint** — pluggable Terraform linter: provider-specific mistakes (invalid instance types), deprecated syntax, unused declarations; SARIF/JSON output for CI.
- **kube-linter** — `run-as-non-root`, `no-read-only-root-fs`, `privileged-container`, `privilege-escalation-container`, `unset-cpu-requirements` / `unset-memory-requirements`, `latest-tag`, `default-service-account`, `host-network`, `docker-sock`. *(check names verified against stackrox/kube-linter generated docs.)*
- **actionlint** — GitHub Actions workflow linter: expression type-checks, runner-label validation, plus a shellcheck integration over `run:` scripts.
- **zizmor** — GitHub Actions *security* audits (~two dozen rules): template injection (`${{ }}` of attacker-influenced context interpolated into `run:`), actions pinned to mutable tags instead of commit SHAs, excessive workflow token permissions, use of actions with known advisories.

### Reviewable heuristics (skill-checklist seeds)

- Does CI run the full gate on the diff — lint, format-check, type-check, tests, dep/security scan — and is passing **required** to merge?
- Beyond that required floor, are the **deterministic quality signals** this stack benefits from actually present — **coverage reporting** (with a branch/diff threshold, not a vanity global %), a **performance benchmark** on the hot paths, and **complexity/maintainability scoring**? Their absence is a **preference-tunable advisory** (`route: implementer`), not a floor-tier block: surface "no coverage gate / no perf benchmark / no complexity budget" as a gap worth wiring up, and let a repo that deliberately skips it suppress the note (cross #17, #21).
- Is the build **reproducible/hermetic** enough to not depend on machine-local state (pinned toolchain, lockfiles, no network in build)?
- Is CI **fast and reliable**? A new slow/flaky job is a defect — parallelized, cached, deterministic?
- Is any **quality gate disabled or soft-failed** (`continue-on-error`, `|| true`, `allow_failure`, a skipped/excluded check) — a deliberate, tracked decision or silent debt? A gate that's off because its tool broke on the current toolchain (language/runtime version, build) is a **gap to close**: fix it or swap in a maintained equivalent — often a younger, less well-known one — not a permanent `continue-on-error` (cross #21).
- Are **secrets** injected at runtime (not baked into the image/repo/CI logs) and least-privilege scoped (cross #14)?
- Risky change → is there a safe rollout (canary/flag) and a **tested rollback** path (cross #16, #20)?
- Is incomplete work integrated **behind a flag** (trunk-based), not a long-lived branch?
- Does the pipeline **build once and promote** the same artifact, not rebuild per environment?
- Are pre-commit/pre-push hooks present so obvious issues never reach CI?
- **IaC is code:** does infrastructure/config-as-code in the diff (Terraform, K8s manifests, Helm, Dockerfiles, CI workflows) pass the same gate as app code — linted (checkov/tflint/kube-linter/hadolint), reviewed, and `plan`ned in CI before apply?
- **Workflow injection:** does any `${{ }}` expression interpolate attacker-influenceable context (issue/PR titles and bodies, branch names, commit messages) directly into a `run:` script? Pass it through an env var instead — the template is expanded *before* the shell parses (template injection).
- **Action/workflow supply chain:** are third-party actions pinned to full commit SHAs (not mutable tags), and are workflow token `permissions:` explicitly declared and least-privilege (cross #18, #14)?
- **Container hygiene in the diff:** image versions pinned (no `:latest`), a non-root final `USER`, CPU/memory requests+limits set, read-only root filesystem where workable, no `privileged: true` or host namespace/docker-socket mounts without a documented reason.
- **Cloud misconfig in the diff:** does a new/changed IaC resource open public access (`0.0.0.0/0` ingress, public bucket ACL), disable encryption, or grant wildcard IAM? Deliberate-and-documented or a finding (security verdict owned by #14).

---

## #20 Data & persistence safety

### Key references

- **Martin Fowler — "Parallel Change" (expand/contract)** → mine: never do a breaking schema change in one step — **expand** (add new alongside old) → **migrate** (dual-write + batched backfill) → **contract** (drop old once drained). Each phase independently deployable and reversible.
- **Online schema-change tools — gh-ost (GitHub, binlog-based, *triggerless*), pt-online-schema-change (Percona, trigger + shadow table), pgroll (Postgres)** → mine: large-table `ALTER`s take blocking metadata locks; these copy rows in batches and keep the copy in sync for near-zero downtime.
- **ankane/strong_migrations** — https://github.com/ankane/strong_migrations → mine: the best single **catalog of unsafe migration operations and their safe rewrites** (the rename-column 6-step: add column → write both → backfill → move reads → stop writing old → drop). Lift these directly as checklist items.
- **Martin Kleppmann — *Designing Data-Intensive Applications*** → mine: ACID, isolation levels, and constraints as the last line of defense for integrity.
- **Batched-backfill discipline** → mine: backfill in small batches (1k–10k rows) with a sleep to avoid lock/IO saturation; make it **idempotent and resumable**.

### Tooling rules worth lifting

- **strong_migrations** (Rails), **online-migrations** gem, **Django migration checks**, **squawk** (Postgres migration linter) — flag unsafe DDL pre-merge.
- **gh-ost, pt-osc, pgroll, Vitess online DDL** — zero-downtime schema change execution.
- **DB constraints** (NOT NULL, FK, UNIQUE, CHECK) + **transactional DDL** (Postgres) — DB-enforced invariants.
- **`CREATE INDEX CONCURRENTLY`**, add-nullable-then-backfill, `NOT VALID` + `VALIDATE CONSTRAINT` — the safe Postgres idioms.
- **Schema-drift detection** (cross prior-art `schema-drift-detector`); migration dry-run/plan.

### Reviewable heuristics (skill-checklist seeds)

- Is the schema change **backward-compatible** with the currently-running app version (rolling deploy)? If breaking, is it split expand→migrate→contract?
- Does adding a NOT NULL column / index / FK **lock the table** (esp. large tables)? Use safe variants (`CREATE INDEX CONCURRENTLY`; add nullable then backfill; `NOT VALID` then validate).
- Is a data **backfill batched, throttled, idempotent, and resumable** — not one giant `UPDATE`?
- During the transition, does the app **dual-write/dual-read** so neither old nor new code breaks?
- Are migrations **reversible** — or is the irreversibility deliberate and documented?
- Are **integrity constraints** (FK, UNIQUE, CHECK, NOT NULL) used so the DB enforces invariants, not just app code (cross #10)?
- Are **transaction boundaries** correct — multi-step writes atomic, no partial commit on failure (cross #2)?
- Is **destructive DDL** (DROP column/table) gated until the new path is verified live and old code drained?
- Is there a **tested backup/restore** path before a risky data change?

---

## #26 Configuration & environment

### Key references

- **The Twelve-Factor App — Config (factor III)** — https://12factor.net/config → mine: strict separation of config from code; store config in **env vars**; never commit config/secrets. Also factor X (dev/prod parity), XI (logs to stdout — cross #16).
- **Pete Hodgson — "Feature Toggles (aka Feature Flags)" (martinfowler.com)** — https://martinfowler.com/articles/feature-toggles.html → mine: toggle **categories** (release, ops, experiment, permission), decoupling deploy from release, and the crucial point that **flags have a lifecycle** — release flags are temporary and must be removed to avoid debt (cross #21).
- **HashiCorp Vault / secrets management** → mine: secrets out of config files; prefer dynamic, leased, rotated secrets.
- **Config validation at startup / "fail fast"** → mine: validate all config at boot (clear error on missing/invalid), don't discover misconfig at 3am on first use.

### Tooling rules worth lifting

- **Config schema/validation:** envalid, zod env parsing, **Pydantic Settings**, viper, Spring `@ConfigurationProperties` validation, dotenv-linter.
- **Secret scanning:** Gitleaks, TruffleHog, detect-secrets (cross #14).
- **Feature-flag platforms:** LaunchDarkly, **Unleash**, Flagsmith, **OpenFeature** (vendor-neutral standard) — incl. stale-flag detection / flag-cleanup.
- **Portability/env:** ShellCheck (portable shell), `.editorconfig`; pinned container base images for parity.

### Reviewable heuristics (skill-checklist seeds)

- Is config **separated from code** and injected via env — no secrets or env-specific values hardcoded/committed?
- Is config **validated at startup** (fail fast, clear message), not lazily at first use?
- Are **safe, secure defaults** used (deny-by-default, TLS on, debug off in prod — cross #14)?
- **Dev/prod parity**: does the change keep environments close (same backing services, same config shape), avoiding env-specific code branches?
- New **feature flag**: does it have an owner and a **removal plan**? Are stale/dead flags being cleaned up (debt — cross #21)?
- ★ **Portability**: any hardcoded paths, OS/arch assumptions, locale/encoding/timezone assumptions, or non-portable shell?
- Are **secrets** sourced from a manager/env (never repo or logs) and rotatable?
- Is configuration **documented** (each var's purpose, required vs optional, default)?

---

## #30 Enforcement apparatus & meta-artifacts

Scope: the machinery wrapped around the code, reviewed as its own surface (the G10 framing gap — a missing category yields a *silent* hole, not a thin heuristic). Three meta-artifacts: **suppression hygiene** (the act of opting out of enforcement — `# noqa` / `eslint-disable` / `# type: ignore` accretion, lint-baseline growth); **monitoring-config as artifact** (alert rules, dashboards, SLO definitions as reviewed code, not the instrumentation #16 emits); **codegen ↔ source drift** (checked-in generated output stale vs. its generator/spec). Repo-shaped (map-gaps G7): accretion and drift are *standing* conditions across the tree, better scanned on a schedule than in a single diff.

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

### Tooling rules worth lifting

- **ESLint** — `--report-unused-disable-directives` (CI flag); `eslint-comments/no-unlimited-disable`, `/no-unused-disable`, `/require-description`, `/no-aggregating-enable`.
- **Ruff `RUF100`**, **flake8-noqa**, **pygrep-hooks** `python-check-blanket-noqa` (PGH004) + `python-check-blanket-type-ignore` (PGH003) — ban blanket suppressions in pre-commit.
- **mypy** `warn_unused_ignores`, **pyright** `reportUnnecessaryTypeIgnoreComment` — sweep dead ignores; **TypeScript** `@ts-expect-error` (errors if unused) over `@ts-ignore`.
- **Baseline trackers** — detekt `baseline`, Android `lint-baseline.xml`, ESLint bulk-suppressions, `betterer` — and a CI check that the baseline count is **non-increasing**.
- **`pint` / `promtool check rules`** — alert-rule linters (missing `for:`/labels/runbook, broken PromQL); **grafana/dashboard linters**; **`terraform validate`/`plan`** for monitors-as-code drift.
- **Codegen drift gate** — `make generate && git diff --exit-code` (or `go generate`, `buf generate`, `sqlc diff`) as a required CI job; `linguist-generated`/`.gitattributes` to mark and exclude generated files from review noise.

### Reviewable heuristics (skill-checklist seeds)

- **Blanket suppressions:** any file-wide or unscoped `/* eslint-disable */`, bare `# noqa`, bare `# type: ignore`, or `@ts-ignore` that disables *all* checks rather than a named rule? Flag to scope to the specific rule and justify — a blanket disable hides unrelated future violations at that location.
- **Unjustified suppressions:** does each suppression carry a reason (and ideally an issue link or expiry)? `# noqa: E501  # long external URL` is reviewable; a bare suppression with no rationale is undocumented debt.
- **Unused / stale suppressions:** are there suppressions for problems that no longer exist (ESLint unused-disable, Ruff `RUF100`, mypy `warn_unused_ignores`)? They mask the *next* real violation at that spot — remove them.
- **Baseline accretion:** is the lint/type baseline (detekt, lint-baseline.xml, bulk-suppressions) *growing* over time rather than shrinking? A ratchet must only tighten; a growing baseline is silent debt — track the count as a trend, not a point-in-time pass.
- **Alert actionability:** does every alert rule describe a user-visible **symptom** and link a runbook, or are there cause-based / noisy / unactionable alerts that train responders to ignore the pager? Alert on SLO burn, not raw resource gauges.
- **Monitoring drift & as-code parity:** are dashboards/monitors referencing metrics that were renamed or removed (dead panels giving false confidence)? Is monitoring defined **as code** (versioned, reviewable, restorable) rather than click-ops that silently drift?
- **Codegen freshness:** for checked-in generated/compiled artifacts (protobuf, OpenAPI clients, sqlc, ORM models, bundled assets), does CI regenerate and `git diff --exit-code` to prove they match their source — or can they silently drift from the generator/spec?
- **Generated-file provenance:** are generated files marked as generated (header / `linguist-generated`) and kept out of hand-editing, so the next regeneration doesn't clobber a manual patch?
- **Suppression density hotspots:** which files concentrate suppressions? A file full of disables is either genuinely hard (flag for refactor) or a place where enforcement is theater — name it.
- **Alert-rule sanity:** do rules have a `for:` duration, severity/labels, and thresholds tied to an SLO rather than arbitrary numbers? Run a rule linter (`pint` / `promtool`) over them as part of the audit.

---

## #31 Infrastructure-as-code

Scope: IaC manifests — Terraform / OpenTofu, Kubernetes / Helm, CloudFormation, Pulumi — reviewed **as code that provisions production**, where a one-line diff can open a security hole or destroy data far beyond what the same-size application diff could. Four facets: **change blast-radius** (what does `plan` say this actually creates/replaces/destroys); **over-broad access** (public exposure, wildcard IAM — cross #14 least-privilege, which owns the security *verdict*); **drift** between declared config and live infra; **module/provider hygiene** (pinned versions, no secrets in state/vars, sane defaults). Distinct from **#19** (the build/CI *pipeline* and generic workflow mechanics, which owns Dockerfile/workflow linting) and **#26** (application *config keys*). Mature scanners exist (Checkov, Trivy, kube-linter) — the lens **orchestrates and judges blast-radius and intent**, it does not re-implement the rule engines. Repo-shaped (map-gaps G7): exposure and drift are *standing* conditions across all manifests, better scanned on a schedule (and in any IaC PR) than discovered one diff at a time.

### Key references

- **Checkov (Palo Alto Networks / Prisma Cloud, formerly Bridgecrew)** — https://github.com/bridgecrewio/checkov . The most widely-adopted open-source IaC scanner; 1,000+ built-in policies across Terraform/CloudFormation/K8s/Helm/ARM, **graph-based cross-resource checks** (e.g. a security group wired to a public subnet), and custom policies in Python or YAML. Standalone CLI is free.
  → mine: the default first scanner for Terraform/CloudFormation/K8s; its graph checks catch relationships a single-resource linter misses. Soft-failed or `--skip-check`'d en masse, it is theater (cross #30 suppression hygiene).
- **Trivy (Aqua Security) — IaC/misconfiguration scanning; tfsec is folded in** — https://github.com/aquasecurity/trivy . Aqua merged **tfsec into Trivy** (announced 2023, completed 2024); tfsec still runs but gets **no new checks**, and its `AVD-AWS-xxxx` IDs map unchanged into Trivy. For new work, use Trivy `config`/`misconfig`, not tfsec.
  → mine: if a repo still calls `tfsec`, that is a **stale-tool finding** — migrate to Trivy so post-2024 Terraform features are covered. One scanner (Trivy) covers IaC misconfig **and** image/dependency CVEs (cross #18).
- **kube-linter (StackRox / Red Hat) + hadolint** — https://github.com/stackrox/kube-linter . kube-linter checks Kubernetes YAML and Helm charts against best practices (no `latest` tag, resource requests/limits set, non-root, read-only root FS, no privileged); hadolint (DL3xxx) covers Dockerfiles (the Dockerfile mechanics themselves are #19's, but image-security defaults are shared).
  → mine: a K8s workload with **no resource limits** (noisy-neighbour / OOM-kill risk, cross #28), running **privileged / as root**, or pulling **`:latest`** is the recurring set — these are the kube-linter defaults worth asserting by hand.
- **Policy-as-code: OPA / Conftest (Rego) and HashiCorp Sentinel** — https://www.openpolicyagent.org/ , https://www.conftest.dev/ .
  → mine: org-specific guardrails (no public S3, mandatory tags, approved regions/instance types) belong in **versioned policy** evaluated in CI on the `plan`, not in a reviewer's memory — recommend codifying a repeated manual objection as a policy.
- **Drift detection: `terraform plan` (canonical), driftctl (maintenance mode), Snyk IaC** — https://developer.hashicorp.com/terraform/cli/commands/plan .
  → mine: a non-empty `terraform plan` against a supposedly-applied config **is** drift — someone changed live infra by hand (ClickOps), and the next apply will revert or fight it. `driftctl` is now maintenance-mode (Snyk moved drift detection into its platform); the always-available signal is `plan` in CI.
- **Cautionary — verify the tool still lives.** **Terrascan (Tenable) was archived 2025-11-20, read-only** — no new checks, no new provider/CVE coverage. A pipeline still gating on Terrascan has a **silently-decaying** gate.
  → mine: a concrete instance of this suite's standing rule — a canonical-but-dead scanner is a gap to close (migrate to Checkov/Trivy), not a gate to trust because it still exits zero (cross #19, #30).

### Tooling rules worth lifting

- **Checkov** — `checkov -d .`; built-in policy IDs `CKV_AWS_*` / `CKV_K8S_*` / `CKV2_*` (the `CKV2_` graph checks are the cross-resource ones); custom policies in Python/YAML; `--compact --quiet` for CI.
- **Trivy** — `trivy config <dir>` (IaC misconfig, includes the former tfsec rules `AVD-*`); `trivy k8s`; pairs with `trivy image` / `trivy fs` for CVEs so one tool spans IaC + supply chain.
- **kube-linter** — `kube-linter lint .` over K8s manifests/Helm; default checks: `latest-tag`, `no-read-only-root-fs`, `run-as-non-root`, `unset-cpu-requirements` / `unset-memory-requirements`, `privileged-container`, `dangling-service`.
- **hadolint** — `DL3008` (pin apt versions), `DL3007` (no `:latest` base), `DL3002` (no root `USER`), `DL3025` (JSON CMD) — image hygiene (Dockerfile *mechanics* owned by #19).
- **Conftest / OPA** — `conftest test plan.json` to enforce Rego policy on a `terraform show -json` plan; **Sentinel** for Terraform Cloud/Enterprise org policy.
- **`terraform plan` / `terraform validate` / `tflint`** — `validate` for syntax, `tflint` for provider-specific correctness + deprecations, `plan` (reviewed in the PR) as the blast-radius and drift signal; run `plan` in CI before any `apply`.

### Reviewable heuristics (skill-checklist seeds)

- **Blast radius of the change:** what does `terraform plan` (or the CloudFormation change set) say this actually does — **create, in-place update, or replace/destroy**? A `-/+` replace of a stateful resource (database, volume, bucket) is potential **data loss / downtime**; a destroy of anything stateful needs explicit confirmation and a backup (cross #20, #28).
- **Public exposure:** does the change open something to the world — `0.0.0.0/0` ingress, a public S3 bucket / blob container, a database with a public IP, a K8s `Service` of type `LoadBalancer` with no restriction? Default to private; flag any new public surface for explicit justification (security verdict owned by #14).
- **Over-broad IAM / least privilege:** wildcard `Action: "*"` or `Resource: "*"`, `AdministratorAccess`, or a role far broader than the workload needs? Scope to the specific actions/resources required (cross #14).
- **Secrets in plaintext or state:** are credentials hardcoded in `.tf` / vars / manifests, or written to **Terraform state** (which is plaintext)? Source from a secrets manager / sealed-secrets; ensure state is encrypted and access-controlled.
- **Unpinned modules & providers:** are Terraform `required_providers` / module sources and provider versions **pinned** (not floating to `latest`), and is the **state backend remote and locked** (not local `terraform.tfstate`)? Floating versions make the next apply non-reproducible (cross #18, #19).
- **Drift between declared and live:** does a `terraform plan` on supposedly-applied config come back **non-empty** (someone changed infra by hand)? ClickOps drift means the IaC is no longer the source of truth — reconcile or import it.
- **Container/workload defaults (K8s):** do Pods/Deployments set **resource requests and limits** (no limits → noisy-neighbour / OOM, cross #28), run **non-root** with a **read-only root filesystem**, avoid **`privileged` / hostNetwork / hostPath / docker-socket** mounts, and pin image digests (no `:latest`)?
- **Encryption & data protection:** is encryption-at-rest enabled on new storage (bucket / volume / DB) and TLS required in transit, rather than relying on a permissive default?
- **Tool currency & gate health:** is the IaC scanner in CI **maintained and actually running** (Checkov/Trivy current — not archived Terrascan or unmaintained tfsec), required to pass (not `continue-on-error`), and are its suppressions rule-scoped with a reason (cross #30)?
- **Policy-as-code for repeated objections:** is an org guardrail that keeps coming up in review (mandatory tags, no public exposure, approved regions) **codified as OPA/Conftest/Sentinel policy** evaluated on the plan, rather than re-litigated by hand each PR?

---

## Open threads

- **#17 over-mocking ↔ #11 dependency-elimination**: both push toward real collaborators/fakes over mocks. A shared "minimize mocking" stance is needed so the test-quality skill and the simplicity skill agree.
- **CVE scanning has three claimants** — #18 (deps), #14 (A06), #25 (LLM03). Single owner needed (map-gaps G1); SBOM (#18) also feeds license review in #27.
- **#19 fitness functions ↔ #12 architecture**: ArchUnit/import-linter rules are *authored* as architecture concerns (#12) but *run* as CI gates (#19). Decide where the skill responsibility sits.
- **#20 is the densest single-source category**: `strong_migrations`' unsafe-op catalog is the highest-value checklist seed in this whole cluster. Migration safety also overlaps #3 (online-change concurrency) and #2 (transaction/rollback) — a combined "safe data change" behavior is attractive.
- **Diff-shaped vs repo/cron-shaped (map-gaps G7)**: most of this cluster is diff-reviewable, but **dependency freshness (#18), stale-flag cleanup (#26), and schema drift (#20)** are *standing* conditions better checked on a schedule than in a single PR. Implies some Cluster-V skills are maintenance/cron-shaped, not review-shaped (cross open-question Q8).
- **Feature-flag lifecycle** is triple-booked (#12/#16/#26); canonical home proposed as #26 (map-gaps G1).
- **IaC/workflow surface added (2026-06-12):** hadolint/Checkov/tflint/kube-linter/actionlint/zizmor rules + five heuristics now live in #19. The seam mirrors G1: cloud *misconfiguration* findings are security findings (#14 owns the verdict, A05), and environment-pinning overlaps #26 portability — proposed split: **#19 owns the pipeline/workflow/manifest mechanics; #14 owns the security adjudication.** If IaC-heavy repos prove to need more, this is a candidate for its own review behavior (noted in taxonomy residual candidates).
