---
type: "Runbook"
cluster: "—"
universe: live
status: verified
entity: "docs/runbooks/"
---

# Runbook

A how-to procedure for a recurring manual task — a file under
`docs/runbooks/`, read and followed rather than invoked.

## Why this shape

Some recurring work isn't automatable end-to-end (standing up a local-model
substrate for a cross-model re-gate; fanning a review out across many
repos by hand) but still needs to be repeatable and consistent across
sessions rather than re-derived from memory each time. A `Runbook` is that
procedure written down once.

## Shape

- File: `docs/runbooks/<name>.md` — the filename is the runbook's identity
  (`_meta/schema.md`'s Naming rule); title convention `# Runbook — <what it
  does>` (e.g. `docs/runbooks/cross-model-re-gate.md:1`).
- Prose procedure, not frontmatter-declared like a `Command` — no
  `argument-hint`/`allowed-tools`, since nothing invokes it directly.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `EvalScenario` (`cross-model-re-gate.md` is the procedure for
  the Q21 campaign's `Decision`-tracked re-gate runs)
- **looks-like-but-is-not:** `Command` — see the `Command` card's own
  looks-like-but-is-not entry for the reverse framing; also not a
  `PlanDoc` — a runbook stays live/current by design, a plan doc is a
  one-time execution record that's often historical once shipped

## If you change this

- **Hits:** nothing generated — runbooks are hand-authored and read
- **Does not hit:** other runbooks, or the mechanism they describe (a
  runbook edit doesn't change `tooling/` behavior, only the documented
  procedure for using it)

## Surfaces

| Surface | Role |
|---|---|
| `docs/open-questions.md` Q21 entries | cite `cross-model-re-gate.md` as the procedure behind a re-gate result |

## See

- Source: `docs/runbooks/`
- Verified 2026-08-15 @ `ff7c642`
