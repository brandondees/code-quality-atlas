---
name: reviewing-install-and-upgrade-experience
description: 'Reviews a change for the experience of the people who consume this software
  — installing, configuring, and upgrading it — distinct from the decision-lifecycle
  lens''s "should we adopt this dependency" call and from end-user product UX. Covers
  setup friction and undocumented prerequisites; configuration ergonomics (safe defaults,
  schema validation, fail-fast actionable errors, backward-compatible keys); and upgrade/migration
  smoothness — especially whether a consumer or a code agent can complete and verify
  the upgrade from the docs alone: a codemod or migration command, SemVer-correct
  breaking-change signaling, deprecation windows over silent removals, and a downgrade
  path. Use when reviewing installers, setup/init scripts, packaging, CLI and config
  surfaces, upgrade or migration guides, or release/versioning changes — or anything
  a downstream project adopts (a tool, plugin, template, or library). Skip when the
  change has no consumer-facing install, config, or upgrade surface.'
provenance:
  taxonomy_version: v0.8
  built_from:
  - category: 33
    source: docs/research/cluster-6-evolution.md#33
    hash: bed0e0fed59d2f2d4d499b0cd7064b399dca5d23840f94c366edfe2ddc02c4c6
---

# reviewing-install-and-upgrade-experience

*Can a consumer install, configure, and upgrade this cleanly — even hand it to an agent? Setup friction, config UX, version-bump smoothness, migration path.*

## When to use

Reviews a change for the experience of the people who consume this software — installing, configuring, and upgrading it — distinct from the decision-lifecycle lens's "should we adopt this dependency" call and from end-user product UX. Covers setup friction and undocumented prerequisites; configuration ergonomics (safe defaults, schema validation, fail-fast actionable errors, backward-compatible keys); and upgrade/migration smoothness — especially whether a consumer or a code agent can complete and verify the upgrade from the docs alone: a codemod or migration command, SemVer-correct breaking-change signaling, deprecation windows over silent removals, and a downgrade path. Use when reviewing installers, setup/init scripts, packaging, CLI and config surfaces, upgrade or migration guides, or release/versioning changes — or anything a downstream project adopts (a tool, plugin, template, or library). Skip when the change has no consumer-facing install, config, or upgrade surface.

**Shape: diff — design-capable.** Also works on design docs and plans: apply the same checks to the proposed states, data flows, and failure paths before any code exists.

## Reviewer discipline

Report only real problems. If the code correctly handles the case, reply "No findings" and stop — do not invent issues. This guards against false positives on correct code; still report every genuine issue you do find, with its full detail.

**Defects are the default; improvements are opt-in.** By default this lens is defect-only: do not suggest changes to code that is already correct. When the team has opted up into improvement suggestions, a finding on already-correct code is admissible only as `nit`-severity, `route: implementer` (the author applies, defers, or ignores), and must clear the non-configurable anti-churn floor: it must genuinely *improve* — never offer a merely equivalent alternative — and must converge (once a dimension is as good as you can confidently make it, stop; never oscillate A→B then B→A, never re-order to an equivalent state). Defects keep the strict bar above regardless of this setting.

**Pre-existing defects in touched code are surfaceable, not yours to fix.** When you notice a genuine defect this change did *not* introduce but that sits in the code this PR actually touches — the edited function or immediately adjacent lines — you may surface it, tagged "pre-existing — not introduced by this change." Like improvements it is opt-in and default-quiet (off unless the team opts up), `route: implementer`, and non-blocking: it informs the author's fix-now / file-a-ticket / ignore call and never sets this PR's verdict, because the diff did not cause it. Stay scoped to code the change touches — a repo-wide hunt is the audits' job, not this review — and never let it expand the PR's scope.

## Top checks

The head of the full checklist — enough for a first pass without opening any reference file:

