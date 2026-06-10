# Tool rules to triage — checking-restraint

## Contents
- From category #11
- From category #15

## From category #11

### Tooling rules worth lifting
- **Duplication detectors:** jscpd (Rabin-Karp, 150+ languages, pmd-cpd report format), PMD **CPD**, SonarQube **`S4144`** (methods should not have identical implementations) + duplication-density, Simian. *Caveat:* these find duplication, but the counterweight says **not all duplication should be DRY'd** — coincidental duplication that evolves separately should stay duplicated.
- **Dead/unused-code:** knip, ts-prune, Vulture (Python), staticcheck `U1000`, RuboCop `Lint/UselessAssignment` — find speculative/unused abstractions and config.
- *Over-abstraction itself is largely un-tooled* → an LLM-judgment heuristic (map-gaps G5).

## From category #15

### Tooling rules worth lifting
- **ESLint `eslint-plugin-react`** `react/jsx-no-bind` and **`react-hooks/exhaustive-deps`** — inline closures / wrong deps cause needless re-renders & re-allocation on the render hot path.
- **ESLint** `no-await-in-loop` — sequential awaits in a loop (serialized I/O round-trips that often should be batched/`Promise.all`).
- **RuboCop Performance** cop family, e.g. `Performance/Detect`, `Performance/Count`, `Performance/RedundantMerge`, `Performance/StringReplacement`, `Performance/CollectionLiteralInLoop`, `Performance/MapCompact` — idiomatic-but-slow patterns and allocation in loops.
- **SonarQube** `java:S2864` (don't call both `keySet()` and `get()` — iterate `entrySet()`), and the general "this loop is O(n²)" / "string concatenation in loop" hotspot rules. `(verify)` exact squids.
- **golangci-lint** `prealloc` (slice not preallocated before append in a loop), `bodyclose` (HTTP response body not closed → leak/perf), `ineffassign`, and `gocritic`'s `rangeValCopy`/`hugeParam` (large struct copies).
- **Database / ORM N+1 detectors:** Rails **Bullet** gem (N+1 query and unused-eager-loading detection); Django `nplusone` / `django-debug-toolbar` SQL panel; Hibernate `hibernate.generate_statistics` + N+1 alerts; ent/Prisma query logging. Lift the *pattern*: a list view that issues one query per row.
- **Lighthouse / `lighthouse-ci`** budgets — performance score plus `total-byte-weight`, `unused-javascript`, `render-blocking-resources`, `largest-contentful-paint`, `interaction-to-next-paint` audits as CI gates.
- **`bundlesize` / `size-limit` / webpack-bundle-analyzer** — enforce a max gzipped bundle budget per entrypoint; fail CI on regressions.
- **clippy** (Rust) `clippy::needless_collect`, `clippy::redundant_clone`, `clippy::or_fun_call` (eager arg evaluation) — avoidable allocation/work.
- **DB `EXPLAIN`/`EXPLAIN ANALYZE`** + tools like `pganalyze` / pt-query-digest — surface seq scans, missing indexes, and the literal cost of the hot query.
