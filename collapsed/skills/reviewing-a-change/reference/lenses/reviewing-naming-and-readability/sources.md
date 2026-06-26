# References to mine — reviewing-naming-and-readability

## Contents

- From category #5
- From category #6
- From category #7

## From category #5

### Key references

- **Arlo Belshee — "Good Naming Is a Process, Not a Single Step" / "Naming is a Process" series** — https://arlobelshee.com/good-naming-is-a-process-not-a-single-step/ → mine: names improve in **stages**, not one leap — you don't need the perfect name to make progress. The 7 stages: **Missing → Nonsense → Honest → Honest-and-Complete → Does-the-Right-Thing → Intent → Domain Abstraction** (final stage: ["Intent to Domain Abstraction"](https://arlobelshee.com/naming-is-a-process-part-7-intent-to-domain-abstraction/)). Key insight to lift: *dishonest* names (look meaningful, aren't) are more dangerous than honest-nonsense ones; the reviewer behavior is "identify the stage, nudge it one stage better," not "demand perfection."
- **Robert C. Martin — *Clean Code*, ch. 2 "Meaningful Names"** → mine: intention-revealing names; avoid disinformation; meaningful distinctions (no `a1`/`a2`, no noise words `Info`/`Data`/`Manager`); pronounceable & searchable; class = noun, method = verb. Mine the *checks*, treat as heuristics not law.
- **Eric Evans — *Domain-Driven Design* (Ubiquitous Language)** + **Vaughn Vernon — *Implementing DDD*** → mine: names should come from the domain's shared vocabulary; a mismatch between code names and domain-expert language is itself a defect.
- **Steve McConnell — *Code Complete* (2nd ed.), ch. 11 "The Power of Variable Names"** → mine: name length scales with scope; name to the *problem* not the solution; consistent antonym pairs (`begin`/`end`, `first`/`last`); avoid numerically-suffixed series.
- **Phil Karlton — "two hard things: cache invalidation and naming things"** (widely attributed) → mine: a cultural anchor that naming deserves explicit review attention. (Folklore-level attribution; cite as such.)
- **Felienne Hermans — *The Programmer's Brain*** → mine: cognitive-science backing — good names reduce working-memory load; naming is a *comprehension* lever, not mere style.

## From category #6

### Key references

- **G. Ann Campbell / SonarSource — "Cognitive Complexity: A new way of measuring understandability" (white paper)** → mine: the metric powering modern linters. Rules: (1) **ignore** structures that read multiple statements as one; (2) **+1** for each break in linear flow (`if`/`else if`/`else`, ternary, `switch`, loops, `catch`, mixed boolean-operator sequences, labelled break/continue); (3) **increment more for nesting** — deeper nesting costs more. A flat `switch` scores low, nested conditionals score high — closer to *felt* difficulty than cyclomatic. **Sonar default "too complex" threshold = 15** (rule S3776).
- **Thomas J. McCabe — "A Complexity Measure" (1976)** → mine: cyclomatic complexity = linearly-independent paths (≈ decision points + 1); a *lower bound on test cases needed*. Common bands: 1–10 simple … >50 untestable `(verify exact bands)`.
- **Robert C. Martin — *Clean Code*, ch. 3 "Functions"** → mine: small functions, "do one thing," single level of abstraction (the **altitude** rule), few arguments (0–2), no flag arguments, no side-effect surprises. Mine the *checks*, push back on the dogmatic "4 lines."
- **John Ousterhout — *A Philosophy of Software Design*** → mine: complexity accumulates from *dependencies* and *obscurity*; "deep modules" (simple interface, substantial behavior) over many shallow ones. **Counterweight** to Clean Code's "lots of tiny functions" — central to not over-splitting (see map-gaps G3).
- **Martin Fowler — *Refactoring* (2nd ed.)** → mine: the smell→refactoring names a review should suggest — *Long Function*, *Long Parameter List*, *Magic Number* → Replace Magic Literal with Symbolic Constant, *Nested Conditional* → Replace Nested Conditional with Guard Clauses (the **early-return** move), Decompose Conditional, Extract Function.
- **Kent Beck — *Tidy First?*** → mine: small, safe, local tidyings (guard clauses, explaining variables, dead-code removal, reorder for reading order, normalize symmetries) and *when* they pay off; the **symmetry** idea — express parallel things in parallel form — is explicit here.
- **Linux kernel CodingStyle — "if you need more than 3 levels of indentation, you're screwed"** → mine: a blunt real heuristic that nesting depth ≈ complexity.

## From category #7

### Key references

- **Robert C. Martin — *Clean Code*, ch. 4 "Comments"** → mine: "comments don't make up for bad code"; *good* comments (intent, warning of consequences, TODO, legal, amplification, public-API docs) vs. *bad* (redundant, misleading, mandated noise, commented-out code, journal/attribution now in VCS). The "explain *why*, not *what*" thesis operationalized.
- **"Comments should say WHY, not WHAT"** (community canon; *Pragmatic Programmer*, McConnell, Coding Horror) → mine: the *what* is the code's job; comments earn their keep capturing intent, rationale, constraints, road-not-taken.
- **Andrew Hunt & David Thomas — *The Pragmatic Programmer*** → mine: DRY applies to comments — a comment duplicating code is a second source of truth that *will* drift; prefer self-documenting code, reserve comments for the non-obvious *why*.
- **Steve McConnell — *Code Complete*, ch. 32 "Self-Documenting Code"** → mine: taxonomy of comment kinds; good comments operate at the level of *intent*; comments are first-class code to maintain.
- **Comment–code inconsistency / "comment rot" research** (specific authors/venues `(verify)`) → mine: comments drift from code measurably; stale `@param`/`@return`/docstrings are a real, detectable defect class. Motivates "doc mentions a param/return that no longer exists" checks.
- **Docstring conventions — PEP 257, JSDoc, Javadoc, rustdoc, KDoc** → mine: what "complete" looks like per ecosystem (summary, params, returns, raises, examples) so a reviewer can judge *completeness & accuracy*.
