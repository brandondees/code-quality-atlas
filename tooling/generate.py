# SPDX-License-Identifier: MIT
# tooling/generate.py
from __future__ import annotations
import json
import shutil
import warnings
import yaml
from pathlib import Path
from tooling.manifest import Artifact, Entrypoint, Manifest, Skill, Source
from tooling.sections import (extract_bullets, extract_section,
                              extract_subsection, section_hash,
                              is_priority, strip_priority)

_KIND_TITLE = {
    "heuristics": "Reviewable heuristics",
    "tooling": "Tool rules to triage",
    "references": "References to mine",
}

# Standing guidance prepended to every tool-rules.md. The named tools in each
# list are concrete starting points, not a mandate — this keeps a reviewer from
# cargo-culting a canonical-but-broken tool instead of finding the equivalent
# that fits the stack.
_TOOLING_PREAMBLE = (
    "> **Selecting tools for this stack.** The tools named below are "
    "field-tested starting points, not a mandate. Pick the one that fits this "
    "codebase's language version, build, and CI — and verify it actually runs "
    "on your toolchain before relying on it. A listed tool that is broken, "
    "abandoned, or noisy on your setup is a gap to close, not a permanent "
    "`continue-on-error`: prefer a working, maintained equivalent (often a "
    "younger, less well-known one) over a canonical-but-broken default. The "
    "capability is the requirement; the specific tool is replaceable.\n"
)


def build_reference(skill: Skill, kind: str, docs_root: str = ".") -> str:
    """Concatenate the `kind` subsection from each source category into one
    reference file, each under a `## From category #n` header, with a ToC."""
    if kind not in _KIND_TITLE:
        raise ValueError(f"unknown kind {kind!r}; must be one of {list(_KIND_TITLE)}")
    entries = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        body = strip_priority(
            extract_subsection(extract_section(text, src.section), kind).strip())
        if body:
            entries.append((src.section, body))
    toc = "\n".join(f"- From category #{n}" for n, _ in entries)
    parts = [f"## From category #{n}\n\n{body}" for n, body in entries]
    preamble = f"{_TOOLING_PREAMBLE}\n" if kind == "tooling" else ""
    header = f"# {_KIND_TITLE[kind]} — {skill.name}\n\n{preamble}## Contents\n\n{toc}\n"
    return header + "\n" + "\n\n".join(parts) + "\n"


_TOP_CHECKS_BUDGET = 8
_CROSS_REF_QUOTA = 2  # shared categories get token representation, not parity


def top_checks(skill: Skill, docs_root: str = ".") -> list[str]:
    """The head of the heuristics checklist, inlined into SKILL.md so a first
    review pass needs no second fetch. Budget ~8 checks total; cross_ref
    (shared) categories are capped so the lens's own categories dominate."""
    per_cat = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        bullets = extract_bullets(
            extract_subsection(extract_section(text, src.section), "heuristics"))
        per_cat.append((src.section, bullets))
    primaries = [b for n, b in per_cat if n not in skill.cross_ref]
    crosses = [b for n, b in per_cat if n in skill.cross_ref]
    checks: list[str] = []
    if primaries:
        # When a lens carries enough cross_ref categories that the quota would
        # consume the whole budget, the raw subtraction goes <= 0 and the max()
        # floor below silently collapses the budget to len(primaries) — one check
        # per primary category. No current skill has more than one cross_ref, so
        # this never fires today; warn rather than clamp silently if it ever does,
        # so a future manifest edit that squeezes the budget is visible at
        # generate time instead of quietly shipping half-length checklists.
        if _CROSS_REF_QUOTA * len(crosses) >= _TOP_CHECKS_BUDGET:
            warnings.warn(
                f"{skill.name}: cross-ref quota ({_CROSS_REF_QUOTA} x "
                f"{len(crosses)}) meets or exceeds the top-checks budget "
                f"({_TOP_CHECKS_BUDGET}); primary categories will fall back to "
                f"~1 check each. Consider raising _TOP_CHECKS_BUDGET or reducing "
                f"cross_ref breadth for this lens.",
                stacklevel=2)
        budget = max(_TOP_CHECKS_BUDGET - _CROSS_REF_QUOTA * len(crosses),
                     len(primaries))
        # Priority-marked bullets always inline (G9), marker stripped — they are
        # *additive*, so promoting a deep factor never displaces a foundational
        # position-based check. Only a lens that carries a marker grows (by the
        # number of marks), which keeps the promotion targeted rather than a
        # blanket budget increase across every lens.
        for bullets in primaries:
            checks.extend(strip_priority(b) for b in bullets if is_priority(b))
        base, rem = divmod(budget, len(primaries))
        for i, bullets in enumerate(primaries):
            non_prio = [b for b in bullets if not is_priority(b)]
            checks.extend(non_prio[:base + (1 if i < rem else 0)])
    # Cross-ref categories keep their small position-based quota and ignore the
    # priority marker — a factor is force-surfaced only in the lens that *owns*
    # it, not in every lens that shares the category. Markers are still stripped.
    for bullets in crosses:
        checks.extend(strip_priority(b) for b in bullets[:_CROSS_REF_QUOTA])
    return checks


