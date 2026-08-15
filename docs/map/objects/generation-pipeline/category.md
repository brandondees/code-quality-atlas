---
type: "Category"
cluster: "generation-pipeline"
universe: live
status: verified
entity: "docs/research/cluster-*.md"
---

# Category

One research-derived heuristic group a `Lens` is `built_from` — e.g. `#2
Error handling & resilience` (`docs/research/cluster-1-correctness.md:50`).

## Why this shape

D3 (`docs/open-questions.md`) mapped the problem space before designing any
skill: research/taxonomy first, skills derived from it. A `Category` is that
map's addressable unit — the thing a `Lens`'s `built_from` cites, and the
thing a research edit changes when a lens needs regenerating (D6).

## Shape

- Lives as a `## #N Title` section inside one of the `docs/research/
  cluster-{1-7}-*.md` files (example: `## #2 Error handling & resilience`,
  `docs/research/cluster-1-correctness.md:50`).
- Numbered across the whole taxonomy (not per-file) — `#1`-`#4` live in
  `cluster-1-correctness.md`, later numbers in later cluster files, plus a
  handful promoted out-of-band by a `Decision` or `Gap` (e.g. `#32`
  promoted by D14/G2).
- `taxonomy_version` in `skills/manifest.yaml:1` tracks which taxonomy shape
  every `built_from` citation is checked against.

## Connected to

- **owns:** —
- **owned-by:** —
- **joins:** `Lens` (via `built_from`); a `Gap` sometimes promotes into a
  new `Category` (e.g. G2 → `#32 Agentic & tool-use safety`, D14)
- **looks-like-but-is-not:** `Gap` — a `Category` is a settled taxonomy
  entry a lens is built from; a `Gap` is an *open* structural question about
  the taxonomy that hasn't (or hasn't yet) become a category

## If you change this

- **Hits:** every `Lens` whose `built_from` cites this category (regenerate
  via `tooling.cli generate`/`drift`)
- **Does not hit:** categories in other cluster files, or lenses that don't
  cite this one

## Surfaces

| Surface | Role |
|---|---|
| `tooling/manifest.py` | validates `built_from` citations against category numbers |
| `tooling/generate.py` | pulls category prose into generated skill files |

## See

- Source: `docs/research/cluster-1-correctness.md` through `cluster-7-product.md`
- `docs/research/README.md`'s standing authoring rules
- `docs/open-questions.md` D3, D5, D13, D14, D15
- Verified 2026-08-15 @ `ff7c642`
