---
name: reviewing-agent-legibility
description: 'Reviews a change for agent-legibility — whether an AI agent can understand,
  navigate, and safely modify this code within a context budget. The mirror of reviewing-ai-authored-code
  (quality of code *for* AI readers, not *by* them): context economy and self-containment
  (a depth-first slice understandable without loading the whole repo — the "40% context
  rule"), retrieval-friendly and AST-navigable structure, local self-explanation at
  the edit site, agent-onboarding files (AGENTS.md / CLAUDE.md) present, accurate,
  and scoped with do-not-touch guardrails, an llms.txt-style index for agent-consumed
  repos, and no agent-hostile patterns (context-budget-blowing megafiles, bloated
  scaffolding, duplicated parallel copies). Use when reviewing a change to an AI-/agent-maintained
  codebase, to agent-onboarding files or repo structure an agent must navigate, or
  any large or scattered change whose context economy matters. Defers human readability
  to #5–#8, agent-operator parity to #24, and runtime tool-safety to #32.'
provenance:
  taxonomy_version: v0.6
  built_from:
  - category: 35
    source: docs/research/cluster-2-readability.md#35
    hash: 5b915385ac18d7d22cf9b5836b342f177debb19643e749bceaa8d4284f159a59
---

# reviewing-agent-legibility

*Can an AI agent read, navigate, and safely change this within a context budget? Context economy, retrieval-friendly structure, scoped AGENTS.md/CLAUDE.md.*

## When to use

Reviews a change for agent-legibility — whether an AI agent can understand, navigate, and safely modify this code within a context budget. The mirror of reviewing-ai-authored-code (quality of code *for* AI readers, not *by* them): context economy and self-containment (a depth-first slice understandable without loading the whole repo — the "40% context rule"), retrieval-friendly and AST-navigable structure, local self-explanation at the edit site, agent-onboarding files (AGENTS.md / CLAUDE.md) present, accurate, and scoped with do-not-touch guardrails, an llms.txt-style index for agent-consumed repos, and no agent-hostile patterns (context-budget-blowing megafiles, bloated scaffolding, duplicated parallel copies). Use when reviewing a change to an AI-/agent-maintained codebase, to agent-onboarding files or repo structure an agent must navigate, or any large or scattered change whose context economy matters. Defers human readability to #5–#8, agent-operator parity to #24, and runtime tool-safety to #32.

**Shape: diff.** Written for concrete code; not meant for design docs or plans.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Context economy / self-containment (the 40% rule):** Can this change be understood — and safely modified — *without* loading the whole repo into context? Is the unit of change a **depth-first slice** (the function plus the key callees, types, and constants it depends on sit together or are reachable in one hop) rather than logic scattered across many files each needing the rest to make sense? A change that only makes sense after a large, fragmented read is a legibility defect for an agent *and* a human (models retrieve worst from the middle of a long context); prefer the self-contained shape.
- **Agent-onboarding files present, accurate, and scoped (AGENTS.md / CLAUDE.md):** If the change alters the build/test/run/convention surface, does the repo's agent-instruction file still tell an agent the truth — and is it **scoped** (the right commands, conventions, and do-not-touch guardrails) rather than absent, stale, or a bloated everything-dump? This is the agent analog of #22's README front-door: file *drift* is #22/#24 and artifact *conformance* is #30, but *"does the repo provide good, scoped agent onboarding to work here"* is owned here. A missing or misleading onboarding file makes every later agent edit start from a worse prior.
- **Retrieval-friendly / discoverable structure (xref #5):** Would a grep / retrieval / AST query land on the right chunk? Are names, file paths, and module boundaries **intention-revealing for a reader who arrives by retrieval**, not by having read the whole tree — the file where a reader (human or agent) expects it, named for what it does? An agent reads by search; structure that defeats search defeats the agent.
- **Structurally-addressable interfaces (AST-navigable):** Does the change expose behavior through **stable, structurally-addressable surfaces** — named exports, typed signatures, clear module entry points an agent can target — rather than dynamic/stringly-typed indirection (reflection, runtime-assembled names, monkey-patching) that defeats static navigation and makes a safe edit guesswork?
- **Local self-explanation over whole-system context (xref #7):** Does the change carry the *why* an agent needs **in place** — a type, a docstring stating the contract, an invariant comment at the edit site — so an editor doesn't have to reconstruct intent from distant files? Distinct from #7's human "why-not-what": here the audience is a **context-bounded** reader, so locality of the explanation is the property, not just its presence.
- **LLM-centric readability — superficially clean, intrinsically complex (xref #6):** Does the code read fine line-by-line yet carry hidden reasoning cost — deep parameter coupling, long-range data dependencies, control flow that only resolves across several files? This is #34's "superficially clean but intrinsically complex" signature read from the *reader's* side; flag where a simpler shape lowers the cost of reasoning about it within a budget (route decomposition detail to #6, restraint counterweight to #11).
- **No agent-hostile patterns introduced:** Does the change add things that make the tree *harder* for an agent to work in — a giant single file that blows the context budget, generated scaffolding/config that bloats what an agent must scan, or duplicated parallel copies that invite editing the wrong one (xref #21 change-amplification, #34 duplication)? Surface these as legibility regressions even when each line is individually fine.
- **Scoped guardrails for autonomous edits:** Do the onboarding files (or equivalent) name the **do-not-touch zones, required checks, and project conventions** an agent must honor, so an autonomous edit *fails safe* rather than confidently wrong? Distinct from #32 runtime agent/tool-safety and #24 operator parity — this is the quality of the *written guidance content*, the agent analog of a good CONTRIBUTING guide.
- **`llms.txt`-style index for agent-consumed repos:** For a library/product that publishes for agent consumption, is there an `llms.txt` (or equivalent machine-readable map) pointing an agent at canonical entry points and docs — present and current, not stale? Emerging standard; surface as an improvement/nit absent a stated agent-consumption need, not a blocker.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
