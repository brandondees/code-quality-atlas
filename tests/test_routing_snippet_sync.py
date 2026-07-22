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
