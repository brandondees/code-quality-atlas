# pr640 — the recorded snapshot at #640's parity anchor

`eval-run --fixture atlas_reviewer/fixtures/pr640` reviews pull request 640
as it stood at the anchor the parity key grades: head `0fe45e5e`
(`0fe45e5ea79f3abd8e07488a01b623186df96692`, the head the Nov 14 trial
reviewed), against base `771925a5` (main's tip the branch was cut from).
Built with `atlas_reviewer snapshot-build` (see `snapshot.json` for the
recorded spec); the build's GitHub reads are the only network the fixture
ever involves — everything here is committed and the runs over it are
offline.

## What the snapshot holds, and what it filters

- **Commits** — the anchor's lineage, `771925a5..0fe45e5e`, 15 commits,
  each from the PR's current listing (the anchor was merged, so the
  listing still covers it). The branch's later pushes are not part of
  the snapshot.
- **Remarks** — the reviews, review threads and conversation comments
  posted strictly **before the cutoff**, the anchor commit's committer
  date (`2026-11-13T19:33:07+00:00`): what the anchor's reviewer saw.
  The two `cursor[bot]` lifecycle reviews posted seconds after the push
  are outside it. The prior review rounds reach the eval **only through
  this conversation block** — they are not synthesized into a
  `rounds.jsonl` (the owner's 2026-11-26 decision); this fixture ships
  no `rounds.jsonl`, so the run starts from an empty round log.
- **CI** — the check runs at the retained commits (4: `gate` and
  `CodeRabbit` at the last two commits; the branch's earlier pushes were
  rebased away, so their runs belong to commits that are not in this
  PR), the workflow runs at the retained commits (both green, including
  gate run 43493645208 at the anchor), each run's jobs and artifact
  listing, and the jobs' logs where GitHub still serves them
  (`job-log-*.txt`, the anchor run's and the previous commit's).
- **Trees** — `source.tar.gz` is the head tree and
  `source-771925a.tar.gz` the merge base's, each the **exact tarball
  bytes GitHub serves** for that revision — what a live review's
  tarball fetch receives, committed verbatim (the loader serves them at
  their SHAs; no loose anchor file ships for the repo's content gates to
  re-lint).
- **History** — `history.bundle` is the self-contained git bundle the
  staging's history fetch reads: `refs/heads/atlas-history` at the
  anchor head, no prerequisite (the staged repository's git is
  synthetic). The eval loader that fills the bridge's history tools from
  it is the git-history slice's wiring (the brief's S1); until that
  lands the file is the fixture's record of the PR's history, in the
  README-documented shape.
- **Setup** — the fixture-root `REVIEW.md` and `agents-md.txt` are the
  default branch's files **as they stand today** (the owner's decision:
  setup uses today's default-branch `REVIEW.md`, which carries the
  setup spec), not the anchor-time copies; the anchor-time copies ride
  in the trees, where the merge-base config read takes them.

## The body

`pull.json`'s body is GitHub's **current** body for #640. GitHub does
not expose body-edit history, and no reconstruction of the anchor-time
body exists for this PR (unlike #661's round-5 body); the merged body
was later edited — its CI line cites the merged head's run, a commit
outside this snapshot — so a lens that checks the body's CI citations
against the snapshot's evidence can flag exactly that staleness. Treat
that as the known fidelity limit it is, not as a graded finding.

## Rebuilding

From the repo root:

```sh
python -m atlas_reviewer snapshot-build \
  --repo brandondees/code-quality-atlas --pr 640 \
  --head-sha 0fe45e5ea79f3abd8e07488a01b623186df96692 \
  --base-sha 771925a538d6744b6017175e8fe5f170abf27a6d \
  --branch cursor/comment-posting-1b42 \
  --out atlas_reviewer/fixtures/pr640
```
