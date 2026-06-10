# Tool rules to triage — finding-maintainability-hotspots

## Contents
- From category #21

## From category #21

### Tooling rules worth lifting
- **CodeScene** — *Hotspot* (high change-frequency × high complexity), *Change Coupling*, *Code Health* decline, *Knowledge Loss / off-boarded code*, *Brain Method / Brain Class* — VCS-aware maintainability signals. `(verify)` exact metric names.
- **SonarQube** — `Maintainability` rating (A–E), *Technical Debt Ratio* (remediation effort ÷ dev cost), *Code Smells* category, rule `java:S3776` Cognitive Complexity is too high, `java:S138` method too long. `(verify)` squids.
- **RuboCop** — `Metrics/AbcSize`, `Metrics/CyclomaticComplexity`, `Metrics/PerceivedComplexity`, `Metrics/MethodLength`, `Metrics/ClassLength` — proxies for change-difficulty.
- **Reek (Ruby)** — `FeatureEnvy`, `DataClump`, `TooManyInstanceVariables`, `RepeatedConditional` — smells that predict ripple edits.
- **ESLint** — `complexity`, `max-depth`, `max-lines`, `max-lines-per-function`, `max-params` — caps that bound per-unit change cost.
- **Lizard / radon (Python)** — cyclomatic complexity (CC), `radon mi` Maintainability Index, `radon cc` per-function — language-agnostic hotspot inputs.
- **PMD** — `CyclomaticComplexity`, `NPathComplexity`, `GodClass`, `ExcessiveImports`, `CouplingBetweenObjects` — fan-out / god-module ripple risk. `(verify)` rule names.
- **`git-of-theseus` / `hercules` / `git-quick-stats`** — repo-level churn, code age, and authorship/bus-factor analytics. `(verify)`.
- **TODO/FIXME/DEBT-tracking linters** (e.g. ESLint `no-warning-comments`, or a `todo-or-die`-style check) — surface *untracked* debt markers so debt is accounted, not invisible.
