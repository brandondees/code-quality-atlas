# Protocol reference rows

Each JSON file is one Claude Code protocol round from PRs #602–#637, normalized by `atlas_reviewer.eval_harness.protocol_review`. `input.head_sha` is the pull's head at fetch time. `input.reviewed_commit` is the commit on the GitHub review, which is the commit that round judged. Findings are inline review comments whose `pull_request_review_id` is that review and whose first line is `**Severity · lens**`. Summaries are redacted and cut to 240 characters. `metadata.run` is how the round says it was run: `lens-fan-out` when the coverage section names lenses or says lenses were run, re-ran, or loaded; `coordinator-verified` when the body says that (lens fan-out did not finish); `unrecorded` when it says neither. `metadata.lenses_recorded` is the backticked lens names in that coverage section. A coordinator-verified row does not clear the fan-out criterion. These files have no `candidate`, so `eval --gate` on this directory exits 1.

Fetched 2026-11-12. 26 round file(s). Runs: lens-fan-out 20, coordinator-verified 0, unrecorded 6. Flagged coordinator-verified: none in this fetch.

#637 has no protocol review in this fetch, and #636 has rounds 1 and 2 only, so the coordinator-verified examples named for those pulls (#637 round 2 and #636 round 4) are not rows here.

## PRs in #602–#637 with no protocol round in this fetch

- #602: no protocol round by brandondees
- #603: no protocol round by brandondees
- #604: no protocol round by brandondees
- #605: no protocol round by brandondees
- #606: no protocol round by brandondees
- #607: no protocol round by brandondees
- #610: pull not read (gh: Not Found (HTTP 404))
- #611: pull not read (gh: Not Found (HTTP 404))
- #612: no protocol round by brandondees
- #613: no protocol round by brandondees
- #614: no protocol round by brandondees
- #615: pull not read (gh: Not Found (HTTP 404))
- #620: no protocol round by brandondees
- #624: pull not read (gh: Not Found (HTTP 404))
- #626: no protocol round by brandondees
- #627: no protocol round by brandondees
- #628: pull not read (gh: Not Found (HTTP 404))
- #629: no protocol round by brandondees
- #633: pull not read (gh: Not Found (HTTP 404))
- #637: no protocol round by brandondees
