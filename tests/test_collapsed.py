# SPDX-License-Identifier: MIT
# tests/test_collapsed.py
import json
from pathlib import Path

from tooling.generate_collapsed import (
    entrypoint_lenses,
    generate_lens_bundle,
    lens_bundle_body,
)
from tooling.manifest import Entrypoint, Manifest, Skill, Source

ROOT = Path(__file__).resolve().parent.parent


def _skill(**kw):
    base = {
        "name": "hunting-silent-failures",
        "description": "x",
        "shape": "diff",
        "wave": 1,
        "picker": "Where do errors vanish?",
        "built_from": [Source(2, "tests/fixtures/research_sample.md#2")],
    }
    base.update(kw)
    return Skill(**base)


def test_entrypoint_lenses_membership_by_shape_and_design():
    diff_plain = _skill(name="a", shape="diff", design=False)
    diff_design = _skill(name="b", shape="diff", design=True)
    repo = _skill(name="c", shape="repo")
    m = Manifest("v0", [diff_plain, diff_design, repo])
    ep_change = Entrypoint(name="reviewing-a-change", description="d", shapes=["diff"])
    ep_decision = Entrypoint(
        name="reviewing-a-decision",
        description="d",
        shapes=["decision"],
        include_design=True,
    )
    assert {s.name for s in entrypoint_lenses(m, ep_change)} == {"a", "b"}
    assert {s.name for s in entrypoint_lenses(m, ep_decision)} == {
        "b"
    }  # design-capable only


