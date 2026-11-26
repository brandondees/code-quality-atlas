# Recorded parity runs

Nine run files the offline command scores against the parity key. Three
repetitions each of pull requests #640, #661 and #801. Each one finds every
key finding for its pull request and carries one extra nit, so a clean
`eval-parity --runs` of this directory exits 0 and the report shows the
extra.

These are scorer fixtures. They are not output from a model, and they are
not a measurement that any model passed. The comparison fields — cost,
wall time, cache reads, cache writes, clean lenses, false-positive Majors,
previous-turn misses — are null on purpose. A later A/B fills those fields
in its own run files. Nothing here is that run.

The #661 runs are recorded at the key's re-anchored head, the round-5
commit `28854775` (D71's 2026-11-26 update): their `head_sha` matches the
key's `reviewed_commit`, and their findings cite the spans re-read there.
