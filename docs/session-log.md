# Session Log

Chronological record of how the research evolved. Newest at the bottom.

**Rotation policy (#467, 2026-09-08):** this file previously grew
unboundedly (append-only since repo creation, 5,173 lines with no split)
until it was the single largest file in the repo. Going forward: once this
live file's entries exceed roughly 1,500 lines, extract the oldest
completed calendar month(s) verbatim into a new
`docs/session-log-<start>-to-<end>.md` archive file (named by the range of
months it covers) and replace them here with nothing but this pointer
update — no summarizing, no trimming, matching how
[`eval-hardening-campaign-log.md`](eval-hardening-campaign-log.md) was
already extracted from `open-questions.md` (#426). The first rotation split
out June–August 2026:
[`session-log-2026-06-to-08.md`](session-log-2026-06-to-08.md). This file
carries September 2026 onward.

---

## 2026-09-01 — Q22 Phase 1 shipped: the standing-dispute check

A fresh session opened with "what's next?" and worked the repo's own
orientation docs rather than starting from a named task. `docs/open-questions.md`'s
"Genuinely still open" list had shrunk to two items: **Q21** (the eval-hardening
campaign), confirmed resolved for the current lens catalog per its own
resolution note and the 2026-08-24 session-log entry hardening the last lens
(`auditing-deployment-and-trust-boundaries`) — still open only for extending
the A-E pattern to any new lens or shape added after this pass; and **Q22**
(does the atlas's own
review pass execute the checks it cites), which already carried a
decision-ready, owner-gated design doc — [`executing-cited-checks.md`](executing-cited-checks.md),
drafted 2026-08-22 — proposing a small, reversible Phase 1. Asked the owner
whether to build it; approved.

**Shipped Phase 1 (M1 — the standing-dispute check).** Added one paragraph to
`synthesizing-review-findings`'s `## Reviewer discipline` section, generated
from `tooling/generate_synthesizer.py`'s `build_synthesizer_md` (the same
function `generate_collapsed.py` reuses for every collapsed entrypoint's
bundled `reference/synthesis.md`, so one edit reached both surfaces with no
manifest schema change — exactly the doc's own recommended home and
mechanism): before affirming any claim not independently re-derived, scan the
PR's existing comment threads and prior review rounds for a standing dispute
of that exact claim; treat a disputed claim as unresolved rather than
settled, without flipping to "the disputing comment is automatically right"
either. Added 3 meta-review eval scenarios to
`skills/synthesizing-review-findings/evals/eval.json` (already above D8's
3-scenario baseline at 9, now 12) in the transcript-input shape the design
doc's own "how would we know it worked" sub-question anticipated: a direct
reconstruction of PR #253 (the sharpest recorded instance — a confident
positive affirmation of an S3 canned-ACL claim already disputed by a standing
comment ~90 seconds earlier), a precision check that the discipline doesn't
invent phantom disputes on a finding nobody ever contested, and a boundary
check distinguishing a *resolved* historical objection (superseded by a
later fix and a confirming comment) from a *standing* one.

Wrote the dated implementation-plan record the design doc's closing section
asked for — [`plans/2026-09-01-executing-cited-checks-phase1.md`](plans/2026-09-01-executing-cited-checks-phase1.md)
— deliberately without the full TDD/checkbox scaffolding the repo's other
plan docs use, since inventing task-by-task ceremony for a one-paragraph,
already-completed change would be exactly the ceremony cost Q22 itself warns
against. Updated `executing-cited-checks.md`'s status line and Phase 1
section, and `open-questions.md`'s Q22 entry and "Genuinely still open"
summary, to record the shipped state; Phase 2 (M2, falsification attempts on
affirmatively-applied greppable rule classes) stays owner-gated pending
Phase 1 producing signal and a non-self-authored instance, unchanged from
the design doc's own phasing.

