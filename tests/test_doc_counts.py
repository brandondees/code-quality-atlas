# SPDX-License-Identifier: MIT
# tests/test_doc_counts.py
"""Documentation skill/lens counts must match the manifest and the skills/ tree.

Issue #95: every public-facing doc claimed 35 skills / 33 lenses / 23 diff-shaped
while the suite actually ships 36 / 34 / 24. The CI drift check verifies skills
match the manifest but never asserted the prose counts, so the drift persisted
silently. This test ties the documented numbers to the manifest (the source of
truth), so adding a lens fails CI until the docs are updated too.
"""
from pathlib import Path

from tooling.manifest import load_manifest

ROOT = Path(__file__).resolve().parent.parent


def _counts() -> dict[str, int]:
    m = load_manifest(str(ROOT / "skills" / "manifest.yaml"))
    composition = (1 if m.router else 0) + (1 if m.synthesizer else 0)
    return {
        "lenses": len(m.skills),
        "diff": sum(1 for s in m.skills if s.shape == "diff"),
        "total": len(m.skills) + composition,
    }


def _has(path: Path, needle: str) -> bool:
    return needle in path.read_text(encoding="utf-8")


def test_skills_dir_matches_manifest():
    dirs = [p for p in (ROOT / "skills").iterdir() if p.is_dir()]
    c = _counts()
    assert len(dirs) == c["total"], (
        f"skills/ has {len(dirs)} directories but the manifest implies "
        f"{c['total']} (={c['lenses']} lenses + router + synthesizer)"
    )


def test_documented_counts_match_manifest():
    c = _counts()
    readme = ROOT / "README.md"
    plugin = ROOT / ".claude-plugin" / "plugin.json"
    market = ROOT / ".claude-plugin" / "marketplace.json"
    assert _has(readme, f"**{c['total']} review skills**"), "README total skill count is stale"
    assert _has(readme, f"**{c['lenses']} review lenses**"), "README lens count is stale"
    assert _has(plugin, f"{c['lenses']} code-review and maintenance skills"), (
        "plugin.json lens count is stale"
    )
    assert _has(market, f"{c['total']} code-review and maintenance skills"), (
        "marketplace.json total skill count is stale"
    )
    assert _has(market, f"{c['diff']} diff-shaped review lenses"), (
        "marketplace.json diff-shaped lens count is stale"
    )
