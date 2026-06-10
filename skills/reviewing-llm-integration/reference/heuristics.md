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

---

## Open threads (gaps / mis-placements / sub-topics worth deeper research)

- **Sourcing status (was a gap):** the draft's standards spines and high-traffic rule IDs are now **web-verified (2026-06-09)** — CWE 2024 ranks, ASVS 5.0 (17 chapters), OWASP LLM Top 10 2025, Bandit/gosec IDs, Core Web Vitals, lethal trifecta. Residual `(verify)`: exact Semgrep/CodeQL query IDs, Sonar squids, LLM-Guard scanner names — these churn fastest and should be confirmed at skill-build time.
- **Security ↔ Dependencies/Supply chain (#14 ↔ #18):** A06 Vulnerable Components and CVE scanning live in both #14 and #18; LLM03 (LLM supply chain) and #25 also overlap. Decide which skill *owns* dependency-CVE review so it isn't done twice or dropped between them.
- **Security ↔ Compliance/PII (#14 ↔ #27):** PII handling, data residency/retention, and "PII sent to third-party models" (#25) straddle #14, #25, and #27. The map currently has PII handling under #14 and regulatory obligations under #27 — a review skill will need an explicit hand-off rule.
- **Observability ↔ Configuration (#16 ↔ #26):** Twelve-factor logging, feature-flag lifecycle/stale-flag cleanup, and graceful startup/shutdown appear in both #16 and #26. The taxonomy already notes flags live in #12/#16/#26 — worth a single canonical home for "feature-flag hygiene."
- **SLO/error-budget straddles #16 and #24:** As the taxonomy's residual-candidates note flags, SLO/error-budget framing is partly a process concern. The observability skill should *instrument* SLIs; the process skill should own the budget policy. Clarify the seam.
- **Performance counterweight is hard to lint:** "Premature optimization" is almost entirely a heuristic/judgment call with essentially no tooling support (unlike most categories). The skill will likely need an LLM-judgment check ("is there a profile/benchmark justifying this?") rather than a rule — note for phase-2 skill design, and mirrors the #11 premature-abstraction counterweight problem.
- **#25 is tooling-thin and fast-moving:** Unlike #14–#16, classic static analysis barely covers LLM integration; the leverage is in eval harnesses, output-schema enforcement, and guardrail frameworks. Tool/IDs here will churn fastest of any category — design the skill to assert *behaviors* (validate output, pin model, bound cost, label untrusted input) rather than name specific tools.
- **Agentic/tool-use risk may deserve its own factor:** "Excessive Agency" (LLM06) + the lethal-trifecta pattern (autonomous tool-calling agents acting on untrusted input) is arguably bigger than a sub-bullet of #25 and cross-cuts #14 (authz of tool actions) and #13 (API contracts the agent calls). Candidate for promotion or an explicit cross-link as agent features proliferate.

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

## Open threads   (gaps / mis-placements / sub-topics worth deeper research)

- **Citation status (was a gap):** the standards spines and high-traffic tool IDs are now **web-verified (2026-06-09)** — WCAG 2.2 SCs (2.4.11, 2.5.8, 1.4.3), axe-core / jsx-a11y rule ids, Conventional Commits + commitlint, the SmartBear/Cisco review-size numbers, Diátaxis, ADR, Keep a Changelog, SPDX/AGPL, REUSE, EAA (2025-06-28), GDPR. Residual `(verify)`: some SonarQube squids and formatjs/i18next/html-validate plugin rule names — confirm at skill-build time.
- **#21 ↔ #15/#6 overlap.** Cyclomatic/cognitive complexity and god-modules appear here (as change-amplification proxies), in #6 (local readability), and #12 (architecture). The *maintainability* lens is specifically VCS-aware (churn × complexity, change-coupling, bus factor) — worth carving out as the distinguishing behavior so it doesn't collapse into generic complexity linting.
- **#22 ↔ #7 boundary.** "Comment rot" lives in #7 (comments) but doc-drift detection (docstring-vs-signature, example rot) is here. Suggest: #7 = in-code why-not-what; #22 = external/structured docs + ADR/changelog/runbook. Tools like `darglint`/`eslint-plugin-jsdoc` straddle both.
- **i18n money/units genuinely double-booked (#23 ↔ #4).** The *formatting* facet (Intl/CLDR, locale-aware output) is here; the *arithmetic correctness* facet (precision, overflow, currency math) is #4. The taxonomy already cross-links this; a single skill may need to own both ends to avoid a seam.
- **AI-generated-code provenance (#27) ↔ #25.** Provenance/attribution/licensing of AI output sits in #27; prompt-injection and output-validation sit in #25. A reviewer checking an AI-authored PR needs both lenses at once — candidate for a combined "AI-contribution review" behavior.
- **Privacy/telemetry is triple-booked** (#27 regulatory, #16 observability/logging-no-PII, #14 PII handling). The taxonomy's own residual-candidates note flags this. For the skill suite, recommend one PII-data-flow check that all three reference rather than three partial ones.
- **Agent-native parity (#24)** is a project-specific principle with thin external prior art (mainly the in-repo `agent-native-reviewer`). Worth deeper sourcing or treating as a house rule rather than an industry-standard heuristic.
- **"Definition of done" and SLO/error-budget framing** straddle process (#24) and observability (#16); the taxonomy notes this. Decide whether DoD is a checklist owned by #24 that *includes* observability gates, or a cross-cutting meta-check.
- **Legal calls exceed an agent's authority.** Several #27 heuristics (copyleft linkage, export control, data-residency legality) should *flag for human/legal review* rather than assert a verdict — the skill design should encode that escalation, not pretend to adjudicate.
