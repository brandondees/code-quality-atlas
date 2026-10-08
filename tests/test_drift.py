# SPDX-License-Identifier: MIT
# tests/test_drift.py
from pathlib import Path

import pytest
import yaml

from tooling.drift import DriftError, DriftReport, check_drift
from tooling.generate_skill import generate_skill
from tooling.manifest import Skill, Source

ROOT = Path(__file__).resolve().parent.parent


def _skill():
    return Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )


def test_no_drift_right_after_generation(tmp_path):
    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert reports == []


def test_drift_detected_when_source_changes(tmp_path, monkeypatch):
    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    # Simulate a docs edit by pointing drift at an altered copy of the docs root.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace(
            "Does every remote call have a timeout?",
            "Does every remote call have a timeout and deadline?",
        )
    )
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert isinstance(reports[0], DriftReport)
    assert reports[0].skill == "hunting-silent-failures"
    assert [s.section for s in reports[0].changed] == [2]


def _two_source_skill():
    return Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[
            Source(2, "tests/fixtures/research_sample.md#2"),
            Source(4, "tests/fixtures/research_sample.md#4"),
        ],
    )


def test_multi_source_drift_only_changed_source_reported(tmp_path):
    """Only the section that was actually edited should appear in DriftReport.changed."""
    generate_skill(
        _two_source_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path)
    )
    # Build altered docs root where ONLY section #2 is changed.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace(
            "Does every remote call have a timeout?",
            "Does every remote call have a timeout and deadline?",
        )
    )
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert reports[0].skill == "hunting-silent-failures"
    changed_sections = [s.section for s in reports[0].changed]
    assert changed_sections == [2]  # #2 drifted
    assert 4 not in changed_sections  # #4 untouched


def test_malformed_skill_md_raises_clear_error(tmp_path):
    """A SKILL.md missing its YAML frontmatter must raise a clear error, not a
    bare IndexError from splitting on '---'."""
    import pytest

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# broken\n\nno frontmatter here\n")
    with pytest.raises(ValueError, match="frontmatter"):
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))


def test_drift_tolerates_crlf_skill_md(tmp_path):
    """A Windows (CRLF) checkout must not break frontmatter parsing."""
    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    skill_md = tmp_path / "hunting-silent-failures" / "SKILL.md"
    crlf = skill_md.read_text(encoding="utf-8").replace("\n", "\r\n")
    skill_md.write_bytes(crlf.encode("utf-8"))
    assert check_drift(skills_root=str(tmp_path), docs_root=str(ROOT)) == []


def test_drift_rejects_frontmatter_without_provenance(tmp_path):
    """Valid YAML but missing name/provenance.built_from must raise a clear
    ValueError, not TypeError/KeyError."""
    import pytest

    skill_dir = tmp_path / "noprov"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: noprov\n---\n\nbody\n")
    with pytest.raises(ValueError, match="provenance"):
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))


def test_drift_missing_source_file_raises_clear_drift_error(tmp_path):
    """A referenced source file that can't be read must raise a clear DriftError
    naming the skill and path, not a bare FileNotFoundError traceback."""
    import pytest

    from tooling.drift import DriftError

    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    # Point docs-root at an empty dir so the referenced source file is missing.
    empty_docs = tmp_path / "empty_docs"
    empty_docs.mkdir()
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(empty_docs))
    assert "hunting-silent-failures" in str(exc.value)
    assert "research_sample.md" in str(exc.value)


def test_drift_renumbered_source_section_raises_clear_drift_error(tmp_path):
    """A source section that was renumbered/removed in the research doc after
    a skill was generated from it must raise a clear DriftError naming the
    skill, path, and section -- not a bare KeyError traceback from
    extract_section (mirrors the sibling missing-file/non-UTF-8 cases above;
    see issue filed against this exact gap)."""
    import pytest

    from tooling.drift import DriftError

    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    # Point docs-root at a copy of the research doc with section #2 renumbered
    # away, simulating a taxonomy promotion/renumbering after generation.
    altered = tmp_path / "docs_renumbered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace("## #2 ", "## #99 ")
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert "hunting-silent-failures" in str(exc.value)
    assert "#2" in str(exc.value)


def test_drift_non_utf8_source_file_raises_clear_drift_error(tmp_path):
    """A source file that exists but isn't valid UTF-8 raises UnicodeDecodeError
    (a ValueError, not an OSError); it must still surface as a clean DriftError."""
    import pytest

    from tooling.drift import DriftError

    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    bad_docs = tmp_path / "bad_docs"
    (bad_docs / "tests" / "fixtures").mkdir(parents=True)
    # invalid UTF-8 bytes at the referenced source path
    (bad_docs / "tests" / "fixtures" / "research_sample.md").write_bytes(
        b"\xff\xfe\x00bad"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(bad_docs))
    assert "hunting-silent-failures" in str(exc.value)


def test_drift_built_from_entry_missing_hash_raises_clear_drift_error(tmp_path):
    """A built_from entry missing its `hash` field must raise a clear
    DriftError naming the skill, not a bare KeyError traceback."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - category: 2\n"
        '      source: "tests/fixtures/research_sample.md#2"\n'
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)
    assert "hash" in str(exc.value)


def test_drift_built_from_entry_bool_category_raises_clear_drift_error(tmp_path):
    """A built_from entry whose `category` is a bool (a subtype of int in
    Python, so it would otherwise silently masquerade as category 1) must
    raise a clear DriftError naming the skill, not a bare ValueError escaping
    with no skill context."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - category: true\n"
        '      source: "tests/fixtures/research_sample.md#2"\n'
        '      hash: "deadbeef"\n'
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)


