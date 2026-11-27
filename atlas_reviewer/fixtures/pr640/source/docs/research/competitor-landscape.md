# Research — Competitor landscape: AI-native code review products

> Not a taxonomy cluster (#1–#37) — a **product-landscape** research pass, sibling to
> [`prior-art.md`](../prior-art.md) but scoped to commercial AI-native review *products*
> (CodeRabbit, GitHub Copilot code review, Greptile, …) rather than agent skills/plugins or
> classic linters. Generated 2026-07-05 via a verified web-research pass (5 search angles, 21
> sources fetched, 88 claims extracted, 25 adversarially voted 3-way, 19 confirmed / 6 refuted).
> Feeds [`../map-gaps.md`](../map-gaps.md) G34. Time-sensitive: pricing/features captured
> mid-2026 and will drift — re-verify before citing externally.

## Why this exists

`prior-art.md` mines **agent skills/plugins and static-analysis tools** for heuristics. It does
not cover the commercial **AI-native review products** the suite is most often compared to —
CodeRabbit, Copilot code review, Greptile, and peers — which are a different kind of prior art:
not a checklist to mine, but a **competing architecture** (hybrid deterministic-tool + LLM
pipelines, some with persistent state and auto-fix) worth comparing our own architecture against.

## Coverage note (be honest about what this pass did and didn't confirm)

This pass produced **high-confidence, source-backed findings for CodeRabbit and GitHub Copilot
code review**, and a **partial, lower-confidence read on Greptile**. It did **not** yield verified
claims for Qodo/CodiumAI, Sourcery, Graphite Diamond, Codacy, DeepSource, Amazon CodeGuru
Reviewer, Snyk Code, or SonarQube's AI features — those were in scope but the adversarial
verification pass killed or didn't reach specific claims about them before the source/claim
budget ran out. **Treat their absence below as "unresearched," not "no gap."** A follow-up pass
should target those specifically (see Open threads).

Several sources were competitor marketing blogs (`gitautoreview.com`, sponsored-style `dev.to`
posts) rather than neutral third parties. Where possible, claims were cross-checked against each
vendor's own primary docs, which raised confidence — but **every specific numeric claim**
(bug-catch-rate percentages, head-to-head benchmark superiority) was refuted on adversarial
verification (0-3 or 1-2 votes) and is excluded below. Treat any "beats X by Y%" claim you
encounter elsewhere about these products as unverified marketing.

---

## CodeRabbit

### Architecture: confirmed hybrid pipeline

CodeRabbit runs deterministic tooling and an LLM review layer together, not LLM-only. Its own
docs confirm specific tool integrations:

- **Infer** (C/C++/Java) — null dereferences, resource leaks, concurrency issues.
- **ast-grep** — multi-language AST structural pattern matching; also exposed to users as a
  **custom-rule mechanism** (<https://docs.coderabbit.ai/configuration/ast-grep-instructions>) — write an
  AST pattern once, it becomes a repo-specific lint rule enforced on every PR.
- **PMD** (Java) — auto-generates a default ruleset for repos with no existing PMD config.
- A broader bundle independently reported at **40+ linters/SAST tools** (ESLint, Pylint, Golint,
  RuboCop, Bandit-class scanners, Semgrep) layered under the AI review.

**→ mine:** the ast-grep-as-custom-rule pattern is the sharpest idea here — it's a *low-cost,
high-precision* way to let a team encode "this AST shape is wrong in our repo" once and have it
enforced deterministically forever, instead of re-deriving the same finding by LLM judgment on
every review.

### Unique capabilities beyond generic LLM prompting

- **Autofix** — `@coderabbitai autofix` applies a fix for an unresolved finding directly to the
  PR branch (or `autofix stacked pr` for a separate stacked PR).
- **Simplify Code** — extracts reusable functions, simplifies conditionals, as a distinct
  suggested action from a plain finding.
- **Committable one-click suggestions** — a diff-shaped patch a reviewer applies with one click,
  batchable into a single commit.
- **Learnings** — a persistent preference store: review-thread feedback ("we don't flag this
  pattern," "always require X here") is captured from chat and **automatically applied to future
  reviews** of that repo, with an admin `approval_delay` workflow before a learning takes effect,
  and a `GET /v1/learnings` API for exporting the accumulated preference set as CSV.

**→ mine:** Learnings is the concrete answer to "how would a team-preferences overlay actually
work in production" — capture corrections *in the review conversation itself*, not in a separate
config file nobody maintains, with an approval gate so one loud reviewer can't silently redefine
team policy.

### Pricing / deployment

SaaS: Pro at **$24/user/month annual ($30 month-to-month)**, Pro Plus at **$48/user/month annual
($60 month-to-month)**, AI compute bundled into the subscription (no bring-your-own-key). A more
specific claim about an Enterprise self-hosted deployment (AWS ECS/EKS, $15,000+/month) was
**not confirmed** on adversarial verification (1-2 vote) — treat CodeRabbit's actual
self-hosting/on-prem story as unknown, not as "doesn't exist."

### Known limitation

Multiple independent sources describe CodeRabbit as **weaker on cross-repo/cross-file context** —
it primarily sees the diff plus a small surrounding window, not a full-codebase index. One of
those sources, Sourcegraph, is itself a competitor, so read that specific source with appropriate
skepticism — but the limitation is consistent with the confirmed architecture above and this is
the one place a specific Greptile-superiority claim was refuted (0-3) while the qualitative
limitation itself survived (2-1).

---

## GitHub Copilot code review

### Architecture: prompt/instruction-based, not a bundled static-analysis pipeline

Unlike CodeRabbit, Copilot code review's customization runs through **instruction files and model
configuration**, not an orchestrated bundle of third-party linters/SAST tools:

- **Two effort/reasoning tiers** — Low (default, fast, common-issue feedback) and Medium (public
  preview, routes to a higher-reasoning model for complex logic, security-sensitive code,
  cross-service changes).
- **Repo-wide instructions** — `.github/copilot-instructions.md`, applied to every review (team
  standards, universal security requirements).
- **Path-scoped instructions** — `.github/instructions/*.instructions.md` with an `applyTo`
  frontmatter glob (e.g. `applyTo: **/*.py`) to target language- or directory-specific rules.
- **Copilot Memory** (public preview, Pro/Pro+/Max) — persists learned repo details across
  sessions, the closest Copilot analog to CodeRabbit's Learnings, though scoped to "what the
  model has learned about this repo" rather than an explicit, admin-approved preference ledger.
- **Automatic re-review on push** — configurable to re-review on every push, plus on draft-PR and
  draft-to-open-PR conversion.
- **One-click suggested changes**, individually or batched into a single commit.

**→ mine:** the `applyTo`-glob path-scoped instruction file is a clean, low-cost pattern worth
comparing against how `code-quality-atlas` scopes lens applicability today — it's essentially a
declarative "this rule set applies to this glob" mechanism, adjacent to (but simpler than) the
suite's `shape:`/`artifacts:` manifest-driven routing.

### Known limitation

Copilot code review is **GitHub-only** — no native GitLab/Bitbucket/Azure DevOps support,
contrasting with CodeRabbit and Qodo, which are multi-platform (per independent third-party
comparisons; GitHub's own docs corroborate the GitHub-exclusive mechanism).

---

## Greptile (partial — lower confidence)

The one specific, adversarially-confirmed claim: Greptile **indexes the entire codebase** (not
just the diff) and reviews each PR against that full index specifically to catch **cross-file /
"seam" bugs** — logic that's locally correct but breaks an invariant elsewhere in the repo. It
supports **directory-scoped custom rules** via a `.greptile/` config folder: `config.json` for
structured directory/file-pattern + severity rules, `rules.md` for freeform markdown guidance,
merged from the repo root down to the specific file's directory (enabling per-directory/monorepo
overrides). A specific "82% bug catch rate" claim was refuted (0-3) — treat it as marketing.

**→ mine:** whole-repo indexing is the single clearest capability the atlas structurally lacks —
every lens here reasons from a diff (plus whatever the agent chooses to read live), not from a
persistent, pre-built index of the entire codebase's call graph and cross-file relationships.

---

## Gap analysis: code-quality-atlas vs. this landscape

Ranked by (my estimate of) value ÷ implementation cost, using the confirmed findings above.

### Tier 1 — high value, low cost, no proprietary infrastructure needed

1. **Deterministic-tool pre-pass, fed into the LLM lenses as evidence.** CodeRabbit's core
   architecture — and DeepSource's own positioning (a competitor comparison independently
   describes DeepSource as "5,000+ deterministic rules plus an AI layer on top," though this
   specific claim wasn't part of the adversarially-verified set here and should be re-confirmed)
   — is unanimous on one point: **ground the LLM's findings in a linter/SAST run first, use the
   LLM to add context and cut false positives on top, not to invent the finding from scratch.**
   The atlas today is pure LLM judgment even where mature tools already exist (this is the
   opposite of [`prior-art.md`](../prior-art.md)'s own G5 framing — "where mature linters cover a
   category, the skill's job is to orchestrate/triage tool output, not re-implement it" — a
   principle the map already states but the runtime doesn't yet act on). Concretely: a review
   invocation could shell out to whatever linter/SAST the repo already has configured (ESLint,
   Semgrep, Bandit, RuboCop, `go vet`, …) and hand the LLM lens the tool's raw findings as
   additional evidence to confirm, contextualize, or dismiss — rather than the LLM independently
   re-deriving "this looks like a resource leak."
2. **ast-grep-style durable custom rules.** CodeRabbit's ast-grep-instructions mechanism is a
   direct, buildable pattern: let a team write an AST pattern once (in a config file) and have it
   become a deterministic, zero-token check enforced on every review, instead of relying on the
   LLM to notice the same repo-specific anti-pattern every time.
3. **Auto-applied fixes for high-confidence findings.** Both CodeRabbit (Autofix,
   `autofix stacked pr`) and Copilot (one-click, batchable suggested changes) ship this; the atlas
   is explicitly **detect-and-suggest only, with no auto-apply, today**
   ([`map-gaps.md`](../map-gaps.md) G26 — the "defect-only by construction" finding is about a
   different axis, *which findings* are surfaced by default, not *whether* a surfaced finding can
   be applied; G13/G26 both name auto-application as the still-open half of Q8, the fixing mode).
   This tier-1 placement is about the **narrower, safer slice**: mechanical, low-risk fixes (a
   committable one-line patch for a clearly-scoped nit) — not the broader "should the agent edit
   code" question, which stays gated behind Q8. **Caveat: unlike items 1–2, this one doesn't
   actually fit "no new infrastructure"** — applying a fix to a branch needs write/commit access
   plus safety rails (a revert path, scope limits on what counts as "mechanically safe") the atlas
   doesn't have today; it's grouped here on value/cost, not on infrastructure-free-ness.

### Tier 2 — real value, moderate cost, mostly config/prompt-engineering work

1. **A persistent, admin-approved team-preference ledger (CodeRabbit Learnings analog).** The
   atlas has a *designed-but-unbuilt* team-preferences overlay
   ([`team-preferences-overlay.md`](../team-preferences-overlay.md), the Q13 mechanism referenced
   throughout `map-gaps.md`); CodeRabbit's Learnings is a validated, in-production version of
   exactly that idea — captured from review-thread conversation, gated by an approval delay,
   exportable via API. Worth reading Learnings' specific UX (capture-from-chat +
   approval-before-effect) as a concrete design reference when Q13 gets built, rather than
   re-deriving the mechanism from scratch.
2. **Declarative path-scoped rule application (Copilot's `applyTo` glob).** A lighter-weight
   precedent for scoping a rule set to a glob than the atlas's manifest-driven `shape:`/`artifacts:`
   routing; worth a comparison pass when that routing is next revisited, though not obviously an
   improvement over what's already built.

### Tier 3 — high differentiation, high infrastructure cost

1. **Whole-repo indexing / RAG (Greptile-style).** The clearest capability gap in kind, not
   degree: every lens here reasons from a diff (or a repo-audit's live reads), never from a
   persistent, pre-built cross-file index built once and queried cheaply on every PR. Building
   this means real infrastructure (an embeddings/graph index, incremental re-indexing on push,
   storage) that doesn't fit a stateless, per-invocation Claude Code skill without a companion
   service. This is the correct-shape but not-yet-built analog of the atlas's own diff-isolation
   finding ([`map-gaps.md`](../map-gaps.md) G22 — cross-change interaction blindness); Greptile's
   full-index approach is one way to close that gap, at real infrastructure cost.

### Not a gap (already covered or deliberately out of scope)

- **Two-tier reasoning effort** (Copilot Low/Medium) — the atlas already has a depth-mode axis
  (comprehensive vs. targeted, [`review-depth-modes.md`](../review-depth-modes.md)) serving a
  similar purpose.
- **Re-review on push** — this is an orchestration/CI-wiring concern
  ([`runbooks/pr-review-automation.md`](../runbooks/pr-review-automation.md)) already documented
  as the caller's responsibility, not a missing skill capability.
- **Multi-platform (GitLab/Bitbucket) support** — a distribution/packaging question, not a review
  *capability* gap; out of scope for this doc.

---

## Open threads (follow-up research, not yet done)

1. **Qodo/CodiumAI, Sourcery, Graphite Diamond, Codacy, DeepSource, Amazon CodeGuru Reviewer,
   Snyk Code, SonarQube's AI features** — none produced adversarially-confirmed claims in this
   pass on the (a)–(e) dimensions (hybrid architecture, static-analysis signals, unique
   capabilities, pricing/deployment, known limitations). A dedicated follow-up pass per product
   is needed before drawing conclusions about them.
2. **Practitioner sentiment / complaints** (false positives, review noise, cost) — searched for,
   but no claim from this angle survived adversarial verification in this pass. Re-run targeting
   this angle specifically (Hacker News threads, r/ExperiencedDevs, G2/Capterra reviews).
3. **CodeRabbit's actual self-hosting/on-prem story** — the specific $15k/month AWS ECS/EKS claim
   was refuted; whether CodeRabbit offers self-hosting at all, and at what terms, is unresolved.
4. **Minimum-viable architecture for tier-1 gaps 1–3 above** — given the atlas runs as stateless
   Claude Code skills/commands per invocation (no backend service), what's the smallest addition
   that lets a lens shell out to an already-configured linter/SAST tool and use its output as
   evidence, without building a persistent service? This is the natural next design question, not
   yet answered here.
