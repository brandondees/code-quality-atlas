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
_VENDORED = (
    Path(__file__).resolve().parent.parent / ".claude" / "skills" / "icm-architect"
)


@pytest.mark.parametrize("twin", ["AGENTS.md", "routing.md"])
def test_map_twin_matches_claude_md(twin):
    source = (_ROOT / "CLAUDE.md").read_bytes()
    copy = (_ROOT / twin).read_bytes()
    assert copy == source, (
        f"docs/map/{twin} has drifted from docs/map/CLAUDE.md, the hand-edited "
        f"source. Re-copy CLAUDE.md over {twin} in the same change -- never "
        f"hand-edit a twin directly."
    )


def test_process_template_matches_vendored_copy():
    """Unlike object.md (a deliberate fork -- see docs/map/objects/CONTEXT.md's
    "Templates" section), process.md's frontmatter has no brace-placeholder
    YAML bug to fix, so it's meant to stay an exact copy of icm-architect's
    own template rather than diverge. Flagged in atlas-review round 3: an
    earlier fix wrongly claimed process.md was also a deliberate fork without
    actually forking it, which would have hidden real drift instead of
    catching it."""
    ours = (_ROOT / "_templates" / "process.md").read_bytes()
    vendored = (_VENDORED / "assets" / "templates" / "process.md").read_bytes()
    assert ours == vendored, (
        "docs/map/_templates/process.md has diverged from the vendored "
        ".claude/skills/icm-architect/assets/templates/process.md. If this "
        "divergence is intentional, update docs/map/objects/CONTEXT.md's "
        "'Templates' section to explain it (the way object.md's fork is "
        "explained) before updating this test."
    )
