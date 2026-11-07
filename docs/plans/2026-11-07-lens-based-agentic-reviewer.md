# Lens-based agentic reviewer — a controller-run model loop over a read-only Sprite

**Status: proposal, not decided (D31 in
[`../open-questions.md`](../open-questions.md)).** Nothing here is built.
It extends the manual reviewer service
([`2026-11-06-manual-reviewer-service.md`](2026-11-06-manual-reviewer-service.md),
D24-D30, D32) from one prompt per diff part to one model loop per review
lens. Every number below is an estimate or a proposal. Nothing in this doc
was run live.

## What this doc is, and what it is not

The suite already knows how to run a lens-based review. It picks lenses,
sets breadth and severity floors by depth mode, gathers deterministic
evidence and routes it to lenses, loads each lens's body, and merges
findings under one contract into one verdict. That machinery is the
skills and commands listed under [Reused as-is](#reused-as-is). This
design reuses all of it unchanged. It adds no lens selector, budget
scheme, merger or finding format of its own.

What the suite does **not** have is a way to run that procedure without
handing an agent both the checkout and the credentials. Today it runs
inside Claude Code, where the agent reads the repo with its own tools.
In the reviewer service, the controller holds every credential and the
checkout lives only in a deny-all, credential-free Sprite. So the agent
cannot read files itself. Only four things are new, and the
[Gaps](#gaps-what-is-actually-new) section covers just those:

1. **The controller-run model loop.** The controller runs one tool-using
   conversation per lens, plus the picker and the merge.
2. **The read-only Sprite tool bridge.** This is a closed set of
   read-only tools. The controller validates each tool call and runs it
   in the Sprite, with output and time bounds. Every result is untrusted.
3. **Security boundaries.** These cover what the model can make the
   controller do, and what crosses each boundary.
4. **The credentials split.** This says which component holds which key,
   and why none of them reach the Sprite or the model.

"Claude Code checks out the repo" is taken as the *shape* of the agent,
not as running the Claude Code CLI. Running the CLI inside the Sprite
would need a model key in the Sprite. Running it on the controller would
put a working tree on the trusted host and give the agent shell tools
there. Both break the security model. The loop described here gives the
model the same kind of tools (diff, list, read, grep, log, blame) without
giving it either.

## Reused as-is

Each row below is an existing piece used unchanged. The "Role here"
column says where it plugs in.

| Need | Existing piece (path) | Role here |
|---|---|---|
| Lens selection | [`skills/choosing-review-lenses/SKILL.md`](../../skills/choosing-review-lenses/SKILL.md), generated from the `router:` section of [`skills/manifest.yaml`](../../skills/manifest.yaml) by [`tooling/generate_router.py`](../../tooling/generate_router.py) | The picker's whole instructions. It already runs as one model call in [`atlas_reviewer/picker.py`](../../atlas_reviewer/picker.py) (D32). |
| Depth modes: breadth and severity floor | The `modes:` section of `skills/manifest.yaml` ([`tooling/manifest.py`](../../tooling/manifest.py) `Mode`); [`docs/review-depth-modes.md`](../review-depth-modes.md); [`docs/collapsed-entrypoints-and-depth-modes.md`](../collapsed-entrypoints-and-depth-modes.md) | Triage runs the critical tier with no picker call. Review runs the top 3-8 lenses. Comprehensive runs every relevant lens. The floor is applied in the merge. |
| Lens instructions | `collapsed/skills/reviewing-a-change/reference/lenses/<lens>/body.md` (28 lenses, about 11k-35k characters each), plus `tool-rules.md` and `sources.md` on demand | Each lens subagent's system prompt is its `body.md`, verbatim. |
| "A lens ran only if its body was read" | [`collapsed/skills/reviewing-a-change/SKILL.md`](../../collapsed/skills/reviewing-a-change/SKILL.md) *How this works*; [`commands/atlas-review-pr.md`](../../commands/atlas-review-pr.md) step 4 | Loading the body *is* starting the subagent. Selected lenses with no subagent run are named as not run. |
| Deterministic evidence | [`collapsed/skills/reviewing-a-change/reference/tool-evidence.md`](../../collapsed/skills/reviewing-a-change/reference/tool-evidence.md) (= `skills/grounding-review-in-tool-output`) | Its rules apply as written: use only tools the repo configures, a clean run clears nothing, a timeout is a coverage gap, and the coverage line keeps its five-line format. |
| Head-SHA CI evidence | [`atlas_reviewer/gather.py`](../../atlas_reviewer/gather.py), [`classify.py`](../../atlas_reviewer/classify.py), [`groups.py`](../../atlas_reviewer/groups.py), [`archive.py`](../../atlas_reviewer/archive.py), [`evidence.py`](../../atlas_reviewer/evidence.py) | Unchanged. Non-head or missing evidence is UNKNOWN. |
| Merge, dedupe, rank, verdict, coverage | [`collapsed/skills/reviewing-a-change/reference/synthesis.md`](../../collapsed/skills/reviewing-a-change/reference/synthesis.md) (= `skills/synthesizing-review-findings`, generated by [`tooling/generate_synthesizer.py`](../../tooling/generate_synthesizer.py)) | The merge step's whole instructions. Its *Finding contract* is the output format every lens subagent must emit. Its *Fan-out model* already allows a harness to run lenses in parallel and mechanize the merge. |
| Round policy | [`REVIEW.md`](../../REVIEW.md): floor per round, round cap of 10, approve-on-clean, scope discipline | Read from the base ref, as today. The service is draft-only, so rounds stay manual. |
| Cheap triage, then a stronger review | [`commands/atlas-poll-and-review.md`](../../commands/atlas-poll-and-review.md) steps 1 and 3 | The same split: the picker is the triage call, and the lens subagents are the review. |
| Whole-repo audit | [`collapsed/skills/auditing-a-repository/SKILL.md`](../../collapsed/skills/auditing-a-repository/SKILL.md) and its `reference/lenses/*`; [`docs/runbooks/multi-repo-audit.md`](../runbooks/multi-repo-audit.md) | Audit mode's route table and lens bodies. |
| Running cited checks | [`docs/executing-cited-checks.md`](../executing-cited-checks.md) | A lens that needs a check run asks for one of the bridge's closed checks. It never gets a free-form command. |
| Cost and call caps | [`atlas_reviewer/budget.py`](../../atlas_reviewer/budget.py) `ReviewBudget`, `CallLimits`, `check_tokens`, `worst_case_usd`; [`pricing.py`](../../atlas_reviewer/pricing.py); [`openrouter.py`](../../atlas_reviewer/openrouter.py) preflight | The same worst-case-reservation scheme. See [Budgets](#budgets) for how lens slices are just more `ReviewBudget` instances. |
| Sprite lifecycle and exec | [`atlas_reviewer/runner.py`](../../atlas_reviewer/runner.py) (fresh Sprite, deny-all egress set and read back from outside, deadline, destroy on every path), [`sprites_api.py`](../../atlas_reviewer/sprites_api.py) `exec_request`, `runner.exec_argv` (D28/D29 wrapper), [`interpreter.py`](../../atlas_reviewer/interpreter.py), [`ledger.py`](../../atlas_reviewer/ledger.py) | Unchanged. Bridge tools are more execs of the same shape. |
| Redaction and untrusted fences | [`atlas_reviewer/redact.py`](../../atlas_reviewer/redact.py), [`prompt.py`](../../atlas_reviewer/prompt.py) fences with a per-prompt nonce, [`notes.py`](../../atlas_reviewer/notes.py) `quote_untrusted` | Every tool result passes through both. |
| Telemetry and draft | [`atlas_reviewer/telemetry.py`](../../atlas_reviewer/telemetry.py), [`instrumented.py`](../../atlas_reviewer/instrumented.py), [`draft.py`](../../atlas_reviewer/draft.py) | Every tool call is one more event. The draft keeps its sections. Model output in it stays untrusted. |

Reusing the skill files also means **no copy of lens content lives in
`atlas_reviewer/`**. The controller reads the collapsed bundle as data
(D24), so a lens fix lands through the usual `tooling.cli generate` path
and the reviewer picks it up.

## The loop, end to end

All of this runs on the controller unless it is marked *(Sprite)*.

1. **Fetch and gate.** As today: the event, PR metadata, head-SHA
   evidence, the diff, and the key and budget preflight. A failed diff
   fetch gives NOT REVIEWED with no model call (D30).
2. **Stage the source.** *(Sprite)* A fresh Sprite gets deny-all egress
   set and read back from outside before anything runs. The source is
   uploaded (see [Source staging](#source-staging-base-and-head-in-the-sprite)).
   The trusted interpreter and `git` are resolved by absolute path.
3. **Pick lenses** with `choosing-review-lenses`, as D32 already does, at
   the operator's depth. Triage skips the call and runs the critical tier.
4. **Run the repo's configured checks** once, per `tool-evidence.md`, through
   the bridge's closed check set. The results become the evidence block.
   A configured check outside that set (for example ruff or pytest, when
   no head-SHA CI evidence covers it) is not run. It is listed as an
   unrun check in the coverage line, never as passing.
5. **Run lens subagents** up to the parallelism limit. Each one:
   - **System prompt:** the controller's agent instructions, then that
     lens's `body.md`, then the *Finding contract* section of
     `synthesis.md`.
   - **First user turn**, all fenced as untrusted: PR metadata, the diff
     stat, the controller notes, the evidence block, and the risk-ordered
     changed-file list from [`atlas_reviewer/diffs.py`](../../atlas_reviewer/diffs.py).
   - **Loop:** the model calls bridge tools. The controller validates each
     call, runs it in the Sprite, redacts the result and fences it as
     untrusted. The loop ends when the model returns findings or hits its
     budget.
6. **Check findings mechanically.** The controller parses each lens's
   findings against the *Finding contract*: the closed severity, valence,
   route and attribution sets, plus required fields. It also runs
   `synthesis.md`'s own quote-the-line gate. For a `file:line` finding, the
   quoted `evidence` must appear in that range of the head blob. A finding
   that fails is moved to an "unverified" list, never dropped silently.
   - **Redacted quotes.** Lenses only ever see redacted text, so the
     controller runs the same `Redactor` over the head range before
     comparing. A quote holding a mask then matches the masked line. The
     raw secret never leaves the controller, and a quote with text that
     isn't in the range still fails.
   - **Removed lines.** A quote of deleted code isn't in the head blob. It
     is checked against the `-` lines of that file's diff hunks, redacted
     the same way, and the finding is labelled "removed lines". A quote
     that matches neither the head range nor a removed line fails.
7. **Merge.** One model call with `synthesis.md` as its instructions, over
   the checked findings, the coverage ledger and the tool-evidence
   coverage line. It produces the verdict, ranked sections, tensions,
   coverage and process notes in `synthesis.md`'s output format.
   - **Reconciling the merge.** The merge is model output, so the
     controller checks it against the checked findings before the draft
     uses it. Every checked finding at or above the floor must appear in
     the ranked sections or be named as merged into one that does.
     `synthesis.md`'s permitted exclusions (below-floor findings sent to
     *Non-blocking*, and pre-existing or improvement findings that don't
     set the verdict) count as present. No finding may appear that no lens
     reported, and no severity may rise (`synthesis.md` forbids inflation).
     The verdict must follow `synthesis.md`'s rule from the highest
     surviving verdict-setting severity: one Blocker means block.
   - **Merge mismatch.** On any mismatch the merged text is kept as
     untrusted output, marked "merge inconsistent", and has no verdict
     line. The draft lists every checked finding unmerged and ranked by
     severity, as when the merge fails.
8. **Write the draft and destroy the Sprite.** The draft keeps today's
   controller-generated sections (runner proof, budget, telemetry,
   omissions, lens coverage). The merged review sits under the existing
   "model output, untrusted" label. The Sprite is destroyed on every exit
   path, as today.

## Gaps: what is actually new

### Gap 1 — The controller-run model loop

- **Message shape.** OpenRouter's OpenAI-compatible chat API with `tools`.
  The controller sends tool schemas and gets `tool_calls` back. It answers
  each with a `tool` message. All D25 pins stay: the exact model,
  `provider.only`, `allow_fallbacks: false`, and `require_parameters`.
  Whether every pinned provider supports tool calling under those pins is
  **unverified**, and is the first live check this needs.
- **Turn limit per lens.** A bounded number of model turns per lens
  (proposal: 12). Each turn is one model call, reserved and settled
  through the lens's budget and the review's budget (see [Budgets](#budgets)).
- **Termination.** The loop ends on any of these:
  - the model returns a final message that parses as the finding list
    (an empty list is valid and means "No findings");
  - the turn limit or a budget limit is hit;
  - the review deadline passes;
  - the Sprite becomes unavailable.

  In every case except the first, the lens is reported as **partial**
  with what it read. It is never reported as clean. The first case counts
  as complete only if the ledger shows the lens read the change: at least
  one `diff_file` page, or a `read_file` of a changed file. An empty list
  with no such read is partial, "no source read".
- **Scheduling.** The controller runs subagents with a bounded worker pool
  (proposal: 2 at once, at most 4). Each subagent owns its message
  history. No lens sees another lens's history. That keeps attribution
  clean and matches `synthesis.md`'s collect-then-merge model.
- **Picker and merge are single calls.** Neither one gets tools. The
  picker sees PR text and paths, as in D32. The merge sees only
  controller-checked findings and the coverage ledger.
- **Prompt caching.** The system prompt and first user turn are stable
  for each lens, so a provider prompt cache could cut input cost a lot.
  Whether caching is allowed under the pinned zero-data-retention routing
  is **unverified**.

### Gap 2 — The read-only Sprite tool bridge

The model never names a command. It names a tool from a closed set and
gives typed arguments. The controller builds a fixed argv from a
template, validates every argument, and runs it through `runner.exec_argv`
under `/usr/bin/env -i PATH=/usr/bin:/bin` (D29). It uses a `git` resolved
by absolute path before upload, the same way `interpreter.py` resolves
Python, so PR files can't shim it.

| Tool | Argv template (controller-built) | Model chooses | Bounds (proposal) |
|---|---|---|---|
| `diff_stat` | `git diff --no-ext-diff --no-textconv --find-renames --stat=200 BASE...HEAD` | nothing | 16 KiB, 10 s |
| `diff_file` | `git diff --no-ext-diff --no-textconv --find-renames BASE...HEAD -- PATH`, sliced by byte offset | `path`, `offset` | 32 KiB a page, 10 s |
| `list_files` | `git ls-tree -r --name-only -z HEAD -- PREFIX` | `prefix` | 2,000 entries or 32 KiB, 10 s |
| `read_file` | `git cat-file blob HEAD:PATH`, cut to lines `start`-`end` by the controller-side wrapper | `path`, `start`, `end` | 400 lines or 32 KiB, 10 s |
| `grep` | `git grep -n -I --no-color --max-count=50 -F -e PATTERN HEAD -- PREFIX` (`-E` only if `regex: true`) | `pattern`, `prefix`, `regex` | 200 matches or 32 KiB, 15 s |
| `log` | `git log --no-color --format=%H%x09%an%x09%ad%x09%s -n N BASE..HEAD -- PATH` | `path`, `n` ≤ 20 | 16 KiB, 10 s |
| `blame` | `git blame --porcelain -L START,END HEAD -- PATH` | `path`, `start`, `end` | 200 lines or 32 KiB, 15 s |
| `run_check` | one entry of the controller's closed `ToolSpec` set (today `DEFAULT_TOOLS` in `runner.py` holds only `python-compileall`) | `name` from that set | each spec's own timeout; results cached for the review |
| `read_lens_reference` | **controller-local:** the lens's own `tool-rules.md` or `sources.md` from the trusted bundle | `file` from a closed set | 32 KiB |

**Argument rules.** These apply to every tool before any exec:

- **`BASE` and `HEAD`** are controller-fixed revisions: the SHAs from the
  event and the compare API, or under Option B the synthetic commit IDs
  that staging recorded for them. The model never supplies a revision.
- **Audit mode** has no `BASE` and no diff tools. `log` becomes
  `git log --no-color --format=%H%x09%an%x09%ad%x09%s -n N HEAD -- PATH`,
  with `n` up to 200 (proposal), so churn and bus-factor lenses see enough
  history. That needs Option A staging.
- **Paths and prefixes** must be repo-relative and NUL-free. They may not
  start with `-` or `/`. No segment may be `..`. Each is at most 512
  bytes, and each is passed after `--`.
- **Patterns** are passed with `-e` and are at most 256 bytes. They are
  fixed strings by default.
- **Integers** are range-checked.
- **Quoting.** Every value is shell-quoted by `exec_argv`, as today.
- **Invalid calls.** An invalid call is never run. The model gets a
  structured error, and the call counts toward the lens's turns.

**Git hardening.** Every git exec gets these settings:

- `-c core.hooksPath=/dev/null -c core.fsmonitor= -c core.pager=cat
  -c protocol.allow=never`;
- `GIT_CONFIG_NOSYSTEM=1` and `GIT_CONFIG_GLOBAL=/dev/null`;
- `--no-ext-diff --no-textconv` on diff.

The repository's `.git/config` is written by the staging step, not taken
from the PR. So `.gitattributes` in the PR can name a diff driver, but
nothing defines that driver. Bridge tools never check out, build or
execute PR content. Only `run_check` runs anything, and it runs only
the closed specs that exist today.

**Results.** Each result goes through the same pipeline before the model
sees it:

- capped at its byte bound, with an explicit truncation marker and the
  size that was cut;
- redacted with the shared `Redactor`;
- fenced as untrusted with the per-prompt nonce;
- recorded in the per-lens coverage ledger: the tool, its arguments, the
  bytes returned, whether it was truncated, and how long it took.

A timeout returns a "timed out" result and becomes a coverage gap, never a
finding (`tool-evidence.md`). Commit messages, blame authors and file
content are all PR-controlled data.

#### Source staging: base and head in the Sprite

`git diff BASE...HEAD`, `log` and `blame` need git objects in the Sprite.
Two options, both keeping the controller free of a working tree:

- **Option A — a git bundle.** The controller makes a bare fetch of
  `BASE` and `HEAD` with the read-only installation token, with no depth
  limit. A shallow fetch won't do: per git-bundle(1), a bundle can list
  prerequisite commits that the receiving repository must already have,
  and the Sprite's empty repository has none, so the offline clone would
  fail. The full-history fetch is bounded by a byte cap (proposal: the
  existing 9 MiB upload cap). Over the cap, staging falls back to
  Option B, and the draft says history-dependent tools are limited. The
  controller writes a bundle and uploads it through the existing stdin
  path. The Sprite clones from the file with no network. The bundle carries objects
  and refs only, never a remote URL or a token. The cost is git on the
  controller and a fetch of PR-controlled objects onto the trusted host.
  Those objects are never checked out or executed there.
- **Option B — two tarballs.** The controller fetches the merge-base and
  head tarballs, as it already fetches head. The Sprite builds a
  two-commit repo from them. Diff, list, read and grep work fully.
  `log` and `blame` only see that synthetic history, so PR commit
  metadata comes from the GitHub API as fenced evidence instead. Each
  tarball stays under the existing 9 MiB cap, and both go through the
  same upload exec. The synthetic commits have their own IDs, which
  differ from the GitHub SHAs. Staging reports both IDs back, and the
  controller fills `BASE` and `HEAD` in the bridge templates with them.
  The GitHub SHAs stay as provenance in the draft and the ledger.

Proposal: build **Option B first**. It reuses the existing fetch and
upload with no new trusted-host git. Option A comes only when a lens needs
real history, for example `finding-maintainability-hotspots` in audit
mode.

### Gap 3 — Security boundaries

| Boundary | What crosses | Rule |
|---|---|---|
| Model → controller | Tool calls | Closed tool set, typed and validated arguments, fixed argv templates, fixed revisions. Nothing the model writes becomes a command, a URL, a file write, a GitHub call or a network destination. |
| Controller → Sprite | Exec requests (D28 shape), the source upload | No credentials, no `env`/`dir` API parameters, a minimal environment. Egress is denied before the first exec and read back from outside. |
| Sprite → controller | Exec output | Untrusted. Byte- and time-capped per tool, streamed with the D28 first-frame and stall cutoffs, redacted and fenced before any model sees it. |
| Controller → model | Prompts | Only redacted, fenced data. The model is the only outbound destination for repo content, and it already is today. |
| Model → draft | Findings and merged review | Untrusted model output. Parsed against the finding contract and quote-checked. It goes only into the draft file or stdout. Nothing is posted (draft-only, D24). |
| Lens ↔ lens | Nothing | Separate histories. One lens's tool output can't steer another lens except through findings, and the merge treats those as data. |

**Prompt injection.** File content, commit messages and PR text can
contain instructions. The worst they can do is:

- make a lens call more read-only tools, bounded by its turns and budget;
- make the picker choose a different subset of real lens names, bounded by
  the closed name set (a D32 open question);
- make a lens report false or missing findings.

The last one is the residual risk. It is why the draft stays a draft, why
the merge must report coverage, and why a human reads the result. No tool
can write, reach the network, or touch credentials, so injection can't
exfiltrate data beyond the model provider, which already sees the
content.

**Fail-closed rule.** Anything the controller can't establish is UNKNOWN
or not run, and is named in the draft. That includes a lens that didn't
finish, a tool that timed out, evidence for another SHA, and a finding
whose quote didn't match. None of these is ever reported as a pass.

### Gap 4 — The credentials split

| Credential | Held by | Used for | Never reaches |
|---|---|---|---|
| GitHub App key and installation token (read-only, one repo; D25) | Controller | PR metadata, diff, tarballs (or the Option A fetch), head-SHA evidence | Sprite, model, draft, bundle |
| OpenRouter key (D25, key-limit preflight) | Controller | Picker, lens turns, merge | Sprite, model prompts, draft |
| Sprites org token | Controller (`SpritesClient`) | Create, policy set and read-back, exec, destroy | Sprite (it is the outside API's token), model |
| None | Sprite | — | — |
| None | Model | — | — |

The tool bridge is controller code calling the Sprites API with the
controller's token. Inside the Sprite there is only the source, `git`, the
trusted interpreter, and the closed checks. Telemetry and the draft go
through the existing redactor.

## How the requested topics map onto this

- **Lens selection.** No new selector. `choosing-review-lenses` runs as
  the picker call (D32), and triage uses the critical tier. The coarse
  path and keyword selector was already removed from `atlas_reviewer`
  in D32 in favour of this picker. Choosing a cheaper picker model, as the
  poll command does, is open question 6.
- **One subagent per lens.** Gap 1. The instructions are the lens's
  `body.md`, verbatim.
- **Budgets and parallelism.** See [Budgets](#budgets). The existing
  depth-mode breadth and `ReviewBudget` reservations are reused, plus one
  new number: the worker-pool size.
- **Evidence and CI.** Head-SHA CI evidence and `tool-evidence.md` are
  reused unchanged. Routing tool hits to the owning lens is a judgment
  `tool-evidence.md` gives the reviewer. Here, every lens gets the whole
  bounded evidence block, and its `body.md` decides what is its own.
  Mechanized routing is a gap, not proposed.
- **Merging and deduplication with lens attribution.** `synthesis.md`,
  unchanged, as one merge call. The controller checks the finding
  contract and the quote-the-line gate that `synthesis.md` already
  requires. It then reconciles the merge output against the checked
  findings (step 7).
- **Coverage.** `synthesis.md`'s *Coverage & limitations* and
  `tool-evidence.md`'s coverage line, filled from the controller's
  per-lens ledger. The ledger records what each lens actually read:
  files and ranges, greps, diff pages and checks. The draft gains a
  "read by" column next to today's lens table. A lens's claimed coverage
  that the ledger doesn't show is a process note.
- **Whole-repo audit.** The same loop with no `BASE`. The tools are list,
  read, grep, log and blame on `HEAD`, with no diff tools. The lens set
  and bodies come from `auditing-a-repository`'s route table. It names
  every repo-shaped audit, so no picker call is needed. Churn and
  bus-factor audits need history (Option A). Multi-repo fan-out follows
  `docs/runbooks/multi-repo-audit.md`: one review per repo, never
  parallel Sprites in one run while the one-review-at-a-time rule
  stands.
- **Failure modes.** See [Failure modes](#failure-modes).
- **Migration.** See [Migration](#migration-from-the-single-prompt-path).
- **Cost.** See [Cost estimate](#cost-estimate-rough).

## Budgets

No new scheme. `ReviewBudget` already reserves a worst case per call
against a dollar cap and a call cap, and settles to the actual cost:

- **Review budget.** One `ReviewBudget` for the review, as today, with
  the key-credit ceiling.
- **Lens slices.** Each lens gets its own `ReviewBudget(CallLimits(...))`
  with a smaller dollar cap and turn cap. Every call reserves on **both**
  the lens slice and the review budget, and is refused if either refuses.
  That is two instances of the existing class, not a new mechanism.
- **Per-call tokens.** `check_tokens` stays as written: at most 200k
  input and output under the catalog context. The lens loop lowers
  `max_output_tokens` per turn (proposal: 4,000; findings are short).
  That shrinks each turn's worst-case reservation.
- **Breadth** comes from the depth mode. **Rounds** come from `REVIEW.md`.
- **Parallelism.** The worker-pool size is the only new number. With
  *p* subagents in flight, up to *p* reservations are unsettled at once,
  so the review cap must cover *p* worst cases.

**This needs a new owner decision.** D25's **3 calls per review** and
**$3.00 reservation** were set for one prompt per review. A lens loop
needs roughly *(lenses × turns) + 2* calls. The cap is a hard owner
limit, so this design can't change it. See open question 1.

## Failure modes

| Failure | Behaviour |
|---|---|
| Sprite create, egress set or read-back fails | No bridge. As today, no in-Sprite tool runs. Proposal: no lens loop either. The draft says NOT REVIEWED (agentic), and the operator can rerun the single-prompt path. |
| Source upload or staging fails | Same as above. A lens without the source would only see the diff text, which the single-prompt path already covers. |
| Invalid tool call | Not run. A structured error goes back to the model and counts as a turn. |
| Tool timeout or output cap | A "timed out" or truncation marker goes back. It is a coverage gap in the ledger and the coverage line. |
| Sprite dies mid-review | Lenses still running end as partial. Finished lenses keep their findings. Destroy and verify run as today, and the ledger and sweep cover a failed destroy. |
| Lens hits its turn or budget limit | Partial. Its parsed findings so far are kept if they parse, and coverage lists what it read. |
| Lens output doesn't parse against the finding contract | Partial: "output did not parse". No findings from that lens, and nothing is fabricated for it. The merge and the draft get it as a coverage gap, never as a clean lens. |
| Quote-the-line gate fails | The finding moves to an "unverified" list in the draft. It never feeds the verdict. |
| Review budget or call cap reached | Remaining lenses are "selected, not run" (`synthesis.md` coverage wording). |
| Picker fails | Critical tier, as D32 does now. |
| Merge call fails or doesn't parse | The draft lists each lens's checked findings unmerged, ranked by severity, under "not synthesized". There is no verdict line. |
| Merge drops or changes a checked finding, adds one, or gives a verdict its findings don't support | "Merge inconsistent": the same unmerged listing and no verdict line, with the merged text kept as untrusted output (see step 7). |
| Deadline passes | The same as the Sprite dying: what finished is reported and the rest is not run. |
| Model returns another model's response | Rejected, as D25 requires. |

## Migration from the single-prompt path

1. **Now (D32).** The single prompt per diff part, with the picker and
   diff fitting to the 200k bound. This stays the fallback.
2. **Bridge only.** Add the tools to `runner.py` and `probe-runner`, with
   no model. Test them offline against `FakeSprites` and a fixture repo,
   covering argument rejection, caps, timeouts and git hardening. The
   owner runs `probe-runner --sequence bridge` live once.
3. **One lens.** Add `--agentic --lens <name>`, which runs one subagent
   and the merge on a pilot PR. Compare it with the single-prompt draft
   for the same head. This needs the call cap decision first.
4. **Picker, N lenses run one at a time, and the merge.** The full loop
   with a pool size of 1.
5. **Parallelism, then audit mode** (Option A staging).
6. **Retire the single-prompt path** once agentic drafts match or beat it
   on the pilot PRs. `diffs.py`'s risk ordering and fitting stay: they
   order the changed-file list each lens gets.

What changes in `atlas_reviewer/`:

- **New:** a `bridge.py` (tool schemas, validation, argv templates) and a
  `loop.py` (turns, termination, ledger).
- **`harness.py` and `openrouter.py`:** gain tool-message support.
- **`lenses.plan_lenses`:** becomes a one-body loader, with no shared
  60,000-character budget.
- **`draft.py`:** gains the "read by" column.
- **Nothing** under `skills/`, `collapsed/` or `tooling/` changes.

## Cost estimate (rough)

These assumptions are **estimates, not measurements**:

- About 3.8 characters per token for real usage. Reservations keep the
  stricter one-byte-per-token bound.
- The fixture prices of $3/M input and $15/M output (the base tier).
- No prompt caching.
- 12 turns per lens.

The one live data point is D26's single call, which cost $0.17.

- **Per lens subagent.** The first turn is about 45k characters, or about
  12k tokens: instructions, about 17k characters of body on average, the
  finding contract, PR metadata, notes and evidence. Each turn adds about
  10k characters of tool output and model text, about 2.6k tokens. Resent
  history makes 12 turns about 12 × 12k + 2.6k × 66, or about 315k input
  tokens. That is about $0.95, plus about 12k output tokens at about
  $0.18, so **about $1.1 per lens**. A prompt cache, if allowed, could
  bring that to roughly $0.3-0.4.
- **Picker and merge.** About $0.10-0.25 together.
- **Per review:**

  | Mode | Lenses | Uncached | Cached, if allowed |
  |---|---|---|---|
  | Triage | 4 | about $4.5 | about $1.5 |
  | Review | 3-8 | about $3.5-9 | about $1-3 |
  | Comprehensive | up to 28 | about $30 | about $9-11 |
  | Repo audit | 11 | about $15-25 (more reading) | — |

- **Reservations versus spend.** Under the byte bound, a late turn of
  about 165k bytes reserves about 165k × $6/M + 4k × $22.5/M, or about
  $1.08 at the top fixture tier. That is far above its likely real cost.
  With 2 subagents in flight, about $2.2 is held at once. So any cap below
  about $5 serialises the pool in practice.

## Open questions for Brandon

1. **Caps.** D25's 3 calls and $3.00 per review can't run a lens loop.
   What call cap, review dollar cap, per-lens slice, and key hard limit
   (today at most $5) should it get? Or should agentic mode stay triage
   only (4 lenses) until the cost is measured?
2. **Source staging.** Option B (two tarballs, no git on the controller)
   first, or straight to Option A (a bundle, real history)?
3. **Own loop or Claude Agent SDK.** An SDK on the controller with every
   built-in tool disabled and only bridge tools allowed could replace
   `loop.py`. It would add a dependency and a second provider path
   outside D25's pins. Whether it can route through OpenRouter with those
   pins is unverified.
4. **Provider features under the pins.** Does every pinned provider
   support tool calling with `require_parameters`? Is prompt caching
   allowed under zero-data-retention routing? Both need a live check
   before step 3 of the migration.
5. **Merge as a model call.** `synthesis.md` allows a mechanized merge.
   This proposal keeps one model call, because tensions and coverage
   prose are judgments. Is a controller-only merge (dedupe on location and
   root cause, rank, floor) wanted as the fail-closed fallback instead of
   "not synthesized"?
6. **Picker model.** The poll command triages on a cheaper model. D25 pins
   one model. Should a second, cheaper model be allowed for the picker
   only?
7. **Parallelism.** Can one Sprite serve concurrent execs (unverified), or
   should the pool be 1 until that is probed?
8. **The floor tier under injection.** Carried from D32: should a critical
   tier always run in review mode, whatever the picker returns?
9. **Machine-readable critical tier.** The manifest's `modes:` entry
   describes triage's breadth in prose. `picker.py` copies the four names
   from `docs/review-depth-modes.md`. Should the manifest carry the list,
   so there is one source?
