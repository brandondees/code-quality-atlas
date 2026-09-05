# SPDX-License-Identifier: MIT
# tooling/generate_doc_counts.py
"""Renders the manifest's skill/lens/audit counts directly into the handful of
hand-authored prose files that quote them, so those digits can't drift from
`skills/manifest.yaml` by construction (issue #372).

Before this module, `tests/test_doc_counts.py` chased the same goal with a
free-text sweep: scan every "living" doc for any two-digit number (or spelled-
out equivalent) sitting near the words skill/lens/audit/zip/upload, and assert
it equalled a current manifest count. That detector self-inflicted four false-
positive escalations (issues #131, #206, #219, #220) as its keyword/proximity
heuristics were patched again and again. The fix here is the same one
`generate_router.py`'s `n_repo_audits` already applies to router prose
("Derived, not hardcoded"): stop guessing which numbers are counts and instead
render the counts themselves at generate time, at each occurrence's exact
location. A regenerate-and-diff CI gate (mirroring the one already guarding
`skills/` and `collapsed/`) then catches drift the same way template drift is
already caught elsewhere — no detector left to fool.

Scope is deliberately the 7 files issue #372 names plus the 3 issue #420
added, not every doc that mentions a count — see the file list on
`_TEMPLATE` below. docs/session-log.md, docs/plans/**, and docs/taxonomy.md
stay hand-authored narrative logs that intentionally freeze *past* counts,
the same way the old sweep's own file scope excluded them.

Three locations the old sweep *did* cover were briefly unmanaged after #372
narrowed scope to that issue's literal 7-file list (PR #419 review,
dees-bot): `tooling/vendor-skills.sh` and `tooling/package-account-zips.sh`
both hardcode "the 44 standalone skills" in comments and `--help` text, and
docs/open-questions.md's Q8 answer named the repo-shaped-audit count in
prose. Issue #420 closed the gap: `CountOccurrence`'s prefix/suffix
substitution is plain-text and was never markdown-specific, so the two `.sh`
files needed no code change, only new `_TEMPLATE` entries below. Q8's count
was spelled out ("eleven") rather than a digit, so it couldn't be matched by
the digit-only `pattern()` regex as-is; rather than teach this module a
words-to-digits round trip for one call site, the doc itself was changed to
the digit form ("11"), which is also what every other `_TEMPLATE` occurrence
already uses. Q8's now-inert `<!-- doc-counts:live -->` marker (a leftover
from the old sweep that nothing has read since #372) was removed rather than
kept as a second, redundant source of truth alongside the anchor entry."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tooling.manifest import Manifest

CountKey = str  # one of "lenses", "diff", "repo", "total"


class DocCountAnchorError(ValueError):
    """Raised when a `_TEMPLATE` anchor doesn't match exactly once — a stale
    template entry or prose edited out from under it, not an internal failure.
    Subclasses ValueError so it reads as the bad-anchor condition it is, while
    giving a caller a precise type to catch (so an unrelated internal
    ValueError elsewhere in the render path still surfaces as a bug instead of
    being misreported as "documented count(s) out of sync") — mirroring
    `generate_collapsed.CollapsedOverlapError`'s identical rationale."""


def compute_counts(manifest: Manifest) -> dict[str, int]:
    """The four counts every occurrence below renders. `total` includes the
    composition skills (router, tool-grounding pre-pass, synthesizer) the same
    way `skills/` itself does — one directory each — so it stays comparable to
    `test_skills_dir_matches_manifest`'s directory count."""
    composition = (
        (1 if manifest.router else 0)
        + (1 if manifest.prepass else 0)
        + (1 if manifest.synthesizer else 0)
    )
    return {
        "lenses": len(manifest.skills),
        "diff": sum(1 for s in manifest.skills if s.shape == "diff"),
        "repo": sum(1 for s in manifest.skills if s.shape == "repo"),
        "total": len(manifest.skills) + composition,
    }


@dataclass(frozen=True)
class CountOccurrence:
    """One count-bearing digit token in a hand-authored doc: the file it lives
    in, which manifest count it must render (`count_key`), and enough literal
    text on either side of the digits to locate that specific occurrence — not
    just "some tracked count is nearby," the loose match that made the old
    sweep both noisy and blind by turns. `prefix`/`suffix` are matched
    literally (via `re.escape`), so they must be copied verbatim from the
    file's current content; either may span a newline when the count wraps
    across a line break in the source prose."""

    path: str  # repo-relative, e.g. "README.md"
    count_key: CountKey
    prefix: str
    suffix: str = ""

    def pattern(self) -> re.Pattern[str]:
        return re.compile(re.escape(self.prefix) + r"(\d+)" + re.escape(self.suffix))


