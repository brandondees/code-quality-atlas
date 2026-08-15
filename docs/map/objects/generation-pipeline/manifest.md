---
type: "Manifest"
cluster: "generation-pipeline"
universe: live
status: verified
entity: "skills/manifest.yaml"
---

# Manifest

`skills/manifest.yaml` — the single YAML file that declares every `Lens` and
`CollapsedEntrypoint`, and drives everything the generation pipeline emits.

## Why this shape

D6 (`docs/open-questions.md`) made docs the source of truth and skills
derived/regenerable, not hand-maintained. The manifest is the mechanism: one
file a generator reads, so a doc change (a new research category, a raised
`eval_min`) flows into every affected `Lens` file by re-running
`python -m tooling.cli generate`, instead of hand-editing 30+ `SKILL.md`
files in sync. `python -m tooling.cli drift` catches the gap when a source
doc changes but the generated skill doesn't.

## Shape

- `taxonomy_version` (`skills/manifest.yaml:1`) — the taxonomy version every
  `built_from` citation is checked against.
- `skills:` (`skills/manifest.yaml:2`) — the list of `Lens` entries; each
  item's shape (`built_from`, `eval_min`, `wave`, `tier`, `cross_ref`,
  `design`) is documented on the `Lens` card, not repeated here.
- `router:` (`skills/manifest.yaml:960`) — drives the generated
  `choosing-review-lenses` skill (picker text per lens).
- `prepass:` (`skills/manifest.yaml:1254`) — drives
  `grounding-review-in-tool-output`.
- `synthesizer:` (`skills/manifest.yaml:1414`) — drives
  `synthesizing-review-findings` (dedup/tension/ranking rules).
- `modes:` (`skills/manifest.yaml:1601`) — the three depth modes (triage /
  review / comprehensive), each with a `breadth` and a severity `floor`.
- `entrypoints:` (`skills/manifest.yaml:1627`) — the list of
  `CollapsedEntrypoint` entries.

`router:`, `prepass:`, `synthesizer:`, and `modes:` each generate their own
skill/section with `built_from: []`, so they never trip drift when a
research doc changes — only a manifest edit regenerates them.

## Connected to

- **owns:** every `Lens` (via `skills:`), every `CollapsedEntrypoint` (via
  `entrypoints:`)
- **owned-by:** —
- **joins:** `docs/research/cluster-*.md` (each `Lens`'s `built_from` cites a
  `Category` there)
- **looks-like-but-is-not:** a `Lens` or `CollapsedEntrypoint` file itself —
  the manifest is the single declarative source; the `skills/<name>/` and
  `collapsed/skills/<name>/` folders are generated output, not hand-edited

## If you change this

- **Hits:** every generated `Lens`/`CollapsedEntrypoint` file once
  `python -m tooling.cli generate` runs; `docs/research/README.md`'s
  authoring rules govern what a manifest change is allowed to claim
- **Does not hit:** `docs/map/` itself — this map is hand-maintained and
  cites the manifest, it isn't regenerated from it

## Surfaces

| Surface | Role |
|---|---|
| `tooling/manifest.py` | parses/validates this file |
| `tooling/generate*.py` | reads it to emit `skills/`/`collapsed/` |
| `tooling/cli.py` (`generate`/`drift`/`eval`) | the commands that consume it |

## See

- Source: `skills/manifest.yaml`
- `docs/open-questions.md` D6, D9, D10, D12, D16
- Verified 2026-08-15 @ `ff7c642`
