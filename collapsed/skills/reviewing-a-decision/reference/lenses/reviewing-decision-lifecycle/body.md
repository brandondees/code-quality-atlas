# reviewing-decision-lifecycle

Is this decision sound and recorded? Adoption justification, lock-in/exit, ADR assumptions, revisit-triggers, planned retirement.

## When to use

**Shape: decision.** Reviewed at decision time — an ADR, RFC, design doc, adoption PR, or deprecation/rollout plan — not a diff of implementation code. Apply the checks to the decision and its record (rationale, assumptions, alternatives, exit/rollback), not to lines of code.

## Checklist

## From category #29

### Reviewable heuristics (skill-checklist seeds)

- **Adoption justification recorded:** for a new dependency / framework / platform, is there a rationale weighed against the cheaper options (stdlib, a few lines, an existing in-house capability, a smaller library)? "We need X" is not a justification; an evaluated A/B/build comparison is.
- **Right-sizing (build-vs-buy):** does the chosen option's weight match the need? A 40-dependency framework for one screen, or a hand-rolled implementation where a maintained library exists, both warrant a second look (cross #11 restraint, #18 deps).
- **Lock-in & exit cost assessed:** is the cost of *leaving* considered — is data exportable, is the integration behind a portable boundary/adapter, or is this a one-way door into proprietary surface that's expensive to reverse?
- **Reversibility matched to scrutiny:** is this a two-way door (cheap to undo → decide fast) or a one-way door (expensive to undo → demand a recorded decision and an exit plan)? Flag heavy process on trivial reversible calls, and casual adoption of irreversible ones.
- **Decision record present & complete:** for a non-obvious choice, is there an ADR capturing context, options considered, decision, and consequences — the *why*, not just the *what*?
- **Assumptions stated and still valid:** does the decision name the assumptions it rests on (load, team size, vendor support, scale)? On revisit, do they still hold — or has a premise expired, making the decision stale debt?
- **Revisit-triggers named:** does the record state the conditions that should reopen it ("revisit if write volume > 10k/s"; "if the vendor drops Kafka")? A decision with no trigger rots silently.
- **Retirement planned on a schedule:** when something is deprecated, is removal *planned and clocked* — a `Deprecation`/`Sunset` header or `deprecated` marker, a sunset date, a consumer-migration path, and a tracked removal ticket — rather than left to surface later as dead code (cross #1, #13)?
- **Vendor adopt/exit symmetry:** does adopting a managed service / SaaS / model API record how we'd migrate off (second source, abstraction seam), so it isn't silently irreplaceable?
- **Escalate the governance slice:** build-vs-buy *TCO*, procurement, and contract terms are business calls — surface them with evidence and **escalate to humans**; detect and flag, don't adjudicate (cross #27, the G8 boundary).

---

## Examples

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

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
