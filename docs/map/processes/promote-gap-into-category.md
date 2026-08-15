---
type: process
status: verified
consumes: [Gap]
produces: [Category, Decision]
---

# promote-gap-into-category

Turn an open structural `Gap` into a first-class `Category` (and often a
new `Lens`), closing the *silent* hole the gap named rather than a thin
factor an existing category could absorb.

## Input → Movement → Output

Input: a `Gap` section in `docs/map-gaps.md` naming a kind of reviewable
thing the taxonomy never framed at all. Movement: decide the category's
scope and boundary against neighboring categories, add a numbered
research section (the `## #N Title` format the `Category` card
describes), update `taxonomy.md`, and record the call as a `Decision`.
Output: a new `Category`, a `DN` bullet resolving both the `Gap` and (if a
question tracked it) a `QN`, and — separately, not always same-day — a
`Lens` built from the new category.

## Why this shape

G10's own framing: "a missing category does not yield a *thin* heuristic
you can spot by auditing the skills... it yields a *silent* hole — the
factor is never written at all." A `Gap` exists precisely because sharpening
an existing `Category` wasn't the right fix; promoting it to its own
category is what closes a framing-class hole rather than papering over it
with an add-factor to something adjacent.

## Steps

1. Name the gap's scope and its boundary against neighboring categories
   explicitly — e.g. G2's `#25`↔`#32` boundary: model-call concerns stay
   `#25`, action/tool concerns move to the new `#32`
   (`docs/open-questions.md:18`, D14).
2. Add the new `## #N Title` research section to the appropriate
   `docs/research/cluster-*.md` file and update `taxonomy.md`.
3. Record the call as a `DN` bullet in `docs/open-questions.md` — e.g. D14
   for G2 → `#32 Agentic & tool-use safety`, or D13 for G10 → `#30
   Enforcement apparatus & meta-artifacts` (`docs/map-gaps.md:97`).
4. Mark the `Gap` section itself resolved, inline, with a pointer to the
   `Decision` that closed it (`docs/map-gaps.md:27` for G2; `docs/
   map-gaps.md:97` for G10) — there is no separate resolved/open gap list,
   the resolution lives in the same `GN` section.
5. Ship a `Lens` built from the new category (see the `generate` process
   card) — often a later, separate step from the taxonomy promotion itself.

## If you change this

- **Hits:** `taxonomy.md`; the target `docs/research/cluster-*.md` file; any
  neighboring `Category`'s boundary note if the new category's scope
  overlaps it
- **Does not hit:** other open `Gap` entries (each is independently
  resolved on its own evidence, not by precedent alone)

## Surfaces

| Surface | Role |
|---|---|
| `docs/map-gaps.md` | where a `Gap` is named and, inline, marked resolved |
| `docs/open-questions.md` | where the promotion decision (`DN`) is recorded |
| `taxonomy.md` | the category list the promotion updates |

## See

- Objects: `Gap`, `Category`, `Decision`
- Source: `docs/map-gaps.md` (G2 at line 21, G10 at line 83)
- `docs/open-questions.md` D5, D13, D14
- Verified 2026-08-15 @ `1ed3006`
