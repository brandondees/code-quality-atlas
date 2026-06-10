# tests/test_drift.py
from pathlib import Path
from tooling.manifest import Skill, Source
from tooling.generate import generate_skill
from tooling.drift import check_drift, DriftReport

def _skill():
    return Skill(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                 built_from=[Source(2, "tests/fixtures/research_sample.md#2")])

def test_no_drift_right_after_generation(tmp_path):
    generate_skill(_skill(), "v0.2", docs_root=".", skills_root=str(tmp_path))
    reports = check_drift(skills_root=str(tmp_path), docs_root=".")
    assert reports == []

def test_drift_detected_when_source_changes(tmp_path, monkeypatch):
    generate_skill(_skill(), "v0.2", docs_root=".", skills_root=str(tmp_path))
    # Simulate a docs edit by pointing drift at an altered copy of the docs root.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = Path("tests/fixtures/research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace("Does every remote call have a timeout?",
                         "Does every remote call have a timeout and deadline?"))
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert isinstance(reports[0], DriftReport)
    assert reports[0].skill == "hunting-silent-failures"
    assert [s.section for s in reports[0].changed] == [2]


def _two_source_skill():
    return Skill(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                 built_from=[Source(2, "tests/fixtures/research_sample.md#2"),
                              Source(4, "tests/fixtures/research_sample.md#4")])


def test_multi_source_drift_only_changed_source_reported(tmp_path):
    """Only the section that was actually edited should appear in DriftReport.changed."""
    generate_skill(_two_source_skill(), "v0.2", docs_root=".", skills_root=str(tmp_path))
    # Build altered docs root where ONLY section #2 is changed.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = Path("tests/fixtures/research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace("Does every remote call have a timeout?",
                         "Does every remote call have a timeout and deadline?"))
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert reports[0].skill == "hunting-silent-failures"
    changed_sections = [s.section for s in reports[0].changed]
    assert changed_sections == [2]           # #2 drifted
    assert 4 not in changed_sections         # #4 untouched
