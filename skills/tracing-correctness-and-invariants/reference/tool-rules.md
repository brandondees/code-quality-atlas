# Tool rules to triage — tracing-correctness-and-invariants

## Contents
- From category #1
- From category #4

## From category #1

### Tooling rules worth lifting
- **ESLint (all in `recommended`):** `no-unreachable` (code after return/throw/break), `no-unreachable-loop` (body runs ≤1×), `no-fallthrough` (switch fallthrough), `no-constant-condition` & `no-constant-binary-expression` (always-true/false → dead branch or bug), `no-dupe-keys` / `no-dupe-args` (silently dropped), `no-self-assign` / `no-self-compare`, `no-unmodified-loop-condition` (likely infinite loop), `array-callback-return` (map/filter/reduce callback missing return), `default-case-last`, `no-cond-assign` (`=` where `==` meant).
- **typescript-eslint (type-checked):** `no-unnecessary-condition` (type is always truthy/falsy → dead branch), `switch-exhaustiveness-check` (non-exhaustive union switch), `no-base-to-string` (stringifies `[object Object]`).
- **RuboCop Lint:** `Lint/UnreachableCode`, `Lint/UnreachableLoop`, `Lint/DuplicateMethods`, `Lint/IdentityComparison` (`equal?` when `==` meant), `Lint/UselessAssignment`.
- **Dead-code detectors:** Vulture (Python), ts-prune / Knip (TS), `golang.org/x/tools/cmd/deadcode`, staticcheck `U1000` (unused), RuboCop `Lint/UselessAssignment`.

## From category #4

### Tooling rules worth lifting
- **Go:** `bodyclose` (HTTP response body), `sqlclosecheck` (`database/sql`), `rowserrcheck` (`rows.Err()`), `go vet lostcancel` (context), `ineffassign` (state written, never read).
- **Python:** Pylint `R1732` (`consider-using-with` — use a context manager), Ruff `SIM115` (open without context manager), Bandit `B110`.
- **RuboCop:** `Lint/FloatComparison` (exact `==`/`!=` on floats), `Lint/UselessAssignment` (state never read).
- **ESLint:** `no-unused-vars` (dead state); time/money have thin core-rule coverage → heuristic-led.
- **C/C++:** Valgrind/Memcheck, AddressSanitizer + LeakSanitizer (handle/memory leaks).
