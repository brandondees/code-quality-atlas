# Distribution & cross-environment reliability

How to get the suite **reliably present** everywhere you run it — local Claude
Code (CLI / desktop / IDE), other `SKILL.md` agents, and especially **Claude
Code web / cloud sessions and routines**, where the plugin install path does
*not* work.

If you just want the happy-path install commands, see [`install.md`](install.md).
This page is the *decision* layer: which channel for which environment, and why.

## The one constraint that decides everything

A skill only runs if its **body** (`SKILL.md`) is on a filesystem the session
reads. Per the [Claude Code on the web
docs](https://code.claude.com/docs/en/claude-code-on-the-web), a **cloud session
loads exactly three things** — and a marketplace plugin is *not* one of them:

| What | Loaded in cloud? | Why |
|---|---|---|
| The reviewed repo's `.claude/skills/` | ✅ Yes | part of the clone |
| Skills **enabled on claude.ai** (account GUI) | ✅ Yes, automatically | attached to your account |
| Your machine's `~/.claude/skills/` | ❌ No | lives on your machine, not in the repo |
| A **marketplace plugin** (`enabledPlugins` / `extraKnownMarketplaces`) | ❌ No | the cloud runtime never runs the plugin-install step |

The [routines docs](https://code.claude.com/docs/en/routines) enumerate what a
cloud session can use — *"shell commands, skills committed to the cloned
repository, and connectors"* — and **plugins are absent from that list**.
`enabledPlugins`/`extraKnownMarketplaces` is a **CLI-local** feature; committing
it to a repo's `.claude/settings.json` has **no effect in web/cloud**. This was
verified the hard way: the snippet committed, and the skills still didn't load.

> **Correction to earlier docs.** A prior version of [`install.md`](install.md)
> claimed the committed marketplace snippet covers Claude Code web sessions. It
> does not — the docs' own "what loads" list excludes plugins. That claim has
> been corrected.

### Why "just fetch it at runtime" can't work either

It's tempting to think a setup script or a manual `/plugin marketplace add` could
pull the suite in. It can't, and the reason is worth recording so nobody burns
time looking for a whitelist that doesn't exist.

Cloud sessions don't get open `github.com` access. Git is rewritten through a
**per-session credential proxy** (`http://127.0.0.1:<port>/git/<owner>/<repo>`)
that is **scoped to the repositories you connected to the session**. Cloning any
*other* repo — even a public one like this marketplace — returns **403**:

```text
fatal: unable to access 'http://127.0.0.1:41729/git/brandondees/code-quality-atlas.git/': 403
```

The network *allowlist* you can configure (npm, PyPI, crates.io, …) governs
**package-registry HTTPS**, not arbitrary `git clone`. There is no "allow this
repo" setting because it isn't a domain rule — it's repo-level authorization in
the proxy. So any channel that fetches the suite at runtime is a dead end in
cloud. The two channels below work precisely because they **fetch nothing**:
account skills come from your account, and vendored bodies are already in the
clone.

## Channel matrix

| Channel | Body lives in | CLI / desktop / IDE | Web / cloud | Repo-independent | Update story |
|---|---|---|---|---|---|
| **Plugin (marketplace)** | plugin cache | ✅ | ❌ **not run in cloud** | ✅ | per-commit; auto/manual refresh |
| **Settings-based marketplace** | plugin cache | ✅ | ❌ **not run in cloud** | ✅ | n/a for cloud |
| **Skulto sync** | personal/project `SKILL.md` dir | ✅ | only if synced into the cloned repo | depends | `skulto pull` / `update` |
| **Repo `.claude/skills/`** (vendored) | the cloned repo | ✅ | ✅ **documented** | ❌ (per repo) | re-vendor on update |
| **Account skills on claude.ai** (GUI) | your Anthropic account | ⚠️ verify for CLI | ✅ **documented, automatic** | ✅ | re-upload on update |

✅ works · ⚠️ conditional · ❌ doesn't apply

## Two forms: standalone (35) vs collapsed (4)

Every channel above can ship the suite in **either of two forms** — install **one
form, not both** (they cover the same lenses):

- **Standalone (35 skills)** — the default. One `SKILL.md` per lens plus the
  `choosing-review-lenses` router and `synthesizing-review-findings` synthesizer.
  Richest top-level discoverability; the most skills to upload/list.
- **Collapsed (4 entrypoints)** — `reviewing-a-change`, `auditing-a-repository`,
  `reviewing-a-decision`, `reviewing-an-artifact`. Each entrypoint bundles its
  shape's lenses under `reference/lenses/<lens>/body.md` and loads them on demand,
  carrying the same relevance-ranked routing, depth modes, and synthesis. Best for
  **cloud / account-skill / context-budget-constrained** surfaces — 4 uploads or 4
  vendored folders instead of 35, at the cost of one extra `Read` per lens.

The collapsed form ships as its own marketplace plugin,
**`code-quality-atlas-collapsed`** (see [`install.md`](install.md)), and the
distribution scripts take `--collapsed` to package/vendor it. Pick the form per
surface; do not install both into the same session.

## Recommendation for a "both" workflow

You review **a known set of your own repos** *and* **occasional arbitrary repos**
in cloud. Two documented channels cover this — no plugin path involved:

- **Arbitrary + known repos in cloud → enable the suite as account skills on
  claude.ai.** This is the only **repo-independent** cloud channel, and the docs
  state account-enabled skills *"are loaded into cloud sessions automatically."*
  One-time upload, then every cloud session on any repo has the suite. This is
  the channel for the arbitrary-repo case that nothing repo-committed can reach.
- **Known repos → also vendor `.claude/skills/`** into each, when you want the
  suite **committed/pinned** with the repo, working in **local CLI offline**, or
  shared with teammates who don't have your account skills. Belt-and-suspenders
  over the account channel.
- **Local CLI keeps using the plugin / Skulto** — the **source of truth** the
  other channels are generated from. The plugin is a *CLI* convenience; it is not
  a cloud channel.

## Channel details

### A. Account skills on claude.ai — repo-independent, the cloud default

The claude.ai web GUI (**Settings → Capabilities / Skills**) offers, alongside
Anthropic's skill packs, **create-custom-skill / upload-a-zip**. A skill enabled
here is attached to *you*, not a repo, and the docs say it loads into cloud
sessions automatically — so it covers every repo, including ones you've never
touched.

Each `SKILL.md` is self-contained, so upload is mechanical. Two practical points
to confirm on first use, since the docs describe the *mechanism* but not these
specifics:

1. **Custom-uploaded skills behave like the Anthropic packs** (i.e. the
   "loaded automatically" statement covers your own uploads, not just first-party
   ones). Verify with a one-skill test before doing the whole set.
2. **One skill per zip — confirmed.** The GUI rejects a multi-skill bundle
   ("must contain exactly one top-level folder"), so it's one upload per lens,
   ~35 total. Each zip is a single `<name>/` folder shipping the runtime
   resources — `SKILL.md`, `reference/`, **and `examples.md`** (a lens opens it
   for the output format) — and excluding the dev-only `evals/`.

[`tooling/package-account-zips.sh`](../tooling/package-account-zips.sh) builds the
upload-ready zips with exactly that inclusion rule:

```bash
tooling/package-account-zips.sh               # 35 zips -> dist/account-skills/
tooling/package-account-zips.sh --collapsed   # 4 zips (the collapsed entrypoints)
```

The `--collapsed` flag packages the **4 collapsed entrypoints**
(`collapsed/skills/`) instead of the 35 standalone skills — far fewer GUI uploads,
with the lenses bundled and loaded on demand. Pick **one form**: the 35 standalone
skills *or* the 4 collapsed entrypoints, not both (see *Two forms* below).

There is **no bulk path** through the GUI: no multi-skill zip, and (per the note
below) no usable API. The ~35 uploads are unavoidable today, which is the cost
that motivates the structural rethink in
[`open-questions.md`](open-questions.md) (fewer top-level skills, more nesting).

> **No programmatic shortcut.** The Claude API has a `POST /v1/skills` (workspace
> scope) that could bulk-create skills, but per the [Agent Skills
> docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
> skills **do not sync across surfaces** — Claude Code loads only filesystem
> skills (`.claude/skills/`) and the claude.ai account-GUI skills, **not** API
> workspace skills. So the GUI upload (or vendoring) is the only path into cloud
> sessions; the API loop won't help here.

**One-skill validation (5 min):** upload one distinctive lens
(`tracing-correctness-and-invariants.zip`), enable it, open a cloud session on an
**unrelated** repo, and ask for a review — confirm that lens is offered. If it
surfaces, upload the rest; if not, fall back to vendoring (B).

### B. Vendor into the target repo — committed, offline, CLI too

Copy each lens's `SKILL.md` into the consuming repo under
`.claude/skills/<name>/SKILL.md` and **commit** it. Both CLI and cloud sessions
on that repo load it automatically; nothing is fetched at runtime, so it is
immune to every cloud failure mode (no marketplace fetch, no plugin install, no
account dependency).

```text
<target-repo>/
└── .claude/
    └── skills/
        ├── choosing-review-lenses/SKILL.md
        ├── synthesizing-review-findings/SKILL.md
        └── …one folder per lens
```

Ship `SKILL.md` and the files a lens loads at runtime — `reference/` and
`examples.md` — and exclude only the dev-only `evals/`.
[`tooling/vendor-skills.sh`](../tooling/vendor-skills.sh) does exactly this from a
code-quality-atlas clone:

```bash
# from inside the code-quality-atlas clone; pass the OTHER repo
tooling/vendor-skills.sh ~/code/my-service              # 35 standalone skills
tooling/vendor-skills.sh ~/code/my-service --collapsed  # OR the 4 collapsed entrypoints
( cd ~/code/my-service && git add .claude/skills && git commit -m "vendor code-quality-atlas review suite" )
```

`--collapsed` vendors the 4 collapsed entrypoints instead of the 35 standalone
skills. **Vendor one form, not both** — the two cover the same lenses.

`skulto install brandondees/code-quality-atlas -y` run inside the target repo is
an equivalent alternative.

**Tradeoff:** bodies are duplicated into each repo and pin to the synced commit —
refresh by re-running the sync and committing the diff. `skulto save` writes a
`skulto.json` that `skulto sync` reproduces for teammates.

### C. Plugin / Skulto — local source of truth (CLI only)

Install the plugin (or Skulto-sync) for **local** CLI / desktop / IDE work, per
[`install.md`](install.md). This repo stays canonical; both the account zips and
the vendored bodies are *generated from it*, so updates have one origin. Do **not**
expect the plugin to appear in cloud sessions — it won't.

## Automation

- **Channel A — [`tooling/package-account-zips.sh`](../tooling/package-account-zips.sh):**
  emits one upload-ready zip per lens (`<name>/SKILL.md` + `reference/` +
  `examples.md`, no `evals/`) for the claude.ai GUI. `--collapsed` emits the 4
  collapsed-entrypoint zips instead.
- **Channel B — [`tooling/vendor-skills.sh`](../tooling/vendor-skills.sh):**
  copies the same runtime resources into a target repo's `.claude/skills/`,
  idempotently, ready to commit. `--prune` safely drops only previously-vendored
  skills that have left the suite (tracked via a `.atlas-vendored` marker; never
  touches the target repo's own skills). `--collapsed` vendors the 4
  collapsed entrypoints instead of the 35 standalone skills. The `skulto` flow
  above is an alternative.

```bash
tooling/vendor-skills.sh ~/code/my-service          # vendor/refresh into that repo
tooling/vendor-skills.sh ~/code/my-service --prune   # also drop stale vendored skills
tooling/vendor-skills.sh ~/code/my-service --collapsed  # the 4 collapsed entrypoints
```
