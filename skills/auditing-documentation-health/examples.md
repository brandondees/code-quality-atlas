# Examples — auditing-documentation-health

This skill is repo-shaped: its input is a docs-vs-code parity scan. Report each
distinct issue as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** a docs finding needs a concrete
mismatch or gap — a documented thing that no longer exists, an existing public
surface with no doc, an example that can't run, a docstring contradicting its
signature. "Could have more docs" is not a finding. If the surface and the docs
agree and examples run, report exactly "No findings: documentation is healthy".
A scan lists what was actually audited; a category absent from the scan's own
text (no README line, no docstring line, no changelog line) means that
artifact was **not included in this scan**, not that it is missing or stale in
the repository. Never report "No README" / "no docstrings" / "no changelog" as
a finding purely because the scan you were handed doesn't mention one — that is
an inference from silence, not a documented gap; only report a category as
broken when the scan states its actual content (or actual absence) as an
audited fact. This is not a license to declare a scan entirely out of scope
whenever it omits some categories — a scan that describes even one real
documentation artifact (a README, a docstring set, a changelog) is squarely in
scope for that artifact; evaluate what's actually there on its own merits
(including "proportionate for this project's size and audience" as a valid
verdict) rather than treating a scan as not-applicable just because it isn't
exhaustive across every category this lens could check.

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

## Good → no finding (minimal but present, proportionate to the project)

**Input (scan):**

```text
Repo: a personal backup script used by one person, no other users, no CI.
Docs: a single README covering install and the two commands it has; both
commands match the README's usage examples exactly. No ADRs, no changelog,
no runbook — the author has no need for them at this scale.
```

**Expected finding:** None. There **is** a documentation artifact here — a
README — and it matches the surface exactly, so evaluate it on its own
merits rather than opening with what's absent. Report "No findings:
documentation is healthy". The missing ADRs/changelog/runbook are not a
finding: a one-person tool with no other users or support burden has no
audience for them, and demanding parity with a public-facing project's
documentation bar here would be exactly the "could have more docs" non-finding
this lens's own decision rule already excludes. Do NOT report "Not
applicable" — a real documentation artifact was provided and checked; this is
a "checked and clean" verdict, not an out-of-scope one.

## Not applicable → outside this lens's scope

**Input (scan):**

```text
Dependency audit only: 118 direct + transitive packages, 3 with known CVEs
(2 medium, 1 low), all have available fixed versions, none are unmaintained.
No README, docstring, changelog, ADR, runbook, or any other documentation
artifact was included in this scan.
```

**Expected finding:** This scan is outside this lens's scope — it contains
only dependency/CVE data, which this lens's checklist does not cover, and no
documentation artifact was included to audit. Report "Not applicable: this
scan contains no documentation artifact for this lens to audit" — never "No
README" / "no changelog" / "no ADRs" as findings. The scan's silence on
documentation means documentation was **not part of this scan**, not that it
doesn't exist in the repository; inferring the latter from the former is a
fabricated finding, not a real one. Do NOT report "No findings: documentation
is healthy" either — that sentence means documentation was checked and found
to match the surface, which implies there was documentation content to check.
There wasn't any in this scan.
