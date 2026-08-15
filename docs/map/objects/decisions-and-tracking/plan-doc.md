---
type: "PlanDoc"
cluster: "decisions-and-tracking"
universe: leftover
status: verified
entity: "docs/plans/"
---

# PlanDoc

A dated, scoped, `**Status:**`-tagged implementation plan under
`docs/plans/`.

## Why this shape

A build-approval `Decision` (e.g. D17 approving stage 1 of the
self-improvement loop) often needs a task-by-task execution plan separate
from the decision's own prose. `docs/plans/` holds that plan as its own
file, dated and named for what it plans — kept afterward as the historical
record of *how* the work was sequenced, not deleted once shipped.

## Shape

- Filename: `YYYY-MM-DD-<slug>.md` under `docs/plans/` — already dated and
  scoped, so `_meta/schema.md`'s Naming rule ("the literal filename") needs
  no further addressing scheme.
- First line after the title is a bold `**Status: <word...>**` sentence
  (e.g. `**Status: implemented.**`,
  `docs/plans/2026-06-09-skill-pipeline-wave1.md:3`; `**Status: complete —
  2026-06-27 (PR #92).**`,
  `docs/plans/2026-06-27-threat-modeling-lens.md:3`) — the live
  source of truth for whether the plan is still actionable. Root
  `CLAUDE.md`/`AGENTS.md`'s orientation section points here and says to
  check each file's own header rather than assuming the whole directory is
  a live queue or a closed archive.
- The body below the status line is often the *original* execution plan
  with `- [ ]` checkbox task syntax, kept unexecuted-looking on purpose once
  status is `implemented`/`complete` — the shipped code is the source of
  truth at that point, not the checkboxes.

**Universe: leftover.** Every plan doc currently in the directory carries a
`Status` marking it already implemented/complete (verified 2026-08-15,
`ff7c642`) — the type still exists and gets used for new plans, but no
*current* instance is in force; re-check each file's own header before
citing one as live, since a new plan doc could land at `live` at any time.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `Decision` (the approving `DN`/`QN` this plan executes, e.g.
  D17 → the self-improvement-loop stage-1 plan)
- **looks-like-but-is-not:** `Runbook` — a `PlanDoc` is a one-time execution
  plan for a specific build, often historical once shipped; a `Runbook` is a
  repeating manual procedure meant to stay current indefinitely

## If you change this

- **Hits:** nothing generated — plan docs are hand-authored and read, never
  regenerated
- **Does not hit:** other plan docs, or the `Decision` that approved this
  one (update that separately if the resolution narrative changes)

## Surfaces

| Surface | Role |
|---|---|
| Root `CLAUDE.md`/`AGENTS.md` orientation | routes here, with the "check the Status header" caveat |

## See

- Source: `docs/plans/`
- Verified 2026-08-15 @ `ff7c642`
