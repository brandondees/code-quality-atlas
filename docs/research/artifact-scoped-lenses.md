# Artifact-scoped quality lenses — research & pattern

**Status:** research, 2026-06-12 (web-grounded from the main loop; citations verified today).
**Triggered by:** the observation that the suite holds itself to Anthropic's *Agent Skill authoring
best practices* (D7) but has **no lens that reviews someone else's** `SKILL.md` / agent definition
against that standard — and the owner's broader question of whether that one guide is the only good
reference, and how to host *many* artifact-specific lenses without bloating the top-level kit's
context cost. Logged as [`map-gaps.md`](../map-gaps.md) **G11**.
**Feeds:** the G11 candidate factor (artifact-authoring quality), Q16 (agentic category), and
**Q18** (the artifact-scoped-lens hosting / context-cost architecture).

---

## 1. Two findings, one pattern

This pass set out to answer a narrow question (*is the Anthropic skills guide the only reference
for "well-formed agent artifact"?* — no, there's a whole family) and surfaced a structural one
the narrow question is just one instance of.

1. **The narrow gap (G11).** "Is this `SKILL.md` / agent definition well-authored?" is a real,
   externally-standardized reviewable surface that **no atlas lens owns**. The artifact is a skill
   or agent-config file; the standard is published and concrete (§3). We are arguably a reference
   *implementation* of that standard (the generator + validator enforce it on our own skills) but
   we never turned it into a *review behavior* pointed at other people's skills.

2. **The pattern it instances.** A large and growing class of files are **not application source**
   but carry their own canonical "well-formed X" standard, their own dedicated linters, and their
   own failure modes: Dockerfiles, Terraform, K8s manifests, CI workflows, OpenAPI specs, ADRs,
   changelogs, `AGENTS.md`, model cards, dataset datasheets, `SKILL.md`. Reviewing each is an
   **artifact-scoped lens** — it only applies when that artifact is present, and it judges against
   an artifact-specific rubric, not the generic code-quality clusters. The atlas already ships a
   few of these implicitly (migrations → #20, IaC → #31, CI config → #19, API specs → #13), but
   has never named *artifact-scoped review* as a first-class **shape** the way it named diff,
   repo, and decision shapes.

The owner's framing is the right one: the prize is not "add a SKILL.md lens," it's **a foundational
pattern for hosting an open-ended set of artifact-scoped lenses without paying top-level context
cost for all of them**. §5–§6 are that pattern; §3–§4 are the evidence it rests on.

## 2. The context-cost problem (why "one lens per artifact" naively fails)

The atlas already feels this: the 2026-06-12 discoverability feedback flagged "the harness-level
cost of 22 names in the listing" and that frontmatter descriptions can be dropped from the model's
skill budget. Adding a lens per artifact type makes that strictly worse. The literature says why:

- **Metadata is the always-on tax.** Every installed skill pre-loads its `name` + `description`
  into the system prompt at startup; only the *body* is deferred. "The context window is a public
  good." So N artifact lenses cost N descriptions on *every* session, reviewing or not.
  ([Anthropic, Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices))
- **More tools/lenses measurably degrade selection.** "Too many or overlapping tools can distract
  agents from efficient strategies." ([Anthropic, Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents))
  RAG-MCP quantifies it: flooding the prompt with tool descriptions causes *prompt bloat* and
  *context rot*; retrieving only the relevant tools **more than tripled** selection accuracy
  (43.13% vs 13.62% baseline) and cut prompt tokens >50%. Providers (OpenAI/Anthropic/Google) cap
  hard at ~128 tools. ([RAG-MCP, arXiv 2505.03275](https://arxiv.org/abs/2505.03275))
- **Long context is not free even when it fits.** *Lost in the middle*: a U-shaped attention curve
  (RoPE-induced) drops multi-document QA accuracy 30%+ when the needle moves from the edges to the
  middle, even in long-context models. ([Liu et al., arXiv 2307.03172](https://arxiv.org/abs/2307.03172))
  *Context rot*: Chroma's 2025 study found all 18 frontier models tested (incl. Claude Opus 4,
  GPT-4.1, Gemini 2.5) degrade as input length grows, at every increment. The implication: a big
  bundled catalog isn't just a token bill, it's a *reasoning* tax.

**Conclusion:** artifact-scoped lenses must be **discovered and loaded on demand**, never carried at
the top level. The cost model has to be "pay only when the artifact is present," which is exactly
what progressive disclosure + presence-based activation buy.

## 3. The artifact-standard catalog (the references — beyond the one guide)

The owner's suspicion is correct: the agent-skills guide is one entry in a mature, per-artifact
standards landscape. Each row is a candidate artifact-scoped lens; most have a dedicated linter
whose rule set is the heuristic goldmine (the same "mine the linters" move as phase-1 research).

### AI / agent artifacts
| Artifact | Canonical standard | Dedicated tool / rules | Atlas status |
|---|---|---|---|
| `SKILL.md` / agent skill | [Anthropic skill-authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) (frontmatter limits, <500-line body, one-level refs, ToC>100, no time-sensitive text, single default, eval-first) | our own `manifest.py`/`generate.py` validators (no public linter yet) | **unowned as a review lens** (G11); enforced only on *our* skills |
| `AGENTS.md` / agent instructions | [agents.md](https://agents.md/) (Markdown, no required fields, **nearest-file-wins** cascade; Linux Foundation Agentic AI Foundation since 2025-12) | none canonical | drift covered by #22/#24; *authoring* uncovered |
| MCP server / tool surface | [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices) (confused deputy, token passthrough, tool poisoning); least-privilege scopes, namespacing | — | runtime-security heuristics under #25 (Q16) |
| Model card | [Mitchell et al. 2019, arXiv 1810.03993](https://arxiv.org/abs/1810.03993) (intended use, eval, limitations, ethical considerations) | HF model-card schema | uncovered |
| Dataset datasheet | Gebru et al., *Datasheets for Datasets* (motivation, composition, collection, recommended uses) | — | uncovered |

### API / contract artifacts
| OpenAPI / AsyncAPI spec | [Google AIP](https://docs.cloud.google.com/apis/design) · [Zalando RESTful Guidelines](http://opensource.zalando.com/restful-api-guidelines/) · Microsoft REST guidelines | [Spectral](https://github.com/stoplightio/spectral) (rulesets per API type/maturity), Zally, oasdiff, buf | partially via #13 `reviewing-api-contract-safety` (judgment, not spec-lint) |

### Infrastructure / deployment artifacts
| Dockerfile | Docker official best practices | [hadolint](https://github.com/hadolint/hadolint) (DL3xxx) | #31 / #19 research has the rule IDs |
| Terraform / IaC | HashiCorp style; cloud well-architected | [tflint](https://github.com/terraform-linters/tflint), [Checkov](https://www.checkov.io/), tfsec | #31 |
| K8s manifest / Helm chart | Pod Security Standards | [kube-linter](https://github.com/stackrox/kube-linter) | #31 |
| GitHub Actions workflow | hardening guides; SHA-pinning | [actionlint](https://github.com/rhysd/actionlint), [zizmor](https://github.com/woodruffw/zizmor) (template injection, mutable-tag) | #19 research has these |

### Build / config / docs / decision artifacts
| `package.json`/lockfiles, `.env`, semver, Conventional Commits | 12-factor; [SemVer](https://semver.org/); [Conventional Commits](https://www.conventionalcommits.org/) | commitlint, dependabot | #18/#19/#24 |
| ADR / RFC | [Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) / MADR | adr-tools | #29 `reviewing-decision-lifecycle` (decision shape) |
| Changelog / docs | [Keep a Changelog](https://keepachangelog.com/) · [Diátaxis](https://diataxis.fr/) | — | #22 audit |

The right-hand column is the punchline: **the atlas already touches many of these, but always folded
into a topic cluster, never as a declared artifact-scoped lens with presence-based activation.** That
inconsistency is what made the `SKILL.md` case fall through — there was no "review this *kind of file*"
slot for it to land in.

## 4. Prior art for presence-based activation (how the linter world scopes cheaply)

The orchestrating-linter ecosystem already solved "host dozens of artifact-specific checkers, run
each only when its artifact is present" — worth borrowing wholesale:

- **Activate on artifact presence.** MegaLinter enables a given linter *only if* the matching file
  type / config is found in the repo (e.g. ESLint only when an eslint config or JS files exist).
  Super-linter dispatches by detected language/file type. The check is cheap (a file-glob), the
  expensive checker loads only on a hit.
- **Glob-scoped rule blocks.** ESLint flat-config `overrides`/glob blocks attach a rule set to a
  path pattern with last-match-wins precedence — per-artifact rules co-resident but only applied to
  matching files. pre-commit hooks use the same idea (`files:`/`types:` regexes per hook).
- **Rulesets by artifact subtype.** Spectral ships *different rulesets per API maturity/type*
  (private/partner/public) over the same OpenAPI artifact — scoping isn't just file-type, it's
  *artifact-variant*.

The common shape: **a cheap detector (glob / file-presence / language) gates an expensive, artifact-
specific rubric.** That maps directly onto the atlas's existing "skip when…" clauses and the
SessionStart router hook — which already do presence-style reasoning, just hand-authored.

## 5. The hosting pattern (synthesizing §2–§4 for the atlas)

Three reinforcing mechanisms, all already partially present in the suite, that together let the kit
carry an open-ended set of artifact lenses at near-zero idle cost:

1. **Progressive disclosure, three tiers** (the atlas already does this for content; extend it to
   *lens hosting*). Metadata (always-on) → `SKILL.md` body (on relevance) → bundled rubric files
   (on demand). Anthropic's framing: bundled context is "effectively unbounded" because the agent
   "doesn't need to read the entirety of a skill into context." The artifact rubric (the hadolint-
   style rule list for that file type) lives in a bundled `reference/` file, costing nothing until
   the artifact appears. ([Equipping agents with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills))
2. **Presence-based activation** (§4), formalized. The two axes Q14 already wants to separate —
   *relevance* vs *depth* — are exactly what an artifact detector provides for this lens class:
   relevance is mechanical (is there a `Dockerfile`? a `SKILL.md`? an `*.tf`?), so these lenses can
   be **signal-routed**, not hand-listed in the router table. This is Q14 candidate-3 (signal-based
   matching) with an unusually clean signal: file presence.
3. **One artifact-scoped *shape*, not N top-level lenses.** Rather than 15 new peer skills (15 new
   always-on descriptions — the §2 tax), host them as **one `shape: artifact` family**: a single
   entry-point lens ("reviewing-artifact-conventions") that, on detecting an artifact, loads the
   matching rubric file. The top-level cost is one description; the breadth lives in bundled,
   on-demand rubrics. This mirrors the [code-execution-with-MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
   result (present a large tool surface as on-demand code, ~98.7% token reduction) and the
   tool-retrieval papers ([RAG-MCP](https://arxiv.org/abs/2505.03275), MCP-Zero arXiv 2506.01056,
   ScaleMCP arXiv 2505.06416): **index broadly, load narrowly.**

**Namespacing** ties it together: Anthropic recommends grouping related tools under a common prefix
so the model selects well; an `artifact:*` (or `reviewing-<artifact>-conventions`) naming convention
gives the family a recognizable handle without 15 unrelated names competing in the listing.

## 6. Design implications & options for the suite

This is the part that needs an owner decision (tracked as **Q18**). Three ways to absorb the pattern,
in increasing ambition:

- **(a) Minimal — one new lens, today's mechanisms.** Add `reviewing-skill-and-agent-artifacts`
  (or fold into the Q16 agentic work) as a normal lens with a tight "skip when no `SKILL.md` /
  agent config present" clause. Closes G11; doesn't generalize. One more always-on description.
- **(b) The artifact-scoped shape.** Promote a `shape: artifact` capability (sibling to diff / repo
  / decision), with a shared "detect → load rubric → review against artifact standard" skeleton and
  a manifest `artifacts:` table (artifact → detector glob → rubric source). One entry-point lens;
  rubrics are bundled and regenerable from per-artifact research sections. Generalizes to the whole
  §3 catalog at one description's worth of top-level cost. **Recommended** — it's the pattern the
  owner asked to strengthen, and it directly serves Q14's relevance/depth split.
- **(c) Retrieval-routed lenses.** Go full RAG-MCP: index every lens (artifact and topic) and have
  the router retrieve the relevant set per change rather than carry any of them at the top level.
  Highest leverage on the §2 tax, but it's a harness-level change that breaks D7 portability (needs
  a retrieval step, not plain markdown) — a longer-horizon bet, noted not chosen.

Cross-cutting, regardless of (a)/(b)/(c): the per-artifact rubrics are a **linter-mining research
task** (§3's right-hand tools are the goldmine), and the `SKILL.md` rubric is the worked example we
can author with the highest confidence because we already enforce it on ourselves.

## 7. Open threads

- **Taxonomy placement of artifact-authoring** (the G11 factor): a #30 meta-artifact factor
  (suppression/codegen-drift already live there) vs. a #22/#24 docs/agent-parity factor vs. folding
  agent-artifact authoring into a promoted Q16 category. Lean: meta-artifact (#30) for the generic
  "is this artifact well-formed per its standard," keeping Q16 about *runtime* agent safety. (Three
  distinct agent surfaces: runtime security → Q16/#25; agent-doc drift → #22/#24; **agent-artifact
  authoring → here**.)
- **Detector reliability.** File-presence is a clean signal for most rows; some (an OpenAPI spec
  embedded in code, an ADR with a non-standard path) need content sniffing. Borrow MegaLinter's
  config-or-extension heuristic.
- **Re-gate cost.** A `shape: artifact` skeleton is new behavior → cross-model eval-gate per the
  runbook before it ships (compounds with the already-pending re-gate noted in open-questions).
</content>
</invoke>
