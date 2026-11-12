# Agentic reviewer — direction and phased plan

**Status: direction accepted (D34 in
[`open-questions.md`](open-questions.md), 2026-11-08); phases 1 and 2 are
merged and phase 3 is built offline (D38, D39, D40), the rest is not built.**
The owner accepted the recommendations below as proposed ("I can roll with
recommendations as proposed for now"). Phase 1 (full PR conversation and
branch-wide CI, D38, #612) and phase 2 (the read-only tool bridge with Option B
staging, D39, #614) are merged, tested against fixtures only. Phase 3's
offline half (the controller loop and one attested lens, D40) is on draft
PRs, tested with the real bridge over a fixture repository and a scripted
model; nothing calls it from the CLI, and no live run has been made. Brandon
set provisional defaults for the five phase-3 limits on 2026-11-11 (see
[Open numeric decisions](#open-numeric-decisions-pending-brandon)); they are
headroom, configurable, and to be revisited after live runs. The other
rows in that table are unchanged.
This doc carries no live-run approval. No model call, Sprite run, merge or
deploy was made to write it.

This doc sets the direction for the D31 proposal,
[`plans/2026-11-07-lens-based-agentic-reviewer.md`](plans/2026-11-07-lens-based-agentic-reviewer.md).
It does not replace that proposal. D31's controller-run loop, closed
read-only tool bridge, security boundaries and credentials split stand as
written. That plan stays the detailed design for the loop, the bridge tools
and the finding checks. This doc records what the owner accepted on top of
it: phase 0, lens-body attestation, full PR context, branch-wide CI, one
secret rule for everything the model reads (extending D33), a baked
toolchain, starting scope and scoring.

The source is a research note prepared for the owner on 2026-11-07, "How
Atlas should become an agentic reviewer". It was a landscape pass over
hosted and open-source reviewers, a reading of the review-evaluation
literature, and a gap analysis against the reviewer service on
the #601-#607 stack. Product and pricing details in that note were checked on
2026-11-07 and will drift. They are summarized here only where they
motivate a decision, and are not re-verified. The paper findings under
[Why change the runtime](#why-change-the-runtime) are also the note's
summaries. They were not checked against the papers for this doc and are
marked `(verify)`; D34 does not depend on their exact figures.

## Why change the runtime

The suite already has the parts a lens-based reviewer needs. It has the
lenses, the picker (`choosing-review-lenses`), depth modes
([`review-depth-modes.md`](review-depth-modes.md)), the finding merger
(`synthesizing-review-findings`), and tool grounding
(`grounding-review-in-tool-output`). The reviewer service on the stack
(D24-D33) is a careful substrate but a one-shot one. Before D38 it had
these gaps (D38 closes the second and third):

- **The model sees a parcel, not a checkout.** It gets a fetched diff,
  split into parts by size, and cannot open a file or compare branches.
- **The PR conversation is cut.** The PR body and issue text are capped at
  2,000 characters (`evidence.DETAIL_CHARS`). Review threads are not
  fetched.
- **CI evidence is head-SHA only.** Anything for another SHA is UNKNOWN.
  That is correct for "does this pass", but it hides a failure on the
  parent commit that was never re-run.
- **The sandbox toolchain is almost empty.** D26 left `ruff` and
  `shellcheck` out of the defaults because a deny-all Sprite cannot install
  them.
- **Lens execution is not attested.** Lens bodies are inlined under a
  character budget. In the first pilot no lens body was loaded, and the
  model reported that no lens ran (D26). Naming a lens in a prompt without
  its body never ran it.
- **The caps fit one prompt, not a loop:** 3 model calls and a $3.00
  reservation per review (D25). D31 estimated about $1.1 per lens
  uncached at 12 turns.

The research note draws three design rules from the literature. Each
paper claim below is as the note reports it, not checked here:

- **Give the reviewer the project, not the hunk.** SWR-Bench (Zeng et al.,
  2025, [arXiv 2509.01494](https://arxiv.org/html/2509.01494v1)) rebuilds
  review evaluation on real pull requests with a full project snapshot,
  and reports precision as the main weakness of current automated
  reviewers (verify).
- **Run tools, then select and explain the hits.** Stuffing raw analyzer
  reports into the prompt did badly on SWR-Bench (its Hybrid-Review
  baseline) (verify). Jaoua, Sghaier and Sahraoui (MSR 2025,
  [arXiv 2502.06633](https://arxiv.org/html/2502.06633)) found that
  retrieving the relevant static-analysis results helped, where naive
  concatenation did not help accuracy much (verify). This is what
  `grounding-review-in-tool-output` already says.
- **Split by concern, not by free-form agents.** SWR-Bench's two-agent
  debate setup underperformed single-pass prompting (verify). Splitting by lens
  gives each loop a typed concern with its own skill file, which is how
  the suite's picker and merger already work. Verification belongs in the
  controller, where the model cannot argue past a failed check.

## Accepted direction

### 1. Phase 0: the one-shot stack stays the fallback

The one-shot reviewer on #601-#607 stays mergeable and is the fallback.
Agentic mode is built beside it as a separate path. It does not rewrite
the one-shot controller, change the skill bundle, or put agentic scope
into those PRs. A review finding on #601-#607 that is about agentic design
is filed as follow-up. The one-shot path is retired only after measured
pilots show agentic drafts match or beat it on PRs the owner picks (see
[scoring](#5-caps-unchanged-start-triage-only-own-loop-issue-hit-scoring)).

### 2. One tool loop per selected lens, with the body attested

Each selected lens runs its own tool-using loop over a checkout in the
Sprite. The checkout holds the PR head and base, plus the repository
default branch when a lens needs to tell new problems from pre-existing
ones. BASE, HEAD and DEFAULT are SHAs the controller fixes; the model
never supplies a revision. Staging follows D31's Option B first (two
tarballs into a synthetic two-commit repository). When the PR's base is
not the default branch and a lens needs it, the controller stages a third
tarball of the default branch at its pinned DEFAULT SHA, as a separate
read-only commit beside the other two. The bridge's revision argument is
then the closed set BASE, HEAD and DEFAULT, and DEFAULT reads get the
same byte, time and path limits as the others. When the base is the
default branch, DEFAULT is BASE and nothing extra is staged. Option A, a
real git bundle with history, comes when lenses need blame and log.

A lens counts as run only when its loop started with that lens's
`body.md` injected by the controller. A review that names a lens without
its body loaded counts as **not run**. The controller retries such a lens
once with the body forced. If that fails, it escalates: the lens is
reported as not run or partial in the draft. A stronger model is tried
once only if the owner has approved a model map (see the open decisions).
D31's other checks apply unchanged:

- source-read attestation: an empty finding list with no read of a
  changed file is partial;
- quote checks: every `file:line` finding must quote text found at that
  range of the head, or in the diff's removed lines;
- an ID-reconciled merge: the controller mints finding IDs, and the merge
  must cite them without inventing or promoting any.

### 3. Full PR conversation and branch-wide CI, labelled by SHA

The reviewer gets the full PR conversation instead of the 2,000-character
body cap: body, labels, requested reviewers, commit subjects, and review
threads and comments. The working budget is about 64 KiB, and anything
clipped is named as an omission, never cut silently. The exact split
between the body and comments is an open number.

CI evidence covers the whole PR branch, as far back as GitHub still keeps
it, within a page and byte budget. Every item is labelled with its commit
SHA. Only evidence for the current head SHA can support a current pass.
Evidence for an older SHA stays visible, marked stale, and never counts as
a pass for head. Missing evidence stays UNKNOWN, so D24's fail-closed rule
is unchanged.

All of this text is untrusted. It is fenced with the per-prompt nonce and
redacted, as D33 keeps for PR, issue and CI text. Inside the conversation
block (D38), every one-line field a person wrote (title, names, branches,
labels, commit subjects) is a JSON string, and every body is split at
every line terminator with each line starting `>`, so nothing PR-written
can begin an unquoted, controller-looking line. Commits are ordered by
their parents and committer date, not by how GitHub lists them.
Repository content follows the secret rule below.

### Secret rule for everything the model reads

One rule, extending D33 from the diff to every bridge result, replaces
D31's "every bridge result is redacted":

- **Repository content is not redacted.** That covers the diff and every
  bridge result that returns file content at BASE, HEAD or DEFAULT,
  changed or unchanged: reads, grep matches and `git diff` output. It is
  already in the repository. The controller scans each result with
  `detect_secrets` before sending it. Each hit becomes a controller
  finding (HIGH, "possible committed secret in `<path>`; rotate if real")
  with the path, line and pattern label, never the value. A hit in an
  unchanged file is reported as pre-existing, not as introduced by the PR.
  Detection removes no text.
- **Flagged values are scrubbed from the output.** Every value the scan
  found is scrubbed from the model's findings, the merge and the draft.
  The system prompt tells each lens never to repeat a value.
- **Runtime text stays redacted.** That covers tool and test output, CI
  logs (redacted before the tail is kept), artifacts, PR and issue text,
  and anything quoted into the published draft. These can carry runtime
  secrets that are not in the repository. A secret scanner's hit, such as
  Gitleaks, reaches a lens as path, line and rule only, with no excerpt.

### 4. Keys stay on the controller; the Sprite is deny-all and credential-free

The controller is the only trusted process. It holds the OpenRouter key,
the GitHub App key and the Sprites token, and it places every model call.
The model never names a shell command. The controller validates each tool
call, runs a fixed argv in the Sprite, caps and fences the output, and
returns it. The Sprite has the checkout and tools, deny-all egress, no
keys, and no route to the model provider. It is destroyed and verified
absent after every review, as today. Neither the Claude Code CLI nor any
other agent runtime runs inside the Sprite or on the controller.

Free, self-hostable tools are baked into the Sprite image, never installed
from the PR or the network. The first set is the existing `compileall`
probe, `ruff`, `mypy`, `shellcheck`, Semgrep Community Edition (or
Opengrep), Bandit, `pip-audit`, Gitleaks, a complexity tool (`radon` or
`lizard`), and a license lister such as `pip-licenses`. `pytest` follows
for repositories that already lock their test dependencies. A tool that
runs PR code (`pytest`, or `mypy` when the repository configures plugins)
could change the review's own Git state, for example by writing
replacement refs that redirect later reads, or change files lenses read.
So code-executing tools run in a second disposable Sprite that holds only
a copy of the head tree, without `.git`, and never in the Sprite the bridge
reads. Only their capped, redacted output comes back. As defence in depth,
bridge Git commands run with replacement refs disabled
(`GIT_NO_REPLACE_OBJECTS=1`) and read objects by the controller's SHAs. `pip-audit`
needs a vulnerability database, and the Sprite has no network, so that
database has to be baked in or the tool reports UNKNOWN (verify before
building). The shared toolchain runs once per review. Lenses get
summarized hits (file, line, rule ID and a short excerpt) to confirm,
place in context or dismiss, never raw logs. A clean run clears nothing by
itself, and a timeout is a coverage gap.

### 5. Caps unchanged; start triage-only; own loop; issue-hit scoring

- **Caps.** The one-shot path keeps D25's 3 calls and $3.00 reservation,
  and the model pin stays (`anthropic/claude-sonnet-5.5`, no fallbacks).
  Agentic mode has Brandon's provisional defaults (2026-11-11), for
  headroom and configurable. A live run still needs the tool-calling
  adapter, which is not built.
- **Starting scope.** Triage only: the four critical-tier lenses from
  [`review-depth-modes.md`](review-depth-modes.md) —
  `tracing-correctness-and-invariants`, `sweeping-for-security`,
  `reviewing-migration-and-data-safety` and
  `reviewing-concurrency-and-async`. Review and comprehensive depths come
  after triage is measured.
- **Own loop.** A small controller loop of our own, not the Claude Agent
  SDK. Our own loop is how we keep a closed tool set, D25's pinned routing
  and the attestation ledger without a second provider path or a new
  dependency.
- **Scoring.** Score issue-hit precision and recall against pilot PRs the
  owner labels: did the review name the issues a human cared about, and
  how many of its findings were real? This is the hit-or-miss shape
  SWR-Bench uses, not BLEU-style text similarity. Coverage honesty is
  scored alongside: lenses attested out of lenses selected, changed files
  read out of files changed, and whether every omission was named. The
  existing lens evals keep running.

## Phased plan

Each phase is its own PR, or set of PRs, off `main` after the stack lands.
None of them changes the one-shot path's behaviour except phase 1, which
improves the context both paths share, and phase 2's archive check (D39),
which the one-shot source upload now also passes: it refuses, before any
runner is created, an archive that is not a readable gzip tar, that unpacks
past 256 MiB, that has more than 50,000 members (files, directories and
links), or that holds a member whose parent directory is not an earlier
entry, which a repository can reach well under the 9 MiB compressed cap. Live runs need a fresh yes from the
owner at every phase.

| Phase | Scope | Gate to start |
|---|---|---|
| 0 | Land #601-#607 as the one-shot reviewer and fallback, with the D33 note (#608). No agentic scope in those PRs. | none |
| 1 | Full PR conversation (about 64 KiB, omissions named) and branch-wide CI labelled by SHA, in the shared evidence code. Fixture-tested. Built offline (D38), stacked on #607 with the owner's go-ahead rather than after the stack merged. | stack merged |
| 2 | The tool bridge, offline: closed git tools (diff, list, read range, grep) against `FakeSprites` and a fixture repo, with argument rejection, byte and time caps, and git hardening. Option B staging. Built offline (D39), stacked on phase 1 with the owner's go-ahead. | phase 1 merged |
| 3 | The controller loop and one attested lens, offline first: body injection, the attestation ledger, quote checks, retry and escalate. Offline half built (D40): `lens_loop.py`, `coordinator.py`, `attestation.py`, `quotes.py`, `lens_contract.py`, with a mechanical synthesis (no merge call for one lens) and no CLI entry point. Then one owner-approved live run, compared with the one-shot draft on the same head; that needs a tool-calling model adapter, which is not built. | offline work: none. Live run: Brandon's provisional defaults are set (2026-11-11); the run still needs the tool-calling adapter, which is not built |
| 4 | Triage mode: the four critical lenses, pool size 1, ID-reconciled merge, coverage never claimed complete unless the ledger shows it. | phase 3 measured |
| 5 | The baked toolchain: the first tool set in the Sprite image, with summarized hits routed to lenses. | image build approved |
| 6 | Measured pilots on owner-labelled PRs, scored for precision, recall and coverage honesty. Then review and comprehensive depths, a concurrency probe before any pool size above 1, Option A history staging, and the decision on retiring the one-shot path. | phases 4-5 done |

## Open numeric decisions (pending Brandon)

Brandon set provisional defaults for the five phase-3 limits on
2026-11-11, for headroom, configurable, and to be revisited after live
runs. A run with those defaults is accepted. Clearing one back to unset
makes `coordinator.review_lens` refuse before any model, runner or ledger
work (`LimitsUnsetError`, naming each unset field). An override must be
positive and finite, and a per-lens limit no greater than its per-review
limit. The other rows are unchanged: a working default stands where one
is named, and a row still marked none stays unset until Brandon sets it.
Until each of those is set, the phase that needs it does not run live.
The five are fields of
`lens_loop.AgenticLimits` (`reservation_usd`, `max_calls`, `max_turns`,
`lens_wall_s`, `review_wall_s`).

| Decision | Current state | Note |
|---|---|---|
| Agentic per-review dollar reservation | $5, provisional default (2026-11-11); one-shot stays $3.00 | Headroom, configurable through `AgenticLimits`. Revisit after live runs. D31 estimated about $1.1 per lens uncached at 12 turns, or about $0.3-0.4 with prompt caching if the pinned routing allows it. |
| OpenRouter key hard limit for agentic runs | the one-shot preflight requires at most $5 | Must cover the agentic reservation. The provisional reservation is $5, the same ceiling this preflight already requires. |
| Agentic per-review model-call cap | 50, provisional default (2026-11-11); one-shot stays 3 | Headroom, configurable. Includes the picker, each lens's turns and the merge. A per-lens turn cap is no greater than this. |
| Per-lens turn cap | 50, provisional default (2026-11-11) | Headroom, configurable, and no greater than the review's call cap. D31 suggested 12. |
| Per-lens and per-review wall clocks | 20 minutes per lens and 60 minutes per review, provisional defaults (2026-11-11) | Headroom, configurable. The per-lens clock is no greater than the review clock. Crossing either ends the lens or review as partial, never clean. |
| PR conversation budget split | about 64 KiB total, working default | The body and comment caps within it. |
| Branch-wide CI budget | check runs at up to 20 other commits of the PR, working default (`IngestConfig.max_ci_commits`) | How many commits back. Each commit's list keeps the client's page cap; jobs, logs and artifacts are still read at the head SHA only, under the one-shot caps. |
| Per-tool timeout and output caps for the baked toolchain | none | A timeout is a coverage gap. |
| Lens worker pool size | 1; the only value phase 3 accepts | Above 1 only after a concurrency probe. The research note suggests at most 4. |
| Retries per failed attestation | 1, recommended; the phase 3 default | Then escalate. A failed quote, a reply outside the finding contract and an abandoned attempt are retried the same way (D40). |
| Pilot set and the bar for retiring one-shot | none | Which PRs, how many, and the precision, recall and coverage results agentic drafts must reach. |

Two non-numeric decisions stay open as well. The first is a per-lens model
map, which would relax the single-model pin; the recommendation is to keep
the pin until agentic mode is measured. The second is learning and memory;
the recommendation is explicit, human-accepted rules in the repository,
such as the Q13 overlay, never silent memory.

## Invariants carried forward

- No key in the Sprite, a prompt, the draft or a bundle.
- Draft-only: no GitHub write path, webhook, merge or deploy without a
  separate decision.
- Missing evidence is UNKNOWN, and only head-SHA evidence supports a
  current pass.
- Every limit hit, clipped input, unread file and unrun lens is named in
  the draft.
- Model output is untrusted, including the merge.

## Sources

- The owner-facing research note, "How Atlas should become an agentic
  reviewer" (2026-11-07), held outside the repository.
- [D31 plan: lens-based agentic reviewer](plans/2026-11-07-lens-based-agentic-reviewer.md)
- [Manual reviewer service plan](plans/2026-11-06-manual-reviewer-service.md)
- [Competitor landscape (July 2026)](research/competitor-landscape.md)
- [SWR-Bench: benchmarking LLM-based code review](https://arxiv.org/html/2509.01494v1)
- [Combining LLMs with static analyzers for code review](https://arxiv.org/html/2502.06633)
