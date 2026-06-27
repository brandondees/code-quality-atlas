# reviewing-agentic-safety

Is the agent's action surface safe? Tool least-privilege, approval gates & step budgets, untrusted tool metadata, sandboxed exec, egress control.

## When to use

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Checklist

The full review checklist, grouped by the research category each check draws from:

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

## Examples

Report each distinct issue as its own numbered finding, naming the **ASI/LLM class**
it maps to and citing the code on the action/tool surface. This lens owns what the
model is permitted to *do*; it **defers** the model call itself to #25
(`reviewing-llm-integration`), the authz verdict to #14 (`sweeping-for-security`),
and the tool *contract* to #13. When the action surface is already least-privilege,
gated, and bounded, the entire response is exactly "No findings".

## Bad → finding (over-broad tool — ASI02 least-privilege)

**Input (diff):**

```python
# tools.py — exposed to the agent
@tool
def run_sql(query: str) -> list:
    """Run any SQL the model asks for."""
    return db.execute(query)            # full read/write, arbitrary statements
```

**Expected finding:**

1. **Tool least-privilege violation (ASI02/ASI03):** the agent is handed an
   `execute_sql`-class tool with arbitrary read/write over the whole database, where
   the feature only needs to look up an order. Excessive *functionality* and
   *permissions* on the tool surface is the finding before any exploit — a prompt
   injection now reaches every table. Replace with a narrow, parameterized
   `lookup_order(order_id)` (read-only, single-purpose); if SQL is genuinely needed,
   scope it to an allow-list of statements and a read-only role.

## Bad → finding (unbounded loop + ungated action — ASI01/ASI08)

**Input (diff):**

```python
while not done:                          # no step / iteration budget
    step = agent.next()
    if step.tool == "send_refund":
        issue_refund(step.amount)        # state-changing, irreversible, no approval
```

**Expected finding:**

1. **No autonomy bound + no approval gate (ASI01/ASI08, LLM10):** the agent loop has
   no step budget, recursion limit, spend cap, or wall-clock timeout, and a
   state-changing, irreversible action (`issue_refund`) fires with no human approval
   or policy check. A hijacked or confused agent can run away and move money. Bound
   the loop (step/spend/time budget) and gate `issue_refund` behind human approval or
   an allow-list with an amount threshold.

## Bad → finding (token passthrough / confused deputy — ASI03, detect-and-route)

**Input (diff):**

```python
# mcp_server.py — proxies the caller's request to an upstream API
def handle(req):
    upstream.get("/data", headers={"Authorization": req.headers["Authorization"]})
    #                                  ^ forwards the inbound token unchanged
```

**Expected finding:**

1. **Token passthrough / confused deputy (ASI03):** the server forwards the inbound
   `Authorization` token to an upstream API without validating its **audience** —
   explicitly prohibited by the MCP security spec. A token issued for this server is
   replayed against another service, so the server spends its trust on a lower-trust
   caller's behalf. Validate the token audience and exchange it for one minted for the
   upstream (or act under the server's own scoped identity). **Route:** the authz
   verdict to `sweeping-for-security` (#14); the agentic token-discipline defect is
   owned here.

## Good → no finding

**Input (diff):**

```python
@tool
def lookup_order(order_id: str) -> dict:   # narrow, read-only, single purpose
    return orders.get_readonly(order_id)

result = agent.run(task, max_steps=8, on_action=require_approval)  # bounded + gated
```

**Expected finding:** No findings

Note: the tool is least-privilege (read-only, single-purpose), the loop is bounded
(`max_steps`), and actions are gated (`require_approval`). Do NOT invent an agentic
defect on a tool surface that is already narrow, bounded, and gated.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
