# Tool rules to triage — hunting-silent-failures

## Contents
- From category #2
- From category #4

## From category #2

### Tooling rules worth lifting
- **typescript-eslint:** `no-floating-promises` (unhandled async error/rejection), `no-misused-promises`, `await-thenable`, `require-await`, `no-throw-literal` `(verify name)` (throw `Error`, not strings).
- **ESLint:** `no-empty` (empty catch block), `prefer-promise-reject-errors`, `no-ex-assign`.
- **RuboCop Lint/Style:** `Lint/SuppressedException` (empty `rescue`), `Lint/RescueException` (rescuing `Exception` is too broad), `Lint/ShadowedException`, `Style/RescueStandardError`.
- **Python — Pylint/Ruff/Bandit:** Pylint `W0702` (bare `except:`), `W0703`/`broad-exception-caught`; Ruff `E722` (bare except); Bandit `B110` (`try/except/pass`), `B112` (`try/except/continue`).
- **Go:** `errcheck` (unchecked returned errors), `wrapcheck` `(verify)` (wrap errors crossing boundaries), `nilerr` `(verify)` (returning nil where err is non-nil).
- **Sonar / CWE:** CWE-390 "Detection of Error Condition Without Action"; CWE-391 "Unchecked Error Condition".

## From category #4

### Tooling rules worth lifting
- **Go:** `bodyclose` (HTTP response body), `sqlclosecheck` (`database/sql`), `rowserrcheck` (`rows.Err()`), `go vet lostcancel` (context), `ineffassign` (state written, never read).
- **Python:** Pylint `R1732` (`consider-using-with` — use a context manager), Ruff `SIM115` (open without context manager), Bandit `B110`.
- **RuboCop:** `Lint/FloatComparison` (exact `==`/`!=` on floats), `Lint/UselessAssignment` (state never read).
- **ESLint:** `no-unused-vars` (dead state); time/money have thin core-rule coverage → heuristic-led.
- **C/C++:** Valgrind/Memcheck, AddressSanitizer + LeakSanitizer (handle/memory leaks).
