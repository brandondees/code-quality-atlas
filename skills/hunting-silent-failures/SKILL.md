---
name: hunting-silent-failures
description: Reviews changes for swallowed or silently-handled errors — empty catch/rescue
  blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad
  exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers.
  Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience,
  timeouts, or resource cleanup on failure paths.
provenance:
  taxonomy_version: v0.6
  built_from:
  - category: 2
    source: docs/research/cluster-1-correctness.md#2
    hash: f3544ba46872ca9fb6eadfeb5d13f6f8cb22edc9036229c26c1e3eb2b13480c4
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 63ae9d27a00a6a9575d63c6bc8a91c2d785f7d0ba313fd9416e3f61f8f730043
---

# hunting-silent-failures

*Where do errors vanish? Swallowed exceptions, silent fallbacks, missing timeouts and retries.*

## When to use

Reviews changes for swallowed or silently-handled errors — empty catch/rescue blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers. Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience, timeouts, or resource cleanup on failure paths.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Root cause vs. band-aid (esp. bug fixes):** does the fix resolve the underlying cause, or paper over a symptom — catch-and-ignore the error, special-case the one bad input, retry a flaky call, bump a timeout, drop a null guard at the crash site? A symptom-level patch that leaves the cause live is a finding even when it makes the reported case pass; ask what *produced* the bad state (5-whys) and whether this change addresses that level, not just the visible failure.
- Is any error swallowed — empty catch/`rescue`, `except: pass`, ignored Go `err`, discarded Result?
- Does each handler narrow to the *expected* exception type, not a blanket catch-all?
- On failure does it **fail loud** (surface + log with context) or **degrade intentionally** — never silently?
- Do error messages carry actionable context (what failed, key inputs, remediation) without leaking secrets/PII (cross #14/#16)?
- Does every remote/IO call have a timeout? Retries with capped backoff + jitter, not unbounded?
- Is there a fallback / circuit breaker for a dependency that fails repeatedly?
- Is every acquired resource (file, socket, connection, lock, cursor) released on **all** paths including errors (`with`/`using`/`defer`/`ensure`)?
- Does anything that grows (logs, cache, queue, temp files, sessions) have a bound / eviction / TTL (steady state)?

**Shared categories:** category #4 checks are shared with **tracing-correctness-and-invariants** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
