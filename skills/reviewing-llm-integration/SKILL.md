---
name: reviewing-llm-integration
description: Reviews LLM/AI integration code for prompt-injection surface, the lethal
  trifecta, unvalidated model output, missing eval coverage, unpinned models, unbounded
  token/cost, and PII sent to third-party models. Use when reviewing code that calls
  an LLM or model API, builds prompts, parses model output, or wires up agents and
  tools. Skip when the change has no model/LLM call, prompt construction, or model-output
  handling — ordinary code that never touches an AI API.
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 25
    source: docs/research/cluster-4-runtime.md#25
    hash: 3c25b2e7b87bb65211317bfdf8f477ebc281978b8ba6271795c7318cf6018eda
  - category: 27
    source: docs/research/cluster-6-evolution.md#27
    hash: ba00467edc777fed0fce3439c40c1d7cede1c341eafc278465121b57c67c3ccc
---

# reviewing-llm-integration

*Is the model call safe and bounded? Injection surface, output validation, evals, token cost, PII.*

## When to use

Reviews LLM/AI integration code for prompt-injection surface, the lethal trifecta, unvalidated model output, missing eval coverage, unpinned models, unbounded token/cost, and PII sent to third-party models. Use when reviewing code that calls an LLM or model API, builds prompts, parses model output, or wires up agents and tools. Skip when the change has no model/LLM call, prompt construction, or model-output handling — ordinary code that never touches an AI API.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Team preferences.** If the reviewed repo has `.code-quality-atlas/preferences.md`, apply it before reporting: a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this lens's thresholds or selection, and — being **preference-tier** — may `suppress` one of its findings outright (it never surfaces). Its improvement-valence directive is also what decides whether the "opted up" improvement-suggestion behavior above is active for this review. Absent the file, apply this lens's defaults exactly as written above.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Untrusted-input surface:** Is any content the model sees that originates from an untrusted source (user text, retrieved docs/RAG, web pages, tool results, file uploads) clearly *delimited and labeled as data, not instructions*? Assume it can contain injected instructions; the system prompt must not say "do whatever the document says."
- **Lethal-trifecta check:** Does this feature combine access to private/sensitive data + exposure to untrusted content + an ability to exfiltrate or take consequential actions (send email, call tools, make requests)? If all three, treat injection as exploitable and require mitigations (human-in-the-loop, egress allow-list, capability scoping). (Maps LLM01/LLM06 Excessive Agency.)
- **Structured-output validation:** Is every model output that drives code/decisions validated against a schema (types, enums, ranges) and safely handled on validation failure (re-ask, fallback, reject) — never trusted as free text or blindly `JSON.parse`d? (Maps LLM05.)
- **Output as a sink:** Is model output ever passed to a dangerous sink (shell, SQL, `eval`, HTML render, file path, code exec, downstream API auth) without the same treatment you'd give raw user input? It must be sanitized/encoded/parameterized exactly like untrusted input.
- **Eval coverage for nondeterminism:** Is there an eval/regression suite (golden set + assertions/metrics) so prompt or model changes can be measured, not vibe-checked? Are there test cases for failure modes (refusals, hallucination, injection attempts, malformed output)?
- **Model & prompt versioning/pinning:** Is the model identifier pinned (not a floating "latest" alias) and is the prompt template versioned in source control? Can you reproduce a past output's prompt+model? Is there a plan for provider model deprecations?
- **New dependency license check:** does an added dependency (and its transitive tree) carry a license compatible with the project's distribution model? Block/strongly-flag GPL/AGPL pulled into a permissive or proprietary product.
- **Copyleft contamination / linkage:** does the change *link* or *combine* with copyleft code in a way that triggers obligations (esp. AGPL over a network service)? Static vs. dynamic linking and "mere aggregation" matter — flag for legal if unsure.

**Shared categories:** category #27 checks are shared with **auditing-compliance-and-provenance** (their primary owner). When both lenses run on the same change, report each shared finding once, under the primary owner.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

**Process notes.** If this lens misfired on this change — flagged correct code, missed an obvious issue squarely in its own scope, or its checklist didn't fit the change shape — say so in one line under `synthesizing-review-findings`'s **Process notes** appendix; that is not a defect finding. Say nothing if the lens worked as intended — never invent a process note to fill the section.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