- **Upgrade is mechanical and hand-off-able:** can a consumer move from the previous version to this one by following a single documented path — ideally a codemod / `migrate` command (dry-run-able, idempotent), otherwise a copy-pasteable checklist — without reverse-engineering the diff? A rename/move/removal of a consumer-facing knob needs an automated migration or an explicit "to upgrade: …" note, not just a changelog line — *and* a verification step (tests green / build passes / re-run diff empty) an agent can run to confirm a clean result. This is the gap between a version bump an agent can complete-and-verify and one a human must babysit.
- **Version vs. changelog/bump are consistent:** does the proposed version bump and the changelog (and the Conventional-Commit `!`/footer) actually match the break surface in the diff? A correctly-implemented but mis-versioned change still mis-drives downstream automation (cross #24).
- **No co-existence / co-installability collision:** does the change hardcode a port, host path, temp-file name, or global resource that collides with another instance/app on the same host, or add a dependency with an unsatisfiable peer/transitive constraint (resolved only via `--legacy-peer-deps`/`--force`)? (catches "breaks a system that already has X installed".)
- **The consumer path was actually exercised:** for a tool, plugin, template, or library, was the install/upgrade run against a real sample consumer (a fresh-adopter dry run), not only unit-tested in-repo? The smoothest adoptions come from dogfooding the exact path a new adopter — or their agent — will take.
- **Install from scratch still works:** following only the documented steps from a clean checkout / empty environment, does setup succeed — no undocumented prerequisite, no manual step the change silently introduced? A new setup step with no installer or doc update is an adoption regression (cross #22 README front-door).
- **Breaking changes are signaled and versioned (the whole contract):** is every consumer-facing break — not just typed API, but CLI flags, exit codes, env vars, config keys *and their semantics*, default values, output/serialization format, log format, file/dir layout (the Hyrum's-law surface) — reflected in a SemVer-major bump and called out as `BREAKING` with before→after, so SemVer-aware tooling and agents can gate on it (cross #13, #24)? A break under a patch/minor bump auto-merges into consumers.
- **Config is validated, fail-fast, and actionable:** is new configuration validated at startup against a schema (unknown keys rejected, not silently ignored), failing with a message that names the offending key *and the fix* — not a deep stack trace, not a silent wrong default that surfaces much later (cross #26)?
- **Existing config keeps working or is migrated:** does a current adopter's existing configuration still load after this change — new keys optional with safe defaults, no silent semantic change to an existing key — or is there an automatic migration and a clear rename/alias path?
- **Safe defaults; zero-config common case:** does the change work out of the box for the common case with little or no configuration, keeping new complexity behind optional knobs and making each new default the secure one, rather than requiring the adopter to set several values before first success (cross #11 restraint — a new *required* knob is the friction to question)?
- **Time-to-first-success stays low:** does the quickstart still get a new adopter to a working result in a few steps, and does this change avoid adding a required step, gate, or credential to that path? Prefer a quickstart that runs in CI so it cannot rot (cross #22 runnable example).
- **Deprecate, don't yank:** is a removed or renamed consumer surface kept working for a deprecation window — with a runtime warning that names the replacement at the point of use and a stated removal version/date — rather than removed in place (cross #29 retirement-on-a-schedule)?
- **Install / setup is idempotent and reproducible:** is the installer / `init` safe to re-run — guard every append/create so a second run is a no-op, no clobbering the consumer's own edits — and does it install from a committed lockfile with a pinned toolchain so two adopters get identical bytes? An `init` that overwrites customizations on re-run, or a `>>`/`tee -a` with no "already present?" guard, is a trap.

## Mechanizing these checks

Where a finding here is one a tool can catch deterministically, surface that as an advisory `route: implementer` note next to the finding: the hand review caught it this time, and wiring the matching tool from [reference/tool-rules.md](reference/tool-rules.md) into CI gates it going forward. This is a suggestion to mechanize, not a defect — it never blocks a verdict, and it falls away on a repo that already runs the tool.

## Going deeper

- [reference/heuristics.md](reference/heuristics.md) — the full checklist; open it when the change sits squarely in this lens's domain.
- [examples.md](examples.md) — concrete good/bad findings, and the output format to match.
- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules covering the mechanical subset; for wiring up linters, not needed for the judgment review itself.
- [reference/sources.md](reference/sources.md) — the research behind each check; for provenance, not needed during a review.
