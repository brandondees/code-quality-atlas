# Examples — reviewing-install-and-upgrade-experience

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
