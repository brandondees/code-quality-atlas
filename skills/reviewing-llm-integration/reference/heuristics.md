# Reviewable heuristics — reviewing-llm-integration

## Contents
- From category #25
- From category #27

## From category #25

### Reviewable heuristics (skill-checklist seeds)
- **Untrusted-input surface:** Is any content the model sees that originates from an untrusted source (user text, retrieved docs/RAG, web pages, tool results, file uploads) clearly *delimited and labeled as data, not instructions*? Assume it can contain injected instructions; the system prompt must not say "do whatever the document says."
- **Lethal-trifecta check:** Does this feature combine access to private/sensitive data + exposure to untrusted content + an ability to exfiltrate or take consequential actions (send email, call tools, make requests)? If all three, treat injection as exploitable and require mitigations (human-in-the-loop, egress allow-list, capability scoping). (Maps LLM01/LLM06 Excessive Agency.)
- **Structured-output validation:** Is every model output that drives code/decisions validated against a schema (types, enums, ranges) and safely handled on validation failure (re-ask, fallback, reject) — never trusted as free text or blindly `JSON.parse`d? (Maps LLM05.)
- **Output as a sink:** Is model output ever passed to a dangerous sink (shell, SQL, `eval`, HTML render, file path, code exec, downstream API auth) without the same treatment you'd give raw user input? It must be sanitized/encoded/parameterized exactly like untrusted input.
- **Eval coverage for nondeterminism:** Is there an eval/regression suite (golden set + assertions/metrics) so prompt or model changes can be measured, not vibe-checked? Are there test cases for failure modes (refusals, hallucination, injection attempts, malformed output)?
- **Model & prompt versioning/pinning:** Is the model identifier pinned (not a floating "latest" alias) and is the prompt template versioned in source control? Can you reproduce a past output's prompt+model? Is there a plan for provider model deprecations?
- **Determinism discipline:** Is `temperature` (and top-p/seed where available) set deliberately — low/zero for extraction/classification/tool-routing, higher only where creativity is wanted? Don't leave a default temperature on a task that needs reproducibility.
- **Timeouts / retries / fallbacks:** Does every model call have a timeout, bounded retries with backoff (idempotent-safe), and a defined fallback when the model is slow/unavailable/over budget (cached answer, smaller model, deterministic path, graceful "can't do that right now")? (Maps LLM10 Unbounded Consumption.)
- **Cost & token efficiency:** Are token usage and spend bounded and observable — context trimmed/summarized, `max_tokens` capped, retrieval top-k bounded, prompt-caching used where supported, batching where possible? Is there a per-user/per-request budget guard against runaway loops (agent step caps)?
- **PII / data egress to third-party models:** Is sensitive data (PII, secrets, regulated data) minimized or redacted before being sent to an external model API? Is the provider's data-retention/training-use setting appropriate, and is this allowed under the data's compliance constraints? (Overlaps #14/#27.)
- **Response caching correctness:** If responses are cached, does the cache key include the full prompt, model, and all params (so a prompt/model change doesn't serve stale outputs), and is caching disabled/scoped for user-specific or sensitive responses?
- **Guardrails & refusal handling:** Are there input *and* output guardrails (moderation/PII/topic/jailbreak) outside the prompt, and does the app handle a refusal or a low-confidence answer gracefully (don't render a refusal as data; have a fallback path)?
- **Graceful degradation when the model is wrong:** Does the UX/flow assume the model can be confidently wrong? Are high-stakes outputs gated by human review, confidence thresholds, citations/grounding, or a deterministic cross-check rather than auto-applied?
- **System-prompt secrecy (don't over-rely):** System prompts and "hidden" instructions can leak (LLM07) — don't put secrets, credentials, or the only security control inside the prompt. Treat the prompt as visible.
- **Supply chain (LLM03/LLM04):** Are third-party models, fine-tunes, embeddings, and prompt/tool plugins from trusted, pinned sources? Untrusted models/datasets can be poisoned.
- **Tool least-privilege (ASI02/ASI03, LLM06):** Does each tool exposed to the model carry the narrowest capability that serves the feature (a `lookup_order` tool, not `execute_sql`; read-only where writes aren't needed; per-tool scopes)? Excessive *functionality*, *permissions*, or *autonomy* in the tool surface is the finding even before any exploit.
- **Approval gates & autonomy bounds (ASI01/ASI08, LLM10):** Are state-changing, irreversible, or externally visible agent actions gated (human approval, policy check, or allow-list), and is every agent loop bounded — step budget, recursion limit, spend/token cap, wall-clock timeout — so a hijacked or confused agent can't run away?
- **Tool metadata is untrusted input (ASI04):** Tool descriptions, manifests, and server instructions (MCP and similar) are *prompt input from a third party* — they can carry injected instructions (tool poisoning). Are third-party tools/servers pinned to versions, reviewed on update, and their descriptions treated with the same suspicion as user content?
- **Agent identity & token discipline (ASI03):** Does each agent/integration act under its own identity with audience-validated tokens — never passing through tokens issued for someone else, never acting as an ambient over-privileged service account — so actions are attributable and revocable?
- **Sandboxed code execution (ASI05):** If the agent generates or runs code, does it execute in a sandbox with no ambient credentials, bounded resources, and an egress allow-list — never in the host process or with the agent's full privileges?
- **Inter-agent communication (ASI07):** In multi-agent setups, are messages between agents authenticated and integrity-checked, and is another agent's output treated as untrusted data rather than trusted instructions?
- **Memory hygiene (ASI06):** Are writes to persistent agent memory validated and provenance-tagged, with expiry/review — since poisoned memory survives the session and becomes a standing compromise ("sleeper" behavior)?
- **Agent audit trail (ASI09/ASI10):** Is every tool invocation logged with its arguments and initiating context so behavior is traceable, divergence from the agent's role is detectable, and a human can audit *why* an action happened (cross #16)?

---

## From category #27

### Reviewable heuristics (skill-checklist seeds)
- **New dependency license check:** does an added dependency (and its transitive tree) carry a license compatible with the project's distribution model? Block/strongly-flag GPL/AGPL pulled into a permissive or proprietary product.
- **Copyleft contamination / linkage:** does the change *link* or *combine* with copyleft code in a way that triggers obligations (esp. AGPL over a network service)? Static vs. dynamic linking and "mere aggregation" matter — flag for legal if unsure.
- **License/attribution preservation:** are upstream license texts, copyright notices, and NOTICE files retained when vendoring/copying code? Removed attribution = violation.
- **Provenance of copied code:** does this diff include code pasted from Stack Overflow, a blog, another repo, or AI generation without attribution/license clarity? Treat as untrusted: verify license, run secret/IP scan, label it.
- **Per-file license header:** do new source files have an `SPDX-License-Identifier` + copyright (REUSE)? Missing header = provenance gap.
- **PII data-flow:** does new code collect, store, log, or transmit personal data? If so — lawful basis/consent present, **minimized** to what's needed, not logged in plaintext, and not sent to a third party/region without basis (cross-links #14, #16, #25).
- **Retention & deletion:** is there a retention limit and an erasure path for new personal data (right-to-be-forgotten), or does it accumulate indefinitely?
- **Data residency / cross-border:** does the change move PII to a new region, vendor, or third-party model (incl. LLM APIs) — is that transfer permitted and documented? (cross-links #25 PII-to-model.)
- **Consent & purpose:** for new tracking/telemetry/analytics, is consent gating in place and is use limited to the stated purpose? No silent expansion of data use.
- **Accessibility-as-legal:** for regulated/consumer surfaces, does the change keep WCAG 2.x AA conformance (cross-links #23) given its legal weight?
- **Export / sanctions / crypto constraints:** does new cryptography, or distribution to restricted regions, hit export-control or compliance obligations? Flag for review (don't assume).
- **SBOM currency:** if dependencies changed, is the SBOM / license inventory regenerated so provenance stays accurate?

---
