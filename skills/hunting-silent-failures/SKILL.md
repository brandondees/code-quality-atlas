---
name: hunting-silent-failures
description: Reviews changes for swallowed or silently-handled errors — empty catch/rescue
  blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad
  exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers.
  Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience,
  timeouts, or resource cleanup on failure paths.
provenance:
  taxonomy_version: v0.3
  built_from:
  - category: 2
    source: docs/research/cluster-1-correctness.md#2
    hash: e57d4915e49200d858adbbc56c972154fb6dacf73a988c58de734ea8693339c0
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 9a8288ba9a0155c5b816ae033497849954224582cc461daf7baeb8b6af4e5afc
---

# hunting-silent-failures

*Where do errors vanish? Swallowed exceptions, silent fallbacks, missing timeouts and retries.*

## When to use

Reviews changes for swallowed or silently-handled errors — empty catch/rescue blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers. Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience, timeouts, or resource cleanup on failure paths.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- Is any error swallowed — empty catch/`rescue`, `except: pass`, ignored Go `err`, discarded Result?
- Does each handler narrow to the *expected* exception type, not a blanket catch-all?
- On failure does it **fail loud** (surface + log with context) or **degrade intentionally** — never silently?
- Do error messages carry actionable context (what failed, key inputs, remediation) without leaking secrets/PII (cross #14/#16)?
- Does every remote/IO call have a timeout? Retries with capped backoff + jitter, not unbounded?
- Is there a fallback / circuit breaker for a dependency that fails repeatedly?
- Is every acquired resource (file, socket, connection, lock, cursor) released on **all** paths including errors (`with`/`using`/`defer`/`ensure`)?
- Does anything that grows (logs, cache, queue, temp files, sessions) have a bound / eviction / TTL (steady state)?

**Shared categories:** category #4 checks are shared with **tracing-correctness-and-invariants** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
