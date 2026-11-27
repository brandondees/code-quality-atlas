# SPDX-License-Identifier: MIT
# tests/test_doc_counts.py
"""Assert documented skill/lens/diff/repo counts match the manifest (issue #95,
mechanism replaced by #372).

This used to carry a ~500-line hand-rolled sweep: scan every "living" doc for
any two-digit number (or spelled-out equivalent) near the words
skill/lens/audit/zip/upload, and assert it equalled a current manifest count.
That detector self-inflicted four false-positive escalations (issues #131,
#206, #219, #220) as its keyword/proximity heuristics were patched again and
again to chase edge cases in prose it was never told the shape of.

#372's fix: stop detecting where the counts are and instead render them
directly from the manifest at generate time, at each occurrence's exact,
pre-recorded location (`tooling/generate_doc_counts.py`'s `_TEMPLATE`) — the
same "Derived, not hardcoded" pattern `generate_router.py`'s `n_repo_audits`
already uses. Generated content can't drift from its source by construction,
so this file only needs to assert the render actually happened: every
template occurrence's current file content already reflects the manifest's
counts. The regenerate-and-diff CI gate (`.github/workflows/ci.yml`, the
"Generated trees are in sync" step) is what catches a doc edited without
regenerating; this test is the local/pre-commit equivalent of that gate for
these files specifically."""

from pathlib import Path

from tooling.generate_doc_counts import _TEMPLATE, compute_counts
from tooling.manifest import load_manifest

ROOT = Path(__file__).resolve().parent.parent


def _counts() -> dict[str, int]:
    return compute_counts(load_manifest(str(ROOT / "skills" / "manifest.yaml")))


def test_skills_dir_matches_manifest():
    dirs = [p for p in (ROOT / "skills").iterdir() if p.is_dir()]
    c = _counts()
    assert len(dirs) == c["total"], (
        f"skills/ has {len(dirs)} directories but the manifest implies "
        f"{c['total']} (={c['lenses']} lenses + the composition skills: "
        f"router, tool-grounding pre-pass, synthesizer)"
    )


def test_documented_counts_match_manifest():
    """Every occurrence `tooling/generate_doc_counts.py` knows about must
    already render the manifest's current count in its file — i.e. `python -m
    tooling.cli generate` is a no-op on these files right now. A failure here
    means someone edited a rendered digit (or the surrounding doc) by hand
    without regenerating; run `python -m tooling.cli generate` and commit."""
    c = _counts()
    failures = []
    for occ in _TEMPLATE:
        text = (ROOT / occ.path).read_text(encoding="utf-8")
        matches = occ.pattern().findall(text)
        expected = str(c[occ.count_key])
        if matches != [expected]:
            failures.append(
                f"{occ.path}: anchor {occ.prefix!r} ... {occ.suffix!r} "
                f"(count_key={occ.count_key!r}) found {matches!r}, expected "
                f"[{expected!r}]"
            )
    assert not failures, (
        "documented count(s) out of sync with the manifest -- run "
        "`python -m tooling.cli generate` and commit:\n" + "\n".join(failures)
    )
