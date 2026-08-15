---
type: "Decision"
cluster: "decisions-and-tracking"
universe: live
status: verified
entity: "docs/open-questions.md"
---

# Decision

A tracked design question and its resolution state, in
`docs/open-questions.md`.

## Why this shape

D3 (map first) and D6 (docs are the source of truth) together mean a design
call needs one durable, citable home — not scattered across PR
descriptions or session memory. `docs/open-questions.md` is that home,
distinguishing a *settled* call from a still-*open* one so a session can
tell which is which without re-deriving it.

## Shape

Both marker forms below are `Decision` instances, as defined by
`_meta/schema.md`'s Naming rule:

- **`DN` — a bullet under `## Decisions made`** (`docs/open-questions.md:3`
  onward, e.g. `- **D1 — Project framing.** ... *(2026-06-08)*`). Already
  resolved when written; carries a date and often a build-completion note
  added later (`✅ built ...`).
- **`QN` — a `### QN — Title` header under `## Open questions`**
  (`docs/open-questions.md:24` onward). May be marked `→ RESOLVED` or
  `→ PARTIALLY RESOLVED` (with a pointer to the `DN` that closed it, e.g.
  Q16 → D14) or left genuinely open — the live roster is
  `docs/open-questions.md`'s own "Genuinely still open (undecided)" list
  (`docs/open-questions.md:40`), not this card.
- A `DN` and a `QN` about the same question cross-reference each other by
  number; they are not duplicates — `QN` is the question and its resolution
  narrative, `DN` is the settled-decision ledger entry.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `Category` (a decision can promote a `Gap` into one, e.g. D14);
  `PlanDoc` (a decision's "build deferred" note often points at one);
  `EvalScenario` (Q21's per-lens entries record a hardened suite's
  rationale)
- **looks-like-but-is-not:** `Gap` — a `Decision` is a question the project
  has taken (or is tracking toward) a stance on; a `Gap` is a structural
  taxonomy hole that hasn't been framed as a decision yet

## If you change this

- **Hits:** any doc, plan, or session-log entry that cites this `DN`/`QN`
  by number as settled context
- **Does not hit:** unrelated decisions/questions in the same file — each
  is independently addressable by its own number

## Surfaces

| Surface | Role |
|---|---|
| Root `CLAUDE.md`/`AGENTS.md` orientation | points new sessions here first |
| `docs/session-log.md` | narrates *how* a decision got made, dated |
| `docs/map-gaps.md` | a `Gap` entry often resolves by becoming a `Decision` |

## See

- Source: `docs/open-questions.md`
- Verified 2026-08-15 @ `ff7c642`
