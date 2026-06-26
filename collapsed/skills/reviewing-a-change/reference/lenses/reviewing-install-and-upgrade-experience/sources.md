# References to mine — reviewing-install-and-upgrade-experience

## Contents

- From category #33

## From category #33

### Key references

> Web-verified 2026-06-16. The full per-topic synthesis (ISO models, break-detection tooling, codemod ecosystems, deprecation policies, distribution lifecycle, prior-art reconciliation, and a net-new-angle inventory) lives in `adopter-experience-cluster.md`; this section carries the curated head that the lens is built from.

- **Twelve-Factor App — III. Config / X. Dev-prod parity** — https://12factor.net/config (open-sourced Nov 2024)
  → mine: config strictly separated from code and injected via the environment; a new *required*, environment-specific setting with no safe default is adoption friction; an `if env == "prod"` branch widens the parity gap and escapes CI.
- **Semantic Versioning 2.0.0** — https://semver.org
  → mine: the machine-readable promise that lets a consumer — and Renovate/Dependabot, and an agent — tell a safe patch/minor from a breaking major. A break under a non-major bump silently breaks every *automated* upgrade. Caveat: a `0.y` *minor* bump is itself a break that `^0.y` ranges may still auto-pull.
- **Keep a Changelog + Conventional Commits 1.0.0** — https://keepachangelog.com , https://www.conventionalcommits.org/en/v1.0.0/
  → mine: the categorized changelog + the `feat!:`/`BREAKING CHANGE:` footer are the migration metadata auto-release and an agent read; a diff removing public surface with no `!`/footer ships as a non-major bump — a versioning bug. A *rename* needs an upgrade instruction, not just a line (cross #22).
- **Rich Hickey — "Spec-ulation" (2016)** — https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/Spec_ulation.md
  → mine: the accretion rubric — *relax a requirement* / *strengthen a promise* / *add a name* = safe; *require more* / *promise less* / *remove or rename* = break. A language-agnostic break test that covers data formats and behaviors, not just signatures.
- **Hyrum's Law** — https://www.hyrumslaw.com
  → mine: with enough users, *all observable behaviors* get depended on — so CLI flags, exit codes, env vars, output/serialization format, log lines, file layout, and grep-able error strings are part of the contract a compiler does not guard (the highest-yield break blind spot).
- **ISO/IEC 25010:2023 — product quality model** — https://www.iso.org/obp/ui/en/#!iso:std:78176:en
  → mine: the 2023 revision renamed Portability→**Flexibility** (installability, replaceability, adaptability, scalability as *peers*) and put **co-existence + interoperability** under **Compatibility** — naming installability/replaceability/co-installability as distinct adopter properties (the reconciliation that reopened this surface; see `adopter-experience-cluster.md` §10).
- **Codemod & migration tooling** — jscodeshift, **OpenRewrite** (`rewriteDryRun`), Rust `cargo fix --edition` (migrates, then prints what it can't fix), Angular `ng update` schematics, `npx @next/codemod upgrade`, React codemods — https://docs.openrewrite.org/concepts-and-explanations/recipes
  → mine: ship the upgrade as *runnable, dry-run-able* tooling, not prose; an automated migration turns a version bump into a step a consumer or agent runs and diffs. Cautionary: `2to3` shows automation can't rescue a big-bang break across an incompatible runtime — expand/contract + dated-version-with-dry-run exist to avoid that cliff.
- **Stripe — `upgrade-stripe` Agent Skill + `.well-known/skills/index.json`** — https://docs.stripe.com/building-with-ai `(verify exact index contents)`
  → mine: the agent-runnable-upgrade exemplar — a vendor ships a *machine-discoverable* skill that drives the migration and a cross-component sync checklist; the upgrade is something an agent can find, run, and verify, not just read.
- **RFC 9745 (Deprecation header, 2025) / RFC 8594 (Sunset) / RFC 8631 (links) + runtime deprecation warnings** — https://www.rfc-editor.org/rfc/rfc9745.html
  → mine: deprecation is a dated, signposted activity that names the replacement *at the point of use* (`@deprecated`, `#[deprecated(note)]`, `Deprecation`/`Sunset` headers), passing through a warning tier *before* an error/removal tier, giving a migration window instead of a surprise broken build (cross #29).
- **Adopter DX / "time to first success"** — DevEx, ACM Queue 21(2), 2023 https://dl.acm.org/doi/10.1145/3595878 ; TTFHW https://www.moesif.com/blog/technical/api-product-management/What-is-TTFHW/
  → mine: the highest-leverage adoption metric is steps-to-first-working-result; a diff adding a step/gate/undocumented prerequisite to the clone→first-success path is a DX regression. (Adopter DX is diff-visible and in scope; contributor-DevEx-as-a-metric stays out — see `adopter-experience-cluster.md` §10.)
- **Config-as-schema / fail-fast validation** — pydantic-settings https://docs.pydantic.dev/latest/concepts/pydantic_settings/ ; envalid/znv/convict/zod (JS), viper/envconfig (Go), CUE, Dhall, HCL `validation {}`
  → mine: validate config at startup against a declared schema (`extra='forbid'` rejects typo'd keys) and fail with a message naming the offending key *and the fix* — not a deep stack trace, not a silent wrong default surfacing three steps later (cross #26).
- **Reproducible & idempotent install** — Reproducible Builds (`SOURCE_DATE_EPOCH`) https://reproducible-builds.org/specs/source-date-epoch/ ; Ansible/Molecule idempotency (run-twice ⇒ `changed=0`); npm install-script default-off (2026) `(verify rollout)`
  → mine: a consumer's install/setup should be reproducible (lockfiles + pinned toolchains → identical bytes) and idempotent (safe to re-run, no clobber); an installer's lifecycle scripts are a code-execution/supply-chain surface (cross #18, #19).
- **AGENTS.md (Agentic AI Foundation / Linux Foundation, Dec 2025)** — https://agents.md , https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/
  → mine: the "README front-door for agents" — exact build/test/lint/run commands with flags, nearest-file-wins in a monorepo; a project an agent can adopt/upgrade is one whose setup is captured as runnable commands, not tribal knowledge (cross #22, #24).
