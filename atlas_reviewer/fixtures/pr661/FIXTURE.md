# pr661 — the recorded snapshot at #661's parity anchor

`eval-run --fixture atlas_reviewer/fixtures/pr661` reviews pull request
661 as it stood at the anchor the parity key grades: head `28854775`
(`28854775e5965eb554b368cc3a543969a635b681`, the round-5 head the
protocol review and the Nov 13–14 trials scored; the commits after it fix
three of the key's four defects, which is why the key re-anchored here),
against base `f82b4bf1` (the merge base `git merge-base` resolves for the
anchor, the same commit the old evalmix fixture carried). Built with
`atlas_reviewer snapshot-build` (see `snapshot.json` for the recorded
spec); the build's GitHub reads are the only network the fixture ever
involves — everything here is committed and the runs over it are offline.

## What the snapshot holds, and what it filters

- **Commits** — the anchor's lineage, `f82b4bf1..28854775`, 5 commits,
  **rebuilt from the commit objects** (`commits_source:
  git-reconstructed`): the branch was rebased after the anchor, so the
  PR's current listing shares no commit with it, and GitHub's listing
  could not be filtered — the lineage comes from the local git in the
  listing's shape (SHA, full message, committer date, parents), oldest
  first.
- **Remarks** — the reviews, review threads and conversation comments
  posted strictly **before the cutoff**, the anchor commit's committer
  date (`2026-11-13T19:59:56+00:00`): the prior review rounds (the
  owner's Nov 13 review, the CodeRabbit threads) reach the eval **only
  through this conversation block** — they are not synthesized into a
  `rounds.jsonl` (the owner's 2026-11-26 decision); this fixture ships
  no `rounds.jsonl`, so the run starts from an empty round log.
- **CI** — the check runs at the retained commits (`gate` run
  43498153209 green at the anchor, plus that push's `CodeRabbit` run),
  the workflow run at the anchor, its job, and the job's log. The
  branch's earlier runs belong to pre-rebase heads that are not in this
  PR's lineage, so they are not the snapshot's evidence — which is
  exactly the situation 661-m1 grades: the body cites a run
  (`61273b4f`, run 43429340358) the snapshot's evidence does not back.
- **Trees** — `source.tar.gz` is the head tree and
  `source-f82b4bf.tar.gz` the merge base's, each the **exact tarball
  bytes GitHub serves** for that revision — what a live review's
  tarball fetch receives, committed verbatim (the loader serves them at
  their SHAs; no loose anchor file ships for the repo's content gates to
  re-lint).
- **History** — `history.bundle` is the self-contained git bundle the
  staging's history fetch reads: `refs/heads/atlas-history` at the
  anchor head, no prerequisite (the staged repository's git is
  synthetic). `history-base.txt` carries the merge base beside it — the
  merged loader's contract (`history_source.fixture_history` loads the
  bundle only when both files are present) — and the offline stage-0
  test proves the eval path stages this history for the fixture.
- **Setup** — the fixture-root `REVIEW.md` and `agents-md.txt` are the
  default branch's files **as they stand today** (the owner's decision:
  setup uses today's default-branch `REVIEW.md`, which carries the setup
  spec), not the anchor-time copies; the anchor-time copies ride in the
  trees, where the merge-base config read takes them. The setup spec's
  `review_setup_files:` line declares `requirements.txt`, and that file
  is deliberately **not** recorded: the replayed setup phase would run
  the spec's install against a real package index, which the offline
  stage-0 contract cannot carry — the replay names the gap (the
  declared file is not served by the fixture's default branch) and no
  setup phase runs, the same named shape a fixture without the file
  produces; a production run on the live default branch does install
  it, and that fidelity gap is this fixture's recorded cost.

## The body

`pull.json`'s body is **the round-5 body**, taken from
`../parity-key/661-round5-body.md` (reconstructed from the merged body;
GitHub does not expose body-edit history) — the text 661-m1 grades and
the round-5 review actually read. The reconstruction file's leading
HTML comment is its provenance note for the parity key's human reader
(it names the graded finding and lists each deviation), so the builder
strips it from the replayed body — the reviewer reads the PR text alone,
its stale-CI citation included, never the note that says what the
defect is. The provenance lives here and in the parity key's own copy
of the file.

## Rebuilding

From the repo root:

```sh
python -m atlas_reviewer snapshot-build \
  --repo brandondees/code-quality-atlas --pr 661 \
  --head-sha 28854775e5965eb554b368cc3a543969a635b681 \
  --base-sha f82b4bf18b252daf76759f21d2b09ed4f09d39c9 \
  --branch cursor/full-pr-context-rounds-218c \
  --body-file atlas_reviewer/fixtures/parity-key/661-round5-body.md \
  --out atlas_reviewer/fixtures/pr661
```
