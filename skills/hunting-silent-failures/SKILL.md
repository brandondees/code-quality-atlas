---
name: hunting-silent-failures
description: Reviews changes for swallowed or silently-handled errors — empty catch/rescue
  blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad
  exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers.
  Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience,
  timeouts, or resource cleanup on failure paths.
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 2
    source: docs/research/cluster-1-correctness.md#2
    hash: b0ac6e42beaa9894ca97a61b97d7a75c9eb1e12d9d6bb7611897c9a94de839c0
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 3edce8248eeb84bff46c3aa7e7c5ad1ada54d091f9366fb17fba234616ec27c7
---

# hunting-silent-failures

## When to use

Reviews changes for swallowed or silently-handled errors — empty catch/rescue blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers. Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience, timeouts, or resource cleanup on failure paths.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

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