def test_drift_built_from_entry_non_mapping_raises_clear_drift_error(tmp_path):
    """A built_from entry that isn't a mapping at all (e.g. a bare string or
    YAML null) must raise a clear DriftError naming the skill, not a bare
    TypeError from `b["category"]` ("string indices must be integers" /
    "'NoneType' object is not subscriptable") (issue #555)."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - just a string\n"
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)


def test_drift_built_from_container_non_list_raises_clear_drift_error(tmp_path):
    """A `built_from` that isn't a list at all (e.g. YAML null or a scalar)
    must raise a clear DriftError naming the skill, not a bare TypeError from
    `for b in built_from` ("'NoneType'/'int' object is not iterable")
    (issue #555 round 2)."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\nprovenance:\n  built_from:\n---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)


def test_drift_built_from_entry_non_string_source_raises_clear_drift_error(tmp_path):
    """A built_from entry whose `source` is a non-string (e.g. `source: 5` or
    `source: null`) must raise a clear DriftError naming the skill, not a bare
    TypeError from Source.__post_init__'s `"#" not in self.source`
    ("argument of type 'int'/'NoneType' is not iterable") (issue #555)."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - category: 2\n"
        "      source: 5\n"
        '      hash: "deadbeef"\n'
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)


def _entry(**overrides):
    """A well-formed built_from entry, with one or more fields overridden."""
    base = {
        "category": 2,
        "source": "tests/fixtures/research_sample.md#2",
        "hash": "deadbeef",
    }
    base.update(overrides)
    return base


def _entry_missing(key):
    """A well-formed built_from entry with one field removed entirely."""
    entry = _entry()
    del entry[key]
    return entry


def _write_broken_skill_md(tmp_path, built_from):
    """Write a SKILL.md at tmp_path/broken whose provenance.built_from is
    exactly the given value, serialized via YAML to avoid hand-escaping."""
    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    frontmatter = {"name": "broken", "provenance": {"built_from": built_from}}
    (skill_dir / "SKILL.md").write_text(
        "---\n" + yaml.safe_dump(frontmatter) + "---\n\nbody\n"
    )


# Every cell below is one shape `check_drift` must route through `DriftError`
# naming the skill, instead of letting a bare Type/Key/ValueError escape
# uncaught. Four separate fixes (#107, #546, #554, #555) each closed exactly
# one shape of this same defect family and missed the next one; this table
# enumerates the type-space of each validated field (the built_from
# container, an entry, and an entry's category/source/hash) so the next
# shape is a test failure here instead of a fifth issue (#558).
MALFORMED_BUILT_FROM_MATRIX = [
    # built_from container itself: must be a list.
    ("container-null", None, "must be a list"),
    ("container-str", "oops", "must be a list"),
    ("container-int", 5, "must be a list"),
    ("container-bool", True, "must be a list"),
    ("container-dict", {"category": 2}, "must be a list"),
    # a built_from entry: must be a mapping.
    ("entry-null", [None], "expected a mapping"),
    ("entry-str", ["just a string"], "expected a mapping"),
    ("entry-int", [5], "expected a mapping"),
    ("entry-bool", [True], "expected a mapping"),
    ("entry-list", [["nested", "list"]], "expected a mapping"),
    # entry.category: must be a non-bool int.
    ("category-bool-true", [_entry(category=True)], "category must be an integer"),
    ("category-bool-false", [_entry(category=False)], "category must be an integer"),
    ("category-str", [_entry(category="2")], "category must be an integer"),
    ("category-null", [_entry(category=None)], "category must be an integer"),
    ("category-list", [_entry(category=[2])], "category must be an integer"),
    ("category-dict", [_entry(category={"x": 1})], "category must be an integer"),
    ("category-missing", [_entry_missing("category")], "missing field 'category'"),
    # entry.source: must be a string.
    ("source-null", [_entry(source=None)], "source must be a string"),
    ("source-int", [_entry(source=5)], "source must be a string"),
    ("source-bool", [_entry(source=True)], "source must be a string"),
    ("source-list", [_entry(source=["x"])], "source must be a string"),
    ("source-dict", [_entry(source={"x": 1})], "source must be a string"),
    ("source-missing", [_entry_missing("source")], "missing field 'source'"),
    # entry.source: a string, but the wrong shape.
    (
        "source-no-hash-sign",
        [_entry(source="tests/fixtures/research_sample.md")],
        "must be '<path>#<section>'",
    ),
    (
        "source-non-digit-section",
        [_entry(source="tests/fixtures/research_sample.md#x")],
        "non-negative integer",
    ),
    # entry.hash: only "missing" is a validated cell. Its *value* is never
    # type-checked -- it's just compared with `!=` against a freshly
    # computed hash, so any present value (str, int, ...) degrades to
    # "drifted" rather than crashing. Missing is the only cell with an
    # error path to cover.
    ("hash-missing", [_entry_missing("hash")], "missing field 'hash'"),
]


@pytest.mark.parametrize(
    "built_from,expected_substring",
    [(bf, msg) for _case_id, bf, msg in MALFORMED_BUILT_FROM_MATRIX],
    ids=[case_id for case_id, _bf, _msg in MALFORMED_BUILT_FROM_MATRIX],
)
def test_malformed_built_from_type_matrix_raises_drift_error(
    tmp_path, built_from, expected_substring
):
    """Every malformed `built_from` shape in the matrix above must raise a
    `DriftError` naming the skill and the problem, not a bare
    Type/Key/ValueError escaping `check_drift` uncaught (issue #558)."""
    _write_broken_skill_md(tmp_path, built_from)
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)
    assert expected_substring in str(exc.value)
