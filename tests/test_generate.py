# SPDX-License-Identifier: MIT
# tests/test_generate.py
from pathlib import Path
from tooling.manifest import Manifest, Route, Router, Skill, Source, load_manifest
from tooling.generate import build_reference


def _skill(**kw):
    base = dict(name="hunting-silent-failures", description="x", shape="diff", wave=1,
                built_from=[Source(2, "tests/fixtures/research_sample.md#2"),
                            Source(4, "tests/fixtures/research_sample.md#4")])
    base.update(kw)
    return Skill(**base)


def test_build_reference_heuristics_concatenates_across_sources_with_headers():
    md = build_reference(_skill(), kind="heuristics", docs_root=".")
    assert "## From category #2" in md
    assert "## From category #4" in md
    assert "Is any error swallowed" in md
    assert "Is every acquired resource released" in md
    assert "## Contents" in md  # ToC is always emitted


def test_build_reference_tooling_only_has_tooling():
    md = build_reference(_skill(), kind="tooling", docs_root=".")
    assert "no-floating-promises" in md
    assert "Is any error swallowed" not in md


def test_tooling_reference_leads_with_tool_selection_principle():
    # The named tools are starting points; the standing preamble must steer a
    # reviewer to pick/verify for their stack rather than cargo-cult a default.
    tooling = build_reference(_skill(), kind="tooling", docs_root=".")
    assert "Selecting tools for this stack" in tooling
    assert "verify it actually runs on your toolchain" in tooling
    # ...and only on tool lists, not the heuristics/reference files.
    heuristics = build_reference(_skill(), kind="heuristics", docs_root=".")
    assert "Selecting tools for this stack" not in heuristics


from tooling.generate import build_skill_md
import yaml


def test_build_skill_md_has_frontmatter_and_provenance_and_links():
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert md.startswith("---\n")
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["name"] == "hunting-silent-failures"
    assert front["description"]
    assert front["provenance"]["taxonomy_version"] == "v0.2"
    bf = front["provenance"]["built_from"]
    assert {b["category"] for b in bf} == {2, 4}
    assert all(len(b["hash"]) == 64 for b in bf)
    # body links one level deep
    assert "reference/heuristics.md" in md
    assert "reference/tool-rules.md" in md
    assert "examples.md" in md


from tooling.generate import generate_skill
import json


def test_generate_skill_writes_full_tree(tmp_path):
    out = generate_skill(_skill(), taxonomy_version="v0.2", docs_root=".",
                         skills_root=str(tmp_path))
    assert (out / "SKILL.md").exists()
    assert (out / "reference" / "heuristics.md").exists()
    assert (out / "reference" / "tool-rules.md").exists()
    assert (out / "reference" / "sources.md").exists()
    assert (out / "examples.md").exists()
    eval_doc = json.loads((out / "evals" / "eval.json").read_text())
    assert eval_doc["skills"] == ["hunting-silent-failures"]
    assert isinstance(eval_doc["scenarios"], list)


from tooling.generate import top_checks


def test_top_checks_are_inlined_so_skill_md_is_self_sufficient():
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    # head of the heuristics checklist appears directly in the body
    assert "Is any error swallowed" in md
    assert "Is every acquired resource released" in md


def test_top_checks_cap_cross_ref_categories():
    # #4 is a cross_ref: it must contribute at most 2 checks; #2 (primary) leads
    checks = top_checks(_skill(cross_ref=[4]), docs_root=".")
    assert checks[0].startswith("Is any error swallowed")
    from_4 = [c for c in checks if "acquired resource" in c or "caches bounded" in c.lower()]
    assert len(from_4) <= 2


def _research_with_deep_priority(tmp_path):
    # one section, a long heuristics list, a high-value factor marked priority
    # well past the ~8-check budget so position alone would never surface it.
    bullets = "\n".join(f"- Ordinary check number {i}?" for i in range(1, 13))
    doc = (
        "# Research — Marker Sample\n\n"
        "## #7 Some category\n\n"
        "### Reviewable heuristics (skill-checklist seeds)\n\n"
        f"{bullets}\n"
        "- ★ Deep but high-value factor that must surface?\n"
    )
    p = tmp_path / "research.md"
    p.write_text(doc, encoding="utf-8")
    return Skill(name="some-lens", description="x", shape="diff", wave=1,
                 built_from=[Source(7, "research.md#7")])