def _scope_line(skill: Skill) -> str:
    if skill.shape == "repo":
        return ("**Shape: repo.** Run against the whole repository (scheduled or "
                "on demand), not a single diff.")
    if skill.shape == "decision":
        return ("**Shape: decision.** Reviewed at decision time — an ADR, RFC, "
                "design doc, adoption PR, or deprecation/rollout plan — not a diff "
                "of implementation code. Apply the checks to the decision and its "
                "record (rationale, assumptions, alternatives, exit/rollback), not "
                "to lines of code.")
    if skill.shape == "artifact":
        return ("**Shape: artifact.** Presence-activated: run only when one of the "
                "artifacts in the table below is present in the change or repo. "
                "Detect the artifact, open its rubric, and review the artifact "
                "against that published standard — not the surrounding application "
                "code. Skip entirely when none of the listed artifacts are present.")
    if skill.design:
        return ("**Shape: diff — design-capable.** Also works on design docs and "
                "plans: apply the same checks to the proposed states, data flows, "
                "and failure paths before any code exists.")
    return ("**Shape: diff.** Written for concrete code; not meant for design "
            "docs or plans.")


def _cross_ref_note(skill: Skill, owners: dict[int, str] | None) -> str:
    if not skill.cross_ref or not owners:
        return ""
    parts = []
    for c in skill.cross_ref:
        owner = owners.get(c)
        if owner and owner != skill.name:
            parts.append(f"category #{c} checks are shared with **{owner}** "
                         f"(their primary owner)")
    if not parts:
        return ""
    return ("\n**Shared categories:** " + "; ".join(parts) +
            ". When both lenses run on the same change, report each shared "
            "finding once, under the primary owner.\n")


def build_skill_md(skill: Skill, taxonomy_version: str, docs_root: str = ".",
                   owners: dict[int, str] | None = None) -> str:
    built_from = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        built_from.append({
            "category": src.section,
            "source": src.source,
            "hash": section_hash(text, src.section),
        })
    front = {
        "name": skill.name,
        "description": skill.description,
        "provenance": {"taxonomy_version": taxonomy_version, "built_from": built_from},
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False,
                        allow_unicode=True).strip()
    # A one-line scannable summary (the same `picker` the router catalog uses),
    # surfaced at the top of each lens so the lens is recognizable at a glance
    # without reading the full trigger-rich description below it.
    tagline = f"*{skill.picker.strip()}*\n\n" if skill.picker else ""
    # The attribution (Boy-Scout) guard is diff-specific — it talks about "this
    # PR", "touched code", and "a repo-wide hunt is the audits' job". That framing
    # has no referent on a repo-shaped audit (everything is pre-existing; repo-wide
    # hunting *is* its job) or the decision shape (it reviews an ADR, not a diff),
    # so emit it only on diff-shaped lenses — mirroring how `_scope_line` already
    # differentiates by shape.
    attribution_guard = (
        "**Pre-existing defects in touched code are surfaceable, not yours to "
        "fix.** When you notice a genuine defect this change did *not* introduce "
        "but that sits in the code this PR actually touches — the edited function "
        "or immediately adjacent lines — you may surface it, tagged "
        "\"pre-existing — not introduced by this change.\" Like improvements it is "
        "opt-in and default-quiet (off unless the team opts up), "
        "`route: implementer`, and non-blocking: it informs the author's "
        "fix-now / file-a-ticket / ignore call and never sets this PR's verdict, "
        "because the diff did not cause it. Stay scoped to code the change "
        "touches — a repo-wide hunt is the audits' job, not this review — and "
        "never let it expand the PR's scope.\n\n"
    ) if skill.shape == "diff" else ""
    # The "checks" surface differs by shape: a diff/repo/decision lens inlines the
    # head of its checklist; an artifact lens instead lists its detect→rubric table,
    # because its checks live in per-artifact bundled rubrics loaded on a presence hit
    # (D15 — pay only when the artifact is present).
    if skill.shape == "artifact":
        rows = "\n".join(
            f"| {a.name} | {a.detect} | [reference/{a.slug}.md](reference/{a.slug}.md) |"
            for a in skill.artifacts)
        core_block = (
            "## Artifacts\n\n"
            "Detect which artifact the change adds or touches, then open its rubric "
            "and review the artifact against that published standard:\n\n"
            "| Artifact | Activate when | Rubric to apply |\n"
            "|---|---|---|\n"
            f"{rows}\n\n")
        going_deeper = (
            "## Going deeper\n\n"
            + "".join(
                f"- [reference/{a.slug}.md](reference/{a.slug}.md) — the rubric for "
                f"{a.name}; open it on a presence hit and review against it.\n"
                for a in skill.artifacts)
            + "- [examples.md](examples.md) — concrete good/bad findings, and the "
            "output format to match.\n"
            "- [reference/tool-rules.md](reference/tool-rules.md) — the tools that "
            "mechanize part of each rubric; for wiring up checks, not needed for the "
            "judgment review itself.\n"
            "- [reference/sources.md](reference/sources.md) — the published standards "
            "behind each rubric; for provenance, not needed during a review.\n")
    else:
        checks = "\n".join(f"- {c}" for c in top_checks(skill, docs_root))
        core_block = (
            "## Top checks\n\n"
            "The head of the full checklist — enough for a first pass without opening "
            "any reference file:\n\n"
            f"{checks}\n"
            f"{_cross_ref_note(skill, owners)}\n")
        going_deeper = (
            "## Going deeper\n\n"
            "- [reference/heuristics.md](reference/heuristics.md) — the full checklist; "
            "open it when the change sits squarely in this lens's domain.\n"
            "- [examples.md](examples.md) — concrete good/bad findings, and the output "
            "format to match.\n"
            "- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules "
            "covering the mechanical subset; for wiring up linters, not needed for the "
            "judgment review itself.\n"
            "- [reference/sources.md](reference/sources.md) — the research behind each "
            "check; for provenance, not needed during a review.\n")
    body = (
        f"# {skill.name}\n\n"
        f"{tagline}"
        "## When to use\n\n"
        f"{skill.description}\n\n"
        f"{_scope_line(skill)}\n\n"
        "## Reviewer discipline\n\n"
        "Report only real problems. If the code correctly handles the case, reply "
        "\"No findings\" and stop — do not invent issues. This guards against false "
        "positives on correct code; still report every genuine issue you do find, "
        "with its full detail.\n\n"
        "**Defects are the default; improvements are opt-in.** By default this lens "
        "is defect-only: do not suggest changes to code that is already correct. "
        "When the team has opted up into improvement suggestions, a finding on "
        "already-correct code is admissible only as `nit`-severity, "
        "`route: implementer` (the author applies, defers, or ignores), and must "
        "clear the non-configurable anti-churn floor: it must genuinely *improve* — "
        "never offer a merely equivalent alternative — and must converge (once a "
        "dimension is as good as you can confidently make it, stop; never oscillate "
        "A→B then B→A, never re-order to an equivalent state). Defects keep "
        "the strict bar above regardless of this setting.\n\n"
        f"{attribution_guard}"
        f"{core_block}"
        "## Mechanizing these checks\n\n"
        "Where a finding here is one a tool can catch deterministically, surface "
        "that as an advisory `route: implementer` note next to the finding: the "
        "hand review caught it this time, and wiring the matching tool from "
        "[reference/tool-rules.md](reference/tool-rules.md) into CI gates it going "
        "forward. This is a suggestion to mechanize, not a defect — it never "
        "blocks a verdict, and it falls away on a repo that already runs the "
        "tool.\n\n"
        f"{going_deeper}"
    )
    return f"---\n{fm}\n---\n\n{body}"


