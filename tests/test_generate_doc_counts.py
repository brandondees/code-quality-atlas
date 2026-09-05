# SPDX-License-Identifier: MIT
# tests/test_generate_doc_counts.py
"""Unit tests for tooling/generate_doc_counts.py's rendering mechanics,
independent of the real repo docs test_doc_counts.py checks (issue #372)."""

import pytest

from tooling.generate_doc_counts import (
    CountOccurrence,
    DocCountAnchorError,
    compute_counts,
    sync_doc_counts,
)
from tooling.manifest import Manifest, Skill, Source


def _manifest(n_diff: int = 2, n_repo: int = 1) -> Manifest:
    skills = [
        Skill(
            name=f"diff-lens-{i}",
            description="x",
            shape="diff",
            wave=1,
            built_from=[Source(1, "x.md#1")],
        )
        for i in range(n_diff)
    ] + [
        Skill(
            name=f"repo-lens-{i}",
            description="x",
            shape="repo",
            wave=1,
            built_from=[Source(1, "x.md#1")],
        )
        for i in range(n_repo)
    ]
    return Manifest("v0", skills)


def test_compute_counts_matches_shape_breakdown():
    c = compute_counts(_manifest(n_diff=2, n_repo=1))
    assert c == {"lenses": 3, "diff": 2, "repo": 1, "total": 3}


def test_sync_doc_counts_rewrites_only_when_changed(tmp_path, monkeypatch):
    doc = tmp_path / "doc.md"
    doc.write_text("This suite ships 99 lenses today.", encoding="utf-8")
    template = (CountOccurrence("doc.md", "lenses", "ships ", " lenses today."),)
    monkeypatch.setattr("tooling.generate_doc_counts._TEMPLATE", template)

    changed = sync_doc_counts(_manifest(n_diff=3, n_repo=0), docs_root=str(tmp_path))
    assert changed == [doc]
    assert doc.read_text(encoding="utf-8") == "This suite ships 3 lenses today."

    # Second run is a no-op: content already matches the manifest.
    changed_again = sync_doc_counts(
        _manifest(n_diff=3, n_repo=0), docs_root=str(tmp_path)
    )
    assert changed_again == []


def test_sync_doc_counts_raises_on_missing_anchor(tmp_path, monkeypatch):
    doc = tmp_path / "doc.md"
    doc.write_text("This suite ships lenses today.", encoding="utf-8")  # no digit
    template = (CountOccurrence("doc.md", "lenses", "ships ", " lenses today."),)
    monkeypatch.setattr("tooling.generate_doc_counts._TEMPLATE", template)

    with pytest.raises(DocCountAnchorError, match="expected exactly one match"):
        sync_doc_counts(_manifest(), docs_root=str(tmp_path))


def test_sync_doc_counts_raises_on_ambiguous_anchor(tmp_path, monkeypatch):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "This suite ships 3 lenses today. It also ships 5 lenses today.",
        encoding="utf-8",
    )
    template = (CountOccurrence("doc.md", "lenses", "ships ", " lenses today."),)
    monkeypatch.setattr("tooling.generate_doc_counts._TEMPLATE", template)

    with pytest.raises(DocCountAnchorError, match="found 2"):
        sync_doc_counts(_manifest(), docs_root=str(tmp_path))


def test_sync_doc_counts_is_atomic_across_files(tmp_path, monkeypatch):
    """PR #419 review: a bad anchor in a later file must not leave an earlier
    file already rewritten on disk. Two files, both stale; the second file's
    anchor is broken (no match) — neither file should be touched."""
    good = tmp_path / "good.md"
    good.write_text("This suite ships 99 lenses today.", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("This suite ships lenses today.", encoding="utf-8")  # no digit
    template = (
        CountOccurrence("good.md", "lenses", "ships ", " lenses today."),
        CountOccurrence("bad.md", "lenses", "ships ", " lenses today."),
    )
    monkeypatch.setattr("tooling.generate_doc_counts._TEMPLATE", template)

    with pytest.raises(DocCountAnchorError):
        sync_doc_counts(_manifest(n_diff=3, n_repo=0), docs_root=str(tmp_path))

    # `good.md` must be untouched -- still the stale "99", not rewritten to "3"
    # -- since the batch as a whole failed to validate.
    assert good.read_text(encoding="utf-8") == "This suite ships 99 lenses today."
