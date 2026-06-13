# Examples — auditing-documentation-health

This skill is repo-shaped: its input is a docs-vs-code parity scan. Report each
distinct issue as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** a docs finding needs a concrete
mismatch or gap — a documented thing that no longer exists, an existing public
surface with no doc, an example that can't run, a docstring contradicting its
signature. "Could have more docs" is not a finding. If the surface and the docs
agree and examples run, report exactly "No findings: documentation is healthy".

## Bad → finding

**Input (docs parity scan):**

```text
README quickstart:   `pip install acme && acme init` — `acme init` was removed in v3
                     (replaced by `acme setup`); install example imports acme.legacy
public API:          14 endpoints; docs cover 9; /v1/exports (added 4 months ago) undocumented
docstrings:          rotate_keys(key_id, *, force=False) — docstring documents `dry_run`
                     param that was removed; says "returns bool", returns RotationReport
CHANGELOG:           last entry 11 months ago; 6 user-facing releases since
diagrams/arch.png:   binary image, references services deleted in Q1
```

**Expected finding:**

1. **Broken front door:** the README quickstart fails on the first command
   (`acme init` removed) and imports a deleted module — a new user cannot onboard;
   fix and add a CI-checked runnable example.
2. **Undocumented public surface:** 5 of 14 endpoints, including 4-month-old
   `/v1/exports`, have no reference docs.
3. **Docstring contradicts the signature:** `rotate_keys` documents a removed
   `dry_run` param and the wrong return type — worse than no docstring; fix both.
4. **Changelog abandoned:** 6 user-facing releases with no entries — consumers
   can't track changes.
5. **Stale binary diagram:** references deleted services and can't be diffed —
   redraw as text (Mermaid) so drift shows up in review.

## Good → no finding

**Input (docs parity scan):**

```text
README quickstart:   runs in CI (doctest job green)
public API:          22/22 endpoints documented; reference regenerated from schema
docstrings:          signature parity check green
CHANGELOG:           entry per release, categories + semver impact
ADRs:                12, latest covers the queue migration decision
```

**Expected finding:** None — surface and docs agree, examples are CI-checked, the
changelog is current. Report "No findings: documentation is healthy". Do NOT
demand more documentation volume for its own sake — parity and accuracy are the
bar, not page count.
