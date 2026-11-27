# Adopter, Upgrade & Distribution Experience — research synthesis

**Status:** synthesized 2026-06-16. **Candidate — provisional, owner-gated.** A deep,
web-verified research pass behind category **#33 (Install, upgrade & configuration
experience)** and the territory adjacent to it. This doc **enriches the corpus and
records candidates**; it does **not** assert a `taxonomy.md` change beyond #33 (which
already shipped). Category-vs-fold granularity calls are flagged for owner disposition,
the same gate `product-experience-value-cluster.md` and the round-3 hunt were held to.

**Motivation.** #33 shipped with references drafted from model knowledge and tagged
`(verify)`, and without reconciling against the repo's own prior dispositions
(round-3's "installability → covered by portability"; round-3's "install-footprint →
fold"; round-2's "contributor DevEx → out of scope"). The owner's mandate here is
**maximal comprehensiveness** — over-cover now, prune for signal later — because the
cost we are avoiding is *failing to specify an angle a review bot would then never
check*. This is the missing prior-art pass, done web-verified.

**Method.** Seven parallel web-verified research clusters (ISO/completeness models;
versioning & break detection; upgrade/migration mechanics; configuration UX;
install/setup mechanics; deprecation & adopter DX; agent-adoptability & distribution
lifecycle), each returning cited references, concrete tool/rule IDs, and one-line
diff-reviewable heuristics. Verified 2026-06-16 unless tagged `(verify)`.

---

## 1. External completeness models — what a standards-grade map names

The decisive finding: **ISO/IEC 25010:2023 reorganized exactly the area #33 lives in**,
which is why the round-3 "installability ⊆ portability" call no longer holds (see §10).

### Key references

- **ISO/IEC 25010:2023 — Product quality model (2nd ed., 2023-11)** — <https://www.iso.org/standard/78176.html> (free view: <https://www.iso.org/obp/ui/en/#!iso:std:78176:en>) — → mine: nine top-level characteristics; **Portability → renamed Flexibility** (sub-chars adaptability, installability, replaceability, **scalability**); **Compatibility** (co-existence, interoperability); **Usability → Interaction Capability** (+ self-descriptiveness, inclusivity, user assistance); **Safety** added; **Security** top-level; maturity → faultlessness. Each sub-characteristic maps to a distinct adopter signal.
- **ISO/IEC 25010:2011 (1st ed.)** — <https://www.iso.org/standard/35733.html> — → mine: the baseline the repo's "installability covered by portability" judgment was made against; 2011 Portability = adaptability + installability + replaceability + **co-existence** (2023 moved co-existence to Compatibility).
- **arc42 Quality Model — "Update on ISO 25010, version 2023"** — <https://quality.arc42.org/articles/iso-25010-update-2023> — → mine: authoritative plain-language changelog of the 2011→2023 deltas; the per-sub-characteristic one-liners at <https://quality.arc42.org/standards/iso-25010> are usable verbatim as review-check labels.
- **ISO/IEC 25019:2023 — Quality-in-use model** — <https://www.iso.org/standard/78177.html> — → mine: the *in-use* sibling; adopter *outcomes* live here, *product* properties (installability/replaceability) live in 25010 — cite to separate "code property" from "adopter outcome."
- **ISO/IEC 25002:2024 — Quality model overview & usage** — <https://www.iso.org/standard/78175.html> — → mine: confirms 25010 (product) + 25019 (in-use) compose as siblings, so installability/replaceability are *product* properties a diff can carry.
- **SEI — *Software Architecture in Practice*, 4th ed. (Bass/Clements/Kazman, 2022)** — <https://quality.arc42.org/articles/sei-quality-model> — → mine: adds **Deployability** and **Integrability** as first-class attributes ISO lacks — "can this be rolled out / rolled back / wired into a brownfield system?"
- **Debian — lintian** — <https://lintian.debian.org/manual/index.html> — → mine: installability/policy-lint precedent; tags flag broken maintainer scripts, file conflicts, missing deps — install-time failure caught statically.
- **Debian — piuparts** (.deb install/upgrade/remove tester) — <https://wiki.debian.org/piuparts> — → mine: the canonical "does install → upgrade-from-previous → purge leave the system clean?" CI gate — models installability + replaceability + clean-uninstall directly.

### Reviewable heuristics (highlights — full set folds into #33)

- Co-existence: does the change hardcode a port, host path, temp-file name, global config key, or system resource that could collide with another instance/app on the same host? *(catches co-existence/clobber)*
- Co-installability: does adding a dependency introduce an unsatisfiable peer/transitive constraint resolved only via `--legacy-peer-deps`/`--force`? *(catches dependency-resolution hell)*
- Installability: does install fail-fast on a missing prerequisite instead of half-installing, and is it idempotent on re-run? *(catches partial-install corruption)*
- Replaceability: does a public/library API change bump the version per semver / ship a deprecation window? *(catches silent replaceability break)*
- Clean teardown: does an uninstall path exist and remove what install created (files, services, schema, cron)? *(catches leftover-after-removal — no current atlas home)*
- Deployability/integrability (SEI): is there a rollback/flag path, and can the new component be wired into an existing system via documented config rather than assuming greenfield? *(catches non-deployable / non-integrable change)*

---

## 2. Versioning & breaking-change discipline — "beyond the type signature"

### Key references

- **Semantic Versioning 2.0.0** — <https://semver.org/> — → mine: MAJOR = incompatible, MINOR = compatible additions, PATCH = compatible fixes; `0.y.z` = "anything MAY change." Any incompatible change demands MAJOR.
- **node-semver range semantics** — <https://docs.npmjs.com/cli/v6/using-npm/semver/> — → mine: `^0.2.3` is treated like `~` (allows `0.2.x`, blocks `0.3.0`); a `0.x` *minor* bump IS a consumer break that caret ranges may still auto-pull.
- **Rust RFC 1105 — API Evolution** — <https://rust-lang.github.io/rfcs/1105-api-evolution.html> — → mine: a precise major-vs-minor taxonomy (adding an enum variant breaks exhaustive match; adding a non-defaulted trait item is major; loosening bounds is minor). "All major changes are breaking, but not all breaking changes are major."
- **Go 1 Compatibility Promise** — <https://go.dev/doc/go1compat> — → mine: never-break-within-major; a change that stops downstream compiling needs a new major (the `/v2` module-path rule).
- **Hyrum's Law** — <https://www.hyrumslaw.com/> — → mine: with enough users, *all observable behaviors* get depended on — so output format, log lines, error strings, exit codes, ordering, and timing are part of the contract, not just the typed signature.
- **Rich Hickey — "Spec-ulation" (2016)** — <https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/Spec_ulation.md> — → mine: the accretion rubric — *relax a requirement* or *strengthen a promise* or *add a name* = safe; *require more*, *promise less*, *remove/rename* = break. A language-agnostic break test that covers data formats and behaviors.
- **CalVer** — <https://calver.org/> — → mine: date-based versions carry **no** compatibility signal; on a CalVer package, break discipline must move to changelog/deprecation, and semver-assuming bots (Renovate/Dependabot) mis-fire.
- **ZeroVer** — <https://0ver.org/> — and **"Lost in Zero Space" (arXiv 2101.00836, 2021)** — <https://arxiv.org/pdf/2101.00836> — → mine: staying on `0.y.z` signals "no stability promise"; empirical evidence that 0.x packages ship breaks frequently `(verify the study's exact numbers)`.
- **Conventional Commits 1.0.0** — <https://www.conventionalcommits.org/en/v1.0.0/> — → mine: `feat!:`/`BREAKING CHANGE:` is the machine-readable break signal that drives auto-versioning; a diff removing public surface with no `!`/footer ships as a non-major bump — a versioning bug.
- **Renovate versioning / automerge** — <https://docs.renovatebot.com/modules/versioning/> — → mine: downstream automerge keys off the semver update-type; a break shipped as a minor gets auto-merged into consumers — the concrete blast radius of a mis-bump.

### Tooling rules worth lifting (CI break-detection gates, verified to exist)

- **cargo-semver-checks** (Rust) — `cargo semver-checks check-release`; non-zero exit on an API break without a major bump.
- **cargo-public-api** (Rust) — `cargo public-api diff <baseline>`; snapshots the public surface in CI.
- **@arethetypeswrong/cli** (`attw --pack .`) — broken TS/module-resolution contract: `💀 Resolution failed`, masquerading CJS/ESM, missing `types`.
- **@microsoft/api-extractor** — checked-in `.api.md` report diffed in CI; `@public/@beta/@alpha` release-tag discipline.
- **griffe check** (Python) — `griffe check pkg --against 1.0`; removed params/changed signatures between refs.
- **apidiff** / **gorelease** / **go-apidiff** (Go) — classify changes compatible vs incompatible; `gorelease` suggests the lowest semver-consistent version.
- **japicmp** / **revapi** / **japi-compliance-checker** (Java) — source- AND binary-incompatibility diff between JARs (distinguishes the two).
- **.NET ApiCompat / Package Validation** — `<EnablePackageValidation>true</EnablePackageValidation>` against a baseline package; suppression file for intentional breaks.
- **elm diff** — compiler-*enforced* semver: you cannot publish a break as a minor (the strongest prior-art exemplar).

### Net-new reviewable surface

The high-yield blind spot is **everything beyond the typed surface** — CLI flags, exit codes, env vars, config keys *and their semantics*, default-value changes, output/serialization format, log format, file/artifact layout, grep-able error strings (the Hyrum's-Law surface) — almost none of which has a compiler guarding it. Plus **version-vs-changelog consistency**: the novel check isn't "is this a break?" but "does the *version bump and changelog* match the break?", because downstream automation acts on that metadata.

---

## 3. Upgrade & migration mechanics — and the agent-runnable upgrade

### Key references

- **OpenRewrite — Recipes & dry-run** — <https://docs.openrewrite.org/concepts-and-explanations/recipes> — → mine: migrations as composable recipes producing a git-style diff via `rewriteDryRun` *before* any write — the gold standard for a *reviewable* automated upgrade; vendor-published version-jump pipelines (e.g. Migrate-to-Java-21) are the "upgrade guide as executable artifact."
- **Rust Edition Guide — `cargo fix --edition`** — <https://doc.rust-lang.org/edition-guide/editions/transitioning-an-existing-project-to-a-new-edition.html> — → mine: tool migrates code, then **prints the warnings it can't fix** — "automate the mechanical part, surface the residue explicitly"; advanced-migrations doc shows per-target/`--all-features` so feature-gated code isn't missed.
- **Stripe — `upgrade-stripe` Agent Skill + `.well-known/skills/index.json`** — <https://docs.stripe.com/building-with-ai> — → mine: **the agent-runnable-upgrade anchor** — a vendor ships a *machine-discoverable* skill that drives the migration plus a server-SDK ↔ Stripe.js ↔ webhooks sync checklist. Also Stripe lets you *dry-run* a new API version via the `Stripe-Version` header before committing (reversible rehearsal). `(verify the exact index URL contents)`
- **React 19 Upgrade Guide + codemods** — <https://react.dev/blog/2024/04/25/react-19-upgrade-guide> — → mine: each breaking change paired with `npx types-react-codemod@latest preset-19 ./path` — a rename ships a codemod, not just a changelog line.
- **Next.js `npx @next/codemod upgrade`** / **Angular `ng update` schematics** — <https://nextjs.org/docs/app/guides/upgrading/codemods>, <https://angular.dev/tools/cli/schematics> — → mine: library authors ship migrations *with* the breaking version; the consumer runs one command and reviews the diff.
- **Kubernetes Deprecated API Migration Guide + `kubectl convert`** — <https://kubernetes.io/docs/reference/using-api/deprecation-guide/> — → mine: a per-API removal-version table + a converter tool + a hard clock (GA 12 mo/3 releases, beta 9 mo/3 releases).
- **Rails Upgrade Guide** — <https://guides.rubyonrails.org/upgrading_ruby_on_rails.html> — → mine: upgrade one minor at a time, grep logs for `DEPRECATION WARNING:` **under full test coverage** — tests are the upgrade's verification harness.
- **Confluent — Schema Evolution & Compatibility Types** — <https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html> — → mine: backward = deploy consumers first, forward = producers first, full = order-free — tells you the safe deploy order and thus whether a rollback is safe.
- **Zuplo — versioning/back-compat best practices** — <https://zuplo.com/learning-center/api-versioning-backward-compatibility-best-practices> — → mine: the migration-guide genre spec — each breaking change shows before→after request+response, a deprecation window (≥1 cycle / ~90 days), warnings while old behavior still works.
- **Cautionary: `2to3`** — → mine: automation cannot rescue a migration across a *non-backward-compatible runtime boundary with no compatibility version*; "big-bang break, codemod as the only bridge" is a smell, not a solution. Expand/contract + dated-version-with-dry-run exist to avoid the 2to3 cliff.

### Tooling rules worth lifting

- **jscodeshift** / **ts-morph** / **codemod.com (`@codemod`)** — AST codemod runners with reviewable recast diffs; the substrate framework codemods build on.
- **OpenRewrite `rewriteDryRun`** — diffs + data tables, no writes (the reviewability primitive); `rewriteRun` applies.
- **Rector** (PHP) `--set php-php-85 --dry-run`; **`cargo fix --edition`**; **`go fix`** / **`gofmt -r`**; **`pyupgrade`**; **`ruff check --fix`** (classifies **safe vs unsafe** fixes, applies only safe by default).
- **`kubectl convert`**; **Angular `ng update`**; **`@next/codemod` / `react-codemod`**.
- **Renovate `automerge`** scoped by update-type (auto-merge clean patch/minor, hold majors); **`package.json` `engines`/`peerDependencies`** for compatibility signaling.
- **Schema Registry compatibility modes** — `BACKWARD`/`FORWARD`/`FULL` (+ `*_TRANSITIVE`) enforced at registration to block incompatible schema changes pre-deploy.

### Net-new reviewable surface — agent-runnable upgrade-and-verify (high value)

No existing atlas lens asks: **can a code agent move a consumer from N→N+1 from the docs/metadata alone and *verify* a clean result?** Two concrete signals: (a) a **machine-discoverable migration entry** (Stripe `.well-known/skills/index.json`, an `ng update` schematic, a codemod-registry slug, an OpenRewrite recipe id, an `npx … migrate` convention); (b) an **agent-runnable verification gate** (re-run recipe ⇒ empty diff; tests green; zero remaining deprecation warnings; build passes). Distinct from the human-facing migration guide.

---

## 4. Configuration UX (adopter-facing)

### Key references

- **Twelve-Factor — III. Config / X. Dev-prod parity** (open-sourced Nov 2024) — <https://12factor.net/config>, <https://12factor.net/dev-prod-parity> — → mine: deploy-varying values in env, not committed code (the "could-be-open-sourced" litmus); flag env-conditional code paths (`if env=='prod'`) that widen parity and escape CI.
- **pydantic-settings** — <https://docs.pydantic.dev/latest/concepts/pydantic_settings/> — → mine: typed schema validated at startup; `extra='forbid'` rejects unknown keys; a missing required setting fails fast naming the field. Flag ad-hoc `os.getenv` with no schema.
- **clig.dev — CLI Guidelines** — <https://clig.dev/> — → mine: follow XDG config paths, expose a `--config` override, make config discoverable, errors must be actionable.
- **OWASP — Secure-by-Default (Proactive Controls C5)** — <https://top10proactive.owasp.org/the-top-10/c5-secure-by-default/> — and **Secrets Management Cheat Sheet** — <https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html> — → mine: a new setting's default must be the secure choice (TLS on, debug off, CORS closed); secrets out of config files, referenced from a manager.
- **CUE** — <https://cuelang.org/docs/concept/configuration-use-case/> — and **Dhall** — → mine: validation-first / typed-total config languages; reference for "validate config against a schema, don't trust raw YAML."
- Critiques: **"Revisiting the Twelve-Factor App"** `(verify)` and **"We Followed the 12-Factor App…"** `(verify)` — → mine: env-var-only config hurts discoverability/debuggability at scale; argue for a single resolved/printed config surface and typed config files + secret managers alongside env.

### Tooling rules worth lifting

- **pydantic-settings** (`extra='forbid'`), **confuse** (layered + typed, Python); **envalid** / **znv** (Zod) / **convict** (per-key `doc`/`default`/`format`, generates a reference) / **zod** (JS/TS); **viper** + **kelseyhightower/envconfig** (Go); **CUE** / **Dhall**; **HCL/Terraform `validation { condition, error_message }`**; **JSON Schema + json-schema-for-humans** (validate + auto-generate a config reference).

### Net-new vs already-owned

`auditing-config-and-build-hygiene` / #26 already own the **internal** config-hygiene view (validated at startup, secrets out of files, env parity, drifting/unused keys). The genuinely **adopter-facing** slice nothing else owns: **new-required-setting friction** (a validated setting with no default still breaks every existing consumer on upgrade), **precedence surprises** (defaults < file < env < flags — "env var silently ignored"), and **config error-message actionability** (names the key + the fix). Backward-compatible config-key evolution (alias + warn on rename) is expand/contract for config — cross-ref `reviewing-api-contract-safety` + `reviewing-migration-and-data-safety`.

---

## 5. Install & setup mechanics

### Key references

- **Reproducible Builds — `SOURCE_DATE_EPOCH`** — <https://reproducible-builds.org/specs/source-date-epoch/> — → mine: an install/build step embedding wall-clock/build-host/absolute-paths without honoring `SOURCE_DATE_EPOCH` yields non-identical artifacts.
- **"How to write idempotent Bash scripts" (Arslan, 2019)** — <https://arslan.io/2019/07/03/how-to-write-idempotent-bash-scripts/> — → mine: `mkdir -p`, `ln -sfn`, guard appends; an installer using `>>`/`tee -a` into a user file with no "already present?" guard is a duplicate-write defect on re-run.
- **Ansible idempotency / Molecule `idempotence`** — <https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_intro.html> — → mine: the convergence bar — run twice, second run reports `changed=0`; the cleanest "is this installer idempotent" mental model + a concrete CI gate (run-twice-assert-no-change) neither currently named in the repo.
- **GitHub/npm — disabling npm install scripts by default (2026)** — <https://thehackernews.com/2026/06/github-to-disable-npm-install-scripts.html> — → mine: install-time lifecycle scripts are "the single largest code-execution surface in npm"; a diff adding `preinstall`/`install`/`postinstall` (or a dep that ships one) is a supply-chain surface, and CI running plain `npm install` rather than `npm ci --ignore-scripts` is the exposure. `(verify npm default-off rollout timing)`
- **Bundlephobia / Packagephobia** — <https://bundlephobia.com>, <https://packagephobia.com> — → mine: install-footprint signal — a new dep with heavy transitive weight / large unpacked size is install bloat. `(verify which measures install vs bundle size)`
- **Toolchain pinning** — `rust-toolchain.toml` <https://www.rustfaq.org/en/how-to-use-rust-toolchaintoml-to-pin-toolchain-versions/>, **mise.lock** <https://mise.jdx.dev/dev-tools/mise-lock.html>, `.nvmrc`/`.tool-versions` — → mine: floating `stable`/no pin lets toolchain drift change install/build output across adopters.
- **pip secure installs** — <https://pip.pypa.io/en/stable/topics/secure-installs/> — → mine: `pip install --require-hashes` against `pip-compile --generate-hashes`; unpinned/unhashed `pip install -r` is a reproducibility + supply-chain gap.
- **Dev Containers for onboarding** — <https://dev.to/nicovogel/onboarding-new-team-members-simplified-with-dev-containers-5gag> — → mine: "one command / open-in-container to working state"; a setup change adding a manual host prerequisite *not* captured in `devcontainer.json`/Dockerfile regresses time-to-first-success.
- **Apple — cross-platform shell scripting** — <https://developer.apple.com/library/archive/documentation/OpenSource/Conceptual/ShellScripting/PortingScriptstoMacOSX/PortingScriptstoMacOSX.html> — → mine: GNU-vs-BSD flag diffs (`sed -i`, `readlink -f`), `#!/usr/bin/env bash`, tool-presence assumptions; flag macOS-vs-Linux-breaking constructs in setup scripts.

### Tooling rules worth lifting

- **hadolint** (Dockerfile) — pin rules **DL3008** (apt `=ver`), **DL3013** (pip), **DL3016** (npm), **DL3018** (apk), **DL3028** (gem); footprint **DL3009** (clean apt lists), **DL3015** (`--no-install-recommends`), **DL3059** (consolidate `RUN`). `(verify exact DL numbers per current hadolint)`
- **ShellCheck** — **SC2039**/**SC3xxx** (bashism in a `sh` script), **SC2086** (unquoted vars break on paths), `# shellcheck shell=sh`. `(verify)`
- **`npm ci --ignore-scripts`** + **`can-i-ignore-scripts`** (audit which deps need scripts); **`pip --require-hashes`** + **pip-tools** `pip-compile --generate-hashes`/`pip-sync`; **`cargo build --locked`**; **`go mod verify`**.
- **Molecule `idempotence` / Ansible `--check`** + **`ansible-lint`** (`no-changed-when`, `command-instead-of-module`) — the run-twice gate + non-idempotent-step linting. `(verify rule names)`
- **`.gitattributes` `* text=auto eol=lf` / `*.sh text eol=lf`** — LF on shipped scripts so a CRLF checkout doesn't `bad interpreter`.
- **Fresh-install / quickstart CI job** — clean container running *only* documented steps; executable-README harnesses **mdsh** / **cram** / language doctest (`cargo test --doc` on README via `include_str!`, Python `doctest`). `(verify mdtest vs cram roles)`
- **`docker buildx` / `--platform`** — arch-explicit images so non-x86 adopters get a working install.

### Net-new (caught by no ordinary linter)

(1) **Re-run idempotency** of an installer/`init` (static analysis won't tell you `init` clobbers a user's edited config on second run — needs the run-twice heuristic); (2) **time-to-first-success regression** (counting required manual steps a diff adds to the quickstart); (3) **cross-platform install assumptions** broader than any single linter (ShellCheck catches bashisms, not "assumes GNU coreutils / a locale / an x86 image").

---

## 6. Deprecation — planned, dated, replacement-named

### Key references

- **RFC 8594 — Sunset HTTP header** — <https://www.rfc-editor.org/rfc/rfc8594.html> — and **RFC 8631 — deprecation/sunset link relations** — <https://www.rfc-editor.org/rfc/rfc8631.html> `(verify 8631 scope)`.
- **RFC 9745 — The Deprecation HTTP Response Header Field (March 2025)** — <https://www.rfc-editor.org/rfc/rfc9745.html> — → mine: **standardizes the `Deprecation:` header** (supersedes the long-running draft) paired with `Sunset:` + a `deprecation` link rel. **The atlas (#29) currently cites only 8594/8631 — 9745 is a clean, dated addition.**
- **OpenAPI `deprecated: true`** / **GraphQL `@deprecated(reason:)`** — <https://spec.openapis.org/oas/latest.html>, <https://spec.graphql.org/> — → mine: mark before removing; `@deprecated` should name the replacement *at the point of use* (default "No longer supported" names none — flag it).
- **Node.js deprecation tiers + `DEP00xx` codes** — <https://nodejs.org/api/deprecations.html> — → mine: Documentation-only → Runtime (stderr `util.deprecate`) → End-of-Life; a removal should have passed through Runtime-warning first.
- **Python PEP 387 — Backwards-compatibility policy** — <https://peps.python.org/pep-0387/> — → mine: removal requires a prior `DeprecationWarning` for ≥2 releases (~2 yr); formalizes **soft deprecation** (doc-only, propose a replacement).
- **Java `@Deprecated(since, forRemoval)`** — <https://docs.oracle.com/en/java/javase/25/core/how-deprecate-apis.html> — → mine: omitting `since`/`forRemoval` is under-documented; `forRemoval=true` is the strong scheduled-removal signal.
- **Rust `#[deprecated(since, note)]` + editions** / **C# `[Obsolete(message, IsError)]` + `DiagnosticId`** — <https://doc.rust-lang.org/reference/attributes/diagnostics.html>, <https://learn.microsoft.com/en-us/dotnet/fundamentals/syslib-diagnostics/obsoletions-overview> — → mine: deprecations carry the replacement in `note`/`message`; `IsError`/edition migration is the "end-of-grace-period" lever.
- **Kubernetes Deprecation Policy** — <https://kubernetes.io/docs/reference/using-api/deprecation-policy/> — and **Django Deprecation Timeline** (`RemovedInDjangoXXWarning`) — <https://docs.djangoproject.com/en/dev/internals/deprecation/> — → mine: gold-standard tiered, dated policies with version-named warning classes consumers can filter.
- **endoflife.date + API** — <https://endoflife.date/>, <https://endoflife.date/docs/api/v1/> — → mine: machine-readable EOL/EOS dates; a diff pinning/bumping a runtime/dep to an already-EOL release is reviewable; Renovate has an `endoflife-date` datasource.

### Tooling rules worth lifting

- **`staticcheck SA1019`** (Go — reads `// Deprecated:` comments; high noise on transitive deps, often scoped); **`@typescript-eslint/no-deprecated`** (successor to the archived `eslint-plugin-deprecation`); **`import-x/no-deprecated`**; **`javac -Xlint:deprecation` + `jdeprscan`**; **C# `CS0612`/`CS0618`/`CS0619`** + per-obsoletion `SYSLIB0XXX`. `(verify IDs)`
- Doc-freshness: **Python `doctest`**, **phmdoctest**, **markdown-doctest**, **rustdoc doctests** — examples-as-tests so the quickstart can't rot.

### Already-owned vs net-new

`reviewing-decision-lifecycle` (#29) fully owns the **decision/plan** level (sunset date, migration path, tracked removal ticket, revisit-triggers; its eval already uses an RFC-8594 plan). Net-new at the **mechanism** level on a diff: replacement-named-at-use, **warning-tier-before-error**, deprecation-with-no-removal-date (permanent limbo), removal-with-no-prior-warning — plus **RFC 9745** and **EOL-on-the-diff**. These are lint-adjacent per-diff checks distinct from the decision review.

---

## 7. Adopter developer-experience / time-to-first-success

### Key references

- **DevEx: What Actually Drives Productivity (Noda, Storey, Forsgren, Greiler — ACM Queue 21(2), 2023)** — <https://dl.acm.org/doi/10.1145/3595878> — → mine: three dimensions — **feedback loops, cognitive load, flow state**; the *adopter* slice is a diff that lengthens the consumer feedback loop (quickstart no longer runs) or raises cognitive load (new undocumented prerequisite). **Distinguish from internal contributor DevEx** (out of scope, §10).
- **Time to First Hello World / time-to-value (DevRel/DX literature)** — <https://www.moesif.com/blog/technical/api-product-management/What-is-TTFHW/> — → mine: the canonical adopter metric; a diff adding a step/signup-gate/config requirement between clone and first success regresses TTFHW (one cited target: access → first call < 30 min).
- **Diátaxis — tutorials** — <https://diataxis.fr/> — → mine: the guaranteed-to-work tutorial is the adopter front door; breaking its happy path, or burying getting-started in reference, is an onboarding regression.
- **Stripe / Twilio onboarding** — <https://www.twilio.com/en-us/blog/developers/redesigning-twilio-onboarding-experience-whats-new> — → mine: working sample + test key + sandbox "in minutes," copy-pasteable example per language; the reviewable analog is "does the change keep a minimal example that runs against the current API?"

### Reviewable heuristics

- Does this change add a step, gate, credential, or undocumented prerequisite between clone and first successful run? *(onboarding-friction regression)*
- Does the README/tutorial happy-path still execute against the changed code (imports resolve, no removed API, commands valid)? *(broken front door)*
- If a getting-started step changed (renamed command/new flag), is the doc updated *and* the old form deprecated/redirected, not just deleted? *(adopter-facing yank of the onboarding path)*

`auditing-documentation-health` (#22) owns doc *truth/freshness* and the runnable-example check; the net-new framing is **onboarding friction added by a diff** as a measurable DX regression against the consumer's clone→first-success path.

---

## 8. Agent-adoptability & distribution lifecycle

### Key references

- **AGENTS.md** — <https://agents.md/> — and **Linux Foundation — Agentic AI Foundation (formed Dec 2025)** — <https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation> — → mine: a root (and nested, nearest-file-wins) plain-Markdown agent-instructions file; AGENTS.md/MCP/goose now neutrally stewarded (platinum members incl. AWS, Anthropic, Google, Microsoft, OpenAI, Block). *(Charter's "founded ~2025" verified as formed December 2025.)*
- **GitHub — "How to write a great agents.md (2,500 repos)"** — <https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/> — → mine: the most-reviewable signal is **exact commands with flags at the top** (`pytest -v`, `npm run build`), a real code snippet over prose, and a three-tier boundary block (always / ask-first / never). Catches vague AGENTS.md an agent can't act on.
- **npm package provenance + Trusted Publishing (Sigstore, GA July 2025)** — <https://github.blog/security/supply-chain-security/introducing-npm-package-provenance/>, <https://docs.npmjs.com/generating-provenance-statements/> — → mine: publish with `--provenance` via OIDC Trusted Publishing (not a long-lived `NPM_TOKEN`); consumer/CI verify via `npm audit signatures` / `slsa-verifier`.
- **publint** — <https://publint.dev/rules> — and **`@arethetypeswrong/cli`** — → mine: lint packaging shape (`exports`/`main`/`module`/`types` order, files shipped, CJS/ESM correctness) and TS resolution under each module mode on any entry-point diff.
- **npm deprecate** — <https://docs.npmjs.com/cli/v11/commands/npm-deprecate/> — → mine: deprecation is first-class, reversible registry metadata shown on install; a sunset PR should `npm deprecate` the old version, not unpublish. (Contrast: **crates.io yank** RFC 3660 — no message; **PyPI yank** — no per-version deprecate flag + `Requires-Python` as the compat field — so teardown comms differ by ecosystem.)
- **VS Code Extension Manifest / activation / `deactivate`** — <https://code.visualstudio.com/api/references/extension-manifest> — and **Claude Code plugins** (`.claude-plugin/plugin.json`) — <https://code.claude.com/docs/en/plugins> — and **MCP Bundles `.mcpb`** (manifest declares capabilities, entry points, **permissions**, config inputs; Nov 2025, replaced `.dxt`) — <https://github.com/modelcontextprotocol/mcpb> — → mine: the distributable-artifact manifest is a reviewable surface (required fields, declared contribution/activation points, declared+minimal permissions, `engines`/compat range, clean `deactivate`/uninstall). `(verify .mcpb spec version)`
- **Agent-native architecture** — <https://www.builder.io/blog/agent-native-architecture> — → mine: "anything the UI can do, the agent can do too" via one action model; a new user-facing action with no programmatic/tool path is a parity gap.

### Tooling rules worth lifting

- **publint**, **attw**, **`npm pkg get/set/fix`** (agent-friendly deterministic metadata edits), **package-json-validator**, **Knip** (dead files/deps/exports before publish), **`npm publish --provenance`** + **`npm audit signatures`** / **slsa-verifier** / **cosign**, **`vsce`** (VS Code packaging/manifest validation), **`mcpb`** CLI (scaffold/pack/validate bundles), **codemod CLI / jscodeshift**. `(verify)`

### Net-new reviewable surface (high value; partly dogfoodable — this repo *is* a plugin)

- **Agent-runnable install/upgrade-and-verify** (see §3) — no lens asks whether the setup/upgrade journey is executable and self-verifying by a machine.
- **Plugin/extension/bundle lifecycle** — manifest integrity, capability/**permission declaration clarity**, **enable/disable/uninstall cleanliness (no mess, reversible adoption)**, **multi-version coexistence**, plugin-vs-host **API stability**. None of the current lenses target the distributable-artifact lifecycle (VS Code/`.vsix`, Claude plugin, `.mcpb`, Backstage, Terraform provider, Helm chart) — and this repo's own `plugin.json`/`marketplace.json` + `atlas-init` install/uninstall flow are reviewable under it.
- **Registry/distribution metadata quality** — provenance attached, README renders on the registry, deprecate-not-unpublish, compat fields (`engines`/`requires-python`) truthful per ecosystem.
- **AGENTS.md machine-followability** — exact runnable commands + scoping/precedence (extends #22's "README front-door for agents").

---

## 9. Tooling-rule index (verified, CI-mountable)

| Capability | Tools (verified to exist) |
|---|---|
| API/ABI break detection | cargo-semver-checks, cargo-public-api, attw, api-extractor, griffe check, apidiff/gorelease/go-apidiff, japicmp/revapi, .NET ApiCompat, elm diff |
| Packaging shape | publint, attw, package-json-validator, Knip, vsce, mcpb |
| Codemods / migration | jscodeshift, ts-morph, codemod.com, OpenRewrite, Rector, cargo fix --edition, go fix/gofmt -r, pyupgrade, ruff --fix, ng update, @next/codemod, kubectl convert |
| Config validation | pydantic-settings, confuse, envalid, znv, convict, zod, viper/envconfig, CUE, Dhall, HCL validation, JSON Schema |
| Install reproducibility/supply-chain | hadolint (DL30xx), ShellCheck, npm ci --ignore-scripts, can-i-ignore-scripts, pip --require-hashes/pip-tools, cargo --locked, go mod verify, SOURCE_DATE_EPOCH, lockfiles, toolchain pins (rust-toolchain.toml, mise.lock, .nvmrc) |
| Installability/idempotency | Debian piuparts/lintian, Ansible/Molecule idempotence gate, ansible-lint |
| Deprecation surfacing | staticcheck SA1019, @typescript-eslint/no-deprecated, import-x/no-deprecated, javac -Xlint:deprecation + jdeprscan, C# CS0618/0619 |
| Doc/quickstart freshness | doctest, phmdoctest, markdown-doctest, rustdoc doctests, fresh-install CI job |
| Provenance | npm --provenance + Trusted Publishing, npm audit signatures, slsa-verifier, cosign, Sigstore |
| EOL / lifecycle | endoflife.date API, Renovate endoflife-date datasource, Renovate automerge |

---

## 10. Prior-art reconciliation (the step #33 skipped) — fresh-evidence verdicts

| Prior disposition (where) | Fresh-evidence verdict |
|---|---|
| **"installability ⊆ portability/scalability — covered"** (round-3, ISO-25010 sweep) | **Overturn / split.** ISO **2023** renamed Portability→**Flexibility** and now lists installability, replaceability, adaptability, **scalability** as *peers*, and moved **co-existence + interoperability to Compatibility** — "portability/scalability" no longer even names installability or replaceability. Failure modes differ (portability = "runs elsewhere"; installability = "the act of install/upgrade/remove succeeds & is clean"; replaceability = "swap us in/out"), and tooling is separate (piuparts ≠ a portability linter; japicmp/cargo-semver-checks target replaceability). → installability+upgradeability, replaceability, and **co-existence/co-installability** deserve their own reviewable surface (fold into #33). |
| **"packaging / install-footprint → fold as factors into #13/#24"** (round-3) | **Partially holds.** Footprint *is* a factor (cross-ref #18). But install **mechanics** — re-run idempotency, reproducible bytes, lifecycle-script execution surface, cross-platform setup — are net-new and live in neither #13 nor #24. → #33 owns install mechanics; footprint cross-refs #18. |
| **"contributor DevEx-as-a-system → out of scope"** (round-2, org-measurement/no-artifact) | **Holds for contributor/org DevEx.** But **adopter DX** (TTFHW, quickstart-runs, new-required-step) is diff-visible and in-scope via G23 detect-and-route. Draw the line explicitly: contributor-DevEx-as-a-metric out; adopter-onboarding-friction-on-a-diff in. |
| **G23 detect-and-route (surfacing ≠ deciding)** (product-experience-value-cluster) | **Applies.** Adopter-experience findings are reviewable at review time; some (a product-driven config default, a distribution policy) `route:` to maintainers/product but are surfaced with evidence, never silently dropped. |

**Net:** the reframe *sharpens* the boundary — most prior calls were right on their axis, but the ISO-2023 reorganization genuinely reopened installability/replaceability/co-existence, and the adopter-vs-contributor DX distinction was conflated.

---

## 11. Net-new reviewable-angle inventory (owner-gated dispositions)

| # | Angle (diff-reviewable) | Currently owned? | Lean disposition |
|---|---|---|---|
| A | Re-run idempotency of installer/`init` (no clobber/dup on 2nd run) | No | **fold → #33** (run-twice gate) |
| B | Reproducible install bytes / `SOURCE_DATE_EPOCH` / pinned toolchain | partial #19 (build-side) | **#33 consumer-facing + cross-ref #19** |
| C | Version-vs-changelog consistency (break matches the bump) | No | **fold → #33 / cross-ref #13** |
| D | Hyrum's-law contract surface (CLI/exit/env/output/log/file-layout breaks) | partial #13 (typed only) | **fold → #33** |
| E | **Agent-runnable upgrade-and-verify** (discoverable migration + verification gate) | No | **fold → #33; candidate ★ factor** |
| F | Co-existence / co-installability (port/path/env clobber, peer-dep hell) | partial #26 (env), #18 (deps) | **candidate factor (#33) + cross-ref** |
| G | Replaceability / exit (semver-diff CI gate; swap-out cost) | partial #13, #29 | **cross-ref #13/#29** |
| H | Clean uninstall / teardown (no mess, reversible adoption) | **No home** | **candidate — fold #33 or new** |
| I | Operator-facing interaction quality (CLI flag help+default, destructive-op guard, actionable errors) | No (#23 is end-user UI) | **candidate — distinct surface** |
| J | Config precedence surprises + new-required-setting friction + error actionability | partial #26 (internal) | **fold → #33 / cross-ref #26** |
| K | Plugin/extension/bundle lifecycle (manifest integrity, permission clarity, multi-version, host-API stability, uninstall) | **No** | **candidate — own category? (dogfoodable)** |
| L | AGENTS.md machine-followability (exact commands, scoping/precedence) | partial #22 (drift) | **extend #22 / cross-ref #33** |
| M | Agent-native parity (user action ⇒ programmatic path) | partial #24 | **strengthen #24** |
| N | Distribution/registry metadata quality (provenance, engines/requires-python truthful, registry-renderable, deprecate-not-unpublish) | partial #18/#27 | **candidate factor + cross-ref** |
| O | Deprecation **mechanism** on a diff (replacement-at-use, warning-before-error, removal clock, RFC 9745) | partial #29 (plan-level) | **fold → #29 + #33 cross-ref** |

---

## 12. Recommended adjacent-category factor additions (owner-gated — do not apply unilaterally)

- **#29 Decision lifecycle:** add **RFC 9745** (Deprecation header) alongside 8594/8631; add code-level deprecation-**mechanism** heuristics (warning-tier-before-error, replacement-at-use); add **EOL-on-the-diff** via endoflife.date.
- **#13 API & contract:** add **version-vs-changelog consistency**, the **Hyrum's-law non-typed contract surface**, and a **CI break-detection tool gate** (cargo-semver-checks / attw / japicmp / griffe / apidiff / api-extractor / elm diff).
- **#26 Configuration & environment:** cross-link the **adopter-facing** config-UX slice (new-required-setting friction, precedence surprises, error actionability) as distinct from internal hygiene.
- **#18/#19 Deps & build:** strengthen the **install-script execution surface** (`--ignore-scripts`) and **consumer-facing reproducible install** (lockfile clean-install, hash-pinning) framing.
- **#22 Documentation:** add **AGENTS.md machine-followability** (exact runnable commands, nearest-file-wins) and the **upgrade-guide-as-genre** sub-check (before→after, deprecation window, automated path).
- **#20 Data & persistence:** extend **expand/contract** beyond DB to **wire/serialization formats** (Protobuf reserved field numbers, Avro aliases/defaults, Schema-Registry FULL/transitive) and to **config**.

---

## 13. Open questions for owner disposition

1. **Granularity.** Does **#33** absorb angles A–J (install/upgrade/config experience), or do some split out? Cluster VI is filling up, and angles **K (plugin/distribution lifecycle)**, **I (operator-interaction quality)**, and **H (clean uninstall)** arguably form a distinct **"distribution, packaging & lifecycle"** topic rather than factors of #33.
2. **Agent-runnable upgrade-and-verify (E).** A ★ factor inside #33, or its own thin lens? It's the highest-leverage net-new angle and the one most aligned with the suite's agent-native thesis.
3. **Plugin-lifecycle dogfood.** Should the suite review its **own** plugin install/upgrade/uninstall (`plugin.json`, `marketplace.json`, `atlas-init`) under angle K — the most direct test of "can we compete with a smooth adopter experience"?
4. **Operator-interaction quality (I).** A new home, or factors split between #33 (CLI flag/help/defaults) and #16 (actionable operator errors)?

## Sources

All inline above (verified 2026-06-16). Residual `(verify)` marks: the "Lost in Zero Space" study figures, the `.mcpb` spec version, the exact Stripe skills-index URL contents, current hadolint DL-number assignments, and npm install-script default-off rollout timing — confirm at skill-authoring time.
