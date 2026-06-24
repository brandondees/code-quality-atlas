# SPDX-License-Identifier: MIT
import pytest

from tooling.manifest import (
    Manifest, Skill, Source, ValidationError, load_manifest, validate,
    _check_comment_truncation,
)


def test_comment_truncation_caught_in_note_value():
    bad = (
        "router:\n"
        "  routes:\n"
        "    - when: Foo\n"
        "      run: [a]\n"
        "      note: design-time stuff,\n"
        "            RTO/RPO; pairs with #16 for the runtime side\n"
    )
    with pytest.raises(ValidationError, match="truncates the value"):
        _check_comment_truncation(bad, "x.yaml")


def test_comment_truncation_caught_on_key_line_value():
    bad = "synthesizer:\n  tensions:\n    - about: weigh against #14 owner\n"
    with pytest.raises(ValidationError, match="truncates the value"):
        _check_comment_truncation(bad, "x.yaml")


def test_comment_truncation_allows_quoted_and_blockscalar_and_real_comments():
    ok = (
        "skills:\n"
        "  - picker: >\n"
        "      A line that mentions #16 inside a block scalar is fine.\n"
        "    cross_ref: [4]    # primary owner: something  -- a real comment\n"
        "router:\n"
        "  routes:\n"
        '    - note: "RTO/RPO; pairs with #16 for the runtime side"\n'
        "      when: A change with no hash\n"
    )
    _check_comment_truncation(ok, "x.yaml")  # no raise


def test_real_manifest_passes_comment_truncation_guard():
    # the shipped manifest must stay clean (and load_manifest enforces the guard)
    load_manifest("skills/manifest.yaml")


def test_real_manifest_has_cross_quality_tensions():
    # G31: the tensions table must cover pairs where neither side is restraint,
    # so cross-quality collisions get a default instead of falling back to the
    # generic "safer and simpler".
    m = load_manifest("skills/manifest.yaml")
    cross_quality = [t for t in m.synthesizer.tensions
                     if "checking-restraint" not in t.between]
    # enforce pair-level coverage, not loose substrings: the three G31 pairs
    # whose lenses exist today must all be present.
    pairs = {tuple(sorted(t.between)) for t in cross_quality}
    assert len(cross_quality) >= 3
    assert tuple(sorted(["reviewing-performance-and-efficiency",
                         "reviewing-accessibility-and-i18n"])) in pairs
    assert tuple(sorted(["reviewing-observability-and-operability",
                         "auditing-compliance-and-provenance"])) in pairs
    assert tuple(sorted(["checking-idioms-and-consistency",
                         "finding-maintainability-hotspots"])) in pairs
    validate(m)  # the new tensions reference real, distinct lenses

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


def test_source_without_fragment_raises_clear_error():
    with pytest.raises(ValueError, match="<path>#<section>"):
        Source(category=2, source="docs/research/cluster-1-correctness.md")


def test_source_with_nonnumeric_fragment_raises_clear_error():
    with pytest.raises(ValueError, match="non-negative integer"):
        Source(category=2, source="docs/research/cluster-1-correctness.md#two")


def _write_manifest(tmp_path, text):
    p = tmp_path / "manifest.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_manifest_rejects_empty_file(tmp_path):
    path = _write_manifest(tmp_path, "")
    with pytest.raises(ValidationError, match="expected a YAML mapping"):
        load_manifest(path)


def test_load_manifest_rejects_list_root(tmp_path):
    path = _write_manifest(tmp_path, "- a\n- b\n")
    with pytest.raises(ValidationError, match="expected a YAML mapping"):
        load_manifest(path)


def test_load_manifest_rejects_missing_skills_key(tmp_path):
    path = _write_manifest(tmp_path, "taxonomy_version: v0.2\n")
    with pytest.raises(ValidationError, match="missing required key 'skills'"):
        load_manifest(path)


def test_load_manifest_rejects_missing_taxonomy_version(tmp_path):
    path = _write_manifest(tmp_path, "skills: []\n")
    with pytest.raises(ValidationError, match="missing required key 'taxonomy_version'"):
        load_manifest(path)


def test_load_manifest_rejects_non_list_skills(tmp_path):
    path = _write_manifest(tmp_path, "taxonomy_version: v0.2\nskills: not-a-list\n")
    with pytest.raises(ValidationError, match="'skills' must be a list"):
        load_manifest(path)


def test_load_manifest_wraps_malformed_source(tmp_path):
    path = _write_manifest(tmp_path,
        "taxonomy_version: v0.2\n"
        "skills:\n"
        "  - name: hunting-silent-failures\n"
        "    description: x\n"
        "    shape: diff\n"
        "    wave: 1\n"
        "    built_from:\n"
        "      - category: 2\n"
        "        source: docs/research/cluster-1-correctness.md\n")  # no #section
    with pytest.raises(ValidationError, match="skill #0"):
        load_manifest(path)


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


