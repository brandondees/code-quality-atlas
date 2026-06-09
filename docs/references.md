# References

The active research surface. Organized to mirror [`taxonomy.md`](taxonomy.md). This is a **living document** — seeded below with foundational works so we have anchors; the work of phase 1 is to keep filing references, heuristics, checklists, and tool capabilities against the right cluster.

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
- **TODO** error-handling taxonomies (fail-fast vs. fail-safe; the "silent failure" anti-pattern literature).
- **TODO** concurrency: *Java Concurrency in Practice* (Goetz) for the happens-before/atomicity vocabulary (#3); "Nondeterminism in async UIs" sources for frontend races.
- **TODO** idempotency & exactly-once myths (#4).

## Cluster II — Readability & Clarity

- **Arlo Belshee — naming-as-process / "Naming is a Process"** — the progression from nonsense → honest → complete → does-the-right-thing names (#5).
- **TODO** cognitive-complexity rationale (the metric behind modern linters) (#6).
- **TODO** "comments should say *why*" canon; comment-rot studies (#7).
- **TODO** idiom/consistency: language-specific style guides as heuristic sources (#8).

## Cluster III — Structure & Architecture

- **Alexis King — "Parse, Don't Validate"** — the type-modeling north star (#10).
- **Yaron Minsky — "Make Illegal States Unrepresentable"** — same idea, OCaml lineage (#10).
- **TODO** connascence (Page-Jones) as a finer-grained coupling vocabulary than "coupling/cohesion" (#9, #11).
- **TODO** "the wrong abstraction" (Sandi Metz) — the canonical premature-abstraction counterweight (#11).
- **TODO** evolutionary architecture / fitness functions (Ford, Parsons, Kua) (#12).
- **TODO** API design: *The Design of Web APIs* (Lauret); Joshua Bloch "How to Design a Good API" (#13).

## Cluster IV — Cross-cutting runtime qualities

- **OWASP Top 10** + **OWASP ASVS** (`owasp.org`) — the security checklist backbone (#14).
- **TODO** CWE Top 25; Semgrep rule rationale as heuristic source (#14).
- **TODO** Brendan Gregg — systems performance; "USE method" (#15).
- **TODO** caching: "there are only two hard things…" / invalidation literature (#15).
- **Charity Majors et al. — *Observability Engineering*** — logs/metrics/traces, high-cardinality (#16).

## Cluster V — Verification & Supply

- **TODO** test-pyramid (Cohn) vs. testing-trophy (Dodds); their tradeoffs (#17).
- **TODO** property-based testing (Hughes, *QuickCheck*); fuzzing intros (#17).
- **TODO** mutation testing as a coverage-quality signal (#17).
- **TODO** supply-chain: SLSA framework; lockfile/repro-build practices (#18).
- **TODO** *Continuous Delivery* (Humble & Farley); hermetic builds (#19).
- **TODO** zero-downtime migrations (expand/contract pattern); "online schema change" writeups (#20).

## Cluster VI — Evolution & humans

- **The Twelve-Factor App** (`12factor.net`) — config, parity, disposability (#16, #21, candidate: config mgmt).
- **TODO** tech-debt accounting (Fowler's debt quadrant) (#21).
- **TODO** ADRs (Michael Nygard, "Documenting Architecture Decisions") (#22).
- **Diátaxis** (`diataxis.fr`) — docs taxonomy: tutorials/how-to/reference/explanation (#22).
- **WCAG 2.2** + **ARIA Authoring Practices** (`w3.org`) (#23).
- **TODO** conventional commits; commit-as-communication / risk-signaling notation (#24).

---

> Filing discipline: when a reference clearly serves a category, drop it under that cluster with a "what we'd mine" note. When it's whole-suite, put it in *Foundational*. Don't let URLs rot — prefer author/title when unsure.
