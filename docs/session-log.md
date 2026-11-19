# Session Log

Chronological record of how the research evolved. Newest at the bottom.

**Rotation policy (#467, 2026-09-08; half-month rule added 2026-09-25, #520):**
once this live file's entries exceed roughly 1,500 lines, move the oldest
completed calendar month(s) verbatim into a new
`docs/session-log-<start>-to-<end>.md` archive, named by the range it covers,
and leave only this pointer behind: no summarizing, no trimming. The same
pattern extracted [`eval-hardening-campaign-log.md`](eval-hardening-campaign-log.md)
from `open-questions.md` (#426). **If one month alone pushes the file past the
threshold before it ends**, don't wait for month-end. Move that month's
completed first half (days 1–15) instead, named
`session-log-<YYYY-MM>-01-to-15.md`; the second half follows once the month
closes. Archives so far:
[`session-log-2026-06-to-08.md`](session-log-2026-06-to-08.md) (June–August,
the first rotation) and
[`session-log-2026-09-01-to-15.md`](session-log-2026-09-01-to-15.md) (the first
half-month rotation). This file carries 2026-09-16 onward.

---

## 2026-09-18 — #510, #511: `load_evals` crashed instead of reporting INVALID on a malformed `scenarios`/`skills` shape

Same bug class as #106/#268 for a shape neither covered: an `eval.json`
with `scenarios: null`, a bare string, or a list containing a non-dict
entry escaped `validate_evals` as an uncaught `TypeError`/`AttributeError`,
aborting the whole `tooling.cli eval` batch instead of reporting a clean
`INVALID` line for just that one skill. Fixed `tooling/evals.py` to
validate the shape explicitly before iterating. Two review-driven
follow-ups landed in the same PR: a missing direct regression test for the
`skills`-list isinstance-per-element check (self-review), and a
`scenarios` test case mixing one bad entry among otherwise-valid ones —
the existing test used an all-bad list, which `coverage.py --cov-branch`
correctly flagged as not distinctly proving the `all(isinstance(s, dict)
...)` guard against a *mixed* list (dees-bot round-1 finding on #511).

## 2026-09-18 (same day) — #512: a `mypy` gate for `tooling/`, closing the dogfooding gap D19 had left open

`tooling/` (~150KB across `cli.py`, `manifest.py`, `drift.py`,
`generate_*.py`, `run_evals.py`, `sections.py`, `frontmatter.py`,
`evals.py`) is fully type-annotated (every module opens with `from
__future__ import annotations`) but nothing in this repo's own CI ever
type-checked it — this suite's own review content tells *consumer* repos
to run mypy/pyright, while this repo's own CI didn't. Added `mypy>=2.0.0`
and `types-PyYAML` to `requirements.in`/`.txt` (hash-pinned, regenerated
via the same `pip-compile` process CI's own consistency gate uses), a
`[tool.mypy]` table in `pyproject.toml` (scoped to `tooling/`,
`python_version = "3.12"`), and a "type-check (mypy)" step in `ci.yml`'s
gate job. Fixed the 28 errors mypy surfaced, mostly `Optional` manifest
fields (`manifest.router`/`.prepass`/`.synthesizer`) unpacked without
narrowing across a function boundary — every call site already guards on
`is not None` before calling in, so each fix is an `assert x is not None`
documenting an already-enforced invariant for the type checker, not new
runtime error handling for a case that can't happen. Documented the new
command in `CLAUDE.md`/`AGENTS.md`'s Development setup block.

Two round-1 review fixes landed in the same PR: adding `mypy` transitively
pulled in `pathspec`, which reports an MPL-2.0 license the compatibility
gate's allow-only list didn't cover — allowed it after confirming MPL-2.0
is weak, file-level copyleft that only obligates redistributing *modified*
MPL-covered files, and `pathspec` is a CI-only tool dependency never
imported into this repo's own MIT-licensed `tooling/` (D11); and
`requirements.txt`'s regenerated pip-compile header said "Python 3.11"
because the authoring sandbox's `python3` resolved to 3.11.15 rather than
the project's pinned 3.12 — exactly the drift class `pyproject.toml`'s own
`[project]` comment calls out by name — fixed by regenerating under
`/usr/bin/python3.12` and re-verifying the full local gate suite (mypy,
ruff, pytest, `pip-licenses`, the requirements-in-sync check) under a
fresh 3.12 venv matching CI's actual interpreter.

## 2026-09-19 — D19 marked superseded: mypy adoption (#512/PR #514) had reversed its own premise without updating the decision record

A scheduled maintenance audit cross-checked `ci.yml` against
`docs/open-questions.md` and found D19's central claim ("no `mypy`/
`pyright` run locally or in CI") had gone false the moment the previous
day's mypy gate (PR #514, commit `c966e29`) merged — `CLAUDE.md`'s
Development setup section already documented `mypy` as a standard
command, but nothing had touched the decision record itself. Added a
"Superseded (2026-09-19)" addendum to D19 in `docs/open-questions.md`
stating the operative state plainly (mypy runs in CI, scoped to
`tooling/`) while leaving D19's original text as the historical record of
the deferral — the same treatment D21 already gives a reasoning-only
addendum, and the exact "decision record went stale the moment its own
premise reversed" pattern D19's own closing sentence was written to
prevent recurring.

**Backfill note (2026-09-20, #516):** this entry and the two above were
written retroactively during #516/#513's fix (the mechanical currency
gate below) — `docs/session-log.md` had gone stale for these three days'
worth of substantive commits (PRs #514/#515) until this pass, the exact
recurring gap #513/#516 exist to catch mechanically rather than relying on
each session remembering to update this file.

## 2026-09-20 — #517, #518: two code-actionable findings from the weekly self-audit (#347)

A fresh "what's next" session with no named task went to #347's latest
sweep (filed the same day, #516-#520) rather than `docs/open-questions.md`'s
"genuinely still open" list, which is all owner-gated design questions.
Picked the two fully-specified, code-ready findings; left #519/#520 (marked
"needs a decision from the doc's owner" in their own text) and the
already-standing #492/#493 (repo-Settings actions only `brandondees` can
take) alone.

**#517.** The 2026-09-05 changelog entry describing issue #394's redaction
of personal/machine identifiers from `docs/self-hosted-runners.md`
reproduced, in its own narrative prose, the exact identifiers it said were
removed — an OS account name/home-directory pattern and two VM hostnames,
still spelled out verbatim at what was then
`docs/session-log.md:915-916`. (Writing them out again right here would
repeat the same mistake this fix corrects, so this entry names the class
of leak rather than quoting the strings — see
`tests/test_no_private_repo_names_in_runner_docs.py`'s `_PRIVATE_STRINGS`
for the literal values, which is the one legitimate place they belong.)
That test's 2026-09-15 widening (#495, PR #508) scans the whole tracked
tree, but `_PRIVATE_STRINGS` never listed these three strings, so this
exact passage survived two subsequent #394 audit sweeps undetected.
Genericized the passage the same way the original fix genericized
`self-hosted-runners.md` (`<runner-user>`, `<vm-name>`, `<old-vm-name>`)
and added the three missing strings to `_PRIVATE_STRINGS` so this class
can't silently reappear a third time. Confirmed no other tracked file
contained them before adding them to the guard. **Caught by the guard's
own new run in this PR's CI** — the first draft of this very changelog
entry quoted the strings while describing the fix, which the widened test
correctly flagged before merge.

**#518.** `tests/test_license_paths_exhaustive.py` only reasons about
top-level git-tracked directories, but `LICENSE`'s own prose carries two
*nested* MIT exceptions inside otherwise-CC-BY buckets:
`.claude/skills/icm-architect/` (within `.claude/`) and
`collapsed/hooks/` + `collapsed/.claude-plugin/` (within `collapsed/`).
Nothing machine-checked that these nested exceptions still hold — exactly
the "nested directory, different license than its parent bucket" shape
the top-level test exists to catch, one level up. Verified as of HEAD the
content was already self-consistent (a coverage gap, not live drift).
Added `test_nested_mit_exceptions_still_hold`, asserting:
`.claude/skills/icm-architect/LICENSE` exists, reads as an MIT license
text, and still attributes Jake Van Clief; its `NOTICE.md` still states
MIT; every tracked script under `collapsed/hooks/` still carries the
`SPDX-License-Identifier: MIT` header; and
`collapsed/.claude-plugin/plugin.json` still declares
`"license": "MIT AND CC-BY-4.0"`.

Verified: `pytest tests/ -q --cov=tooling` 797 passed, 14 skipped, 95.00%
coverage (≥94% floor); `ruff check .`/`ruff format --check .` clean;
`mypy` clean; `python -m tooling.cli drift` clean (44/44 skills in sync);
`npx markdownlint-cli2 docs/session-log.md` clean.

## 2026-09-20 (same day) — #513, #516: backfilled the 09-16–09-19 gap and added a mechanical currency gate so this stops being manual

With PR #521 merged, picked up the next roadmap item: #513 (opened
2026-09-18) and #516 (filed by the same-day weekly audit, #347) both flag
the *same* recurring defect — `docs/session-log.md` going stale for
multiple days of substantive work with nothing catching it until a later
scheduled audit happens to notice. This is the third recorded instance of
this exact gap. Both issues propose the same fix in two parts.

**Part 1 — backfill.** `docs/session-log.md`'s last entry before this
backfill (and before the earlier #517/#518 entry above) was 2026-09-15,
but PRs #510/#511 (`load_evals` shape validation), #514 (the `mypy`
gate), and #515 (the D19-superseded addendum) all landed on 2026-09-17
through 09-19 with no corresponding entries. Added the three
backfill entries above (inserted in chronological order ahead of today's
earlier #517/#518 entry, not appended after it) summarizing each from
its commits' own messages.

**Part 2 — the mechanical gate.** Added `tests/test_session_log_currency.py`:
compares `docs/session-log.md`'s newest `## YYYY-MM-DD` header against
today's date, failing if the gap exceeds a 5-day slack. Deliberately
**not** git-log-based, despite both issues suggesting "the latest commit
touching a substantive path-set" as the comparison point — this repo's CI
checks out with `fetch-depth: 2` (too shallow to reliably walk back
further), and a `pull_request` run's checked-out HEAD is GitHub's
synthetic merge-ref commit, whose message and parentage don't reliably
reflect what the PR itself touched. Comparing the log's header to
wall-clock "today" needs no git history at all and is accurate to within
hours of the actual landing commit on every push-triggered run. Documented
trade-off in the test's own docstring: a dependency-only PR landing after
a genuinely quiet stretch could trip this through no fault of its own —
accepted as the same "good enough, mechanically checked" trade-off
`test_ci_python_filter_covers_known_reads.py` already makes explicitly for
a different guard.

Also added `docs/session-log.md` to `ci.yml`'s `python:` path filter (it
wasn't there) and to `test_ci_python_filter_covers_known_reads.py`'s
`_KNOWN_EXTERNAL_READS` inventory — without this, a PR whose only change
*is* the backfill remediation this test asks for (a session-log-only diff)
would never actually run the `tests` step, silently reporting a `skipped`
conclusion that branch protection treats as passing instead of verifying
the fix.

This resolves both #513 and #516 — they're the same defect with the same
fix, so closing #513 as fixed-alongside-#516 rather than superseded, since
both land in the one PR.

Verified: `pytest tests/ -q --cov=tooling` 800 passed, 14 skipped, 95%
coverage (≥94% floor); `ruff check .`/`ruff format --check .` clean;
`mypy` clean; `python -m tooling.cli drift` clean (44/44 skills in sync);
`python -c "import yaml; yaml.safe_load(...)"` confirmed `ci.yml` still
parses after the filter edit; `npx markdownlint-cli2 docs/session-log.md`
clean.

## 2026-09-20 (same day) — #488: fix-verification rounds must re-derive the threat model, not inherit a fix's own "closes it" framing

With PRs #521/#522 merged, picked up #488 — the last fully code-actionable,
non-owner-gated item off #347's queue (#519 and #520 need an owner
decision; #492 and #493 need a GitHub Settings action only `brandondees`
can take; #446 needs its own investigation into whether a meta-review
eval is a per-entrypoint or a new transcript-level category, left for a
future session).

**The gap.** PR #483 fixed #471 (a fork PR's own `if:` gate on a
self-hosted runner was editable by that same fork PR) by replacing it with
a conditional `runs-on:` expression. The atlas's own round-1 review of
that fix ran the right lenses and accepted the commit's "closes it
structurally" framing at face value — but the new `runs-on:` expression
lives in the exact same fork-editable file the old `if:` gate did, so the
same attacker could revert it in the same diff. CodeRabbit caught it;
round-2 corrected course and credited the catch. The underlying lens,
`auditing-deployment-and-trust-boundaries`, had already articulated this
exact attacker model once, cold, in the audit that produced #471 — round
1 of the *fix's* review just never re-ran that enumeration against the
new code, judging only the new conditional's syntax and inheriting the
fix's own claim about what threat it defeats.

**The fix.** Added a third ★ heuristic to `docs/research/cluster-4-
runtime.md#45` (the source category `auditing-deployment-and-trust-
boundaries` builds from): re-derive the threat model — same attacker, does
the same class of edit still reach the same target — whenever a diff
claims to close a previously-filed trust-boundary finding, rather than
accepting the PR's framing; a gate reworded into a different in-tree
conditional that still lives in the same trust domain isn't closed, it
needs a boundary genuinely outside that domain or an explicit accepted-
risk statement. Cites #488/PR #483 as the field-confirming instance,
matching how #45's own intro cites #191. Added a new eval scenario
(`skills/auditing-deployment-and-trust-boundaries/evals/eval.json`,
20 → 21) modeling the exact PR #483 shape generically, so a future
regression here is a failing eval, not a fourth round.

Ran the full regenerate-and-vendor loop per
[`docs/runbooks/regenerating-skills.md`](runbooks/regenerating-skills.md):
`tooling.cli generate` (SKILL.md + the `auditing-a-repository` collapsed
lens body regenerated, provenance hash re-stamped), `tooling.cli drift`
(clean), `tooling/vendor-skills.sh .` (re-vendored `.claude/skills/`'s
copy of this one lens).

Verified: `pytest tests/ -q --cov=tooling` 803 passed, 14 skipped, 95%
coverage (≥94% floor) — the one local failure
(`test_no_warning_for_a_clean_git_target`) is this repo's own working
tree carrying uncommitted changes at test-run time (the vendor script's
warning checks the *source* repo's git status), not a real regression;
`ruff check .`/`ruff format --check .` clean; `mypy` clean;
`python -m tooling.cli eval` — `auditing-deployment-and-trust-boundaries`
21 scenarios, structurally valid; `python -m tooling.cli drift` clean
(44/44 skills in sync).

**Round-2 self-correction (PR #523, before merge):** the atlas's own
round-2 review of this PR independently verified a point CodeRabbit's
summary had raised — the new heuristic's own eval scenario listed
"branch protection on the workflow file" as an example of a boundary
outside the fork's trust domain, but that's false for exactly the case
the heuristic exists to catch: a `pull_request`-triggered workflow runs
from the PR's own head commit regardless of what protection the target
branch carries. Fixed the same overgeneralization in both places it
appeared — the research heuristic (`docs/research/cluster-4-
runtime.md#45`) and the eval scenario's grading criteria — narrowing the
"boundary outside the trust domain" examples to ones that actually gate
the run itself before it starts, and adding an explicit note that target-
branch protection is not such a boundary. Re-verified: `pytest tests/ -q
--cov=tooling` (803 passed), `python -m tooling.cli eval` (21 scenarios,
structurally valid), `python -m tooling.cli drift` clean.

## 2026-09-25 — #527 (backfill): the quote-the-line evidence gate

*(Backfilled — PR #530 merged without its own entry.)* `synthesizing-review-findings`'s
finding contract required a `location` but never a quote of what is actually
there, so a finding could name a plausible `file:line` the reviewer had never
read. PR #530 added an `evidence` field — the verbatim current line(s) — and a
*Reviewer discipline* paragraph (the quote-the-line gate), threaded
`<evidence>` through every ranked section of the output template, and added two
eval scenarios (the required branch and the `boundary:`/`component:`
exemption). CodeRabbit's round-1 review found two Majors, both fixed before
merge: the exemption referred to a "repo-audit finding" shape the location
contract never defined (a bare file path is now an explicit third location
shape), and a finding about *deleted* code could never satisfy a gate that only
read the current file (it now quotes the diff's deleted side, named as such).

## 2026-09-25 (same day) — #525: an unexecuted, falsifiable claim is provisional, not affirmed

A fresh "what's next?" session picked #525 from the self-improvement
routine's 09-21 batch (#524-#526). The issue: in several projects, a review
affirmed a concrete claim it had no way to check from a static diff — a
migration "auto-applies, no drift", a bulkhead cap and a cache byte-bound
"holding at production scale", suppressions "confirmed dead by a full
type-check, 0 errors" — and the claim was false. In the clearest case the
review *disclosed* it had not reproduced the run and approved anyway, so the
disclosure was a caveat rather than an input to the verdict.

**The fix, at the four places a verdict can rest on such a claim:**

- **Synthesizer** (`tooling/generate_synthesizer.py`) — a new *Reviewer
  discipline* paragraph: a load-bearing, falsifiable claim this review did
  not run, reproduce, or measure is reported as **provisional pending
  verification**, naming what would settle it and who can run it; it caps
  the verdict at *approve with changes* (the verification is the change),
  or *block* where the claim is all that stands between the change and a
  Blocker-class failure. A reported run counts only for files in its
  scope. A CI result on the exact head commit whose scope covers the code
  is evidence and is affirmed normally. The *Verdict* step now points at
  the rule so it can't be read past.
- **Tool-grounding pre-pass** (`skills/manifest.yaml` `prepass.rules`) — "A
  reported run is a claim, not evidence", including the vacuous-scope trap
  (a tool config that excludes the file reports zero errors about it).
- **#20** (`docs/research/cluster-5-verification.md`) — trace whether a new
  migration is actually reached by what the deploy runs, rather than
  accepting "applies on deploy".
- **#28** (`docs/research/cluster-4-runtime.md`) — evaluate a numeric bound
  at the real production parameters; a cap can be inert and a
  microbenchmark's per-item size can undercount resident memory.

Five eval scenarios: two for the synthesizer (unverified claim → not a plain
approve; CI-verified claim → approve, no redundant demand), one for the
pre-pass (a pyright `include` that doesn't cover the edited file), one each
for migration (a migration placed outside the deploy runner's directory) and
resilience (a `min(64, cpu*32)` cap evaluated at the production vCPU count).
Two regression tests in `tests/test_generate.py`. Regenerated, re-vendored,
drift clean.

## 2026-09-25 (same day) — #524: sweep a confirmed defect's shape before closing it

Second item from the same "what's next?" session, right after #525 (PR #531)
merged. The issue: across several projects, a lens confirmed a defect with a
clearly nameable construct — a rate-limit record call reachable on only one
branch, an auth header re-sent across a cross-host redirect, a shell pipeline
masking an early-stage failure, a response path missing a header — and the fix
landed at the one site the diff touched. The identical construct elsewhere was
found later, by hand, as separately filed issues. In three of four cases the
reviewer had *named* the pattern in its own commentary; searching for it simply
wasn't part of the procedure.

**The fix, in the synthesizer** (`tooling/generate_synthesizer.py`), because it
applies to every lens, not just the three the evidence happened to name
(`sweeping-for-security`, `hunting-silent-failures`,
`reviewing-resilience-and-scalability`), and the synthesizer is bundled into
every collapsed entrypoint:

- A new *Reviewer discipline* rule: once a lens confirms a defect with a
  reusable shape, run a targeted grep/AST query for that construct over the
  whole tree. Report the hits as that finding's `siblings` (each held to the
  quote-the-line gate), stating the pattern searched and the scope covered, so
  a partial sweep can't read as a complete one. Siblings are pre-existing:
  routed to the implementer, not verdict-setting. The exception is a change
  that claims to close the whole defect class; there an unfixed sibling makes
  the claim incomplete, which caps the verdict at *approve with changes*. A
  shape no text or AST query can find is reported as not swept, never as swept
  clean.
- A `siblings` field in the finding contract, and a same-line
  `same shape also at …` form in the output template.
- The attribution axis ("keep it scoped to touched code; a repo-wide sweep is
  the audits' job") now names the shape sweep as its one bounded exception, so
  the two rules don't contradict each other. That is the same class of mismatch
  CodeRabbit caught in #531's round 1.

Three eval scenarios: siblings listed but not blocking when the PR fixes one
client; approve-with-changes when the PR claims to close the class; and a
counterweight (a one-off logic error, where no sweep is invented). Plus one
regression test in `tests/test_generate.py`. Regenerated, re-vendored, drift
clean.

## 2026-09-25 (same day) — #526: findings still open at merge (D22)

Third item from the same session, after #525 (PR #531) and #524 (PR #532)
merged. #526: a Major finding that round 2 explicitly re-noted as still open
merged with the PR and never became tracked work. Asked the owner whether to
make this advisory or gated. The answer was advisory by default, with the
stricter behaviors easy to switch on, recorded as **D22** in
`open-questions.md`.

Built as one setting in `REVIEW.md` / `templates/REVIEW.md` (new *Unresolved
findings at merge* section): `unresolved_findings: note | require-followup |
file-followup | block`, plus `unresolved_threshold` (default `Major`). It lives
in `REVIEW.md` rather than `preferences.md` because it's reviewer-workflow
policy, and it's read from the base ref like the rest of that file.
`commands/atlas-review-pr.md` step 5 says what each value does. It acts at the
points a reviewer actually observes (every posted summary, approve-on-clean,
the round-cap notice, and a merge a watching session sees), since merge alone
isn't reliably visible to it. `file-followup` is idempotent via a
`<!-- atlas-followup pr:<number> -->` marker. `block` is named, in the *GitHub
review state vs. severity* section, as the one opt-in override of the
Blocker-only `REQUEST_CHANGES` rule, and it only gates merge where branch
protection requires an approving review (#492). It can't gate a PR authored by
the reviewer's own account at all, since GitHub forbids `REQUEST_CHANGES`
there; the policy says so explicitly (PR #533 round 1). The PR-watch runbook prompt now
points at the setting for an observed merge. New
`tests/test_unresolved_findings_policy.py` keeps the three restating files in
sync.

## 2026-09-25 (same day) — #519 and #520: D9's versioning trigger made checkable (D23), first half-month log rotation

Last pair from the 2026-09-20 weekly audit (#347) this session took on. Both
issues asked for an owner decision, so the session asked, with a
recommendation for each, and the owner took both recommendations.

**#519 → D23.** D9's revisit-trigger ("switch to semver if/when the suite
stabilizes for external users") had no checkable condition, and a static
`plugin.json` `0.1.0` had crept in with no recorded judgment behind it. D23
re-affirms commit-SHA versioning and states that the `plugin.json` version is
cosmetic and deliberately not bumped, with no `CHANGELOG`. It replaces the
vague trigger with three concrete ones: a consumer asks to pin by
version/tag, the first non-owner, non-automation PR merges, or 2027-03-31
arrives. D9's own trigger wording is now marked superseded by D23 (after
CodeRabbit noted it could still read as an independent reason to switch), and
`docs/distribution.md`'s pointer names D9's 2026-09-07 addendum and D23.

**#520 → half-month rotation.** September alone had pushed this file to about
2,080 lines before the month closed, so the "oldest completed month" rule had
nothing it could move. The header rule now allows splitting an overrunning
month at day 15. Applied immediately: 2026-09-01 through 09-15 moved verbatim
into [`session-log-2026-09-01-to-15.md`](session-log-2026-09-01-to-15.md),
checked lossless by rebuilding the original from the archive plus the live
file. The live file dropped to about 400 lines. `CLAUDE.md`/`AGENTS.md`'s
orientation text now says the log carries 2026-09-16 onward and mentions the
half-month case.

## 2026-09-26 — #535, #536: sweeping a dynamically-attached repo set

A scheduled routine's prompt is written once, but the set of repos it's
attached to can change over time via the routine's own config rather than
by editing the prompt — a hardcoded `OWNER/REPO[, ...]` scope in the prompt
text then goes stale. `commands/atlas-poll-and-review.md`'s argument-hint
and a new "Sweeping a dynamically-attached repo set" section now cover this
as a real, legitimate case, distinct from the issue #387 threat (an
unbounded sweep of "every repo this session's credentials can reach"): the
blast radius stays exactly as bounded, only the scope's *source* changes,
from hand-typed in the prompt to read fresh each tick. One confirmed
enumeration source, observed directly in a live scheduled-task session on
Claude Code: the session's own system prompt carrying a literal
"Repository Scope" section. Where a session surfaces that kind of
declaration, the routine should read it at the start of each tick and pass
it straight through as the command's explicit repo-scope argument, rather
than omitting the scope or guessing at it; where a platform instead
surfaces the attached set as local checkouts, each one's origin remote is
an equivalent source. This is confirmed for that one session shape, not
asserted for every routine/platform surface, so the text says to check the
specific session's own system prompt before relying on it.
`docs/runbooks/pr-review-automation.md`'s §4 (the poll-driven Model B) now
points at the same guidance for its own dynamically-attached case, keeping
the two docs in sync.

## 2026-09-28 — #539: a consumer-contract check for `tracing-correctness-and-invariants`

Added two Top-checks-promoted heuristics to cluster-1's #1 category: tracing
a changed/new interface (signature, return shape, null/error behavior)
forward to every consumer in the diff, so a mismatch between what a helper
returns and what a caller reads gets caught; and resolving a guard's
definition (including one introduced elsewhere in the same diff) before
reporting it as missing. Found via the #528 benchmark: two independent
atlas-code-review runs both missed four human-verified goldens on
calcom/cal.com#11059, all consumer-contract mismatches with both ends in the
diff (a `safeParse` result persisted as the payload, a raw `Response` read
as parsed JSON, a `credentialId`/`userId` argument swap). Regenerated
`SKILL.md`/`reference/heuristics.md`, the collapsed entrypoints, and this
repo's self-vendored `.claude/skills/` copy; added an eval scenario
exercising the new check. #539's other validation step — re-running the #528
benchmark cell on cal.com#11059 — is left for a follow-up session with
model access to that harness.

## 2026-09-29 — `tooling.cli drift` crashed on a renumbered/removed source section

`check_drift()` already wrapped a missing/non-UTF-8 source *file* in a
clean `DriftError` (#107), but a source *section* that disappears from an
existing research doc — renumbered during a taxonomy promotion, or its
heading text edited out — still escaped `extract_section` as an uncaught
`KeyError`, crashing `python -m tooling.cli drift` with a raw traceback
instead of the clean `ERROR:`/`DRIFT:` reporting every other failure mode
gets. That's exactly the "the source changed under a generated skill" case
this command exists to detect, not an internal programming error. Fixed by
catching the `KeyError` around `section_hash` and re-raising as a
`DriftError` naming the skill, path, and section; added a regression test
exercising a renumbered section.

## 2026-10-02 — #548, #549: the session-log currency gate was blocking unrelated PRs on calendar drift alone

The currency gate added by #513/#516 compares `docs/session-log.md`'s
newest header to today's date on every CI run, with no regard for what the
current PR actually touched — so once the log went more than `_SLACK_DAYS`
(5) days stale, *every* open and new PR failed `tests`, including a
dependency-only Dependabot bump (`#547`, the trigger for #548) that has no
way to add a session-log entry of its own. #549 was the proximate case: two
substantive, undocumented commits (`0174a12`/#539 above, `f67435b`'s drift
fix above) pushed the log 6 days stale, and this entry backs both of them
in alongside the gate fix itself rather than requiring a separate PR.

Fixed `tests/test_session_log_currency.py::test_session_log_is_current` to
skip the calendar assertion on a `pull_request` run whose own diff doesn't
touch anything in a new, dedicated `session_log_substantive` paths-filter
group. Two review rounds (atlas self-review and `copilot-pull-request-
reviewer`) on the fix's own PR (#550) each caught a real gap in the first
cut: reusing the existing `python` filter left a `github-actions`-ecosystem
Dependabot pin bump (which edits `ci.yml`, one of `python`'s paths) still
tripping the gate — exactly the #548 failure, unsolved for that case — so
`session_log_substantive` is the same list minus `ci.yml`/`pyproject.toml`/
`.python-version`/`.pre-commit-config.yaml`. And a first cut's "skip if the
PR also touches docs/session-log.md" escape hatch let a substantive PR
bypass enforcement by editing the file without adding a *current* entry;
dropped in favor of relying on the existing `last <= today`/`not stale`
assertions, which already pass on their own once a PR's own entry is
current. `push`/`schedule` runs (and a contributor's local `pytest`) keep
the original unconditional check — there's no single PR diff to blame
there, and that's exactly the "many small, individually innocent PRs left
the log stale" case the calendar check still needs to catch. `ci.yml`'s
`tests` step now exports `CI_EVENT_NAME` plus the new filter's output as
`CI_FILTER_SESSION_LOG_SUBSTANTIVE`; `test_should_enforce_pr_diff_gate`
covers the decision table directly, and a new
`test_ci_yml_wires_the_pr_diff_gate_env_vars` pins the wiring itself so a
future rename can't silently disable the gate on every PR.

## 2026-10-08 — #558: a table-driven type-matrix test for `check_drift`'s malformed `built_from` handling

`tooling/drift.py::check_drift`'s malformed-`built_from` handling had been
fixed four times for four different input shapes (#107, #546, #554, #555),
each fix covering only the exact shape its triggering report showed and
missing the next one. Added `MALFORMED_BUILT_FROM_MATRIX` to
`tests/test_drift.py`: a parametrized table enumerating the type-space of
the container (`built_from` itself), an entry, and an entry's
`category`/`source`/`hash` fields (null, str, int, bool, list, dict, and
missing-key, as applicable to each), asserting every cell routes through a
`DriftError` naming the skill rather than a bare Type/Key/ValueError. 26
new cases pass against current `main`; reverting the `entry`-is-a-mapping
guard locally to confirm the matrix is load-bearing reproduces the exact
pre-#555 bare `TypeError` across its 5 `entry-*` cases, as expected. Left
the existing per-shape regression tests in place rather than consolidating
them into the matrix, to keep this change additive. The issue's other two
suggested follow-ups — a `tracing-correctness-and-invariants` lens check
for this input-validation pattern, and a hand-authored eval scenario —
are bigger, separate asks and remain open.

## 2026-10-12 — #540: file/module renames and moves now reviewed as an interface change

A rename/move changes the module's import-path namespace the same way a
signature change alters a function's call contract, but no lens treated it
that way — the #528 cal.com benchmark found a real `_utils/` → `_utils/oauth/`
move reviewed as untouched ("only their import path moved") on two separate
atlas runs. Added one ★ heuristic to each of the three clusters #540 named:
cluster-1 `#1` gets a dedicated move/rename bullet next to the existing
"Consumer contract across the diff" one (`tracing-correctness-and-invariants`)
— every importer, re-export, alias, and string-keyed mock (`jest.mock("old/
path")`) is a consumer of the old path, not just the diff's own updated
imports; cluster-3 `#9` gets a structural-fit check (`reviewing-module-design`)
— does the new location sit with the right neighbors, or does it cross a
layering rule or split a cohesive family; cluster-2 `#5` gets a naming-bar
check (`reviewing-naming-and-readability`) — is the new path actually clearer,
or a sideways move trading one incomplete name for another. Regenerated the
three skills (`tooling.cli generate`) and re-vendored `.claude/skills/`
(`tooling/vendor-skills.sh .`, this repo's own self-vendor case); `tooling.cli
drift` reports clean. Added the eval scenario #540 itself proposed (a module
move where every import was updated except one `jest.mock` string path) to
`tracing-correctness-and-invariants/evals/eval.json` — the other two lenses'
new checks are judgment calls (structural fit, naming clarity) rather than a
crisp pass/fail the same scenario shape would exercise, so left for a
follow-up eval pass rather than forcing a scenario that wouldn't discriminate.
The other proposed change — resolving PR/local diffs with rename detection
(`git diff -M`, or GitHub's `previous_filename`) so a moved file reaches the
lenses as a move instead of an unrelated add+delete — landed in both
`commands/atlas-code-review.md` (step 1) and `commands/atlas-review-pr.md`
(step 4, point 5), since both commands currently resolve diffs without it.

## 2026-10-19 — #574: withdrew #347's false "5 dead `# noqa: TRY004`" finding, closed the invocation pitfall that produced it

\#347's weekly self-audit flagged five `# noqa: TRY004` suppressions
(`tooling/manifest.py:35`, `tooling/run_evals.py:197/253/264/292`) as dead,
grounded in `ruff check --select RUF100 .`. #574 showed that invocation is
itself unsound: `--select` *replaces* the effective rule set for that run
instead of adding to it, so under `{RUF100}` alone every pre-existing `noqa`
looks unused regardless of whether its named rule fires under the repo's
real configuration. Removing the 5 directives and running the unmodified
`ruff check .` immediately reproduced 5 fresh `TRY004` failures, confirming
the suppressions are genuinely necessary — the directives were left
untouched. Added `RUF100` to `pyproject.toml`'s `extend-select` (verified
clean both via `ruff check --extend-select RUF100 .` and the now-updated
plain `ruff check .`) so the rule is a standing, correctly-configured gate
rather than a one-off ad hoc CLI invocation. Added a rule to
`grounding-review-in-tool-output`'s `prepass` section in `manifest.yaml` —
"a narrowing flag changes what 'unused' means" — naming this exact pitfall
and `ruff`'s `--extend-select` as the fix, regenerated
(`tooling.cli generate`) and re-vendored (`tooling/vendor-skills.sh .`); drift
reports clean. Commented on #347 withdrawing the Minor finding and citing
\#574's evidence.

## 2026-10-23 — #347: closed the log-dir symlink guard gap (Minor finding) in the opt-in feedback hooks

\#347's weekly self-audit flagged that `hooks/lib/feedback-tier.sh`'s
symlink guard "covers only the final file": `_code_quality_atlas_append`
already refuses to write through a symlinked log *file*, but
`_code_quality_atlas_hook_prologue` ran `mkdir -p "$LOG_DIR"`
unconditionally, and `mkdir -p` on a path that already exists as a
symlink-to-directory succeeds silently — so a cloned repo shipping
`.code-quality-atlas/learnings` itself as a symlink pointing outside the
tree would have every append write through it unguarded, one path segment
above the existing protection. Confirmed live before fixing (the directory
itself, not just the file inside it, had no `-L` check anywhere in the
file). Added a `[ -L "$LOG_DIR" ]` refusal before the `mkdir -p` call,
mirrored byte-identically into `collapsed/hooks/lib/feedback-tier.sh` (kept
in sync by `test_collapsed_generic_hook_scripts_match_standalone`). New
regression test `test_symlinked_log_dir_itself_is_refused` plants
`.code-quality-atlas/learnings` as a symlink to an outside directory and
asserts nothing gets written there; confirmed it fails against the
pre-fix code (a file is actually created in the outside directory) and
passes once the guard is added.

PR #579's own round-1 atlas self-review (`dees-bot`) caught that this
first pass was still only partial: checking `LOG_DIR` alone misses a
symlinked *parent* (`.code-quality-atlas` itself) whenever `learnings`
doesn't exist yet inside the symlink's target — `[ -L "$LOG_DIR" ]` then
lstats a path that doesn't exist (ENOENT) and reads as "not a symlink",
so `mkdir -p` still creates a brand-new, unguarded real directory inside
the symlink's target. Added a second regression test
(`test_symlinked_parent_dir_is_also_refused`), confirmed it fails the same
way against the first-pass fix, then extended the guard to
`[ -L "$LOG_DIR" ] || [ -L "$(dirname "$LOG_DIR")" ]` in both copies.
`ruff`/`mypy`/the full `pytest` suite (868 passing)/`shellcheck`/
`tooling.cli drift` all clean on the final version.

## 2026-10-28 — #583, #584, #585: two routine dependency bumps and the version-pin comment refresh they triggered

Two Dependabot PRs landed back to back on 2026-10-27: ruff 0.17.1 → 0.17.2
(#584, `requirements.in`/`requirements.txt` only) and
`actions/setup-python` 7.0.0 → 7.1.0 (#583, one line in `ci.yml`). Both
are mechanical, dependency-only changes with no source or doc edits of
their own.

The ruff bump left `pyproject.toml`'s `[tool.ruff.lint]` comment citing
the now-superseded `ruff==0.17.1` pin it was last verified against — the
exact stale-pin drift the comment's own closing sentence warns about, and
the same spot #581/#582 had just finished correcting (0.16.5 → 0.17.1,
407/409 counts restored after an off-by-one) only a day earlier. #585
(2026-10-28) re-ran `ruff check --isolated --show-settings .` and this
repo's own `ruff check --show-settings .` under the newly-pinned 0.17.2:
both rule counts (407 default, 409 with this repo's `extend-select`) came
back unchanged, so only the cited version string needed correcting.

**Backfill note (2026-10-31, #586):** this entry was written retroactively
— none of #583/#584/#585 added one of their own, and the weekly
`schedule` currency check
(`tests/test_session_log_currency.py::test_session_log_is_current`) was
heading toward its next run with the log 8 days stale and no open PR able
to carry the fix.

## 2026-11-03 — #588: drift guard for pyproject.toml's hand-maintained ruff rule-count comment

\#588's scheduled self-improvement sweep (2026-11-02) flagged that the
`[tool.ruff.lint]` comment's numeric claims (407 rules enabled by ruff's
default, 409 once this repo's own `extend-select` is applied, and the
"four" `# noqa: TRY004` suppressions in `tooling/run_evals.py` that
implicit surface forces) had needed manual correction repeatedly — #581
refreshed a stale pair of counts, #582 then had to fix an off-by-one in
that very refresh, and #585 was a third comment-only follow-up to a
routine `ruff` version bump. Nothing mechanically caught the drift; it
was only ever found by a human or agent re-deriving the numbers by eye.

Added `tests/test_ruff_rule_count_comment_sync.py` (issue #588's "Option
2"): it parses the comment's claimed version pin and both counts, derives
the real numbers via the exact commands the comment itself names
(`ruff check --isolated --show-settings .` and
`ruff check --show-settings .`, counting the `linter.rules.enabled = [...]`
block's actual entries) plus a regex count of `# noqa: TRY004` in
`tooling/run_evals.py`, and fails with a correction message on any
mismatch — including a guard that the installed ruff
matches `requirements.txt`'s pin, so a version mismatch can't masquerade
as a real drift (or vice versa). Confirmed the new tests pass against the
current (accurate) comment, and that each one fails with a clear message
when a claimed number is deliberately corrupted. Not a generation-based
fix like `test_doc_counts.py`'s #372 mechanism, since this is prose
explaining a tradeoff rather than a rendered template occurrence — per
\#588's own framing, a drift-guard test is the right-sized fix here.
`ruff`/`ruff format`/the full `pytest` suite (coverage gate green) all
clean.

## 2026-11-06 — D24: `atlas_reviewer/`, the first manual, draft-only reviewer service

**Where the code is:** the `atlas_reviewer/` package lands through the
stack split from #598 (steps 2-8, #601-#607). Until step 8 merges, a tree
without those steps has no `atlas_reviewer/`, and links into it resolve
only on those branches.

The owner approved one manual review path. An operator-triggered
controller takes a PR event (repo, PR number, head SHA), gathers CI
evidence matched to that exact SHA, runs extra tools in a fresh,
credential-free Sprite, and writes a review draft to stdout or a file.
It publishes nothing to GitHub. The service lives here as a new top-level
package, `atlas_reviewer/`, with its own entry point
(`python -m atlas_reviewer`), its own tests and coverage run, and two new
CI steps: the suite, and an offline dry run against
`atlas_reviewer/fixtures/sample-pr/`. It runs the collapsed
`reviewing-a-change` skill bundle as data and changes nothing under
`skills/`, `collapsed/`, or `tooling/`. It is recorded as **D24**, a
scoped step under the still-open Q24; design in
[`plans/2026-11-06-manual-reviewer-service.md`](plans/2026-11-06-manual-reviewer-service.md).

The runner lifecycle follows the same-day live Sprites validation. Every
review gets a fresh Sprite, never a reused one. Deny-all egress is set and
read back from the outside API before anything executes, and an external
deadline is enforced by a watchdog. Destroy is the only cleanup primitive.
It runs in `finally` and from the watchdog, is verified by an existence
check, and is backed by a ledger that a `sweep` command reads after a
crash. Mutation checks confirmed the lifecycle tests bite: removing the
`finally` destroy fails 11 tests, dropping the deny-all read-back fails 2,
and disabling the watchdog fails its test.

The domain is a closed union. `Matched` / `Stale` / `Missing` evidence
means only head-SHA evidence can ever PASS. Stale, missing, and
inconclusive evidence is UNKNOWN. Untrusted text is typed (`RedactedText`
is minted only by `redact()`), and it reaches the prompt only inside
nonce-fenced blocks.

Only the offline provider ships. The first live adapter to wire is the
Anthropic Messages API. Live runs still need three things: a pre-minted
GitHub App installation token (no in-process JWT minting), confirmation of
the Sprites exec request shape, and a model choice.

Repo wiring:

- `LICENSE` and `tests/test_license_paths_exhaustive.py` classify the
  directory as MIT.
- `[tool.mypy] files` now includes the package. The "only fully annotated
  package" comments in `pyproject.toml`, `ci.yml`, and both
  `CLAUDE.md`/`AGENTS.md` copies were updated together.
- `ci.yml`'s `python` and `session_log_substantive` path filters gained
  `atlas_reviewer/**`.

## 2026-11-07 — D25: the reviewer service's live-readiness slice

Second slice of `atlas_reviewer/`, still draft-only and still offline in
tests and CI. It is recorded as **D25**, which amends D24's "stdlib-only"
and "no live provider" statements. Design and the remaining live setup are
in [`plans/2026-11-06-manual-reviewer-service.md`](plans/2026-11-06-manual-reviewer-service.md#live-run-gaps).

- **Pagination.** Every GitHub list follows `Link: rel="next"` up to a
  10-page cap, and refuses a `next` link that leaves the API origin. A
  list cut off by the cap is an explicit omission in the draft, and what
  it did not read is UNKNOWN.
- **Ingestion.** Job logs and artifact ZIPs are fetched only for the
  matched head SHA and are capped per download and per review. ZIPs are
  read in memory with per-entry checks (traversal, symlinks, encryption,
  type allowlist, binary content, size, ratio, total budget). They are
  never extracted or executed, and are redacted before use. Every limit
  hit is listed in a new "Omissions and limits hit" table.
- **GitHub App auth.** Installation tokens are minted in-process (RS256
  through `PyJWT[crypto]`, the repo's first runtime dependency beyond the
  stdlib, controller only). They are read-only and scoped to one
  repository, and cached until five minutes before expiry. Each minted
  token feeds the redactor.
- **Sprites.** Exec now follows the published OpenAPI 0.1.12. The response
  framing is undocumented, so the decoder strips framing bytes and trusts
  an in-band exit marker. A tool probe runs before any PR bytes are
  uploaded, and a missing binary is UNKNOWN, never executed. A new
  `probe-runner` command lets the owner check the protocol live once.
- **OpenRouter.** OpenRouter replaces the Anthropic suggestion. The
  provider is pinned to `anthropic/claude-sonnet-5.5` with no fallbacks
  and is opt-in with `--allow-live-inference`. It runs at most three calls
  per review, retries included. Each call reserves its worst case against
  a $3.00 budget at the highest catalog prices, and unknown pricing fails
  closed. A preflight refuses any key without a hard limit of at most $5.
  Writing the tests found a gap: retries were checked against the key's
  remaining credit one call at a time, not in total. The reservation now
  caps at the lower of the two.

Writing the archive tests also showed that an "actual compression ratio"
check could never fire, because `zipfile` never yields more than the
declared size. That check was removed, and the docstring now states the
real mechanism, which is tested with a header that under-declares its
size.

## 2026-11-07 (same day) — provider `only` uses the slugs the public list exposes

A read-only check of OpenRouter's public provider list found Vertex
exposed as `google-vertex/global`, `google-vertex/us`, and
`google-vertex/europe`, not as bare `google-vertex`. Bedrock is listed as
the base slug `amazon-bedrock` plus region slugs that check did not name.
The provider-selection doc's "Base Slug Matching" says a bare slug in
`only` matches every eligible endpoint of that provider, regions included,
so the old pin would have widened routing past the endpoints that were
reviewed. `PINNED_PROVIDERS` is now those four named slugs, with
`allow_fallbacks` still false. Anything else, including the bare Vertex
slug and the docs' region examples `google-vertex/us-east5` and
`amazon-bedrock/eu-west-1`, is refused before a request. The in-region
routing doc says a bare `amazon-bedrock` does not pin that provider's
regional-surcharge endpoints, which is why the unnamed Bedrock regions
stay off the list rather than being guessed.

Still unverified against live responses: the Sprites exec response body,
the GitHub and OpenRouter response shapes, and the input-token bound.

## 2026-11-07 (same day) — D26: fixes from the first live pilot

The owner ran one live pilot of PR [#598](https://github.com/brandondees/code-quality-atlas/pull/598)
at head `9ff859b` and reported: the probe passed with the exec framing the
decoder already handles; the image has `python3` but no `ruff` or
`shellcheck`; one model call cost $0.17; the source upload of about 3 MiB
failed with "The read operation timed out", so no in-Sprite tool ran; and the
model said no lens ran. Everything below is offline-tested only.

**The timeout was not what the report suggested.** The first hypothesis was
the 30-second client default. The code does not support it: `_exec` already
gave the upload `min(remaining deadline, ...)`, about 590 seconds, and
`SpritesClient.exec` passes it to the transport. The new tests pin the number
sent to the transport (300 seconds, capped by the deadline) at the fake and
through a real `SpritesClient` with a recording transport. The cause is
unknown. The upload now extracts with `head -c N | tar` so it does not wait for
a stdin EOF, which is a guess, labelled as one, and `probe-runner` gained a 3
MiB stdin round-trip so the next pilot can separate a stdin problem from a
tarball problem without PR code.

**Lenses are fed, not named.** The model had no way to open `body.md`, so
naming lenses in the prompt could never run them. `lenses.py` selects from
changed paths and PR text, and inlines bodies under a character budget. Real
bodies run 11k to 35k characters each, so a 60,000-character budget fits about
three; the draft says which were included, truncated or omitted. The selector
is a digest of the bundle's route table and a test checks every lens it names
exists. Writing the ranking showed that letting the generic baseline route
count the same as specific routes buried the specific lens (security ranked
third, behind two generic lenses, for an auth change), so specific routes now weigh ten times more.

**Grouping.** A check run, its job, its log and its workflow run were four
passes. Links come from ids (a job's documented `check_run_url`), never names.
Writing the tests turned up two traps: a run that fails because of one job
would fail its passing sibling's group if its verdict were shared, so a run is
context only and carries no verdict into a group; and a run failure no job
explains must stay an independent failure rather than vanish into a group. A
cycle in the links could also have erased a failing check, so anything a
traversal does not reach becomes its own check.

**Controller notes.** One code-generated section replaces the old Notes and
Disposable runner sections, and the model is handed the same text as
established fact. The notes can quote runner output (an upload failure
includes the guest's output tail), so they are fenced as untrusted data like
everything else.

Smaller items: `ruff` and `shellcheck` left the default tools; truncation of
the diff, PR body and issue bodies is an omission, computed before the
evidence block so the model hears about it (the diff entry names the files it
never saw, from character offsets); `sweep` takes the single-review lock; the
OpenRouter key counter is documented as able to lag about 90 seconds and is
never read after inference.

Not changed, and said so: check summaries, log tails and artifact excerpts are
still capped without an omission row.

## 2026-11-07 (same day) — D27: lifecycle telemetry and risk-ordered diff coverage

The second owner-run pilot at `d63f087` failed the same way the first did,
with `POST …/exec failed: The read operation timed out`, after a 3 MiB stdin
probe at the same head had passed in about 2 seconds. The message had no
upload label. Reading the runner confirmed the owner's inference: only the
upload wrapped its errors, so the tool check (60-second budget) and both tool
execs (135 seconds) could each have produced that bare text, and nothing
recorded which one did. Its model call also saw only 13 of 77 files, cut in
diff order, so the auth, redaction, runner and HTTP modules went unread.

**Telemetry.** One `EventSink` (`telemetry.py`) with a JSONL implementation
and an in-memory record the draft and `probe-runner` render as a table. Every
phase is one event, and an exec event carries its purpose, timeout, bytes
each way, the stream-id bytes seen, exit status and duration. `span` re-raises
a boundary error as the same type with its phase, step, duration and time
into the run. The innermost span labels it, so nested spans (an exec inside
the upload) do not stack prefixes. GitHub reads are timed by a wrapper
(`instrumented.py`) instead of threading telemetry through `gather.py`. Step
labels use only ids, never branch names. Error text is redacted with the
environment's credential values before any sink sees it.

**Runner.** Upload and unpack are now two execs, and the upload must report
writing exactly the bytes sent, so a transport stall, a short write and a slow
extraction fail differently. `probe-runner --sequence review` calls
`run_disposable` itself, on a local tarball or the App-fetched head tarball,
with no model. It reproduces the exact exec order rather than an approximation
of it.

**Diff coverage.** The single 60,000-character cut became risk-ordered,
first-fit packing into at most three parts, one model call each. The parts
share the existing three-call cap (retries included), the $3 reservation and
the preflight, now exposed as `--max-model-calls` and `--diff-chars-per-call`.
Writing the end-to-end test against the real `OpenRouterProvider` and its
budget showed the trade-off plainly: one retry on part 1 leaves part 3
refused. That part gets its own omissions row listing its files, and the
post-call controller note says PARTIAL. With the defaults, a diff the size of
this PR's (412,078 characters) still cannot be fully reviewed, and the draft
says so, naming the docs and tests that went unsent.

## 2026-11-07 (same day) — D28: one exec shape and fail-fast on silence

The owner's live `probe-runner --sequence review --tools review` at
`fd56ca0` got further than either pilot: create, egress, the tool check,
the upload (3,062,571 bytes in 0.25 s) and the unpack (0.33 s) all
succeeded, and `python3 --version` with no stdin then timed out at 135 s.
The ask was to diff how the failing exec was built against the ones that
worked.

The diff came back empty. All three no-input execs went through the same
`SpritesClient.exec`, with the same method, headers, `Content-Length: 0`
and query keys, and the same blocking read. Only the third `cmd` value and
the timeout differed. So the request shape could not be the cause, and the
write-up says so instead of shipping a "fix" for a difference that did not
exist. Two real gaps came out of the comparison. No-input execs relied on
the server's undocumented stdin when `stdin` is false. And the transport's
one blocking `read` threw away partial output on a timeout, so the
telemetry's "no frames" was never measured. The leading hypothesis is about
the command, not the request: `python3` is the first binary the runner ever
executed rather than resolved, and how the multi-runtime image provides it
is unknown.

Shipped: one request builder (`exec_request`, always `stdin=true` with an
exact-length body) and one script wrapper (`exec_argv`: start marker,
exactly N stdin bytes then EOF, exit marker), checked in a local `sh`
against a stdin that never closes. A streaming transport on `http.client`
gives each read a wall-clock budget, so a silent no-input exec fails at
`--first-frame-seconds` and a stall keeps its bytes. The tool check now
reports where each binary resolves. One trade-off is stated rather than
hidden: until a live run shows whether HTTP exec output streams, a long
tool that prints nothing could trip the window.

## 2026-11-07 (same day) — D29: a controller-chosen interpreter, never the pyenv shim

The owner's next probe, at `9805cfc`, showed the D28 wrapper doing its job.
The start marker arrived after the unpack, so the shell was running, and
then `python3 --version` sent nothing more for 135 s. The tool check had
already said where `python3` lived: `/.sprite/bin/python3`, resolving to
itself, so it is a script rather than a link. The owner matched that to the
Sprites docs (pyenv shims in `/.sprite/bin`, default 3.13.x) and to this
repo's `.python-version` of `3.12`. The suspected cause is the reviewed PR's
own pin, read by the shim from the checkout. Run #6's write-up had said the
PR's files could not affect `python3 --version` because it prints before
Python imports anything. That holds for a real interpreter but not for a
shim, and the README now says so where it made the claim.

The fix does not wait on the hypothesis. Every exec now gets a minimal
environment from the shared wrapper (`env -i`, `PATH=/usr/bin:/bin`). Before
any PR byte is uploaded, one exec from an empty directory lists the real
interpreters, and the controller accepts only two exact path shapes.
Python tools can name the chosen interpreter only through a `{python}`
placeholder and run it with `-I`, so a PR can steer neither the version nor
the module search path. To confirm or refute the hypothesis,
`probe-runner --sequence review` gains labelled, never-fatal diagnostics.
The last one is bare `python3` from the checkout, bounded to 15 s, which is
expected to hang if the hypothesis is right. The wrapper and both new
scripts are also run for real in a local shell in the tests, without any
Sprite or network.

## 2026-11-07 (same day) — D30: third-pilot findings verified, fixed, and untrusted notes quoted

The owner's third live pilot at `a246625` ran end to end, and its draft
flagged five problems in the reviewer itself. The draft is model output, so
none was taken on trust: each was reproduced or refuted against the code
first. Four were real. The assignment redactor's `\b` never matches after an
underscore, so `OPENAI_API_KEY=...` passed through. Archive entries were
charged only after a successful read, so ones failing their CRC check were
never counted. A failed diff fetch still made one model call with an empty
diff. CI and dependency files ranked below ordinary code, and PR-controlled
paths and error text reached the authoritative controller notes verbatim.
The transport finding was partial. Only the streaming exec path lacked a
cumulative deadline before the body, where trickled headers could hold an
exec open indefinitely. The plain transport never claimed one.

Each fix has a regression test that failed on the old code. The notes now
quote every untrusted value as one JSON string literal in a code span and
say so in their introduction and in the system prompt, so a file name
cannot pose as a controller statement.

## 2026-11-07 (same day) — D32: diff parts fitted to the 200k-token bound, the repo's own lens picker; D31 proposed

Run #9 asked for a much larger diff part (about 450k characters) and a
design for a lens-based agentic reviewer. The larger part can't pass the
existing token check. The input bound counts one token per UTF-8 byte, on
purpose, so it never under-reserves. The prompt room is therefore
`min(200k, 200k − 24k output)` = 176,000 characters, and that is the new
default. Each review then measures every planned prompt and shrinks the part
until the largest one fits. A first version shrank a nominal budget that
didn't change the packing when the diff was smaller than it, and
overshot on multi-byte text. The fix shrinks from the byte-largest actual
part, and ASCII, `é` and `漢` diffs are tested. One full-room call reserves
about $1.60, under the unchanged $3.00, and the 3-call cap is unchanged.

Brandon corrected the design brief mid-run: the suite already chooses
lenses, budgets reviews and merges findings, so reuse that rather than
invent parallel machinery. That also retired the reviewer's own
path-and-keyword lens selector. `picker.py` now runs
`skills/choosing-review-lenses/SKILL.md` as one model call, with a strict
reply parser and a critical-tier fallback. The design doc,
`docs/plans/2026-11-07-lens-based-agentic-reviewer.md` (D31, a proposal),
reuses the picker, depth modes, lens bodies, `tool-evidence.md`,
`synthesis.md`, `REVIEW.md` and `ReviewBudget` as they are. It specifies only
what's missing: the controller-run loop, a read-only Sprite tool bridge, the
security boundaries and the credentials split. Its first open question is the
call and cost caps a lens loop would need.

## 2026-11-07 (same day) — PR #598 frozen as the single-prompt reviewer; cleanup and a split plan

Brandon marked PR #598 ready for review and froze it as the single-prompt
manual reviewer, with D31 left as a proposal. The cleanup pass made no
behaviour change. It removed an unused alias in `fakes.py`, and the draft's
Review lenses intro no longer says lenses come from changed paths and PR text.
Test docstrings now cite decision IDs instead of operator run numbers. The
reviewer README and plan doc no longer say only one pilot ran or that no
upload had succeeded. The plan's runner steps gained the D29 interpreter
step, and the plan gained a follow-ups list: the D31 lens loop, a deployed
controller, and omission rows for check summaries and log tails. The D24-D32
entries now cross-reference consistently, and Q24 gained a 2026-11-07 update.

A split into a stack of smaller PRs was planned from this branch. The
branch's commits are time-ordered slices that each touch most modules, so
the plan was to re-slice by file from the final tree, not cherry-pick. Each
proposed step's tests were run against only that step's modules as a
feasibility check, and every step measured 95% or more against the 94% floor.
The split was carried out later the same day; the next entry records it.

## 2026-11-07 (same day) — the manual reviewer split into #599-#607

The split planned above was carried out, re-sliced by file from #598's
final tree. #599 is the D31 proposal doc and is merged. #600 is this
stack's docs step (D24-D32, the service plan, the session log). #601-#607
are the draft code steps, based on each other. #598 stayed open and was
not merged.

## 2026-11-07 (same day) — D33: the diff goes to the model unredacted, committed secrets are flagged

Brandon decided to stop redacting PR diffs. On #601's live run, an
unterminated private-key BEGIN in `test_redact.py` made diff redaction
swallow the four files after it, and the assignment redactor mangled type
annotations and missed `token: str = "..."`. D33 records the decision and
marks D24, D30, D31 and D32 and the two plans as amended. The code is on
the stack. Step 2 (#601) adds `detect_secrets` and the fenced, unredacted
`RepoText`. Step 7 (#606) sends the diff unredacted and lists each possible
committed secret as a HIGH finding by file, line and pattern, never the
value. It also lists any file the fitted selection drops as an omission.
Step 8 (#607) updates the README. Redaction stays for PR, issue, CI,
artifact and runner text and for the published draft.

## 2026-11-08 — D34: agentic reviewer direction accepted

Brandon accepted the recommendations in a research note on making Atlas an
agentic reviewer: "I can roll with recommendations as proposed for now."
D34 records them, and [`agentic-reviewer.md`](agentic-reviewer.md) holds the
design and phased plan. The one-shot stack (#601-#607) stays the fallback.
Each selected lens runs its own tool loop over a Sprite checkout, and a
lens counts as run only when its body was loaded. The reviewer gets the
full PR conversation and branch-wide CI labelled by SHA, all keys stay on
the controller, and free tools are baked into the image. Agentic mode
starts triage-only, on a small controller loop of our own, and is scored by
issue-hit precision and recall plus coverage honesty. Every agentic budget
is pending Brandon. Nothing was built and no live run was made.

## 2026-11-10 — agent docs and the stale-PR sweep learn native stacked PRs

GitHub stacked pull requests went GA on 2026-10-06 and are in use here. The
open reviewer stack is #606 → #607 → #613. #612 → #614 is a second stack
whose trunk is #607's branch. `AGENTS.md` and `CLAUDE.md` now say how to
push a fix onto the layer that owns it, restack upward with `gh stack`, and
leave merges to the owner. `update_pull_request_branch` writes a merge
commit, which breaks the linear history a stack requires, so
`atlas-rebase-stale.md` and `atlas-poll-and-review.md` skip that call on a
stack member and post the one-time restack poke instead. The poller runbook
says the same wherever it used to treat every behind PR as auto-rebased.
Brandon approved a restack-only review round the same day. Before round 2+,
`atlas-review-pr.md` fingerprints the layer diff. An equal fingerprint with
green required checks posts `## Round N — restack only, layer diff unchanged`
and carries the previous verdict forward, with no lenses and no cap count.
A different fingerprint, a missing one, or a failed check is a normal round.

## 2026-11-12 — agentic per-call limits follow the model, and a stop names which one

The agentic loop no longer uses the one-shot 200,000 input cap. The
per-call input room is the pinned model's catalog context minus the
output reserve, and the output cap is the model's own completion
limit. An override can tighten either and cannot exceed the model.
OpenRouter's reasoning hint is still sent, and the reservation prices
the whole output cap at the completion rate plus the reasoning rate,
on this path and on the one-shot path. D43's $5 reservation and
one-token-per-byte bound stay. The one-shot 3-call, $3, and
200,000 ceilings stay. The eight agentic limits are flags and `ATLAS_*` variables.
`limits_for_lens` is what a lens run uses. The one-shot `review`
command does not read them, so a value such as `ATLAS_MAX_CALLS=10`
does not refuse it. A limit that stops a lens is its own cause, with the
configured value, the observed value, and where to change it, in the
ledger and on the status line's `limit_stop`. Compaction is not built.
The Claude Code comparison and the follow-up are
[`research/claude-code-long-sessions.md`](research/claude-code-long-sessions.md)
and Q26.

## 2026-11-12 — the default reasoning hint leaves half the output cap for the reply

The default hint was one token under the output cap. OpenRouter counts
reasoning tokens against `max_tokens`, so a turn that used the hint had
one token left for the reply and stopped with `finish_reason=length`,
which the loop recorded as a model error. The default is now half the
output cap. A length stop is an output-cap limit: the configured cap
and `finish_reason=length`. The one-shot `review` command no longer
accepts the eight agentic limit flags, which it did not read. The
`ATLAS_*` variables are unchanged, and `limits_for_lens` still reads
them. A runner deadline reports elapsed seconds, as the other two
clock stops do.

## 2026-11-12 — parity gate for submitting APPROVE, and an offline protocol scorer

The draft's `review_event` line is still D36. Submitting that line to
GitHub as `APPROVE` is a separate decision: the poster may do it only
when `python -m atlas_reviewer eval --fixtures <dir> --head <sha> --gate`
exits 0 on a candidate recorded for that head. The four criteria (repo
access, a full diff at any size, per-lens fan-out with verification, and
recall of the Claude Code protocol findings on PRs #602–#637) are all
unmet in the current reviewer, so the gate fails closed. The plan is
[`plans/2026-11-12-reviewer-parity-gate.md`](plans/2026-11-12-reviewer-parity-gate.md).
D45 recommends self-hosted Phoenix on Fly in org `personal` and does not
provision it. The scorer and the reference rows are offline fixtures;
nothing in this change calls a model or writes to GitHub. The hosting
decision is D45. D44 belongs to #646. D48 is #639's webhook receiver,
already on main, and D46 is the open #640's. A reference row's `metadata.run`
records `coordinator-verified` when the
round says fan-out did not finish. That field is information and does
not itself fail the gate. `--gate` also fails when any reference row has
no candidate, when `--head` has no passing pair, or when no passing pair
records `over_context_window`. GitHub `APPROVED` is `APPROVE`. Body
findings and
the `**Severity** · \`lens\`` inline shape are parsed. Brandon's
2026-11-12 bar: an extra finding never fails the gate, and the verdict
and the severity do not have to match. The gate fails on a selected
lens that was NOT RUN or failed, a lens named by a reference finding
that was not run, incomplete file coverage, or recall below 1 of the
reference findings (same path, line within five).
The reference is the checked-in row, and a missing or malformed
reference set fails closed. Zero parsed findings are a gap unless the
round says there are none.

The agentic loop also emits OpenInference spans when
`ATLAS_OTEL_ENDPOINT` is set on the controller. Prompt and completion
bodies stay off unless `ATLAS_OTEL_EXPORT_BODIES=1`, and every string
attribute goes through the review's redactor. The JSONL event file is
unchanged. No exporter is built when the endpoint is unset, including
when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Collector header values are
scrubbed, `http` export is loopback-only, and a dead collector cannot
hold the process open at exit. D25's claim that `PyJWT[crypto]` is the
only runtime dependency is amended: the OpenTelemetry packages are too.

## 2026-11-12 — the live model and provider pin are configurable

The OpenRouter model defaults to `anthropic/claude-sonnet-5.5` and can be
set with `ATLAS_MODEL` or `--model`. `provider.only` defaults to the four
Bedrock and Vertex slugs and can be one slug (`ATLAS_PROVIDERS` or
`--providers`). `zdr: true`, `data_collection: deny`, `allow_fallbacks:
false`, `require_parameters: true`, and `max_price` are not settings.
Before a completion the adapter reads `GET /api/v1/endpoints/zdr` and
refuses a slug that is not pure ZDR for that model. Safety Retention is
off unless `ATLAS_ALLOW_SAFETY_RETENTION=true` or
`--allow-safety-retention`. `reasoning` and `cache_control` are sent only
when every selected endpoint lists them. No live call was made. D51.

## 2026-11-12 — round 1 on the configurable model pin

D51, not D49: #654 and #655 already use D49 and D50. A parent slug is
refused when a child tag on the ZDR list is Safety Retention. A bare
slug such as `deepinfra` is refused and the error names the exact tags.
`max_tokens` stays the configured output cap. The ZDR list is read once
per provider. A zero required rate and a non-finite per-million price
are refused. No live call was made.

## 2026-11-12 — each agentic round reviews the whole pull request

The agentic first turn can carry the PR conversation
(`conversation.review_context`) and prior atlas rounds
(`rounds.RoundLog`, keyed by repository and pull request, not by head
SHA). No shipped caller wires the log yet: `review_lens` accepts
`round_log`, and the tests pass it. A superseded head stays in the log, labelled as not this
review's scope. The changed-file list is still every file in the
current diff. A round that does not fit, or a log line that does not
parse, is an omission, and that omission cannot approve. D52. The
plan is [`plans/2026-11-12-full-pr-context-rounds.md`](plans/2026-11-12-full-pr-context-rounds.md).

## 2026-11-13 — round 2 on the configurable model pin

D51's cost sentence now says each review adds one GET of the ZDR list
per provider, which is what the cache does. A tag that only shares a
slug's prefix, such as `amazon-bedrock-extra`, is not a child of that
slug. No live call was made.

## 2026-11-13 — round 3 on the configurable model pin

The catalog is fetched once per provider for the review and reused.
That is what `load_terms` does. The module docstring and the agentic
README said it was fetched on every completion or turn, which was true
before this cache. D41's sentence keeps the original design and notes
the amendment. No live call was made.

## 2026-11-12 — agentic reviews run every selected lens, and a lens's unread files can be assigned to it again

`agentic-review` is the command that applies the agentic limits. The
one-shot `review` command does not accept those flags and does not read
the eight agentic `ATLAS_*` limit variables (it does read
`ATLAS_KEY_CEILING_USD`), and it still uses the
60,000-character lens budget, so a review-depth one-shot run still
skips the picker. The agentic path calls the picker and runs the
critical tier plus every ranked lens that has a body, up to the pool
(1 to 16; 4 when the operator does not set it). Each lens has its own
Sprite name. A Sprites HTTP 429 on create is waited out and tried
again. A final reply outside the finding contract is quoted back once
inside the attempt, with the rejected reply in the model's own turn.
A lens's own unread files are handed to a continuation of that lens
while a call and the review clock remain. Coverage is per lens, as D42
approved: a read by another lens does not cover a file, and a file a
lens still has not read cannot approve. The draft names any runner
whose delete was not verified, and carries the picker's selection note
and the picked names that did not run; a picked name that did not run
blocks approval. A live run builds the picker's provider from the
agentic limits, and the picker's calls and dollars count in the
review's totals. The PR head is pinned to the event SHA before and
after the diff fetch, the picker sees a redacted title, a lens queued
past the review deadline is not started, and a halt is checked again
after a call is priced. `auditing-documentation-health`
keeps its repo shape; the change-review library reads its body from
the audit bundle. The OpenRouter key ceiling stays $5 unless
`--key-ceiling-usd` or `ATLAS_KEY_CEILING_USD` raises it, and a refusal
names that setting. D44 records it. Lenses still cannot run tests or
mutants, read CI, or see commits.

## 2026-11-13 — round 2 on whole-PR review rounds

The round log keeps another pull request's records out of this review,
compares the repository key case-insensitively, and counts the records
it sets aside without treating them as omissions. A file that cannot
be read is an omission. Mode 0600 is applied on every write. A record
of 8,192 characters is kept and 8,193 is not, and the newest record is
the one that stays when the budget holds one. Prior finding lines are
quoted. The first turn still lists every changed file. A continuation
may later list a subset. No live call was made. D52.

## 2026-11-13 — a later round can approve after the prior budget fills

A superseded round that does not fit, and a line that names another
pull request or no pull request, no longer block approval. A line that
names this pull request, including a future record version, still does.
A finding is quoted up to the 8,192-character record cap. The 16,384
default is pinned. A log write that fails after the model call returns
the review, and the draft and the status line name the cause. A
superseded record that does not fit is skipped instead of stopping
the pack. No live call was made. D52.

## 2026-11-13 — round 5 on whole-PR review rounds

An unreadable round-log file is its own omission. A superseded record
that does not fit no longer hides a current-head record written
earlier. A truncated superseded record does not block a new head. The
round-log arguments stay on the nested trace path. No live call was
made. D52.

## 2026-11-12 — an unknown severity drops that finding, and the review cannot approve

Main refused a lens's whole final reply when one finding's severity
was not exactly one of the four names. The agentic parser now maps a
closed set of aliases (`critical` to Blocker, `low` to nit, and the
same kind of neighbour for Major and Minor) after case and whitespace.
A finding that meets the rest of the contract but whose severity still
matches none of them is left out, with no repair turn. The other
findings stand. The draft lists each dropped finding, with its raw
severity scrubbed, quoted and cut to 80 characters, under its own
heading, and a drop blocks approval. Any other problem in a finding
still sends the whole reply back once, then `UNPARSED`. D54 records it.

## 2026-11-12 — a whole-line quote may sit two lines off its citation

The quote check was rejecting a finding the owner read as a real
exit-code Major. The quote text is not in the comments on #639, #640
or #642. Comparison now collapses internal whitespace, and a quote of
whole lines may match within two lines of the citation. That match is
tagged in the draft. A short fragment, such as `}`, still has to be
the cited line. A quote from a file the pull request does not change
now verifies when the lens read that file at HEAD. D47 records it.

## 2026-11-12 — every lens the picker names has a body

`auditing-infrastructure-as-code` was the picker's top choice on a Fly
config pull request, and its body lives in the audit bundle. The
change-review library already reads that body. A test now requires a
body for every review lens the picker skill names, and that lens is in
the set. A lens that still has none is listed as NOT RUN under Lens
selection, and that blocks approval. D56 records it.

## 2026-11-12 — a failed model call is sent once more

A live lens failed at turn 20 when Bedrock returned
`finish_reason=error`. The loop now sends a failed call again, once by
default, after a backoff of 2s times the failed calls so far. Each call
still reserves its worst case
and counts toward the call cap, and the failed call's reservation stays
committed. `--call-retries` and `ATLAS_CALL_RETRIES` set the count, 0
to 3. D49 records it.

## 2026-11-12 — a call is fitted to what the reservation has left

A live driver stopped about $2 short of its reservation, pricing each
call at the full 128k output cap. The product priced calls the same
way. A call the reservation cannot cover whole is now sent with the
largest output cap it can cover, as `max_tokens`, when that is at least
`min_output_tokens` (16,000 by default; `--min-output-tokens` or
`ATLAS_MIN_OUTPUT_TOKENS`). Below that it stops on `reservation_usd`,
and the stop names the cap the remainder covered. D50 records it.

## 2026-11-13 — pinned endpoints set the price, and ZDR can be turned off

`max_price`, the reservation, the context and the completion limit come
from the endpoint rows the route selects. The highest row price is the
cap. The smallest row context and completion limit are the bounds. The
catalog is still read once, to confirm the model id, and its headline
price is not the cap. The unset agentic output cap is a quarter of that
context when the completion limit would leave less input than that, and
the completion limit otherwise. `ATLAS_MAX_OUTPUT_TOKENS` overrides it.
`ATLAS_REQUIRE_ZDR` defaults to on. `false` or `--no-require-zdr` drops
`zdr: true` and selects from the model endpoint list. That switch is
flexibility. It is not how caching comes back: OpenRouter lists
`cache_control` on no endpoint, and a ZDR Bedrock Sonnet endpoint still
honors the breakpoint when the request sends it. Anthropic-family
routes (`anthropic/...`) therefore always send `cache_control`, with
`require_parameters` still true. Other models keep D51's intersection.
`data_collection: deny`, `allow_fallbacks: false` and the pinned `only`
list stay. The usage line and the completion span record whether ZDR
was required and whether `cache_control` was sent. No live call was
made from this repo. D57. Amends D51. D52 is unchanged.

## 2026-11-14 — round 4 on the per-lens continuation branch (#646)

A review appends one round record, after the final synthesize, from the
verdict over every lens and continuation. Each pooled lens and each
continuation had appended its own one-lens record, so one review could
store APPROVE and COMMENT side by side and spend the prior-round budget
on repeats. The lock that serialized those writes is gone. The pooled
path is tested for one record, one round-log read, the log-write note,
and a caller omission. `agentic-review --model` has a test. #640 has
merged since the 2026-11-12 entry above called it open, so D46 is on
main. No live call was made. D44, D52.

## 2026-11-14 — endpoint tiers and Safety Retention with ZDR off

A selected row's `pricing.overrides` count toward `max_price`, the
reservation and the fallback settlement. The base price alone was
short of a long-context tier. With the ZDR requirement off, a tag the
ZDR list marks Safety Retention is still refused unless the opt-in is
on, and an unreadable ZDR list refuses the call. The smallest context
and completion limit are the ones the request uses, and a row's
`max_prompt_tokens` caps the input when the row sets it. The usage
line and the completion span name the selected tags and those limits.
Sonnet 5.5's completion limit in the worked example is 128,000. The
one-shot path refuses a prompt over a row's `max_prompt_tokens` before
it is sent, and a bad tier names that row. A null `max_prompt_tokens`
is no ceiling: the live ZDR list and the Sonnet endpoint rows carry
the key as null. With ZDR off both the model endpoint list and the
ZDR list are read. No live call is made from the tests. D57.

## 2026-11-14 — a verified Major stays a comment

Brandon kept Majors as `COMMENT` in agentic reviews. A verified
introduced Blocker is `REQUEST_CHANGES`. A verified introduced Major
or Minor is approve-with-changes and `COMMENT`. Nits, and a review
with no verdict-setting finding, still approve.
`skills/synthesizing-review-findings/SKILL.md` says a single Blocker
is enough to block. `templates/REVIEW.md` calls that Blocker-only
GitHub state a deliberate choice, and offers
`unresolved_findings: block` with `unresolved_threshold: Major` for a
repo that wants Majors to hold the review. The agentic coordinator
does not read that file. D55.

## 2026-11-14 — the agentic dry run runs the lenses end to end (D59)

The shipped `agentic-review --dry-run` never reached a lens: its runner
was the one-shot's rules-only fake, which has no trusted-git step, so
bridge staging failed and every lens was NOT RUN, and its model never
called a tool. The offline pieces the tests already trust moved into the
package: `LocalSprites` (each exec's wrapper run locally, moved out of
the test helpers so there is one implementation), `LocalTasks` (the
Tasks API on a unix socket under the state directory, so the keepalive
hold runs for real), and a scripted reviewer (`lens_script.py`) driven
by a JSON lens script — fixed reading behavior (every changed file's
diff page by page, then the head files a finding cites), data-only
variation (findings per lens, validated by the real finding-contract
parser at load; `unread` for a coverage-gap scenario), and a
`--lens-script` flag that is refused outside a dry run. The shipped
fixture gains a merge-base tree (`source-1a2b3c4/`) and scenarios for
each verdict class under D55: a verified Blocker (the default, exit 5),
a Major plus a removed-line Minor (COMMENT, exit 0), an approve (exit
0), a coverage gap (exit 4), and a dropped finding (exit 4). The dry
run's attestation ledger is per run, so editing a scenario replays from
scratch. Nothing is read from the environment and no network client is
constructed; the deny-all read-back is asserted from the telemetry in
the end-to-end suite. The one-shot `review --dry-run` is unchanged.

## 2026-11-14 — #663, #664: redaction hardening and pre-request refusal bookkeeping

`redact` gains a `sprites-token` pattern in the shape the operator
confirmed the deployed token has -- four slash-separated segments,
`<org slug>/<numeric org id>/<token id>/<secret>`, only the second all
digits, the secret at least eight characters and carrying a digit -- and
scrubs each known credential's base64 (padded and unpadded), hex (both
cases), percent-encoded and JSON-escaped forms under the same label, so a
token the controller does not hold, and a log that carries one encoded,
no longer survive redaction; a value with undecodable bytes from the
environment scrubs instead of crashing (#663, round-1 review of #687).
The match may not start where a URL path's segment begins, so commit
and job links, wheel URLs and dated paths are not flagged; a bare
relative four-segment path at the start of a line still is (round-2
review). The one-shot provider records a fail-closed transport failure
of the ZDR-list or `/model` catalog GET in `budget.refusals`, and the
agentic adapter, which reaches `load_terms` directly, records the same
failures itself; the agentic draft shows the refusal through the lens
line's cause detail, not as a budget-refusals list (#664, round-2
review). The agentic loop gives a ZDR or pricing refusal its own
`MODEL_REFUSED` cause instead of `MODEL_ERROR` -- still failing the
lens, still not retried -- so the draft and the ledger name a policy
refusal rather than a model failure (#664). Every change names a test
that fails when it is reverted. D60.

## 2026-11-15 — a lens retry keeps the earlier attempts' verified findings (#691, D61)

The Nov 14 model trials left a hole in the retry path: `QUOTES_FAILED`
is retryable, so one unverifiable quote re-ran the whole lens, and
`next_step` let the last attempt's outcome stand — an empty or weaker
retry replaced findings the quote checker had already verified (21
verified findings lost across 12 trial runs, including a verified catch
of a real Minor on PR #661). A settled lens's outcome is now the last
attempt's with every earlier attested attempt's verified finding merged
into it, deduplicated, computed from the ledger alone in `next_step` so
every reader of a settle sees the same merge. The retry's reply is the
one that counts: a finding it restates stays its copy, an earlier
verified finding replaces the retry's unverified copy at the same
citation, and one the retry does not restate is appended. The identity
is location, severity, valence and attribution plus the normalized
finding and evidence text; route and fix are not the identity. Honesty
is unchanged by construction: the merged outcome keeps the last
attempt's attestation, causes, detail, unread list and changed-file
count, so a retry that still failed is still partial or failed, and
coverage reads the last attempt exactly as before. Only verified
findings from attested attempts are carried; an outcome whose last
attempt never attested keeps them on the ledger but reports none. The
retry prompt is unchanged — the body is still applied whole. Policy
tests in `test_attestation.py`, end-to-end over the real bridge with the
scripted model in `test_coordinator.py`. Offline only.

## 2026-11-15 — one lens's refused runner no longer aborts the review (D62)

The 2026-11-14 trials lost three reviews to Sprites capacity: about 12
pooled lenses created Sprites at once, the three waits of 1, 2 and 4s
that issue #636 left behind gave up, and the `CreateRefusedError` escaped
`future.result()` and crashed the review with every other lens's result
lost. A 429'd create now waits a schedule that doubles from 2s capped at
60s, `create_retries` waits long (default 6, about two minutes;
`ATLAS_CREATE_RETRIES`), honoring a Retry-After header the 429 carries
(read case-insensitively; a value the parser cannot read is None and the
schedule stands in) up to 120s a wait and truncated to the deadline the
runner has left. The coordinator passes its pooled lenses and continuations a per-review
gate of
`create_concurrency` (default 4, `ATLAS_CREATE_CONCURRENCY`), so at most
that many Sprites create at once; slot waits are telemetry events, and a
slot that never frees degrades that runner before any create is sent. A
create still refused after the schedule now degrades only that lens: it
is NOT RUN with why in the draft, the other lenses' results and
continuations run on, and coverage stays incomplete so the review cannot
approve. Because a 429 means the server made nothing, the create outcome
returns to `not started` for the wait, so a deadline that fires during
one degrades the runner with cleanup `NOT_CREATED` and no ledger entry
left. A 502 during a tree upload already failed only its runner; the
new tests pin that path too. Round 1 on the PR also pinned the
review-level wiring and bounds (the gate size, the retry count, the env
ranges and the literal defaults) its mutants showed unpinned. Folding
the plain positive-int limits' parser into the ranged one changed what
those nine limits say when they refuse -- "must be an integer, not X"
for a non-integer and "must be an integer of at least 1, not X" for a
below-one value, was "must be a positive integer, not X" -- both texts
pinned by test. Offline
only: no live Sprite, model or GitHub call was made.

## 2026-11-15 — Anthropic routes pin one endpoint, and the draft counts prompt-cache misses (#695, D63)

The Nov 14 trials' Sonnet runs paid to rewrite the whole context on
about a third of their turns: the default pin's bare `amazon-bedrock`
slug matched every eligible Bedrock endpoint, regions included, each
endpoint keeps its own prompt cache, and consecutive turns of one lens
conversation alternated between them (72 of 146 turns missed on #661,
46 of 179 on #640; cache writes ran 1.73x and 1.66x the sessions'
final contexts). Haiku, served by Google Vertex all run, missed none
of its 217 turns. An Anthropic-family model id (anything under
`anthropic/`) now defaults `provider.only` to the single endpoint
`google-vertex/global` — of the three tags with a `safety_retention:
false` ZDR row for both that Sonnet and that Haiku on the list
(`google-vertex/global`, `google-vertex/europe`, and
`amazon-bedrock/eu-west-1`), it is the cheapest, at $0.10 cache read
and $2.50 cache write per million against $0.11/$2.75 on both others,
and the only region-unbound one; the bare `amazon-bedrock` tag prices
the same for Sonnet but has no Haiku row and expands to regional
endpoints. Any other model keeps
the four-slug pin, and `ATLAS_PROVIDERS`/`--providers` still overrides.
A pin the list does not serve is refused before any request, so a bad
pin fails loudly instead of spreading. The agentic draft gains a
`## Prompt cache` section: per session (one conversation, bounded by
the system prompt), the turns, the turns whose reported cached tokens
fell short of the previous turn's prompt (or reported none), the
cache-write total, and the final context, plus a run total of writes
against the summed final contexts — the check issue #695 names for
confirming the fix on any future run. `cache_stats.py` holds the
tracker, model-agnostic; `OpenRouterLensModel` feeds it. Offline only:
no live model call was made for this change, and the tests pin every
rule with fakes and recorded HTTP.

## 2026-11-15 — a rejected quote is repaired in the session, and the checker tolerates a small offset (#697, D64)

The Nov 14 trials made the retry path the most expensive failure mode:
all 7 Sonnet retries were `QUOTES_FAILED`, one failed quote re-ran the
whole lens from turn 1 ($2.00 on #661, $0.69 on #640), and every failed
quote was text that really is in the head file — two one line off, two
span mismatches, three 9–62 lines off. Two changes, on the quote checker
and the loop only. The checker's drift search is generalized: a quote of
whole lines may now match a window of the quote's own line count starting
within three lines of the citation's first line (`ATLAS_QUOTE_TOLERANCE`,
default 3, bounded 0–8), so an off-by-one citation and a span mismatch
verify with the finding's location corrected to the lines that hold the
quote; fragments never drift, removed-line matches still win, and nothing
outside the window verifies. A quote that still fails earns a bounded
repair turn in the same conversation (`ATLAS_QUOTE_REPAIRS`, default 1,
bounded 0–3): the rejected locations, reasons and quotes go back fenced,
the model corrects the range or drops the finding, and the answering
reply is re-checked by the same checker, with the held reply's verified
findings merged in through D61's `_merged_findings` — #694's merge
reused, not duplicated. When the bound is spent and quotes still fail,
the attempt keeps `QUOTES_FAILED` exactly as before, with the bound named
in the detail; the ledger's `nudges` and the completion span record the
`quote-repair` turn, and the draft's lens line counts repair turns and
window corrections. Tests in `test_quotes.py`, `test_lens_loop.py`,
`test_agentic_limits.py` and `test_coordinator.py`, each behavior also
checked against a killed mutant. Offline only.

## 2026-11-15 — round-1 review fixes for #703: the repair's failure paths keep the verified findings

The round-1 protocol review of #703 traced two failure paths the happy-
path tests did not cover. A repair reply that never attests — a second
contract refusal, or one naming another lens — used to become the
attempt's recorded outcome, and D61's attested-only merge then dropped
the held reply's verified findings on the retry: an attested empty retry
settled the lens clean with nothing to report and the review approved.
The held reply's attested judgment is now what the attempt records, with
the failed repair reply's causes and detail folded on, so the verified
findings report, block approval, and carry to the retry. A contract
repair queued after a quote repair used to overwrite the held judgment
with the unparsed one, so a stop before it was sent dropped the findings
too; the hold stays the quote hold's with the refusal folded in. The
repair turn is counted — `nudges`, the span, the draft's lens line —
only when its call is sent, so a stop in the gap no longer counts a turn
that never ran (the unread and no-progress labels keep D58's queue-time
recording, which their tests pin). The posted source tag is built from
the match's own distance instead of the configured window, so it stays
true at any setting, and `QuoteSource.HEAD_NEAR` no longer hardcodes the
number; a float is refused at the quote-limit check before it could
break the window mid-review; the repair message marks a quote cut at 120
characters; and the three mutants the round-1 review found surviving —
the equal-distance tie-break, removed-lines-wins over an in-window head
match, and the `resolve()`-layer bound rejection — are pinned by tests.
D64's update paragraph carries the same record. Offline only.

## 2026-11-15 — round-2 review fixes for #703: the misacknowledged repair leaves a trace

Round 2 verified every round-1 fix and left one Minor: a repair reply
that named another lens folds nothing onto the held judgment (a
misacknowledged outcome has no causes and no detail), so the recorded
attempt read character-for-character like a repair that attested and
still failed its quote. The fold now records the attestation's
controller text as the detail on that path, and both round-1 Major
tests assert the recorded first attempt through the ledger, not only
the lens after the retry — so the fold's causes and detail are pinned,
along with the contract-repair fold's validator message. The held
outcome's fold is pinned to the attempt's current tools, turns, unread
list and nudges (a scenario where the repair turn's tool work closes
coverage before the cap lands), a budget refusal before the repair call
is pinned uncounted, the ledger's `drift` validation is pinned by a
damaged line that fails closed, and the env parser's tolerance cap is
pinned by its own message. The unread list now flows through one
`_Progress.unread()` accessor, which is where #704's shared-prefix path
will land its bookkeeping (the accessor takes no different value today).
D64's Telemetry and Reversibility sentences were corrected to the
`drift_label` tag, the "head near the citation" value and the
backward-readable `drift` ledger field, and the README's other limit
count now says twelve. Offline only.

## 2026-11-15 — the review's lenses share one cached prefix (issue #696, D65)

Every lens session paid to write the whole diff into its own cache: the
lens-specific system prompt came first in every request, only the
automatic top-level `cache_control` was sent, and no two lenses could
share a cached block — on the Nov 14 trials each Sonnet session read
every changed file's diff through `diff_file` (32k tokens on #661, 44k
on #640, 60–65% of a lens's final context), and every turn 1 reported
`cached_tokens: 0`. A lens request is now laid out so a byte-identical
block comes first and carries its own explicit `cache_control`
breakpoint: the tools, a shared system text (the prefix instructions,
the review's one fence nonce, the Finding contract) and the fenced
whole diff of the files the lens was given; the lens skill and the
turn-1 message follow inside the same user message. The fence nonce is
minted once per review instead of once per lens, which is what makes
the prefixes byte-identical across lenses and across a lens's retry;
the fence's nonce scrub keeps diff text from closing the shared block
early, and the nonce still comes from the CSPRNG, not from PR content.
The size threshold is `diff_prefix_share` (default 0.5,
`ATLAS_DIFF_PREFIX_SHARE` / `--diff-prefix-share`) of the model's
resolved per-call input cap, so it is configurable and model-aware;
above it, a model that cannot name an input room, a scope any of whose
paths has no section in the diff, or share 0 all page through
`diff_file` exactly as before, and
each names its reason in a `diff_prefix` note the ledger records and
the draft's lens line shows. On the prefix path coverage is attested
from what the prefix held — a lens that calls no tool is clean — and
the unread-list nudge and the `diff_file` page bookkeeping are retired
there; the paged path keeps both and its honest-coverage rule. First
wave: no warming — the lenses fan out as configured, each may write the
prefix (about $0.24–$0.33 per review at the cited sizes, because the
`agentic-review` command defaults its pool to 4 — `AGENTIC_POOL` in
`cli.py`, not the `AgenticLimits` default of 1 — so a flagless first
wave starts its lenses together and up to three of them write the
prefix at the $2.50/M write price), because warming would serialize
the first lens ahead of the pool and spend review wall clock on
ordering the pool does not need. `cache_stats` gains each session's opening-turn cache read —
on the prefix path that count is the shared prefix's read for the
session — so the saving reads straight off the draft. OpenRouter's
prompt-caching page (fetched 2026-11-15) grounds the per-block
breakpoints across Anthropic-compatible providers. The page's sticky
routing keys on the first system and first non-system message, and the
prefix leaves the first non-system message lens-specific — it carries
the lens skill and the turn-1 text after the diff — so the routing hash
still differs per lens: the locality comes from D63's endpoint pin, and
the cache sharing from the explicit breakpoint over the byte-identical
first part. The combination of the top-level automatic field with the
explicit block was not probed live (verify). The dry run keeps the paged path, which
keeps the `gap` scenario's coverage gap reachable. Offline only: no
live model call was made for this change; the tests pin the byte
identity over serialized request bytes, the breakpoint, the threshold,
coverage on both paths, the nudge, the fencing, and the per-session
prefix read. The README's limit counts count every `agentic_config.ENV`
entry — the command-scoped pool and the prefix share included — which
is why the merged total reads sixteen after the #698 merge, where
main's earlier count left the pool out.

## 2026-11-15 — the no-progress window counts stalled turns, on both paths alike (issue #705, D66)

The Nov 15 Sonnet measurement on #640 found 5 of 12 lenses getting the
"finalize now" nudge at about turn 6, where none did on the Nov 14
baseline, with lens sessions averaging about 4 turns against about 13
and verified findings down to 10 from 20. The cause was D65's seeding:
`_Progress.covered_at_turn` started at 0 on the shared-prefix path, so
D58's no-progress window counted from the lens's first turn — a lens
whose diff arrived inline in the prefix got about 6 turns of
exploration in total, where the paged path gave it 6 turns after
finishing its diff reads, and on neither path did the window reset when
the lens was actually making progress. The window now counts
consecutive turns that brought the lens nothing new, by one rule on
both paths: a turn makes progress when one of its bridge calls
succeeded with a (tool, validated-args) pair the attempt has not
successfully run before — a new file, a new diff page, a new search, a
new HEAD read; an empty result still counts — or when a judged final
reply carried a verified finding the attempt has not recorded before
(the finding's `repr` is the signature, so a repeated finding is not
progress). A failed call is never progress. `no_progress_turns`
consecutive stalled turns inject the one finalize nudge as before; the
duplicate-call trigger, the max-turn/max-call/dollar/clock guards, the
`ATLAS_NO_PROGRESS_TURNS` configuration and the `nudges` vocabulary
are unchanged, and no default was resized — per Brandon's standing
rule the limit guards runaway loops and costly failures, not review
cost. The nudge text now names why it fired and the turns it counted
("No turn since turn 1 has brought new content or a new finding: 6
turns without progress, as of turn 7"), so a run shows which lenses
hit the limit and on which turn. `_Progress.covered_at_turn` is gone,
with D65's P17 test replaced by the shared-window tests (mutants NP1–
NP5 pin steady progress never nudged, the exact stall count on each
path, and both reset signals). Tests use fakes only; the stalled turns
are turns that call nothing (`NOTHING` in the agentic fixtures), and
the paged-path pin counts a lens fumbling before coverage, which the
old window never reached.
Offline only: no live model call, network call or secret, and no
deployed service setting changed.

## 2026-11-15 — round-1 review fixes for #707: the window counts final-reply turns, and the stall shapes are tested

The round-1 protocol review of #707 came back COMMENT (2 Minor, 3 Nit).
A nonterminal final reply that queues a follow-up turn — the contract
repair, the unread-list nudge, a quote repair — and brings no new
verified finding was never counted: the window counted only tool turns,
so up to about five bounded follow-up turns per attempt escaped it. The
judgment turn is now counted as a stalled turn in `_accept_or_repair`,
with the detector checked before the follow-up is queued, so the
finalize nudge and the queued follow-up compose in one conversation the
way the nudge composes after tool results; D66's "every other tool
turn" wording is corrected in place, and a test pins the probe shape
(read, stalled tool turn, finding-less reply with a file unread, then a
stall — the nudge fires on exactly the second non-progress turn). The
review also found the stall tests only drove `NOTHING`, a shape the
live adapter never produces, and five predicate mutants survived the
whole suite; the stall tests now run the production shapes — rejected
calls (an empty `grep` pattern), a repeated successful call with
`duplicate_calls` raised above the window, an all-unverified reply, the
attempt scope of `seen_calls` across an intervening call, and the
co-fire where the duplicate trigger wins — and M1, M2, M5, M8 and M9
die on them (M3, M4, M6, M7 and NP1/NP3 re-verified dead). D65 carries
an appended Correction pointing at D66 for its obsolete
accessor-bypass clause and P17 reference; D66's revisit clause now
names argument variation (ever-increasing `diff_file` offsets,
near-identical `grep` patterns, alternate path spellings) as the first
suspect for a lens dodging the window, bounded by the unchanged caps;
and D66 states that a transport-timed-out turn is not counted while its
one retry counts once. The round-2 review (APPROVE, 2 Nit) added one
more pin: the `atlas.nudge` span naming is now checked end to end
through the production trace wrapper on a nudged attempt
(`test_a_nudged_attempt_names_the_nudge_on_the_completion_span`),
killing mutant R5 — dropping the loop's `note_nudge` from the detector
had passed the whole suite — and the round-1 entry's "verified filing"
typo is corrected to "verified finding". Offline only.

## 2026-11-15 — the agentic review passes the PR conversation and the round log into every lens, and the picker gets the PR body (issue #709, D67)

The lens-budget plan's S1. `review_lens` had accepted `context=` and
`round_log=` since D52, but no shipped caller passed either, so the
agentic lenses' first turn never carried the PR conversation and the
picker saw only the PR title, so process and claim findings such as the
m1 mutant pinned on issue #661 were unreachable in a real run.
`_cmd_agentic_review` now
builds the one-shot path's `Conversation` (parse, commits through the
new `gather.pr_commits`, remarks through `fetch_remarks`,
`build_conversation`) and passes `conversation.review_context` plus its
omissions into `review_lenses`, together with a `RoundLog` at
`<state dir>/rounds.jsonl` — the caller-chosen path D52 left open — so
the prior rounds open the first turn and the review appends its own
record. The picker's pull-request block is the one-shot view, title and
body, redacted and fenced: `conversation.picker_block` is now the one
helper both pickers call. The sizing D52 left to the caller is here
too: the model's resolved per-call input room minus D65's prefix share,
the largest loaded lens body, the turn-1 framing measured from the
diff, and an 8,192-character reserve for the controller text
(`CONTEXT_RESERVE_CHARS`) bounds the context blocks; a block that does
not fit is rebuilt smaller under the same recorded-omission trail D38
uses, and one that still does not fit is left out whole and named —
never silently truncated, never sent to overflow the per-call token
check. A model that names no room keeps the D52 fixed caps. A partial
context cannot approve and stays COMMENT, unchanged, and the parity
gate is unchanged. Six behaviors pinned in
`atlas_reviewer/tests/test_agentic_context.py`, mutants M1–M6 applied
by hand and killed by their named tests (drop `context=`, the
title-only picker, body-as-instructions, room without the prefix share,
`round_log=None`, silent slice). The diff stays off #717's files: no
`review_wide.py`, `agentic_config.py`, `lens_loop.py`, coordinator,
`test_coordinator.py` or `docs/agentic-reviewer.md` change, and D68 is
untouched. Offline only: fixture, scripted reviewer and fakes; no live
model call, network call or secret, and no deployed service setting
changed. The live confirmation that #661 m1 is reachable stays with S0
(#708).

## 2026-11-15 — round-1 review fixes for #718: the omits-whole gate is the mechanism, the positive-fit path is pinned, and the stale caller claims are cleared

The round-1 protocol review came back COMMENT (2 Major, 1 Minor, 3 Nit),
all fixed on the PR branch. M-1: the unparseable-pull guard had no test
and its deletion survived the whole suite — a fixture whose pull
carries no `head.ref` (the reachable shape; a headless pull is refused
by `_require_head` first) now pins no crash, exactly one `pull request
fields` omission, the COMMENT-not-approve outcome, and the picker's
title-only fallback (kills N1). M-2: the positive-fit sizing path was
untested and its mutant (N7, first build at D38's cap alone) survived —
the refit loop the first wording described is gone entirely: the block
is first built at the room's own size, and one rebuild at a quarter of
the room follows when the UTF-8 bytes overflow, whose bound holds by
construction (4 × (fit // 4) ≤ fit), so the omits-whole mechanism is
exactly the fit < 1 gate and no dead exhaustion branch remains. The
positive-fit test asserts the first build is the only build, the block
reaches every lens smaller than D38's build, and the prior rounds take
only what the conversation left of the room; a direct unit test at fit
56,000 over thirty multi-byte remarks pins the byte-bound rebuild
(kills M7, and with it the review's unreachable M6′). m-1: the README's
two "no shipped caller builds the path yet" sentences for `rounds.py`
are fixed here; `docs/agentic-reviewer.md`'s matching sentence is the
follow-up for whichever PR merges second (it is in #717's edit set).
n-1: `_input_room_chars`'s docstring states the first turn's real order
(prior rounds, then the conversation block). n-2: the remarks' fetch
errors are quoted with the one-shot's scrubber — the redactor augmented
with `scan_diff`'s flagged secret values, flagged before anything is
quoted — and D67's Correction states the one remaining difference (the
one-shot's controller-notes channel has no agentic equivalent yet).
n-3: the room accessor is public (`lens_loop.input_room_tokens`), no
private import from the CLI. Offline only, as before: fixture, scripted
reviewer and fakes; no live model call, network call or secret, and no
deployed service setting changed.

## 2026-11-15 — round-2 review fix for #718: the sizing counts the truncation marker, and the small-fit band is swept

MJ-1, the round's one new Major: the round-1 fix's two-build scheme
crashed at fit 1 to 3 — the rebuild asked `build_conversation` for a
zero-character budget (`fit // 4` at fit below 4), and the resulting
`ValueError` is one no CLI handler catches, so the review died with a
traceback instead of an omission — and its "fits by construction" byte
bound ignored `_truncate`'s 39-character marker, which a truncated
build appends after its cap, so a rebuilt block could ship up to 39
bytes over the room. The sizing is marker-aware now: the omit-whole
gate fires below 43 characters (one worst-case UTF-8 character plus the
marker — a room that small holds no block), the first build runs at
`fit − 39` (an ASCII build truncated to the room ships at exactly the
room's bytes in one build), and the multi-byte rebuild at
`(fit − 39) // 4`, whose bound `4 × ((fit − 39) // 4) + 39 ≤ fit` holds
by construction. A unit sweep over fit 1 to 60 in both byte widths
(ASCII and four-byte) pins no-exception and bytes-within-the-room;
the multi-byte test runs a four-byte variant beside the three-byte one;
and a marker test pins the first build's subtraction (a giant fixed
part truncated to the room ships in one build). Killed: the round-2
scheme as written (crash), M8 (its clamped variant, which ships a
40-byte block at fit 1), the skipped-marker first build, and a gate at
39 instead of 43. D67's second Correction also retracts the round-1
Correction's false unreachability claim: the deleted loop's exhaustion
branch WAS reachable for fit 1 through 39, because of that same marker
— the old code omitted whole there, which was correct. Offline only,
as before.

## 2026-11-15 — the review-wide limits derive from the planned lens count, under a $10 ceiling (issue #710, D68)

The flat review-wide defaults — 50 calls and a $5 reservation shared by
every lens, the picker and the continuations (D44) — stopped a 12-lens
review near 50 calls with lenses unrun: a missing-lens failure under the
parity gate, not a cheap review. `review_lenses` now derives its
review-wide limits from the planned lens count before any lens runs
(`review_wide.derive_review_wide`), and the per-lens values stay the
knobs: the call cap is the per-lens call budget
(`ATLAS_PER_LENS_CALLS` / `--per-lens-calls`, default 50) times the
planned lenses plus the picker's calls; the reservation is the per-lens
dollar budget (`ATLAS_PER_LENS_USD` / `--per-lens-usd`, default $5)
times the planned lenses plus the picker's committed dollars, clamped to
the absolute per-review dollar ceiling; and the review wall is the
configured wall raised to the lens wall times the planned waves — a wave
is one pool-full of planned lenses — raised, never lowered, so no review
loses wall clock it ran on before. The per-lens defaults are the
2026-11-11 review-wide defaults re-scoped per lens, so an unconfigured
one-lens review keeps the numbers it always had, and a review whose
planned lenses fit one wave of the default pool keeps its 60-minute
wall. The ceiling's default is $10 (`ATLAS_REVIEW_CEILING_USD` /
`--review-ceiling-usd`); the reviewed repo's own `REVIEW.md` overrides
it with a `review_ceiling_usd:` line read from the PR's base ref — the
file's own rule that the base copy governs, so a PR cannot raise or
lower its own ceiling — and precedence is repo, then configured, then
default, resolved by the one pure function `resolve_ceiling`, which is
the documented seam a later per-run policy adjusts the ceiling through.
No policy engine is built. An operator-set `--max-calls`,
`--reservation-usd` or `--review-wall-seconds` keeps the review-wide
meaning it always had and wins for that one limit;
`agentic_config.load_agentic_limits` records which in the new
`AgenticLimits.explicit` field, and the ceiling clamps the reservation
even when it is explicit. A derived call budget below the per-lens turn
cap is refused before any lens runs. A stop on a derived limit names the
derived values, the ceiling, the observed value and the knob —
`lens_loop.Derivation` builds the `LimitHit` texts and the ledger stores
the same fields — and the picker's calls are now added on top of the
derived lens budget instead of eating into it, so the flat cap's other
failure mode (one busy picker starving the lenses) is gone by
construction. The single-lens `review_lens` path and the one-shot
`review` command are unchanged; the service switch onto `agentic-review`
is #712 and waits on this. D66 is #707's (it merged into main while this
PR was open) and D67 is #709's, so the decision is recorded as D68. Offline only: the
tests run the real bridge through `LocalSprites` with scripted models
and fakes — no live model call, network call or secret read — and pin
the formulas, the clamp, the ceiling precedence, the `REVIEW.md` line's
fail-open parsing, both derived limit stops' texts, and the acceptance
run: a 12-lens scripted review with 15 turns per lens finishes with no
limit stop and complete coverage, while reviews pushed past the derived
calls or the ceiling stop with the derivation named. The mutants this
kills are pinned: dropping either x-lenses factor fails the formula
tests, dropping the ceiling clamp fails the clamp test, and dropping the
wave scaling fails the wall test.

Review round on this PR fixed three findings. The per-lens-against-
review-wide relations (`max_turns` no greater than `max_calls`,
`lens_wall_s` no greater than `review_wall_s`) were still checked inside
`resolve` against the configured review-wide values, which on
`agentic-review` are no longer the totals — the derivation raises them —
so a legitimate configuration such as a 60-turn lens budget with a
60-call per-lens budget, or a 4000-second lens wall, was refused before
the derivation could accept it. The two relations are split into
`_check_cross_limits` and now checked where the totals are known: the
derivation re-checks them against the derived values (structurally
satisfied by a derived budget and wall; refused for an explicit
review-wide value below its per-lens budget), the loader and every
multi-lens resolve site defer them, and the single-lens `review_lens`
path still checks them against its configured totals. The reservation
stop's clamp flag is taken from the value the clamp bit on — the
formula's value when the reservation is derived, the configured
reservation when it is not — so an explicit $40 reservation clamped to
the $10 ceiling on a one-lens review no longer reads as "the ceiling is
above it". And a `REVIEW.md` over the 64 KiB read bound is unparseable
rather than parsed cut, so a truncation inside the value cannot read as
a number it is not. All three are pinned in `test_review_wide.py`.

## 2026-11-15 — round-1 fixes for #717: the in-flight backpressure, the merge-base ceiling, and the refusal's exit path

The round-1 protocol review of #717 came back COMMENT (1 Major, 5 Minor,
2 Nit). The Major was the clamp's own edge: with the recorded catalog
terms a Sonnet call's worst-case reservation is about $2.72-$2.90, so at
defaults a 12-lens review at pool 4 projects four concurrent first-turn
worst cases ($11.60) against the $10 clamped reservation, and the fourth
lens's first call took a non-retryable BUDGET stop — the missing-lens
failure this slice exists to close, now from the clamp instead of the
flat cap. `Spend` now separates settled spend from in-flight worst cases
(`settled_usd`; every sent call settles, to its actual when that is a
cost and to its reservation kept as spent when it is not — D43's rule,
now also the timed-out and failed paths), and a reservation that would
pass the cap only because of other calls' in-flight worst cases waits,
bounded by the review wall, for one of them to settle instead of
stopping; it stops outright only when the settled spend plus its own
worst case cannot fit even with nothing in flight, or the wall runs out,
and spend never passes the ceiling. The picker's committed dollars are
settled from the start. The acceptance variant runs 12 lenses at pool 4
with the scripted worst case at $2.90 — it completes with full coverage —
and the deterministic kill for the revert-to-stop mutant is a unit test
that parks a fourth reservation against three in-flight worst cases and
settles one under it. The REVIEW.md ceiling is now stated as read from
the **merge-base** tree the review already fetches — the tree the PR
branched from, not the base-ref tip, which the code always read and the
docs overstated — with a coordinator test pinning that the merge-base
copy governs and a head copy does not; a seen-but-unusable ceiling line
still fails open but now carries a note through `Derivation` and the
draft's Model calls line, so a meant ceiling that silently fell back is
visible; the derivation's refusals are planned-count independent and the
CLI validates them before the picker spends, exiting EXIT_USAGE instead
of trace-backing after a billed picker call; the wave count gained its
non-multiple case (7 lenses at pool 4 derive 2 waves, killing the
ceil-division mutant the review found alive); D68 now carries an "amends
D55" clause for the coordinator's REVIEW.md read, D55 an appended
Correction, and the record that the #654 retry composition's per-lens
call share is a conscious acceptance; and the "the ceiling is never a
budget" prose now describes what actually binds — settled spend plus a
call's own worst case against the ceiling, with in-flight waits in
between. Offline only.

## 2026-11-15 — round-2 fixes for #717: the backstop arms only on a stalled clock, the exception-path settles are pinned, and the tight ceiling line parses

The round-2 protocol review of #717 came back COMMENT (1 Major, 2 Minor,
4 Nit) with the round-1 Major re-opened by the backstop itself:
`BACKPRESSURE_REAL_LIMIT_S` (10 s) armed on every wait, and 10 wall
seconds is shorter than the pinned model's typical first turn (31–46 s in
the D58 trials), so the fourth lens at pool 4 could still take a BUDGET
stop in production — the acceptance run had passed only because its
scripted turns take 0.2 s. The backstop now arms only when the review
clock shows no progress across wakeups — recorded at wait start,
re-checked each wake, disarmed the moment the clock moves — so on a
healthy clock the review wall is the bound however long a turn takes,
and a stalled clock (a stopped test clock, one that lies) still ends its
wait on the backstop. Two tests pin it: a freeing settle arriving after
22 seconds of clock advance — with the backstop shrunk to a quarter
second so the unconditional-backstop mutant dies in a second, not in
ten — still reserves; and a wait on a moving clock stops at the wall,
with the clock's reading at the stop naming the wall as what ended it.
The exception-path settles are pinned per exit — a turn stopped at the
output cap, a transport timeout with its retry, a transport failure, and
a model error each settle at their reservation (`settled_usd` equals
`committed_usd`), which kills the dropped-settle mutants C4 and C5 whose
survival had left the wall-bounded guarantee resting on an unpinned
invariant. The tight `review_ceiling_usd:15` form parses now (the
separator after the colon is optional; the round-2 regex had required a
space and silently dropped the tight form), a no-space unusable value
still routes to the note, and `_UNUSABLE_NOTE` (and the oversized-file
note) now say "the configured ceiling (default $10) stands", which reads
true when nothing is configured. A reservation parked in the wait when
the review halts comes back from `_reserve_call` as the halt outcome
(`HALTED_CALL`), not as a dollar stop. The timing-level pins for the
round-2 survivors: the wall-ignored mutant C9 and the halt-ignored
mutant C10 die on thread-and-join pins (a parked waiter must return
within two wall-seconds of the wall passing or of the halt), and C8 —
the genuine-stop check disabled — is left recorded as equivalent by
construction: the wait's own settled re-check returns immediately in the
same case, so the branch is a fast path, not a distinct behavior, and no
test can tell them apart without reshaping the code to kill a mutant.
C1/C7 (a dropped notify) stand as the round-2 review found them: the
0.05 s polling slice is the correctness mechanism and now carries a
comment saying so, with the C2 hazard (removing the slice because a
notify looks reliable) named in it. Offline only.

## 2026-11-15 — #717 merges #718 and pays D67's follow-ups; the frozen-clock wait is pinned (round 3)

Round 3 of #717's review APPROVED at `a2beea96`, and #718 (D67) merged
into main first, so the branch merged main (`5e39bd04`) with three
conflicts, all mechanical: `cli.py`'s import block keeps both sides
(#718's `TRUNCATION_MARKER`/`rounds` imports beside this PR's
`review_wide` import); the decision list reads D65, D66, D67, D68 with
both entries whole; and the session log lands main's three #718 entries
before this PR's three. `lens_loop.py` auto-merged — #718's public
`input_room_tokens` rename lives in the shared-prefix area, this PR's
backpressure in the `Spend` area — and both slices' suites pass
together. This PR merges second, so it owes #718's recorded follow-ups:
`docs/agentic-reviewer.md`'s "No shipped caller builds one yet" sentence
for `rounds.py` now names the shipped caller (`agentic-review` keeps
`rounds.jsonl` under its state directory and passes the log into every
review it runs); D67 carries an appended Correction — never editing
earlier text — withdrawing the four-byte rebuild test's kill claim for
the marker-blind `fit // 4` rebuild (equivalent-safe, by the
ASCII-prefix argument: the block's leading framing is ASCII, so a
build's bytes sit below the four-bytes-per-character bound by more than
the marker-blind size's few extra characters can consume — run on the
merged tree, the whole of `test_agentic_context.py` passes with the
mutant in), correcting the round-2 oversize band's extent to fit 50 (not
42), and stating that the 43-character omit-whole gate is a conservative
margin, not the minimum, since one content character plus the marker
needs only fit >= 40; `_MIN_FIT_CHARS`'s and `_conversation_block`'s
docstrings now state the margin as a margin. The round's one new test
pins the frozen-clock wait (m-8): a reservation parked on a frozen
FakeClock — no settle, no halt, a far wall, the backstop monkeypatched
to 0.3 s — returns with the reservation stop, killing the
progress-comparison mutant A9 (`now >= last_seen` reads every wake as
progress, never arms the backstop, and the parked wait never comes
back). The healthy-clock pin's ticker steps coarser (five seconds of
clock a tenth-second, n-9). Offline only.

## 2026-11-16 — the agentic lenses receive the head SHA's CI evidence (issue #715 Part A, D73)

The 2026-11-13 plan's phase 3. `gather.py` had collected check runs,
workflow runs and jobs since the one-shot path was built, but only that
path consumed them, so no agentic lens could name a real CI run and the
PR #661 m1 shape (a PR body claiming verification results the head's own
CI contradicts) stayed unreachable in an agentic review.
`gather_head_ci` now fetches the head SHA's own results only — the check
runs at the SHA, the workflow runs at the SHA, and the jobs of those
runs, under the one-shot `IngestConfig` caps, with no other commit's
checks, no branch-name listing and no log or artifact download (D25's
scoping; the one-shot's `_gather_run` lost its jobs half to the
extracted `_gather_jobs`, which it calls back into, so its behavior is
unchanged) — and the new `ci_block.ci_block` renders it with the
one-shot path's own `classify` + `render_evidence`, prefixed by the one
controller-written line in the block, which names the head SHA. The CLI
passes the block into `review_lenses` as one more `context=` block after
the conversation (the first turn's order is now prior rounds,
conversation, CI evidence, changed-files), with every gather failure —
an unfetchable listing, a malformed entry, a page-cap cut — converted
into an omission beside the assembly's, so `coverage_complete` goes
false and an approve-shaped review is held at COMMENT (D42): CI evidence
can never make a review approvable the omission gate would not. The
sizing is D67's, shared with the conversation: the block takes what the
conversation left of the input room, builds at
`min(16,384, room − 39)` characters (`CI_EVIDENCE_CHARS`, the size D52
gives the prior-round blocks), names a truncation at its cap, and is
omitted whole and named when its UTF-8 bytes still overflow — never
silently truncated; the omit-whole gate fires below 43 characters, the
same figure D67's round-2 review derived. The fence and nonce are
`first_turn`'s one fence; the picker keeps D38's view; the status line
gains no field; the draft shows CI evidence only through the existing
quote and scrub paths. Eight behaviors pinned in
`atlas_reviewer/tests/test_agentic_context.py`, mutants M1–M7 (and the
marker mutant M5b) applied by hand and killed by their named tests:
dropping the block from `context=` and dropping the head-SHA tag (M1,
M7), swallowing the gather's failures (M2), the fence-stripping mutant
that ships block text unfenced (M3), the gather reaching past the head
SHA (M4), removing the omit-whole gate (M5), the skipped-marker build
budget (M5b), and the wiring that hands the block no room (M6). The diff
stays off #717's files except the one file it must touch:
`atlas_reviewer/cli.py`, confined to the wiring beside D67's blocks and
the `_input_room_chars` docstring; no `lens_loop.py`, `review_wide.py`
or `agentic_config.py` change, no coordinator change at all, and the
docs logs appended only. Part B of the plan (the sandboxed
`run_tests`/`mutate` tools) is
untouched. Offline only: fixture, scripted reviewer and fakes; no live
model call, network call or secret, and no deployed service setting
changed. The live confirmation that #661 m1 is now reachable stays with
S0 (#708).

## 2026-11-16 — round-1 review fixes for #724: the CI block is sized against the room the conversation left, and the overlap sentence says so

The round-1 protocol review came back COMMENT (1 Major, 2 Minor, 2 Nit),
all fixed on the PR branch. Major 1 (also CodeRabbit's inline Major on
`cli.py`): `ci_block` was handed the full `fit`, so a conversation near
its cap plus a near-cap CI block could overrun the fit by more than the
8,192-character reserve, starving the prior rounds to one character and
risking a per-call refusal — the reviewer's worktree arithmetic showed
+2.8k to +3.4k over the fit at ordinary rooms. The root fix: the CLI now
passes the fit minus the conversation block's UTF-8 bytes
(None-preserving) as `ci_block`'s room, so `sum(context bytes) ≤ fit`
holds by construction and the prior rounds take the remainder; a
conversation that leaves almost nothing trips the 43-character
omit-whole gate and names the omission. The regression test
(`test_the_ci_block_takes_the_room_the_conversation_leaves`, two
conversation sizes under the approve scenario) records the fit and the
room the block was actually handed and asserts `room == fit −
conversation bytes` plus either `sum(context bytes) ≤ fit` or the named
CI omission — killing M8, the revert to full-fit sizing, whose claimed
pin in the first cut (M6's test) fired through the byte gate alone and
pinned nothing about conversation-relative sizing; M6's test docstring
now says what it actually pins. Minor 3: the "diff stays off #717's
files" sentences were false for `cli.py` (it is in #717's edit set) —
D73 and the session-log entry are new in this PR, so both say the
exception first in place; the first commit message repeats the false
clause and stays as written, since history is not rewritten. Nit 4: the
marker and minimum-fit figures now live beside `redact.TRUNCATION_MARKER`
(`TRUNCATION_MARKER_CHARS`, `MIN_FIT_CHARS`), imported by `ci_block.py`;
round 2 replaced this round's alias arrangement in `cli.py` — which
conflicted with #717's edits of the same lines — with `cli.py` keeping
its own main-side derivation of the same figures and a test holding the
two copies equal. Nit 5: D73 now states the asymmetry once —
the conversation block rebuilds once smaller on a multi-byte overflow
because `build_conversation` can drop the oldest remarks, while
`render_evidence` has no refit, so the CI block omits whole instead.
Minor 2 is recorded, not fixed: a settled lens reused for the same head
and body never sees the CI evidence gathered for the later review (the
CI block is not in the reuse key), the same gap the conversation block
has had since D67; whether context-derived data belongs in the reuse key
is an owner decision on the reuse contract, recorded as an open question
in D73, and no reuse key changed here. The session-log merge note: this
file and #717 both append at EOF, so whichever merges second conflicts
mechanically — keep both dated entries. Offline only, as before:
fixture, scripted reviewer and fakes; no live model call, network call
or secret, and no deployed service setting changed.

## 2026-11-16 — round-2 review fixes for #724: the sizing constants go back to cli.py's main-side lines, and the byte measure is named and pinned

The round-2 protocol review came back COMMENT (2 Minor, 1 Nit), all
addressed on the PR branch. Minor R2-1: round 1's Nit-4 alias arrangement
in `cli.py` — renaming the `redact` import line and rewriting the
`_MARKER_CHARS`/`_MIN_FIT_CHARS` block #717 also edits — had moved
`cli.py` into conflict with #717's head (`git merge-tree --write-tree`
against `70d9110b` confirmed two hunks: the import line and the
constants block). `cli.py` now keeps its import line and both constant
definitions exactly as main has them, `redact`'s shared constants serve
`ci_block.py` alone, and
`test_the_cli_sizing_copies_agree_with_their_shared_home` holds the two
copies equal (kills M10, a drifting copy); the PR body states the real
merge-tree result. While this round was in flight #717 merged to main
(`1c230180`), so the branch merges main with a normal merge commit
(`d9dfbaf6`) and the #717 conflict is resolved in that merge: `cli.py`
keeps both import lines and #717's `_MIN_FIT_CHARS` docstring — its
"conservative margin, rooms of 40 to 42" note intact, content and not
noise — alongside this PR's `ci_block` wiring, and the session-log EOF
conflict is resolved by keeping both sides' dated entries in
chronological order. Minor
R2-2: the CLI's conversation measure is named `conversation_bytes` (it
was `conversation_chars` while holding UTF-8 bytes), and
`test_the_ci_block_takes_the_room_the_conversation_leaves` gains a
four-byte parametrization — the multi-byte remark bodies the
conversation byte-budget tests use — under which the chars-instead-of-
bytes mutant M9 fails while both ASCII parametrizations pass under it,
which is exactly why the mutant had survived round 1's test. Nit R2-3
(D73 amended in place rather than by a Corrections append): no change —
D73 has never landed on main, the session-log preserves what changed
and why, and the amendment is flagged in the entry itself. Offline only,
as before: fixture, scripted reviewer and fakes; no live model call,
network call or secret, and no deployed service setting changed.

## 2026-11-16 — the owner decides the reuse-with-newer-evidence question D73 raised (docs only)

Brandon's decision on round-1 Minor 2, given 2026-11-15 8:32 PM CT and
recorded in D73 in place of the open question (D73 has not landed, so
the in-place amendment stands, as round-2 Nit R2-3 accepted): "it's a
little of both. we shouldn't toss out findings just because more
information comes along, but the agent should re-assess their judgement
and follow up accordingly if the new information changes anything." A
reused settled result keeps its findings — newer CI evidence or newer
comments never discard them — and, when newer CI evidence or comments
exist since the reused result was produced, the lens re-assesses its
judgment with that new evidence and adds, revises or follows up on
findings where the new information changes anything. The re-assessment
behavior is not implemented in this PR: the reuse key and the reuse code
are unchanged, and the behavior is the follow-up the decision records
(#726), covering the conversation block's identical gap since D67. Docs only:
`docs/open-questions.md` (D73) and this entry; no code, no test, no
generated or mirrored file, and the full local gates were green on the
merge before this docs-only commit.

## 2026-11-16 — the webhook service's child follows a service mode: agentic by default, one-shot kept (issue #712, D70)

The deployed Fly webhook app had started the one-shot `review` command
since D53, so every posted review ran only tracing and security —
migration, concurrency and pr-hygiene were skipped and the picker was
never called. Brandon's Nov 15 decision moves the service onto
`agentic-review` and keeps one-shot as a selectable mode. `service_run`
now resolves `ATLAS_SERVICE_MODE` (`agentic` unset; unknown refuses
startup through `config_from_env`), `review_argv` builds the matching
argv — same `--event`/`--out`/`--events`/`--provider` wiring for both —
and `RunConfig` validates the mode, so nothing can silently pick a
command. The agentic `ATLAS_*` limits (`agentic_config.ENV`, D68's
`ATLAS_PER_LENS_CALLS`/`ATLAS_PER_LENS_USD` and the $10
`ATLAS_REVIEW_CEILING_USD` included) join the child allowlist; the
one-shot child ignores variables it does not read, and token-like names
(`FLY_API_TOKEN`, the webhook secret) still stay in the parent. The
parent's hard 1,200-second wall becomes `ATLAS_SERVICE_DEADLINE_S`
(60–14,400 seconds, startup-refused outside the bounds) because a slower
model needs more time. The posted body stays COMMENT-only (D46);
`summarize_draft` dispatches on the status line's `"mode": "agentic"` and
maps the agentic draft — selection NOT RUN bullets, ledger lens lines
(`clean`/`partial` run; `failed`/`NOT RUN` not), a coverage note from the
status line's controller counts, and the status line's limit stop, the
context omissions and the ceiling note as Limit stops — with the
`Model calls:` line as Cost; runner and round-log prose that shares the
coverage section when no cache section follows is excluded. The fixture
parity test runs the real `agentic-review` dry run through the faked
`popen` and asserts the posted COMMENT lists every planned lens as run,
`Lenses not run: None.`, and the coverage note. The mode flip on the
running app is a separate approved deploy and was not made here. Offline
only.

## 2026-11-16 (same day) — round-1 fixes for #727: the deadline covers the child's wall, and the runner's failure note is not a limit stop

Round 1 of #727's protocol review returned COMMENT with one Major: the
shipped default left the parent's wall at the D53 one-shot 1,200 s, a
third of the agentic child's default derived review wall (3,600 s), so a
healthy multi-lens review was SIGTERMed mid-run and posted nothing —
silently, on every push. `service_deadline` is now mode-aware: oneshot
keeps 1,200 s; agentic derives its default from the child's own
configured review wall (`agentic_child_wall_s` reads `ATLAS_REVIEW_WALL_S`
through `agentic_config.load_agentic_limits`, the same configuration the
child reads; D68's derivation only raises the multi-lens wall above it)
plus the SIGTERM teardown wait — 3,690 s at defaults, following an
operator-raised child wall. An explicit `ATLAS_SERVICE_DEADLINE_S` below
the child's wall refuses at boot rather than warning: the service already
refuses to start on a bad port, secret, concurrency or provider, the boot
refusal is what the deploy's readiness checks see, and the alternative is
a service that starts and then silently kills every review it queues. A
child wall the 14,400 s ceiling cannot cover refuses too. The README and
deploy-service.md state the pairing and say plainly that a deadline kill
posts nothing (job FAILED, telemetry event, Sprite already destroyed, a
later push can requeue). The runner's `Runner reported, quoted:` note —
a real `coordinator.render_draft` shape the round-1 review caught landing
in Limit stops when no prompt-cache section precedes it — joins
`_AGENTIC_NON_LIMITS`, with the test built from the real renderer in the
runner-failed state. The incomplete-coverage note with no unread file is
cause-neutral now (the status counts do not name the gap). `make_runner`
labels every draft-parse failure — including a status line that will not
parse, and the version-skew shape of a draft whose status line disagrees
with the service's mode (`summarize_draft`'s new `expect=` keyword) — as
`draft parse failed`, still posting nothing. Recorded in D70 and the PR
body: issue #712's `REVIEW_DEADLINE_S` is implemented as the env var
`ATLAS_SERVICE_DEADLINE_S` (no alias), and the service's agentic round
log is per-head until #728 lands. The session-log rotation nit is
pre-existing debt and untouched. Offline only.

## 2026-11-16 (same day) — round-2 fix for #727: the agentic deadline default is the ceiling, a backstop not the limit

Round 2 verified five of the six round-1 fixes by execution and accepted
the round-log deferral, and narrowed the deadline Major: the mode-aware
default still tracked only the configured wall, while D68's waves raise
(`max(configured, ATLAS_LENS_WALL_S x ceil(planned/pool))`) happens
inside the child after the picker plans — invisible to the parent. At
the shipped pool of 1, a plan of 4 or more lenses derives 4,800 s or
more against the 3,690 s default; the parity fixture's own 4-lens plan
was the boundary case. The unset agentic default is now the deadline
bound's ceiling itself (14,400 s, the same constant the bound check
uses): in agentic mode the parent deadline is a backstop, not the real
limit — the child's derived wall and the $10 ceiling stop the review.
The boot refusal stays for an explicit deadline below the *configured*
wall (the only part of the child's wall the parent can see), and the
residual is the operator's to cover: the README and deploy-service.md
now state that a plan's derived wall can reach
`ATLAS_LENS_WALL_S x ceil(N/pool)`, that an explicit deadline must cover
the plans you expect, and that at pool 1 plans of 13 or more lenses
exceed even 14,400 s — raise `ATLAS_POOL_SIZE` or lower
`ATLAS_LENS_WALL_S` for those. The child's limits are still validated at
boot with the default in place, and a limit variable the loader refuses
now names the environment variable (`ATLAS_REVIEW_WALL_S: ...`), not the
loader's internal field name. Mutants killed: reverting the default to
configured-wall-plus-margin, and dropping the naming wrap. Offline only.

## 2026-11-16 (same day) — round-3 fix for #727: the wall-above-ceiling boot refusal is back on the default path

Round 3 verified the round-2 fixes and the #724 merge, and caught one
Minor: the round-2 change had removed the round-1 refusal of a
configured child wall above the deadline ceiling along with its
now-unneeded default branch, but the undercut it guarded stayed
reachable on the default path — `ATLAS_REVIEW_WALL_S` above 14,400 s
with no explicit `ATLAS_SERVICE_DEADLINE_S` booted the service with a
14,400 s deadline below the child's configured wall, killing every
review it queued, silently. The comparison is restored on both paths:
`wall > MAX_SERVICE_DEADLINE_S` refuses, naming `ATLAS_REVIEW_WALL_S`
and telling the operator to lower it. The restored assertions in
`test_an_agentic_deadline_below_the_child_wall_refuses_at_boot` cover
the default path and an explicit value, and kill the mutant dropping
the comparison. The docs name the case in one line each. The round-3
review also flagged commit `3a7f66f4`'s message as garbled (a pasted
shell line embedded twice); noted in the PR body for cleanup at merge
rather than a history rewrite. Offline only.

## 2026-11-16 (same day) — fix: the agentic and --sequence paths now honor the parent-minted installation token

The first live agentic review on the deployed service (Fly v5, D70) died
at boot with `this command needs the ATLAS_GITHUB_APP_ID environment
variable`: the parent mints a read-only installation token and passes the
child only `ATLAS_GITHUB_INSTALLATION_TOKEN` (`_CHILD_ALLOWED` withholds
the App id and key by design, D53), but `_live_github` and `_probe_source`
called `_app_tokens` unconditionally while `_live_wiring` alone checked
for the fixed token first. The token choice now lives in one
`_review_tokens` helper all three live call sites ask: fixed token when
set, App-minted otherwise with the existing `_require_env` checks — so
the paths cannot drift apart again, and no new credential crosses the
child boundary (`_CHILD_ALLOWED` is untouched). Redaction is unchanged:
the minted token still goes through `credentials.register`, and
`_Credentials` already seeds the env token. Pinned by tests at each path
(agentic command, `--sequence` tarball fetch) that pass only with the
token and no App credentials, a boundary test feeding `service_run`'s
`child_env` output straight into the agentic wiring — the test that
would have caught this — and fallback tests that the clear
`ATLAS_GITHUB_APP_ID` usage error survives when neither credential is
set. Mutants killed: reverting `_live_github` to `_app_tokens`
unconditionally fails the agentic and service-boundary tests; reverting
`_probe_source` the same way fails the `--sequence` test. Round 1 of the
PR's own review first had the fixed-token branch refuse
`--include-issues` up front; Brandon amended that the same day: the
parent's mint now includes issues read (read-only, on every mint — the
mint happens before the child exists and `review_argv` builds no
`--include-issues` flag a conditional mint could key on), and a
permission error on an optional read degrades instead of refusing:
GitHub's 403/404 on issues, checks, actions or any optional context read
is already caught by the gather's `_attempt` and the controller's
`_issue_block`, recorded as a gap in the draft's coverage notes with the
failed read as a telemetry event, while a 403 on a read the review
cannot proceed without (the PR, its diff, the head contents) still fails
loudly with exit 3. The up-front refusal is gone: a fixed token plus
`--include-issues` wires and lets the read proceed. Pinned by the
one-shot and agentic paths building from the fixed token with
`--include-issues`, an issue read refused for permission noted and
continuing with its telemetry event, a required read refused for
permission exiting 3, and the service mint asserting the five read
permissions. Precedence when both the fixed token and App credentials
are set is pinned with a mint-attempt guard, killing the mutant that
mints whenever the App id is present. The deploy runbook now names the
issues read in the child token's grant; `docs/agentic-reviewer.md` puts
the App key on the controller, unchanged; no new D number. Round 2 of
the PR's own review: the runbook's installation paragraph now also
states the App itself must grant read on contents, checks, actions,
pull requests and issues, because an installation missing any of them
fails every mint at review start and no review posts; the
wiring-with-`--include-issues` pin is parametrized over the one-shot and
agentic paths; and a failed mint's error names the five read
permissions it requested and hints that the installation may be missing
one, without ever carrying the key. Offline only.

## 2026-11-16 — the lens picker chooses any number of lenses, and a repo preference overrides the guideline (issue #711, D69)

The picker was hard-capped at 8 names at review depth (40 at
comprehensive, one-shot), with instructions that said extras "are
dropped" — contradicting the guideline's own "not a strict cap" — and
hygiene, added ahead of the picks since D58, could spend one of the 8
slots because the picker was never told it was already in. Auto-includes
depended on the model under that slot economy, which is how the #640
module-design Major went missing. Brandon had settled the direction on
Nov 15: the picker chooses any number of lenses, the skill bundle's
guideline (default selection and auto-includes) governs, repo
preferences override it, and the $10 review ceiling (D68), not a lens
count, is the runaway guard.

`Depth.limit` is now `int | None`: triage keeps its critical-tier cap
(its depth mode), review and comprehensive are uncapped, and
`plan_lenses` treats None as uncapped — the one-shot 60,000-character
body budget decides what a one-shot review inlines, and the agentic path
stays bounded by D68's derived limits. `MAX_LENSES` and
`COMPREHENSIVE_LIMIT` are gone. The picker's instructions now carry the
guideline's breadth as a default, name the auto-includes explicitly
(decision-lifecycle on a decision-record or decisions-log change,
documentation-health on a docs-only change, module-design and naming on
a rename), and say there is no fixed cap. Hygiene spends no slot: twelve
named picks plus a verification-stating body yield all twelve picks plus
hygiene, every one running.

The reviewed repo's merge-base `REVIEW.md` — the same tree the D68
ceiling line is read from — may carry `review_lens_include:` and
`review_lens_exclude:` lines (comma-separated lens names). The
controller applies the override to the picks itself: an exclude drops a
ranked pick, an include runs even when the picker fell back or made no
call, triage is never widened, and the critical tier — the controller's
own floor, not the guideline's — is untouched either way. The selection
note records the override and the draft carries it; an unusable line
fails open with a note, the way the ceiling's unusable line does, and a
name matching no bundle lens surfaces as its own NOT RUN line rather
than being guessed away. The auto-includes stay model-applied per the
guideline: the slice removes what forced their drops, and the parity
gate's missing-lens failure stays scoped to a leftover cap or a
hygiene-spent slot. `agentic-review` reads the preference (it fetches
the merge-base tree); the one-shot `review` command runs on the
guideline alone, recorded in D69 rather than given a second preference
source. Mutants applied by hand and killed: the cap of 8 back at review
depth and on the agentic plan, the `max_lenses` default back at 8, the
exclude ignored, the includes silently dropped, the exclude reaching the
critical tier, includes applied at triage, a numeric cap back in the
instructions, the lens-name validation dropped, and the unusable-line
note dropped from the draft. Offline only.

## 2026-11-16 (same day) — round-1 fixes for #729: hygiene is excludable and undeletable no more, exclude wins everywhere, and the controller states its shape facts

Round 1 verified the D69 implementation (mutants M4 and M9 re-run and
confirmed killed) and returned one Major: `_apply_preferences` did not
know the D58 controller-added hygiene choice `_with_critical` inserts
after it, so `review_lens_include: reviewing-pr-and-process-hygiene` with
a verification-stating body ran hygiene twice — the body inlined twice
one-shot, two conversations and a doubled reservation agentic — and
`review_lens_exclude:` naming hygiene silently did nothing. The hygiene
choices now reach `_apply_preferences`, join the covered set, and an
exclude naming hygiene removes the controller-added lens (hygiene is
neither critical-tier nor a cap, so the repo may decline it), recorded in
the note; `plan_lenses` refuses a repeated name structurally ("already
chosen earlier in this plan"), so no path can plan a lens twice, and a
loop test holds the selection duplicate-free across the
hygiene/preference/fallback combinations. Exclude wins over include on
every path — the fallback applies the exclude filter too. Cheap
hardening, not a redesign: the controller computes the auto-include
shapes from the changed paths it already holds (`guideline_shapes`: a
decision record or the decisions log touched, an all-documentation diff
with at least one non-record path, a git rename record), states them in
the picker's instructions and the draft's selection note with every path
quoted as data, and adds no lens itself — stated, not enforced; the
recorded owner decision that the model applies the auto-includes stands.
The instructions' enumeration no longer claims completeness ("its
auto-includes include"), names the decision route's second lens, and
attributes the rename pair to the restructuring route where the
guideline carries it. A preference that changes nothing is now still
recorded ("nothing needed changing"), and the fallback note no longer
says "only the critical tier" once the preference changed the set.
`LensPreferences.source` is dropped. Killed there, by hand: the
covered-set mutant omitting hygiene, the structural dedupe removed, the
fallback exclude filter removed, the nothing-changed record suppressed,
and the "only" reword removed. Overlap noted in the PR body: #652's
`test_lenses.py` imports `_NAME`, which this PR renamed to `LENS_NAME`;
whoever merges second updates the import. Offline only.

## 2026-11-16 (same day) — round-2 fixes for #729: the doc claims stated as they are, and the fallback's hygiene drop recorded once

Round 2 verified all eight round-1 fixes fixed — its reviewer re-ran all
seven claimed mutants by hand and confirmed each killed — and returned
two Minors and four Nits, all fixed: the `_pick_lenses` #624 comment now
states its current truth (the branch's `select_lenses` call never reads
`scrub`; `guideline_shapes` does, before the branch, and only through
the note); the stray 4-space indent in `review_wide.py`'s module
docstring is gone; a fallback's hygiene exclude is recorded once, as the
controller-added drop, never also mislabeled as a dropped pick
(`test_a_fallback_hygiene_exclude_is_recorded_once`; the
revert-to-dropped-pick mutant dies on it); the rename sentences in the
instructions and in the shape facts are marked "among others" — the
same partial-list pattern swept from `_BREADTH` into `guideline_shapes`
per the standing authoring rules — pinned by both rename tests (the
qualifier-removal mutant dies on the instructions test); the
`_DECISION_DIRS` comment no longer claims coverage it does not have (a
root-level log under another name matches no heuristic, and a missed
shape costs one sentence, as the function's docstring already says); and
the D69 Update gained a write-once Correction splitting the
killed-mutant attribution: the covered-set mutant kills only the
include-duplicate test, while the exclude tests die to the separate
`hygiene_dropped` mutant. One process slip, caught and recovered: the
mutant revert's `git checkout` wiped the still-uncommitted N3/N4/N5
edits, which the full-suite run caught as three failures; the edits were
re-applied, committed, and only then were the two mutants applied
against the commit and killed. 3,040 reviewer tests at 96.68% coverage.
Offline only.

## 2026-11-16 (same day) — #726: a reused settled lens re-assesses on newer CI evidence or comments (D73)

D73's follow-up, implemented as `atlas_reviewer/reassess.py` and the
pieces it wires. The reuse key is unchanged — a lens settled for this
head and body is still reused without a runner — but the reuse path now
compares the evidence snapshot this review gathered against a digest
stored with the settled result (`AttemptLedger.finish`'s new
`evidence_digest`, read back by `AttemptLedger.evidence_digest`), over
the gathered head-SHA CI items and the PR's remarks with each item's
fetch time excluded, plus the gathers' omissions, failures and notes so a
listing that now fails or now succeeds moves the digest too. A digest
that moved — or a result settled before the digest was ever stored —
earns one bounded re-assessment call: no tools (the head is unchanged, so
the cited code is the code that is there), no repair turn, reserved at
its worst case against the review's shared `Spend` (D68's derived limits
and dollar ceiling; D69's no-lens-cap stands), settled like any turn. The
turn carries the prior findings labeled `P1`, `P2`, … plus the review's
own conversation and CI blocks — the digest says something changed, not
what, so the delta is the complete current picture under the same
budgets, inside the review's one fence. The reply has its own contract
shape: findings that may `revises` a prior label with a stated reason,
and `withdrawn` entries of exactly `{id, reason}` — silence keeps a prior
finding as it stands, so nothing is ever dropped silently, and the draft
lists withdrawals with their reasons and a revision's replacement id.
Every reported finding is quote-verified against the head files like an
ordinary reply's; a label naming no prior finding refuses the whole
reply. The re-assessment is recorded on the lens's `#reassess` ledger
key, never the lens key, so a garbled supplementary reply cannot turn a
clean lens partial, and the effective result is composed from the ledger
alone on every review; a failed re-assessment (unparsed, refused,
halted) stores no digest, so the next review re-earns the bounded call
instead of freezing the failure in. A settled result that never attested
earns no re-assessment — the ordinary retry policy governs it — and a
caller that passes no snapshot keeps today's reuse unchanged. The
one-shot path re-reviews every time and has no settled-result reuse to
wire; the service's GitHub permission failures keep their existing
omission handling, and a refused listing moves the digest so the
re-assessment proceeds with what is available and names the gap. The
dry-run script gained a `reassessment` scenario section (validated at
load) and the no-script dry-run model confirms by silence. Twelve
mutants applied by hand and killed, each named in the D73 Update; 3,080
reviewer tests at 96.29% coverage, tooling suite 882 passed at 95.20%,
`gate`'s ruff/mypy/drift legs clean. Offline only.

## 2026-11-16 (same day) — round-1 fixes for #731: a withdrawal annotates instead of deleting, and the re-assessment call is traced

Round 1 returned COMMENT with no Blocker — every acceptance criterion in
issue #726 confirmed met, the digest called sound, and five of the author's
twelve mutants independently re-killed — plus four fixes. M2 is the
substantive one: a withdrawal was untrusted-input-driven and directly
deleted a prior finding from the effective set, so a comment crafted to
say "P1 is wrong" could flip a Blocker review to approve. Per the brief's
option (a), `effective_outcome` now never removes a prior finding on a
withdrawal — the withdrawal is an annotation the draft's withdrawn
section shows with its reason — and a revision that would lower a
Blocker's or a Major's severity is annotation-only too, so the higher
severity still counts; the status line gained the `withdrawn` annotation
count (option (c)), and the reply instructions state the proposal
semantics. M1: the reuse branch now builds the scrubber and wraps the
model in the lens trace, so the re-assessment call records its completion
span. M3: `dropped` is composed from the settled run plus only the latest
re-assessment's notes, so one malformed severity cannot accumulate into
every later review of the head. N1–N4: the verified-only participation
rule stated, a revise-and-withdraw-same-label reply refused at `judge`,
the digest's not-covered fields (title, body, labels, commit subjects)
named in its docstring, and the latest re-assessment's `limit_hit`
carried onto the composed outcome so the status line names it. Seven new
mutants applied by hand and killed, each attributed in the D73 Update's
round-1 paragraph. #730's `cli.py` hunks are disjoint; latest main merged
first. 3,100 reviewer tests, tooling 882 passed at 95.20%,
ruff/mypy/drift clean. Offline only.

## 2026-11-16 (same day) — round-2 fixes for #731: the routine's Major — the re-assessment quote check saw changed files only

The round-1 review's verdict held at COMMENT solely on the routine's open
Major, reproduced live: a verified prior finding can cite an unchanged
file (the ordinary run's lens read it there), and the re-assessment's
quote check — built from the changed files' sources plus an empty
head-reads set — could not verify that same quote, so a revision replaced
a verified finding with an unverified copy and the finding vanished from
the reported set. Both of the routine's suggested shapes shipped:
`judge` now takes the head tree and quote-checks against the head lines
of every path the reply's and the prior findings' locations cite, so the
requested test (P1 cites `docs/notes.md:1`, revised with its quote
unchanged) verifies and keeps counting toward the verdict; and
`effective_outcome` keeps the prior whenever its replacement does not
verify, showing the failed revision as an annotation with the quote
check's reason. The carried routine Minor ships with it: the
re-assessment attempt is started on the ledger before its first model
call, and a failure beyond the recorded causes is finished as the
MODEL_ERROR attempt it is — an exception in the re-assessment no longer
fails the whole review, the prior findings stand, and a death mid-call
(a BaseException the guard correctly does not catch) leaves the started
attempt reading back as ABANDONED. The three Nits: a revision's `reason`
capped at `MAX_TEXT_CHARS` like a withdrawal's; `_note` counting only
resolved references with annotation-only revisions counted as
`annotated`, separate from `revised`; the N2 test on pytest's `tmp_path`
instead of a leaked `mkdtemp`; and the abandoned-latest-attempt dropped
note documented. Six mutants applied by hand and killed, each attributed
in the D73 Update's round-2 paragraph. 3,105 reviewer tests, tooling 882
passed at 95.20%, ruff/mypy/drift clean. Offline only.

## 2026-11-17 — #728: the service's round log is now one file per pull request, so prior-round context survives a pushed head

The deployed agentic review lost its round log on every push:
`_cmd_agentic_review` hardcoded the log at `<state dir>/rounds.jsonl`
and the service passes `--state-dir <run dir>/state` with `run_dir`
keyed by head SHA, so round N never read round N-1 (found in #727's
round-1 protocol review, D70's correction (3); CodeRabbit raised it
too). The fix is the seam D67 deferred: `agentic-review` takes
`--round-log`, and `service_run.review_argv` — now required to take the
event — appends the per-PR path `<state root>/rounds/<repo>-<pr>.jsonl`
to the agentic child only. The unflagged CLI default is unchanged, so a
local run keeps its path; `rounds.py` itself is untouched, and the
contents stay untrusted fenced data under D67's budgets. Storage
(D74): `/data/rounds/<repo>-<pr>.jsonl` on the existing Fly volume,
outside the per-head run directory the job's end removes, no janitor in
this slice — the log stays until a later cleanup slice; the queue's
one-active-job-per-PR rule is the single-writer story, and the reader's
existing semantics absorb the supersede teardown's overlap window (a
torn line charges nobody, a garbled line that names the PR is its
omission, an unreadable file is the `round log file` omission). One
decision made against the issue's wording, recorded in D74: a missing
log is a first review's normal shape — no omission, because D42 holds a
review with an omission at COMMENT and every first review would land
there — while a corrupt log stays the named omission it already was.
Three mutants applied by hand and killed: the service omitting the
flag, the per-PR path keyed by head, and the CLI ignoring the flag;
each dies on its named test, and the two-heads-of-one-PR dry run shows
the second head's first turn opening with the first round's fenced
block. 3,109 reviewer tests passed at 96.37% coverage, ruff/mypy clean
on the touched files. Offline only.

## 2026-11-17 (same day) — round-1 fixes for #732: the per-PR log's omissions no longer outlive the head that caused them

The round-1 protocol review (COMMENT) confirmed the routine's Major,
which this PR's own design had introduced: under D67's per-head logs a
garbled round-log line died with its run directory, but under the
per-PR file it held every later review of the pull request at COMMENT
forever — a `ROUND_VERSION` bump or a rollback turned every existing
line into an `unreadable record`, an undecodable file never healed
because `append` reopens the same path, and a teardown-window garble
was the same standing omission. Two fixes. The `unreadable record`
charge is head-scoped in `prior_blocks`, mirroring how it already
scoped the budget omission: a line that names the PR but is not a
current record carries the head it claims (`UnreadableLine`, extracted
by `_owner`), and only a line sitting at the head under review blocks
— at an older head it is set-aside superseded data, and a line with no
readable head charges nobody (it cannot be proven to hide current-head
context). `RoundLog.read` now quarantines a file it cannot decode:
`os.replace` moves it aside under a `.corrupt-<UTC stamp>-<ns>` name,
the review that saw it reports the `round log file` omission once with
the quarantine path named, and the next review starts fresh; a parent
the process cannot reach stays the operator's case, now documented in
`deploy-service.md` along with the persistence truth the first wording
understated (a charged line holds every later review until the log is
repaired, not just the next draft). The Nits: `round_log_path`
casefolds the repository so a case-only rename keeps the log (N1); the
corrupt-log test's docstring now names causes that can actually
produce such bytes — this reader's own appends are ASCII, so a torn
write is `unattributed`, never `file_unreadable` (N2); and
`RoundLog`'s stale "nothing in the service builds one yet" docstring
names both paths now (N3). Four mutants applied by hand and killed:
charge-any-named-line, set-aside-everything, no-quarantine, and the
reverted casefold, each on its named test; the coordinator pin that a
head-less bad line blocks the PR it names was re-pinned to the new
rule. 3,119 reviewer tests, ruff/mypy clean, drift clean. Offline
only.

## 2026-11-17 (same day) — round-2 fixes for #732: quarantine narrowed to decode failures, and the permission tests made root-independent

The round-2 protocol review returned APPROVE with three cleanups. The
quarantine no longer fires on every `OSError`: `RoundLog.read` moves a
file aside only when its bytes cannot be decoded (`UnicodeError`) — a
permission refusal, an unreachable parent, or a directory at the log's
path renames nothing, keeps the file where it is, and stays the named
omission and the operator's repair, so a transient read failure can
never rename a healthy log out from under the path (killed by hand:
the quarantine-on-any-OSError mutant fails on
`test_a_directory_at_the_log_path_stays_put_and_stays_unreadable`,
`test_a_permission_refusal_does_not_quarantine_and_the_file_stays_put`
and `test_an_unreachable_log_does_not_quarantine_and_stays_put`). The
two round-1 permission-based tests leaned on `chmod(0)`, which a root
runner ignores; they are now root-independent fakes that raise the
error for the target path only, the fragile `finally` restore is gone
with them, and the four quarantine tests were verified passing under
`sudo` as well as the normal user. Nit: the round-1 entry's test count
said 3,116 where the suite has 3,119 — corrected here in this
branch's own unmerged entry. `deploy-service.md`'s recovery paragraph
and `rounds.py`'s docstrings now state the narrowed rule. 3,119
reviewer tests at 96.39% coverage, ruff/format/mypy/drift clean.
Offline only.

## 2026-11-17 — the reviewer image carries every file the controller reads at review time (v6's synthesis.md crash)

atlas-reviewer-service v6, the image built from main `d5a2a93f`, failed its
first live review (of PR #732) on 2026-11-16 with
`FileNotFoundError: '/opt/atlas/collapsed/skills/reviewing-a-change/reference/synthesis.md'`
from `pathlib.Path.read_text` in the review subprocess, exit 1. Root cause:
packaging, not generation. `finding_contract()` reads `lens_loop.SYNTHESIS`
(added 2026-11-12 in 4057c636) and `coordinator.py` calls it with no path
when a lens run starts, but the Dockerfile — written 2026-11-10 in 81a279d3,
before that read landed — copied only the change bundle's `SKILL.md`, its
`reference/lenses` directory, and the picker's `SKILL.md`. CI stayed green
because `test_fly_deploy.py::test_image_copies_exactly_the_files_the_controller_reads`
snapshotted the Dockerfile's COPY source list and checked that those files
exist in the checkout, so a new runtime read never touched it; the lens-loop
tests read `SYNTHESIS` against the full checkout, where the file exists, and
nothing in CI builds the image. The same allow-list class also silently
weakened reviews: `LensLibrary.body()` falls back to the other collapsed
entrypoints' lens bodies when the picker names a lens the change bundle does
not ship, and none of those trees was copied, so an audit, decision, or
artifact lens in the image was NOT RUN ("no lens body in the bundle") instead
of crashing. The fix copies the whole committed `collapsed/skills` tree (plus
the unchanged picker `SKILL.md` copy) so the image holds every file the
controller reads at the same path the code resolves — no per-file exception
next to the lenses copy to drift out of sync again — and replaces the
snapshot test with `test_image_carries_every_file_the_controller_reads`,
which derives the required set from the modules that read
(`harness.DEFAULT_BUNDLE`, `lens_loop.SYNTHESIS`, `picker.PICKER_PATH`, and
every collapsed entrypoint's `reference/lenses/*/body.md`) and requires each
file to land at `/opt/atlas/<repo path>` via a COPY whose source is the file
or a parent directory; a companion test checks no `.dockerignore` rule hides
one. The derived test fails on the pre-fix tree (synthesis.md plus all three
fallback entrypoints' lens bodies uncovered), and kills a mutant that copies
the tree to the wrong destination. `tool-evidence.md` rides along in the tree
copy but is not a runtime read. 3,106 reviewer tests, ruff/mypy clean.
Offline only. After merge, a Fly redeploy of atlas-reviewer-service is needed
to pick this up; not deployed from here.

## 2026-11-17 (same day) — round-1 fixes for #733: the dockerignore guard failed open on interior `**`, and the eval references left the derivation

The round-1 review's Major: the new `.dockerignore` guard's `str.replace`
translation chain destroyed its own `**` semantics — the `.*` emitted for
`**` was rewritten by the later `*` pass into `.[^/]*`, which cannot cross a
`/` — so the most natural rule for the v6 crash file
(`collapsed/**/synthesis.md`, mutant M6) hid it from Docker while the guard
stayed green, and a middle-directory rule (`**/reference`) was unreachable
too because the leading-`**/` candidates only ran from each segment to the
path's end. The guard now translates each rule token by token (`**/` → zero
or more whole segments at any depth, `**` → crossing, `*`/`?` within one
segment, character classes member-for-member, literals `re.escape`d) and
walks the file's path node by node the way docker build walks the context:
the last matching rule decides each node, and a directory the walk leaves
excluded prunes its subtree, which is what makes the committed
`atlas_reviewer/fixtures/*` + two `!` re-include rules behave as Docker
behaves — and a `!` cannot resurrect a file whose parent directory the walk
pruned. Nineteen single-rule and four multi-rule parametrized cases pin the
semantics (M6, `**/reference`, `a/**/b` at zero and deep segments, `.git`
vs `xgit`, root-anchored `*.md`, `**/*.py[cod]`, the committed negation
triple, and the caveat cases). The Minor: the deleted snapshot had been the
only guard on the non-skill COPY lines, so dropping
`atlas_reviewer/fixtures/eval-references` (the `eval` subcommand's
reference set, read by `eval_harness._REFERENCES`) or the whole
`atlas_reviewer/*.py` package COPY left every test green (mutant M7). Both
are now in the derived set — the `pr-*.json` fixtures and the top-level
package modules — so each drop fails
`test_image_carries_every_file_the_controller_reads`, and the glob COPY's
`*` is matched with the same within-segment semantics. The Nits shipped
with them: the PR body's count corrected to 33 files (1 synthesis + 32
fallback lens bodies), the Dockerfile comment narrowed to the
collapsed/skills tree, and the `!` walk semantics documented in the guard's
docstring. Mutants M6, `**/reference`, M7, and the package-COPY drop each
kill exactly one test. 3,129 reviewer tests, ruff/mypy clean. Offline only.

## 2026-11-17 (same day) — round-2 fixes for #733: the dockerignore guard fails closed on what it cannot model, and the `!`-rescue claim corrected to BuildKit

Correction first: the round-1 entry's "a `!` cannot resurrect a file whose
parent directory the walk pruned" states classic-builder behavior as
Docker's. Modern Docker (BuildKit's fsutil walk) descends into an excluded
directory when an exception's literal reaches below it, so under rules
`dir` + `!dir/file.md` the file ships — also under `!dir/sub/x.md` and a
wildcarded child exception, though a bare trailing-`**` exception still
prunes. The guard keeps the classic walk, so that case is its known
strictness gap: it can report a file hidden where BuildKit would ship it,
never the reverse — the test now says "at least what docker would", the
case is annotated as the gap, and the agreeing shapes are pinned.

The Major: the round-1 translator still had three fail-open divergences
from moby/patternmatcher, each a future rule that hides a file in Docker
while the guard stays green — no `filepath.Clean` preprocessing
(`collapsed//skills` and `./collapsed` forms compile to regexes that can
never match a real path), no backslash-escape handling
(`synthesis\.md`), and `[!` read as a negated class where Go reads `!` as
an ordinary member. Rather than chase full Docker emulation, the guard
now fails closed: every rule is Cleaned Go-faithfully (empty segments
collapse, `.` drops, `..` resolves; leading and trailing `/` dropped,
which only over-reports), and a rule carrying a backslash escape or a
`[!` class raises "unsupported .dockerignore syntax; extend the guard"
instead of being mis-translated — the two constructs whose faithful
behavior is ambiguous or easy to get wrong, while the plain and `[^`-
negated classes the committed `.dockerignore` uses stay modeled. Mutants
`collapsed//skills`, `collapsed/**/synthesis\.md`, and `[!n]ollapsed/
skills` appended to `.dockerignore` each now fail
`test_no_dockerignore_rule_hides_a_runtime_read`; Clean-equivalence and
refusal cases are pinned parametrized. 3,139 reviewer tests, ruff/mypy
clean. Offline only.

## 2026-11-17 (same day) — round-3 fixes for #733: the guard refuses POSIX bracket classes, and Clean keeps a leading `/` like Go

Two more fail-open classes in the `.dockerignore` guard, both closed the
round-2 way — refuse or mirror, never mis-translate:

- POSIX bracket classes: `_class_end` closed a class at the first `]`, so
  `[[:alpha:]]` compiled as the Python members set `{[, :, a, l, p, h}` plus
  a literal `]`, while Go passes `[` and `]` raw into RE2, where
  `[[:alpha:]]` is any letter — the mutant `[[:alpha:]]ollapsed/**` hid the
  whole `collapsed/` tree in Docker while every dockerignore test stayed
  green. `_unsupported_syntax` now scans rule-by-rule and refuses `[[:`
  (RE2 compiles it; Python re does not), a `[` nested inside a class, a `[!`
  class, and a backslash escape, all with the same "unsupported
  .dockerignore syntax; extend the guard" error; plain `[...]`/`[^...]`
  classes stay modeled (the committed `**/*.py[cod]` needs one).
- `_clean` dropped a leading `/`, which Go's Clean keeps — and the kept
  slash compiles to a `^/...$` regex that never matches a relative context
  path, so a leading-slash rule is inert in Docker in BOTH directions. For
  an exclude rule the drop only over-reported; for a `!` exception
  (`!/collapsed/skills` against a preceding exclude) it re-included a file
  Docker hides — fail-open. `_clean` now keeps the slash (and drops a `..`
  that would climb above the root, as Go does), so the model is inert
  exactly where Docker is. The mutant kill is the parametrized pair
  `["collapsed/skills", "!/collapsed/skills"]` (a lone appended
  `!/collapsed/skills` is inert in both engines, since no committed rule
  excludes the tree); the review's three fuzz shapes (`["[^a]", "!//?"]`,
  `["y", "!/?"]`, `["**//", "c*", "!/**/**/y/"]`) are pinned too, and the
  two docstrings no longer claim the dropped slash only over-reported.

Cleaning the raw rule before reading `!` also exposed a third divergence
the fuzz found on its own: Go's Clean resolves `..` against the segment
carrying the `!`, so `![a]/../y` Cleans to the exclude rule `y` — the
negation vanishes — while strip-first ordering made the model see an
exception. The guard now Cleans first and reads `!` off the cleaned rule,
as `patternmatcher.New` does. Verified against a fresh transcription of
`moby/patternmatcher` and BuildKit's fsutil walk (seed 11): 19,533
comparable cases, 0 fail-opens, 878 fail-closed over-reports, and 0
divergences across the committed `.dockerignore` × all 158 runtime reads.
The COPY glob sources now pass the same refusal gate (`image_path_of`
raises on `\`, `[!`, `[[:`, nested-`[`), closing the round-3 Nit. 3,167
reviewer tests at 96.37%, ruff/format/mypy clean. Offline only.

## 2026-11-17 (same day) — round-4 fixes for #733: the guard reads `.dockerignore` through ignorefile.ReadAll, as BuildKit does

Correction first: the round-3 entry's leading-slash semantics were built on
the round-3 review's wrong ground truth, which that review has since
retracted. BuildKit does not feed `.dockerignore` lines to
`patternmatcher.New` directly — `frontend/dockerui` reads them through
`moby/patternmatcher/ignorefile.ReadAll`, whose contract is: skip lines whose
first raw character is `#` and blanks, trim, read `!` from the first raw
character first (and re-trim the remainder), `filepath.Clean` the remainder,
strip one leading `/` when more than one character remains — "/some/path and
some/path are considered equivalent" — and re-attach the `!`. So
`/collapsed`, `//collapsed`, `/../collapsed`, and `/x/../../collapsed` are
all live excludes of `collapsed`, `!/collapsed/skills` is a live re-include,
and `![a]/../y` normalizes to `!y` — the negation is never eaten by ReadAll.
The guard's normalization is now one function transcribing exactly that
(cited to moby/patternmatcher v0.6.1 in its docstring), and the four
appended-slash mutants each fail `test_no_dockerignore_rule_hides_a_
runtime_read`; the leading-slash and rescue parametrized cases were re-pinned
to the corrected outcomes and the docstrings no longer claim the slash is
inert.

The re-verification ran against the real matcher, not a transcription: the
fuzz corpus (5 seeds, 74,916 generated cases, 73,191 comparable after
refusals) was scored by a Go program calling `ignorefile.ReadAll` +
`patternmatcher.MatchesOrParentMatches` — fail-opens 0, over-reports 29 (the
guard's documented strictness: the unmodeled exception descent and the wider
mid-segment `**`), committed `.dockerignore` × 158 runtime reads: 0
divergences. The real-matcher fuzz then surfaced one more quirk the
transcriptions had all missed: `patternmatcher.New` cleans the ReadAll
output — `!` attached — before reading `!`, and that second Clean can eat
the negation (`!../../*` cleans to the exclude-everything rule `*`, because
the `..` pops the `!..` segment), so the guard now applies New's Clean after
ReadAll's, and the fuzz's own fail-open cases are pinned parametrized. The
round-3 refusals (`\`, `[!`, `[[:`, nested `[`) and the COPY-source refusal
gate are unchanged. 3,175 reviewer tests at 96.37%, ruff/format/mypy clean.
Offline only.

## 2026-11-17 (same day) — #738: the service-posted review now carries the draft's verified findings

The service's posted COMMENT review never contained a finding: `ReviewReport`
had no findings field, both report builders read the draft's lens, coverage,
limit and cost sections but skipped `## Findings (verified quotes only)`, and
`render_comment` posted the banner, the recommendation, the lenses, files,
limit stops and cost — the shape the post has had since a3219f9b. On #654 at
badc60e5 the live service posted a review with no findings while its round log
held seven verified findings (five Minor, two Nit).

The fix is one field and one section: `ReviewReport` gains `findings`
(default `()`, so every existing caller is unchanged), filled by a single
`_findings(draft)` helper both builders call — the Findings section's bullets
verbatim, each the whole
finding line (minted id, severity tags, location, lens, text, fix), so
severity and location survive with no second rendering path (the
`No verified findings.` line is prose, not a bullet, and yields none) — and
`render_comment` renders **Findings** right after the recommended-event line,
ahead of lenses and cost, so the 65,000-character cut cannot eat the findings
first. Each item goes through the section's existing `quote_untrusted`, the
unverified findings section stays unposted, and posts stay COMMENT-only. The
one-shot draft has no findings section and posts `None.`.

Tests: a real `render_draft` agentic draft with two verified findings yields
both in order with severity and location (`test_an_agentic_draft_with_
findings_carries_them_into_the_report`); the posted body carries each finding
and keeps them under a cut to the post limit
(`test_the_findings_reach_the_post_quoted_with_the_recommended_line`); markup
in a finding cannot break out of the quoting
(`test_a_hostile_finding_cannot_break_out_of_the_quoting`); no findings posts
`None.` (`test_a_report_without_findings_posts_none`). Mutants applied by
hand and killed: `_findings` always empty (M1), the section after the cost
lines (M3), the section dropped from the post (M5), the findings posted raw
outside their inert code spans (M4) — the `No verified findings.` prose line
is not a bullet, so the empty draft yields none without a placeholder filter. The posted
body is now documented with findings in `atlas_reviewer/README.md` and
`atlas_reviewer/deploy-service.md`; the body-contract amendment is recorded
as D75.

## 2026-11-17 (same day) — #739 round-1 fixes: the posted findings are the controller's own rendering, not a re-quote of it

Both round-1 reviews (the protocol review and the routine review, each
COMMENT) caught the same Major in the round-0 shape: the Findings section
re-quoted every finding line through `quote_untrusted`'s 200-character
default, so the controller's 600- and 1,200-character minted fields were cut
mid-line — a realistic 448-character finding posted as 225 characters and
lost its `Fix:` and `Evidence:` — and each line's inner code spans were
double-escaped inside the outer one (backticks as `\u0060`, quotes as
`\"`). D75's Cost paragraph had claimed the only loss mechanism was the
65,000-character cut; that was wrong on both counts, and the update
paragraph appended there names them.

The fix removes the second quoting layer instead of enlarging it: a finding
bullet is controller-assembled text — every model-authored field in it is
already one inert code span the controller's own `quote_untrusted` escaped
at draft time, and the scaffolding (minted id, severity tags, lens name,
the `Fix:`/`Evidence:` labels) is controller text — so
`_findings_section` posts each bullet as the controller rendered it,
scrubbed and uncapped. The inner spans stay readable, nothing is cut at
200, and the only bound is the 65,000-character cut the section's position
already survives. Every other section keeps the 200-character default,
now pinned by a test on a 300-character limit stop.

The Minor was real too: the round-0 post-side tests were a 135-character
hand-written fixture and a real-draft test that never rendered the post,
and a mutant raising the quote default to 100,000 survived all 84 of them.
The new round-trip test goes from a real `render_draft` draft with a
400-plus-character finding through `summarize_draft` and `render_comment`,
asserting `Fix:` and `Evidence:` survive, the inner spans render as spans,
and no truncation marker appears. Mutants applied by hand and killed, each
with bytecode caching disabled after a same-size mutant restore was found
serving a stale `__pycache__` (the round-0 battery's restores were
same-size writes in the same mtime second, which briefly made a killed
mutant look alive): the findings re-quoted at 200 (M6), the quote default
raised to 100,000 (M7), the findings scrub dropped (M8), and the round-0
kills M1, M3 and M5 re-applied against the new structure. The hostile
round-trip test re-checks the r1 list on the new path — HTML comment,
injected backtick, mention, fake heading, RTL override, and the
APPROVE/REQUEST_CHANGES words each stay span-bound and escaped, and the
recommendation line is unchanged. The CRLF-heading and wrapped-bullet
hardening is noted as unreachable in `_findings`'s docstring rather than
added, and the round-0 entry's "minus the placeholder" wording is
corrected in place (this branch's own, unmerged entry). 3,182 reviewer
tests at 96.38%, 882 tooling at 95.20%, ruff/format/mypy/drift clean.
Offline only.

## 2026-11-17 (same day) — #739 round-2 fixes: the section anchor, the siblings pin, and a cut that lands on a finding boundary

Round 2 APPROVEs from both reviewers, with one shared Minor and two Nits.

The Minor was in the extraction, not the rendering: `section` matched its
heading anywhere in the draft and took the first occurrence, so posting the
finding bullets raw was safe only because nothing before the real heading
could carry the literal `## Findings (verified quotes only)` line — true,
but pinned by nothing. The class fix went into `section` itself for every
section: the match is anchored to a whole heading line and takes the last
occurrence, which is always the real section (the controller writes each
section once, in order), and a pre-section field rendered unquoted — the
selection note, a lens note — that quotes a heading line can no longer
steal the extraction. A quoted field can never carry a whole line
(`quote_untrusted` collapses whitespace), so the doubled-heading shape
needs unquoted prose; the test injects it through a real `render_draft`
selection note and asserts the post takes only the real section.

Nit 1: the minted `siblings` field's `quote_untrusted` had no test — a
mutant dropping it survived all 86. The new assertion pins the escaped span
form of a siblings string carrying a backtick, an HTML comment and a
mention.

Nit 2: the hard cut could land inside a finding's inner code span and leave
an unclosed backtick run. `render_comment` now drops whole findings from
the end (the draft lists findings most severe first) until what remains
fits, and the Findings section names the drops — `[1 of 3 findings cut to
fit the post limit]` after the kept bullets, `[all N findings cut to fit
the post limit]` when every finding was dropped, never a false none — while
a body that still overflows with nothing left to drop ends in the plain
hard cut that predates findings. Mutants applied by hand and killed, all
with `PYTHONDONTWRITEBYTECODE=1` per the round-1 stale-`__pycache__` lesson:
the unanchored first-occurrence `section` (M9), the siblings quoting
dropped (M10), the cut reverted to the hard cut (M11), the all-dropped note
reverted to a bare none (M12), and the partial-drop note removed (M13).
3,185 reviewer tests at 96.41%, 882 tooling at 95.20%,
ruff/format/mypy/drift clean. Offline only.

## 2026-11-17 (same day) — #739 round-3 fixes: the label echo reprd at the source, the anchor and the fallback cut pinned

The branch rebased onto main (36842631, carrying #654's merge) first; the
rebase was clean and the frozen-decision-entry test passes against it, so
the docs logs' appends needed no conflict resolution.

The Minor was the r2 anchor's own hazard, closed at its source: the
re-assessment judge interpolated the model-authored `revises` label raw
into its refusal message, which becomes `outcome.detail`, which
`retry_reasons` echoes and the lens line joins raw into the coverage
section — a section that comes after Findings, where the r2
last-occurrence `section()` would favor a later forgery; a label of 32
characters or fewer could carry `## Context omissions` plus a bullet,
putting fake limit stops into the post. The judge now reprs the label, as
the withdrawn path already does. Pinned three ways: at the judge (the
message carries no raw newline), end to end from the real refusal through
the draft to the post (exactly one real `## Context omissions` heading in
the draft, the section reader takes it, no fake stop or forged heading in
the post), and cap-independently — a 33-to-64-character label carrying the
Findings heading is refused at parse by the length message alone, which
never echoes the label, so no label length can forge a heading through any
refusal path; the mutant raising `PRIOR_LABEL_CHARS` from 32 to 64, which
had survived everything, dies on that test.

The nits: the r2 whole-line anchor itself is pinned — a post-findings line
that merely ends with the heading's literal text (the unquoted ceiling
note) is not a heading, and the unanchored-rfind mutant dies there; and the
hard-cut fallback now lands on a line boundary rather than mid-line — every
rendered item is one line of whole code spans, so the line the plain cut
would have split is dropped whole, and the mid-line-cut mutant dies on the
last kept line's integrity. Mutants applied by hand and killed with
`PYTHONDONTWRITEBYTECODE=1`: M14 (raw interpolation), M15 (the cap raised),
M16 (the anchor dropped), M17 (the mid-line fallback). One measured pair
each on the rebased head: 3,202 reviewer tests at 96.43%, 882 tooling at
95.20%; ruff/format/mypy/drift clean. Offline only.

## 2026-11-17 (same day) — #692: a later clean run of a lens supersedes its earlier NOT RUN for coverage

Found in the Nov 14 model-trials rerun (Haiku #640): `sweeping-for-security`
was NOT RUN after a Sprites 502, its continuation ran it to clean as entry
L13, and the original NOT RUN entry (L2) stayed in `lenses` — so
`_lens_gap`'s per-entry check read a standing gap out of an entry the lens
had already made good, `coverage_complete` stayed false, the draft opened
with REVIEW INCOMPLETE, the event was held at COMMENT, and the service post
listed a lens under "Lenses not run" that had in fact run.

The fix is in the shared coverage computation (`coordinator._lens_gap`), so
every consumer agrees: a lens blocks coverage only when none of its own
entries is clean. Supersession is by presence, not position — a later clean
run supersedes an earlier NOT RUN, and a later NOT RUN does not undo an
earlier clean run — with D42's per-file gate and the runner gate unchanged
(a failed runner is still not approved away). Findings are untouched:
D61/D73's keep-findings rules are coverage-independent, and minting still
walks every attested entry. The record is not rewritten — the status line's
per-entry counts keep the `not_run` count — and the draft marks the
superseded entry with a controller note (`recovered by L<n>'s clean run`)
appended last, outside the quoted reason; the service parser reads the
marker off the line's end, so a quoted reason carrying the same words can
never forge a recovery, and carries the whole ledger line among the limit
stops so the posted COMMENT keeps the failure. Recorded as D76 in
`docs/open-questions.md`.

Tests pin both directions of the ordering semantics, the lens-identity
isolation, the surviving failure record in the draft and in the post, and
the unsuperseded NOT RUN still blocking. Mutants applied by hand and
killed: M1 (the supersede check dropped, back to per-entry `any`), M2 (the
grouping collapsed to one bucket — lens identity ignored), M3 (the
recovered note dropped from the draft), M4 (the service's recovered branch
dropped), M5 (last-entry-decides ordering). 3,225 reviewer tests at 96.40%,
882 tooling at 95.20%; ruff/format/mypy/drift clean. Offline only.

## 2026-11-17 (same day) — #744 round-1 fixes: the scoped path's carve-out hole closed, the `$` anchor pinned, the cross-references added

The round-1 protocol review, Brandon's routine review and the
atlas-reviewer-service review all returned COMMENT on the same Major, and
the protocol review reproduced it before fixing: the scoped path implemented
"none of its entries blocks" through `_blocks_coverage`, whose unread-only
carve-out (PARTIAL, attested, `FILES_UNREAD` only) returns False for a
partial that merely left a file unread — so such a partial excused a sibling
that failed for a real cause. The repro (an unread-only partial plus a
continuation that read every file and then failed `QUOTES_FAILED`) reached
`coverage_complete` with no clean entry at all: APPROVE on the branch,
COMMENT on origin/main, with the headline printing "Every selected lens ran
whole, attested, with every quote verified" over a lens that never had a
clean run. Exactly the parity failure the fix was meant to prevent,
introduced by the fix's own first cut.

The fix takes the stated rule literally: one per-lens predicate
(`_uncovered_lens` — at least one clean entry, presence not position, per
lens) now drives both the scoped and the no-scope paths, retiring
`_blocks_coverage` and its two-definition divergence (the module-design note
folded into the Major). The unread-only partial's files still gate through
`_unread_paths` exactly as before, so nothing about D42's per-file gate
moves; a lone unread-only partial stays incomplete, now charged to the state
rule as well. Pinned by the reviewer's repro
(`test_an_unread_only_partial_does_not_excuse_a_failed_sibling`, killing the
carve-out-restored mutant) and by a positive control
(`test_a_clean_run_still_covers_an_unread_only_partial_and_a_failure`)
guarding against over-correction; the round-0 supersede and identity pins
were re-verified against the new structure (M1′ per-entry `any`, M2 one
bucket, M5 last-entry-decides all still die).

The Minors: the `$` anchor on `_AGENTIC_RECOVERED` — load-bearing for
forgery resistance and unpinned, M6 had survived all 179 round-0 tests — is
now pinned by `test_a_quoted_reason_cannot_forge_the_recovered_marker`, a
NOT RUN lens with no clean run whose quoted reason carries the marker's
words and stays a not-run lens in the report and the post; and the vacuous
`or "complete" in report.files_note` assertion is now the exact
complete-coverage note text, so `incomplete` can no longer satisfy it. D40,
D42, D44 and D70 gained their `Update (2026-11-17, D76 ...)` cross-reference
notes, and D76 gained this correction. The module docstring's
order-dependent wording ("whose own later run settled clean") is reworded to
the presence-based rule. 3,229 reviewer tests, 882 tooling; ruff/format/
mypy/drift clean. Offline only.

## 2026-11-18 — #744 round-2 cleanups: the D76 residue superseded by name, the marker given one definition, the order-dependent wordings reworded

The round-2 protocol review returned APPROVE and confirmed all five round-1
fixes; its two Minors and two Nits are advisory, and all four are fixed
here.

Minor 1: D76's original body still described the retired `_blocks_coverage`
carve-out as live and its Reversibility note still named the retired code —
one record, two conflicting accounts. The entry is append-only
(`test_decision_updates_are_appended`), so the body stays as written and a
new note names both sentences verbatim and supersedes them, restating the
current revert path (give either check back its per-entry form; drop
`_uncovered_lens` and `_clean_runs` with them).

Minor 2: the "recovered by L<n>'s clean run" marker was a free-text
interface — an f-string in `coordinator._lens_line`, a hand-copied regex in
`service_run`. One definition now: `notes.RECOVERED_NOTE` (the template),
`notes.recovered_note(index)` (the builder the draft renders) and
`notes.RECOVERED_NOTE_PATTERN` (the service-side pattern, built from the
same template and anchored at the line's end), so the two sides cannot
drift. Pinned by `test_the_recovered_note_and_its_pattern_are_one_definition`
(the wording, the derived pattern's match, and the anchor property at the
unit level) beside the existing end-to-end round-trip and forgery tests;
the one-sided mutants — the draft appending its own literal instead of the
builder, and the service matching its own regex — die on the existing
recovered/forge tests.

Nit 1: D44's D76 update note and `deploy-service.md` reworded from "a later
run / the lens's own later runs" to the presence-based rule the code
implements. Nit 2: the forgery test's "forgeable-free" typo is now "keeps
the marker unforgeable by a quoted reason". 3,230 reviewer tests, 882
tooling; ruff/format/mypy/drift clean. Offline only.

## 2026-11-17 (same day) — #693: the bridge session budget is per lens attempt, and repeated session-limit refusals end the attempt

Found in the Nov 14 model-trials rerun: `SessionLimits.max_calls = 64` was
per runner session, and a lens's attempt 1 and its retry share that
session, so eight DeepSeek #661 retries, DeepSeek #640's
decision-lifecycle retry (16 `OVER_SESSION_LIMIT` refusals) and one
Kimi #640 retry started nearly out of tool calls and ended `TOOL_GAP`
`FILES_UNREAD`, every duplicate-call nudge earned from re-issuing refused
calls. D77 records the decision.

The budget moved to the attempt: the coordinator calls
`Bridge.begin_attempt(lens, number)` before each attempt it runs on a
bridge, the attempt's call and shown-output counters start over, and a
refusal names the attempt that spent the budget
("all 64 calls of this attempt made (lens attempt 2)"). The session
ledger (`Bridge.calls`) still keeps every call across the attempts. The
loop then cuts an attempt at `SESSION_REFUSAL_LIMIT` (3) consecutive
`OVER_SESSION_LIMIT` results, mid-turn, at a limit stop
(`limit: session_limits`, cause `TOOL_GAP`) naming the lens, the attempt
and the cap -- carried into the ledger's per-attempt `limit` record, the
status line, and the round log's new `limit_stop` field, which the next
round's first turn shows back (a pre-field line parses with an empty
stop). The dollar ceiling and the wall clocks still bound the whole
review; D42's structural rule (a diff over 1 MiB cannot come clean in one
attempt) stands; the cap is deliberately not model-aware yet, and the
attempt the threshold stops is not retried, like every other limit stop.

Tests pin a retry starting with a full budget (one loop-level and one
end-to-end, the latter also pinning the round-log record), the threshold
cut mid-turn with the stop's text, and the field's round-trip. Mutants
applied by hand and killed with `PYTHONDONTWRITEBYTECODE=1`: M1 (the
session-wide counter restored), M2 (the threshold raised out of reach),
M3 (`begin_attempt` not called by the coordinator), M4 (the attempt
number not passed to the loop). 3,224 reviewer tests at 96.40%, 882
tooling at 95.20%; ruff/format/mypy/drift clean. Offline only.

## 2026-11-17 (same day) — #745 round-1 fixes: the refusal stop delivers instead of discarding, and the decision records catch up

Round 1 (the protocol review, Brandon's routine review, and the atlas
reviewer service converging on one Major) caught the round-1 cut
throwing away an attempt's ready findings: when a tool batch straddled
the attempt budget, the mid-turn cut fired before the model saw any
refusal, so the results and the final reply both vanished into an
unretried `UNACKNOWLEDGED` outcome where the pre-#693 code ended
attested with the finding delivered.

The stop no longer ends the attempt. Once `SESSION_REFUSAL_LIMIT` (3)
`OVER_SESSION_LIMIT` results have accumulated -- cumulative, since once
either cap is spent every later call refuses, so the round-1
"consecutive" streak and its untestable reset branch are gone -- the
turn's results go back and the attempt gets a tool-less turn to finalize
with what it has: the next request carries no tool schemas, so
re-issuing refused calls is impossible, and the reply the model then
gives is judged like any final reply. The stop is built once at that
boundary and rides on the delivered outcome's `limit_hit` (a later
stop's own hit wins), so the ledger, the status line, the round log and
the service report still name the lens, the attempt and the cap; the
unread-list nudge is not earned on the finalize path (its request has no
tools to read with), and the stall detector's own nudge does not also
fire on the stop's turn. D77 now amends D39 and records the
alternatives, the accepted cost (one more reserved, clock-gated model
call; an unread-file finalize stays partial) and a revisit trigger;
D39 and D42 carry the `Update (2026-11-17, D77)` notes; the coordinator
test's call arithmetic and the session log's Kimi-retry sentence are
restored; the README's stray triple space and rewrap noise are cleaned.

The rewritten regression tests pin the reviewer's repro shape: a batch
straddling the budget ends attested with the finding delivered, the
tool-less finalize request carries no schemas, and the stop rides on the
outcome (loop-level) and reaches the status line and the round log
(coordinator-level, which also pins that the retry's 64 reads really
ran). Mutants applied by hand and killed with
`PYTHONDONTWRITEBYTECODE=1`: the round-1 four (M1 shared counter, M2
threshold raised, M3 `begin_attempt` dropped, M4 attempt number
dropped) plus the round-1 fixes' own: the finalize turn never built (the
loop and coordinator tests lose the stop and the tool-less request), the
tool-less request reverted to the full tool set, and the stop not
attached to the delivered outcome. Full local checks green; offline
only.

## 2026-11-18 — #745 round-2 fixes: the finalize turn keeps its tools, and the stop never vanishes under a later one

Round 2 caught the finalize turn's request shape: it sent an empty tools
array next to a conversation already carrying assistant tool calls and
tool results -- a shape the pinned Bedrock Converse route rejects
(tool history requires a toolConfig), so the finalize call would have
failed as a non-retryable model error and lost the findings the turn
exists to deliver, on the route every live run takes.

The tool schemas now stay on the finalize request: the model is asked to
finalize, and the spent bridge refuses whatever it still calls -- a
re-issue is a logged refusal, bounded by the turn cap, the dollar
reservation and the wall clocks, and cannot restart the stop, which
fires once per attempt. The adapter gained the shape invariant itself:
`_payload` refuses any request that carries tool history next to an
empty tools array before any request goes out (the one tool-less
request that exists, the re-assessment call's single user turn, carries
no history), so a future tool-less finalize turn cannot fail the call
mid-review. When a later stop claims the outcome the session-limit stop
once lost -- the turn cap landing on the finalize boundary -- its
message is now kept in the outcome's detail. The unread-list nudge is
still not earned on the finalize path: the stop asked for a reply, not
more reads the bridge will refuse.

D77 and the README now describe the tools-kept design and record the
tool-less shape as a rejected alternative; the stale "consecutive"
vocabulary left the loop test's name and the rounds fixture; the
"round 1" journal citations left the new code comments; the PR title and
body were rewritten to the current design. Mutants applied by hand and
killed with `PYTHONDONTWRITEBYTECODE=1`: the tools dropped from the
finalize request again (the loop and coordinator tests fail on the
carried schemas), the shape guard removed (the adapter test fails), the
detail-keeping dropped (the later-stop test fails), and the round-1
suite (shared counter, threshold, wiring) re-killed. Full local checks
green; offline only.

## 2026-11-18 (same day) — #745 round-3 fixes: the Bedrock premise marked (verify), and the nudge-label lists completed

Round 3 returned APPROVE with two documentation items. D77 stated the
Bedrock Converse tool-history premise as fact; it now carries the repo's
`(verify)` marker -- documented across OpenAI-to-Bedrock translation
layers' issue trackers, not yet probed on this repo's own live route --
and its revisit trigger now includes the first live run settling the
premise (a finalize reply that still calls tools, or the shape turning
out to be accepted). The README and the adapter guard's message say
"documented to reject" instead of the bare claim.

The `session-limit` nudge label joined the two label lists it was
missing from -- `note_nudge`'s docstring and the `atlas.nudge` comment
in `tracing.py`, the latter also gaining the `quote-repair` label it had
been missing before this PR. Docs-only round; the suites, lint, format,
mypy and drift are unchanged-green.

## 2026-11-17 — CI moves to GitHub-hosted runners for every event (D78)

main's `gate` runs had been stuck `queued` since roughly 3 AM CT: the
workflow's `runs-on:` sent `pull_request` to `ubuntu-latest` but
`push`(main)/`schedule` to `fromJSON('["self-hosted", "Linux"]')`, and the
fleet's runner for this repo was down — the single point of failure the
self-hosted guide's own Accepted Risks section had already recorded ("no
automatic failover... a job with no available runner sits `queued` rather
than erroring"). Brandon called the migration at 5:43 PM CT (D78): every
event of every workflow under `.github/workflows/` now runs on GitHub-hosted
runners — `runs-on: ubuntu-latest`, left floating rather than pinned to a
dated image because every gate already version-pins its tools independently
of the runner OS (hash-pinned `requirements.txt`, exact-pinned
pip-tools/pip-audit/pip-licenses, checksum-verified upstream shellcheck and
actionlint tarballs — the apt-pin breakage the tarballs replaced was itself
coupling to a runner OS archive). Only `ci.yml` existed; no other workflow
file carried a runner label.

Workarounds retired with the persistent hardware, each in place: #366's
fresh-venv install (its precondition — site-packages accumulating across
jobs on one shared interpreter, silently skipping a pin's hash check —
cannot occur on a per-run VM; the image-baked tool-cache interpreter can
still in principle satisfy a pin, so the install keeps
`--require-hashes --ignore-installed`, resolving and downloading every pin
whatever the image holds — round-1 review of #746, Minor 2), the
event-conditional `cache: 'pip'` (#475/#589), the fleet's arch-agnostic
`runs-on:` notes, and the `$RUNNER_TEMP`-vs-`$HOME` persistent-host defense
notes. Kept because still useful: the hash-verified `pip install
--require-hashes` gate, the per-arch shellcheck/actionlint downloads (any
hosted Linux arch), and the fail-fast step ordering. The concurrency block
keeps `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` and
adds the event name to the group (`ci-<event>-<ref>`) so the weekly schedule
never shares a group with main pushes: schedule resolves to the default
branch's ref, so a ref-only group put them together, and — the correction
this entry's first draft got wrong — a concurrency group holds at most one
running and one pending run, and a newer run cancels an older *pending* one
regardless of `cancel-in-progress` (observed live: push run 44087837195 was
cancelled at 2026-11-17T23:41:36Z, the instant run 44181631062 queued; round-
1 review, Minor 1). So no config can promise a recorded run per commit: what
the group split buys is that a mid-week push can neither cancel an
in-progress audit nor supersede a pending one, superseded *pending* main
pushes are accepted (the newest head's result is the one that matters), and
PR runs keep the cancel. D78 does not close #471's residual gap: GitHub
evaluates a plain `pull_request` workflow from the PR's own head, so a
hostile PR can still edit its own `runs-on:`; the protection is the Settings
value ("Require approval for all outside collaborators"), not this file.

Guards moved with the decision: `tests/test_ci_runners_are_github_hosted.py`
replaces `test_ci_pull_request_runner_is_hosted.py` (which pinned the split
shape D78 removes — every job's `runs-on` must now be a plain hosted label,
with no `self-hosted` and no event-conditional expression) and globs every
`*.y*ml` file under `.github/workflows/` with a non-vacuity assert, not
`ci.yml` alone — a second workflow file carrying a self-hosted label must
fail CI (round-1 review, Minor 3, confirmed by a two-file probe);
`test_ci_require_hashes_targets_fresh_venv.py` becomes the slimmer
`test_ci_require_hashes_install.py`, which pins the `--ignore-installed`
flag the install needs once the venv is gone.
`docs/self-hosted-runners.md` stays as the fleet how-to for the
repos that still self-host, with this repo's state updated in its header
and Per-repo notes; the review-lens content about self-hosted runners
(`auditing-deployment-and-trust-boundaries` and its `collapsed/` copy) is
guidance about other repos and was left alone, as were the historical logs.

Deliberately not touched: the stuck runs on main (no cancel, re-run, or
settings change), the runner registrations, and `docs/research/` (records
of findings, not live state). Round-1 review fixes on #746 landed in the
same PR: the concurrency wording and group (`ci-<event>-<ref>`) above, the
`--ignore-installed` flag, the guard's whole-directory glob, the
`$RUNNER_TEMP` comment's PATH contradiction, and the runner doc's
self-check grep — each pinned by a test or killed mutant: dropping
`--ignore-installed` fails
`test_require_hashes_install_exists_and_ignores_installed`; a second
workflow file carrying `[self-hosted, Linux]` fails
`test_every_job_in_every_workflow_runs_on_a_github_hosted_runner`; the
event-conditional expression shape stays killed by
`test_no_job_conditions_its_runner_on_the_event`. Round-2 review added one
Minor — the group expression itself had zero CI signal, mutant M4 (revert
to the ref-only group) passed the whole suite — closed by
`tests/test_ci_concurrency_group.py`, which pins the parsed
`concurrency.group` to carry `github.event_name` and `github.ref` and
`cancel-in-progress` to the PR-only expression (M4 now fails
`test_concurrency_group_carries_the_event_name`; a bare-`true`
cancel-in-progress fails `test_cancel_in_progress_stays_pull_request_only`).
Round-3 review hardened the cancel-in-progress pin from a substring check to
an exact whitespace-normalized match on
`${{ github.event_name == 'pull_request' }}` — the substring version let the
inverted split `!= 'pull_request'` pass (mutant M7, the semantically worst
survivor: push would cancel an in-progress audit and PR runs would stop
superseding); M7 now fails the exact-match assert, with M4 and the bare
literals re-verified dying.
Verification, all on the
PR head: `pytest tests/` 880 passed / 14 skipped, coverage 95.20% (floor
94%); `pytest atlas_reviewer/tests` 3,242 passed, 96.42%; ruff
check/format, mypy (84 files), `tooling.cli drift` clean; actionlint 1.7.12
clean on `ci.yml`. Offline only.

## 2026-11-18 — #702: the keep-or-cancel decision for a push that lands mid-review (D79, PR 1 of the stack)

The queue superseded any active job of a pull request on every newer
head, so a review in flight was cancelled and its spend lost on exactly
the pushes that carry the least review risk (the Nov 14 sample was
mostly merges of main and docs or test-only fixes). This slice — the
first of the two-PR stack the brief allowed, the delta review being the
second — moves the decision into the service parent as a pure rule
(`head_change.py`) over what the push changes (classified from GitHub's
comparison of the two heads plus the base: every commit whose second
parent is not `merge_base(base, new)` reads as code, so a
feature-branch merge is never a base merge; the benign kinds are
claimed on evidence only — a cut commit list (an empty, untruncated range is benign; corrected by round-1 F6, the first wording here was wrong), a failed fetch,
or no credentials at all read as code or keep with the gap recorded,
never as benign by default), what the review is still reading (the
review child now records a cumulative `progress` telemetry event into
its run's events file after every settled lens and once when its lens
loop ends — lenses settled of the planned count, spend against the
derived reservation, the paths still being read), and how early the
review is (`ATLAS_HEAD_CHANGE_CANCEL_FRACTION`, default 0.5, early on
both the lens and the spend fractions; round-1 F1 corrected the first
wording's either-measure reading). A kept head is recorded as the
pull request's pending follow-up in the queue file — never holding an
active slot — and materializes when the running review settles: a
success queues it as a delta review (`PrEvent.delta_from`, the second
PR's subject), a failure queues an ordinary review; a queued follow-up
a newer push supersedes passes its `delta_from` on, so the chain stays
anchored on the last head a review actually finished. `Board.enqueue`
keeps its supersede contract untouched, and
`ATLAS_HEAD_CHANGE_POLICY=cancel` restores the blanket supersede whole.
Measure-first is wired: one `head change` event per decision (both
heads, kind, fractions, reason, gap), a `review cost` event per settled
review (draft cost lines when finished, the last progress record when
cancelled or failed — read before the run directory is dropped —
`measured: unknown` past both), and `follow-up queued` for the
materialized head, all tagged with the heads in `service.jsonl`.
Deliberately not done here: the delta review itself, and the session-log
rotation the file's length owes (#467/#520 pre-existing debt, untouched
per the D70 correction's precedent). Tests (the counts as of this
entry; the later rounds grew them — 37 and 22 at the round-1 fix head,
per that entry): 31 in
`atlas_reviewer/tests/test_head_change.py`, 13 service flows in
`test_service_receive.py`, the progress emission pinned end to end
through a real `JsonlSink` and read back with the real reader in
`test_coordinator.py`; named mutants in the D79 entry. Verification, all
on the PR head: `pytest tests/` 880 passed / 14 skipped, coverage
95.20% (floor 94%); `pytest atlas_reviewer/tests` 3,289 passed,
96.06%; ruff check/format, mypy (85 files), `tooling.cli drift` clean.
Offline only.

## 2026-11-18 (same day) — #702 part 2: the delta review and its carry-forward (D79 update, PR 2 of the stack)

The follow-up a kept head materializes as (PR 1's `take_pending`) is now
a delta review. Its diff is the pull request's diff at the new head
restricted to the paths the range `delta_from..head` touched — the pull
request's diff never carries merge-from-base content (merging the base
moves the merge base forward, and the base's changes drop out of the
three-dot diff), so the restriction IS the range diff with that content
excluded, with no per-commit reads; a merge-only push yields an empty
delta, whose review exists to carry the earlier findings forward. After
the delta's lenses settle, one bounded, tool-less carry-forward call —
built like D73's re-assessment and quote-checked through the same judge,
so the two paths' quote checks cannot drift — judges the earlier
review's findings (the round log's records at `delta_from`, parsed back
from `{id} {severity} {location} {finding}` lines, labeled by position
`P1`, `P2`, ...): a verified re-statement joins the findings set under
its `P` label and counts for the verdict (reconstructed
defect-introduced, the conservative direction); a resolution is accepted
only when the prior finding's location is a path the delta touched (the
mechanical gate that keeps PR content from resolving a finding on a file
the new commits never changed — a refused resolution is recorded as the
proposal it is); everything else is carried as the record stored it, in
the draft's `Carried, not re-verified` section AND back into this
review's round record, so the next review re-offers it — nothing
silently dropped (D73). A finding identical to a carried one is posted
once, as the carried copy. The delta post cites the review it builds on;
the status line carries `carried`/`resolved` on a delta review; an
unfetchable range falls back to the full diff, recorded in the draft.
The dry-run lens script grew a `carryforward` scenario section
(controller-level), validated at load with the real carry-forward parser;
the scripted reviewer answers the carry turn from it — checked before
the body markers, because the carry system prompt carries no lens body
(the scripted model's `_markers` used to run first and refused the turn,
which is how the fixture dry run found the ordering bug). Tests: 25 in
`atlas_reviewer/tests/test_delta.py`, 5 delta flows in
`test_coordinator.py`, 2 in `test_service_run.py`, 2 in
`test_service_post.py`, 6 in `test_lens_script.py`, and two delta dry
runs over the new `fixtures/sample-pr-delta/` in `test_cli.py` (the
delta scope's two files, the carried blocker, the dedupe, the record's
carried line, and the no-prior gap named). Verification, all on the PR
head: `pytest tests/` 880 passed / 14 skipped, coverage 95.20% (floor
94%); `pytest atlas_reviewer/tests` 3,332 passed, 95.78%; ruff
check/format, mypy (86 files), `tooling.cli drift` clean. Offline only.

## 2026-11-18 (same day) — #748 round 1: the carry-forward's gate fails closed, resolutions need evidence, nothing leaves the chain

The protocol review's five Majors, fixed on the delta branch (the
correction appended to D79 carries the full list and its tests):
the resolution gate no longer fails open where the delta is not the
delta — `DeltaScope.resolution_paths` is empty on an unfetchable range,
a diverged compare (rebase or force-push), and a malformed or
cap-cut `files` list, refusing every resolution and naming the reason;
a resolution now requires evidence the new commits removed the cited
code (every quoted line among the delta diff's removed lines for that
file), not the model's say-so; an unparsed prior line travels as the
record's raw text verbatim — shown and re-recorded — instead of
vanishing behind a note that claimed it carried, and the location in a
record's finding line is now quoted, so a path with a space parses
whole instead of silently corrupting (the legacy unquoted form still
parses when its token is unambiguously a line range, and an ambiguous
one is refused rather than guessed); a carried prior that fails to
re-anchor still counts for the verdict, so a standing prior Blocker can
never become an approval — including when the carry call fails whole;
and a record whose finding lines did not fit the 8 KB cap is named as
the omission it is instead of reading as "no findings recorded". The
Minors: the unreadable-log naming, the double-counted raw lines (one
walk now), the compare-cap and malformed-`files` shapes, the
carried-vs-carried dedupe across two records at one head (the
paraphrase case stated as the exact-match limitation it is), the
instructions no longer inviting findings the composition drops (a
non-`revises` entry is dropped and named), the D79 test list and the
"5 delta flows" count corrected (13 in `test_coordinator.py` now), the
no-delta-sections test parsing a real full-review draft, and the shared
parsers promoted to public names so `delta.py` stops reaching into
underscore internals. The Nits: the docstring churn reverted, the dead
helper removed and the shadowed parameter renamed, the carry call's
model now wrapped by the lens trace (it was the one review-stage call
with no span), and the status line carrying `carried_unverified` beside
`carried` and `resolved`. One test flake observed once
(`test_instrumented.py::test_every_read_returns_what_the_inner_reader_returned`,
a tarball read) and not on retry or in the full re-run; left alone.

## 2026-11-18 (same day) — #747 round 1: finishing is the default, the race installs, the gap is recorded

The protocol review's three Majors, fixed on the bottom layer (the
correction appended to D79 carries the full list). The "early" test is
now under the threshold on BOTH measures — the lens fraction and the
spend fraction — because the spend measure reads against D68's derived
worst-case reservation and so cannot tell an early review from a cheap
one: the reproduced case (every lens settled, a third of the
reservation spent) was cancellable in the window between the lens loop's
end and the post, where a cancelled review's draft is never posted and
the whole spend is re-spent. The issue's literal "or" supported the old
reading; owned here as an ambiguity resolved the wrong way, with the
reason string's self-contradiction fixed with it. `keep_head`'s race
branch — the review settling between `head_change_candidate` and
`keep_head`, up to three 5-second reads later — now installs the head
under the same lock instead of answering `queued` over nothing (a 2xx is
an acknowledgment GitHub will not redeliver, so the old branch dropped
the pushed head while claiming it). A classifier-less deployment — the
App credentials absent or unusable — now records the gap on every
unclassifiable decision with an error status, and the boot log says once
that the cancel branch is dead ("head-change policy is keep with NO
classifier …"); the classifier's builder returns the reason there is
none. The Minors: the cut-commit-list test's input is an all-base-merges
cut list (the old input killed the guard only by accident of its paths);
the at-threshold boundary pinned (`<=` mutant dies); D79 and the session
log no longer say an empty commit list reads as code (the code and the
README were right); stranded pending heads are recovered — at boot and
on every worker pass, `Board.recover_pending` queues a pending head
whose PR has no active job as an ordinary review, and `take_pending` no
longer appends past the active-slot cap, leaving the head for the
recovery; the `head change` event carries the decision's duration and a
`timed_out` flag for a classification that ran past its transport
timeout; the PEM normalization lives in one place
(`github_auth.normalize_pem_key`) and `service_post.repository_names` is
public; the `step is` string-identity comparison is `==`; D79 gained its
Revisit clause (re-measure on live decision/cost telemetry; reopen when
keeps would have been cheaper as cancels or the reverse) and D48, D53
and D74 carry `Update (2026-11-18, D79)` notes, so no older entry states
the reversed supersede as live; the vacuous truncation test replaced by
real ones for the reading cap and the reader's tail-seek; the
comparison-without-`files` shape refused instead of read as empty;
`pending_head` replaced by `pending_heads`, which the boot log reads;
the dead `PROGRESS_SOURCE` removed; the duplicated `_threading` alias
import removed; the progress record's `lenses_done` field is the one
source for the settled count (read back directly, not recounted); the
classifier's docstring no longer claims GitHub redelivers a timed-out
delivery (D53 records the opposite). The Nits noted: F18's trust-model
boundary (the base-merge evidence comes from the party the review
judges; every consequence lands on the keep side) is stated in D79 and
the README. Counts corrected: 22 service flows in
`test_service_receive.py` (15 from the first push, 7 from this round),
37 in `test_head_change.py`.

## 2026-11-18 (same day) — #747 round 2: the recovery cannot interleave or post stale, and the docs catch up to the code

The round-2 protocol review (APPROVE) asked for the Minors and cheap
Nits. The behavioral one is the recovery's two windows (R2-F4):
`recover_pending` now checks that the pending head is still the
pull request's accepted head, dropping a stale record the way
`take_pending` drops one — the consequence of the old shape was a
stale COMMENT posting for a head the PR had moved past, since
`still_current` compares nothing against `_heads` — and the review's
settle and its follow-up's install are one queue step now
(`Board.settle`: the supersede coercion, the pending checks, the
install and the save under one lock, one save, one rollback), which
closes the interleave window where an idle recovery pass between a
review's `finish` and its `take_pending` installed the head as a plain
review and cost the follow-up its delta base. The classification runs
under one overall budget (`_CLASSIFY_BUDGET_S`, 8 seconds, in a helper
thread the caller waits on) — past it the push is unclassifiable-keep
with the gap and `timed_out` on the event, and the handler's occupancy
is bounded (R2-F8). `_diverged` reads a missing or malformed merge base
as diverged — fail closed, like every other unusable shape (R2-F5).
The first progress wave is emitted as lenses complete (`as_completed`),
not in submission order, so a pool past one no longer leaves no record
until the slowest first-submitted lens settles; `runs` stays in
submission order, so the draft's ordering, mint ids and clean-run
supersession are unchanged (R2-F7, done in this layer — it is the
shared coordinator surface). The reading set round-trips as a JSON
array (paths with spaces mangled by the space-join; a cap-truncated
value falls back to the legacy space split, whose fragments match
nothing — keep direction) (R2-F12). The progress record's field names
are one home's constants on both the writer and reader side (R2-F13).
The decision constants are named apart from the policy constants
(`DECISION_KEEP`/`DECISION_CANCEL`) and the dead Optional guard on
`_decision_fields` is gone (R2-F14). The docs: the README's env-var row
now says both measures (R2-F1); D79's tests paragraph no longer
inventories the superseded OR rule (R2-F2), and D79 records the spend
gauge's reading explicitly — `settled_usd / reservation_usd`, the
directive's "actual spend" read as the settled-vs-committed distinction
in the numerator, the denominator left as the derived reservation
(directionally safe: clamped under the ceiling, so the implemented
measure cancels less than a ceiling gauge would), with the Revisit
clause covering Brandon weighing in (R2-F6); the first session-log
entry's superseded wording and counts now carry their corrections inline
(R2-F3). The one-sided `<=` boundary corner is pinned (R2-F15); the
race test's tautological assertion is a real pending-empty assertion
(R2-F10); the duration pin uses a clock that advances, so a dropped
`start_s` fails it (R2-F11). deploy-service.md documents the downgrade
rollback: a release without the queue file's `pending` key and
`delta_from` strands kept heads (their redelivery is refused), so drain
before downgrading, with the boot log's `pending follow-ups N` as the
observable (R2-F9).

## 2026-11-18 (same day) — #748 round 2: the evidence pool is the range's, and the omission rides the chain

The round-2 protocol review's two Majors, fixed on the delta branch
(the correction appended to D79 carries the list). The resolution
evidence pool was the pull request's `base...head` net diff restricted
to range paths — the removed lines of the very diff the review runs on
— not the `delta_from..head` range's own deletions: a delta commit
deleting PR-added code is invisible in a net diff (the line exists at
neither end), so the dominant legitimate resolution could never produce
evidence, while a pre-delta PR removal sat in the pool and could clear
the gate. The pool is now `DeltaScope.removed`, read from the
comparison's per-file `patch` fields with each removed line's old-side
line number — the range measures its patches from `delta_from`, so
those are the coordinates the prior findings cite — and the carry turn
shows the range's own patches, so the assessor can quote what the
commits actually deleted; the judge's quote sources come from the same
range diff. The evidence check is span-bounded (round-2 a2): every
quoted line must sit within the finding's cited span widened by the
quote tolerance, so any removed line in the file — down to a one-line
brace — no longer clears the gate. The summed `findings_omitted` now
rides on the review (`carried_omitted`) and into `_round_record`, added
on top of `fit_record`'s own drops, so the gap stays in the durable
chain across hops — pinned by a two-hop test. The Minors: a comparison
with no readable merge base is untrusted (a1); `_capped`'s truncation
branch is pinned (a4), its docstring stating why a truncated delta
still judges resolutions safely (the pool is structured; an assessor
that cannot see a removed line cannot quote it); the D79 Update's dead
`delta_review_diff` reference and superseded gate prose corrected in
place (a5). The Nits: `prompt.fence_rule` public (n5, the last
underscore reach-through); `CarryCallRefused` no longer stores the
never-read `found` (n6); the failed-carry note names the exception's
detail. Skipped with reasons, recorded in D79: n7 (the fabricated
`ReassessReply` shim — harmless while the carry path stores no
attestation, and un-fabricating it splits the judge for one caller) and
n8 (the 16-parameter clump is the existing `review_lens`/`_review_one`
convention; a delta-only context object would be a second convention).

## 2026-11-18 (same day) — #748 round 3: a re-statement cannot lower the recorded severity

The round-3 protocol review's Major C, fixed on the delta branch: a
verified carry-forward re-statement replaced the recorded prior finding
wholesale — severity, valence and attribution all from the model's reply
— so a carried Blocker restated as a nit flipped the delta verdict to
APPROVE; the round-1 M4 guard covered only the unanchored priors. The
rule is now D73's own: a re-statement re-anchors location, evidence and
wording, but a replacement that would leave the verdict-setting set
weaker — a lower severity, or valence/attribution moved off
defect-introduced — carries the RECORDED severity and shape with its
re-anchored copy, and the proposal is named in the draft; a raise is
taken (the conservative direction). Pinned by the delta-level tests
(Blocker→nit keeps BLOCKER and names the proposal; a raise is taken;
the valence trade refused the same way) and the coordinator-level probe
(Blocker restated as a nit keeps the verdict at BLOCK). The Minors: the
two-hop omission test's second hop now points its scope at hop one's
own head and asserts the note's sha is hop one's — the assertion that
dies when the hop re-reads the seeded record (a6); `_patch_removed`
treats a `---`-shaped line as a header only before the first hunk (a
SQL or Lua comment inside a hunk is content) and the
`\ No newline at end of file` marker moves no counter (a7); the delta
note goes through the quote discipline like every other model-adjacent
field (a8); the D79 Update's parse-format sentence was to name the
quoted-location form (a9 — claimed in this entry and not applied; the
round-4 fix corrects it, below); the #747-owned session-log heading
restored to its own layer's text (a10). The Nits: the unused `names` parameter
dropped from `_range_removals` (n9); the module docstring's acceptance
sentence names `DeltaScope.removed` and the span bound (n10). Skipped
with reason: n11 (the coordinator-level pool test injects its pool
synthetically — the real `delta_scope`→`_carry_call` wiring is pinned
at the delta.py level with a compare fixture; wiring the coordinator
test through a fixture-backed reader would duplicate that pin).

## 2026-11-18 (same day) — #748 round 4: the a9 sentence actually corrected (b1)

The round-4 protocol review's one Minor (b1): the round-3 fix claimed —
in its commit message and in the round-3 entry above — that the D79
Update's parse-format sentence named the quoted-location form, but the
fix commit touched no `docs/open-questions.md`, and the Update still
described the record's finding line as the unquoted
`{id} {severity} {location} {finding}`, while `_round_record` has
written the quoted-location form `{id} {severity} "{location}" {finding}`
since the round-1 fix (the location quoted so a path containing a space
cannot be misread as the finding's first word). The sentence now names
the shipped form, with the correction owned in place, and the round-3
entry's a9 clause above was corrected to say the fix was claimed and
not applied. The round-4 verdict is APPROVE with nothing else at or
above Nit; the round-3 mutants were re-applied by the reviewer and all
13 died.

## 2026-11-18 (same day) — #748 round 5: the unproven scope never bounds a review

PR #747 merged (main `9b5f8841`); #748 retargeted to main and restacked
(`83dbc6c7`, the round-4 tree). CodeRabbit finished after the round-4
APPROVE, and Brandon's round-10 routine review verified three of its
Majors and approved the round. The fixes, each pinned by a named test
whose mutant dies: **Major 1** — a diverged history or a cut comparison
file list cannot prove what the range touched, so `delta_scope` no
longer narrows the lens diff to such a list (the review runs the full
pull request diff, the unfetchable case's own fallback), and the
service-side family case is fixed where the shape is decided:
`ReviewReport` carries the status line's `coverage_complete` flag and
`Board.settle` keys the follow-up's shape on it, so a finished review
that did not read every changed file queues its kept head as an
ordinary full review, never a delta on an unread base. **Major 2** — a
prior finding the delta cannot assess (a raw-text line, a legacy
unquoted whole-file location among them, or a record-cap omission)
marks coverage incomplete through `_lens_gap`, the one coverage rule,
so a clean delta over it posts COMMENT and never a plain approval; a
complete record with no standing findings still approves. **Major 3** —
the carry-forward's exception note is scrubbed where it is recorded, so
the status line and the body carry the same redacted text
(`_status_log_note` never scrubbed). **The check** — `LensKey` carried
no scope, and the deployment-wide attestation ledger would let a later
full run at the same head reuse a delta run's settled lens and its
unread list; the run's scope digest now suffixes the key
(`lens@<12-hex>`), same-scope reuse intact. The cheap CodeRabbit
fixes: the resolution gate is the range's own touched paths (a deleted
file's resolutions accepted; renames contribute `previous_filename` to
the gate and the removed pool), the patch reader splits on LF only, a
double quote is refused in a finding's location at the mint-side
contract, the dedupe keeps the duplicate pair's stronger finding, the
carry call checks the review wall before its reservation and again
before sending (a reservation that crosses the wall is accounted, not
sent), the parser's dropped restatements are named in the draft (D54),
the post quotes the draft's delta note instead of asserting a carry,
and the post's resolved and carried sections render the controller's
bullets scrubbed and uncapped. The fixture tree's dry-run realism fixes
landed with it (the head commit in `pull-commits.json`, the hunk
counts, `changed_files`, the scenario's cited line, the SPDX header,
the runner's ruff response matching reality). Skipped with one-line
reasons in the PR body: the record's valence/attribution fields, the
stale-anchor SHA check, the withdrawal quote's content match (the last
two and the first fail closed or over-count conservatively today; the
first and third need the record-format change), the base-merge path
separation (documented deliberate over-inclusion), the quarantined-log
note wording (the context omission already blocks approval), and the
fixture withdrawal scenario (pinned at the delta and coordinator
levels). Seventeen mutants applied by hand this round; all died.

## 2026-11-18 (same day) — #748 round 6: the record catches up with its own justification

The round-6 protocol review's verdict is APPROVE — all three round-5
Majors and the LensKey scope fix verified, 17 mutants dead, the six
skips' reasons each re-traced and held. Two residuals, both records:
**b2** — the round-5 correction justified the one-shot CLI's delta
narrowing with "no round log is read in that mode", which is false (the
one-shot delta path reads the round log through `--round-log`, and the
branch's own end-to-end dry run does exactly that); the clause is
corrected in place in D79, and the justification now names what
actually makes the exception safe — the delta's own coverage is held to
the same `_lens_gap` gate every review runs, so unread files and
unassessable priors still block a plain approval there. **b3** — the
mint-side double-quote refusal makes findings on a double-quoted path
unreportable (the finding fails the reply's contract, the lens retries
into the same wall until its attempts exhaust, the lens ends failed and
coverage incomplete, and the review lands COMMENT — never an approval
over the gap); recorded in D79 as a known limitation with the
record-format follow-up as its escape, not a behavior change. Docs
only; no code touched.

## 2026-11-18 — #759: the delta review redesigned — the whole changeset stays the subject, the coordinator judges each lens (D83)

Brandon amended the delta review the same day #748 shipped: a live
delta post had told the PR's readers "This is a delta-only review:
unchanged content (...) is not re-reviewed", and the design backed it —
the lenses ran on the diff restricted to the range's touched paths, and
the prompts and docs said so. The wrong contract was in the design
itself, so the fix is in the design: `DeltaScope` is no longer a lens
scope (the `diff` field and its pr-diff intersection are gone), the
review's diff is the whole pull request at the new head, and only the
incremental diff travels as the new material. Before any lens runs, the
coordinator makes one bounded, tool-less judgment call over the
incremental diff and the reuse-eligible lens names (read from the round
records at `delta_from` — the per-head ledger is unreachable across
heads, and its run directory is dropped on job end, so the round log is
the only durable cross-head record): per lens, re-run on the whole pull
request or reuse the earlier settled result, each with a stated
reason. A re-run lens may report findings anywhere in the pull request
(unchanged content included) and sees the incremental diff highlighted
in its first turn as a `delta-diff` block sized like the CI block; a
reused lens makes no turn, its findings stand through the carry-forward
(D73's rules intact, resolutions still gated on the range's removed
lines), and its files count as covered — "complete coverage" means
every file in the pull request covered by a re-run or by a reused
result that read it, never merely every delta file. Fallbacks run to
the safe side: an unestablished delta reuses nothing and skips the
call, an empty (merge-only) delta reuses every eligible lens without a
call, and a failed or refused decision reply re-runs every eligible
lens with the failure named. Every decision lands in the telemetry
(one event per lens), the round record (a new `decisions` field, bound
at 4,096 characters with the overflow named — and the record's lens
list now names reused lenses too, so the next delta can reuse what this
one reused), the draft's `Lens decisions (delta review)` section, and
the posted comment's `Lens decisions` section; the status line carries
`reused`, and the headline no longer claims every lens ran when some
were reused. D68's cost goals hold: a reused lens costs nothing, and no
turn re-sends the full diff where the incremental one answers. D83 is
recorded in `docs/open-questions.md` with a Correction on D79 marking
the superseded scoping sentences as history, not silently rewriting
them. The Claude Code routine's protocol needed no counterpart fix: its
only-new-findings and proportional-output rules are about posting, and
its lenses already run the pull request's full diff every round.
Eleven hand-applied mutants died on their named tests (the
path-restricted scope restored, both payload flips, the lookup
inverted, the decision ignored, the reused-as-uncovered count, both
record drops, the eligibility drop, and the two no-call branch drops),
plus three on the reply parser and one on the highlight block.

## 2026-11-18 (later) — #760 round 1: the two honest-accounting Majors, fixed under Brandon's calls

The protocol review's verdict was CHANGES REQUESTED on two Majors, both
in what the delta review CLAIMS rather than what it sends. **Major A**
— the coverage contract's "a reused settled result that read it" was
unenforced and unverifiable: a reused result read the pull request at
the delta base and nothing more, so a file the delta added was claimed
covered with no lens having read it this round, and the reviewer's
probe reproduced an all-reuse APPROVE over a delta-added file. Fixed as
an accounting rule, not a lens scope: the delta's touched paths ride on
the review (`delta_paths`), every one must be read by a lens that ran
this round, an uncovered one is unreviewed and holds the review at
COMMENT; the merge-only fast path composes (empty touched set), the
patchless-established case now gates too. **Major B** — the delta-reuse
path never honored D73: a reused lens made no turn, so the fresh CI and
conversation evidence never reached it, and with no ledger entry at
this head the `_reused_with_reassessment` mechanism could never fire.
Brandon decided the shape: the decision turn now sees the fresh
evidence blocks the lenses get, and a reused lens earns its bounded D73
re-assessment when the evidence moved — the round record now stores the
digest each review settled under (a record without one reads as
"cannot be shown to be current", so the first delta after this ships
re-assesses), the same `_reassess_call` runs on a `#reassess-delta`
ledger key, composed by the same `effective_outcome` over the lens's
carried findings (the carry-forward's re-anchored versions, so the two
judgments cannot disagree about what stands); additions join the
findings minted `R<n>-F<m>`, revisions replace carried findings (never
lowering a Blocker or Major — annotation-only), withdrawals are
annotations, and the composition is recorded on the decision across the
same four surfaces, with the verdict recomputed. Per-lens attribution
came from a new parallel record field (`attributions`), with the
`L<n>`-id fallback for older records. The design call landed as
technical decisions: uncertainty resolves toward re-running (pinned in
the prompt), each offered lens carries its one-line concern summary
(`LensLibrary.concern`), and a lens whose findings cite delta-touched
files is flagged to the turn and the flag recorded. The Minors: the
record also carries `clean_lenses` so `_reuse_eligible` offers only
settled results (Minor C, docstring corrected); the `DECISIONS_CHARS`
bound and its overflow naming are pinned (Minor D — round 1's cap
mutant survived, it dies now); an empty offer skips the billed decision
call (Minor E); `fit_record` drops decisions before findings on
overflow (Minor F). Nits: the README's empty-delta parenthetical names
both cases, and the off-delta test's docstring states its two-legged
kill. Twelve new hand-applied mutants, all dead on their named tests
(the coverage accounting dropped, the reassessment dropped, both digest
legs, the flag computation, the cap, the empty-offer skip, the
fit-record order, the uncertainty sentence, the clean-set read, the
turn's evidence blocks, and the concern line).

## 2026-11-19 — #760 round 2: the digest's write side, and the reuse chain stops decaying

The round-2 review's Major was the same failure shape as D74's round-1
Major: a mechanism built and claimed but unreachable in the deployed
path. `_record_round` had taken the `evidence_digest` parameter since
r1, but neither call site passed it — every record stored `""`, every
`_prior_digest` read "cannot be shown to be current", and every delta
review re-assessed every reused lens once per head unconditionally,
recurring against the ceiling D68 exists to enforce. Fixed at both call
sites and pinned end to end through the real `_record_round`: three
chained rounds (full review at the delta base → delta round on an
unchanged snapshot digest → no re-assessment call, digest persisted;
same chain with a moved digest → exactly one bounded call), plus the
single-lens call site's own pin. Brandon decided the reuse chain's
decay: a lens reused this round whose composed outcome is still clean
(the re-assessment added nothing — `LensDecision.gained_findings`) is
recorded in `clean_lenses` and stays reuse-eligible next round; a
reused lens that gained findings is not, because its settled result
changed. Both pinned by the chained test; the stale comments corrected
(the lens list is the ran-or-reused record; `clean_lenses` gates the
offer). The recomputed verdict got its pin: a re-assessment-added
verified Blocker flips the verdict to REQUEST CHANGES, and the
stale-verdict mutant dies. Nits: the unused `review` parameter dropped
from `_reassess_reused_lens`; a legacy record's unattributed line
attributes to nothing instead of storing the comma-joined lens list as
if it were one lens (pinned through the carry-forward into the new
record's `attributions`); `concern()`'s docstring now says the concern
line travels bare (trusted bundle prose), not "quoted". Six mutants
applied by hand; all died on their named tests.

## 2026-11-18 — #750: the reservation's output term double-billed reasoning tokens, unpriced settles kept the ceiling full, and a stopped post read clean

Issue #750's recorded v8 observations on the #702 stack (#747, #748 --
several thousand lines each): every advisory review stopped early on
`reservation_usd`, the $10.00 ceiling (D68) firing after about 4-5
planned lenses and 4 model calls, with the posted reviews saying
"Findings: None" while coverage was incomplete. Measured from the code
and the issue's numbers only (the owner's standing no-live-runs decision
holds until coverage parity): committed spend of $9.999988 across 4
calls is 4 calls averaging about $2.50 of held worst case each, and the
$11.16/$12.73 stop projections are the refused next call's worst case on
top of that. Two stacked causes, both in the per-call accounting (D43's
Update): the output term priced the whole output cap (the model's
completion limit -- 64,000 tokens on the pinned Sonnet route) at the
completion rate PLUS the reasoning rate, double-billing every reasoning
token -- a reasoning token is one of the turn's output tokens, not an
addition to them (OpenRouter's reasoning-tokens guide, OpenAI's reasoning
guide and Anthropic's extended-thinking page, all fetched 2026-11-18) --
and `_actual_cost` refused to price from tokens whenever the model had a
reasoning rate and the response reported no reasoning-token count, so
each such settle kept the full worst case as spent, `Spend`'s committed
never came back down, and the in-flight backpressure never recovered
room. Fixed by pricing the output cap at the higher of the two rates
(`budget.worst_case_usd`, the fit's rate in `tool_model.output_tokens_within`
matching it), pricing a reported reasoning count as the subset of the
completion count it sits in with a missing rate standing for the
completion rate, and pricing a missing count at the higher rate so the
settle frees what the reservation held; a count claiming to sit outside
the completion count keeps the reservation, as do a timeout's keep and a
BYOK call with no reported upstream cost (D43's never-undercount rules,
unchanged). Recorded as D82 (D80 and D81 are taken on open PRs #753 and
PR #751), amending D43's Update; the ceiling, the per-lens knobs and
`Spend`'s own rules are unchanged, and the reservation stays easy to
clamp for the planned operator/daily-budget slice. Second behavior
(issue #750's "can't be mistaken for a clean review"): a review whose
coverage is not complete -- or that the draft's status line cannot show
complete, the fail-closed reading `verdict.decide` gives -- now posts
with a "REVIEW INCOMPLETE -- not a clean review" banner above the
Findings section, and its empty Findings section names the
incompleteness instead of the bare "None." (`service_post.render_comment`,
`_findings_section`). The slicing and compaction design (Q26) stays
open: compaction shrinks the per-call input bound and composes with
this fix; neither is built here. Tests with fakes across
`test_openrouter.py`, `test_tool_model.py`, `test_fit_output.py` and
`test_service_post.py` pin both behaviors; the mutants applied by hand
and killed by their named tests are listed in D82's Tests paragraph
(R1-R6 on the reservation accounting, H1-H4 on the banner).

## 2026-11-18 (same day) — #757 round 1: the overrun tripwire, the correction sweep, and the ceiling's exact boundary

The round-1 protocol review's verdict is APPROVE — two Minors and three
Nits, all fixed or dispositioned. **M1** — D82's subset assumption
(reasoning tokens counted inside the output cap, the reported count
inside the completion count) now has an observable failure signal:
`Spend.settle` records an overrun note when a settle's reported cost
exceeds the worst case reserved for the call, the draft's one
`Model calls:` cost line carries the count and the per-settle note (so
the posted Cost section renders it and the cost event parses it), and
the one-shot `ReviewBudget.settle` flags the same on the record's usage
line; the accounting keeps the reservation (the bound that was held),
and D82's revisit trigger now names the tripwire's signal. **M2** — the
superseded sum formula's surviving current-state statements now carry a
**Correction (2026-11-18, D82).** note in the D55 style at the entries
that state it (D25, D31, D34, D40, D41, D43, D50 — D41's settle-refusal
sentence included), and the Q24 narrative sentence and the lens-based
agentic reviewer plan doc's four passages are corrected in place.
**N1** — the exactly-at-the-ceiling boundary is pinned: a reservation
projecting exactly to the cap is accepted (spend never passes the cap;
the `>` to `>=` mutant dies). **N2** — the PR body's overlap sentence
now names the decisions log and the session log as append-shared with
the two open tool PRs. **N3** — `Spend._reserve`'s genuine-stop
pre-check stays: the review's own mutant showed it behaviorally
equivalent to the wait's re-check, it is pre-existing defense-in-depth
in money code, and the review requested no change; left as is.

## 2026-11-19 — Config slice S1: the merge-base `REVIEW.md` parse moves onto `repo_config.py`, and the lens preference protects the whole floor tier

The user-configuration plan's first slice (`docs/plans/2026-11-18-user-configuration.md`
§5 S1, after S4 landed as #756; the decisions are D81's Q1/Q2 and D69's
5:13 PM CT update in `open-questions.md`). Offline only: the tests use
fakes, the shipped fixture and the real CLI's dry run; no live model,
Sprite or GitHub call was made, no secret was read, and no deployed
service setting, Fly config value or secret changed.

**What moved.** The D68/D69 `REVIEW.md` reads — the tarball walk, the
64 KiB bound, the two line grammars, the fail-open notes — left
`review_wide.py` for a new `atlas_reviewer/repo_config.py`, the parse
module the plan named, with `REVIEW.md` one constant (`REVIEW_MD`) so a
`.atlas.yml`-style rename stays the alternative the key set can grow
into rather than a second file (D81 Q1). `read_repo_config` parses the
file once against the closed schema; `review_md_ceiling` and
`review_md_lens_preferences` are its windows, byte-for-byte the old
semantics, so both existing lines parse identically and no behavior
changed. `review_wide.py` keeps only the derivation (`derive_review_wide`,
`resolve_ceiling`, the defaults) and points at the parse module; the
agentic path's ceiling note is unchanged. `cli.py` parses once where it
previously walked the tarball twice, and appends the parse's notes to
the selection note where D69's unusable-line note already surfaced.

**New keys are named, not silent.** A `review_`-namespaced line the
schema does not carry — the namespace every setting line in this file
lives in — is ignored fail-open with a named note (the key, the
condition, the default that stands; at most eight distinct keys named,
the remainder counted), the generalization of D68's unusable-line note
the plan's §2 called for. The note never echoes the raw rejected value:
the value is unvalidated author-controlled input, only schema-validated
numbers are ever named, and the key a note carries is validated
markup-free at parse (`review_[a-z0-9_]{1,80}`), the same trust boundary
D69's lens-shaped validation draws. Prose outside the namespace and
uppercase variants stay unremarked, exactly as they read today.

**The floor tier is protected.** `picker.py`'s preference application
now protects `FLOOR_TIER` — the manifest's whole `tier: floor` set —
instead of `CRITICAL_TIER` alone (D69's 5:13 PM CT update): an exclude
naming `hunting-silent-failures` keeps the lens on the picks, is not
recorded as dropped, and is refused on the fallback paths the same way.
The set is pinned against `skills/manifest.yaml` by a test, so a tier
change surfaces as a failure instead of silently widening what a
merge-base exclude may drop.

**Tests** (`atlas_reviewer/tests/test_repo_config.py` — the parse tests
moved beside the module they test — plus `test_picker.py` and
`test_cli.py`; each behavior a test that fails when reverted, each
mutant applied by hand and killed): both lines parse identically through
the module (the moved tests, unchanged); the unsupported keys' named
notes at the unit level (the key named, the value never echoed, the cap
and the dedup, the known keys never misnamed, prose outside the
namespace silent, notes composing with the unusable notes) and end to
end in the dry-run draft (`test_a_dry_run_names_an_unsupported_config_key_without_its_value`);
the floor-tier protection on the picks, in the record, on the fallback
path, and against the manifest
(`test_a_repo_preference_exclude_never_touches_the_manifest_floor_tier`,
`test_a_fallback_exclude_never_touches_the_floor_tier_either`,
`test_the_floor_tier_is_the_manifests_tier_floor_set`); the 64 KiB bound
preserved (the moved over-bound tests, plus the combined read's
over-bound case parsing nothing). Ten mutants applied by hand, all
killed: the protection set reverted to the critical four, the
picks-guard reverted, the dropped-record filter reverted, the fallback
set reverted, the unsupported scan disabled, the note echoing the
rejected value, the named-keys cap removed, the known-key exclusion
removed, the dedup removed, and the draft note dropped.

**Overlap.** The open #757 (D82) touches `budget.py`, `openrouter.py`,
`service_post.py` and `tool_model.py` — disjoint from this slice's
`repo_config.py`, `review_wide.py`, `picker.py` and `cli.py`; #752/#753
(D80) touch the bridge files, not these. `coordinator.py` is touched
only by its import line (the ceiling read now comes from
`repo_config.py`); no behavior there changed. The admission-side
default-branch read keeps S4's own narrow parse (its README sentence now
points at the shared parser's review-side naming); unifying the two
reads on one module is a candidate follow-up, not this slice.

## 2026-11-19 (same day) — #769 round 1: the scan learns the admission keys, and the trust boundary gets its pin

The r1 protocol review's fixes, applied on the branch and rebased onto
main (`66a33b31`; #760's delta redesign and #761's retarget admission
merged under this PR's base — `coordinator.py`'s conflict resolved by
taking #760's import simplification beside the moved
`review_md_ceiling` import, `docs/session-log.md`'s by keeping both
sides' entries in date order).

**Major 1 — the false unsupported note on the S4 admission keys.** The
scan's known set carried only the three review-side keys, so a repo
whose `REVIEW.md` carries `review_base_include:`, `review_base_exclude:`
or `review_skip_events:` — honored by `service_admit.py` from the
default branch since #756/#761 — drew a draft note falsely saying the
build does not support the key and ignores it, on every review. The
known set now carries all six keys (the scan stays silent about a key
the build supports, which is also main's behavior for every key), and a
test checks the set against `service_admit._ADMISSION_KEYS`, so a key
added to the admission read without this set fails the suite instead of
drawing a false note (`test_the_admission_class_keys_draw_no_unsupported_note`;
killed by the admission keys removed from the known set).

**Minor 1 — the markup-free-key boundary is now pinned.** The claim that
a note's key is validated markup-free at parse had no failing-when-
reverted test — the reviewer's loosened-charset mutant survived the
whole suite. `test_a_markup_bearing_key_is_never_named` pins that a key
outside the `[a-z0-9_]` shape (`review_<img src=x>:`, backtick, pipe,
space) draws no note, and the loosened-charset mutant dies on it.

**Nit 3 — fenced examples are not configuration attempts.** The scan now
skips lines inside a fenced code block and toggles the fence state back
off, so a policy file documenting a future key in an example draws no
note while a real unknown key after the fence still does
(`test_a_fenced_example_key_draws_no_unsupported_note`; killed by the
fence walk removed). The known keys' own parsers stay line-based and
unchanged — main's behavior — so an unbalanced fence can only shift
which unsupported notes appear, never a parsed value.

**Nit 1** — `_preferenced_fallback`'s docstring says "non-floor" where it
said "non-critical"; the protection set changed under it. **Nit 2**
(session-log rotation) is pre-existing debt, left alone as the fix brief
directs. Full local gate re-run on the rebased tree; three new mutants
applied by hand, all killed.

## 2026-11-19 (same day) — #769 round 2: the fence walk is CommonMark's edge subset, and the docstring stops overclaiming

The r2 protocol review (verdict APPROVE) left two Minors, fixed in one
commit. **Minor 1** — the module docstring's fence sentence ("lines
inside a fenced code block ... are skipped") overclaimed: unqualified,
it is false for the known keys, whose parsers are line-based and
fence-blind by design (main's behavior, deliberately unchanged), so a
fenced `review_ceiling_usd: 20` still configures the ceiling. The
docstring now scopes the skip to the unsupported scan and states the
asymmetry the way the README and this log already did; no code change.

**Minor 2** — the fence walk's edges were unpinned (the reviewer's
`lstrip()`-removed mutant survived the suite) and the "every fence
marker" claim was broader than the code. The walk now implements
CommonMark's fence-edge subset and the claim matches it: up to three
leading spaces, then at least three backticks or tildes, opens a fence;
the same character at at least the open fence's length, carrying no
info string, closes it; a four-space-indented marker is an indented
code block, not a fence. `test_the_fence_walk_follows_the_commonmark_subset`
pins each edge — an indented (≤3 spaces) fence skips a column-0 key
inside it, a 4-space marker does not fence, a `~~~` example is skipped
like a ``` one, a shorter or crossed-character marker does not close,
and a closing fence with an info string does not close. Four mutants
applied by hand, all killed: the indent bound dropped to column 0 (the
reviewer's F4 direction, now dead), the tilde alternative removed, the
closing rule reduced to "any marker line", and the no-info-string check
dropped. The unbalanced-fence hide vector stays as the r2 review
assessed it: disclosed, fail-open, and never a wrong value.

## 2026-11-19 — Config slice S3: the severity floor and the post's verbosity (issue #763, stacked on #769)

Config slice S3 of the user-configuration plan, implemented on the branch
stacked on #769 (the S1 parse module it consumes). The repo's `REVIEW.md`
can now say two more things the service honors: `review_severity_floor:`
raises the severity floor for posted findings (the default posts
everything — the service posts one COMMENT per head, not converging
rounds), and `review_post_verbosity:` lowers the post to its brief body.
D84 records the implementation decisions the plan left open — the read
source, the key names and the brief body's section set.

**The read source is the default branch, at post time (D84).** The floor
decides which verified findings reach the post and the dial decides
which sections it carries; a config read from a surface the PR's author
controls — the PR head, or the merge-base a same-repo or stacked PR can
carry lines onto — would let the PR suppress or quiet its own review on
the only surface a human reads. So both keys sit in the admission-class
window: the service fetches the default-branch `REVIEW.md` at post time
(the payload that named the branch is long gone by then, so the fetch
recovers the branch with one read-only lookup), bounded by the same
64 KiB, and parses it through `repo_config.parse_post_config` — the S1
module's schema, so the file's grammar lives in one place. The
merge-base reads neither honor nor name the two keys, and the
unsupported scan knows them (the known set grows to eight), so a repo
that sets them draws no false unsupported note — the same cohesion the
admission keys' cross-check pins.

**The floor's tier rule carries over unchanged (D81 Q3).** A
below-floor finding from a preference-tier lens is held in the draft
and named by the count the post's Findings section carries — the
section names the hold the way it names the 65,000-character cut, so an
emptied list cannot read as a clean review. A finding from one of the
manifest's five `tier: floor` lenses (`picker.FLOOR_TIER`) is posted at
any severity under any floor, and a line the finding-line parse cannot
classify is kept — the floor suppresses only what it can see. The
overlay's `acknowledge` rule carries over with it; the service reads no
overlay today, so the floor is the only suppression this post path
applies. The floor's coverage cost is stated in the README the way
`review_skip_events`' is (D81's 4:54 PM CT context): a below-floor
preference-tier finding lands in the draft only, and a human reading
only the post does not see it.

**The brief body lowers only.** `review_post_verbosity: brief` drops
the lens bookkeeping (Lenses run, Lenses not run, Lens decisions) and
the Cost section, and keeps the Findings section, the coverage note,
the Limit stops, and a delta review's resolved and carried sections —
the finding-bearing record a brief post must not silently drop. The
Findings section and the coverage note are never suppressible at any
verbosity, and the dial's closed set (`full`, `brief`) is what pins
lowering-only: there is no value above `full`, so no setting can make
the post more verbose than the body the service already sends.

**The post is honest about its own shape.** When a floor or a brief
dial took effect — or a line failed open — the post names the key that
did it, and every value a line of the post names is schema-validated.
An unusable line fails open per key (the keys independent, the way the
admission read's are), its note naming the key, the condition and the
default that stands and never the rejected value; a fetch that fails,
times out or reads a file over the bound leaves the default standing —
the protective direction, since a lost read can only make the post more
complete, never less — with the gap on a `post config` telemetry event,
and the post is never held for it. The source the wrapped publisher
hands the poster is lazy, so an already-posted head spends no read.

**Tests** (`atlas_reviewer/tests/test_repo_config.py`,
`test_service_run.py`, `test_service_post.py`,
`test_service_receive.py`; each behavior a test that fails when
reverted, each mutant applied by hand and killed): the closed sets and
fail-open notes (per key, the independence, the scan cohesion, the
never-echoed value), the finding-line parse on the real `render_draft`
output (the tags bracket's severity — first tag, or the tag after the
carried tag's word — and the lens parenthesis, with the decoy-anchor
pin over a location and a finding text that both carry `(word):`
sequences), the floor's partition (at-or-above kept, the tier
exemption, the unclassifiable kept, the held count), the post (the key
named, the held count in the section, the emptied section not clean,
the brief body's drops and keeps, the unchanged default body), and the
service wiring (the fetcher's branch recovery and bound, the source's
fail-open and gap telemetry, the timeout, the lazily wrapped
publisher). The three S1 tests that used `review_severity_floor:` as
their example unknown key move to `review_round_cap:` — the key is
supported now, which is the point.

**Overlap.** #757 (D82) touches `service_post.py`, which this slice
also edits — `render_comment` (a new optional `post` parameter, the
settings lines appended to the head, the tail's brief selection),
`_findings_section` (a new optional `held` parameter and its
named-hold branches) and `ReviewPoster.post` (the lazy source read
after the dedupe checks) — kept additive for the rebase; `service.py`
gains the post-config fetcher, the per-post source and the publisher
wrapper beside the admission reader's. The plan's S3 row named
`service_run.py` and `service_post.py`; the read lands in `service.py`
because the parent's GitHub-reading machinery (the read-only client,
the bounded call, the telemetry) already lives there — disclosed here
rather than claimed away.

## 2026-11-19 (same day) — #770 round 1: the layer restacked onto #757, and the two post-truths composed

PR #757 (D82) merged six minutes after the S3 head was committed, and #769
was rebased onto it (new head `538d1e53`); the restack
(`git rebase --onto`, per the fix brief) conflicts exactly where the r1
review said it would — `service_post.py`, where #757's `incomplete`
parameter and `elif` branch meet the S3 `held` parameter and branch in
`_findings_section`. docs auto-merged (the decisions log's and the
session log's appends landed cleanly; D84 sits after D82/D83 in number
order and the decision guard passes against the new base).

**The composition, the fix brief's calls (recorded as a Correction after
D84).** The Findings section carries both parameters, and **incompleteness
wins the empty section**: the stronger claim is never hidden, so on an
incomplete review the incomplete note displaces the bare cut and hold
notes and the cut count and the held count fold into it — no combination
of cut, hold and incompleteness leaves the section reading as a plain
`None.` — while a complete review's cut and hold notes stand as each
slice wrote them. And the brief dial's "Lenses not run" drop is
**brief-aware**: an incomplete brief post keeps the section, because
PR #757's banner and its Findings note point the reader there by name; a
complete brief post still drops it as bookkeeping.

**Tests** (`test_service_post.py`, `test_service_receive.py`): the three
interaction tests the brief named — brief+incomplete (the section kept,
the banner present, the bookkeeping still dropped), floor+incomplete with
every finding held (the incomplete note first, the held count folded in),
floor+incomplete+brief (all three at once, both pointed-at sections
render) — plus the complete-review twins (the cut note alone; the hold
note alone), so the precedence is pinned from both sides. The r1 Minor's
two surviving mutants are dead: `test_serve_installs_the_post_config_
wrapper_and_the_post_honors_it` drives serve → worker → poster end to end
with a fetcher and kills the wrapper-installation deletion;
`test_the_poster_reads_its_post_config_source` (and the already-posted
laziness pin) kills the source-ignoring `post`. **Mutants applied by
hand this round, all killed:** the two r1 survivors, the incomplete-brief
"Lenses not run" drop, the held-beats-incomplete order, the cut-then-hold
fold dropped, and the held_clause dropped from the incomplete note.

**The nits.** Nit 1 — the cut-and-hold corner names the held count (the
held clause folds into the cut note). Nit 2 — the wrapper's
three-argument call is typed: `PostPublisher`, a protocol whose third
parameter is optional, so a strict two-argument publisher passed to
`serve` with a fetcher is a type error at the call site, not a
`TypeError` on every post. Nit 3 — the README names the per-post cost:
two uncached read-only calls per post attempt under the App installation
token, bounded by the same 8-second read budget, spent after the poster's
dedupe checks.

Offline only, same rules as the entries above.

## 2026-11-18 — #734 part 1: the bridge can execute — structured `run_tests` and `mutate` (D80)

Part B of the 2026-11-13 plan's phase 2, the slice the parity gate's four
execution-Minors (#661 m3/m4, #640 m1/m2) were waiting on. The model now
names a test selector or a mutant spec — a path, a line and one of two
closed-set operators — and the bridge builds the argv: `<trusted
interpreter> -I -B -m pytest -q --color=no -p no:cacheprovider
<selector>`. The interpreter is resolved before any PR content is
unpacked by probing the pyenv versions and the system python for one
whose pytest imports, accepted only on `interpreter.trusted_path`'s
shapes or a literal candidate the caller named (the tests name this
machine's venv as that candidate). Every call stages a fresh disposable
copy of the HEAD tree, runs in it, and removes it, so the BASE/HEAD
trees stay read-only whatever the tests write; a `mutate` call runs the
baseline first, applies the mutation with one fixed AST script, commits
the mutated copy at the moving `refs/tags/atlas-mutant` ref — the
mutated tree is reachable at exactly one new revision, and MUTANT
resolves *at the ref*, which is what made the `update-ref`-dropped
mutant die — then runs the mutated copy. The verdict is the
controller's, from the runs' exits and its own parse of the final
pytest summary lines: survived only on a baseline that ran a test and
passed plus a mutated run that passed; every other shape is
inconclusive with its reason, and an inconclusive mutant is never a
survived one. Caps: 8 run and 8 mutant calls per attempt (below the 64
call cap), 60s per run, 16 KiB of tail-shown output per run — all
provisional pending the owner. The operator-approval allow-list is
designed as a seam (the bridge-owned argv table) and not built, per the
owner's call. Tool schemas ship with the tools (`tool_schemas` builds
from the bridge's table, so `rev`'s enum gained MUTANT); the
instructions sentence, the attempt counters and the status line's runs
and survivors counts are the next slice, then the parity rerun. Tests
in `test_bridge_runs.py` run the tools for real through `LocalSprites`
against a fixture suite executed by this machine's interpreter, plus
scripted framing tests and pure verdict tests; thirteen hand-applied
mutants each die on a named test (listed in D80). No live model, Sprite
or GitHub call; no secret read; no deployed setting changed.

## 2026-11-18 — #734 part 2: the loop counts what executed, and the draft says so

The stacked slice that closes #734: the execution tools reach the lens
loop's instructions (one shared paragraph for the paged and shared-prefix
variants, so the two cannot drift), and the attempt's counts ride the
outcome the way `changed_files` does. `_tool` counts a `run_tests` call
that came back with a run and a mutant whose verdict was survived onto
the `_Progress`; the outcome carries `test_runs` and
`mutants_survived`, the ledger round-trip reads both back, and the
status line sums them over the lenses as `test_runs` and
`mutants_survived`. An inconclusive mutant adds `TOOL_GAP` — an
execution gap a review cannot approve over, the same rule a failed or
timed-out run already rode; a failing suite is a result, not a gap, and
still counts as a run. The plan's Status header now records Part B as
implemented with D80, phase 5's parity rerun still open (and outside
the issue's scope). Four counting tests run real pytest through
`LocalSprites`; the status-line test sums over three lenses; the
round-trip pins the two new fields.

## 2026-11-18 — #753 round 1 fixes: the counting layer's pins, and the folds carry the counts

The protocol review's verdict was COMMENT with no Major: two Minors and
five Nits, all in the layer this PR owns. The two Minors were pinning
gaps, not behavior: the lens-loop side of "a failing suite is a result,
not a gap, and still counts as a run" had no test of its own (the
bridge side's pin is #752's), so a gate that counted only passing runs
would have passed this layer's whole suite — the new
`test_a_failing_suite_still_counts_as_a_run_and_not_a_gap` runs a
failing suite through the loop and pins the count and the absent gap;
and the `_EXECUTION` instructions paragraph was unpinned, so dropping
it from either prompt layout left the suite green — the anti-drift
test's shared-sentence list now carries the paragraph's four key
sentences. The Nits: the stop fold that carries a held finding across a
follow-up's tool work now refreshes `test_runs`/`mutants_survived`
beside the tools and turns it already refreshed (the fold whose
follow-up never ran keeps the held counts, with the reason stated); a
Byok refusal's exception carries the counts beside the turns and tools,
and the ledger line the coordinator finishes with them records the
executions the attempt had already made; the duplicated assertion was
deleted (the second copy added nothing), and the rule it gestured at — a
mutate call is not a run_tests run — stays pinned where it really lives,
in `test_a_survived_mutant_counts_and_is_not_a_gap`'s
`outcome.test_runs == 0`; the misleading test name now
names what it tests; D80's Update names `_outcome_json` as the writer
and `_outcome_from` as the reader; and the status line's sums are
documented as the head's recorded executions, not what this review paid
for — a reused lens's settled counts are real executions at this same
head (D73's evidence stays at the head it belongs to). Five new
hand-applied mutants over the fixes, each dead on a named test. The
MD018 session-log fix had already landed at `07207c4d`.

## 2026-11-18 — #752 round 1: execution copies come from the object store, and MUTANT reads are hash-checked

The round's Major (the routine's Blocker) was real and the review's
probes proved it end to end: executed PR code — the same user that owns
the review state — re-pointed `refs/tags/atlas-mutant` at a forged
commit (the next `read_file` at MUTANT served the attacker's file),
replaced `trees/head` wholesale (the next `mutate` staged, mutated,
committed and quoted the attacker's content as the head file's), and
deleted `trees` (the next call mislabeled the shell's exit as a test
result). The round-1 fix then leaned on what the probe read as
survival: forging a loose object **at its SHA** looked rejected by git's
read-path hash check, so commit-id-addressed reads looked sound.
*(Rejected by the round-2 entry below — git does not re-verify a loose
object on read — and the re-stage from the controller-held tarballs is
what closes it.)* The fix takes the
strongest option that fits the fakes and the `LocalSprites` seam — no
new users, mounts or binaries, only git plumbing the staging already
trusts. Every execution copy is now staged **from the bare repository's
objects** (`read-tree <recorded HEAD commit>` + `checkout-index
--prefix`; the invocation names the bridge root as its work tree only to
satisfy the bare-repository check, and writes nothing there), so `trees`
is never read after staging and nothing executed code replaced can
change what a later call stages; each staging step's exit is its own
`__ATLAS_STAGE__` block, and a copy that could not be built is an
`unavailable` gap, never a test result. MUTANT resolves at the
**recorded commit id** — the ref stays as bookkeeping and is honestly
demoted: the `update-ref`-dropped mutant is no longer observable and
left the mutant list. A `mutate` call stages a fresh copy between the
baseline and the mutation (the baseline's writes carry into neither the
mutated run nor the mutant commit), and the mutation edit is a span
splice (the rest of the file stays byte-identical; the record quotes the
mutated span). Owned rather than hidden: executed code can still take
the session's availability hostage (recorded as gaps), and a
process-group-escaping daemon could race the edit→commit pair inside one
exec — the same in-band trust boundary the exits already carry. The
round's other findings: exit 0 with no summary line is inconclusive on
both verdict sides; shape errors are gaps, not a latent `ValueError`;
the mutation step's stderr is surfaced redacted; rejected calls spend no
execution slot; exit 4's reason is honest; the chmod test skips under
uid 0. The review's two probes became regression tests
(`test_executed_code_cannot_tamper_with_what_later_calls_trust`,
`test_the_baseline_runs_writes_do_not_carry_into_the_mutant`); seven new
mutants, each dead on a named test. No live model, Sprite or GitHub
call; no secret read; no deployed setting changed.

## 2026-11-18 — #752 round 2: the object store is not a source of truth — the re-stage from the tarballs

The round-2 routine review rejected the round-1 fix's premise with a
re-run: **git does not re-verify a loose object on read** — `cat-file`
inflates and serves it; only `fsck` and the transfer paths check ids —
so the round-1 probe's in-place overwrite of the `calc.py` blob under
its recorded name still served attacker content at `rev=HEAD`, and, once
staging had been moved onto the object store, reached the next execution
copy too. (`read_file HEAD` verified locally: overwrite the blob file
`objects/e7/1172…` in place, and the commit-id-addressed read serves the
forged bytes.) The one source of truth executed code cannot touch is the
controller's own copy of the trees. So: every execution call — and every
read that follows one (`_suspect`, set by any execution, cleared by a
clean re-stage) — now **re-stages the runner's repository, trees, scratch
and staging indexes from freshly re-uploaded, digest-checked tarballs**
(`restage_script`): the staged commits are deterministic (fixed identity
and date), so the recorded BASE/HEAD ids must come back exactly, and a
mismatch is a gap; a recorded mutation re-applies deterministically on a
fresh copy and the mutant commit is re-created with the same id, checked
against the record, so MUTANT keeps serving the mutation the record
names. The digest checks close the upload-to-verify window (a daemon
rewriting the uploaded tarball stops the staging — pinned against a
recompressed-equivalent tarball only the digest can see); the
re-created-id check turns a daemon winning the edit→commit race into a
refused read, not a forged record (pinned with a scripted daemon that
writes into the copy between the edit and the commit). The stale-index
trap this uncovered on the way: a re-stage that kept the staging index
files let `git add`'s cached stat entries (the tarballs' fixed mtimes)
skip re-hashing, and `write-tree` then failed on blobs the fresh
repository had never received — the rebuild removes them. Executed code
deleting the repository no longer takes the session hostage: the next
call rebuilds and runs the real tree. Both review rounds' attacks live
in one regression fixture (the forged ref, the replaced `trees`, the
in-place object overwrite, twice); six more mutants die on named tests.
No live model, Sprite or GitHub call; no secret read; no deployed
setting changed.

## 2026-11-18 — #752 round 2 fix: the between-call daemon loses — controller-side content reads, and a verified sweep before every re-stage and execution

The round-2 review's Blocker (Brandon's round-3 thread, reproduced
independently by the reviewer's probe): a PR test spawns a daemon
detached from its exec's process group (`start_new_session=True`); the
daemon outlives every exec and every re-stage and re-forges the
`calc.py` loose blob every 20ms, so a read that came after its own
successful re-stage still served the forgery, and the next execution ran
the daemon's tree. The re-stage closes every timestamped tamper; it
cannot close a window against a process still alive when the rebuild
ends. The owner's decision: both halves, no owned residual. (1) The
file-content reads moved to the controller: `read_file`, `grep` and
`list_files` answer from the controller's own extraction of the tarballs
it already holds (`_tree_files`), MUTANT from the recorded mutation's
splice applied to that copy (`_splice`, the controller-side form of
`MUTATION_SCRIPT`, parity pinned by
`test_the_controller_splice_matches_the_runner_script`); they never exec
(`test_the_content_tools_answer_without_the_runner` pins it against a
runner that refuses every exec). The diff trio still reads the runner's
repository — its integrity rests on the sweep plus the finding gate's
controller-held quotes, and that reliance is recorded, not hidden. (2) A
stray-process sweep (`Session.sweep`) precedes every re-stage and every
execution: the live sweep kills every process of the execution user
except the exec chain's own ancestors (a `/proc` walk of `PPid` to init;
zombies skipped), waits, verifies with a second scan, and fails closed
on a survivor (`parse_sweep` → `BoundaryError` → `unavailable`). The
uid scope on a real Sprite is reasoned from the single-review
disposable-runner model and has NOT been observed on a live Sprite (the
offline rules forbid the observation); the LOCAL sweep is the testable
stand-in and is scoped differently of necessity — the test machine's
other work shares the uid — so `LocalSprites` sets
`PR_SET_CHILD_SUBREAPER` (every orphan its execs leave becomes a direct
child of the runner process), reaps, kills its descendants, reaps again,
and fails closed (`test_the_sweep_kills_a_runner_descendant`,
`test_the_sweep_fails_closed_on_a_survivor`). Neither sweep keys on the
environment, so a daemon that scrubs its own environment is inside the
live sweep's uid scope and outside no layer. The daemon probe is the
regression test
(`test_a_detached_daemon_cannot_reach_a_later_read_or_run`): reads, the
diff and the next execution all genuine after the daemon's run — and it
fails at the pre-sweep head (`85c101ed`, three consecutive runs) and
passes at the fixed head (six). The sweep mutants die on it (the
executions' sweep dropped, the re-stage's sweep dropped — the diff then
serves the daemon's forgery); the controller-side dispatch's mutant dies
on the no-exec test; and F2's second staging finally has a carrier that
flips the verdict (the old one was satisfiable by the detection path;
M-E now dies). F12: the two comments claiming git verifies a loose
object on read are corrected to name what actually protects the
content — the re-stage and the re-created-id check. No live model,
Sprite or GitHub call; no secret read; no deployed setting changed.

## 2026-11-18 — #752 round 3 fix (part two): the regex `grep` mode stays on the runner

The round-3 daemon fix moved all three content tools controller-side in
one stroke, and the round-3 review's Major showed what that overreach
broke. Python `re` in-process on the controller has no wall-clock bound —
the tool's `timeout_s` stopped applying to anything, and a
catastrophic-backtracking pattern over PR-controlled bytes (the PR
controls both the haystack and, by injection, the pattern) stalls the
review unboundedly; `re.compile("(")` crashes the call on a common model
typo, where the runner path had turned a bad pattern into git's exit
status and a gap; and the dialect silently changed — `git grep -E` is
POSIX extended, `re` is Perl-style, so the same `regex: true` pattern
matches different text than every grep before the local path served.

The fix is the review's fourth option: only the fixed-string mode is
answered controller-side (a substring scan is linear, cannot crash, and
means exactly what `git grep -F` means), and the regex mode is
dispatched back to the runner's `git grep -E` exec — where `timeout -k`
bounds the engine, a bad pattern is git's exit status with the reason in
the redacted stderr (`FAILED`, a gap — pinned by
`test_an_invalid_regex_grep_is_a_gap_not_a_crash`), and the dialect is
unchanged. The regex exec rides
the same protections the diff trio rides — the sweep precedes the
re-stage `_exec` runs on a suspect session, and a finding quoting its
output still verifies against controller-held head content — so
"nothing read back from the runner is trusted as content" now scopes to
the fixed-string content tools, and the runner-reading channels rest on
the sweep plus the quote gate. Killed mutant: the routing revert dies on
`test_a_regex_grep_stays_on_the_runner_and_keeps_its_dialect` (`to.al`
matches under `git grep -E` but not as a literal substring; two grep
execs counted; the runner script's `timeout` asserted). The tool
schema's `regex` description names the dialect (in the stacked #753).
No live model, Sprite or GitHub call; no secret read; no deployed
setting changed.

## 2026-11-18 — #753 round 2 fixes: the boolean-count rejections pinned, and the regex schema names its dialect

The round-2 review approves the counting layer, with one Minor and one
nit. The Minor: the round-1 entry said the duplicated assertion "became
the check it was meant to be" — it was deleted, and the rule it
gestured at (a mutate call is not a run_tests run) lives where it
always did, in
`test_a_survived_mutant_counts_and_is_not_a_gap`'s
`outcome.test_runs == 0`; the entry now says that. The mutant the
review named (M12, the ledger reader's explicit boolean-count check —
needed because `True` is an `int` in Python, so the isinstance gate
alone would pass a boolean) is now pinned:
`test_a_boolean_count_in_the_ledger_is_abandoned` feeds a boolean
ledger line for `test_runs`, `mutants_survived` and `changed_files`
and asserts `ABANDONED` for each. The restack onto #752's round-3 fix
keeps the counting layer in step with the controller-side content
reads and the regex-grep split: the `BridgeResult` shape is unchanged
and the lens contract held with no edits. And the tool schema's
`regex` argument description now names the dialect the bridge pinned on
the #752 branch — "a POSIX extended regex (git grep -E's dialect), not
a fixed string; an invalid regex is a gap" — so the model's `regex:
true` calls mean what the runner's git grep will do with them. No live
model, Sprite or GitHub call; no secret read; no deployed setting
changed.

## 2026-11-19 — Config slice S5: the merge-base `REVIEW.md` re-ranks the diff's paths, ordering only

The user-configuration plan's S5 (`docs/plans/2026-11-18-user-configuration.md`
§5 S5, §3's path row; the decisions are D81's Q6 -- ordering-only until
Q25 decides whether anything may be excluded from review at all -- and
Q5's no-PR-level-overrides). Offline only: the tests use fakes, the
shipped fixture and the real CLI's dry run; no live model, Sprite or
GitHub call was made, no secret was read, and no deployed service
setting, Fly config value or secret changed.

**Three new keys, one job.** `repo_config.py` (D81's S1 parse module)
gains three merge-base lines: `review_path_include:` and
`review_path_exclude:` -- comma-separated path patterns in a glob-lite
grammar (`*` and `?` over letters, digits, `/`, `_`, `.`, `-` and space,
case-insensitive like the tier match, `*` crossing `/` per fnmatch;
bracket classes outside the grammar, at most 32 patterns of at most 200
characters) -- and `review_generated_files:`, a two-word enum
(`deprioritize` or `normal`). All three join `_KNOWN_KEYS`, so a repo
using them draws no unsupported-key note, and the parse stays additive
and narrow: one new `PathRanksRead` record on `RepoConfig`, one window
(`review_md_path_ranks`), the over-bound and no-file branches extended,
the known keys' line-based parsers (fence-blind, main's behavior)
unchanged.

**The application is `diffs.py`, and it only ever re-orders.**
`diffs.PathRanks` carries the parsed values; `rank_files` splits the
files into three groups -- include-matched first, the unranked rest
between, the deprioritized last (an exclude match beats an include
match; an explicit include beats the generated heuristic) -- each group
in risk order, so the output is a permutation of the input and nothing
else about the selection changes. `is_generated` is the setting's
path-shaped heuristic (build and tool-output directories, vendored and
dependency trees, lockfiles, common generated-code suffixes); it reads
no content and a repo's own patterns override it. `rerank_note` builds
the draft's record: what each applied setting deprioritized, the paths
quoted as data (`describe_by_risk`, at most 25 named and the rest
counted), the statement that no file was dropped, and never a pattern --
patterns are author-controlled text and only their validated effect on
the order is reported.

**Where it applies.** The agentic path (`agentic-review`): `cli.py`
threads the parsed ranks into `review_lenses`, whose every lens job's
first turn lists the changed files in the ranked order (the header says
the ranking, not "highest risk first", so the model is never told a
lie), and `_review_lenses` attaches the rerank note beside the ceiling
note, scrubbed at render like the selection note. A changed file is
still listed, still held to every lens, still counted for coverage --
ordering and depth only. The one-shot `review` command fetches no
merge-base tree and reads no repo config today (the pre-S1 state), so
it runs on the risk order alone; that is stated in the README rather
than papered over. A seen-but-unusable ranking line rides the same
surface the lens lines' unusable note does: `_with_preference_note`
appends `config.ranks.note` to the selection note.

**Tests** (`test_repo_config.py`, `test_diffs.py`,
`test_coordinator.py`, `test_cli.py`; each behavior a test that fails
when reverted): the three lines parse (valid, tight, commented, the
`normal` default, dedup in file order), fail open at every edge (bad
charset, bracket classes, the cap, a repeated key, an unknown generated
value, values never echoed), the combined read carries the rank read,
the new keys never draw an unsupported note, and the over-bound note
names them; `rank_files`' group order, precedence and permutation
(nothing dropped -- Q25 untouched, pinned), case-insensitive matching,
the generated shapes and their negatives; the note's wording, its cap,
its silence when nothing ranks, and its refusal to carry a pattern;
`first_turn`'s ranked header and unchanged default, the note in a
rendered draft, the multi-lens entry point threading ranks into the
lens jobs; and two end-to-end dry runs -- the recorded re-ranking and
the unusable line's named note, each with the review running clean.

**Mutants.** 26 applied by hand, all killed: the known-key entry
dropped, the pattern charset loosened, the cap removed, the
duplicate-key refusal dropped, the unknown-generated-value refusal
dropped, the unusable note emptied, the dedup removed, the bad read
returning ranks anyway, matching made case-sensitive, the exclude-over-
include precedence swapped, the generated branch removed, the minified
shape dropped, the middle group dropped, the note always emptied, the
note cap raised past bounding, the no-drop clause dropped,
`applies` forced False, the note echoing the patterns, the ranked header
not stated, the ranking not applied in `first_turn`, the note not
attached, the ranks not passed to the lens jobs, the ranks not threaded
from the CLI, the scaffold measured without the ranking, and the
unusable note not surfaced. (M6 was not applied: the note builder never
receives a rejected value, so the no-echo rule has no mutant to kill.)
One process note: applying M20 by hand and restoring with
`git checkout -- coordinator.py` wiped the uncommitted slice work; the
edits were re-applied and re-verified (mypy, ruff format, the targeted
suites) before continuing -- the lesson recorded here so the next
mutant is restored from the in-memory original, as the gauntlet script
does, never from HEAD.

**Overlap.** No open PR touches `diffs.py` (the D79 delta work touched
`delta.py` and `head_change.py`; #759/#760's delta redesign has not
started on it). #770 (S3) edits `repo_config.py`'s post-config keys and
`service_post.py`/`service_run.py`/`service.py` -- this slice's
`repo_config.py` change is additive (one record, one window, three
known keys), so the rebase against it stays mechanical, and no
`service_*` file is touched. #752/#753 (D80) touch the bridge files,
not these. Q25 stays open and untouched; the plan document was not
edited.

## 2026-11-19 (same day) — #772 round 1: the note tells the truth about an exclude-overridden include, and D85 records the S5 decisions

The r1 review's verdict was APPROVE with three Minors and one Nit; the
rebase onto `cc96c26c` (S3's #770 merged after this branch's first push)
came first. All five conflicts were mechanical, resolved keep-both: the
`repo_config.py` import block (`PathRanks` beside `Severity`) and its
`_KNOWN_KEYS` set (the three S5 keys beside S3's two post keys, the list
still in key order), the README's admission key-list paragraph and
`repo_config.py` module-table row (both now carrying S3's post-window
sentence and S5's key list), and the session-log and
`test_repo_config.py` appends (S3's post-keys tests, then S5's
path-ranks section — the decisions list stays append-only in number
order, D85 appended after D84's correction).

**Minor 1 — the note's include sentence is now true under overlap.**
When `review_path_include:` and `review_path_exclude:` name the same
paths, exclude wins (D69's rule carried to paths), the front group is
empty, and the note used to say "ranked nothing: none of this diff's
file(s) match its patterns" — false, and a false record next to a
correct exclude sentence breaks the summary-agrees rule. The note now
distinguishes the two ways a front group can be empty: no pattern
matched (the old sentence, unchanged and pinned for that case), or
patterns matched and the exclude rule took the matches — "ranked nothing
ahead: its N matching file(s) were deprioritized by
review_path_exclude". `test_the_rerank_note_is_true_when_exclude_took_
the_includes_matches` pins the overlap case, and the no-match case is
pinned beside it so the two wordings cannot drift into each other.

**Minor 2 — the README states the coverage cost.** The path-ranking
section now says what deprioritizing actually costs, the way
`review_skip_events`' cost is stated: on the paged path a lens chooses
its own reading order and the ranked listing nudges it, so under a lens
budget that cannot read everything the deprioritized files are the first
candidates to be left unread — surfacing as the loud, non-approvable
incomplete-coverage state (D36), never a silent drop — and a repo
deprioritizing its riskiest paths should expect more incomplete reviews,
not quieter ones.

**Minor 3 — D85.** The S5 implementation decisions the plan left open
are recorded as D85 in `open-questions.md`, after D84's correction
(S3's precedent for exactly this class): the key names, the glob-lite
grammar and its caps (32 × 200, the charset, bracket classes outside),
the exclude-over-include and include-over-heuristic precedence with
risk-ordered groups, the path-shaped generated heuristic, the merge-base
read source, and the one-shot command's config-free state.

**Nit — the grammar example now matches.** The comment's `dist/` became
`dist/**` (a no-wildcard pattern must match the whole path exactly, so a
bare directory prefix matches nothing), and the README's grammar
sentence says the same.

Offline only, same rules as the entries above; the full gate re-run on
the rebased tree (both suites with the coverage floors, ruff, mypy,
drift, markdownlint), and the r1 mutant set re-run plus the new
overlap-wording mutant, all killed.
