---
name: reviewing-agentic-safety
description: 'Reviews the action/tool surface of agent and tool-using systems — what
  the model is permitted to *do*, distinct from reviewing-llm-integration''s review
  of the *model call*: tool least-privilege, approval gates and step/spend budgets
  on autonomous loops, tool metadata and MCP server descriptions as untrusted input
  (tool poisoning), confused-deputy and token-audience discipline (no token passthrough),
  inter-agent authentication, sandboxed code execution (no ambient credentials, egress
  allow-list), agent-memory hygiene, action audit trails, and the action-leg mitigations
  of the lethal trifecta. Grounded in OWASP''s Top 10 for Agentic Applications (ASI01–ASI10)
  and the MCP security spec. Use when reviewing tool or function definitions exposed
  to a model, an MCP server or client, an autonomous or multi-agent loop, agent memory,
  or code that lets a model take actions. Skip when the change has no tools, agents,
  MCP, or autonomous loop — an ordinary model call with no action surface is reviewing-llm-integration''s
  job.'
provenance:
  taxonomy_version: v0.9
  built_from:
  - category: 32
    source: docs/research/cluster-4-runtime.md#32
    hash: 43c943d3e502924241f60020e6572dfb055445e6d2f290c0fc09965e657e6246
---

# reviewing-agentic-safety

*Is the agent's action surface safe? Tool least-privilege, approval gates & step budgets, untrusted tool metadata, sandboxed exec, egress control.*

## When to use

Reviews the action/tool surface of agent and tool-using systems — what the model is permitted to *do*, distinct from reviewing-llm-integration's review of the *model call*: tool least-privilege, approval gates and step/spend budgets on autonomous loops, tool metadata and MCP server descriptions as untrusted input (tool poisoning), confused-deputy and token-audience discipline (no token passthrough), inter-agent authentication, sandboxed code execution (no ambient credentials, egress allow-list), agent-memory hygiene, action audit trails, and the action-leg mitigations of the lethal trifecta. Grounded in OWASP's Top 10 for Agentic Applications (ASI01–ASI10) and the MCP security spec. Use when reviewing tool or function definitions exposed to a model, an MCP server or client, an autonomous or multi-agent loop, agent memory, or code that lets a model take actions. Skip when the change has no tools, agents, MCP, or autonomous loop — an ordinary model call with no action surface is reviewing-llm-integration's job.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists. When the design doc is specifically a decision record (an ADR, RFC, or adoption/deprecation plan), also run the shared **decision-record checklist** on top of this lens's own topical checks: is the rationale actually recorded (not just the outcome); are the stated assumptions still current; is there a revisit-trigger; is an exit, rollback, or sunset path defined; were real alternatives weighed, not just the chosen option justified after the fact? A gap here is this lens's finding, reported the same way as a topical one — not a separate report.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Tool least-privilege (ASI02/ASI03, LLM06):** Does each tool exposed to the model carry the narrowest capability that serves the feature (a `lookup_order` tool, not `execute_sql`; read-only where writes aren't needed; per-tool scopes)? Excessive *functionality*, *permissions*, or *autonomy* in the tool surface is the finding even before any exploit.
- **Approval gates & autonomy bounds (ASI01/ASI08, LLM10):** Are state-changing, irreversible, or externally visible agent actions gated (human approval, policy check, or allow-list), and is every agent loop bounded — step budget, recursion limit, spend/token cap, wall-clock timeout — so a hijacked or confused agent can't run away?
- **Tool metadata is untrusted input (ASI04):** Tool descriptions, manifests, and server instructions (MCP and similar) are *prompt input from a third party* — they can carry injected instructions (tool poisoning). Are third-party tools/servers pinned to versions, reviewed on update, and their descriptions treated with the same suspicion as user content?
- **Agent identity & token discipline (ASI03):** Does each agent/integration act under its own identity with audience-validated tokens — never passing through tokens issued for someone else (confused-deputy / token-passthrough — explicitly prohibited by the MCP spec), never acting as an ambient over-privileged service account — so actions are attributable and revocable?
- **Sandboxed code execution (ASI05):** If the agent generates or runs code, does it execute in a sandbox with no ambient credentials, bounded resources, and an egress allow-list — never in the host process or with the agent's full privileges?
- **Inter-agent communication (ASI07):** In multi-agent setups, are messages between agents authenticated and integrity-checked, and is another agent's output treated as untrusted data rather than trusted instructions?
- **Memory hygiene (ASI06):** Are writes to persistent agent memory validated and provenance-tagged, with expiry/review — since poisoned memory survives the session and becomes a standing compromise ("sleeper" behavior)?
- **Agent audit trail (ASI09/ASI10):** Is every tool invocation logged with its arguments and initiating context so behavior is traceable, divergence from the agent's role is detectable, and a human can audit *why* an action happened (cross #16)?
- **Exfiltration & egress control (lethal-trifecta action leg, xref #25):** When the agent can both reach sensitive data **and** take an outbound action (send a message, call a tool with model-influenced arguments, make a request), is the *action leg* constrained — egress allow-list, no free-form outbound destinations, human-in-the-loop on data-carrying actions — so injected instructions can't turn a read into an exfiltration? (#25 owns the trifecta *framing* and flags the combination; #32 owns the mitigation that gates the action/exfil leg.)

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