def test_priority_marked_deep_factor_surfaces_in_top_checks(tmp_path):
    # G9: a marked bullet inlines even though its position is past the budget,
    # and the marker is stripped from the rendered check.
    skill = _research_with_deep_priority(tmp_path)
    checks = top_checks(skill, docs_root=str(tmp_path))
    assert "Deep but high-value factor that must surface?" in checks
    assert "★" not in " ".join(checks)
    # an *unmarked* check at the same deep position is still excluded
    assert "Ordinary check number 12?" not in checks
    # additive, not displacing: the marker GROWS the list (1 priority + the full
    # 8-check position budget = 9) instead of dropping a position-based check to
    # "make room". A substituting impl that kept the total at 8 would fail here.
    assert len(checks) == 9
    assert "Ordinary check number 8?" in checks  # last position-based check kept


def test_priority_marker_stripped_from_heuristics_reference(tmp_path):
    skill = _research_with_deep_priority(tmp_path)
    ref = build_reference(skill, kind="heuristics", docs_root=str(tmp_path))
    assert "Deep but high-value factor that must surface?" in ref
    assert "★" not in ref


def test_priority_marker_ignored_in_cross_ref_categories(tmp_path):
    # owner-only: a marked bullet in a CROSS-REF category, sitting past the
    # positional quota, must NOT force-surface — a factor is promoted only in the
    # lens that owns the category, not in every lens that shares it.
    doc = (
        "# Research — Cross-ref Marker Sample\n\n"
        "## #7 Owned category\n\n"
        "### Reviewable heuristics (skill-checklist seeds)\n\n"
        "- Primary check one?\n- Primary check two?\n\n"
        "## #8 Shared category\n\n"
        "### Reviewable heuristics (skill-checklist seeds)\n\n"
        "- Shared one?\n- Shared two?\n- Shared three?\n"
        "- ★ Marked shared factor deep in the cross-ref list?\n"
    )
    p = tmp_path / "xref.md"
    p.write_text(doc, encoding="utf-8")
    skill = Skill(name="xref-lens", description="x", shape="diff", wave=1,
                  built_from=[Source(7, "xref.md#7"), Source(8, "xref.md#8")],
                  cross_ref=[8])
    checks = top_checks(skill, docs_root=str(tmp_path))
    assert "Marked shared factor deep in the cross-ref list?" not in checks
    assert "★" not in " ".join(checks)
    # the cross-ref still contributes its positional quota, marker-free
    assert "Shared one?" in checks and "Shared two?" in checks


def test_picker_renders_as_scannable_tagline():
    # The one-line picker is surfaced at the top of the body so the lens is
    # recognizable at a glance, above the trigger-rich description.
    md = build_skill_md(_skill(picker="Where do errors vanish? Swallowed exceptions."),
                        taxonomy_version="v0.2", docs_root=".")
    assert "*Where do errors vanish? Swallowed exceptions.*" in md
    # the tagline sits between the H1 and the "When to use" header
    assert md.index("*Where do errors vanish?") < md.index("## When to use")
    # no stray tagline when a skill has no picker (the two composition skills)
    plain = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert plain.split("## When to use")[0].count("*") == 0


def test_scope_line_marks_design_capability():
    plain = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert "not meant for design docs" in plain
    design = build_skill_md(_skill(design=True), taxonomy_version="v0.2", docs_root=".")
    assert "design-capable" in design
    repo = build_skill_md(_skill(shape="repo"), taxonomy_version="v0.2", docs_root=".")
    assert "Shape: repo" in repo


