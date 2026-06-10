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
