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
    hash: 50eed7d384d719649b96bf16051744e3c80954079467508fb4c02f813c3ad1b7
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: 69e72250723c3e9ab22ccbefecb049b2a53da21c6da51f55d570f161bfe0454f
---

# reviewing-llm-integration

## When to use

Reviews LLM/AI integration code for prompt-injection surface, the lethal trifecta, unvalidated model output, missing eval coverage, unpinned models, unbounded token/cost, and PII sent to third-party models. Use when reviewing code that calls an LLM or model API, builds prompts, parses model output, or wires up agents and tools.

## Top checks

Start with the full checklist, then escalate to the references as needed.

- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.
- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.
- See [reference/sources.md](reference/sources.md) for the references behind each check.
- See [examples.md](examples.md) for good/bad examples.