def test_mechanize_with_nudge_present_in_every_lens():
    # Q19(a): each lens reframes its tool-rules as an advisory mechanization
    # source — a non-blocking route: implementer suggestion. Check every real
    # lens, and scope the assertions to the mechanization section so a stray
    # match elsewhere in the doc can't mask a regression.
    manifest = load_manifest("skills/manifest.yaml")
    for skill in manifest.skills:
        md = build_skill_md(skill, taxonomy_version=manifest.taxonomy_version,
                            docs_root=".")
        assert "## Mechanizing these checks" in md, skill.name
        section = md.partition("## Mechanizing these checks")[2].split("\n## ", 1)[0]
        assert "route: implementer" in section, skill.name
        assert "reference/tool-rules.md" in section, skill.name
        assert "not a defect" in section, skill.name  # never blocks a verdict


def test_reviewer_discipline_is_defect_default_with_anti_churn_optin():
    # G26: every lens stays defect-only by default, but names the opt-in
    # improvement path bounded by the non-configurable anti-churn floor.
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert "Defects are the default; improvements are opt-in" in md
    assert "defect-only" in md
    assert "anti-churn floor" in md
    assert "route: implementer" in md
    # convergence/no-oscillation is part of the floor
    assert "converge" in md


def test_reviewer_discipline_surfaces_pre_existing_defects_in_touched_code():
    # G32: the attribution axis. A defect this change did not introduce but that
    # sits in touched code is surfaceable — tagged, opt-in/default-quiet,
    # route: implementer, non-blocking, scoped to touched code.
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert "pre-existing — not introduced by this change" in md
    assert "default-quiet" in md
    # scoped to touched code, never a repo-wide sweep, never expands PR scope
    assert "expand the PR's scope" in md
    assert "audits' job" in md


def test_attribution_guard_is_diff_shaped_only():
    # G32 is diff-specific ("this PR", "touched code", "the audits' job"), so it
    # must not render on repo-shaped audits (repo-wide hunting IS their job) or on
    # the decision shape (reviews an ADR, not a diff). Mirrors _scope_line gating.
    marker = "Pre-existing defects in touched code are surfaceable"
    assert marker in build_skill_md(_skill(shape="diff"), taxonomy_version="v0.2",
                                    docs_root=".")
    assert marker not in build_skill_md(_skill(shape="repo"), taxonomy_version="v0.2",
                                        docs_root=".")
    assert marker not in build_skill_md(_skill(shape="decision"),
                                        taxonomy_version="v0.2", docs_root=".")
    # the defect/improvement valence guard stays shape-neutral (unchanged)
    assert "Defects are the default" in build_skill_md(
        _skill(shape="repo"), taxonomy_version="v0.2", docs_root=".")


def test_cross_ref_note_names_primary_owner():
    md = build_skill_md(_skill(cross_ref=[4]), taxonomy_version="v0.2", docs_root=".",
                        owners={2: "hunting-silent-failures", 4: "some-other-skill"})
    assert "shared with **some-other-skill**" in md
    assert "report each shared finding once" in md
    # without an owners map (or without cross_refs) no note is emitted
    assert "Shared categories" not in build_skill_md(
        _skill(), taxonomy_version="v0.2", docs_root=".",
        owners={2: "hunting-silent-failures"})


from tooling.generate import build_router_md, generate_router


def _manifest_with_router():
    return Manifest(
        taxonomy_version="v0.2",
        skills=[_skill(picker="Where do errors vanish?", design=True)],
        router=Router(
            name="choosing-review-lenses",
            description="Picks lenses.",
            routes=[Route(when="Bug fix", run=["hunting-silent-failures"]),
                    Route(when="Repo audit", run=["hunting-silent-failures"],
                          note="run independently")],
        ))


def test_build_router_md_routes_table_and_catalog():
    md = build_router_md(_manifest_with_router())
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["name"] == "choosing-review-lenses"
    assert front["provenance"]["built_from"] == []   # manifest-derived: no docs drift
    assert "| Bug fix | `hunting-silent-failures` |" in md
    assert "— run independently |" in md
    assert "- `hunting-silent-failures` ◆ — Where do errors vanish?" in md


