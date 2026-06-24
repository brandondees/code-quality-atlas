# Reviewable heuristics — reviewing-agentic-safety

## Contents

- From category #32

## From category #32

### Reviewable heuristics (skill-checklist seeds)

- **Tool least-privilege (ASI02/ASI03, LLM06):** Does each tool exposed to the model carry the narrowest capability that serves the feature (a `lookup_order` tool, not `execute_sql`; read-only where writes aren't needed; per-tool scopes)? Excessive *functionality*, *permissions*, or *autonomy* in the tool surface is the finding even before any exploit.
- **Approval gates & autonomy bounds (ASI01/ASI08, LLM10):** Are state-changing, irreversible, or externally visible agent actions gated (human approval, policy check, or allow-list), and is every agent loop bounded — step budget, recursion limit, spend/token cap, wall-clock timeout — so a hijacked or confused agent can't run away?
- **Tool metadata is untrusted input (ASI04):** Tool descriptions, manifests, and server instructions (MCP and similar) are *prompt input from a third party* — they can carry injected instructions (tool poisoning). Are third-party tools/servers pinned to versions, reviewed on update, and their descriptions treated with the same suspicion as user content?
- **Agent identity & token discipline (ASI03):** Does each agent/integration act under its own identity with audience-validated tokens — never passing through tokens issued for someone else (confused-deputy / token-passthrough — explicitly prohibited by the MCP spec), never acting as an ambient over-privileged service account — so actions are attributable and revocable?
- **Sandboxed code execution (ASI05):** If the agent generates or runs code, does it execute in a sandbox with no ambient credentials, bounded resources, and an egress allow-list — never in the host process or with the agent's full privileges?
- **Inter-agent communication (ASI07):** In multi-agent setups, are messages between agents authenticated and integrity-checked, and is another agent's output treated as untrusted data rather than trusted instructions?
- **Memory hygiene (ASI06):** Are writes to persistent agent memory validated and provenance-tagged, with expiry/review — since poisoned memory survives the session and becomes a standing compromise ("sleeper" behavior)?
- **Agent audit trail (ASI09/ASI10):** Is every tool invocation logged with its arguments and initiating context so behavior is traceable, divergence from the agent's role is detectable, and a human can audit *why* an action happened (cross #16)?
- **Exfiltration & egress control (lethal-trifecta action leg, xref #25):** When the agent can both reach sensitive data **and** take an outbound action (send a message, call a tool with model-influenced arguments, make a request), is the *action leg* constrained — egress allow-list, no free-form outbound destinations, human-in-the-loop on data-carrying actions — so injected instructions can't turn a read into an exfiltration? (#25 owns the trifecta *framing* and flags the combination; #32 owns the mitigation that gates the action/exfil leg.)

---
