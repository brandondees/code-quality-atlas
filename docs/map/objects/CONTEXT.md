# objects/ — one card per noun

Cluster by how an editor asks a question, not by the repo's own folder
layout — this map's clusters do not have to mirror the source tree's
directories.

## Clusters

| Cluster | Covers |
|---|---|
| `generation-pipeline/` | Manifest, Lens, Category, CollapsedEntrypoint — "what generates what" |
| `eval-hardening/` | EvalScenario, the A-E adversarial taxonomy — "what does a hardened suite look like" |
| `decisions-and-tracking/` | Decision, Gap, PlanDoc — "where is this question tracked, is it resolved" |

Command, Runbook, and Hook are cataloged in `_index.md` but don't yet have a
dedicated cluster — add one only once enough cards accumulate to need it,
not preemptively.

## Card status

Each line in `_index.md` carries a status: `stub` (named, not yet carded),
`verified` (carded, cited, dated against a commit), or `stale` (carded once,
since drifted — flagged, not deleted). Read the index before opening a
cluster folder; do not open all three clusters to find one noun.
