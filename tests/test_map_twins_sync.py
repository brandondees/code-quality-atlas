# SPDX-License-Identifier: MIT
# tests/test_map_twins_sync.py
"""docs/map/CLAUDE.md is the hand-edited entry file for the repo's ICM system
map; docs/map/AGENTS.md and docs/map/routing.md are supposed to be
byte-identical copies (icm-architect's references/system-map.md: "Generate
AGENTS.md and routing.md as byte-identical twins... Never hand-edit the
twins"). Nothing mechanically tied the three together, which is the exact
drift class the root CLAUDE.md/AGENTS.md pair already hit once (issue #167,
guarded by test_routing_snippet_sync.py) -- flagged in atlas-review round 1
on the PR that introduced docs/map/ before it could repeat unnoticed here."""
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent / "docs" / "map"


@pytest.mark.parametrize("twin", ["AGENTS.md", "routing.md"])
def test_map_twin_matches_claude_md(twin):
    source = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    copy = (_ROOT / twin).read_text(encoding="utf-8")
    assert copy == source, (
        f"docs/map/{twin} has drifted from docs/map/CLAUDE.md, the hand-edited "
        f"source. Re-copy CLAUDE.md over {twin} in the same change -- never "
        f"hand-edit a twin directly."
    )
