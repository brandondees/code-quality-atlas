---
name: reviewing-llm-integration
description: Reviews LLM/AI integration code for prompt-injection surface, the lethal
  trifecta, unvalidated model output, missing eval coverage, unpinned models, unbounded
  token/cost, and PII sent to third-party models. Use when reviewing code that calls
  an LLM or model API, builds prompts, parses model output, or wires up agents and
  tools.
provenance:
  taxonomy_version: v0.2
  built_from:
  - category: 25
    source: docs/research/cluster-4-runtime.md#25
    hash: 91ad39b5e42b74c026eed080276563ac7b3e57f3667abcbb2a97cddedfb83d02
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: 973cb4bcfda0d546fe1fa8a4cde13fda7368c1cd120d0581b2a02d5ace663cfc
---

# reviewing-llm-integration

## When to use

Reviews LLM/AI integration code for prompt-injection surface, the lethal trifecta, unvalidated model output, missing eval coverage, unpinned models, unbounded token/cost, and PII sent to third-party models. Use when reviewing code that calls an LLM or model API, builds prompts, parses model output, or wires up agents and tools.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues, and do not suggest changes to code that is already correct. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
