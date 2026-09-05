---
type: "Lens"
cluster: "generation-pipeline"
universe: live
status: verified
entity: "skills/manifest.yaml"
---

# Lens

One reviewable skill — a single-concern heuristic checklist (e.g.
`hunting-silent-failures`, `reviewing-module-design`) generated from a
`skills:` entry in the `Manifest` and materialized at `skills/<name>/`.

## Why this shape

D7 (`docs/open-questions.md`) sets the authoring bar: a lean `SKILL.md`
(<500 lines) with progressive disclosure into bundled reference files,
portable down to ~8B local models. A `Lens` is the unit that bar applies
to — one concern, one generated skill, traceable back to the `Category` it's
`built_from` (D6) so a research-doc edit can regenerate it.

## Shape

Each `skills:` list item in `skills/manifest.yaml` carries:

- `name` — the lens's own kebab-case identifier; also its directory name
  under `skills/`.
- `description`, `picker` — the trigger text and the router's one-line
  differentiator.
- `shape` — `diff` (most lenses), `repo` (the whole-repo audit lenses),
  `decision` (`reviewing-decision-lifecycle`), or `artifact`
  (`reviewing-artifact-conventions`) — the same four values the sibling
  `CollapsedEntrypoint` card's `shapes` field documents.
- `design` (optional) — whether the lens also fires on design-doc/RFC prose,
  not just diffs.
- `wave` — the lens's original skill-*build* wave (when it was first
  authored). **Name collision:** this is unrelated to the Q21 eval-hardening
  campaign's own "wave 3" numbering (`docs/open-questions.md`,
  `docs/session-log.md`) — see `docs/map/CONTEXT.md`'s "Name collisions"
  section. Check which sense a document means from context.
- `tier` (optional) — `floor` marks one of the five highest-stakes lenses
  Q21 hardened first; every other lens is preference-tier by omission.
- `cross_ref` (optional) — category numbers this lens also draws on, capped
  at 2, with a dedupe note naming the primary owner (D10, G1).
- `eval_min` (optional) — the raised `EvalScenario` floor for this lens
  once its suite has been hardened past D8's 3-scenario baseline (Q21);
  `None` means the baseline still applies.
- `built_from` — a list of `{category, source}` pairs citing the owning
  `Category` (example: `skills/manifest.yaml:26-27` for
  `hunting-silent-failures`).

Example entry: `skills/manifest.yaml:3-28` (`hunting-silent-failures`).

## Connected to

- **owns:** its own `EvalScenario` set (`skills/<name>/evals/eval.json`)
- **owned-by:** `Manifest` (`skills:` list)
- **joins:** `Category` (via `built_from`)
- **looks-like-but-is-not:** `CollapsedEntrypoint` — both materialize as a
  folder with a `SKILL.md`/`evals`/`reference`, but a `CollapsedEntrypoint`
  composes several lenses (no `built_from`, `eval_min`, `wave`, or `tier` of
  its own) rather than owning one atomic heuristic checklist

## If you change this

- **Hits:** the lens's generated `SKILL.md`/`reference/` on
  `tooling.cli generate`; any `CollapsedEntrypoint` that composes it; the
  router (`choosing-review-lenses`) picker text; the self-vendored copy at
  `.claude/skills/<name>/`, which `tooling/vendor-skills.sh .` must re-copy
  to stay in sync — gated by `tests/test_self_vendored_skills_sync.py`
- **Does not hit:** other lenses' generated files (each regenerates
  independently from its own manifest entry); the lens's own
  `examples.md`/`evals/eval.json` — hand-authored and never overwritten by
  regeneration (see `generate`'s own card)

## Surfaces

| Surface | Role |
|---|---|
| `tooling/generate.py` | emits `skills/<name>/` from a `skills:` entry |
| `tooling/evals.py` | validates `EvalScenario` count against `eval_min` |
| `choosing-review-lenses` (generated) | ranks lenses by relevance per change |

## See

- Source: `skills/manifest.yaml` (`skills:` list, e.g. lines 3-28)
- `docs/open-questions.md` D6, D7, D10, Q21
- `docs/map/CONTEXT.md`'s "wave" name-collision entry
- Verified 2026-09-05 @ `33504c1` — fixed the false `examples.md`
  regeneration claim and added the missing `.claude/skills/` re-vendor hit
  (issue #376)
