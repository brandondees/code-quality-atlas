# Parity key

The seven protocol Minors the parity gate scores a recorded review against.
One JSON file is one pull request. A later protocol-reviewed pull request
joins the key by adding another file in this directory; ids must stay unique.
The loader is `atlas_reviewer.parity_key.load_key`. It checks the schema.
The grade that reads `match`, `markers` and `line`, and the k-of-3 pass
rule, are later layers.

The wording is the plan
`docs/plans/2026-11-13-agentic-execution-and-ci-evidence.md` and issue #708
comment 6902255823. The Nov 14 report `mt14/report-draft.md` is not in this
repo. Nothing here is a fresh measurement of a model.

## What a record stores

`match` is `place` or `markers`. A place record has a line on `path`. A
markers record has one or more markers and may omit the line. `needs` is
what reaching the finding took: `ci`, `read`, `run_tests`, or `mutate`.
`path: unlocated` means this repo's record names no source path.

## The seven findings

| Id | Reviewed commit | Anchor | What the record actually says |
|---|---|---|---|
| `661-m1` | `674071a91513b4774c82350fb757d9c085f10baf` | no source line; markers `stale` and `stack` | The pull request body's CI and stack lines are stale. Reaching it needs CI evidence. |
| `661-m2` | same | `atlas_reviewer/rounds.py:207` | Issue #708 names it `unreadable shown as "1 line"`. The line is the omission text `"{unreadable} line(s) could not be parsed"`. |
| `661-m3` | same | `atlas_reviewer/rounds.py:186` | `break` instead of `continue` hides a current-head round. The lines above it `continue` for a superseded record that does not fit. |
| `661-m4` | same | `atlas_reviewer/rounds.py:211` | The superseded `findings_omitted` gate is unpinned. Reaching it needs `mutate`. |
| `640-m1` | `72c56eb24d16025719c4d58ba921eadef94bb8a8` | `atlas_reviewer/service_queue.py:329` | The `begin_post` cancel check is unpinned. Reaching it needs `mutate`. |
| `640-m2` | same | no path in the repo record | The plan says "reading a file the model skipped" and does not name the file. Markers are `skipped` and `file`. |
| `640-m3` | same | no line; markers `decision-lifecycle` | The plan says "a decision-lifecycle body" and does not quote a defect. `reviewing-decision-lifecycle` is the lens #708 says was not picked. D46 at the reviewed head is `docs/open-questions.md` line 62 and is one physical line, so a five-line window would also cover neighboring decisions. The record stores markers and no line. |

Line numbers are the reviewed commit's, not current main's.
