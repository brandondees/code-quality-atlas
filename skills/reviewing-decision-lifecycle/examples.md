# Examples — reviewing-decision-lifecycle

This lens reviews a **decision** (ADR / RFC / adoption PR / deprecation plan), not a diff. Findings point at the *reasoning and its record*, not at lines of code. Match this output shape.

## Bad → finding

**Input (adoption PR):** "Add a GraphQL gateway in front of our 4 REST services. Rationale: 'modern API.' No ADR; no comparison to keeping REST or to a thin BFF; nothing on how we'd remove the gateway if it doesn't pay off."

**Finding:**
> **Major — unjustified adoption, no exit.** The rationale ("modern API") names no problem the gateway solves that the current REST surface can't, and no alternative was weighed (keep REST / a thin BFF / schema-stitching). A gateway is a one-way-ish door — it becomes load-bearing for every client. Record an ADR with the options considered and the consequences, and state the exit path (can clients fall back to the REST services?). Until there's a concrete problem it solves, prefer not adopting it (restraint).

## Bad → finding (stale decision on revisit)

**Input (ADR review):** "ADR-4 (2022, accepted): 'Vendor X for search; assumes < 1M documents, English-only.' Today: 40M documents, 9 locales, query latency p95 2.3s."

**Finding:**
> **Major — decision assumptions expired.** ADR-4 explicitly rests on "< 1M documents, English-only"; both premises are now false (40M docs, 9 locales), and latency confirms it. This is stale debt, not a wrong original call. Supersede ADR-4 with a new decision sized for current scale, and add a revisit-trigger (e.g. "re-evaluate at 10× document growth or any new locale tier") so the next drift is caught on time.

## Good → "No findings"

**Input (deprecation plan):** v1 marked `deprecated: true`, `Sunset` header dated, migration guide published, top consumers contacted, removal ticket tracked, changelog updated.

**Finding:**
> **No findings.** Retirement is planned and clocked — sunset date, migration path, tracked removal, and a changelog entry are all present. Nothing to add.

## Output format

- **Severity** (Blocker / Major / Minor / Nit) — **the decision/record location** (ADR-N, the RFC section, the proposal) — what's missing or unsound in the *reasoning*, concretely — the fix (record the rationale / weigh option Y / add a revisit-trigger / state the exit), **or** the evidence needed to decide.
- For decisions that are genuinely sound and well-recorded, say **"No findings"** — do not manufacture process for a cheap, reversible, well-signaled call.
- Business calls (TCO, procurement, contract terms) are **escalated to humans**, not adjudicated here.
