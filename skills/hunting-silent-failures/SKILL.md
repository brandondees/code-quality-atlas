---
name: hunting-silent-failures
description: "Reviews changes for swallowed or silently-handled errors \u2014 empty\
  \ catch/rescue blocks, ignored returned errors, bare excepts, unhandled promise\
  \ rejections, broad exception catches \u2014 and for unsafe fallbacks, missing timeouts,\
  \ and absent retries/circuit-breakers. Use when reviewing error handling, exceptions,\
  \ try/catch, rescue, fallback, resilience, timeouts, or resource cleanup on failure\
  \ paths."
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 2
    source: docs/research/cluster-1-correctness.md#2
    hash: b0ac6e42beaa9894ca97a61b97d7a75c9eb1e12d9d6bb7611897c9a94de839c0
  - category: 4
    source: docs/research/cluster-1-correctness.md#4
    hash: 1e36f160d81f33df32b24db5e132ac77ac52930aa21b9c957d8d32e28bce86f6
---

# hunting-silent-failures

## When to use

Reviews changes for swallowed or silently-handled errors — empty catch/rescue blocks, ignored returned errors, bare excepts, unhandled promise rejections, broad exception catches — and for unsafe fallbacks, missing timeouts, and absent retries/circuit-breakers. Use when reviewing error handling, exceptions, try/catch, rescue, fallback, resilience, timeouts, or resource cleanup on failure paths.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
