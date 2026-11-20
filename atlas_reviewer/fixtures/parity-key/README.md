# Parity key

The directory holds the seven protocol Minors. The gate grades all seven.
One JSON file is one pull request. A later protocol-reviewed pull request
joins the key by adding another file in this directory; ids must stay unique.
The loader is `atlas_reviewer.parity_key.load_key`. It checks the schema.
The grade that compares a verified finding with these spans is a later layer.

The spans were read at the `reviewed_commit` in each file. The Nov 14 trial
scorer and `docs/plans/2026-11-13-agentic-execution-and-ci-evidence.md` name
the Minors. Each finding's `source` says why its span is that range. Nothing
here is a fresh measurement of a model.

## What a record stores

A record has one or more `spans`. A file span has a `path`, a `line`, and an
`end_line` at or after that line. `encloses` is the function or the decision
entry that contains the span. `pull_request.body` has no line. Its
`citations` are the body lines a quote has to contain. A file record has no
citation. `needs` is what reaching the finding took: `ci`, `read`,
`run_tests`, or `mutate`. `lenses` names the owner lens.

## The seven findings

| Id | Reviewed commit | Span | What the record holds |
|---|---|---|---|
| `661-m1` | `674071a91513b4774c82350fb757d9c085f10baf` | `pull_request.body` | Quotes the gate line or the pre-rebase stack line. A paraphrase is not a citation. |
| `661-m2` | same | `atlas_reviewer/rounds.py` 202–209 | The unreadable omission. `coordinator.py` 725–740 does not format it. |
| `661-m3` | same | `atlas_reviewer/rounds.py` 184–186 | `break` after `continue` in `prior_blocks`. |
| `661-m4` | same | `atlas_reviewer/rounds.py` 210–219 | The `findings_omitted` gate. The span starts at 210 so it does not cover 661-m2. |
| `640-m1` | `72c56eb24d16025719c4d58ba921eadef94bb8a8` | `atlas_reviewer/service_queue.py` 329 | `begin_post`'s cancel check. `still_current` is a different method. |
| `640-m2` | same | `atlas_reviewer/service_post.py` 232–234 | `check is None` raises `PostHookMissing`. The caller records the refusal. |
| `640-m3` | same | `docs/open-questions.md` 62, or `atlas_reviewer/README.md` 14 | Both lines already name D48. Either citation counts. |

Line numbers are the reviewed commit's, not current main's.
