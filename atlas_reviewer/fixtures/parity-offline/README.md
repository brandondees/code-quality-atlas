# Recorded parity runs

Six run files the offline command scores against the parity key. Three
repetitions of pull request #640 and three of #661. Each one finds every
key finding for its pull request and carries one extra nit, so a clean
`eval-parity --runs` of this directory exits 0 and the report shows the
extra.

These are scorer fixtures. They are not output from a model, and they are
not a measurement that any model passed. The comparison fields — cost,
wall time, cache reads, cache writes, clean lenses, false-positive Majors,
previous-turn misses — are null on purpose. A later A/B fills those fields
in its own run files. Nothing here is that run.
