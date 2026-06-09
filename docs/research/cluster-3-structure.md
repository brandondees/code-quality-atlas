# Research — Cluster III: Structure & Architecture

> Part of code-quality-atlas phase-1 research (see ../taxonomy.md). Generated 2026-06-09 via web research from the main loop. Citations verified except where marked `(verify)`. Mirrors the section structure of [cluster-1-correctness.md](cluster-1-correctness.md).

---

## #9 Module / unit design

### Key references
- **David Parnas — "On the Criteria To Be Used in Decomposing Systems into Modules" (1972)** → mine: decompose by **information hiding** — each module hides a design decision likely to change — not by flowchart/processing steps. The foundational cohesion/encapsulation argument.
- **Meilir Page-Jones — Connascence** (catalog: https://connascence.io/) → mine: a *precise* vocabulary for coupling. Nine types — **static**: Name, Type, Meaning/Convention, Position, Algorithm; **dynamic**: Execution (order), Timing, Value, Identity — each evaluated by **Strength** (harder to refactor = worse), **Degree** (how many entities), **Locality** (near is better than far). Operational rule: *prefer weaker connascence; keep stronger connascence local.* Far more actionable than "reduce coupling."
- **John Ousterhout — *A Philosophy of Software Design* (deep modules)** → mine: a good module is a **simple interface over substantial behavior**; shallow modules (interface ≈ implementation) are negative-value ("classitis").
- **Joshua Bloch — "How to Design a Good API and Why It Matters" (2006)** — https://research.google.com/pubs/archive/32713.pdf → mine: **"easy to use, hard to misuse"**, "when in doubt, leave it out", minimize mutability, names matter. The caller-ergonomics / internal-API-DX core of #9.
- **Rust API Guidelines — "hard to misuse"** `(verify URL)` → mine: type-driven misuse-resistance (newtypes, builders, typestate) so wrong usage won't compile.

### Tooling rules worth lifting
- **dependency-cruiser** (JS/TS) — `no-circular`, `no-orphans`, custom `forbidden` rules for cross-module reach-ins. (https://github.com/sverweij/dependency-cruiser)
- **madge** (JS/TS) — `--circular` flags dependency cycles; graphs fan-in/out.
- **eslint-plugin-import `import/no-cycle`**, **eslint-plugin-boundaries** — module-boundary enforcement in lint.
- **import-linter** (Python) — contract types `forbidden`, `independence`, `layers` enforce module boundaries. (https://import-linter.readthedocs.io/)
- **ArchUnit** (Java) / **NetArchTest** (.NET) — assert "no cycles", "X may not depend on Y" as unit tests. (https://www.archunit.org/)
- **Reek** (Ruby) — `FeatureEnvy` (method uses another object more than `self` → move it), `DataClump` (same param group recurs → extract a type), `UtilityFunction` (no `self` refs → misplaced), `TooManyInstanceVariables`. (https://github.com/troessner/reek)
- **PMD** (Java) — `CouplingBetweenObjects`, `ExcessiveImports`, `LawOfDemeter`.

### Reviewable heuristics (skill-checklist seeds)
- Does the unit have **one** clear responsibility (high cohesion)? State its job in a sentence without "and."
- Is the interface **narrow relative to the behavior** behind it (deep module), or a shallow pass-through adding no value?
- What is the **strongest connascence crossing the boundary**, and is it local? (Position/Algorithm connascence across modules is a smell; prefer Name/Type.)
- Does it **hide its implementation** so internals can change without breaking callers?
- Is it **hard to misuse** — invalid argument/call-sequence prevented by types, not docs (caller ergonomics / pit of success)?
- Any **Feature Envy** (method mostly manipulates another object's data → move it there)?
- Any **Data Clump** (the same field/param cluster traveling together → extract a type)?
- Law of Demeter respected (no `a.b.c.d` train-wreck reach-through)?
- Mutability minimized; value objects immutable?
- Composition preferred over inheritance; inheritance shallow and not used purely for reuse?
- Any cyclic dependency between units (break via dependency inversion)?
- "When in doubt, leave it out": is speculative public surface being added (cross #11)?

---

## #10 Type & data modeling

### Key references
- **Alexis King — "Parse, Don't Validate" (2019)** — https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/ `(verify URL)` → mine: parse untrusted input into a **constrained type once** at the boundary; downstream relies on the type's guarantees. "Shotgun parsing" (validate-then-pass-raw, re-checked everywhere) is the antipattern.
- **Yaron Minsky — "Make Illegal States Unrepresentable" (Effective ML, 2010; Jane Street/OCaml)** → mine: model the domain so invalid/nonsensical states **cannot be expressed**; the type system is the enforcement mechanism, not runtime checks or docs.
- **Scott Wlaschin — "Designing with Types" (F# for Fun and Profit)** — https://fsharpforfunandprofit.com/posts/designing-with-types-making-illegal-states-unrepresentable/ → mine: practical recipes — replace primitives with domain types, sum types for state machines, encode optionality explicitly.
- **Martin Fowler — "Primitive Obsession" smell** → mine: stringly-typed/primitive fields that should be domain types (`Email`, `Money`, `UserId`, `Percentage`) carrying invariants and units.
- **Hillel Wayne — type-driven design / lightweight formal methods** `(verify)` → mine: types as cheap proofs; let the compiler check invariants you'd otherwise test.

### Tooling rules worth lifting
- **TypeScript** `strict` (`strictNullChecks`, `noImplicitAny`); **typescript-eslint** `strict-boolean-expressions`, `no-unnecessary-condition`, `switch-exhaustiveness-check` (compiler-checked exhaustive unions), `no-non-null-assertion` (no `!` papering over null).
- **Python** — `mypy --strict` / **pyright** strict; **Pydantic** (runtime parse-into-type at boundaries); `typing.NewType`, `Literal`, `Enum`, frozen dataclasses for value objects.
- **Rust** — newtype pattern, `#[non_exhaustive]`, exhaustive `match`, clippy.
- *Note:* "primitive obsession" itself is weakly tooled → largely a judgment heuristic (map-gaps G5).

### Reviewable heuristics (skill-checklist seeds)
- Are **invalid states representable**? Could you construct a value the domain forbids (an order both `draft` and `shipped`)? Model with a tagged union / state machine instead.
- Is untrusted input **parsed into a precise type at the boundary** (parse-don't-validate), or validated then passed onward as raw primitives (re-validatable downstream)?
- **Primitive obsession**: are domain concepts (email, money, id, %) raw `string`/`number`, or wrapped in domain types carrying invariants/units (cross #4)?
- Are optional/nullable fields modeled explicitly (`Option`/`Maybe`/`| null`) rather than sentinel values (`-1`, `""`)?
- Are unions/enums **exhaustively** handled (compiler-checked)?
- Do (smart) constructors enforce invariants so an invalid instance can't exist?
- Is `null`/`undefined` controlled (`strictNullChecks` on; no non-null assertions)?
- Are mutually-exclusive nullable fields collapsed into a tagged union?
- Do the **types and the persistence schema agree** on constraints (cross #20)?

---

## #11 Abstraction & simplicity  *(counterweight category)*

### Key references
- **Sandi Metz — "The Wrong Abstraction" (2016)** — https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction → mine: **"duplication is far cheaper than the wrong abstraction."** When an abstraction is proven wrong (callers keep adding flags/conditionals), the fastest way forward is *back*: re-inline into callers and let the right abstraction emerge. The premier counterweight.
- **Kent C. Dodds — "AHA Programming" (Avoid Hasty Abstractions)** — https://kentcdodds.com/blog/aha-programming → mine: don't abstract impulsively; prefer some duplication until the shared shape is clear; thoughtful > hasty.
- **Martin Fowler — "Rule of Three" (*Refactoring*) + "Yagni"** — https://martinfowler.com/bliki/Yagni.html → mine: extract on the **third** occurrence; don't build speculative generality you may never need (or that won't match the real need).
- **John Ousterhout — *A Philosophy of Software Design*** → mine: "different layer, different abstraction"; pass-through methods and shallow wrappers *add* complexity rather than hide it.
- **Moseley & Marks — "Out of the Tar Pit"** (cross #1) → mine: minimize state and accidental complexity; the simplest design that works.

### Tooling rules worth lifting
- **Duplication detectors:** jscpd (Rabin-Karp, 150+ languages, pmd-cpd report format), PMD **CPD**, SonarQube **`S4144`** (methods should not have identical implementations) + duplication-density, Simian. *Caveat:* these find duplication, but the counterweight says **not all duplication should be DRY'd** — coincidental duplication that evolves separately should stay duplicated.
- **Dead/unused-code:** knip, ts-prune, Vulture (Python), staticcheck `U1000`, RuboCop `Lint/UselessAssignment` — find speculative/unused abstractions and config.
- *Over-abstraction itself is largely un-tooled* → an LLM-judgment heuristic (map-gaps G5).

### Reviewable heuristics (skill-checklist seeds)
- Is this abstraction introduced on **real, repeated need** (rule of three), or speculatively for one/two uses (YAGNI)?
- Does it have a single, nameable responsibility — or is it a grab-bag taking flags/conditionals to fit multiple callers (the **wrong-abstraction** smell)?
- Is there an **existing** abstraction this duplicates/competes with (reuse/extend it, don't fork — cross #8)?
- Would **inlining** make the code clearer? If the abstraction fights its callers, recommend re-inlining.
- Is the indirection earning its keep, or a **shallow wrapper** that just adds a layer to read through (Ousterhout)?
- Any **speculative generality**: config options, plugin hooks, "just in case" parameters with a single caller? Remove.
- Is the duplication here actually **coincidental** (looks the same, will evolve differently)? If so, leave it duplicated.
- **Counterweight discipline:** am I recommending an abstraction the evidence doesn't yet justify? Default to "duplicate once more, then extract."

---

## #12 System architecture

### Key references
- **Robert C. Martin — *Clean Architecture* / The Dependency Rule + Acyclic Dependencies Principle** → mine: source dependencies point inward toward policy; **no cycles** between components. (Treat the dogma critically; mine the dependency-direction and ADP checks.)
- **Mark Richards & Neal Ford — *Fundamentals of Software Architecture*** → mine: architecture *characteristics* (the "-ilities") as first-class, architecture quanta, and the menu of styles with their explicit trade-offs.
- **Neal Ford, Rebecca Parsons, Patrick Kua — *Building Evolutionary Architectures*** → mine: **fitness functions** — automated, objective checks that the architecture still holds ("domain imports no infra", "no package cycles"). Directly inspires architecture-as-test behavior.
- **Foote & Yoder — "Big Ball of Mud"** → mine: the canonical anti-pattern to detect — no discernible structure, everything coupled.
- **Eric Evans — *DDD* (bounded contexts, context mapping)** → mine: module/service boundaries follow **domain** boundaries; cross-context integration via explicit contracts, never shared internals.

### Tooling rules worth lifting
- **dependency-cruiser, madge `--circular`** (JS/TS), **import-linter** layers/independence contracts (Python), **ArchUnit** (Java), **NetArchTest** (.NET), **pydeps**, **jdepend** — enforce layering, detect cycles, god modules, fan-in/out.
- **`@nx/enforce-module-boundaries`** (Nx) / Turborepo boundaries — monorepo module-boundary tags.
- **SonarQube** — cyclic-dependency / package-tangle measures.

### Reviewable heuristics (skill-checklist seeds)
- Do source dependencies respect the **intended direction** (domain doesn't import infrastructure; UI→app→domain, not back)?
- Any **dependency cycles** between modules/packages/services (ADP)?
- Is there a **god module / hub** with huge fan-in *and* fan-out that everything routes through?
- Does the change honor existing layer/boundary contracts, or smuggle a cross-layer import?
- Could the intended rule be expressed as a **fitness function** (an ArchUnit/import-linter check)? If a rule is repeatedly violated, the boundary is wrong or unclear.
- New cross-service/cross-context coupling via an **explicit contract** (API/event), not a shared DB or internal reach-in?
- Is the architecture style **consistent** with the rest of the system (not a competing pattern bolted on)?
- Does it scale along the expected axis (data volume, traffic, team size), or bake in a single-node assumption (cross #3, #15)?
- Backward/forward-compatibility plan for the boundary change (cross #13)?
- Feature-flag/config architecture: are flags scoped and removable (lifecycle — cross #26)?

---

## #13 API & contract design

### Key references
- **Joshua Bloch — "How to Design a Good API and Why It Matters" (2006)** — https://research.google.com/pubs/archive/32713.pdf → mine: easy to use & hard to misuse; "when in doubt, leave it out" (you can add later, can't remove); minimize accessibility/mutability; don't let implementation leak into the API.
- **Jon Postel — Robustness Principle** ("be conservative in what you send, liberal in what you accept") → mine: a **contested** principle — liberal acceptance can entrench bugs and ambiguity; modern guidance is "be conservative in what you *accept* too." Carry the nuance into review (cross #2).
- **Leonard Richardson — Richardson Maturity Model** (via Fowler) — https://martinfowler.com/articles/richardsonMaturityModel.html → mine: levels of REST maturity (resources → verbs+status codes → hypermedia) as a consistency yardstick.
- **Semantic Versioning — semver.org** → mine: communicate breaking vs. additive vs. fix via version; the social contract for change.
- **Consumer-Driven Contracts / Pact** — https://docs.pact.io/ → mine: verify the provider against *real consumer expectations*; only the parts consumers actually use get tested.

### Tooling rules worth lifting
- **Spectral** (Stoplight) — lint OpenAPI/AsyncAPI against a style guide (naming, required fields, consistency). (https://stoplight.io/open-source/spectral)
- **oasdiff** — OpenAPI **breaking-change detection** (470+ change types) + diff; CLI + GitHub Action. (https://www.oasdiff.com/)
- **buf** — Protobuf breaking-change detection (`WIRE`, `WIRE_JSON`, `PACKAGE`, `FILE` categories) + lint. (https://buf.build/docs/breaking/)
- **Pact / Pactflow** — consumer-driven contract tests across the consumer-provider boundary.
- **GraphQL** — graphql-inspector (schema breaking changes), graphql-schema-linter.
- **Google api-linter** (AIP rules) for gRPC/REST conventions.

### Reviewable heuristics (skill-checklist seeds)
- Is the change to a public contract **backward-compatible**? If breaking, is it versioned and communicated (semver, deprecation window)?
- Is the API **easy to use, hard to misuse**? Required things required by the type; invalid combinations impossible; sensible defaults.
- **"When in doubt, leave it out":** any field/endpoint/param being added that isn't clearly needed? (You can add later; you can't remove.)
- **Consistent** with the rest of the surface (naming, pluralization, error shape, pagination, status codes, casing — cross #8)?
- Are **errors part of the contract** — typed, documented, stable codes — not ad-hoc strings?
- **Idempotency**: are unsafe operations idempotent or protected by idempotency keys (cross #3)?
- Pagination, rate limits, filtering defined for collection endpoints?
- Is there a **contract test** (Pact/schema) guarding the consumer-provider boundary?
- Does the response avoid leaking internal representation (implementation bleed)?
- **Robustness nuance**: are we appropriately *strict in what we accept* (not silently coercing bad input — cross #2)?

---

## Open threads

- **#9 ↔ #11 ↔ #6 are one design cluster** (cohesion/coupling, abstraction restraint, function decomposition). A single "design altitude / decomposition" stance is needed so these skills don't contradict (map-gaps G3).
- **Connascence as the suite's shared coupling vocabulary.** Its 9-type / strength-degree-locality model gives precise, teachable language for *every* "this is too coupled" finding across #9/#11/#12 — worth adopting suite-wide rather than vague "high coupling."
- **#10 types ↔ #20 schema**: domain types and DB/API constraints should be a single source of truth; divergence is a defect class. Who owns the check?
- **#12 fitness functions ↔ #19 CI**: architecture tests (ArchUnit/import-linter) run *in CI*. Is "architecture conformance" a review skill, a CI gate, or both?
- **Over-abstraction (#11) and pattern-violation (#12) are weakly tooled** → high-value LLM-judgment territory (map-gaps G5). Duplication detectors help #11 only in the "too little DRY" direction; the counterweight (too much) needs judgment.
- **Internal (#9) vs external (#13) API**: v0.2 folded caller-ergonomics into #9; the seam is "who's the consumer" (next engineer vs. external client). Keep the split explicit so findings route correctly.