# One entry per count occurrence named in issue #372. Every anchor was copied
# verbatim from the live file content and each is checked (by `sync_doc_counts`)
# to match exactly once before being trusted — a doc edit that removes or
# reworks the surrounding prose out from under an anchor fails generation
# loudly instead of silently leaving that occurrence unmanaged.
#
# The "(4)" / "4 collapsed entrypoints" / "4 zips" figure appearing throughout
# several of these files is a *different* metric (the collapsed-entrypoint
# count, not the manifest's lens/diff/repo/total) and is out of scope here —
# left as hand-authored literals, same as any `25+`/`33+` threshold claim.
_TEMPLATE: tuple[CountOccurrence, ...] = (
    # -- README.md --
    CountOccurrence("README.md", "total", "**", " review skills**,"),
    CountOccurrence("README.md", "lenses", "- **", " review lenses**"),
    CountOccurrence(
        "README.md",
        "lenses",
        "| [`skills/`](skills/) | The ",
        " lenses + the three composition skills:",
    ),
    # -- .claude-plugin/plugin.json --
    CountOccurrence(
        ".claude-plugin/plugin.json",
        "lenses",
        "A research-derived suite of ",
        " code-review and maintenance lenses covering",
    ),
    # -- .claude-plugin/marketplace.json --
    CountOccurrence(
        ".claude-plugin/marketplace.json",
        "total",
        '"description": "',
        " code-review and maintenance skills derived from",
    ),
    CountOccurrence(
        ".claude-plugin/marketplace.json",
        "diff",
        "research atlas: ",
        " diff-shaped review lenses, ",
    ),
    CountOccurrence(
        ".claude-plugin/marketplace.json",
        "repo",
        "diff-shaped review lenses, ",
        " repo-shaped audits,",
    ),
    # -- docs/distribution.md --
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "## Two forms: standalone (",
        ") vs collapsed (4)",
    ),
    CountOccurrence(
        "docs/distribution.md", "total", "- **Standalone (", " skills)** — the default."
    ),
    CountOccurrence(
        "docs/distribution.md", "lenses", "One `SKILL.md` per lens (", ") plus the"
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "vendored folders instead of ",
        ", at the cost of one extra `Read` per lens.",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "standalone skill — lenses *and* composition skills — ~",
        " total. Each zip is a single",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "tooling/package-account-zips.sh               # ",
        " zips -> dist/account-skills/",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "(`collapsed/skills/`) instead of the ",
        " standalone skills — far fewer GUI uploads,",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "with the lenses bundled and loaded on demand. Pick **one form**: the ",
        " standalone",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "For the **standalone** form the ~",
        " uploads are unavoidable",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "tooling/vendor-skills.sh ~/code/my-service              # ",
        " standalone skills",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "`--collapsed` vendors the 4 collapsed entrypoints instead of the ",
        " standalone\nskills.",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "`.claude/skills/` carries a self-vendored copy of its ",
        " lenses (`tooling/",
    ),
    CountOccurrence(
        "docs/distribution.md",
        "total",
        "`--force` to overwrite it anyway. `--collapsed` vendors the 4\n  collapsed entrypoints instead of the ",
        " standalone skills. `--dry-run`",
    ),
    # -- docs/install.md --
    CountOccurrence(
        "docs/install.md",
        "total",
        "`reviewing-an-artifact`) instead of ",
        ", bundling each shape's lenses and loading",
    ),
    CountOccurrence(
        "docs/install.md",
        "total",
        "All ",
        " standalone skills load with provenance intact (4 in the collapsed form",
    ),
    CountOccurrence(
        "docs/install.md",
        "total",
        "of the standalone plugin's ",
        " skills, router, and `commands/`, none of which ship",
    ),
    # -- docs/collapsed-entrypoints-and-depth-modes.md --
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "total",
        "bundles) — ",
        " tedious, error-prone uploads. See",
    ),
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "lenses",
        "~1% of context and drops descriptions beyond it; with ",
        " top-level lenses the",
    ),
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "total",
        "the existing **standalone** form (",
        " skills, unchanged",
    ),
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "total",
        "removing the ~",
        "-upload",
    ),
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "lenses",
        "→ skills/<lens>/            (standalone, ",
        "; unchanged)",
    ),
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "repo",
        "fields: diff lenses → `reviewing-a-change`; the ",
        " audits → `auditing-a-repository`;",
    ),
    CountOccurrence(
        "docs/collapsed-entrypoints-and-depth-modes.md",
        "lenses",
        "don't collide with the ",
        " lens\n  names.",
    ),
    # -- tooling/vendor-skills.sh (issue #420) --
    CountOccurrence(
        "tooling/vendor-skills.sh",
        "total",
        "# Which tree to vendor: the ",
        " standalone skills (default) or the 4 collapsed",
    ),
    CountOccurrence(
        "tooling/vendor-skills.sh",
        "total",
        "  --collapsed   Vendor the 4 collapsed entrypoints (collapsed/skills/) instead of\n"
        "                the ",
        " standalone skills (skills/)",
    ),
    # -- tooling/package-account-zips.sh (issue #420) --
    CountOccurrence(
        "tooling/package-account-zips.sh",
        "total",
        "#   tooling/package-account-zips.sh --collapsed     # the 4 collapsed entrypoints instead of the ",
        " skills",
    ),
    CountOccurrence(
        "tooling/package-account-zips.sh",
        "total",
        "# Which tree to package: the ",
        " standalone skills (default) or the 4 collapsed",
    ),
    CountOccurrence(
        "tooling/package-account-zips.sh",
        "total",
        "  --collapsed    Package the 4 collapsed entrypoints (collapsed/skills/) instead\n"
        "                 of the ",
        " standalone skills (skills/)",
    ),
    # -- docs/open-questions.md (issue #420) --
    CountOccurrence(
        "docs/open-questions.md",
        "repo",
        "**Yes, and the cron shape is built for detection:** the ",
        " repo-shaped audits (including `finding-maintainability-hotspots`) are scheduled",
    ),
)

