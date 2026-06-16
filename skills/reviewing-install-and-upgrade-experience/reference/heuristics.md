# Reviewable heuristics — reviewing-install-and-upgrade-experience

## Contents

- From category #33

## From category #33

### Reviewable heuristics (skill-checklist seeds)

- **Install from scratch still works:** following only the documented steps from a clean checkout / empty environment, does setup succeed — no undocumented prerequisite, no manual step the change silently introduced? A new setup step with no installer or doc update is an adoption regression (cross #22 README front-door).
- **Upgrade is mechanical and hand-off-able:** can a consumer move from the previous version to this one by following a single documented path — ideally a codemod / `migrate` command, otherwise a copy-pasteable checklist — without reverse-engineering the diff? A change that renames, moves, or removes a consumer-facing knob needs an automated migration or an explicit "to upgrade: …" note, not just a changelog line. This is the gap between a version bump an agent can complete-and-verify and one a human must babysit.
- **Breaking changes are signaled and versioned:** is every consumer-facing break (config key, CLI flag, public default, file layout, output format) reflected in a SemVer-major bump and called out as `BREAKING` with before→after, so SemVer-aware upgrade tooling and agents can detect and gate on it (cross #13, #24)? A break under a patch/minor bump silently breaks every automated upgrade.
- **Config is validated, fail-fast, and actionable:** is new configuration validated at startup against a schema, failing with a message that names the offending key *and the fix* — not a deep stack trace, and not a silent wrong default that surfaces much later (cross #26)?
- **Existing config keeps working or is migrated:** does a current adopter's existing configuration still load after this change — new keys optional with safe defaults, no silent semantic change to an existing key — or is there an automatic migration and a clear rename path?
- **Safe defaults; zero-config common case:** does the change work out of the box for the common case with little or no configuration, keeping new complexity behind optional knobs, rather than requiring the adopter to set several values before first success (cross #11 restraint — a new *required* knob is the friction to question)?
- **Time-to-first-success stays low:** does the quickstart still get a new adopter to a working result in a few steps, and does this change avoid adding required steps to that path? Prefer a quickstart that runs in CI so it cannot rot (cross #22 runnable example).
- **Deprecate, don't yank:** is a removed or renamed consumer surface kept working for a deprecation window with a runtime warning that names the replacement, rather than removed in place (cross #29 retirement-on-a-schedule)?
- **Install / setup is idempotent and reproducible:** is the installer / `init` safe to re-run — no duplicate writes, no clobbering of the consumer's own edits — and does it pin what it installs so two adopters get the same result? An `init` that overwrites a consumer's customizations on re-run is a trap.
- **Upgrade has a downgrade / rollback path:** if the upgrade goes wrong, can a consumer return to the prior version — is the config/data format forward-and-backward compatible across one version (expand/contract), or is it a one-way door with no downgrade (cross #20, #29)?
- **Setup and migration failures are diagnosable, not half-applied:** when install or migration fails, does it say what failed and how to recover, and avoid leaving a half-migrated, wedged state (cross #2 silent failures)?
- **The consumer path was actually exercised:** for a tool, plugin, template, or library, was the install/upgrade run against a real sample consumer (a fresh-adopter dry run), not only unit-tested in-repo? The smoothest adoptions come from dogfooding the exact path a new adopter — or their agent — will take.

---