**Verification:** `python -m tooling.cli generate` (regenerated the
standalone skill and all four collapsed `reference/synthesis.md` bundles),
`tooling/vendor-skills.sh .` (re-vendored this repo's own 44 lenses),
`tooling.cli drift` (no drift — this skill is `built_from: []`, so drift
tracks manifest/generator changes, not research-section hashes),
`tooling.cli eval --skill synthesizing-review-findings` (12/12 scenarios
valid), `pytest` (451/451), `markdownlint-cli2` (0 issues) on the touched
files. No cross-model re-gate this session (design doc frames Phase 1's
evidence bar as "produces signal," not a pre-ship hardened-floor gate — see
the plan doc's own note on this).

## 2026-09-01 (same day, follow-up) — #351: vendor the CC BY license text into account-skill zips, not just a link

`tooling/package-account-zips.sh`'s `write_attribution()` shipped only a
`NOTICE.md` linking back to `LICENSE-CC-BY-4.0` on GitHub. `tooling/
vendor-skills.sh` got the equivalent fix for
`brandondees/second-brain-config#1157` (PR #341), but that PR only touched
the vendor-skills.sh channel — `package-account-zips.sh`'s own header and
inline comments still claimed the two channels "mirror" each other, which
stopped being true. Worse for this channel than for #1157: an uploaded
account-skill zip is extracted into a claude.ai account skill with no
ongoing relationship to this git repo at all, so a dead or unreachable link
would be the *only* copy of the license terms that skill will ever have.

Vendored `LICENSE-CC-BY-4.0` into every staged skill directory before
zipping, updated the `NOTICE.md` wording and surrounding comments to match,
and added regression tests mirroring `test_vendor_skills.py`'s coverage for
both the standalone and `--collapsed` paths.

**Verification:** new regression tests covering both packaging paths; no
generated-tree change (packaging-script fix only).

## 2026-09-02 — #359: dual-encode round/ack state so it survives HTML-comment stripping

`pull_request_read` had been observed stripping HTML comments entirely from
returned review/comment bodies, so a round-state protocol relying solely on
the invisible `<!-- atlas-review round:N -->` marker (and
`<!-- atlas-review-ack -->`) could silently undercount: a resumed or
restarted session reading back its own prior reviews would see no markers,
conclude it's round 1, re-post the ACK, and potentially re-raise findings a
human had already settled in an earlier round. Closed #355 and addressed the
actionable (repo-side) portion of #354 — the underlying `pull_request_read`
behavior itself is Claude Code/GitHub-MCP tooling this repo doesn't control.

Made the visible signal primary instead of an afterthought: every
round-posting review now opens with a visible `## Round N — ...` heading as
its first line, in addition to (not instead of) the existing HTML-comment
marker; the ACK comment now also carries the literal visible phrase "atlas
reviewer engaged" alongside its marker, with detection checking for either
signal; round-derivation logic in `atlas-review-pr.md`, `atlas-poll-and-
review.md`, `atlas-rebase-stale.md`, and the routine prompts embedded in
`docs/runbooks/pr-review-automation.md` all updated to parse the heading
first, falling back to the marker only where the heading is absent. Three
review rounds on PR #359 followed: a Copilot pass caught the "past review
summaries carry both" wording overstating the guarantee (reworded to say
only reviews posted by the updated command going forward are guaranteed
dual-encoded); a CodeRabbit finding caught the poller's round-1 ack branch
triggering on ack-absence alone rather than also checking round count (a PR
with an already-missing-or-unreadable ack but existing round reviews could
get a spurious "round 1" re-ack); an atlas review finding caught
`REVIEW.md`/`templates/REVIEW.md` still describing the ACK's visible phrase
as mere illustrative wording, with no mention of the heading-first/
marker-fallback rule, despite being the canonical copy other repos vendor
and what `atlas-review-pr.md` step 3 treats as authoritative when present;
and a CodeRabbit finding caught the Model B poller's own ack-posting
instruction still saying to post only the invisible marker, missed when the
rest of the PR updated every other ack-posting site. Three further
CodeRabbit findings (no reviewer-identity binding on ACK/round detection,
the ack-as-lock pattern not being atomic, "unreadable" collapsing into
"absent") were knowingly deferred to #360.

**Verification:** clean CI, atlas round-2 APPROVE, no author-stated hold;
`REVIEW.md`/`templates/REVIEW.md` kept byte-identical per
`test_review_template_sync.py`.

## 2026-09-03 — #364: stop writing raw `tool_input` and absolute `transcript_path` into the committed learnings log

The 2026-09-03 whole-repo audit (#347) raised #364 (Major, security):
`hooks/log-skill-invocation.sh` recorded the Skill tool's `tool_input`
verbatim and `hooks/queue-session-retro.sh` recorded the full, absolute
`transcript_path` — both into `.code-quality-atlas/learnings/*.jsonl`, which
D17 commits to the consumer repo on the stated grounds that stage-1 records
are "abstracted at creation" (self-improvement-loop.md §5,
templates/preferences-template.md §7's ratified reason line). Only
`docs/install.md` described the actual behavior honestly, as "the raw
tool-input payload." The design promise and the shipped hooks disagreed, and
nothing tied them together.

Picked the issue's option (a) — implement the abstraction — over (b)
striking the promise from the docs, since the design's own privacy-boundary
rationale (D17: local records safe to commit because abstracted, not
because never pushed) depends on it actually holding, and a length + digest
is a strictly better signal for stage 2's future analysis pass than a
capture-or-nothing choice between raw payloads and no invocation evidence at
all. `hooks/log-skill-invocation.sh` now writes `tool_input_len` (byte count
of the compact JSON) and `tool_input_sha256` (its SHA-256 digest,
`sha256sum`/`shasum -a 256`, whichever is present) instead of `tool_input` —
neither needs to know the Skill tool's still-undocumented `tool_input` inner
shape, so the original reason for storing it verbatim (avoid guessing a
field name) survives untouched. `hooks/queue-session-retro.sh` now writes
`transcript_basename` (`.transcript_path | split("/") | last` in jq) instead
of `transcript_path`, dropping the OS username/`$HOME`/project-layout
leakage the issue named. Re-synced `collapsed/hooks/` (byte-identical to
`hooks/` for these two generic scripts per existing test coverage).

Updated every surface that described the old (or the promised-but-false)
shape: `docs/self-improvement-loop.md` §3.1's revisited-assumption note and
a new §5 paragraph naming the two fields precisely (so a future edit can't
quietly reintroduce raw capture without also touching prose that names the
opposite), `docs/install.md`'s "what `local` writes" paragraph,
`docs/open-questions.md`'s D17 entry, and `templates/preferences-template.md`'s
ratified example reason and a new retention note (the issue's third ask —
stage 1 ships no rotation/expiry for the JSONL files; documented as a
prune-periodically hygiene expectation rather than a mandated window, since
nothing in the design needs a specific one). Updated
`tests/test_hooks.py`'s two logging-shape assertions to match (they
previously *enforced* the old raw shape) and added
`tests/test_learnings_abstraction_sync.py` — the sync test the issue asked
for, in `test_review_template_sync.py`'s shape: asserts the hook scripts
never reference the raw fields and do reference the abstracted ones, and
that the design doc/install doc/template keep naming the actual shape
rather than the old promise-only language.

**Verification:** manual end-to-end runs of both hooks against sample
PostToolUse/SessionEnd payloads (confirmed `tool_input_len`/`tool_input_sha256`
match an independent `sha256sum` of the same compact JSON, and
`transcript_basename` strips a synthetic absolute path correctly),
`pytest` (460/460, up from 454 — 2 updated + 6 new in the sync-test file),
`tooling.cli drift` (clean), `tooling.cli generate` (no output diff —
these two hooks aren't manifest-generated, so this confirms nothing else
drifted), `markdownlint-cli2` (0 issues on the touched docs).

## 2026-09-03 — #366: `pip install --require-hashes` verified nothing already-installed on the persistent runner

The same audit (#347) raised #366 (Major, security): `ci.yml`'s
`pip install --require-hashes -r requirements.txt` ran with no venv and no
`--force-reinstall` on `runs-on: [self-hosted, Linux]` — a *persistent*
runner (`docs/self-hosted-runners.md`), so any pin already sitting in
site-packages from a prior job was "Requirement already satisfied" and its
hash never checked at all. Reproduced locally before touching anything: with
`ruff==0.16.5` already installed in a venv, a requirements file pinning it
with a hash of 64 zeros still made `pip install --require-hashes` exit 0.
The workflow's own comment at the time claimed the opposite twice — that the
step "verifies every hash in the committed lockfile against the artifact it
downloads" — which is also wrong on its own terms even ignoring the
persistent-runner gap: pip only ever downloads and checks the one artifact it
resolves for the running job's platform, never the hashes listed for other
platforms' wheels on the same requirement line (reproduced with a forged
`pyyaml` hash: the forged hash for a non-selected wheel survives both the
install and the pip-compile consistency diff below it).

**Fix.** Create a fresh `python -m venv --clear "$RUNNER_TEMP/venv"` per job
and install into that with `--require-hashes`, then append its `bin/` to
`$GITHUB_PATH` so every later step in the job (the `requirements.txt` sync
check's `pip install pip-tools`, the `pip-audit` step, `ruff`, `pytest`,
`tooling.cli`) transparently resolves `pip`/`python`/`ruff`/`pytest` to the
same fresh environment without editing each step individually. `--clear` is
defense in depth beyond what the issue's suggested fix used, in case a
self-hosted runner's `$RUNNER_TEMP` is ever not wiped between jobs the way a
hosted runner's is guaranteed to be — cheap, and removes any doubt about the
one property (nothing pre-installed) this fix depends on. Rewrote the
requirements-sync step's comment to state the actually-true, narrower
guarantee: hash integrity for the platform this job runs on is the
`--require-hashes` step's; `.in`/`.txt` consistency is the sync step's;
cross-platform hash coverage is neither's — matching the two corrections
the issue asked for exactly.

**Verification:** reproduced the original bug in a scratch venv (already-
installed `ruff` + a 64-zeros forged hash → `pip install --require-hashes`
exits 0), then reproduced the fix closing it (same forged hash against a
`python -m venv --clear` target → pip correctly reports a hash mismatch and
exits 1) — both before editing `ci.yml`, so the fix is verified against the
actual failure mode rather than assumed from reading pip's docs.
`python -c "import yaml; yaml.safe_load(...)"` on the edited workflow file
(valid YAML), `pytest` (468/468, unaffected — no test reads `ci.yml`'s pip-
install step specifically), `tooling.cli drift` (clean), `markdownlint-cli2`
(0 issues; `ci.yml` itself isn't Markdown but nothing else changed).
No generated-tree or Python-source changes, so `tooling.cli generate` and
`ruff check` are unaffected by construction — this is a single-file CI
workflow edit.

## 2026-09-03 — #377: `vendor-skills.sh --prune` path traversal via the target's `.atlas-vendored` marker

The same audit (#347) raised #377 (Major + Minor): `main()` in
`tooling/vendor-skills.sh` read every non-comment line of the *target*
repo's committed `.claude/skills/.atlas-vendored` marker into `OLD_NAMES`
with no validation, and `--prune` ran `rm -rf "${dest_root:?}/$old"` for any
entry not in the current skill set. Reproduced before touching anything: a
marker line of `../../src` printed "pruned stale: ../../src" and deleted
`<target>/../src` — a real directory one level above the target repo, from
a file the tool's own header calls "generated, do-not-hand-edit" and a
maintainer reviewing a PR is likely to skim rather than read closely. The
same untrusted `OLD_NAMES` also fed `vendor_one`'s #175 collision check, so
a planted *real* skill name could re-grant `rm -rf` over a non-tool-managed
directory without `--force`.

**Fix.** `is_bare_skill_name` accepts a marker line only if it matches the
manifest's own name shape (`a-z0-9-` only, non-empty); anything else —
`../../victim`, an absolute path, a future field an older copy of this
script doesn't understand — is dropped with a warning before it ever
reaches `OLD_NAMES`, rather than after. `confirm_child_of_dest_root` adds a
second, independent check right before the `--prune` delete: the target's
resolved parent directory must actually be `dest_root`, so a future edit
that weakens or removes the marker-line validation still can't delete
outside the tree this tool owns. Verified the fix against the exact
reproduction, real filesystem, no mocks: planted `../../src` (a real
victim directory containing a file) into a target's marker, ran `--prune`,
confirmed the victim survived untouched and the malformed line was warned
about and dropped from the rewritten marker — then confirmed the same
setup against the pre-fix script actually deletes the victim, so the test
proves the fix closes the reproduced bug rather than merely not opening a
new one.

Also closed the Minor UX/provenance gaps the same finding named: a refresh
with no `--prune` now prints a one-line notice naming any stale
(withdrawn-from-the-suite) names still on disk and pointing at `--prune`,
rather than silently re-listing them in the marker forever with no
indication anything was stale; added `--dry-run`, which reports what would
be vendored/pruned/skipped without writing, deleting, or overwriting
anything (verified: running it against both a fresh and an
already-vendored target leaves the filesystem byte-identical, mtimes
included); `check_target_git_state` warns (never aborts — a legitimate
target, e.g. a test scratch dir, may not be git-tracked) when the target
isn't a git working tree or has uncommitted changes under `.claude/skills/`
before a `--prune`/`--force` run, so there's a version-control safety net
to notice is missing; copied `package-account-zips.sh`'s existing
unresolvable-SHA warning (this script had the same silent `@unknown`
NOTICE.md gap that sibling script already guards against) and added two
more in the same spirit — the *source* repo's own tree must be clean for
the stamped SHA's provenance claim to hold, and the SHA should be reachable
from a remote-tracking branch or the NOTICE.md's GitHub blob link 404s;
and a `# format=N` marker header the reader checks, warning (not failing)
on a mismatch — a secondary, explicit signal alongside `is_bare_skill_name`,
which is the actual safety net against a newer marker field confusing an
older copy of this script.

Declined scope creep on two adjacent asks the issue's fix list didn't
actually make: rewriting `--dry-run` to also simulate `write_attribution`'s
output content (the "would vendor" report already names every affected
skill; a byte-for-byte NOTICE.md preview added complexity for a case
`--dry-run`'s own stated purpose — "touch nothing, report what would
happen" — doesn't need), and adding a `--yes`/confirmation prompt on
`--prune` (not requested, and this is a scriptable CLI tool meant to run
non-interactively in the same breath as `--dry-run`'s whole point of
letting a maintainer preview first).

Added `tests/test_vendor_skills.py` coverage for every piece: the
traversal reproduction itself (both with and without `--prune`, since
`OLD_NAMES` feeds the collision check too, not just the prune loop),
`--dry-run` writing nothing (fresh target) and changing nothing (already-
vendored target, `--prune` case included), the stale-names notice, the
format-header write and mismatch warning, the git-state warnings (dirty,
non-git, and the clean/no-warning case), and direct unit tests of
`is_bare_skill_name` and `confirm_child_of_dest_root` themselves (the
latter unreachable through `main()`'s own flow today, which is exactly why
it needs standalone coverage rather than only integration coverage).
Updated the existing prune-guard test pair
(`test_prune_guard_expression_matches_script`,
`test_prune_rm_guard_aborts_on_empty_dest_root`) to match the guard's new
shape — moved from inline in the `rm -rf` call to a separate `target=`
assignment shared with the new parent-resolution check.

**Verification:** manual end-to-end reproduction of the bug and the fix (see
above) with real files in a scratch directory, `pytest` (487/487, up from
472 — 30 tests in `test_vendor_skills.py`, up from 12), `ruff check` (clean),
`shellcheck --source-path=SCRIPTDIR -x` on the edited script (clean, same
pinned v0.10.0 CI uses), `tooling.cli drift` (clean; no skill content
changed). `docs/distribution.md`'s Channel B section updated to describe
the marker's trust boundary and `--dry-run`.

## 2026-09-03 (same day, follow-up) — #377 PR review round: forged-marker ownership gap, plus a merge conflict from #398

Two things landed on the #377 PR (#400) after it opened. First, a genuine
merge conflict: #398 (an unrelated `--with-lens-coverage-hook` feature)
merged to `main` in between and touched the same two files
(`tooling/vendor-skills.sh`, `tests/test_vendor_skills.py`). Resolved by
merging `main` in and combining both feature sets by hand — kept #377's
marker validation/`--dry-run`/warnings and #398's hook-vendoring call,
gated the latter behind `DRY_RUN` too (a gap neither PR's own diff had
covered, since `--dry-run` didn't exist when #398 was written) so
`--dry-run --with-lens-coverage-hook` together also touch nothing.
Re-verified everything end to end after the merge, including that specific
combination, before pushing.

Second, and more important: Copilot and CodeRabbit both independently
caught a real gap in the #377 fix itself — one the original issue text had
actually already named ("The #175 collision check also trusts the marker,
so a planted real skill name re-grants `rm -rf` over a non-tool-managed
directory without `--force`") but the first round of work only partly
closed. `is_bare_skill_name` stops a malformed *shape* (a traversal
segment) from reaching `OLD_NAMES`, but a well-formed, falsely-claimed
marker line — a real skill name the marker lists as previously vendored,
for a directory this tool never actually touched — still satisfied both
`vendor_one`'s collision check and the new `--prune` loop on name-match
alone. Reproduced against the pre-this-round script: a hand-authored
`checking-restraint/` directory (no generated-marker comment, i.e. never
really vendored) plus a marker forging that claim let a plain refresh
silently `rm -rf` and overwrite it with real content — no `--force`
needed, no warning, exactly the #175 protection the marker-trust bug was
supposed to still have.

**Fix:** `is_tool_vendored_skill_dir` checks for independent evidence a
directory really is this tool's own output — its `SKILL.md` carries the
exact generated-marker comment `append_generated_marker` writes, which
nothing else has reason to write. Both `vendor_one`'s collision check and
the `--prune` loop now require the marker *and* this real-content check
before treating a directory as tool-owned; `--force` still overrides
either path, unchanged. The `--prune` loop's marker-rewrite bookkeeping
was adjusted to match: a stale name skipped (not actually deleted) because
it failed the ownership check now stays recorded in the marker rather than
being silently dropped as if it had been pruned.

Also fixed, from the same review round: Copilot's wording finding that the
git-state warnings undersold the risk to only `--prune`/`--force`, when an
ordinary refresh already `rm -rf`s and recreates every tool-owned skill
directory — reworded both warnings to name the real, broader risk. The
atlas reviewer's own round added two Nits: a vacuous `assert
"MOCK_RM_CALLED" not in result.stderr` in a unit test that never exercises
a code path calling `rm` at all (removed, since the real proof is already
the returncode/message assertions beside it); and a correctness note about
`confirm_child_of_dest_root` aborting mid-`--prune`-loop potentially
leaving the marker unrewritten after some stale dirs are already deleted
— accepted as-is per the reviewer's own "very hard to trigger, not
blocking" assessment (the guard is unreachable in practice once
`is_bare_skill_name` already rules out anything that could mismatch).

Added `test_forged_marker_name_does_not_bypass_the_collision_check_on_refresh`
and `test_forged_stale_marker_name_does_not_authorize_prune_deletion` —
both reproduced against the pre-fix script first (confirmed the forged
name really did bypass protection) before confirming the fix closes them.
One existing test
(`test_warns_when_target_has_uncommitted_skills_changes`) needed adjusting:
its dirty-file simulation replaced a `SKILL.md`'s entire content, which
incidentally erased the generated-marker comment and started tripping the
new ownership check too — switched to appending instead of replacing, so
it exercises only the git-dirty warning it's named for.

**Verification:** reproduced both forged-marker attacks against the
pre-fix script (confirmed real, not theoretical) before fixing, then
confirmed the fix closes both; `pytest` (511/511, up from 487 — includes
PR #398's own 12 tests merged in plus 2 new forged-marker regressions and
one adjusted test); `ruff check .` (clean); `shellcheck --source-path=SCRIPTDIR
-x` across the full `tooling/`, `hooks/`, `collapsed/hooks/` trees with the
same globstar/dotglob flags CI uses (15 files, clean); `tooling.cli drift`
(clean); `markdownlint-cli2` (clean).

## 2026-09-03 — #362: the unattended reviewer could resolve a human reviewer's own thread

The 2026-09-03 whole-repo audit (#347) raised #362 (Major, security, lens
`reviewing-agentic-safety`): `mcp__github__resolve_review_thread` is granted
to the atlas reviewer (`commands/atlas-review-pr.md:15`,
`commands/atlas-poll-and-review.md:13` for the subagent it spawns) with no
ownership scoping in the instructions that call it —
`commands/atlas-review-pr.md`'s step 6 said "if a prior thread was already
addressed by a later push, resolve it," `REVIEW.md`/`templates/REVIEW.md`
said "resolve any threads the new push addressed," and the
`pr-review-automation` runbook said "resolve threads that later pushes
addressed" — all three keyed the decision on the agent's own judgment that a
push addressed the thread, never on who opened it. In the Model B
(poll-driven) design this runs from an unattended, scheduled subagent, so it
could close a *human* reviewer's still-open thread on its own say-so, and on
a repo that gates merge on resolved conversations that silently clears the
gate out from under them — adjacent to but distinct from #360's identity
binding of the ACK/round markers.

**Fix:** scoped resolution to threads whose first comment's author matches
the reviewer's own login. `commands/atlas-review-pr.md` step 6 now has the
reviewer establish its own identity via `mcp__github__get_me` (reusing the
call step 5 already makes for the own-PR fallback rather than calling it
twice), read each candidate thread's first comment author via
`mcp__github__pull_request_read`'s `get_review_comments` method, and resolve
only a thread whose first comment it posted itself — a thread opened by
anyone else gets at most a reply (`add_reply_to_pull_request_comment`)
noting which push addressed it, never a resolve. Swept all three other
copies the issue named (`REVIEW.md`, `templates/REVIEW.md` — kept
byte-identical per `test_review_template_sync.py` — and the runbook) to the
same "your own threads only" language, plus the "already approved, still
nothing new" bullet in `commands/atlas-review-pr.md` step 5, which had the
same unscoped instruction.

Added `tests/test_review_thread_resolution_scoping.py`: asserts none of the
four files still carry the exact unscoped phrasing the issue quoted
(normalizing whitespace so a harmless re-wrap can't defeat the check),
asserts all four keep the "your own" scoping language, and asserts
`atlas-review-pr.md` names the actual mechanism (`get_me`,
`get_review_comments`, "first comment") rather than leaving "your own
threads" as unenforceable prose. Verified the test fails against the
pre-fix content first (stashed the fix, confirmed all four checks catch the
regression, then restored it) before trusting it as a real regression
guard — these are prompt-instruction files with no interpreter to run them
against, so the sync/phrasing test is the only mechanical check available.

**Verification:** reproduced the gap by reading the unattended-agent
instructions as the agent itself would follow them (confirmed the
unscoped "resolve any threads the new push addressed" language was
actually reachable, not just visually present) before fixing; new
regression test confirmed to fail on the pre-fix text and pass on the
fix; `pytest` (515/515, up from 511 — 4 new); `markdownlint-cli2` (clean,
490 files); `ruff check .` (clean); `tooling.cli drift` (clean).

## 2026-09-03 — #360: ACK/round detection had no identity binding, no atomic lock, and collapsed "unreadable" into "absent"

CodeRabbit's review on PR #359 (the #354/#355 comment-stripping fix)
surfaced three related, pre-existing gaps in the round/ACK detection
protocol shared by `commands/atlas-review-pr.md`,
`commands/atlas-poll-and-review.md`, `commands/atlas-rebase-stale.md`, and
their restatements in `docs/runbooks/pr-review-automation.md`. Filed as #360
rather than folded into #359 (a narrow, low-risk doc fix) since these
three span up to five locations across four files, each with more than
one viable design, and getting the trust model wrong under a rushed
documentation-only PR would have been hard to catch pre-merge.

1. **No reviewer-identity binding (Major, spoofing/DoS).** Every detection
   site treated *any* issue comment carrying the ack marker/phrase, or
   *any* review opening with a `## Round N` heading, as authoritative
   regardless of who posted it — a PR author or other collaborator with
   comment access could post a fabricated ACK to suppress the real one, or
   a fake high-round review to inflate the round count past what actually
   happened.
2. **The ACK "post it as a lock" pattern wasn't atomic (Major, race
   condition).** "Check for no ack, then post one" is a read-then-write
   race over a non-transactional API; two sessions acting as the same
   reviewer identity (the event-triggered reviewer and a poller sweep both
   watching the same PR — an explicitly supported combination per the
   runbook) could each read "no ack" before either write lands, and both
   post.
3. **A review with neither readable signal collapsed into "no round," not
   "unreadable" (Major).** Indistinguishable from a review that genuinely
   predates any round, so a corrupted/stripped signal would silently
   restart the loop at round 1 (re-raising settled findings) or silently
   drop out of coverage checks.

**Fix, all three, applied consistently across the four files:**

- **Identity binding:** each detection site now calls
  `mcp__github__get_me` once (cached per session/sweep) and filters every
  ack/round candidate to `author.login == that login` — a signal from
  anyone else, however formatted, is never authoritative.
  `atlas-review-pr.md` establishes this in step 2 (moved earlier so
  round-counting, the ACK check, step 5's own-PR fallback, and step 6's
  #362 resolve-scoping all reuse one call instead of re-deriving it);
  `atlas-poll-and-review.md`'s top-level session calls it once per sweep
  and threads the login into each triage subagent's prompt (subagents
  can't share session state, so re-deriving per subagent would be
  wasteful and, worse, is exactly the kind of duplicated logic that
  drifts); `atlas-rebase-stale.md` needed `mcp__github__get_me` added to
  its `allowed-tools` grant, since it never needed identity before.
- **Atomic lock:** replaced the naive check-then-post ACK with a
  primitive GitHub actually enforces atomically —
  `mcp__github__pull_request_review_write` method `create` with no
  `event` opens a *pending* review, and GitHub allows only one pending
  review per identity per PR at a time, so a concurrent `create` under
  the same identity fails outright instead of racing. A failed `create`
  means stand down (someone else is mid-ACK); a successful one means the
  session holds the lock, re-checks for an existing ACK (now
  authoritative), posts if still absent, then **always** releases via
  `delete_pending` — including on a failed post, since a stuck pending
  review would permanently block every future ACK attempt on that PR.
  Applied to `atlas-review-pr.md` step 2, `atlas-poll-and-review.md` step
  3, and both of the runbook's inlined restatements (Model A's watch loop
  never posts an ACK past round 1, so only Model B's embedded sweep
  needed this — the resident reviewer's first-round ACK is entirely
  delegated to `atlas-review-pr.md` itself, not duplicated in the
  runbook's prose).
- **Tri-state round detection:** a third state, `unknown`, distinct from
  both "round 1" (zero prior reviews from the expected identity — still
  legitimate) and any specific N: one or more prior reviews from the
  expected identity exist but none parses a heading or marker. On
  `unknown`, `atlas-review-pr.md` stops and posts a comment naming the
  ambiguity rather than guessing; the two pollers (`atlas-poll-and-review.md`,
  `atlas-rebase-stale.md`, and the runbook's Model B sweep) skip
  escalating/reviewing that PR for the current cycle and flag it in their
  summary report for human attention, rather than silently treating it as
  covered or uncovered.

Added `tests/test_ack_round_identity_binding.py`, mirroring
`test_review_thread_resolution_scoping.py`'s (#362) prose-guard shape
since these are agent-instruction files with no interpreter to run them
against: asserts every file still cites issue #360 and calls `get_me`,
still names an `unknown` round state, that the three ACK-posting surfaces
(the two commands plus the runbook — `atlas-rebase-stale.md` never posts
an ACK, so it's excluded) still carry the `delete_pending` release half of
the lock, that `atlas-rebase-stale.md`'s `allowed-tools` line grants
`get_me`, and that the identity check is actually tied to round/ack
detection specifically (not just present somewhere else in the file, e.g.
the pre-existing own-PR-fallback or #362's resolve-scoping use). Verified
against the pre-fix content (checked out all four files at their pre-#360
state) that every one of the six checks fails as expected.

**A process note for future sessions:** verifying the regression test against
pre-fix content the first time around overwrote the working files with
`git show`'s output for the pre-fix commit, then ran `git checkout` on those
same paths to "restore" them. Since the fix was still uncommitted, that
checkout restored from HEAD (the pre-fix commit), not from the uncommitted
fix — silently discarding it.

Caught immediately by re-running `pytest` (which started failing against
files that should have passed) and `git status` (a clean working tree when
uncommitted edits should have shown as modified — the tell). Recovered by
re-applying every edit from this same conversation's own record of them.
The safe pattern (used successfully in the #362 and #377 verification
passes) is stashing the paths first and popping them back after the check,
never a raw overwrite followed by a plain checkout, whenever the content
being restored is still uncommitted.

**Verification:** reproduced the conceptual gap by reading each detection
site's unfiltered logic as the unattended agent would actually follow it
before fixing; new regression test confirmed to fail against the pre-fix
content on all six checks and pass on the fix (after the recovery above);
`pytest` (521/521, up from 515 — 6 new); `markdownlint-cli2` (clean, 490
files); `ruff check .` (clean); `tooling.cli drift` (clean).

## 2026-09-03 (same day, follow-up) — #360 PR review rounds: a self-inflicted destructive race, then a real body-marker fix

Three further review rounds on #360's own PR (#402), each finding a real gap
in the previous round's fix — `tests/test_ack_round_identity_binding.py`
grew from the 6 tests above to 13, in three steps (+2, +1, +4); the counts
below are each round's own delta, not the file's running total.

**Round 1 (the atlas reviewer, Major):** the ACK lock added above had a
known-and-acknowledged failure mode with no recovery path — if the session
holding it dies between `create` succeeding and `delete_pending` running
(container reset, `/compact`, reclaim), the lock orphans, and every
backstop (poller, self-nudge) shares the same reviewer identity, so none
could route around it; the PR would silently stop being reviewed forever.
Fixed by having the independently-scheduled pollers (`atlas-poll-and-review.md`,
`atlas-rebase-stale.md`, both runbook restatements) detect and self-heal
it: `pull_request_read`'s `get_reviews` method returns the caller's own
pending review even though it's otherwise invisible to anyone else, so a
`PENDING` review under your own identity older than 30 minutes was treated
as almost certainly stuck and cleared with `delete_pending`. Also fixed a
smaller, related finding: a `create` failure was uniformly read as
"someone else has the lock," silently swallowing real errors (permissions,
rate limits) under the same branch as ordinary contention — now
distinguished. Added `test_pollers_recover_a_stuck_ack_lock` and
`test_create_failure_distinguishes_contention_from_a_real_error`.

**Round 2 (the atlas reviewer, Major):** round 1's recovery couldn't
distinguish `atlas-review-pr.md`'s short-lived step-2 ACK lock from its own
step 5's much longer-lived pending review for building up a round's inline
findings — `get_reviews` shows both identically as "a `PENDING` review
under your own identity on this PR." A poller sweeping mid-review during a
long round (the same event-triggered-reviewer-plus-poller-sweep
combination #360 itself is about) could delete an actively in-progress
review's collected findings — a new, self-inflicted failure mode likely
*more* common in practice than the orphaned-session case round 1 fixed,
since it needs no crash, just an ordinary review that runs long. Fixed by
narrowing auto-recovery to the one case that's actually unambiguous: a
findings review can only ever open after the ACK issue comment already
exists, so a stale `PENDING` review is now only auto-cleared when the ack
is **absent**; when the ack is present, a lingering `PENDING` review is
only flagged in the report, never auto-cleared. Added
`test_stuck_lock_recovery_never_blindly_clears_an_in_progress_review`,
verified to fail against the round-1 commit.

**Round 3 (CodeRabbit, several Major):** ack-absence and age alone still
weren't judged a safe enough signal on their own — a manually deleted ack
comment, both ack signals lost to the #354/#355 HTML-comment-stripping bug,
or read-after-write lag could all make an in-progress findings review look
ack-absent to the recovery pass. Fixed by having every ACK lock create its
pending review with `body` set to the literal marker `(atlas-ack-lock)` — a
direct, load-bearing signal recovery now requires as a third, independent
condition alongside ack-absence and age. CodeRabbit also caught: (a)
`get_reviews` returns the caller's own not-yet-submitted `PENDING` review
(confirmed via GitHub's own REST API docs), which every round-derivation
site was counting as "a review with no parseable heading," wrongly tripping
`unknown` during the lock's hold window — fixed by excluding `PENDING`
reviews from round derivation everywhere; (b) `atlas-rebase-stale.md` said
to check for a stuck lock "once per sweep, not per PR" — backwards, since a
pending review is scoped per-PR per identity, so this would have left every
PR but the first unchecked — fixed to check every open PR; (c)
`atlas-poll-and-review.md`'s "ack 90+ minutes old → crashed, respawn"
branch could spawn a second review subagent while the first was still
legitimately building a large round — fixed to check the recovery pass's
own ambiguous-lock flag first and skip respawning when set; (d)
`atlas-rebase-stale.md`'s report claimed nothing goes to GitHub beyond
pokes and `delete_pending`, omitting the coverage escalation's review
re-requests — fixed the claim. Declined one Trivial finding asking for
fully ordered, section-scoped test assertions in place of the substring
checks used throughout this file and `test_review_thread_resolution_scoping.py`
(#362): the file's own docstring already states these are best-effort
drift tripwires for prose files with no interpreter, not runtime proof, and
the atlas reviewer's own round-1/round-2 reviews independently validated
the anchoring as adequate; a full rewrite is disproportionate to a
Trivial-severity nitpick given the added parsing complexity it would need.
Added `test_ack_lock_is_created_with_a_body_marker`,
`test_recovery_matches_the_body_marker_before_clearing`,
`test_round_derivation_excludes_pending_reviews`, and
`test_rebase_stale_lock_recovery_checks_every_pr_not_once_globally`,
verified to fail against the round-2 commit.

**Verification (round 1):** `pytest` 523/523 (521 + 2 new),
`ruff`/`markdownlint-cli2`/`tooling.cli drift` clean.

**Verification (round 2):** reproduced the destructive scenario by reading
the round-1 recovery logic against a hypothetical long-running review;
`pytest` 524/524 (523 + 1 new), `ruff`/`markdownlint-cli2`/`tooling.cli drift`
clean.

**Verification (round 3):** confirmed via GitHub's REST API docs that
`PENDING` reviews are returned by the list-reviews endpoint to their own
author; `pytest` 528/528 (524 + 4 new),
`ruff`/`markdownlint-cli2`/`tooling.cli drift` clean.

## 2026-09-04 — #393: research/comment accuracy sweep (128-tool cap, RuboCop rename, Pylint default, picomatch, two stale comments)

Six independently-verified inaccuracies from the whole-repo audit (#347),
each checked against the tool's own current docs/source rather than taken
on the issue's word:

1. `artifact-scoped-lenses.md` claimed all three major providers "cap hard
   at ~128 tools." Confirmed via web search against each provider's own
   docs: OpenAI (128 functions/request) and Gemini (128 function
   declarations/request, per Firebase's Gemini docs) do; Anthropic
   documents no fixed cap and ships a tool-search tool for large catalogs
   instead. Rewrote as provider-specific with a citation per provider.
2. Four sites (`cluster-2-readability.md`, `map-gaps.md`,
   `taxonomy-gap-hunt-round-3.md`, `session-log.md`) credited a dev.to
   article with "AST-grounded agent interfaces"; the article never
   mentions AST or interfaces. Dropped the phrase from all four `→ mine:`
   notes.
3. `cluster-2-readability.md` cited RuboCop `Naming/PredicateName`,
   renamed to `Naming/PredicatePrefix` in 1.76.0 — confirmed via RuboCop's
   own changelog/docs. Updated the citation, kept `Naming/PredicateMethod`
   as-is.
4. Same file understated Pylint's `bad-names` default as `foo, bar, baz`;
   confirmed via Pylint's own docs the real default is `foo, bar, baz,
   toto, tutu, tata`.
5. `tests/test_ci_python_filter_covers_known_reads.py` called
   dorny/paths-filter "minimatch-backed" in two places; `ci.yml` and the
   action's own `src/filter.ts` (v4.0.3) say picomatch. Fixed both.
6. Two stale code comments: `tooling/generate.py`'s facade docstring used
   `_checklist_body` as the example of a call-based re-export that can't
   be monkeypatched through the facade — but `_checklist_body` was never
   re-exported there at all (only `_escape_table_cell` is); swapped in the
   real example. `tooling/manifest.py`'s prepass-validation comment
   contrasted itself against "the sibling blocks' `or \"\"` idiom" — that
   literal idiom no longer exists anywhere in `tooling/` (grepped to
   confirm); the sibling skill/router/synthesizer blocks now go through
   `_prose(..., null_ok=True)` instead. Reworded the comment to name the
   actual current mechanism.

Regenerated affected skills (`reviewing-agent-legibility`,
`reviewing-naming-and-readability`) and their collapsed/vendored mirrors
after the research-doc edits, per the standing authoring rule.

**Verification:** `pytest` 528/528 (the vendor-skills "clean git target"
test transiently fails against an uncommitted working tree by design — it
warns exactly because this repo, as its own vendoring source, had
uncommitted `skills/` changes; passes once committed); `ruff check` clean
on touched files (a pre-existing, unrelated `ruff format` diff in
`tooling/manifest.py` predates this change, confirmed via `git stash`);
`tooling.cli drift` clean; `markdownlint-cli2` (pinned to CI's v0.23.2) 0
issues across all 490 files.

## 2026-09-04 — #363: pr-review-automation runbook disagreed with the commands it summarizes

Standing authoring rule 2 (a summary must agree with what it summarizes),
violated three ways in `docs/runbooks/pr-review-automation.md`:

1. Model B's write-up said "One subagent per PR needing one; run them
   concurrently" for the review-subagent spawn step. The command it
   summarizes, `commands/atlas-poll-and-review.md`, caps concurrency at 5
   subagents in flight at once across the whole sweep, batched in groups of
   5 — the opposite of unbounded. Since `/atlas-poll-and-review` doesn't
   resolve in routine sessions, the runbook's inlined copy is what an
   operator actually builds the routine from, so the contradiction would
   ship an uncapped fan-out. Replaced with the same cap, cross-referenced to
   its source.
2. Setup §2 (the Model A poller routine) carried Trigger/Cadence/Model/
   Connectors/Prompt bullets but no Permissions bullet, unlike §1 and §4.
   Added one, phrased around what §2 actually writes (comments, reviews,
   review re-requests, and `update_pull_request_branch`) rather than
   repeating the "never pushes a commit" framing issue #387 separately
   flags as understating that same API call.
3. "Known boundaries" was entirely reliability framing (what can silently
   stop working) — nothing named which identity the routines act as, what
   they can write, that a PR under review carries untrusted content, or the
   blast radius of a multi-repo sweep. Added a new "Accepted risks / trust
   boundaries" section, modeled on `docs/self-hosted-runners.md`'s
   "Accepted Risks" shape (deliberate trade-offs recorded explicitly,
   not solved), naming the GitHub-App identity, write scope, the
   untrusted-PR-content boundary already enforced by `atlas-review-pr.md`'s
   base-ref pin, and the multi-repo blast radius — pointing at issue #387
   for the still-open gate on that last one rather than claiming it's
   solved here.

Added `tests/test_pr_review_automation_runbook_accuracy.py` (3 tests,
following the established prose-drift-tripwire pattern), each verified via
`git show origin/main:...` to fail against the pre-fix content before being
trusted.

**Verification:** `pytest` 531/531 (528 + 3 new); `ruff check`/`ruff format
--check` clean on the new test file; `tooling.cli drift` clean;
`markdownlint-cli2` (pinned to CI's v0.23.2) 0 issues across all 490 files.

## 2026-09-04 — #380: declare the Python floor, add a contributor setup block, gate `ruff format` in CI

Three carry-over gaps from #347: no stated Python floor, no documented setup
anywhere in the repo, and no format gate in CI.

1. **Floor.** `pyproject.toml` had no `[project]` table (so no
   `requires-python`) and no `.python-version`; five plan docs (dated,
   already-implemented) claimed "Python 3.11+" while `ruff`'s
   `target-version`, `requirements.txt`'s pip-compile header, and CI's own
   matrix all say 3.12. Chose **3.12** as the stated floor — matching
   what's actually tested, rather than adding an untested 3.11 CI matrix
   entry purely to keep the older plan docs' claim technically true. Added
   `requires-python = ">=3.12"` under a new `[project]` table (ruff's own
   pyproject parser requires `name`/`version` once `[project]` exists at
   all — RUF200 — so both are stubbed with a comment explaining this isn't
   a distributable package) and a `.python-version` file; corrected the
   five plan docs' `Tech Stack` lines to 3.12+.
2. **Setup docs.** Neither `AGENTS.md` nor `CLAUDE.md` documented a build/
   test/lint command anywhere (confirmed by grep — verified the issue's
   own claim before trusting it). Added a `## Development setup` section
   to the shared-orientation block both files carry (kept in sync by
   `test_shared_orientation_matches_across_agent_files`, so one edit
   covers both): venv, `pip install -r requirements.txt`, the
   test/lint/format/drift commands, and an explicit repo-root-required
   note — verified by reproducing the `ModuleNotFoundError` from `/tmp`
   the issue described. Pointed `docs/runbooks/regenerating-skills.md` at
   it as a stated prerequisite instead of assuming an already-set-up
   environment.
3. **`ruff format --check` in CI.** The "one line" the issue described
   turned out to need real scoping work first: `ruff format .` reformats
   fenced Python code blocks inside Markdown by default (a real ruff
   feature, not a bug), which would have touched every skill's
   hand-authored `examples.md`, every generated `collapsed/**/body.md`,
   and the `.claude/skills/` vendored mirror — fighting the
   generation/vendoring pipeline (those files' content is owned by
   `tooling.cli generate` / `vendor-skills.sh`, not by hand-formatting)
   and turning a one-line CI change into a 130-file diff touching content
   this fix has no business deciding the formatting policy for. Added
   `extend-exclude = ["*.md"]` under `[tool.ruff]` to scope `ruff format`
   to Python source only, matching what `ruff check` already implicitly
   covers; formatting-policy-for-example-code-blocks is left as a
   separate, undecided question. With that scoped, ran `ruff format .`
   once repo-wide (45 `.py` files, all mechanical whitespace-only diffs,
   verified by `git stash`-comparing behavior before/after) and added a
   `format (ruff)` step next to CI's existing `lint (ruff)` step, same
   `if:` gate.
4. **Type checker.** The issue's remaining ask — adopt a type checker on
   `tooling/` or record the decision not to — recorded as **D19** in
   `docs/open-questions.md`: not adopted for now, reasoned explicitly
   (cost of adoption vs. what it would catch beyond the existing test
   suite + `ValidationError`-shaped runtime checks), with a stated revisit
   trigger rather than a silent "not yet."

**Verification:** `pytest` 541/541 (no new test files — the count moved
since #380 branched from a `main` that had already picked up #403's
merge); `ruff check .` / `ruff format --check .` clean; `tooling.cli drift`
clean;
`markdownlint-cli2` (pinned to CI's v0.23.2) 0 issues across all 490 files;
CI's `ci.yml` re-parsed as valid YAML after the edit.

## 2026-09-04 (same day) — #374: onboarding guardrail sent lens fixes to generated files; SKILL.md carried no visible generated marker

The do-not-touch guardrail in `CLAUDE.md`/`AGENTS.md` (the one place either
file explains where a lens fix goes) said "edit `skills/<name>/`" without
naming that `SKILL.md` + `reference/*.md` under that path are themselves
*generated* (from `skills/manifest.yaml` + `docs/research/`) — only
`examples.md` + `evals/eval.json` are hand-authored. Provenance markers were
inverted to match: every generated `reference/*.md` carries a leading
`<!-- GENERATED ... -->` comment; 0 of 44 `skills/*/SKILL.md` and 0 of 4
`collapsed/skills/*/SKILL.md` carried any visible marker (only a
machine-readable `provenance:` block in the frontmatter) — so the guardrail's
own instruction terminates at an unmarked file with no visible sign it's
generated.

Fixed the marker gap first, since it's what the guardrail rewrite depends on
being true: added `_gen_trailer()` to `tooling/generate_common.py` — the
trailing counterpart to the existing `_gen_header()`, for the two file kinds
whose YAML frontmatter must lead (so a leading comment can't be prepended).
Wired it into `generate_skill.build_skill_md` and
`generate_collapsed.build_entrypoint_md`; both now end with the same marker
text every other generated file already carries, just trailing instead of
leading. Extended `test_generate.py` and `test_collapsed.py` to assert it.

Rewrote the guardrail paragraph in both `CLAUDE.md` and `AGENTS.md`
(byte-identical, verified via `diff`) to name the real split: sources
(`manifest.yaml` + `docs/research/`), generated (`SKILL.md` +
`reference/*.md`), hand-authored (`examples.md` + `evals/eval.json`), and
mirrors one level further out (`.claude/skills/`, `collapsed/` — self-
vendored / generated respectively, never hand-edited either). Left the
`.claude/skills/icm-architect` carve-out out of this rewrite — issue #375
owns that decision and explicitly reserves it as "the owner's call," not
something to fold in here.

Extended `tooling/vendor-skills.sh`'s `append_generated_marker` to also
stamp vendored `examples.md` (previously SKILL.md-only) with a source
pointer, generalizing the marker text to take the source filename as a
parameter instead of hardcoding `SKILL.md`. This meant updating
`tests/test_self_vendored_skills_sync.py`'s comparison logic too — it had a
`SKILL.md`-specific marker-stripping branch and compared `examples.md` by
plain byte-identity, which would now always report every vendored
`examples.md` as stale; generalized `_skill_md_matches_source` into
`_marked_runtime_file_matches_source` and applied it to both `_RUNTIME_FILES`
uniformly (the dead byte-comparison branch it left behind was removed, since
the loop only ever iterates over `_RUNTIME_FILES` now).

Fixed `README.md`'s `skills/` row, which the issue's own repo-layout table
had described with no mention of the generated/hand-authored split
`collapsed/`'s row states as a matter of course.

**Verification:** `pytest` 540/540 (the vendor-skills "clean git target"
test transiently fails against this repo's own uncommitted `skills/`
changes, as its own docstring already explains — passes clean post-commit);
`ruff check .` clean (`ruff format --check .`'s 122-file-reformat backlog
predates this branch — #380's still-unmerged fix, not touched here);
`tooling.cli drift` clean; `markdownlint-cli2` (pinned to CI's v0.23.2) 0
issues across all 490 files; re-vendored `.claude/skills/` via
`tooling/vendor-skills.sh .` and confirmed the new `examples.md` markers
render correctly.

## 2026-09-05 — #375: four false claims about `.claude/skills/icm-architect` being a mirror/third-party-only directory

`.claude/skills/` is actually 44 of this repo's own self-vendored lenses
(CC BY 4.0) plus one genuine third-party skill, `icm-architect` (MIT,
vendored from `RinDig/icm-architect`, already carrying its own
`LICENSE`/`NOTICE.md`). `LICENSE`, the license-paths test,
`CLAUDE.md`/`AGENTS.md`, and `.markdownlint-cli2.jsonc` all treated the
whole directory uniformly, each wrong about the actual 44-vs-1 split:
`LICENSE` named neither bucket for `.claude/` so it fell through to the
MIT catch-all (wrong for the 44 self-vendored lenses — added a CC BY
bucket entry with a one-clause `icm-architect` carve-out);
`test_license_paths_exhaustive.py` exempted `.claude` entirely as "editor/
tool state" (it's real vendored content — removed the exemption,
classified `cc_by`); the onboarding twins' "lens fix goes into its
sources" paragraph claimed `.claude/skills/` uniformly mirrors
`skills/<name>/` (false for `icm-architect`, which has no `skills/`
source — added a one-sentence carve-out to both); and
`.markdownlint-cli2.jsonc` ignored the whole `.claude/skills/` tree as
third-party ("same category as `node_modules`" — true for 1 of 45
directories, false for the other 44, which pass the same lint rules
cleanly as a byte-for-byte copy, verified locally before narrowing the
ignore to `icm-architect` only). Also fixed `vendor-skills.sh`'s
`write_attribution()`, whose `NOTICE.md` blankly claimed CC BY 4.0 over
"the skill content in this directory" as a whole — an over-claim that
ships into every consumer repo's own non-vendored skills placed beside
the vendored ones, not just this repo's. Whether a compliance obligation
was created by any of this was left to the repo owner; these fixes only
make the documentation accurately describe the pre-existing situation.

## 2026-09-05 (same day) — #394 problem 2: placeholder personal/machine identifiers in `docs/self-hosted-runners.md`

The maintainer's OS account name (`/home/dees/...`, `usermod -aG docker
dees`) and VM names (`runner-2604`, `actions-runner-mbp`) were spelled out
directly in a file that is otherwise already placeholdered
(`<owner>/<repo>`). Replaced with `<runner-user>`, `<vm-name>`, and
`<old-vm-name>`. This file is a verbatim copy of a private sibling repo's
canonical `docs/self-hosted-runners.md` (stated in its own header), so the
durable fix is upstream, outside this session's repo access — patching this
copy stops the current public exposure immediately, and may get
overwritten on the next verbatim re-copy from the canonical, an accepted
trade-off confirmed with the repo owner rather than an oversight. Problem 1
from the same issue (whether a workflow in that private repo still uses an
unscoped API token) was left unaddressed, since verifying or fixing it
needs access to that repo.

## 2026-09-05 (same day) — #447 → D20: no lens-rename alias; a stale `preferences.md` reference is surfaced, not migrated

Owner's call on all three questions #447 raised: no alias/deprecation
window at all — a renamed or retired lens carries no migration path, ever;
a stale `preferences.md` entry (naming a lens no current manifest entry
matches) is surfaced loudly, never silently dropped or guessed at; and
`preferences.md` stays hand-authored prose, no schema, for as long as that
awareness mechanism reliably works. Built as a `choosing-review-lenses`
router instruction to report the stale directive — a round-1 review finding
(dees-bot) caught that the first version routed it through the
synthesizer's capped "Process notes" appendix, which contradicts that
section's own contract (0-3 one-liners about the review process itself,
never about the reviewed repo's state) and undercut the "surfaced loudly"
goal, since Process notes findings never enter the ranked/dedup'd output.
Reworked to report it as a normal finding instead (`location:
.code-quality-atlas/preferences.md`, `valence: defect`, `route:
implementer`). Recorded as **D20**; `templates/preferences-template.md`
states the no-alias rule up front.

## 2026-09-05 (same day) — #424: a citation-syntax convention and an automated resolution test for `docs/map/**`

The owner delegated the design call ("whatever solves the problem
efficiently is probably fine" — the map is primarily read/maintained by
agents). `docs/map/CONTEXT.md` gained a "Citation syntax" section
documenting the two forms already in informal use — `path:N`/`path:N-M`
for raw line citations, and `path::name` (pytest's own node-id syntax) for
a named anchor a plain-text search would find — with a stated preference
for the anchor form whenever the target has a namable anchor near the
cited content. `tests/test_map_citations.py` parses every citation
matching either form out of `docs/map/**/*.md` (52 found at the time) and
asserts it resolves: a `path::name` citation fails if the name no longer
appears in the target (immune to line drift by construction); a
`path:N`/`path:N-M` citation fails on a missing target or a line count
past EOF (a weaker bounds check, since it can't catch content that moved
to a different line within the same file — exactly why the anchor form is
preferred going forward). Verified the test actually catches drift by
running it against a deliberately corrupted citation before reverting.
Deliberately did not migrate the ~50 existing raw-line citations to
anchors in this pass — genuine per-file judgment, left as an opportunistic
follow-up rather than a required one-shot migration.

## 2026-09-05 (same day) — #426: restructured `open-questions.md`'s 700-line "Genuinely still open" section

The "Genuinely still open (undecided)" paragraph had grown to ~700 lines,
but only about 10 of those were actually open items — the rest was the
Q21 eval-hardening campaign's wave-by-wave narrative and a map-taxonomy
gap-hunt recap (G12-G32), both interleaved inline, so a session looking
for what's genuinely open had to read or skim all 700 lines to find the
signal. Pulled the genuinely-open items (Q24, Q22, Q21, Q17, Q13, Q6, Q8,
Q2) into a short, scannable list, each pointing to its own existing
`### Q<N>` section for full context. Moved the eval-hardening narrative
verbatim into a new `docs/eval-hardening-campaign-log.md` (the G12-G32
gap-hunt recap already had its authoritative home in `map-gaps.md`, so
that part became a pointer instead of a second copy) — nothing summarized
or trimmed, a byte-for-byte relocation. Verified first that no tooling
parses this section's heading structure. Also added the CLAUDE.md/
AGENTS.md orientation guidance on which docs are meant to be read in full
(reference-shaped: `open-questions.md`, `map-gaps.md`, `map/CLAUDE.md`)
versus read partially, filtered to what the task needs (narrative logs:
`session-log.md`, `eval-hardening-campaign-log.md`) — the same
"read fully vs. read partially" distinction this entry's own file now
follows for itself (#467, below).

## 2026-09-05 (same day) — #392: closed out the remaining three nits

Verified #392's 8 problems against current code first: six were already
resolved by earlier merged PRs. Of problem 8's nits, this pass closed the
remaining three: converted every `echo` in `tooling/keep-plugin-current.sh`
to `printf`, matching its sibling scripts' existing convention; standardized
the `ROOT`/`REPO_ROOT`/`_ROOT` naming spread across six test files to
`ROOT` (except `test_map_twins_sync.py`'s, renamed to `MAP_ROOT` since it
points at `docs/map` specifically, not the repo root); and investigated
`write_attribution()`'s apparent duplication between `vendor-skills.sh` and
`package-account-zips.sh`, found the two versions genuinely differ (one
carries a whole self-vendoring branch the other never hits), and documented
that as a deliberate no-op inline rather than force a consolidation. The
"exit-code contracts differ between the two scripts" nit was also
investigated and left as-is: `return` in helper functions and `exit` only
at `main()`/top level is the correct, deliberate bash idiom already used
consistently within each script.

## 2026-09-06 — #449: decomposed monolithic builders, deleted the dead `generate.py` facade and `--bundle`

Two remaining items from an earlier repo-structure review. `build_synthesizer_md`
(236 lines) and `build_router_md` (127 lines) were each a single string-
concatenation expression — split into `_<section>_section()` helpers,
matching the grain `generate_prepass.py` already established, verified
behavior-preserving by regenerating and diffing (zero change beyond the two
source files). `vendor-skills.sh`'s 110-line `main()` did seven jobs —
split into eight named step functions called from a thin `main()`, verified
via `shellcheck`, the full `test_vendor_skills.py` suite, and a real
self-vendor run producing a byte-identical `.claude/skills/` tree. Also
removed two dead/legacy surfaces with no real consumer: `tooling/generate.py`,
a backward-compatible re-export facade whose only callers were six in-repo
files (collapsed onto the split modules directly, facade deleted); and
`package-account-zips.sh`'s `--bundle`/`--bundle-only`, which built an
archive its own header comment already said its only named consumer (the
claude.ai Skills GUI) rejects.

## 2026-09-06 (same day) — #434: record the model digest via `/api/show`; note the mutable-tag floor-of-record risk

Split from an earlier issue's harder half, deferred out of scope at the
time. `tooling/run_evals.py` gained `query_ollama_show()`/
`resolve_ollama_digest()` (Ollama's `/api/show`), printing `MODEL: <name>`
and, for `--api ollama` only, `DIGEST: <digest-or-unavailable>` at the top
of every run — never raising on a lookup failure, so an older server or a
network hiccup can't abort a run whose scenarios would otherwise succeed.
Ollama-only, since no OpenAI-compatible server exposes a standardized
digest endpoint. `docs/runbooks/cross-model-re-gate.md` now notes the floor
of record is defined by tag (not a pinned digest), so a silent re-pull
between two re-gates could misattribute a recall/precision delta to a
prompt or suite edit — pointing at the newly-printed digest line as what to
record and diff first.

## 2026-09-06 (same day) — #347: a fresh whole-repo self-audit filed 10 tracking issues (#466-#475)

The suite reviewed its own repo again via the standard whole-repo
health-audit route (9 of the 11 repo-shaped audits applied; no
Terraform/K8s/data-pipeline surface in the tree for the other two). Outcome:
no Blocker, 6 Major and 6 Minor findings (one Minor folded into #394 as a
comment rather than filed separately), 5 Nit/advisory items, 4 opt-in
improvements. Filed as #466 (three composition-skill `SKILL.md` files ship
with no `GENERATED` marker and no drift coverage), #467 (this file's own
staleness and lack of rotation plan — the issue this entry, and the several
above it, close out), #468 (D9's commit-SHA versioning contradicted by
`plugin.json`'s added `version: 0.1.0` with no decision-log update), #469
(`open-questions.md#Q23` and the cross-model-re-gate runbook out of date
against already-shipped work), #470 (the generator core's 505-file blast
radius has no mandatory-human-review protection), #471 (the CI fork-PR
gate depends on an unverified GitHub Settings default), #472 (no
license-compatibility CI gate; `pip-tools`/`pip-audit` unhashed), #473
(a stale `pyproject.toml` comment), #474 (the new `docs/map/**` citation
test doesn't catch a stale *bare* module-name mention), #475 (CI's pip
cache key not exercised across the dual-arch fleet — later found to
already be arch-safe, see below). Bus factor of 1 across the whole repo
was re-confirmed but deliberately not re-filed, as in the prior refresh —
still a staffing call, not an engineering ticket.

## 2026-09-06 (same day, follow-up) — #473/#475: corrected a stale `pyproject.toml` comment and dropped an unnecessary CI pip cache

`pyproject.toml`'s comment describing 5 `# noqa: C901` exemptions was
stale (all 5 were already fixed; zero remained) and understated ruff's
actual default rule surface at the pinned version. Corrected both. #475's
premise — that `actions/setup-python`'s pip cache key was arch-blind
(`runner.os` only) and could silently mix incompatible wheels across the
fleet's two architectures — didn't hold once checked against the pinned
action's own source: `setup-python@v7.0.0`'s cache-key computation already
includes `process.arch`. `cache: 'pip'` was still dropped, but for an
unrelated, independently-valid reason: these are persistent self-hosted
runners, so each host's local pip cache already survives between jobs
without the network round-trip `actions/cache` would add, and the
`--require-hashes` install is already the source of correctness, not the
cache. Two round-2 review fixes on the same PR: a rule-count precision nit
(413 vs. the comment's "~415") and correcting #475's own arch-blind-cache
premise in the `ci.yml` comment once the pinned source was actually read.

## 2026-09-06 (same day, second follow-up) — #466: wired the `GENERATED` marker into the router/prepass/synthesizer builders

`choosing-review-lenses`, `grounding-review-in-tool-output`, and
`synthesizing-review-findings` are the three composition skills generated
with `built_from: []` (so the drift-hash check doesn't cover them) — but
unlike every other generated `SKILL.md`, they carried no trailing
`<!-- GENERATED -->` marker either, so neither the visible marker nor the
hash check protected them from a direct hand-edit. Wired the existing
`_gen_trailer()` helper into all three builders and regenerated.

## 2026-09-07 — #468/#469: corrected D9's versioning currency and the Q23/runbook drift

D9 (commit-SHA versioning) was contradicted by `plugin.json`'s added
`"version": "0.1.0"` (#389, 2026-09-05) with no decision-log update. Added
a D9 addendum recording the change and clarifying it did not reverse the
commit-SHA policy: `plugin.json`'s version field is a static, unbumped
marketplace-display value, while `hooks/route.sh`'s build identifier is
still resolved via git SHA specifically to avoid the drift a hand-
maintained version string would carry — confirmed directly against current
source and git history. Separately, Q23's "design that hook" follow-up
text was stale: the `hooks/lens-coverage/` scripts, their `hooks.json`
wiring, and `vendor-skills.sh --with-lens-coverage-hook` had all shipped
2026-09-03, three days before the audit that flagged it as still-open ran.
Marked shipped with pointers to the actual files. `cross-model-re-gate.md`
still named `qwen2.5-coder:7b` as the floor of record though Q21 had
already promoted `qwen3.5:4b` on 2026-08-22 — updated the "floor of
record" language and every current-instruction example command, leaving
the dated historical narrative entries as-is since they describe what was
actually run at those dates.

## 2026-09-07 (same day) — #474: catch stale bare Surfaces-table module paths in `docs/map/**`

The citation-resolution test added for #424 (above) only extracted a path
when followed by `:N` or `::name` inside the same backtick span — a bare
`tooling/generate.py`-style mention with no separator at all was invisible
to it. That's exactly the shape that went stale in practice: #449 (above)
deleted `tooling/generate.py`, but a bare Surfaces-table citation of the
old name lingered in three map cards and needed two separate manual
follow-up commits within that same PR to catch. Scoped a new check to each
card's own `## Surfaces` table specifically (a live, current-state
assertion) rather than any bare path anywhere in the file — widening past
Surfaces tables was tried and produced only false positives from dated
"Verified" trailers and same-directory relative cross-references, which
use different resolution rules. Two round-1 review findings (CodeRabbit and
the atlas round both independently caught the same gap): the heading match
was accepting any `#`-prefixed "Surfaces" at any nesting level, not just an
exact `## Surfaces`; and the new bare-path extractor had no analog of the
sibling formal-citation extractor's own unlisted-extension regression
guard. Both fixed, plus a cosmetic round-2 nit hoisting an inline regex to
a module-level constant for consistency with its sibling.

## 2026-09-08 — #467: backfilled this file's own gap and rotated out June-August 2026

This file's last narrative entry before today documented #374 (2026-09-04);
between that commit and today's `HEAD`, 12 non-merge commits had shipped
closing out 9 more distinct issues (the entries directly above this one)
with zero session-log coverage, exactly the drift #467's audit finding
described. Backfilled those entries from `git log`/`git show` on each
commit rather than from memory, then addressed the same issue's second
finding — 5,173 lines, append-only, no rotation plan, unlike its siblings
`open-questions.md`/`eval-hardening-campaign-log.md` which had both
already been split — by applying the same verbatim-extraction pattern one
level up: everything before September 2026 moved out into
[`session-log-2026-06-to-08.md`](session-log-2026-06-to-08.md), this file's
own header now states the rotation policy for future splits, and
`CLAUDE.md`/`AGENTS.md`'s shared orientation block was updated to point at
both. Alongside #467, also closed **#470** (a `.github/CODEOWNERS` entry
requiring human review on `tooling/manifest.py`/`generate_*.py`, the
505-file-blast-radius generator core #470 flagged as unprotected) and
**#472** (a `pip-licenses --allow-only` CI step gating dependency licenses
against this repo's own MIT + CC BY posture, plus **D21** acknowledging —
rather than changing — the existing `pip-tools`/`pip-audit` unhashed-install
trade-off #472's second finding surfaced, since both steps already carried
their own stated revisit trigger inline).