def test_router_body_overrides_description_in_when_to_use():
    # The terse `description` stays the listing surface (frontmatter); a richer
    # `body`, when present, is what the "When to use" section renders.
    m = _manifest_with_router()
    m.router.body = "Richer guidance with an example."
    md = build_router_md(m)
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["description"] == "Picks lenses."          # terse, unchanged
    assert "Richer guidance with an example." in md         # body in the section
    # falls back to description when no body is set
    plain = build_router_md(_manifest_with_router())
    assert "## When to use\n\nPicks lenses." in plain


def test_generate_router_writes_skill_and_draft_eval(tmp_path):
    out = generate_router(_manifest_with_router(), skills_root=str(tmp_path))
    assert (out / "SKILL.md").exists()
    eval_doc = json.loads((out / "evals" / "eval.json").read_text())
    assert eval_doc["skills"] == ["choosing-review-lenses"]


from tooling.generate import build_synthesizer_md, generate_synthesizer
from tooling.manifest import Synthesizer, Tension


def _manifest_with_synthesizer():
    m = _manifest_with_router()
    m.skills.append(_skill(name="checking-restraint",
                           picker="brake pedal", design=True))
    m.synthesizer = Synthesizer(
        name="synthesizing-review-findings",
        description="Merges lens findings.",
        severity_order=["Blocker", "Major", "Minor", "Nit"],
        tensions=[Tension(between=["hunting-silent-failures", "checking-restraint"],
                          about="brake vs. resilience", resolve="favor safety")],
    )
    return m


def test_build_synthesizer_md_carries_severity_tensions_and_no_provenance():
    md = build_synthesizer_md(_manifest_with_synthesizer())
    front = yaml.safe_load(md.split("---\n")[1])
    assert front["name"] == "synthesizing-review-findings"
    assert front["provenance"]["built_from"] == []   # manifest-derived: no docs drift
    assert "**Blocker** > **Major** > **Minor** > **Nit**" in md
    assert "`hunting-silent-failures` ↔ `checking-restraint`" in md
    assert "favor safety" in md
    # closes the loop back to the router
    assert "choosing-review-lenses" in md


def test_synthesizer_contract_carries_route_and_valence_axes():
    # G23 + G26: the finding contract gains a route axis (detect-and-route) and a
    # valence axis (defect vs improvement) alongside severity.
    md = build_synthesizer_md(_manifest_with_synthesizer())
    # valence axis + defaults
    assert "**valence**" in md
    assert "`defect`" in md and "`improvement`" in md
    # route axis + the non-engineering owners
    assert "**route**" in md
    for owner in ("product", "design", "legal", "leadership", "implementer"):
        assert owner in md
    # detect-and-route principle and the anti-churn floor
    assert "surfacing ≠ deciding" in md
    assert "anti-churn floor" in md
    # valence — not route — governs the verdict (a defect blocks even when routed)
    assert "Valence governs the verdict, not route" in md
    # the report carries dedicated Routed / Improvements sections
    assert "Routed — non-defect decisions outside engineering" in md
    assert "Improvements — opt-in, optional" in md
    # G32: the attribution axis — a pre-existing-defect field, a surfacing
    # principle, and a dedicated (opt-in) report section that does not set verdict
    assert "**attribution**" in md
    assert "`pre-existing`" in md
    assert "Attribution (Boy-Scout, scoped)" in md
    assert "Pre-existing — noticed in touched code, not introduced here" in md
    # G19: a coverage & limitations block is required, even on "No findings",
    # and carries its two named bullets (not just the heading phrase).
    assert "Coverage & limitations" in md
    assert "always present" in md
    assert "- Lenses run:" in md
    assert "- Not verifiable from this diff:" in md


def test_router_points_forward_to_synthesizer_when_present():
    assert "synthesizing-review-findings" in build_router_md(_manifest_with_synthesizer())
    # and stays silent when there is no synthesizer
    assert "synthesizing-review-findings" not in build_router_md(_manifest_with_router())


def test_generate_synthesizer_writes_skill_and_draft_eval(tmp_path):
    out = generate_synthesizer(_manifest_with_synthesizer(), skills_root=str(tmp_path))
    assert (out / "SKILL.md").exists()
    eval_doc = json.loads((out / "evals" / "eval.json").read_text())
    assert eval_doc["skills"] == ["synthesizing-review-findings"]
