# SPDX-License-Identifier: MIT
# tests/test_generate.py
from pathlib import Path
from tooling.manifest import Manifest, Mode, Route, Router, Skill, Source, load_manifest
from tooling.generate import build_reference, build_skill_md, primary_owners


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


def test_ai_authored_lens_owns_34_and_crossrefs_supply_chain():
    # G14 (Wave C, v0.4): the AI-authored-code lens primary-owns the new #34
    # category and cross-refs #18 (so the slopsquat leg dedupes under the
    # supply-chain owner rather than double-reporting).
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-ai-authored-code")
    assert lens.shape == "diff"
    owners = primary_owners(m)
    assert owners[34] == "reviewing-ai-authored-code"   # owns the new category
    assert owners[18] == "auditing-dependencies-and-supply-chain"  # not stolen
    assert 18 in lens.cross_ref
    md = build_skill_md(lens, taxonomy_version=m.taxonomy_version, docs_root=".",
                        owners=owners)
    # the two priority-marked checks surface in Top checks (G9)
    assert "slopsquat guard" in md
    assert "Confident-but-wrong constants and APIs" in md
    # shared-category note points to the supply-chain owner for dedupe
    assert "auditing-dependencies-and-supply-chain" in md


def test_agent_legibility_lens_owns_35_as_mirror_of_ai_authored():
    # G20 (Wave C, v0.5): the agent-legibility lens primary-owns the new #35
    # category — the agent-as-reader vantage rotation of Cluster II, the mirror of
    # #34 (quality of code *for* AI readers vs. *by* them). Single-category lens,
    # no cross_ref; both ★-marked checks must surface in Top checks (G9).
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-agent-legibility")
    assert lens.shape == "diff"
    assert not lens.cross_ref
    owners = primary_owners(m)
    assert owners[35] == "reviewing-agent-legibility"
    # the AI-authored mirror lens still owns its own category (not disturbed)
    assert owners[34] == "reviewing-ai-authored-code"
    md = build_skill_md(lens, taxonomy_version=m.taxonomy_version, docs_root=".",
                        owners=owners)
    assert "Context economy / self-containment" in md          # ★ priority check 1
    assert "Agent-onboarding files present, accurate, and scoped" in md  # ★ check 2
    # a single-category lens names no shared-category note
    assert "Shared categories" not in md


def test_ethical_design_lens_owns_36_detect_and_route():
    # G16 (Wave C, v0.6): the ethical/responsible-design lens primary-owns the new
    # #36 category — the diff-visible non-ML ethics class (dark patterns,
    # manipulative defaults, discriminatory conditionals), strictly detect-and-route.
    # Single-category lens, no cross_ref; both ★-marked checks surface (G9).
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-ethical-design")
    assert lens.shape == "diff"
    assert not lens.cross_ref
    owners = primary_owners(m)
    assert owners[36] == "reviewing-ethical-design"
    # the sibling harm lenses still own their categories (not disturbed)
    assert owners[14] == "sweeping-for-security"
    md = build_skill_md(lens, taxonomy_version=m.taxonomy_version, docs_root=".",
                        owners=owners)
    assert "Dark pattern / deceptive flow" in md            # ★ priority check 1
    assert "Manipulative defaults & asymmetric choices" in md  # ★ priority check 2
    assert "Shared categories" not in md  # single-category lens


def test_agentic_safety_lens_owns_32_action_surface():
    # D14 (Q16 / map-gaps G2): the agentic-safety lens primary-owns the new #32
    # category — the action/tool surface (what the model may *do*), split from #25's
    # model call. Single-category lens, no cross_ref; both ★-marked checks surface (G9).
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-agentic-safety")
    assert lens.shape == "diff"
    assert not lens.cross_ref
    owners = primary_owners(m)
    assert owners[32] == "reviewing-agentic-safety"
    # the model-call and authz siblings still own their categories (not disturbed)
    assert owners[25] == "reviewing-llm-integration"
    assert owners[14] == "sweeping-for-security"
    md = build_skill_md(lens, taxonomy_version=m.taxonomy_version, docs_root=".",
                        owners=owners)
    assert "Tool least-privilege" in md          # ★ priority check 1
    assert "Approval gates & autonomy bounds" in md  # ★ priority check 2
    assert "Shared categories" not in md  # single-category lens


def test_artifact_lens_renders_detect_table_not_top_checks():
    # D15 (Q18 / map-gaps G11): the artifact-shaped lens replaces the inlined
    # "Top checks" with a detect→rubric table; its checks live in per-artifact
    # bundled rubric files loaded on a presence hit.
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-artifact-conventions")
    assert lens.shape == "artifact"
    assert lens.artifacts and lens.artifacts[0].slug == "skill-md"
    md = build_skill_md(lens, taxonomy_version=m.taxonomy_version, docs_root=".")
    assert "**Shape: artifact.**" in md
    assert "## Artifacts" in md
    assert "## Top checks" not in md                       # replaced by the table
    assert "SKILL.md / agent skill" in md                  # the artifact row
    assert "[reference/skill-md.md](reference/skill-md.md)" in md  # rubric link
    assert "## Mechanizing these checks" in md             # shared section still present
    # the attribution (Boy-Scout) guard is diff-only and must not appear here
    assert "pre-existing — not introduced by this change" not in md


