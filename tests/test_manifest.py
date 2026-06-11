# SPDX-License-Identifier: MIT
from tooling.manifest import load_manifest, Manifest, Skill, Source

def test_load_manifest_parses_skill_and_sources():
    m = load_manifest("tests/fixtures/manifest_sample.yaml")
    assert isinstance(m, Manifest)
    assert m.taxonomy_version == "v0.2"
    assert len(m.skills) == 1
    skill = m.skills[0]
    assert isinstance(skill, Skill)
    assert skill.name == "hunting-silent-failures"
    assert skill.shape == "diff"
    assert skill.wave == 1
    assert [s.section for s in skill.built_from] == [2, 4]
    assert skill.built_from[0].path == "tests/fixtures/research_sample.md"

def test_source_parses_path_and_section():
    s = Source(category=2, source="docs/research/cluster-1-correctness.md#2")
    assert s.path == "docs/research/cluster-1-correctness.md"
    assert s.section == 2


from tooling.manifest import validate, ValidationError
import pytest

def _skill(**kw):
    base = dict(name="hunting-silent-failures",
                description="x", shape="diff", wave=1,
                built_from=[Source(2, "tests/fixtures/research_sample.md#2")])
    base.update(kw)
    return Skill(**base)

def test_validate_accepts_good_manifest():
    validate(Manifest("v0.2", [_skill()]))  # no raise

def test_validate_rejects_reserved_word_in_name():
    with pytest.raises(ValidationError, match="reserved"):
        validate(Manifest("v0.2", [_skill(name="claude-helper")]))

def test_validate_rejects_bad_name_chars():
    with pytest.raises(ValidationError, match="name"):
        validate(Manifest("v0.2", [_skill(name="Hunting_Failures")]))

def test_validate_rejects_duplicate_names():
    with pytest.raises(ValidationError, match="duplicate"):
        validate(Manifest("v0.2", [_skill(), _skill()]))

def test_validate_rejects_unresolvable_source():
    bad = _skill(built_from=[Source(99, "tests/fixtures/research_sample.md#99")])
    with pytest.raises(ValidationError, match="section #99"):
        validate(Manifest("v0.2", [bad]))

def test_validate_rejects_missing_source_file():
    """A built_from pointing at a non-existent file must raise ValidationError
    (with skill + path context), not a bare FileNotFoundError/OSError."""
    bad = _skill(built_from=[Source(2, "tests/fixtures/does_not_exist.md#2")])
    with pytest.raises(ValidationError, match="cannot read source file"):
        validate(Manifest("v0.2", [bad]))

def test_validate_rejects_invalid_utf8_source(tmp_path):
    """A source file with invalid UTF-8 must raise ValidationError (with context),
    not a leaked UnicodeDecodeError."""
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    bad = _skill(built_from=[Source(2, "bad.md#2")])
    with pytest.raises(ValidationError, match="cannot read source file"):
        validate(Manifest("v0.2", [bad]), docs_root=str(tmp_path))


def test_g1_double_primary_rejected(tmp_path):
    doc = tmp_path / "r.md"
    doc.write_text("## #2 Errors\n\n### Reviewable heuristics (skill-checklist seeds)\n- x\n")
    src = f"{doc}#2"
    a = Skill(name="skill-a", description="d", shape="diff", wave=1,
              built_from=[Source(2, src)])
    b = Skill(name="skill-b", description="d", shape="diff", wave=1,
              built_from=[Source(2, src)])
    with pytest.raises(ValidationError, match="multiple primary owners"):
        validate(Manifest(taxonomy_version="v0", skills=[a, b]), docs_root="/")


def test_g1_cross_ref_resolves_double_booking(tmp_path):
    doc = tmp_path / "r.md"
    doc.write_text("## #2 Errors\n\n### Reviewable heuristics (skill-checklist seeds)\n- x\n")
    src = f"{doc}#2"
    a = Skill(name="skill-a", description="d", shape="diff", wave=1,
              built_from=[Source(2, src)])
    b = Skill(name="skill-b", description="d", shape="diff", wave=1,
              built_from=[Source(2, src)], cross_ref=[2])
    validate(Manifest(taxonomy_version="v0", skills=[a, b]), docs_root="/")


def test_g1_cross_ref_must_be_in_built_from(tmp_path):
    doc = tmp_path / "r.md"
    doc.write_text("## #2 Errors\n\n### Reviewable heuristics (skill-checklist seeds)\n- x\n")
    a = Skill(name="skill-a", description="d", shape="diff", wave=1,
              built_from=[Source(2, f"{doc}#2")], cross_ref=[9])
    with pytest.raises(ValidationError, match="not in built_from"):
        validate(Manifest(taxonomy_version="v0", skills=[a]), docs_root="/")


def test_duplicate_built_from_category_rejected(tmp_path):
    doc = tmp_path / "r.md"
    doc.write_text("## #2 Errors\n\n### Reviewable heuristics (skill-checklist seeds)\n- x\n")
    src = f"{doc}#2"
    a = Skill(name="skill-a", description="d", shape="diff", wave=1,
              built_from=[Source(2, src), Source(2, src)])
    with pytest.raises(ValidationError, match="more than once"):
        validate(Manifest(taxonomy_version="v0", skills=[a]), docs_root="/")


from tooling.manifest import Route, Router

def test_design_flag_only_on_diff_lenses():
    with pytest.raises(ValidationError, match="design"):
        validate(Manifest("v0.2", [_skill(shape="repo", design=True)]))

def test_router_route_must_run_known_skills():
    m = Manifest("v0.2", [_skill(picker="p")],
                 router=Router(name="choosing-review-lenses", description="d",
                               routes=[Route(when="Bug fix", run=["no-such-lens"])]))
    with pytest.raises(ValidationError, match="unknown skill"):
        validate(m)

def test_router_requires_every_skill_to_have_a_picker():
    m = Manifest("v0.2", [_skill()],   # no picker
                 router=Router(name="choosing-review-lenses", description="d",
                               routes=[Route(when="Bug fix",
                                             run=["hunting-silent-failures"])]))
    with pytest.raises(ValidationError, match="picker is required"):
        validate(m)

def test_valid_router_accepted_and_real_manifest_loads():
    m = Manifest("v0.2", [_skill(picker="p")],
                 router=Router(name="choosing-review-lenses", description="d",
                               routes=[Route(when="Bug fix",
                                             run=["hunting-silent-failures"])]))
    validate(m)  # no raise
    real = load_manifest("skills/manifest.yaml")
    assert real.router is not None
    assert all(s.picker for s in real.skills)
