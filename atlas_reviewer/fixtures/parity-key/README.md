# Parity key

The directory holds eleven graded findings: the seven protocol Minors, and
the four secret-echo Majors pull request 801 seeds (issue #814). The gate
grades all eleven. Pull request 640 is anchored on `0fe45e5e`, the head the
Nov 14 trial reviewed. `72c56eb` is the later merged head, and two of the
defects were fixed after that review.
One JSON file is one pull request. A later protocol-reviewed pull request
joins the key by adding another file in this directory; ids must stay unique.
The loader is `atlas_reviewer.parity_key.load_key`. It checks the schema.
`grade_findings` compares one list of verified findings with these spans.
`score_parity` counts a finding across recorded runs. `eval-parity` reads
a directory of run files and writes that report.

The spans were read at the `reviewed_commit` in each file. The Nov 14 trial
scorer and `docs/plans/2026-11-13-agentic-execution-and-ci-evidence.md` name
the Minors; issue #814's review record names the 801 echoes. Each finding's
`source` says why its span is that range. Nothing here is a fresh
measurement of a model.

## What a record stores

A record has one or more `spans`. A file span has a `path`, a `line`, and an
`end_line` at or after that line. `encloses` is the function or the decision
entry that contains the span. `pull_request.body` has no line. Its
`citations` are the body lines a quote has to contain. A file record has no
citation. `needs` is what reaching the finding took: `ci`, `read`,
`run_tests`, or `mutate`. `lenses` names the owner lens.

## The findings

| Id | Reviewed commit | Span | What the record holds |
|---|---|---|---|
| `661-m1` | `674071a91513b4774c82350fb757d9c085f10baf` | `pull_request.body` | Quotes the gate line or the pre-rebase stack line. A paraphrase is not a citation. |
| `661-m2` | same | `atlas_reviewer/rounds.py` 202–209 | The unreadable omission. `coordinator.py` 725–740 does not format it. |
| `661-m3` | same | `atlas_reviewer/rounds.py` 184–186 | `break` after `continue` in `prior_blocks`. |
| `661-m4` | same | `atlas_reviewer/rounds.py` 210–219 | The `findings_omitted` gate. The span starts at 210 so it does not cover 661-m2. |
| `640-m1` | `0fe45e5ea79f3abd8e07488a01b623186df96692` | `atlas_reviewer/service_queue.py` 329 | `begin_post`'s cancel check. `still_current` is a different method. |
| `640-m2` | same | `atlas_reviewer/service_post.py` 229–231 | `check is not None` skips the head check when the hook is missing. `post` is 217–236. |
| `640-m3` | same | `docs/open-questions.md` 62, or `atlas_reviewer/README.md` 13–15 | Neither line says D46 amends D48. Either citation counts. |
| `801-m1` | `186e09f2944e561815462eb5d9795dba4229c488` | `atlas_reviewer/funding.py` 129–131 | The duplicate-name refusal formats the document's `{source.name!r}`. |
| `801-m2` | same | `atlas_reviewer/funding.py` 207 | The duplicate-field refusal formats the document's `{key!r}`. |
| `801-m3` | same | `atlas_reviewer/funding.py` 219–222 | The field-shape refusal formats `sorted(extra)` and `sorted(missing)`. |
| `801-m4` | same | `atlas_reviewer/funding.py` 267 | The duplicate-provider-slug refusal formats the document's `{slug!r}`. |

Line numbers are the reviewed commit's, not current main's. Pull request 661 was
re-read at `674071a9`. The break, the unreadable count, and the
omitted-findings gate are those lines. Pull request 801's four echo sites are
the funding-refusal siblings the `_bool` value-echo fix in the same review
round left behind; the round-6 fix `9ba4759d` removed all four, so the key's
spans only exist at the recorded head.

## How a finding is graded

`SPAN_SLACK` is 0. Overlap means the two spans share a line. A five-line
window would let the last line of 661-m2 also match 661-m4, and the two
grades would depend on which finding was listed first.

A candidate is **found** when it is verified, its severity is at least
minor, and its span sits inside a key span on the same path. Citing the
whole enclosing function, or the whole file, overlaps the defect and is
**partial**. A nit on the defect is partial. So is a verified line in the
enclosing function that misses the defect. For `pull_request.body` the
quote has to contain one citation as an exact substring. A paraphrase is
lost. Severity is compared case-insensitively. Partial does not count
toward a pass. Anything else, including a finding that was not verified
or a severity the record does not name, is **lost**. `grade_findings`
matches by candidate index. Each candidate is used at most once. Two
candidates that cite one span for one key finding are two records: one
matches, and the other is an extra. That extra counts in `extra_majors`
when its severity is major. An unused blocker is an extra and is not a
major.
