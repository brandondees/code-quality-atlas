# References

The active research surface. Organized to mirror [`taxonomy.md`](taxonomy.md). This is a **living document** — seeded below with foundational works so we have anchors; the work of phase 1 is to keep filing references, heuristics, checklists, and tool capabilities against the right cluster.

> **Status note (2026-06-12):** the per-cluster files under [`research/`](research/) are now the deep, web-verified reference surface — most `TODO`s below were fulfilled there (Goetz, connascence, the-wrong-abstraction, SLSA, expand/contract, ADRs, Conventional Commits, …). This file stays as the curated *shortlist*: foundational works plus the cross-cutting anchors. New references land in the cluster files first.

Conventions:

- Cite **author — title** at minimum. Add a URL only when stable and known.
- Tag each with a one-line note on *what we'd mine from it*.
- Tool/linter capabilities go in [`prior-art.md`](prior-art.md), not here; this file is for ideas, principles, and heuristics.

---

## Foundational / cross-cutting

These span most of the map and are worth reading as whole-suite influences.

- **Robert C. Martin — *Clean Code*** — granular smells & heuristics; controversial in places (good for a critical, not reverential, mining).
- **John Ousterhout — *A Philosophy of Software Design*** — deep modules, complexity as the enemy, "define errors out of existence." Strong on #9, #11.
- **Martin Fowler — *Refactoring* (2nd ed.)** — the catalog of smells ↔ refactorings; backbone for the maintenance half of the suite.
- **Kent Beck — *Tidy First?*** — small structural changes, the economics of refactoring; coupling/cohesion framing.
- **Andrew Hunt & David Thomas — *The Pragmatic Programmer*** — broad heuristics (DRY, orthogonality, tracer bullets).
- **Steve McConnell — *Code Complete*** — encyclopedic construction practices.
- **Michael Feathers — *Working Effectively with Legacy Code*** — seams, testability, characterization tests. Core to #17, #21.
- **Eric Evans — *Domain-Driven Design*** + **Vaughn Vernon — *Implementing DDD*** — domain language (#5), boundaries (#9, #12).
- **Google — Engineering Practices / Code Review Developer Guide** (`google.github.io/eng-practices/`) — what to look for, the "CL author" and "reviewer" guides; a model for review-skill behavior.
- **Nicole Forsgren, Jez Humble, Gene Kim — *Accelerate*** (DORA) — outcome metrics that quality should serve (#19, #21).
- **SOLID** (Martin) and its critiques — useful as a checklist *and* as something to push back on (#9).
- **Anthropic — "Agent Skills: best practices"** (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) → mine: the authoring contract for the whole suite — progressive disclosure (lean SKILL.md <500 lines + one-level-deep bundled files, ToC on >100-line files), description-writing for auto-trigger (third person, specific, trigger keywords), degrees-of-freedom matching, eval-first development, and testing across models. Drives D7/D8.

---

## Cluster I — Correctness & Robustness

- *(seed)* **John Regehr — "A Guide to Undefined Behavior"** & embedded-systems writing — boundary/UB intuition (#1).
- *(seed)* **Nancy Leveson — *Engineering a Safer World*** — systems-thinking on failure, partial failure (#2).
- Error-handling taxonomies (fail-fast vs. fail-safe; the "silent failure" anti-pattern literature) (#2). *(done in cluster-1: Nygard's* Release It! *Stability Patterns & Antipatterns, Duffy's "The Error Model," the Go Blog's "Error handling and Go," ISO/IEC 25010:2023 safety/fail-safe defaults.)*
- Concurrency: happens-before/atomicity vocabulary; frontend-race sources (#3). *(done in cluster-1: Goetz —* Java Concurrency in Practice*, Lamport — "Time, Clocks, and the Ordering of Events," Julik Tarkhanov's frontend-race reviews.)*
- Idempotency & exactly-once myths (#4). *(done in cluster-1: Kleppmann —* Designing Data-Intensive Applications *("exactly-once" reframed as idempotency), the Idempotent Consumer pattern.)*

## Cluster II — Readability & Clarity

- **Arlo Belshee — naming-as-process / "Naming is a Process"** — the progression from nonsense → honest → complete → does-the-right-thing names (#5).
- Cognitive-complexity rationale (the metric behind modern linters) (#6). *(done in cluster-2: Campbell/SonarSource — "Cognitive Complexity: A new way of measuring understandability" (SonarQube `S3776`, default threshold 15).)*
- "Comments should say *why*" canon; comment-rot studies (#7). *(done in cluster-2: Martin —* Clean Code *ch. 4; the "comments should say WHY, not WHAT" community canon; McConnell —* Code Complete *ch. 32; comment–code inconsistency research, mechanized by Ruff `ERA001`/`D417`, `eslint-plugin-jsdoc`.)*
- Idiom/consistency: language-specific style guides as heuristic sources (#8). *(done in cluster-2: PEP 8, Google Style Guides, Airbnb JavaScript, Effective Go / Go Code Review Comments, Rust API Guidelines, Ruby Style Guide.)*

## Cluster III — Structure & Architecture

- **Alexis King — "Parse, Don't Validate"** — the type-modeling north star (#10).
- **Yaron Minsky — "Make Illegal States Unrepresentable"** — same idea, OCaml lineage (#10).
- Connascence (Page-Jones) as a finer-grained coupling vocabulary than "coupling/cohesion" (#9, #11). *(done in cluster-3: Page-Jones — Connascence (connascence.io) — nine types, evaluated by strength/degree/locality; adopted suite-wide.)*
- "The wrong abstraction" (Sandi Metz) — the canonical premature-abstraction counterweight (#11). *(done in cluster-3: Sandi Metz — "The Wrong Abstraction" (2016) — "duplication is far cheaper than the wrong abstraction.")*
- Evolutionary architecture / fitness functions (Ford, Parsons, Kua) (#12). *(done in cluster-3: Ford, Parsons, Kua —* Building Evolutionary Architectures *— automated fitness functions as architecture-as-test.)*
- API design (#13). *(done in cluster-3: Joshua Bloch — "How to Design a Good API and Why It Matters" (2006) — easy to use/hard to misuse, minimize mutability, "when in doubt, leave it out.")*

## Cluster IV — Cross-cutting runtime qualities

- **OWASP Top 10** + **OWASP ASVS** (`owasp.org`) — the security checklist backbone (#14).
- CWE Top 25; Semgrep rule rationale as heuristic source (#14). *(done in cluster-4: MITRE — CWE Top 25 Most Dangerous Software Weaknesses (2024); Semgrep taint-flow rules; gosec CWE mappings.)*
- Brendan Gregg — systems performance; "USE method" (#15). *(done in cluster-4: Gregg — Systems Performance / the USE method (utilization, saturation, errors) and Flame Graphs — "profile, don't guess.")*
- Caching: "there are only two hard things…" / invalidation literature (#15). *(done in cluster-4: caching-correctness heuristics — invalidation story, key construction; RFC 9110/9111 HTTP caching semantics.)*
- **Charity Majors et al. — *Observability Engineering*** — logs/metrics/traces, high-cardinality (#16).
- **OWASP — Top 10 for Agentic Applications (2026)** (`genai.owasp.org`) — the agentic-risk spine (goal hijack, tool misuse, privilege abuse, memory poisoning, rogue agents); with the LLM Top 10, the two-list backbone of #25 (and Q16).
- **Model Context Protocol — security best practices** (`modelcontextprotocol.io`) — confused deputy, token passthrough, tool poisoning — the tool-integration anti-pattern catalog (#25, #14).

## Cluster V — Verification & Supply

- Test-pyramid (Cohn) vs. testing-trophy (Dodds); their tradeoffs (#17). *(done in cluster-5: Cohn —* Succeeding with Agile *(the Test Pyramid); Dodds — "The Testing Trophy" (2018), building on Rauch — "Write tests. Not too many. Mostly integration."*)*
- Property-based testing (Hughes, *QuickCheck*); fuzzing intros (#17). *(done in cluster-5: Claessen & Hughes — "QuickCheck: Lightweight Tools for Random Testing of Haskell Programs" (ICFP 2000) — generators + properties + shrinking, ported as Hypothesis/fast-check/jqwik.)*
- Mutation testing as a coverage-quality signal (#17). *(done in cluster-5: PIT, Stryker, mutmut, cargo-mutants — does the suite catch injected bugs; high coverage + low mutation score = weak assertions.)*
- Supply-chain: SLSA framework; lockfile/repro-build practices (#18). *(done in cluster-5: SLSA — Supply-chain Levels for Software Artifacts (OpenSSF) — the build-integrity ladder, L1–L3.)*
- *Continuous Delivery* (Humble & Farley); hermetic builds (#19). *(done in cluster-5: Humble & Farley —* Continuous Delivery *— build once, promote the same artifact; Forsgren/Humble/Kim —* Accelerate */DORA four key metrics.)*
- Zero-downtime migrations (expand/contract pattern); "online schema change" writeups (#20). *(done in cluster-5: Fowler — "Parallel Change" (expand/contract); gh-ost, pt-online-schema-change, pgroll online schema-change tools.)*

## Cluster VI — Evolution & humans

- **The Twelve-Factor App** (`12factor.net`) — config, parity, disposability (#16, #21, candidate: config mgmt).
- Tech-debt accounting (Fowler's debt quadrant) (#21). *(done in cluster-6: Fowler — "Technical Debt Quadrant" — deliberate+prudent debt is OK if recorded; reject silent/untracked debt.)*
- ADRs (Michael Nygard, "Documenting Architecture Decisions") (#22). *(done in cluster-6: Nygard — "Documenting Architecture Decisions" (2011) — context · decision · status · consequences.)*
- **Diátaxis** (`diataxis.fr`) — docs taxonomy: tutorials/how-to/reference/explanation (#22).
- **WCAG 2.2** + **ARIA Authoring Practices** (`w3.org`) (#23).
- Conventional commits; commit-as-communication / risk-signaling notation (#24). *(done in cluster-6: Conventional Commits 1.0.0, commitlint, Beams.)*
- **AGENTS.md** (`agents.md`, Agentic AI Foundation / Linux Foundation) — agent-facing repo instructions as a first-class doc artifact (#22, #24).

---

> Filing discipline: when a reference clearly serves a category, drop it under that cluster with a "what we'd mine" note. When it's whole-suite, put it in *Foundational*. Don't let URLs rot — prefer author/title when unsure.
