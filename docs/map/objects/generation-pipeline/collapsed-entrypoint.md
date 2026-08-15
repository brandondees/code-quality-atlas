---
type: "CollapsedEntrypoint"
cluster: "generation-pipeline"
universe: live
status: verified
entity: "skills/manifest.yaml"
---

# CollapsedEntrypoint

A bundled multi-lens skill — e.g. `reviewing-a-change` — generated from an
`entrypoints:` entry and materialized at `collapsed/skills/<name>/`.

## Why this shape

Q20 (`docs/open-questions.md`, resolved, built PR #80): too many top-level
skills to select from without context bloat. Rather than picking one lens
by hand, a `CollapsedEntrypoint` ranks and runs the relevant `Lens` set
internally at the chosen depth mode (see `Manifest`'s `modes:` section),
then synthesizes one verdict — the routing block in this repo's own
`CLAUDE.md`/`AGENTS.md` sends consumers here for "review this PR/diff"
rather than naming a lens directly.

## Shape

Each `entrypoints:` list item in `skills/manifest.yaml:1627` carries:

- `name` — kebab-case identifier; also the directory name under
  `collapsed/skills/`.
- `description` — trigger text (what request routes here).
- `shapes` — which review shapes it covers (`diff`, `repo`, `decision`,
  `artifact`).
- `include_design` (optional) — whether design-capable lenses are pulled in.

Named entries as of `skills/manifest.yaml:1628-1659` (not restated as a
count — see `docs/map/CONTEXT.md`'s no-count rule): `reviewing-a-change`,
`auditing-a-repository`, `reviewing-a-decision`, `reviewing-an-artifact`.
Check `entrypoints:` itself for the current list rather than trusting this
enumeration as it ages.

## Connected to

- **owns:** —
- **owned-by:** `Manifest` (`entrypoints:` list)
- **joins:** every `Lens` it ranks and runs internally (not a static list —
  computed per change from relevance + `shapes`). Note:
  `commands/atlas-review-pr.md` and `commands/atlas-code-review.md` do
  **not** invoke `reviewing-a-change` — they call the same three
  underlying skills directly and in sequence (`choosing-review-lenses`,
  `grounding-review-in-tool-output`, `synthesizing-review-findings`),
  replicating this entrypoint's composition by hand rather than delegating
  to it; see the `Command` card's own "Connected to" entry.
- **looks-like-but-is-not:** `Lens` — see the `Lens` card's own
  looks-like-but-is-not entry for the reverse direction

## If you change this

- **Hits:** the entrypoint's generated `collapsed/skills/<name>/` files on
  `tooling.cli generate`; the root `CLAUDE.md`/`AGENTS.md` routing table if
  the entrypoint's purpose changes (hand-edited, not generated)
- **Does not hit:** the `Lens` files it composes — those regenerate only
  from their own `skills:` entry, never from an entrypoint edit

## Surfaces

| Surface | Role |
|---|---|
| `tooling/generate.py` | emits `collapsed/skills/<name>/` from an `entrypoints:` entry |
| Root `CLAUDE.md`/`AGENTS.md` routing table | sends "review this" requests here over a bare `Lens` |

## See

- Source: `skills/manifest.yaml:1627-1659`
- `docs/open-questions.md` Q20, D16
- `docs/plans/2026-06-25-collapsed-entrypoint-emission.md`
- Verified 2026-08-15 @ `ff7c642`
