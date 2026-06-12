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

### Tooling rules worth lifting
- **Coverage:** coverage.py (Python), Istanbul/nyc & V8 (JS), JaCoCo (Java), SimpleCov (Ruby), `go test -cover`. Lift: track **branch** coverage and the coverage **delta on the diff**, not a global %.
- **Mutation:** PIT/pitest (Java), **Stryker** (JS/TS, C#, Scala — https://stryker-mutator.io/), mutmut & cosmic-ray (Python), Mutant (Ruby), **cargo-mutants** (Rust — https://mutants.rs/), gremlins (Go — https://gremlins.dev/). For a pure crate/module with fast deterministic tests, a mutation run is cheap, and the surviving-mutant list makes a good CI gate.
- **Property-based:** Hypothesis (Python), fast-check (JS/TS), jqwik (Java), PropEr/QuickCheck.
- **Flaky control:** `pytest-randomly` (random order), `pytest-rerunfailures`, Jest `--detectOpenHandles`, Gradle/Maven retry, flaky trackers (BuildPulse, Datadog Test Optimization).
- **Test linters:** `eslint-plugin-jest` (`no-disabled-tests`, `no-focused-tests`, `expect-expect`, `no-conditional-expect`), `rubocop-rspec`, `flake8-pytest-style`.

### Reviewable heuristics (skill-checklist seeds)
- Do new/changed tests assert **observable behavior** (inputs→outputs, side effects), not internal calls/private state (refactor-resistant)?
- Is coverage **meaningful** on the new code — branches and edge cases, not just lines executed? Don't chase a % with assertion-free tests.
- Bug fix → is there a **regression test** that fails before the fix and passes after?
- Are tests **isolated and deterministic** — no shared mutable state, order dependence, or real clock/network/unseeded random (flaky risk)?
- Is the test at the **right level** (pyramid/trophy) — logic in fast unit/integration, e2e reserved for critical journeys?
- **Over-mocking smell**: do mocks assert on implementation calls so a refactor breaks tests without behavior changing? Prefer real collaborators / fakes (cross #11).
- Are **edge/boundary** cases covered (empty, null, max, error paths) — where the bugs live (cross #1)?
- Would the suite **catch a real bug**, not just execute lines? Apply mutation intuition — for a pure, deterministic, fast-to-test unit, prefer actually running a mutation tool (cheap, high-signal) over eyeballing it; otherwise high coverage masks weak assertions.
- Any disabled/focused/skipped tests (`.only`, `xit`, `@Disabled`) sneaking in?
- For nondeterministic/concurrent code, is the invariant property-tested and the concurrent path exercised (cross #3)?
- Is each test readable — clear arrange/act/assert, one behavior per test, name reads as a spec?

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

### Reviewable heuristics (skill-checklist seeds)
- Does CI run the full gate on the diff — lint, format-check, type-check, tests, dep/security scan — and is passing **required** to merge?
- Is the build **reproducible/hermetic** enough to not depend on machine-local state (pinned toolchain, lockfiles, no network in build)?
- Is CI **fast and reliable**? A new slow/flaky job is a defect — parallelized, cached, deterministic?
- Are **secrets** injected at runtime (not baked into the image/repo/CI logs) and least-privilege scoped (cross #14)?
- Risky change → is there a safe rollout (canary/flag) and a **tested rollback** path (cross #16, #20)?
- Is incomplete work integrated **behind a flag** (trunk-based), not a long-lived branch?
- Does the pipeline **build once and promote** the same artifact, not rebuild per environment?
- Are pre-commit/pre-push hooks present so obvious issues never reach CI?

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
- **Portability**: any hardcoded paths, OS/arch assumptions, locale/encoding/timezone assumptions, or non-portable shell?
- Are **secrets** sourced from a manager/env (never repo or logs) and rotatable?
- Is configuration **documented** (each var's purpose, required vs optional, default)?

---

## Open threads

- **#17 over-mocking ↔ #11 dependency-elimination**: both push toward real collaborators/fakes over mocks. A shared "minimize mocking" stance is needed so the test-quality skill and the simplicity skill agree.
- **CVE scanning has three claimants** — #18 (deps), #14 (A06), #25 (LLM03). Single owner needed (map-gaps G1); SBOM (#18) also feeds license review in #27.
- **#19 fitness functions ↔ #12 architecture**: ArchUnit/import-linter rules are *authored* as architecture concerns (#12) but *run* as CI gates (#19). Decide where the skill responsibility sits.
- **#20 is the densest single-source category**: `strong_migrations`' unsafe-op catalog is the highest-value checklist seed in this whole cluster. Migration safety also overlaps #3 (online-change concurrency) and #2 (transaction/rollback) — a combined "safe data change" behavior is attractive.
- **Diff-shaped vs repo/cron-shaped (map-gaps G7)**: most of this cluster is diff-reviewable, but **dependency freshness (#18), stale-flag cleanup (#26), and schema drift (#20)** are *standing* conditions better checked on a schedule than in a single PR. Implies some Cluster-V skills are maintenance/cron-shaped, not review-shaped (cross open-question Q8).
- **Feature-flag lifecycle** is triple-booked (#12/#16/#26); canonical home proposed as #26 (map-gaps G1).
