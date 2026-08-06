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


# Skills that exist only in the standalone form (skills/<name>/) and are never
# copied when a repo vendors --collapsed (tooling/vendor-skills.sh's
# collect_skill_names()/vendor_one() set SRC_SUBDIR=collapsed/skills for that
# form, which has no choosing-review-lenses/ or synthesizing-review-findings/
# folder — see collapsed/skills/). Naming one of these in the routing block
# without also describing what a --collapsed-vendored repo should do instead
# 404s for that reader (issue #200). Derived from the actual directory layout
# rather than hardcoded, so a future standalone-only skill is caught too.
def _standalone_only_skill_names() -> set[str]:
    root = Path(__file__).resolve().parent.parent
    standalone = {p.name for p in (root / "skills").iterdir() if p.is_dir()}
    collapsed = {p.name for p in (root / "collapsed" / "skills").iterdir() if p.is_dir()}
    return standalone - collapsed


def test_routing_block_names_collapsed_equivalent_for_standalone_only_skills():
    """Regression test for issue #200. Every routing-block row that names a
    standalone-only skill (e.g. `choosing-review-lenses`,
    `synthesizing-review-findings`) must also tell a --collapsed-vendored
    reader what to use instead — the word "collapsed" must appear near the
    mention, not just the standalone skill name in isolation."""
    root = Path(__file__).resolve().parent.parent
    block = _extract_block(
        (root / "templates" / "agents-routing-snippet.md").read_text(encoding="utf-8"))
    standalone_only = _standalone_only_skill_names()
    named = [name for name in standalone_only if f"`{name}`" in block]
    assert named, (
        "expected the routing block to still name at least one standalone-only "
        "skill (e.g. choosing-review-lenses) — if this list is now empty, either "
        "the block or this test's assumptions have changed; update accordingly"
    )
    for name in named:
        # A skill can be mentioned more than once (e.g. in prose ahead of the
        # table as well as in its table row) — the requirement is that AT
        # LEAST ONE mention has nearby --collapsed-form guidance, not that
        # every mention does.
        needle = f"`{name}`"
        occurrences = []
        start = 0
        while (idx := block.find(needle, start)) != -1:
            occurrences.append(idx)
            start = idx + len(needle)
        assert any(
            "collapsed" in block[max(0, idx - 400) : idx + 400].lower()
            for idx in occurrences
        ), (
            f"the routing block mentions the standalone-only skill `{name}` "
            "without nearby guidance for the --collapsed form (issue #200) — "
            "every row citing a standalone-only skill must also name its "
            "collapsed-form equivalent"
        )
