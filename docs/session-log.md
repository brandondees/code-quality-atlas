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