# docs/review-depth-modes.md is in the issue's file list but, verified, quotes
# no skill/lens/audit count today (only unrelated 2-4/3-8 depth-breadth
# figures) -- no template entries needed for it.


def sync_doc_counts(manifest: Manifest, docs_root: str = ".") -> list[Path]:
    """Render every `_TEMPLATE` occurrence's digits from `manifest`'s current
    counts, rewriting a file only when its content actually changes. Returns
    the list of files rewritten (empty when everything was already current —
    the expected, common case once `skills/manifest.yaml` stops moving).

    Raises `DocCountAnchorError` naming the file and anchor when an occurrence's anchor
    text doesn't match exactly once in the file's current content — either it
    was never there (a stale template entry) or the surrounding prose has
    since been edited out from under it. Either way, that's a bug to fix in
    this module or the doc, not something to silently skip: a template entry
    that stops matching is exactly the drift this module exists to prevent.

    Every file is rendered and validated in memory before any file is written,
    so a bad anchor in one file can't leave an earlier file already rewritten
    while a later one fails — either the whole batch renders cleanly and is
    written, or nothing is (PR #419 review)."""
    counts = compute_counts(manifest)
    by_file: dict[str, list[CountOccurrence]] = {}
    for occ in _TEMPLATE:
        by_file.setdefault(occ.path, []).append(occ)

    to_write: dict[Path, str] = {}
    for rel_path, occurrences in by_file.items():
        file_path = Path(docs_root, rel_path)
        original = file_path.read_text(encoding="utf-8")
        text = original
        for occ in occurrences:
            pattern = occ.pattern()
            matches = pattern.findall(text)
            if len(matches) != 1:
                raise DocCountAnchorError(
                    f"{rel_path}: expected exactly one match for anchor "
                    f"{occ.prefix!r} ... {occ.suffix!r} (count_key={occ.count_key!r}), "
                    f"found {len(matches)} -- the surrounding prose likely changed; "
                    "update the anchor in tooling/generate_doc_counts.py"
                )
            new_value = str(counts[occ.count_key])
            text = pattern.sub(
                lambda _m, o=occ, v=new_value: o.prefix + v + o.suffix,
                text,
                count=1,
            )
        if text != original:
            to_write[file_path] = text

    for file_path, text in to_write.items():
        file_path.write_text(text, encoding="utf-8")
    return list(to_write)
