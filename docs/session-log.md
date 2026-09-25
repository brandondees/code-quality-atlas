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
arrives. D9 now points forward to D23. `docs/distribution.md` pointed at a "D9
addendum" that never existed; it now points at D9 and D23.

**#520 → half-month rotation.** September alone had pushed this file to about
2,080 lines before the month closed, so the "oldest completed month" rule had
nothing it could move. The header rule now allows splitting an overrunning
month at day 15. Applied immediately: 2026-09-01 through 09-15 moved verbatim
into [`session-log-2026-09-01-to-15.md`](session-log-2026-09-01-to-15.md),
checked lossless by rebuilding the original from the archive plus the live
file. The live file dropped to about 400 lines. `CLAUDE.md`/`AGENTS.md`'s
orientation text now says the log carries 2026-09-16 onward and mentions the
half-month case.
