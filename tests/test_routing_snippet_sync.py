# SPDX-License-Identifier: MIT
# tests/test_routing_snippet_sync.py
"""The /atlas-init command embeds a *fallback* copy of the routing block for
offline/web sessions that can't reach the plugin clone. The template
(`templates/agents-routing-snippet.md`) is the source of truth, but nothing
mechanically tied the embedded copy to it — so a template edit could silently
leave the fallback stale, and offline sessions would install an outdated block
(issue #64). This test fails the build whenever the two diverge.

This repo also dogfoods the template in its own `AGENTS.md` and `CLAUDE.md`
(the routing block a consumer repo would get from `/code-quality-atlas:atlas-init`).
Neither was covered by the check above, which let `CLAUDE.md`'s copy drift
from the template unnoticed (issue #167). Parametrized below alongside the
`atlas-init.md` fallback check so any of the three copies drifting fails CI.
"""
from pathlib import Path

import pytest

_BEGIN = "<!-- BEGIN code-quality-atlas routing -->"
_END = "<!-- END code-quality-atlas routing -->"


def _extract_block(text: str) -> str:
    """Return the BEGIN…END routing block (inclusive), normalized to LF and with
    trailing whitespace stripped per line so fence indentation / CRLF can't cause
    a spurious mismatch."""
    lines = text.replace("\r\n", "\n").split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.strip() == _BEGIN]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == _END]
    assert len(starts) == 1, f"expected exactly one {_BEGIN!r}, found {len(starts)}"
    assert len(ends) == 1, f"expected exactly one {_END!r}, found {len(ends)}"
    assert ends[0] > starts[0], "END marker precedes BEGIN marker"
    block = lines[starts[0]:ends[0] + 1]
    return "\n".join(ln.rstrip() for ln in block)


def test_atlas_init_fallback_matches_template():
    root = Path(__file__).resolve().parent.parent
    template = _extract_block(
        (root / "templates" / "agents-routing-snippet.md").read_text(encoding="utf-8"))
    fallback = _extract_block(
        (root / "commands" / "atlas-init.md").read_text(encoding="utf-8"))
    assert fallback == template, (
        "The embedded fallback block in commands/atlas-init.md has drifted from "
        "templates/agents-routing-snippet.md (the source of truth). Re-copy the "
        "BEGIN…END block from the template into atlas-init.md's fenced example."
    )


@pytest.mark.parametrize("dogfood_file", ["AGENTS.md", "CLAUDE.md"])
def test_own_dogfood_file_matches_template(dogfood_file):
    root = Path(__file__).resolve().parent.parent
    template = _extract_block(
        (root / "templates" / "agents-routing-snippet.md").read_text(encoding="utf-8"))
    dogfood = _extract_block((root / dogfood_file).read_text(encoding="utf-8"))
    assert dogfood == template, (
        f"This repo's own {dogfood_file} routing block has drifted from "
        "templates/agents-routing-snippet.md (the source of truth). Resync the "
        "BEGIN…END block, or intentionally diverge and document why (issue #167)."
    )


# Skills that exist ONLY in the standalone form (skills/<name>/) and have no
# collapsed-form equivalent anywhere — neither as a top-level entrypoint
# (collapsed/skills/<name>/) nor nested as a lens bundled inside an entrypoint
# (collapsed/skills/<entrypoint>/reference/lenses/<name>/, which is where
# ordinary lenses like sweeping-for-security actually live in the collapsed
# form). Only checking the top-level dir would misclassify every ordinary
# lens as "standalone-only" — it IS present, just nested — which would demand
# collapsed-form guidance for skills that don't need it. Naming a genuinely
# standalone-only skill (choosing-review-lenses, synthesizing-review-findings)
# in the routing block without also describing the collapsed-form alternative
# 404s for that reader (issue #200). Derived from the actual directory layout
# rather than hardcoded, so a future standalone-only skill is caught too.
def _standalone_only_skill_names() -> set[str]:
    root = Path(__file__).resolve().parent.parent
    standalone = {p.name for p in (root / "skills").iterdir() if p.is_dir()}
    collapsed_root = root / "collapsed" / "skills"
    collapsed_top = {p.name for p in collapsed_root.iterdir() if p.is_dir()}
    collapsed_nested = {
        lens.name
        for entrypoint in collapsed_root.iterdir()
        if (entrypoint / "reference" / "lenses").is_dir()
        for lens in (entrypoint / "reference" / "lenses").iterdir()
        if lens.is_dir()
    }
    return standalone - collapsed_top - collapsed_nested


def test_routing_block_names_collapsed_equivalent_for_standalone_only_skills():
    """Regression test for issue #200. Every routing-TABLE row that names a
    standalone-only skill (e.g. `choosing-review-lenses`,
    `synthesizing-review-findings`) must also tell a --collapsed-vendored
    reader what to use instead — the word "collapsed" must appear in that same
    table row. Scoped to table rows (lines starting with "|") rather than any
    line: prose mentions above the table (e.g. explaining the general review
    methodology) are not per-tool routing instructions the way a table row
    is, so they're not held to the same requirement."""
    root = Path(__file__).resolve().parent.parent
    block = _extract_block(
        (root / "templates" / "agents-routing-snippet.md").read_text(encoding="utf-8"))
    standalone_only = _standalone_only_skill_names()
    table_rows = [ln for ln in block.split("\n") if ln.lstrip().startswith("|")]
    # Only skills the block's table actually names are checked below. If the
    # table is ever rewritten to not name any standalone-only skill at all
    # (e.g. made fully form-agnostic), that satisfies this test's actual
    # requirement — "if named, must have collapsed guidance in that row" —
    # vacuously, so this loop intentionally does not assert `named` is
    # non-empty.
    named = [name for name in standalone_only if any(f"`{name}`" in row for row in table_rows)]
    for name in named:
        needle = f"`{name}`"
        mentioning_rows = [row for row in table_rows if needle in row]
        assert all("collapsed" in row.lower() for row in mentioning_rows), (
            f"the routing table mentions the standalone-only skill `{name}` "
            "in a row without --collapsed-form guidance in that same row "
            "(issue #200) — every row citing a standalone-only skill must "
            "also name its collapsed-form equivalent"
        )
