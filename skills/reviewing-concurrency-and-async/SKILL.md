---
name: reviewing-concurrency-and-async
description: 'Reviews concurrent and async code for races and ordering bugs: shared
  mutable state without synchronization, check-then-act spanning an await, lost updates
  from interleaved requests, lock ordering, unawaited promises, accidental sequential
  awaits, non-idempotent message consumers, exactly-once assumptions, and missing
  cancellation/timeout propagation. Use when reviewing threads, async/await, promises,
  locks, queues, message handlers, or anything two callers can run at once. Skip when
  the code is single-threaded and synchronous with no shared mutable state, async/await,
  or message handling — nothing two callers race on.'
provenance:
  taxonomy_version: v0.4
  built_from:
  - category: 3
    source: docs/research/cluster-1-correctness.md#3
    hash: c9755d9b409479e2fac960b39449dc1eaaf0f98e8bbe01fd2758ad97a6bd7ba5
---

# reviewing-concurrency-and-async

*What breaks when two run at once? Races, lost updates, unawaited promises, idempotency.*

## When to use

Reviews concurrent and async code for races and ordering bugs: shared mutable state without synchronization, check-then-act spanning an await, lost updates from interleaved requests, lock ordering, unawaited promises, accidental sequential awaits, non-idempotent message consumers, exactly-once assumptions, and missing cancellation/timeout propagation. Use when reviewing threads, async/await, promises, locks, queues, message handlers, or anything two callers can run at once. Skip when the code is single-threaded and synchronous with no shared mutable state, async/await, or message handling — nothing two callers race on.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is shared mutable state touched by multiple threads/tasks without synchronization?
- Any check-then-act / read-modify-write that spans an `await`/`yield` and isn't atomic?
- Could two concurrent requests interleave to break an invariant (lost update, double-spend)?
- Are locks acquired in a consistent global order, with minimal scope (deadlock avoidance)?
- Are all promises awaited/handled, and is concurrency *intentional* (`Promise.all`) vs. accidental sequential?
- For message consumers: is processing **idempotent** and keyed on a stable id (at-least-once-safe)?
- Does the code assume wall-clock ordering across nodes/processes (clock skew)?
- Does it assume **exactly-once delivery** (it doesn't exist — needs dedupe)?

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