def test_generate_artifact_lens_writes_per_artifact_rubric(tmp_path):
    # The artifact lens writes one bundled rubric per artifact instead of the
    # single concatenated heuristics.md; tool-rules.md / sources.md still back the
    # Mechanizing / Going-deeper links, and provenance tracks the rubric section
    # (#101) so the existing drift checker covers it.
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-artifact-conventions")
    out = generate_skill(lens, taxonomy_version=m.taxonomy_version, docs_root=".",
                         skills_root=str(tmp_path))
    assert (out / "reference" / "skill-md.md").exists()
    assert not (out / "reference" / "heuristics.md").exists()
    assert (out / "reference" / "tool-rules.md").exists()
    assert (out / "reference" / "sources.md").exists()
    rubric = (out / "reference" / "skill-md.md").read_text()
    assert rubric.startswith("# Rubric — SKILL.md / agent skill")
    assert "Frontmatter is well-formed and within limits" in rubric
    front = yaml.safe_load((out / "SKILL.md").read_text().split("---\n")[1])
    assert front["provenance"]["built_from"][0]["category"] == 101


def test_router_catalog_lists_artifact_shape():
    m = load_manifest("skills/manifest.yaml")
    md = build_router_md(m)
    assert "Artifact-shaped" in md
    assert "- `reviewing-artifact-conventions`" in md


def test_interoperability_lens_owns_37_consolidating_conformance():
    # G18-interop (Wave C, v0.7): the interoperability lens primary-owns the new
    # #37 category — the first of the two ISO/IEC 25010:2023 characteristics with
    # no owner (compatibility). Consolidates the "does the code correctly speak an
    # external standard" factor-notes scattered across #4/#8/#13/#26 into one
    # owner. Single-category lens, no cross_ref; both ★-marked checks surface (G9).
    m = load_manifest("skills/manifest.yaml")
    lens = next(s for s in m.skills if s.name == "reviewing-interoperability")
    assert lens.shape == "diff"
    assert not lens.cross_ref
    owners = primary_owners(m)
    assert owners[37] == "reviewing-interoperability"
    # the neighbours whose factor-notes it consolidates still own their categories
    assert owners[4] == "tracing-correctness-and-invariants"   # internal correctness
    assert owners[13] == "reviewing-api-contract-safety"       # the contract we author
    md = build_skill_md(lens, taxonomy_version=m.taxonomy_version, docs_root=".",
                        owners=owners)
    assert "Standard protocol semantics" in md   # ★ priority check 1
    assert "RFC / format conformance" in md       # ★ priority check 2
    assert "Shared categories" not in md  # single-category lens


def test_security_ethical_design_tension_present():
    # G16 + G31: now that reviewing-ethical-design exists, the long-noted
    # security ↔ usability cross-quality collision (protective friction vs.
    # manipulative obstruction) becomes buildable and is added to the table.
    m = load_manifest("skills/manifest.yaml")
    pairs = {tuple(sorted(t.between)) for t in m.synthesizer.tensions}
    assert tuple(sorted(["sweeping-for-security",
                         "reviewing-ethical-design"])) in pairs


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


# --- Depth modes rendering (Plan 1) ---
from tooling.generate import modes_section, build_router_md


def _router_manifest(modes=None):
    skill = _skill(picker="Where do errors vanish?")
    router = Router(
        name="choosing-review-lenses", description="route a change to lenses",
        routes=[Route(when="Bug fix", run=["hunting-silent-failures"])], body="",
    )
    return Manifest("v0", [skill], router=router, modes=modes or [])


def _modes():
    return [
        Mode(name="triage", breadth="the critical tier only", floor="Major", triggers=["triage", "quick review"]),
        Mode(name="review", breadth="the top 2-4 lenses by relevance", floor="escalating", triggers=["review"]),
        Mode(name="comprehensive", breadth="every relevant lens, uncapped", floor="Nit",
             triggers=["thorough", "use all relevant lenses"]),
    ]


def test_modes_section_renders_three_modes_and_triggers():
    md = modes_section(_router_manifest(_modes()))
    assert "## Depth modes" in md
    for name in ("triage", "review", "comprehensive"):
        assert name in md
    assert "every relevant lens, uncapped" in md
    assert "use all relevant lenses" in md           # a trigger phrase is shown
    assert "relevance" in md and "breadth" in md      # separates relevance from breadth


def test_modes_section_empty_when_no_modes():
    assert modes_section(_router_manifest([])) == ""