from tooling.manifest import Artifact


def _artifact_skill(tmp_path, **kw):
    doc = tmp_path / "rubrics.md"
    doc.write_text("## #101 SKILL.md\n\n"
                   "### Reviewable heuristics (skill-checklist seeds)\n- x\n")
    base = dict(name="reviewing-artifact-conventions", description="d",
                shape="artifact", wave=5,
                built_from=[Source(101, f"{doc}#101")],
                artifacts=[Artifact(name="SKILL.md", detect="a SKILL.md changes",
                                    rubric=101, slug="skill-md")])
    base.update(kw)
    return Skill(**base)


def test_validate_accepts_artifact_shape(tmp_path):
    validate(Manifest("v0", [_artifact_skill(tmp_path)]), docs_root="/")  # no raise


def test_artifact_shape_requires_artifacts_table(tmp_path):
    with pytest.raises(ValidationError, match="non-empty `artifacts`"):
        validate(Manifest("v0", [_artifact_skill(tmp_path, artifacts=[])]),
                 docs_root="/")


def test_artifact_rubric_must_be_in_built_from(tmp_path):
    bad = _artifact_skill(tmp_path,
                          artifacts=[Artifact(name="X", detect="y", rubric=999,
                                              slug="x")])
    with pytest.raises(ValidationError, match="rubric #999 is not in built_from"):
        validate(Manifest("v0", [bad]), docs_root="/")


def test_artifacts_only_on_artifact_shape(tmp_path):
    bad = _artifact_skill(tmp_path, shape="diff")
    with pytest.raises(ValidationError, match="only valid on an artifact-shaped"):
        validate(Manifest("v0", [bad]), docs_root="/")


def test_artifact_slug_must_be_lowercase_hyphen(tmp_path):
    bad = _artifact_skill(tmp_path,
                          artifacts=[Artifact(name="X", detect="y", rubric=101,
                                              slug="INVALID_slug")])
    with pytest.raises(ValidationError, match="lowercase"):
        validate(Manifest("v0", [bad]), docs_root="/")


def test_artifact_duplicate_slug_rejected(tmp_path):
    a = Artifact(name="X", detect="y", rubric=101, slug="skill-md")
    bad = _artifact_skill(tmp_path, artifacts=[a, a])
    with pytest.raises(ValidationError, match="duplicate"):
        validate(Manifest("v0", [bad]), docs_root="/")


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


from tooling.manifest import Synthesizer, Tension

def _two_lens_skills():
    return [_skill(picker="p"),
            _skill(name="checking-restraint", picker="brake", design=True,
                   built_from=[Source(4, "tests/fixtures/research_sample.md#4")])]

def _synth(**kw):
    base = dict(name="synthesizing-review-findings", description="d",
                severity_order=["Blocker", "Major", "Minor", "Nit"],
                tensions=[Tension(between=["hunting-silent-failures", "checking-restraint"],
                                  about="a", resolve="r")])
    base.update(kw)
    return Synthesizer(**base)

def test_synthesizer_tension_must_name_known_skills():
    m = Manifest("v0.2", _two_lens_skills(),
                 synthesizer=_synth(tensions=[Tension(
                     between=["hunting-silent-failures", "no-such-lens"],
                     about="a", resolve="r")]))
    with pytest.raises(ValidationError, match="unknown skill"):
        validate(m)

def test_synthesizer_tension_needs_two_distinct_lenses():
    m = Manifest("v0.2", _two_lens_skills(),
                 synthesizer=_synth(tensions=[Tension(
                     between=["checking-restraint", "checking-restraint"],
                     about="a", resolve="r")]))
    with pytest.raises(ValidationError, match="two distinct lenses"):
        validate(m)

def test_synthesizer_rejects_thin_severity_order():
    m = Manifest("v0.2", _two_lens_skills(),
                 synthesizer=_synth(severity_order=["Blocker"]))
    with pytest.raises(ValidationError, match="severity_order"):
        validate(m)

def test_synthesizer_name_must_not_collide_with_a_lens():
    m = Manifest("v0.2", _two_lens_skills(),
                 synthesizer=_synth(name="checking-restraint"))
    with pytest.raises(ValidationError, match="invalid or duplicate name"):
        validate(m)

def test_valid_synthesizer_accepted_and_real_manifest_loads():
    validate(Manifest("v0.2", _two_lens_skills(), synthesizer=_synth()))  # no raise
    real = load_manifest("skills/manifest.yaml")
    assert real.synthesizer is not None
    assert real.synthesizer.severity_order[0] == "Blocker"
    assert all(t.between[0] != t.between[1] for t in real.synthesizer.tensions)
