# Tool rules to triage — reviewing-agentic-safety

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #32

## From category #32

### Tooling rules worth lifting

*(The action/tool surface is judgment-led and the tooling is young — most leverage is in design review of the tool surface, not lint. Treat the tools below as evidence-gatherers, and `(verify)` names against your stack.)*

- **MCP / tool-surface scanners** — `mcp-scan` (Invariant Labs) and similar that inspect connected MCP servers for tool-poisoning, prompt-injection-in-description, and over-broad tool scopes; treat any third-party tool description as untrusted input it parses. `(verify)`
- **Permission / scope auditors** — review the tool manifest and the OAuth scopes / API capabilities each tool actually holds against what the feature needs; a `write`/`delete`/`execute` capability where a read suffices is the finding (least-privilege at the tool boundary, overlaps #14).
- **Sandbox runtimes for agent code-exec** — gVisor, Firecracker, nsjail, or a container with **no ambient credentials**, bounded CPU/mem, seccomp, and an **egress allow-list** for any path where the agent generates or runs code; running generated code in the host process is the anti-pattern to flag.
- **Agent-framework guardrails** — human-in-the-loop / approval-interrupt hooks, step & recursion budgets, spend/token caps, and policy monitors (e.g. LangGraph interrupts, framework-native approval gates); a state-changing tool reachable in an unbounded loop with no gate is a finding even before exploit.
- **Action audit / tracing** — structured logging of every tool invocation with its arguments and initiating context (overlaps #16 observability), so divergence from the agent's role is detectable and a human can audit *why* an action happened.
