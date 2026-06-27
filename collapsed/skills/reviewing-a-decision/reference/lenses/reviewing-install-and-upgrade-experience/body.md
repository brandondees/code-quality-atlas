# reviewing-install-and-upgrade-experience

Can a consumer install, configure, and upgrade this cleanly — even hand it to an agent? Setup friction, config UX, version-bump smoothness, migration path.

## When to use

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Checklist

The full review checklist, grouped by the research category each check draws from:

## From category #33

### Reviewable heuristics (skill-checklist seeds)

- **Install from scratch still works:** following only the documented steps from a clean checkout / empty environment, does setup succeed — no undocumented prerequisite, no manual step the change silently introduced? A new setup step with no installer or doc update is an adoption regression (cross #22 README front-door).
- **Upgrade is mechanical and hand-off-able:** can a consumer move from the previous version to this one by following a single documented path — ideally a codemod / `migrate` command (dry-run-able, idempotent), otherwise a copy-pasteable checklist — without reverse-engineering the diff? A rename/move/removal of a consumer-facing knob needs an automated migration or an explicit "to upgrade: …" note, not just a changelog line — *and* a verification step (tests green / build passes / re-run diff empty) an agent can run to confirm a clean result. This is the gap between a version bump an agent can complete-and-verify and one a human must babysit.
- **Breaking changes are signaled and versioned (the whole contract):** is every consumer-facing break — not just typed API, but CLI flags, exit codes, env vars, config keys *and their semantics*, default values, output/serialization format, log format, file/dir layout (the Hyrum's-law surface) — reflected in a SemVer-major bump and called out as `BREAKING` with before→after, so SemVer-aware tooling and agents can gate on it (cross #13, #24)? A break under a patch/minor bump auto-merges into consumers.
- **Config is validated, fail-fast, and actionable:** is new configuration validated at startup against a schema (unknown keys rejected, not silently ignored), failing with a message that names the offending key *and the fix* — not a deep stack trace, not a silent wrong default that surfaces much later (cross #26)?
- **Existing config keeps working or is migrated:** does a current adopter's existing configuration still load after this change — new keys optional with safe defaults, no silent semantic change to an existing key — or is there an automatic migration and a clear rename/alias path?
- **Safe defaults; zero-config common case:** does the change work out of the box for the common case with little or no configuration, keeping new complexity behind optional knobs and making each new default the secure one, rather than requiring the adopter to set several values before first success (cross #11 restraint — a new *required* knob is the friction to question)?
- **Time-to-first-success stays low:** does the quickstart still get a new adopter to a working result in a few steps, and does this change avoid adding a required step, gate, or credential to that path? Prefer a quickstart that runs in CI so it cannot rot (cross #22 runnable example).
- **Deprecate, don't yank:** is a removed or renamed consumer surface kept working for a deprecation window — with a runtime warning that names the replacement at the point of use and a stated removal version/date — rather than removed in place (cross #29 retirement-on-a-schedule)?
- **Install / setup is idempotent and reproducible:** is the installer / `init` safe to re-run — guard every append/create so a second run is a no-op, no clobbering the consumer's own edits — and does it install from a committed lockfile with a pinned toolchain so two adopters get identical bytes? An `init` that overwrites customizations on re-run, or a `>>`/`tee -a` with no "already present?" guard, is a trap.
- **Version vs. changelog/bump are consistent:** does the proposed version bump and the changelog (and the Conventional-Commit `!`/footer) actually match the break surface in the diff? A correctly-implemented but mis-versioned change still mis-drives downstream automation (cross #24).
- **No co-existence / co-installability collision:** does the change hardcode a port, host path, temp-file name, or global resource that collides with another instance/app on the same host, or add a dependency with an unsatisfiable peer/transitive constraint (resolved only via `--legacy-peer-deps`/`--force`)? (catches "breaks a system that already has X installed".)
- **Config precedence is documented and unsurprising:** when a setting can come from defaults/file/env/flags, is the precedence documented and does the higher layer actually win? (catches "env var silently ignored because the file set it".)
- **Upgrade has a downgrade / rollback path:** if the upgrade goes wrong, can a consumer return to the prior version — is the config/data/wire format forward-and-backward compatible across one version (expand/contract; Schema-Registry-style compatibility), or is it a one-way door with no downgrade (cross #20, #29)?
- **Setup and migration failures are diagnosable, not half-applied:** when install or migration fails, does it say what failed and how to recover, and avoid leaving a half-migrated, wedged state (cross #2 silent failures)?
- **Install path is portable and doesn't execute surprises:** do setup scripts avoid single-OS/arch/shell assumptions (GNU-only `sed -i`/`readlink -f`, hardcoded `#!/bin/bash` or `/usr/local`, CRLF, an assumed locale/timezone), and does the install avoid (or justify) lifecycle scripts that run untrusted code (cross #18 supply-chain)?
- **Distribution metadata & teardown are clean:** for a published package/plugin/extension, are `engines`/`requires-python`/compat fields truthful, the manifest valid with minimal/declared permissions, the README registry-renderable, retirement done via deprecate (not silent unpublish), and is enable/disable/**uninstall** reversible with no orphaned files/state? (the distributable-artifact lifecycle; this repo's own `plugin.json`/`atlas-init` are reviewable here.)
- **Agent-followable onboarding:** if the repo carries an `AGENTS.md`/`CLAUDE.md`, does this change keep its build/test/lint/run commands exact and accurate (nearest-file-wins in a monorepo) so an agent can set up/upgrade from it without tribal knowledge (cross #22 docs drift)?
- **The consumer path was actually exercised:** for a tool, plugin, template, or library, was the install/upgrade run against a real sample consumer (a fresh-adopter dry run), not only unit-tested in-repo? The smoothest adoptions come from dogfooding the exact path a new adopter — or their agent — will take.

---

## Examples

This lens reads a change through the eyes of a *consumer* who installs,
configures, and upgrades the software — including a code agent handed the
upgrade. Report each distinct adoption/upgrade problem as its own numbered
finding. When the change keeps the consumer path clean, the entire response is
exactly the no-finding sentence in the decision rule below.

**Decision rule (apply before flagging):** a finding needs a concrete adoption
or upgrade *regression or trap* — a renamed/removed consumer-facing surface with
no migration, a break shipped under a non-major bump, a new required setting with
no default, config that fails late or silently, an `init` that clobbers a
consumer's edits, a one-way upgrade with no rollback. "Could document more" or a
purely internal refactor is **not** a finding. Skip entirely when the change has
no consumer-facing install/config/upgrade surface. If the consumer path is clean,
report exactly "No findings: the install/upgrade experience is intact".

## Bad → finding

**Input (diff summary — a plugin's `v3` release):**

```text
- config: renamed `outputDir` → `output.dir` and `retries` (number) → `retry: {max}`.
  Loader reads only the new keys; old keys are ignored with no warning.
- removed the `acme init --legacy` flag; `acme init` now overwrites an existing
  acme.config.json in place (no backup, no prompt).
- package.json: version 2.7.4 → 2.8.0 (minor). CHANGELOG: one line, "rework config".
- new required env var ACME_TOKEN read at first request; missing → `TypeError:
  undefined is not a function` deep in the request path.
- no migration script, no upgrade notes.
```

**Expected finding:**

1. **Breaking change shipped as a minor bump:** renamed config keys and a removed
   CLI flag are consumer-facing breaks but the version went 2.7.4 → 2.8.0 — every
   Renovate/Dependabot automerge and every agent trusting SemVer will take this as
   safe. Bump to 3.0.0 and mark `BREAKING` with before→after.
2. **Renamed config with no migration or back-compat:** `outputDir`/`retries`
   silently stop working — an existing adopter's config loads to wrong defaults
   with no warning. Either keep reading the old keys (deprecated, with a warning
   naming the replacement) or ship a `migrate` codemod; a one-line changelog is
   not an upgrade path.
3. **Destructive, non-idempotent `init`:** `acme init` overwriting an existing
   config in place with no backup or prompt clobbers a consumer's customizations
   on re-run. Make it idempotent — detect the existing file and prompt/merge/skip.
4. **New required setting fails late and cryptically:** missing `ACME_TOKEN`
   surfaces as a `TypeError` deep in a request instead of a startup validation
   error naming the key and the fix. Validate config at startup, fail fast.
5. **No upgrade path for an agent or a human:** with no migration script and no
   "to upgrade: …" notes, the version bump can't be completed from the docs
   alone — it requires reverse-engineering the diff. Add an upgrade guide or,
   better, an automated migration.

## Good → no finding

**Input (diff summary — same release, done well):**

```text
- config: `output.dir` added; `outputDir` still read, emits a deprecation warning
  naming the replacement and a sunset version (4.0). `acme migrate` rewrites old
  config in place after backing it up.
- `acme init` detects an existing config and prompts (overwrite/merge/skip); safe
  to re-run.
- version 2.7.4 → 3.0.0; CHANGELOG has Added/Deprecated/Removed with an "Upgrading
  to 3.0" section; the quickstart runs in CI on a clean container.
- ACME_TOKEN validated at startup via the config schema → "ACME_TOKEN is required;
  set it in .env or the environment (see docs/config.md)".
```

**Expected finding:** None — breaks are versioned (major) and signposted, the old
config keeps working through a deprecation window with an automated migration,
`init` is idempotent, config fails fast with an actionable message, and the
quickstart is CI-checked. Report "No findings: the install/upgrade experience is
intact". Do NOT demand a migration for a purely additive, backward-compatible
change, or invent friction where the consumer path is clean.

## Going deeper

- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical subset; for wiring linters, not needed for the judgment review.
- [sources.md](sources.md) — the research behind each check; for provenance.
