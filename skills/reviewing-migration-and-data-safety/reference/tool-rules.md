# Tool rules to triage — reviewing-migration-and-data-safety

## Contents
- From category #20

## From category #20

### Tooling rules worth lifting
- **strong_migrations** (Rails), **online-migrations** gem, **Django migration checks**, **squawk** (Postgres migration linter) — flag unsafe DDL pre-merge.
- **gh-ost, pt-osc, pgroll, Vitess online DDL** — zero-downtime schema change execution.
- **DB constraints** (NOT NULL, FK, UNIQUE, CHECK) + **transactional DDL** (Postgres) — DB-enforced invariants.
- **`CREATE INDEX CONCURRENTLY`**, add-nullable-then-backfill, `NOT VALID` + `VALIDATE CONSTRAINT` — the safe Postgres idioms.
- **Schema-drift detection** (cross prior-art `schema-drift-detector`); migration dry-run/plan.
