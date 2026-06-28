# Runbook — Auditing many repositories at once (fan-out)

The single-conversation flow — `choosing-review-lenses` → run lenses →
`synthesizing-review-findings` — reviews **one** change in **one** repo. For a
fleet audit ("check these 10 services for silent failures and supply-chain
risk") that flow runs sequentially and loses its findings between repos. This
runbook fans the suite out across repositories with **background agents** and
collects every agent's findings through one shared contract, so the result is a
single deduplicated, cross-repo report instead of ten transcripts.

The enabler is the **finding contract** from
[`synthesizing-review-findings`](../../skills/synthesizing-review-findings/SKILL.md):
because every lens normalizes to `{location, severity, lens, finding, fix}`, an
orchestrating session can merge findings it never produced itself — across
lenses **and** across repos — with the same deterministic dedupe-and-rank rules.

## The shape

```text
orchestrator session
├── agent: repo A ──┐
├── agent: repo B ──┤  each runs the relevant lenses on its repo,
├── agent: repo C ──┤  emits findings in the finding contract (one JSON list)
└── agent: repo … ──┘
        ↓
orchestrator aggregates → dedupe within repo → group across repos → one report
```

One agent per repo is the default. For a large repo or a broad audit you can go
one agent per **repo × lens** (or per repo × audit), but keep the fan-out width
in mind — wide fan-out is faster but costs more context and more sandboxes.

## Steps

1. **Pick the lenses once, up front.** Decide what the audit is *for* and select
   the lenses before fanning out — every agent runs the **same** set so findings
   are comparable across repos. For a whole-repo health sweep this is the eight
   repo-shaped audits (`finding-maintainability-hotspots`,
   `auditing-architecture-conformance`, `auditing-dependencies-and-supply-chain`,
   `auditing-config-and-build-hygiene`, `auditing-documentation-health`,
   `auditing-compliance-and-provenance`, `auditing-enforcement-and-meta-artifacts`,
   `auditing-infrastructure-as-code`);
   for a targeted sweep ("error handling across our services") it may be one or
   two lenses. `choosing-review-lenses` is for the *per-change* case — for a
   fleet audit you are choosing the lens set deliberately, not routing.

2. **Honor each lens's skip conditions.** The narrowly-scoped lenses carry
   explicit *Skip when…* clauses (e.g. `reviewing-accessibility-and-i18n` skips
   backend/CLI repos, `reviewing-llm-integration` skips repos with no model
   call). An agent that finds the skip condition true for its repo should return
   `[]` for that lens (identical to a ran-but-clean lens — the orchestrator drops
   both) and note the skip in its summary, rather than inventing findings — this
   is what keeps a wide fan-out from drowning the report in noise from irrelevant
   repos.

3. **Fan out with background agents.** Spawn one agent per repo (the harness's
   parallel-agent / background-task mechanism). Give each the **same** prompt:
   the lens set, the repo to audit, and the instruction to **return findings in
   the finding contract** — a JSON list of `{repo, location, severity, lens,
   finding, fix}` objects (add `repo` to the contract's five base fields so
   findings stay attributable after the merge). An agent with no findings for a
   lens returns an empty list for it, not prose; a lens it skipped per step 2
   does the same.

4. **Aggregate centrally.** When the agents return, the orchestrator applies
   `synthesizing-review-findings`:
   - **Dedupe within a repo** exactly as the skill describes (same location +
     same root cause = one finding, attributed to the category's primary owner).
   - **Group across repos** — the same finding class recurring in many repos
     (e.g. unpinned base images in six of ten services) is a *fleet* signal;
     surface it as one grouped row with the repo list, not ten scattered rows.
   - **Rank** by severity across the whole fleet so a Blocker in one repo floats
     above Minors everywhere.

5. **Report once.** Emit a single cross-repo review: a fleet verdict, then
   findings grouped by class with their affected repos, severity-ranked. The
   per-repo detail lives in each agent's returned list; the merged report points
   to it rather than restating it.

## Notes

- **Reviewer discipline carries over.** The aggregate must not inflate: it is
  exactly the union of the agents' real findings, deduped and grouped — nothing
  added. A repo that came back clean stays clean in the report.
- **Width vs. cost.** Background agents are not free. Start narrow (the lenses
  the audit actually needs), and widen only if the first pass justifies it — the
  same restraint the suite applies to code applies to how much of it you run.
- **This is advisory, like the single-repo merge.** Nothing here requires a
  bespoke harness; the contract just makes the merge mechanical if you have one.
  By hand or automated, the merged report is the same.
