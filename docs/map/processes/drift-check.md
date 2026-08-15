---
type: process
status: verified
consumes: [Category, Manifest, Lens]
produces: []
---

# drift-check

Verify that every generated `Lens` still matches the `Category` research
and `Manifest` entry it was built from — a check, not a production step.

## Input → Movement → Output

Input: the current `skills/<name>/` files' stamped provenance hashes versus
the current content of the `Category` sections and `Manifest` entry each
one cites. Movement: `python -m tooling.cli drift` recomputes what each
skill *would* hash to today and diffs it against what's on disk. Output: a
clean "No drift" line, or a `DRIFT: <skill> — changed sources: #N` line per
out-of-sync skill and a non-zero exit code — no file is written either way.

## Why this shape

D6's derived-not-hand-maintained guarantee (see the `generate` process
card) only holds if a research edit that *should* trigger a regeneration
can't silently ship without one. `drift-check` is the trip wire: it runs in
CI on every PR (the `gate` check every PR in this map's own history cites
as passing) so a stale skill fails the build instead of drifting unnoticed
until someone reads `SKILL.md` against the docs by eye.

## Steps

1. `check_drift` walks `skills_root` and recomputes each skill's provenance
   hash from its current `built_from` sources (`tooling/drift.py`).
2. `tooling/cli.py:81-93` — no drift: print "No drift..." and exit 0; drift
   found: print one `DRIFT:` line per affected skill naming the changed
   `Category` numbers, exit 1.
3. A malformed manifest or missing source raises `DriftError` and prints
   `ERROR: ...` rather than a false "No drift" (`tooling/cli.py:84-86`).

## If you change this

- **Hits:** nothing — this movement only reads and reports; a failing run
  blocks a PR's CI gate until `generate` (see that process card) is re-run
- **Does not hit:** any file on disk

## Surfaces

| Surface | Role |
|---|---|
| `tooling/drift.py` | the hash-comparison logic |
| CI's `gate` check | runs this on every PR |

## See

- Objects: `Manifest`, `Lens`, `Category`
- Source: `tooling/cli.py:81-93`, `tooling/drift.py`
- `docs/runbooks/regenerating-skills.md`
- Verified 2026-08-15 @ `1ed3006`
