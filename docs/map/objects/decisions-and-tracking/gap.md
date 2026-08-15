---
type: "Gap"
cluster: "decisions-and-tracking"
universe: live
status: verified
entity: "docs/map-gaps.md"
---

# Gap

A structural taxonomy gap feeding future categories/lenses — a `## GN —
Title` section in `docs/map-gaps.md`.

## Why this shape

Research-first mapping (D3) surfaces two different kinds of "something's
missing": a factor that's thin but already has an owner (fixable by
sharpening an existing `Category`), and a hole the taxonomy never framed at
all (a *silent* gap, only findable by asking "what kind of reviewable thing
did we never put on the map?" — G10's own framing). `Gap` entries exist so
the second kind gets a durable, addressable home instead of staying an
unrecorded hunch.

## Shape

- Lives as a `## GN — Title` section in `docs/map-gaps.md` (e.g. `## G2 —
  Candidate promotion: "Excessive Agency" / agentic tool-use safety`,
  `docs/map-gaps.md:21`).
- Resolution is recorded inline in the same section (e.g. G2:
  `**Resolved (2026-06-12, D14 / Q16):** ...`, `docs/map-gaps.md:27`) —
  there is no separate resolved/open list the way `docs/open-questions.md`
  keeps one; check each `GN` section itself for its status.
- A resolved `Gap` typically promotes into a new `Category` (G2 → `#32`) or
  gets folded into an existing one — the section says which.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `Category` (a resolved gap's usual destination); `Decision`
  (the `DN`/`QN` that resolved it, cited inline)
- **looks-like-but-is-not:** `Decision` — see the `Decision` card's own
  looks-like-but-is-not entry for the reverse framing

## If you change this

- **Hits:** the `taxonomy.md`/`docs/research/` files if the gap resolves by
  promoting a category; the `Manifest`/`Lens` set if a new lens ships to
  cover it
- **Does not hit:** other `GN` sections in the same file — each is
  independently addressable

## Surfaces

| Surface | Role |
|---|---|
| Root `CLAUDE.md`/`AGENTS.md` orientation | points new sessions here for structural gaps |
| `docs/open-questions.md` | records the `Decision` that resolves a gap |

## See

- Source: `docs/map-gaps.md`
- Verified 2026-08-15 @ `ff7c642`
