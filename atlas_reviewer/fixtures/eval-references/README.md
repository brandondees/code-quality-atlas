# Protocol reference rows

Built by `atlas_reviewer.eval_harness.reference_row` from the pull, its reviews, and the inline comments whose `pull_request_review_id` matches. `input.reviewed_commit` is the review's `commit_id`. `metadata.review_state` is the GitHub review state. `metadata.run` is `lens-fan-out`, `coordinator-verified`, or `unrecorded`. `metadata.parse_gap` is true when the heading announces findings and none were parsed. Summaries are redacted and cut to 240 characters. These files have no `candidate`, so `eval --gate` exits 1.

Fetched 2026-11-12. 26 round file(s). Runs: lens-fan-out 21, coordinator-verified 0, unrecorded 5. Parse gaps: none.

Pull 637 has no protocol review in this fetch, and pull 636 has rounds 1 and 2 only, so the coordinator-verified examples named for those pulls (637 round 2 and 636 round 4) are not rows here.

## PRs in #602-#637 with no protocol round in this fetch

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