def build_artifact_rubric(skill: Skill, artifact: Artifact, docs_root: str = ".") -> str:
    """The bundled rubric file for one artifact of an artifact-shaped lens: the
    heuristics, references, and tooling of that artifact's rubric section, loaded
    on a presence hit. Subsection headings are promoted ### → ## so the file's
    heading levels increment by one (H1 title → H2 sections)."""
    src = next(s for s in skill.built_from if s.section == artifact.rubric)
    section = extract_section(
        Path(docs_root, src.path).read_text(encoding="utf-8"), src.section)

    def block(kind: str) -> str:
        body = strip_priority(extract_subsection(section, kind).strip())
        return ("## " + body[4:]) if body.startswith("### ") else body

    parts = [
        f"# Rubric — {artifact.name}",
        f"Review a **{artifact.name}** against its published standard. Activate "
        f"when {artifact.detect}. Report only real deviations from the standard; "
        "if the artifact is well-formed, reply \"No findings\".",
    ]
    parts += [b for b in (block("heuristics"), block("references"),
                          block("tooling")) if b]
    return "\n\n".join(parts) + "\n"


def generate_skill(skill: Skill, taxonomy_version: str,
                   docs_root: str = ".", skills_root: str = "skills",
                   owners: dict[int, str] | None = None) -> Path:
    out = Path(skills_root, skill.name)
    (out / "reference").mkdir(parents=True, exist_ok=True)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(
        build_skill_md(skill, taxonomy_version, docs_root, owners), encoding="utf-8")
    # An artifact lens replaces the single concatenated heuristics.md with one
    # bundled rubric file per artifact (loaded on a presence hit); the combined
    # tool-rules.md / sources.md still back the Mechanizing and Going-deeper links.
    if skill.shape == "artifact":
        for a in skill.artifacts:
            (out / "reference" / f"{a.slug}.md").write_text(
                build_artifact_rubric(skill, a, docs_root), encoding="utf-8")
    else:
        (out / "reference" / "heuristics.md").write_text(
            build_reference(skill, "heuristics", docs_root), encoding="utf-8")
    (out / "reference" / "tool-rules.md").write_text(
        build_reference(skill, "tooling", docs_root), encoding="utf-8")
    (out / "reference" / "sources.md").write_text(
        build_reference(skill, "references", docs_root), encoding="utf-8")
    if not (out / "examples.md").exists():
        (out / "examples.md").write_text(
            f"# Examples — {skill.name}\n\n"
            "<!-- Add concrete good/bad input→finding pairs during refinement. -->\n",
            encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(json.dumps(
            {"skills": [skill.name], "scenarios": []}, indent=2) + "\n", encoding="utf-8")
    return out


def entrypoint_lenses(manifest: Manifest, entrypoint: Entrypoint) -> list[Skill]:
    """The lenses an entrypoint bundles: by shape, plus design-capable lenses
    when include_design (e.g. the decision entrypoint carries the ◆ diff lenses)."""
    out = []
    for s in manifest.skills:
        if s.shape in entrypoint.shapes or (entrypoint.include_design and s.design):
            out.append(s)
    return out


def _checklist_body(skill: Skill, docs_root: str = ".") -> str:
    """The heuristics checklist for a bundle, without build_reference's own H1
    title and Contents ToC — so the lens bundle keeps a single top-level heading
    (`# <lens>`) and stays markdownlint-clean (MD025)."""
    doc = build_reference(skill, "heuristics", docs_root=docs_root)
    idx = doc.find("## From category")
    return doc[idx:].strip() if idx != -1 else ""


def lens_bundle_body(skill: Skill, docs_root: str = ".", skills_root: str = "skills") -> str:
    """The `body.md` an entrypoint loads for one lens: when-to-use + the full
    heuristics checklist + curated examples + links to the deeper bundled files.
    Examples come from the standalone tree's hand-refined examples.md (canonical);
    tool-rules/sources are a further disclosure level, linked not inlined."""
    picker = f"{skill.picker}\n\n" if skill.picker else ""
    heuristics = _checklist_body(skill, docs_root=docs_root)
    examples_path = Path(skills_root, skill.name, "examples.md")
    examples = examples_path.read_text(encoding="utf-8") if examples_path.exists() else ""
    # The standalone examples.md carries its own `# Examples — <lens>` H1; strip a
    # leading H1 so the bundle keeps one top-level heading.
    examples = examples.strip()
    if examples.startswith("# "):
        examples = examples.split("\n", 1)[1].strip() if "\n" in examples else ""
    examples_block = f"## Examples\n\n{examples}\n\n" if examples else ""
    # Give `## Checklist` a lead-in before the per-category heuristics, mirroring how
    # `## Examples` opens with prose rather than dropping straight onto a sub-header.
    # Without it the section header sits directly on `## From category #NN`, reading as
    # an empty header. Suppress the whole section if a lens carries no heuristics, so a
    # future heuristics-less lens never ships a bare `## Checklist`.
    checklist_block = (
        "## Checklist\n\n"
        "The full review checklist, grouped by the research category each check "
        "draws from:\n\n"
        f"{heuristics}\n\n"
    ) if heuristics else ""
    return (
        f"# {skill.name}\n\n"
        f"{picker}"
        "## When to use\n\n"
        f"{_scope_line(skill)}\n\n"
        f"{checklist_block}"
        f"{examples_block}"
        "## Going deeper\n\n"
        "- [tool-rules.md](tool-rules.md) — static-analysis rules for the mechanical "
        "subset; for wiring linters, not needed for the judgment review.\n"
        "- [sources.md](sources.md) — the research behind each check; for provenance.\n"
    )


def _gen_header(skill: Skill) -> str:
    """A one-block 'generated — edit the source, not me' banner for the collapsed
    lens-bundle files. These are pure generated artifacts assembled from the research
    docs and the lens's hand-refined examples.md; a contributor who edits a collapsed
    copy directly would diverge it from its source (the `tooling.cli drift` /
    regenerate gate catches that after the fact — this header prevents it up front).
    An HTML comment so it renders invisibly and is markdownlint-clean."""
    return (
        "<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.\n"
        f"     Canonical sources: docs/research/ (checklist, tool-rules, sources) and "
        f"skills/{skill.name}/examples.md (worked examples).\n"
        "     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->\n\n"
    )


def generate_lens_bundle(skill: Skill, lenses_dir: Path, docs_root: str = ".",
                         skills_root: str = "skills") -> Path:
    """Write reference/lenses/<skill>/{body,tool-rules,sources}.md and return the dir."""
    dest = Path(lenses_dir, skill.name)
    dest.mkdir(parents=True, exist_ok=True)
    header = _gen_header(skill)
    (dest / "body.md").write_text(header + lens_bundle_body(skill, docs_root, skills_root), encoding="utf-8")
    (dest / "tool-rules.md").write_text(header + build_reference(skill, "tooling", docs_root), encoding="utf-8")
    (dest / "sources.md").write_text(header + build_reference(skill, "references", docs_root), encoding="utf-8")
    return dest


def primary_owners(manifest: Manifest) -> dict[int, str]:
    """category -> the skill that primarily owns it (G1 guarantees uniqueness)."""
    owners: dict[int, str] = {}
    for s in manifest.skills:
        for src in s.built_from:
            if src.category not in s.cross_ref:
                owners[src.category] = s.name
    return owners


def modes_section(manifest: Manifest) -> str:
    """The 'Depth modes' block for the router: separates relevance (which lenses
    apply) from breadth (how many to run). Empty string when no modes declared."""
    if not manifest.modes:
        return ""
    lines = [
        "## Depth modes",
        "",
        "Routing first ranks **every** lens whose scope the change touches by "
        "**relevance** — it is no longer a hard 2-4 cap. A depth mode then sets the "
        "**breadth** (how far down the ranked list to run) and the severity floor. "
        "Pick the mode from the request; default to **review**.",
        "",
        "| Mode | Breadth | Triggers |",
        "|---|---|---|",
    ]
    for mode in manifest.modes:
        triggers = ", ".join(f"\"{t}\"" for t in mode.triggers)
        lines.append(f"| **{mode.name}** | {mode.breadth.strip()} | {triggers} |")
    notes = [(m.name, m.note.strip()) for m in manifest.modes if m.note.strip()]
    if notes:
        lines.append("")
        lines.extend(f"- **{name}** — {note}" for name, note in notes)
    return "\n".join(lines).rstrip() + "\n\n"   # block ends with a blank line; "" when no modes


def build_router_md(manifest: Manifest) -> str:
    """The composition layer: routes a 'what am I reviewing' situation to the
    2-4 lenses worth running, plus a one-line catalog of every lens. Built
    entirely from the manifest — provenance carries no research sections, so
    regeneration is triggered by manifest edits, not docs drift."""
    r = manifest.router
    front = {
        "name": r.name,
        "description": r.description,
        "provenance": {"taxonomy_version": manifest.taxonomy_version, "built_from": []},
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False,
                        allow_unicode=True).strip()
    rows = []
    for route in r.routes:
        run = ", ".join(f"`{lens}`" for lens in route.run)
        if route.note:
            run += f" — {route.note}"
        rows.append(f"| {route.when} | {run} |")
    routes_table = "\n".join(rows)

    def catalog(shape: str) -> str:
        lines = []
        for s in manifest.skills:
            if s.shape != shape:
                continue
            mark = " ◆" if s.design else ""
            lines.append(f"- `{s.name}`{mark} — {s.picker}")
        return "\n".join(lines)

    body = (
        f"# {r.name}\n\n"
        "## When to use\n\n"
        f"{r.body or r.description}\n\n"
        "## How to pick\n\n"
        "- **The 2-4 figure is for focused single-change review only.** For a "
        "single change, this skill recommends **2-4 content lenses**. It is "
        "**not** a cap on the whole-repo health-audit route, which runs **all "
        "eight repo-shaped audits** (see Routes) — apply the 2-4 figure to "
        "per-change review, never to the audit set. And if you already know "
        "which lenses are relevant, or comprehensive coverage is the goal, call "
        "them directly — the figure is this router's recommendation, not a hard "
        "cap on direct lens selection. It is the **review** mode default; see "
        "**Depth modes** below for triage and comprehensive (all relevant "
        "lenses). `reviewing-pr-and-process-hygiene` is "
        "**additive** — on any PR it rides on top of the content lenses and does "
        "not spend one of the 2-4 slots.\n"
        "- Match the change against the routes below; when a change is several "
        "things at once, combine rows.\n"
        "- **Keep the brake pedal.** When a change ships abstraction, generality, "
        "or infrastructure ahead of the consumer that needs it (a generic with "
        "one impl, a crate with no caller yet), retain `checking-restraint` in "
        "the set — under the cap it is the lens most often dropped, and the one "
        "that catches building ahead of need.\n"
        "- For a **design doc or plan** (no code yet), use only lenses marked "
        "◆ in the catalog — the others read concrete code.\n"
        "- Lenses that share a research category name their primary owner in "
        "their SKILL.md; report each shared finding once, under the owner.\n"
        "- Nothing matches: default to `tracing-correctness-and-invariants` + "
        "`reviewing-naming-and-readability` + `checking-restraint`.\n"
        + (f"- After the lenses run, merge their findings with "
           f"`{manifest.synthesizer.name}` — one deduplicated, ranked report "
           "with a single verdict.\n" if manifest.synthesizer else "")
        + "\n" + modes_section(manifest)
        + "## Routes\n\n"
        "| When reviewing… | Run |\n"
        "|---|---|\n"
        f"{routes_table}\n\n"
        "## Catalog\n\n"
        "◆ = design-capable (also works on design docs and plans).\n\n"
        "**Diff-shaped — run on a change:**\n\n"
        f"{catalog('diff')}\n\n"
        "**Repo-shaped — run on the whole repository, scheduled or on demand:**\n\n"
        f"{catalog('repo')}\n\n"
        "**Decision-shaped — run on a decision or plan (ADR, RFC, adoption, "
        "deprecation, capacity/DR design), not a diff:**\n\n"
        f"{catalog('decision')}\n\n"
        "**Artifact-shaped — run when a standardized non-source artifact is "
        "present; detect the artifact, then load and apply its rubric:**\n\n"
        f"{catalog('artifact')}\n"
    )
    return f"---\n{fm}\n---\n\n{body}"


def generate_router(manifest: Manifest, skills_root: str = "skills") -> Path:
    out = Path(skills_root, manifest.router.name)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(build_router_md(manifest), encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(json.dumps(
            {"skills": [manifest.router.name], "scenarios": []}, indent=2) + "\n",
            encoding="utf-8")
    return out


def mode_floor_policy(manifest: Manifest) -> str:
    """The synthesizer's per-mode severity-floor policy. Empty when no modes.
    `escalating` keeps today's round-based floor; any other value pins the floor
    at that severity level (findings below it are dropped from the merged report)."""
    if not manifest.modes:
        return ""
    lines = [
        "## Severity floor by mode",
        "",
        "The merged report's severity floor depends on the active depth mode. "
        "Below the floor, findings are omitted from the verdict.",
        "",
        "| Mode | Floor | Effect |",
        "|---|---|---|",
    ]
    for mode in manifest.modes:
        if mode.floor == "escalating":
            effect = "round-based escalation (as today) — later re-review rounds raise the floor"
        else:
            effect = f"pinned at {mode.floor} — report everything down to {mode.floor}, nothing below"
        lines.append(f"| **{mode.name}** | {mode.floor} | {effect} |")
    return "\n".join(lines).rstrip() + "\n\n"   # block ends with a blank line; "" when no modes


def build_synthesizer_md(manifest: Manifest) -> str:
    """The back half of composition: merges the findings of the 2-4 lenses the
    router picked into one report — deduplicated, conflicts reconciled,
    severity-ranked, single verdict. Like the router, it is built entirely from
    the manifest (provenance carries no research sections), so regeneration is
    triggered by manifest edits, not docs drift."""
    sy = manifest.synthesizer
    front = {
        "name": sy.name,
        "description": sy.description,
        "provenance": {"taxonomy_version": manifest.taxonomy_version, "built_from": []},
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False,
                        allow_unicode=True).strip()
    severity = " > ".join(f"**{s}**" for s in sy.severity_order)
    top, *_ = sy.severity_order
    tension_rows = "\n".join(
        f"| `{t.between[0]}` ↔ `{t.between[1]}` | {t.about} | {t.resolve} |"
        for t in sy.tensions)
    router_name = manifest.router.name if manifest.router else "choosing-review-lenses"
    body = (
        f"# {sy.name}\n\n"
        "## When to use\n\n"
        f"{sy.description}\n\n"
        f"**Shape: composition.** Runs after `{router_name}` has picked the "
        "lenses and you have each lens's findings in hand; it produces the "
        "single review a human or agent actually reads. It adds no new checks "
        "of its own — it only merges.\n\n"
        "## Fan-out model\n\n"
        "Fan-out is **advisory by default**: you run each lens the router named, "
        "collect its findings, then apply the steps below to merge them. The "
        "finding shape is fixed (see *Finding contract*) so a harness that can "
        "invoke lenses in parallel may **mechanize** the same merge — the dedupe "
        "and ranking rules are deterministic. Automated or by hand, the output "
        "is identical. The same fixed finding shape also lets an orchestrator "
        "fan out across **many repositories** — one agent per repo emitting "
        "findings in this contract — and aggregate them centrally (see the "
        "multi-repo runbook under *Going deeper*).\n\n"
        "## How to synthesize\n\n"
        "1. **Collect** — gather every lens's findings, tagging each with the "
        "lens that raised it. Fold in findings from any **companion reviewer** "
        "run alongside the atlas lenses — the built-in code-review skill, a "
        "framework review (e.g. BMAD), linter or scanner output, or human notes "
        "— tagging each with its source so the merge is non-exclusive rather than "
        "atlas-only. A source that reported \"No findings\" contributes nothing; "
        "do not pad the report on its behalf.\n"
        "2. **Dedupe** — two findings at the **same location with the same root "
        "cause** are one finding. Keep the most specific wording and attribute "
        "it to the category's **primary owner** (named in each lens's *Shared "
        "categories* note); list the other lens only if it adds a distinct "
        "angle. Never report a shared finding twice.\n"
        "3. **Reconcile** — when two lenses pull opposite ways, do not silently "
        "drop one. Surface the tension and apply the default below, noting the "
        "trade-off so the author can override with evidence.\n"
        f"4. **Rank** — order by severity ({severity}). A {top}-level finding "
        "floats to the top no matter which lens raised it; correctness, "
        "security, and data-loss findings outrank style and nits.\n"
        "5. **Verdict** — one line at the top: **block**, **approve with "
        f"changes**, or **approve**. A single {top} is enough to block; only "
        "nits left means approve. **Valence governs the verdict, not route.** A "
        "`defect` sets the verdict per its severity *even when its remediation "
        "decision is routed elsewhere* — a GPL-incompatible dependency is a "
        "blocking defect **and** a `route: legal` escalation, not an \"approve\" "
        "that quietly defers to legal. Route only changes *who decides the fix*, "
        "never whether the diff has a problem. Only `improvement` nits and "
        "**non-defect** routed findings (a product, design, or leadership "
        "judgment call with no defect behind it) are surfaced and escalated "
        "without setting the engineering verdict. Likewise a `pre-existing` defect "
        "noticed in touched code is surfaced and routed to the implementer "
        "*without* setting this PR's verdict — the diff did not introduce it. If "
        "every lens found nothing, the whole report is \"No findings\" — do not "
        "manufacture a harsher verdict than the findings justify.\n"
        "6. **State coverage & limitations** — close the report with what the "
        "review did *not* establish: which lenses ran and which the router did "
        "not select, anything that could not be verified from the diff alone "
        "(needs runtime behavior, production data, or repo-wide context), and any "
        "finding asserted without direct evidence. A confident verdict silent on "
        "its own blind spots manufactures false assurance — itself a defect of "
        "the review. Name the gaps so the reader knows the review's edges. Keep it "
        "to a few lines; if coverage was complete and nothing was unverifiable, "
        "say so in one line rather than padding. This block is **always present**, "
        "including on a \"No findings\" report.\n\n"
        "## Reconciling lens tensions\n\n"
        "When the change trips one of these known opposing pairs, apply the "
        "default and state the trade-off:\n\n"
        "| Tension | About | Default resolution |\n"
        "|---|---|---|\n"
        f"{tension_rows}\n\n"
        "For a tension not in this table, prefer the **safer and simpler** "
        "option, and say what evidence would change the call.\n\n"
        "## Finding contract\n\n"
        "Normalize every lens finding to this shape before merging — it is what "
        "makes dedupe and ranking mechanical:\n\n"
        "- **location** — file and line/range, or a design-time "
        "`boundary:<from>→<to>` / `component:<name>` reference when a finding "
        "lives at an architecture boundary rather than a code line (the dedupe key, "
        "with root cause — two findings at the same location and root cause merge "
        "regardless of which lens raised them)\n"
        "- **severity** — one of the levels above\n"
        "- **valence** — `defect` (something is wrong) or `improvement` (a correct "
        "thing could be better). Defects are the default and drive the verdict; "
        "improvements are opt-in, `nit`-severity, and `route: implementer`.\n"
        "- **route** — who decides: `eng` (the default — engineering owns it), "
        "`implementer` (the change's author applies/defers/ignores), or "
        "`product` / `design` / `legal` / `leadership` when the decision authority "
        "sits outside engineering.\n"
        "- **attribution** — `introduced` (the default — this change caused it) or "
        "`pre-existing` (a real defect already present in the code this PR "
        "touches). A `pre-existing` finding is surfaced for the author's awareness, "
        "`route: implementer`, and does **not** set this PR's verdict — the diff "
        "did not introduce it; keep it scoped to touched code, opt-in, and "
        "default-quiet.\n"
        "- **lens** — which lens raised it (the primary owner after dedupe)\n"
        "- **finding** — what is wrong, concretely\n"
        "- **fix** — the suggested change, or the evidence needed to decide\n\n"
        "### Surfacing, routing, and valence\n\n"
        "Two axes sit alongside severity and govern what the merged report does "
        "with each finding:\n\n"
        "- **Detect-and-route (surfacing ≠ deciding).** A holistic review surfaces "
        "every reviewable finding with its evidence and routes the *decision* to "
        "the right owner via `route:`. It never silently drops a finding because "
        "\"that's not engineering's call,\" and never adjudicates a call that is "
        "not engineering's — legal exposure, a product trade-off, a leadership "
        "priority are surfaced under their route and escalated, not decided here. "
        "Routing names *who decides the remediation*; it never downgrades a "
        "finding's severity or valence. A finding that is both a `defect` and "
        "routed (a GPL dependency: `valence: defect, route: legal`) keeps its "
        "verdict weight in its severity section **and** carries the route tag for "
        "escalation. The only thing that stays out is a concern with no artifact "
        "at review time (market sizing, pricing, org politics); it re-enters once "
        "written into a decision record.\n"
        "- **Valence + anti-churn.** `defect` findings carry the strict "
        "anti-false-positive bar and set the verdict. `improvement` findings are "
        "admissible only when the team has opted up — the default is defect-only — "
        "and only as `nit`-severity, `route: implementer` suggestions the author "
        "may apply, defer, or ignore. Every improvement must clear a "
        "non-configurable **anti-churn floor**: it must genuinely improve (never a "
        "merely equivalent alternative) and must converge — no oscillation (A→B "
        "then B→A) and no lateral re-ordering once a dimension is as good as it can "
        "confidently be made. A team can turn improvement verbosity up; it cannot "
        "configure the suite to churn.\n"
        "- **Attribution (Boy-Scout, scoped).** A genuine defect this change did "
        "not introduce, but that sits in the code the PR *touches*, is surfaceable "
        "— tagged `pre-existing — not introduced by this change`. Like an "
        "improvement it is opt-in and default-quiet, `route: implementer`, and "
        "non-blocking: it never sets the verdict, because the diff did not cause "
        "it. Keep it scoped to touched code (a repo-wide sweep is the audits' job, "
        "not a diff review) and never let it expand the PR's scope; it only "
        "informs the author's fix-now / file-a-ticket / ignore call. This is the "
        "attribution axis — reviewable is not the same as introduced-here, just as "
        "it is not the same as who-decides (route) or defect-vs-improvement "
        "(valence).\n\n"
        "## Output format\n\n"
        "```text\n"
        "Verdict: <block | approve with changes | approve> — <one-line reason>\n\n"
        f"{sy.severity_order[0]}\n"
        "- <location> — <finding> (<lens>). <fix>\n\n"
        f"{sy.severity_order[min(1, len(sy.severity_order) - 1)]}\n"
        "- <location> — <finding> (<lens>) [route: legal]. <fix> — escalate the "
        "decision to <owner>\n\n"
        "Routed — non-defect decisions outside engineering\n"
        "- <location> — <finding> (<lens>) [route: product|design|legal|leadership]."
        " <what must be decided, and by whom>\n\n"
        "Improvements — opt-in, optional\n"
        "- <location> — <suggestion> (<lens>) [improvement, route: implementer]."
        " <apply | defer | ignore>\n\n"
        "Pre-existing — noticed in touched code, not introduced here\n"
        "- <location> — <defect> (<lens>) [pre-existing, route: implementer]."
        " <fix now | file a ticket | ignore>\n\n"
        "Tensions\n"
        "- <lens> ↔ <lens>: <how it was resolved here>\n\n"
        "Coverage & limitations\n"
        "- Lenses run: <names>. Not selected: <names, or \"none\">.\n"
        "- Not verifiable from this diff: <what needs runtime, data, or repo-wide "
        "context to confirm, or \"nothing\">.\n"
        "```\n\n"
        "Omit any **findings** section with nothing in it — including **Routed**, "
        "**Improvements**, and **Pre-existing** (the last two are absent entirely "
        "unless the team opted into improvement-valence / Boy-Scout surfacing). "
        "**Coverage & limitations** "
        "is the exception: it is always present, even on a \"No findings\" report. "
        "Keep each finding to one or two lines; the detail lives in the "
        "originating lens's output, not restated here.\n\n"
        + mode_floor_policy(manifest)
        + "## Reviewer discipline\n\n"
        "Synthesis must not inflate. Do not raise a finding no lens reported, do "
        "not upgrade a severity to seem thorough, and do not turn \"No findings\" "
        "into a verdict with changes. The merged report is exactly the union of "
        "real lens findings, deduplicated and ordered — nothing added.\n\n"
        "## Going deeper\n\n"
        f"- [{router_name}](../{router_name}/SKILL.md) — the front half: picks "
        "which lenses to run before you synthesize their output.\n"
        "- [multi-repo audit runbook](../../docs/runbooks/multi-repo-audit.md) — "
        "fan the suite out across many repositories with background agents and "
        "aggregate their findings through this contract.\n"
    )
    return f"---\n{fm}\n---\n\n{body}"


def generate_synthesizer(manifest: Manifest, skills_root: str = "skills") -> Path:
    out = Path(skills_root, manifest.synthesizer.name)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(build_synthesizer_md(manifest), encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(json.dumps(
            {"skills": [manifest.synthesizer.name], "scenarios": []}, indent=2) + "\n",
            encoding="utf-8")
    return out


def build_collapsed_synthesis(manifest: Manifest) -> str:
    """The synthesizer procedure as a bundled reference file (no frontmatter).
    Reuses build_synthesizer_md (which already includes mode_floor_policy) and
    strips the LEADING YAML frontmatter block so an entrypoint can Read it
    directly. Also drops the standalone "Going deeper" section, whose relative
    links (../<router>/SKILL.md, ../../docs/...) point outside the collapsed
    bundle and would 404 when an agent follows them — the entrypoint SKILL.md
    already links the lenses, and this file is loaded directly, not navigated
    from."""
    full = build_synthesizer_md(manifest)
    # Raise loudly rather than silently shipping a frontmatter-laden bundle if the
    # synthesizer's output shape ever changes.
    if not full.startswith("---\n"):
        raise ValueError("build_synthesizer_md output has no leading frontmatter to strip")
    end = full.find("\n---\n", len("---\n"))   # closing fence of the first block only
    if end == -1:
        raise ValueError("build_synthesizer_md frontmatter block is not terminated")
    body = full[end + len("\n---\n"):].lstrip("\n")
    marker = "\n## Going deeper\n"
    idx = body.find(marker)
    if idx != -1:
        body = body[:idx].rstrip() + "\n"
    # The Fan-out-model prose cross-refs the now-removed section; drop the dangling
    # "under *Going deeper*" pointer so the bundle is self-consistent (no-op if the
    # phrase ever changes).
    body = body.replace(" under *Going deeper*", "")
    return body


def build_entrypoint_md(manifest: Manifest, entrypoint: Entrypoint) -> str:
    lenses = entrypoint_lenses(manifest, entrypoint)
    lens_names = {s.name for s in lenses}
    front = {
        "name": entrypoint.name,
        "description": entrypoint.description,
        "provenance": {"taxonomy_version": manifest.taxonomy_version, "built_from": []},
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False,
                        allow_unicode=True).strip()

    # Routes from the router that touch this entrypoint's lenses.
    rows = []
    if manifest.router:
        for route in manifest.router.routes:
            if any(lens in lens_names for lens in route.run):
                run = ", ".join(f"`{lens}`" for lens in route.run if lens in lens_names)
                rows.append(f"| {route.when} | {run} |")
    routes_table = "\n".join(rows) if rows else "| (any item in scope) | all lenses below |"

    # Each lens links to its loadable bundle, so the entrypoint can Read it on
    # demand; ◆ marks design-capable lenses and the picker gives the one-liner.
    catalog = "\n".join(
        f"- [`{s.name}`](reference/lenses/{s.name}/body.md){' ◆' if s.design else ''}"
        + (f" — {s.picker}" if s.picker else "")
        for s in lenses)

    body = (
        f"# {entrypoint.name}\n\n"
        "## When to use\n\n"
        f"{entrypoint.body or entrypoint.description}\n\n"
        "## How this works\n\n"
        "Rank the relevant lenses below by relevance to what is being reviewed, "
        "pick the breadth from the depth mode (default **review**), then for each "
        "selected lens **load its bundle** and apply it:\n\n"
        "- Read `reference/lenses/<lens>/body.md` — the lens's checklist and examples. "
        "Open `reference/lenses/<lens>/tool-rules.md` or `sources.md` only if deeper "
        "tooling/provenance is called for.\n"
        "- After the lenses run, merge their findings with the procedure in "
        "`reference/synthesis.md` — one deduplicated, ranked report with a single verdict.\n\n"
        + modes_section(manifest)
        + "## Routes\n\n"
        "| When reviewing… | Run |\n"
        "|---|---|\n"
        f"{routes_table}\n\n"
        "## Lenses\n\n"
        "◆ = design-capable.\n\n"
        f"{catalog}\n"
    )
    return f"---\n{fm}\n---\n\n{body}"


def collapsed_plugin_manifest(root_plugin_path: str = ".claude-plugin/plugin.json") -> dict:
    """Derive the collapsed plugin manifest from the root one (single source) so
    metadata stays in sync; only name/displayName/description differ."""
    p = Path(root_plugin_path)
    if not p.exists():
        raise FileNotFoundError(
            f"root plugin manifest not found at {root_plugin_path}; "
            "cannot derive the collapsed plugin manifest")
    base = json.loads(p.read_text(encoding="utf-8"))
    base["name"] = "code-quality-atlas-collapsed"
    base["displayName"] = base.get("displayName", "Code Quality Atlas") + " (collapsed)"
    base["description"] = ("Collapsed 4-entrypoint form of the code-quality-atlas "
                           "suite for cloud / account-skill / context-budget installs. "
                           "Lenses are bundled and loaded on demand.")
    return base


def generate_collapsed(manifest: Manifest, docs_root: str = ".", skills_root: str = "skills",
                       collapsed_root: str = "collapsed") -> list[Path]:
    """Emit the collapsed form: 4 entrypoint skills (each bundling its shape's
    lenses + synthesis) plus a generated .claude-plugin/plugin.json. Prunes any
    entrypoint directory no longer in the manifest so the committed tree can't go
    stale."""
    written: list[Path] = []
    skills_dir = Path(collapsed_root, "skills")
    current = {ep.name for ep in manifest.entrypoints}
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            if child.is_dir() and child.name not in current:
                shutil.rmtree(child)   # prune a removed entrypoint
    for ep in manifest.entrypoints:
        out = Path(collapsed_root, "skills", ep.name)
        (out / "reference" / "lenses").mkdir(parents=True, exist_ok=True)
        (out / "evals").mkdir(parents=True, exist_ok=True)
        (out / "SKILL.md").write_text(build_entrypoint_md(manifest, ep), encoding="utf-8")
        (out / "reference" / "synthesis.md").write_text(
            build_collapsed_synthesis(manifest), encoding="utf-8")
        for skill in entrypoint_lenses(manifest, ep):
            generate_lens_bundle(skill, out / "reference" / "lenses",
                                 docs_root=docs_root, skills_root=skills_root)
        if not (out / "evals" / "eval.json").exists():
            (out / "evals" / "eval.json").write_text(
                json.dumps({"skills": [ep.name], "scenarios": []}, indent=2) + "\n",
                encoding="utf-8")
        written.append(out)
    pm_dir = Path(collapsed_root, ".claude-plugin")
    pm_dir.mkdir(parents=True, exist_ok=True)
    plugin_json = pm_dir / "plugin.json"
    plugin_json.write_text(
        json.dumps(collapsed_plugin_manifest(
            root_plugin_path=str(Path(docs_root, ".claude-plugin", "plugin.json"))),
            indent=2) + "\n", encoding="utf-8")
    written.append(plugin_json)   # the generated manifest is an emitted artifact too
    return written