def test_lens_bundle_body_has_checklist_and_deeper_links():
    body = lens_bundle_body(
        _skill(), docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    # Assert the bundle's *structure* (independent of research-fixture wording) so
    # the first red/green is for the right reason — function unimplemented, not a
    # mismatched fixture string.
    assert body.startswith("# hunting-silent-failures")  # H1 = lens name
    assert "## When to use" in body
    assert "## Checklist" in body
    # Pin the lead-in itself: `## Checklist` was present before the lead-in fix too,
    # so the header assertion alone would not catch its regression. The second guard
    # fails on the exact bug — a bare header sitting directly on the `## From category`
    # sub-header with no body between.
    assert "The full review checklist" in body
    assert "## Checklist\n\n## From category" not in body
    assert (
        "## From category #2" in body
    )  # heuristics embedded (fixture's built_from category)
    assert (
        "(tool-rules.md)" in body and "(sources.md)" in body
    )  # deeper disclosure links


def test_lens_bundle_body_carries_the_reviewer_discipline_contract():
    """A collapsed lens bundle previously carried none of the reviewer-discipline
    contract every standalone SKILL.md ships — no report-only-real-problems
    guard, no Team preferences note, no Mechanizing/Process-notes footer (#369).
    Pin the whole contract's presence so a future refactor can't silently drop
    it again."""
    body = lens_bundle_body(
        _skill(), docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert "## Reviewer discipline" in body
    assert "Team preferences" in body
    assert "## Mechanizing these checks" in body
    assert "Process notes" in body
    # Order matters: discipline precedes the checklist, and the mechanizing/
    # process-notes footer precedes Going deeper.
    assert body.index("## Reviewer discipline") < body.index("## Checklist")
    assert body.index("## Mechanizing these checks") < body.index("## Going deeper")


def test_lens_bundle_body_attribution_guard_only_for_diff_shape():
    diff_body = lens_bundle_body(
        _skill(shape="diff"), docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert "Pre-existing defects in touched code are surfaceable" in diff_body
    repo_body = lens_bundle_body(
        _skill(shape="repo"), docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert "Pre-existing defects in touched code are surfaceable" not in repo_body


def test_lens_bundle_body_cross_ref_note_names_the_owner():
    skill = _skill(cross_ref=[2])
    body = lens_bundle_body(
        skill,
        docs_root=str(ROOT),
        skills_root=str(ROOT / "skills"),
        owners={2: "tracing-correctness-and-invariants"},
    )
    assert "Shared categories" in body
    assert "tracing-correctness-and-invariants" in body


def test_lens_bundle_body_for_artifact_shape_has_table_and_rubric_link():
    """An artifact-shaped lens's bundle must not ship the generic heuristics
    checklist — its checks live in per-artifact rubric files loaded on a
    presence hit, mirroring build_skill_md's artifact branch (#144 review:
    this special-case was missing entirely pre-fix, so a collapsed
    reviewing-an-artifact bundle shipped the wrong content)."""
    from tooling.manifest import Artifact

    skill = _skill(
        shape="artifact",
        artifacts=[
            Artifact(
                name="Weird Artifact",
                detect="a weird file",
                rubric=2,
                slug="weird-artifact",
            ),
        ],
    )
    body = lens_bundle_body(
        skill, docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert "## Artifacts" in body
    assert "## Checklist" not in body  # not the generic heuristics dump
    assert "[weird-artifact.md](weird-artifact.md)" in body  # table + Going deeper link
    assert (
        body.count("[weird-artifact.md](weird-artifact.md)") == 2
    )  # table + Going deeper


def test_generate_lens_bundle_writes_rubric_file_per_artifact(tmp_path):
    from tooling.manifest import Artifact

    skill = _skill(
        shape="artifact",
        artifacts=[
            Artifact(
                name="Weird Artifact",
                detect="a weird file",
                rubric=2,
                slug="weird-artifact",
            ),
        ],
    )
    dest = generate_lens_bundle(
        skill, tmp_path, docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    rubric = dest / "weird-artifact.md"
    assert rubric.exists()
    assert "GENERATED by" in rubric.read_text(
        encoding="utf-8"
    )  # carries the gen header
    assert "Rubric — Weird Artifact" in rubric.read_text(encoding="utf-8")


def test_lens_bundle_omits_checklist_when_no_heuristics(monkeypatch):
    # A lens with no heuristics must not ship a bare `## Checklist`; the whole
    # section (header + lead-in) is suppressed. No real lens is heuristics-less
    # today, so exercise the branch by stubbing _checklist_body to empty.
    import tooling.generate_collapsed as g

    monkeypatch.setattr(g, "_checklist_body", lambda *a, **k: "")
    body = g.lens_bundle_body(
        _skill(), docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert "## Checklist" not in body
    assert "The full review checklist" not in body
    assert "## When to use" in body and "## Going deeper" in body  # rest still renders


def test_lens_bundle_body_over_threshold_gets_contents_toc(tmp_path):
    # #163: a lens whose rendered body exceeds ~100 lines must open with a
    # `## Contents` ToC, the same rubric this suite applies to a third
    # party's SKILL.md (skill-md.md category #101). Build a synthetic,
    # oversized research fixture so the test doesn't depend on any real
    # lens's current length.
    bullets = "\n".join(f"- Heuristic bullet number {i}?" for i in range(120))
    research = (
        "# Research — Big\n\n"
        "## #2 Big category\n\n"
        "### Reviewable heuristics (skill-checklist seeds)\n\n"
        f"{bullets}\n"
    )
    (tmp_path / "research.md").write_text(research, encoding="utf-8")
    skill = _skill(built_from=[Source(2, "research.md#2")])
    body = lens_bundle_body(
        skill, docs_root=str(tmp_path), skills_root=str(ROOT / "skills")
    )
    assert len(body.splitlines()) > 100
    assert "## Contents" in body
    # ToC sits before the first real section, and links every top-level
    # heading actually present in the assembled body.
    assert body.index("## Contents") < body.index("## When to use")
    assert "[When to use](#when-to-use)" in body
    assert "[Checklist](#checklist)" in body
    assert "[Going deeper](#going-deeper)" in body


def test_lens_bundle_body_under_threshold_has_no_toc(monkeypatch):
    # A short bundle (no heuristics, no picker, a lens name with no
    # examples.md on disk) must not grow a ToC it doesn't need.
    import tooling.generate_collapsed as g

    monkeypatch.setattr(g, "_checklist_body", lambda *_args, **_kwargs: "")
    skill = _skill(name="nonexistent-lens-for-toc-test", picker="")
    body = g.lens_bundle_body(
        skill, docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert len(body.splitlines()) <= 100  # sanity: this fixture is intentionally short
    assert "## Contents" not in body


def test_toc_for_body_dedups_repeated_headings_with_github_style_suffixes():
    # GitHub disambiguates repeated identical headings by appending -1, -2, ...
    # to the anchor of each repeat — this must match, since #165 already
    # shipped ToCs elsewhere in this repo relying on that exact scheme.
    import tooling.generate_collapsed as g

    body = "## Bad → finding\n\nx\n\n## Bad → finding\n\nx\n\n## Bad → finding\n\nx\n"
    toc = g._toc_for_body(body)
    assert "[Bad → finding](#bad--finding)" in toc
    assert "[Bad → finding](#bad--finding-1)" in toc
    assert "[Bad → finding](#bad--finding-2)" in toc


def test_toc_for_body_skips_headings_inside_fenced_code_blocks():
    # #313: a literal "## "-prefixed line inside a worked example's fenced
    # snippet (e.g. a README excerpt) is example content, not a real heading,
    # and must not get its own (broken) ToC entry.
    import tooling.generate_collapsed as g

    body = (
        "## Real heading\n\n"
        "```markdown\n"
        "## Quickstart\n"
        "    from acme import Client\n"
        "```\n\n"
        "## Another real heading\n\nx\n"
    )
    toc = g._toc_for_body(body)
    assert "[Real heading](#real-heading)" in toc
    assert "[Another real heading](#another-real-heading)" in toc
    assert "Quickstart" not in toc


def test_toc_for_body_handles_a_longer_fence_wrapping_a_shorter_nested_one():
    # A worked example that itself demonstrates fenced Markdown (outer fence
    # longer than the inner one it wraps) must not close early on the inner
    # fence's shorter backtick run.
    import tooling.generate_collapsed as g

    body = (
        "## Real heading\n\n"
        "````\n"
        "```markdown\n"
        "## Quickstart\n"
        "```\n"
        "````\n\n"
        "## Another real heading\n\nx\n"
    )
    toc = g._toc_for_body(body)
    assert "[Real heading](#real-heading)" in toc
    assert "[Another real heading](#another-real-heading)" in toc
    assert "Quickstart" not in toc


def test_toc_for_body_ignores_backtick_runs_inside_indented_code_blocks():
    # CodeRabbit review on PR #315: a 4+-space *indented* code block (not a
    # fenced one) can contain a line that, after stripping leading
    # whitespace, looks like a fence opener (e.g. an indented example
    # documenting fence syntax itself). That must not be mistaken for an
    # active fence and swallow every real heading after it.
    import tooling.generate_collapsed as g

    body = (
        "## Real heading\n\n"
        "    some indented code\n"
        "    ```not a fence, just indented text\n"
        "    more indented code\n\n"
        "## Another real heading\n\nx\n"
    )
    toc = g._toc_for_body(body)
    assert "[Real heading](#real-heading)" in toc
    assert "[Another real heading](#another-real-heading)" in toc


def test_toc_for_body_skips_headings_inside_a_tilde_fenced_code_block():
    # dees-bot review nit on PR #315: the docstring and _FENCE_OPEN_RE both
    # claim ~~~-tilde fence support alongside backticks, but no test
    # exercised it.
    import tooling.generate_collapsed as g

    body = (
        "## Real heading\n\n"
        "~~~markdown\n"
        "## Quickstart\n"
        "~~~\n\n"
        "## Another real heading\n\nx\n"
    )
    toc = g._toc_for_body(body)
    assert "[Real heading](#real-heading)" in toc
    assert "[Another real heading](#another-real-heading)" in toc
    assert "Quickstart" not in toc


def test_toc_for_body_does_not_close_a_fence_on_a_mismatched_fence_character():
    # dees-bot review nit on PR #315: closing a fence requires the *same*
    # character as the opener (set(stripped) == {fence[0]}) — a run of the
    # other fence character must not close it early.
    import tooling.generate_collapsed as g

    body = (
        "## Real heading\n\n"
        "```\n"
        "## Quickstart\n"
        "~~~~\n"
        "still inside the fence\n"
        "```\n\n"
        "## Another real heading\n\nx\n"
    )
    toc = g._toc_for_body(body)
    assert "[Real heading](#real-heading)" in toc
    assert "[Another real heading](#another-real-heading)" in toc
    assert "Quickstart" not in toc


def test_generate_lens_bundle_writes_three_files(tmp_path):
    dest = generate_lens_bundle(
        _skill(), tmp_path, docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    assert (dest / "body.md").exists()
    assert (dest / "tool-rules.md").exists()
    assert (dest / "sources.md").exists()


def test_generate_lens_bundle_files_carry_generation_header(tmp_path):
    # Each generated lens-bundle file leads with a "generated — edit the source, not me"
    # banner naming its canonical sources, so a contributor doesn't edit a collapsed copy
    # directly and diverge it from source.
    skill = _skill()
    dest = generate_lens_bundle(
        skill, tmp_path, docs_root=str(ROOT), skills_root=str(ROOT / "skills")
    )
    for fname in ("body.md", "tool-rules.md", "sources.md"):
        text = (dest / fname).read_text(encoding="utf-8")
        assert text.startswith("<!-- GENERATED by `python -m tooling.cli generate`")
        # Header is an HTML comment ending in "-->\n\n"; pin the blank-line gap before
        # the first heading so a dropped separator regresses the test.
        assert "\n\n# " in text
    # examples.md is a canonical source only for body.md (the only file that inlines it);
    # tool-rules.md / sources.md draw from docs/research only and must not name it.
    assert f"skills/{skill.name}/examples.md" in (dest / "body.md").read_text(
        encoding="utf-8"
    )
    for fname in ("tool-rules.md", "sources.md"):
        assert f"skills/{skill.name}/examples.md" not in (dest / fname).read_text(
            encoding="utf-8"
        )


# --- Task 5: entrypoint SKILL.md + collapsed synthesis ---
from tooling.generate_collapsed import build_collapsed_synthesis, build_entrypoint_md
from tooling.manifest import Mode, Route, Router, Synthesizer


def _full_manifest():
    a = _skill(
        name="hunting-silent-failures", shape="diff", picker="Where do errors vanish?"
    )
    router = Router(
        name="choosing-review-lenses",
        description="route",
        routes=[Route(when="Bug fix", run=["hunting-silent-failures"])],
        body="",
    )
    syn = Synthesizer(
        name="synthesizing-review-findings",
        description="merge",
        severity_order=["Blocker", "Major", "Minor", "Nit"],
        tensions=[],
    )
    modes = [
        Mode(name="review", breadth="top 2-4", floor="escalating", triggers=["review"]),
        Mode(
            name="comprehensive",
            breadth="all relevant",
            floor="Nit",
            triggers=["thorough"],
        ),
    ]
    ep = Entrypoint(
        name="reviewing-a-change", description="review a change", shapes=["diff"]
    )
    return Manifest(
        "v0", [a], router=router, synthesizer=syn, modes=modes, entrypoints=[ep]
    )


def test_build_entrypoint_md_has_trigger_routing_modes_and_load_instructions():
    m = _full_manifest()
    md = build_entrypoint_md(m, m.entrypoints[0])
    assert md.startswith("---\n")  # frontmatter
    assert "name: reviewing-a-change" in md
    assert "## Depth modes" in md  # reuses modes_section
    assert "reference/lenses/hunting-silent-failures/body.md" in md  # load instruction
    assert "reference/synthesis.md" in md  # synthesize pointer
    assert "Bug fix" in md  # the in-shape route
    # Frontmatter must lead (skill discovery), so the generated marker
    # trails instead -- same fix as the standalone tree's SKILL.md (#374).
    assert md.rstrip().endswith(
        "Direct edits are overwritten on regeneration and fail the CI "
        "drift/regenerate gate. -->"
    )


def test_build_entrypoint_md_routes_table_excludes_lens_overlap_from_wrong_shape():
    # Regression for #188: a decision-shaped entrypoint's `include_design`
    # bundles every design-capable diff lens, which used to make ANY
    # diff-shaped route referencing one of those lenses leak into the
    # decision entrypoint's Routes table (e.g. "Bug fix", "Refactor") even
    # though the route's own topic has nothing to do with decision review.
    design_lens = _skill(name="design-lens", shape="diff", design=True)
    router = Router(
        name="choosing-review-lenses",
        description="route",
        body="",
        routes=[
            # Untagged -> defaults to shapes=["diff"]; must NOT appear in the
            # decision entrypoint despite the lens overlap via include_design.
            Route(when="Bug fix", run=["design-lens"]),
            # Explicitly decision-shaped -> must appear in the decision
            # entrypoint and nowhere else.
            Route(
                when="A decision, not a diff", run=["design-lens"], shapes=["decision"]
            ),
            # Multi-shape (shared) -> must appear in BOTH entrypoints, the
            # case the real manifest's "Design doc / plan / RFC" row
            # (shapes: [diff, decision]) relies on.
            Route(
                when="Design doc / plan / RFC",
                run=["design-lens"],
                shapes=["diff", "decision"],
            ),
        ],
    )
    syn = Synthesizer(
        name="synthesizing-review-findings",
        description="merge",
        severity_order=["Blocker", "Major", "Minor", "Nit"],
        tensions=[],
    )
    modes = [
        Mode(name="review", breadth="top 2-4", floor="escalating", triggers=["review"])
    ]
    ep_change = Entrypoint(name="reviewing-a-change", description="d", shapes=["diff"])
    ep_decision = Entrypoint(
        name="reviewing-a-decision",
        description="d",
        shapes=["decision"],
        include_design=True,
    )
    m = Manifest(
        "v0",
        [design_lens],
        router=router,
        synthesizer=syn,
        modes=modes,
        entrypoints=[ep_change, ep_decision],
    )

    change_md = build_entrypoint_md(m, ep_change)
    decision_md = build_entrypoint_md(m, ep_decision)

    assert "Bug fix" in change_md
    assert "A decision, not a diff" not in change_md
    assert "Bug fix" not in decision_md
    assert "A decision, not a diff" in decision_md
    assert "Design doc / plan / RFC" in change_md
    assert "Design doc / plan / RFC" in decision_md


def test_iac_route_note_stays_attributed_when_repo_lens_is_filtered_out():
    # #391 problem 4: the IaC route's `run` names both auditing-infrastructure-
    # as-code (repo-shaped) and sweeping-for-security (diff-shaped), but the
    # diff entrypoint's shape filter drops the former from the rendered `run`
    # column while the note (deliberately, per #188) still travels with the
    # row. Before the fix, the note's "judges blast radius... declared-vs-live
    # drift" clause read as a claim about sweeping-for-security — the only
    # lens left in the row — which is wrong; that's auditing-infrastructure-
    # as-code's job. The note must name its own subject explicitly so it stays
    # correct however the row gets filtered.
    from tooling.manifest import load_manifest

    m = load_manifest(str(ROOT / "skills" / "manifest.yaml"))
    ep_change = next(e for e in m.entrypoints if e.name == "reviewing-a-change")
    md = build_entrypoint_md(m, ep_change)
    line = next(line for line in md.splitlines() if "Infrastructure-as-code" in line)
    assert "`sweeping-for-security`" in line  # the only lens left after filtering
    assert "`auditing-infrastructure-as-code`" not in line  # filtered out of `run`
    # the note itself must still name the audit lens as the blast-radius/drift
    # subject, not leave that clause dangling on whatever lens survived
    assert "auditing-infrastructure-as-code" in line
    assert "declared-vs-live drift" in line


def test_build_collapsed_synthesis_carries_floor_policy_without_frontmatter():
    md = build_collapsed_synthesis(_full_manifest())
    assert not md.startswith("---")  # bundled body, no frontmatter
    assert "## Severity floor by mode" in md  # reuses mode_floor_policy


def test_build_collapsed_synthesis_drops_going_deeper_and_broken_links():
    # The standalone "Going deeper" links (../<router>/SKILL.md, ../../docs/...)
    # don't exist inside a collapsed bundle and would 404; they must be dropped.
    md = build_collapsed_synthesis(_full_manifest())
    assert "Going deeper" not in md  # heading and dangling prose ref both gone
    assert "/SKILL.md" not in md
    assert "docs/runbooks/multi-repo-audit.md" not in md


# --- Task 6: generate_collapsed writes the tree + plugin manifest ---


def test_generate_collapsed_writes_full_tree(tmp_path):
    from tooling.generate_collapsed import generate_collapsed

    m = _full_manifest()
    outs = generate_collapsed(
        m,
        docs_root=str(ROOT),
        skills_root=str(ROOT / "skills"),
        collapsed_root=str(tmp_path),
    )
    ep_dir = tmp_path / "skills" / "reviewing-a-change"
    assert (ep_dir / "SKILL.md").exists()
    synthesis_text = (ep_dir / "reference" / "synthesis.md").read_text(encoding="utf-8")
    # Carries the same "generated — edit the source, not me" banner as its
    # lens-bundle siblings (see test_generate_lens_bundle_files_carry_generation_header);
    # asserted explicitly so a dropped _gen_header() call regresses this test rather
    # than passing silently (the drift/regenerate gate only checks idempotency between
    # two generate runs, not that the marker is present at all).
    assert synthesis_text.startswith(
        "<!-- GENERATED by `python -m tooling.cli generate`"
    )
    assert (
        ep_dir / "reference" / "lenses" / "hunting-silent-failures" / "body.md"
    ).exists()
    assert (ep_dir / "evals" / "eval.json").exists()  # draft scaffold
    plugin = json.loads((tmp_path / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["name"] == "code-quality-atlas-collapsed"
    assert any(p == ep_dir for p in outs)


# --- Task 8: drift/regeneration gate across the collapsed tree ---
import os


def test_committed_collapsed_matches_regeneration(tmp_path):
    from tooling.generate_collapsed import generate_collapsed
    from tooling.manifest import load_manifest, validate

    # Regenerate ONLY the collapsed tree into tmp_path — generate_collapsed reads
    # the real committed skills/ (for each lens's examples.md) but writes nowhere
    # but tmp_path, so this never overwrites the live skills/ tree as a side effect.
    m = load_manifest(str(ROOT / "skills" / "manifest.yaml"))
    validate(m, docs_root=str(ROOT))
    generate_collapsed(
        m,
        docs_root=str(ROOT),
        skills_root=str(ROOT / "skills"),
        collapsed_root=str(tmp_path),
    )
    # the generated plugin.json must match the committed one (catches manifest drift)
    gen_plugin = (tmp_path / ".claude-plugin" / "plugin.json").read_text()
    committed_plugin = (
        (ROOT / "collapsed") / ".claude-plugin" / "plugin.json"
    ).read_text()
    assert gen_plugin == committed_plugin, (
        "drift in collapsed/.claude-plugin/plugin.json"
    )
    # compare every generated SKILL.md / body.md against the committed collapsed/ tree
    for root, _dirs, files in os.walk(tmp_path / "skills"):
        for f in files:
            gen = Path(root) / f
            rel = gen.relative_to(tmp_path)
            committed = (ROOT / "collapsed") / rel
            assert committed.exists(), f"missing committed file: {committed}"
            # eval.json drafts are scaffolds; skip if hand-authored later
            if gen.name == "eval.json":
                continue
            assert gen.read_text() == committed.read_text(), f"drift in {rel}"
    # reverse: every committed non-eval file must have a regenerated counterpart
    # (catches a stale file left in collapsed/ that generation no longer produces)
    for root, _dirs, files in os.walk((ROOT / "collapsed") / "skills"):
        for f in files:
            committed = Path(root) / f
            if committed.name == "eval.json":
                continue
            rel = committed.relative_to(ROOT / "collapsed")
            assert (tmp_path / rel).exists(), (
                f"stale committed file (not regenerated): {committed}"
            )


# --- Round-2 advisory follow-ups: prune path, body override, plugin.json in return ---


def test_generate_collapsed_returns_plugin_json_path(tmp_path):
    from tooling.generate_collapsed import generate_collapsed

    outs = generate_collapsed(
        _full_manifest(),
        docs_root=str(ROOT),
        skills_root=str(ROOT / "skills"),
        collapsed_root=str(tmp_path),
    )
    assert (tmp_path / ".claude-plugin" / "plugin.json") in outs


def test_generate_collapsed_prunes_stale_entrypoint(tmp_path):
    from tooling.generate_collapsed import generate_collapsed

    skills_dir = tmp_path / "skills"
    stale = skills_dir / "reviewing-an-obsolete-thing"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("stale", encoding="utf-8")
    generate_collapsed(
        _full_manifest(),
        docs_root=str(ROOT),
        skills_root=str(ROOT / "skills"),
        collapsed_root=str(tmp_path),
    )
    assert not stale.exists()  # pruned: not in the manifest
    assert (skills_dir / "reviewing-a-change").exists()  # current entrypoint written


def test_generate_collapsed_prunes_lens_dropped_from_existing_entrypoint(tmp_path):
    """A lens deleted, reshaped, or unbundled from an entrypoint must not leave
    its stale reference/lenses/<name>/ behind — only the whole-entrypoint prune
    existed before; this covers the finer-grained per-lens case (#144 review)."""
    from tooling.generate_collapsed import generate_collapsed

    m = _full_manifest()
    ep_lenses_dir = tmp_path / "skills" / "reviewing-a-change" / "reference" / "lenses"
    stale_lens = ep_lenses_dir / "an-old-lens-no-longer-in-the-manifest"
    stale_lens.mkdir(parents=True)
    (stale_lens / "body.md").write_text("stale", encoding="utf-8")

    generate_collapsed(
        m,
        docs_root=str(ROOT),
        skills_root=str(ROOT / "skills"),
        collapsed_root=str(tmp_path),
    )

    assert not stale_lens.exists()  # pruned
    assert (
        ep_lenses_dir / "hunting-silent-failures"
    ).exists()  # still-current lens kept


def test_build_entrypoint_md_uses_body_override_when_present():
    m = _full_manifest()
    ep = Entrypoint(
        name="reviewing-a-change",
        description="the description",
        shapes=["diff"],
        body="A richer hand-written when-to-use body.",
    )
    md = build_entrypoint_md(m, ep)
    # body wins over description in the When-to-use section (description still
    # appears in the frontmatter, which is correct and separate).
    assert "## When to use\n\nA richer hand-written when-to-use body." in md


def test_strip_toc_section_removes_only_the_contents_section():
    """The inlined examples' own ToC is dropped; everything else survives."""
    from tooling.generate_collapsed import _strip_toc_section

    md = (
        "Intro paragraph.\n\n"
        "## Contents\n\n"
        "- [Bad](#bad)\n"
        "- [Good](#good)\n\n"
        "## Bad\n\n"
        "the bad case\n\n"
        "## Good\n\n"
        "the good case\n"
    )
    out = _strip_toc_section(md)
    assert "## Contents" not in out
    assert "- [Bad](#bad)" not in out, "the ToC's list items must go with its heading"
    assert "Intro paragraph." in out, "content before the ToC must survive"
    assert "## Bad\n\nthe bad case" in out
    assert "## Good\n\nthe good case" in out


def test_strip_toc_section_is_a_noop_without_a_contents_heading():
    from tooling.generate_collapsed import _strip_toc_section

    md = "## Bad\n\nthe bad case\n\n### Contents of the payload\n\nnot a ToC\n"
    assert _strip_toc_section(md) == md.strip(), (
        "only a `## Contents` heading is a ToC; a deeper heading that merely "
        "starts with the word must be left alone"
    )


def test_strip_toc_section_drops_a_trailing_contents_section_to_eof():
    """A `## Contents` with no following `## ` runs to EOF — and is dropped.

    Intentional, not incidental: "the ToC and its list" has no other sensible end
    when the ToC is the last section. Locked in because the consequence is real —
    any content placed after a trailing ToC without an intervening `##` heading
    goes with it, and the tree-level test below checks for duplicate headings, not
    content loss, so nothing else would notice.
    """
    from tooling.generate_collapsed import _strip_toc_section

    assert _strip_toc_section("## Contents\n\n- [Bad](#bad)\n- [Good](#good)\n") == ""
    assert (
        _strip_toc_section("## Bad\n\nthe bad case\n\n## Contents\n\n- [Bad](#bad)\n")
        == "## Bad\n\nthe bad case"
    )


def test_strip_toc_section_ignores_a_contents_like_line_inside_a_fenced_block():
    # #317 (the same gap #313 fixed in _toc_for_body): a literal "## Contents"
    # line inside a worked example's fenced snippet is example content, not
    # a real ToC heading, and must not be stripped.
    from tooling.generate_collapsed import _strip_toc_section

    md = (
        "## Bad\n\n"
        "```markdown\n"
        "## Contents\n"
        "- [Quickstart](#quickstart)\n"
        "```\n\n"
        "the bad case\n"
    )
    out = _strip_toc_section(md)
    assert "## Contents" in out
    assert "- [Quickstart](#quickstart)" in out
    assert "the bad case" in out


def test_strip_toc_section_ignores_a_fenced_heading_while_skipping_a_real_toc():
    # A fenced "## "-prefixed line inside a real Contents section must not be
    # mistaken for the next real heading and end the skip early.
    from tooling.generate_collapsed import _strip_toc_section

    md = (
        "## Contents\n\n"
        "- [Bad](#bad)\n\n"
        "```markdown\n"
        "## Not a real heading\n"
        "```\n\n"
        "## Bad\n\nthe bad case\n"
    )
    out = _strip_toc_section(md)
    assert "## Contents" not in out
    assert "- [Bad](#bad)" not in out
    assert "Not a real heading" not in out
    assert "## Bad\n\nthe bad case" in out


def test_no_committed_lens_bundle_has_a_duplicate_contents_heading():
    """Regression: examples.md is inlined verbatim, so a `## Contents` inside one
    used to emit a second mid-document heading plus a self-referencing ToC entry
    (`- [Contents](#contents)` resolving back to the generated ToC). 7 of 39
    examples.md carried the heading, affecting 12 collapsed bodies."""
    offenders = []
    for body in sorted(
        (ROOT / "collapsed").glob("skills/*/reference/lenses/*/body.md")
    ):
        text = body.read_text(encoding="utf-8")
        # Mirror the generator's test exactly (`_strip_toc_section`): an exact,
        # case-folded `## Contents`. `startswith` would count `## Contents of the
        # payload` as a ToC and fail on a legitimate heading.
        n = sum(
            1
            for line in text.splitlines()
            if line.startswith("## ") and line[3:].strip().casefold() == "contents"
        )
        if n > 1:
            offenders.append(f"{body}: {n} '## Contents' headings")
        if "- [Contents](#contents)" in text:
            offenders.append(f"{body}: ToC links to itself")
    assert not offenders, "\n".join(offenders)
