# Examples — auditing-dependencies-and-supply-chain

This skill is repo-shaped: its input is a dependency / supply-chain scan. Report
each distinct risk as its own numbered finding. When the scan is healthy, the entire response is exactly this skill's no-finding sentence given in the decision rule below — never a numbered list of findings for a healthy scan.

**Decision rule (apply before flagging):** flag a dependency only for a concrete
risk signal — a known CVE, no pin/lockfile drift, abandonment (years without
maintenance + single maintainer), an incompatible license, install scripts, or a
typosquat-adjacent name. Age alone, popularity alone, or "I would have chosen a
different library" are not findings. Cite only risk signals the scan actually
shows: an empty `cves` column means there is NO CVE finding — never invent a
vulnerability, a version number, or a license problem the scan does not contain. If every dependency is pinned, scanned clean,
licensed compatibly, and maintained, report exactly
"No findings: dependencies and supply chain are healthy".

## Bad → finding

**Input (dependency scan; project license: MIT, distributed commercially):**

```text
package         version   pinned?  cves          last release  maintainers  license  notes
left-pad-x      ^1.0      no       -             6 years ago   1            MIT      name 1 char off popular pkg
yaml-parse      4.1.2     lock     CVE-2025-881  2 months ago  4            MIT      fix in 4.1.3
report-gen      2.0.0     lock     -             1 month ago   3            AGPL-3.0 postinstall script downloads binary
```

**Expected finding:**

1. **Known CVE with a fix available:** `yaml-parse` 4.1.2 carries CVE-2025-881,
   fixed in 4.1.3 — bump it now.
2. **Typosquat-shaped, abandoned, unpinned:** `left-pad-x` is one character off a
   popular package, single-maintainer, 6 years stale, and floating on `^` with no
   lock entry — verify it's the intended package, pin it, or replace with stdlib.
3. **License incompatibility:** `report-gen` is AGPL-3.0 inside an MIT-licensed
   commercially distributed product — network copyleft obligations likely apply;
   escalate to legal or replace.
4. **Install-script risk:** `report-gen`'s postinstall downloads a binary — an
   unauditable supply-chain surface; vendor a checksummed artifact or build from
   source.

## Good → no finding

**Input (dependency scan; project license: MIT):**

```text
package    version  pinned?  cves  last release  maintainers  license       notes
fastify    5.2.1    lock     -     3 weeks ago   12           MIT           -
pino       9.4.0    lock     -     2 months ago  6            MIT           -
zod        3.24.0   lock     -     1 month ago   8            MIT           renovate enabled
```

**Expected finding:** None — pinned via lockfile, scanned clean, actively
maintained, compatible licenses, automated updates. Report
"No findings: dependencies and supply chain are healthy". Do NOT flag a dependency
merely for being popular, small, or not the auditor's personal preference.