def test_modes_section_renders_mode_notes():
    modes = [Mode(name="triage", breadth="critical tier", floor="Major",
                  triggers=["triage"], note="A pre-merge gate: critical-tier only.")]
    md = modes_section(_router_manifest(modes))
    assert "A pre-merge gate: critical-tier only." in md   # Mode.note is rendered, not dead data


def test_build_router_md_includes_modes_section():
    md = build_router_md(_router_manifest(_modes()))
    assert "## Depth modes" in md
    assert "comprehensive" in md


def test_router_points_2to4_at_review_mode():
    md = build_router_md(_router_manifest(_modes()))
    assert "review** mode default" in md or "review mode default" in md


# --- Per-mode severity floor policy (Plan 1) ---
from tooling.generate import build_synthesizer_md, mode_floor_policy


def _syn_manifest(modes=None):
    from tooling.manifest import Synthesizer
    syn = Synthesizer(name="synthesizing-review-findings", description="merge findings",
                      severity_order=["Blocker", "Major", "Minor", "Nit"], tensions=[])
    return Manifest("v0", [_skill(picker="p")], synthesizer=syn, modes=modes or [])


def test_mode_floor_policy_maps_each_mode_to_a_floor():
    md = mode_floor_policy(_syn_manifest(_modes()))
    assert "## Severity floor by mode" in md
    assert "triage" in md and "Major" in md
    assert "review" in md and "escalating" in md
    # comprehensive pins at the least-severe level
    assert "comprehensive" in md and "Nit" in md
    assert "pinned" in md.lower()      # comprehensive shows everything down to the floor


def test_mode_floor_policy_empty_when_no_modes():
    assert mode_floor_policy(_syn_manifest([])) == ""


def test_build_synthesizer_md_includes_floor_policy():
    md = build_synthesizer_md(_syn_manifest(_modes()))
    assert "## Severity floor by mode" in md


# --- generate_collapsed destructive-prune guard ---
from tooling.generate import generate_collapsed


def test_generate_collapsed_refuses_to_prune_standalone_skills_tree(tmp_path):
    """Guard: generate_collapsed prunes <collapsed_root>/skills of entries not in
    the manifest. If that prune target resolves onto the standalone skills tree,
    it must refuse (ValueError) rather than rmtree the real skills."""
    import pytest
    skills_root = tmp_path / "skills"
    sentinel = skills_root / "some-standalone-skill"
    sentinel.mkdir(parents=True)
    (sentinel / "SKILL.md").write_text("# do not delete me\n")
    m = load_manifest("skills/manifest.yaml")
    # collapsed_root=tmp_path makes Path(collapsed_root, "skills") == skills_root.
    with pytest.raises(ValueError, match="skills"):
        generate_collapsed(m, docs_root=".", skills_root=str(skills_root),
                           collapsed_root=str(tmp_path))
    assert sentinel.exists()  # nothing was pruned


def test_generate_collapsed_normal_roots_do_not_trip_guard(tmp_path):
    """The guard must not fire for legitimately distinct roots (the default shape
    collapsed_root/skills != skills_root)."""
    m = load_manifest("skills/manifest.yaml")
    written = generate_collapsed(m, docs_root=".", skills_root="skills",
                                 collapsed_root=str(tmp_path / "collapsed"))
    assert written  # generation proceeded
    assert (tmp_path / "collapsed" / "skills").exists()


# --- Q13 team-preferences overlay (Wave A) ---

def test_floor_tier_skill_forbids_silent_suppress():
    md = build_skill_md(_skill(tier="floor"), taxonomy_version="v0.2", docs_root=".")
    assert "Team preferences" in md
    assert "floor-tier" in md
    assert "can never `suppress` a finding outright" in md
    assert "`acknowledge`" in md
    assert "acknowledged deviation" in md


def test_preference_tier_skill_allows_suppress_and_gates_valence():
    md = build_skill_md(_skill(tier="preference"), taxonomy_version="v0.2", docs_root=".")
    assert "Team preferences" in md
    assert "preference-tier" in md
    assert "may `suppress` one of its findings outright" in md
    assert "improvement-valence directive" in md


def test_skill_defaults_to_preference_tier_note():
    # _skill() doesn't pass tier=, so this exercises the Skill dataclass default.
    md = build_skill_md(_skill(), taxonomy_version="v0.2", docs_root=".")
    assert "may `suppress` one of its findings outright" in md


def test_build_router_md_includes_preferences_loading_step():
    md = build_router_md(_manifest_with_router())
    assert "Load team preferences first" in md
    assert ".code-quality-atlas/preferences.md" in md
    assert "does not widen or override the depth mode itself" in md


def test_build_synthesizer_md_includes_acknowledged_deviation_clause():
    md = build_synthesizer_md(_manifest_with_synthesizer())
    assert "acknowledged deviation" in md
    assert "`suppress`ed preference-tier finding never" in md
