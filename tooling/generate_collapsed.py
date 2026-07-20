# SPDX-License-Identifier: MIT
# tooling/generate_collapsed.py
"""Renders the collapsed 4-entrypoint form: one skill per shape, each bundling
its lenses (loaded on demand as reference/lenses/<lens>/{body,tool-rules,
sources}.md) plus the synthesis procedure, for cloud / account-skill /
context-budget-constrained installs."""
from __future__ import annotations
import json
import re
import shutil
import yaml
from pathlib import Path
from tooling.manifest import Entrypoint, Manifest, Skill
from tooling.generate_common import _escape_table_cell, _scope_line, build_reference, modes_section
from tooling.generate_skill import build_artifact_rubric
from tooling.generate_synthesizer import build_synthesizer_md

# Matches skill-md.md's own ~100-line ToC rubric (category #101); a lens
# bundle this long benefits from the same navigability the rubric demands
# of a third party's SKILL.md.
_TOC_LINE_THRESHOLD = 100


class CollapsedOverlapError(ValueError):
    """Raised when generate_collapsed's prune target would overlap the standalone
    skills tree — an operator misconfiguration, not an internal failure. Subclasses
    ValueError so it reads as the bad-argument condition it is, while giving the CLI
    a precise type to catch (so unrelated internal ValueErrors still surface)."""


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


def _artifacts_block(skill: Skill) -> str:
    """The `## Artifacts` detect→rubric table for an artifact-shaped lens's
    bundle, mirroring build_skill_md's artifact branch but with links relative
    to the bundle directory (the rubric files sit alongside body.md as
    `<slug>.md`, not under a `reference/` subdirectory)."""
    rows = "\n".join(
        f"| {_escape_table_cell(a.name)} | {_escape_table_cell(a.detect)} | "
        f"[{a.slug}.md]({a.slug}.md) |"
        for a in skill.artifacts)
    return (
        "## Artifacts\n\n"
        "Detect which artifact the change adds or touches, then open its rubric "
        "and review the artifact against that published standard:\n\n"
        "| Artifact | Activate when | Rubric to apply |\n"
        "|---|---|---|\n"
        f"{rows}\n\n")


def _github_anchor(heading: str) -> str:
    """Approximate GitHub's heading-anchor slug algorithm: lowercase, drop
    everything except word characters, whitespace, and hyphens, then turn
    whitespace into hyphens. Manually verified against GitHub's rendering for
    the `## Contents` ToCs #165 added to examples.md (e.g. "Bad → finding
    (Terraform scan)" → "bad--finding-terraform-scan")."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s", "-", slug)


def _toc_for_body(body: str) -> str:
    """A `## Contents` heading list linking every `## ` heading in `body`, in
    order, with GitHub's duplicate-heading dedup suffixing (`-1`, `-2`, ...
    appended to the *n*th repeat of an identical slug). Returns "" if `body`
    has no `## ` headings to link."""
    headings = [line[3:].strip() for line in body.splitlines() if line.startswith("## ")]
    if not headings:
        return ""
    seen: dict[str, int] = {}
    lines = []
    for heading in headings:
        slug = _github_anchor(heading)
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}-{n}"
        lines.append(f"- [{heading}](#{anchor})")
    return "## Contents\n\n" + "\n".join(lines) + "\n\n"


def lens_bundle_body(skill: Skill, docs_root: str = ".", skills_root: str = "skills") -> str:
    """The `body.md` an entrypoint loads for one lens: when-to-use + the full
    heuristics checklist (or, for an artifact-shaped lens, the detect→rubric
    table — its checks live in the per-artifact rubric files generate_lens_bundle
    writes alongside this one, loaded on a presence hit, mirroring build_skill_md)
    + curated examples + links to the deeper bundled files. Examples come from
    the standalone tree's hand-refined examples.md (canonical); tool-rules/sources
    are a further disclosure level, linked not inlined."""
    picker = f"{skill.picker}\n\n" if skill.picker else ""
    examples_path = Path(skills_root, skill.name, "examples.md")
    examples = examples_path.read_text(encoding="utf-8") if examples_path.exists() else ""
    # The standalone examples.md carries its own `# Examples — <lens>` H1; strip a
    # leading H1 so the bundle keeps one top-level heading.
    examples = examples.strip()
    if examples.startswith("# "):
        examples = examples.split("\n", 1)[1].strip() if "\n" in examples else ""
    examples_block = f"## Examples\n\n{examples}\n\n" if examples else ""
    if skill.shape == "artifact":
        core_block = _artifacts_block(skill)
        going_deeper = (
            "## Going deeper\n\n"
            + "".join(f"- [{a.slug}.md]({a.slug}.md) — the rubric for {a.name}; "
                     f"open it on a presence hit and review against it.\n"
                     for a in skill.artifacts)
            + "- [tool-rules.md](tool-rules.md) — the tools that mechanize part of "
            "each rubric; for wiring up checks, not needed for the judgment review "
            "itself.\n"
            "- [sources.md](sources.md) — the published standards behind each "
            "rubric; for provenance, not needed during a review.\n")
    else:
        heuristics = _checklist_body(skill, docs_root=docs_root)
        # Give `## Checklist` a lead-in before the per-category heuristics, mirroring
        # how `## Examples` opens with prose rather than dropping straight onto a
        # sub-header. Without it the section header sits directly on `## From
        # category #NN`, reading as an empty header. Suppress the whole section if a
        # lens carries no heuristics, so a future heuristics-less lens never ships a
        # bare `## Checklist`.
        core_block = (
            "## Checklist\n\n"
            "The full review checklist, grouped by the research category each check "
            "draws from:\n\n"
            f"{heuristics}\n\n"
        ) if heuristics else ""
        going_deeper = (
            "## Going deeper\n\n"
            "- [tool-rules.md](tool-rules.md) — static-analysis rules for the "
            "mechanical subset; for wiring linters, not needed for the judgment "
            "review.\n"
            "- [sources.md](sources.md) — the research behind each check; for "
            "provenance.\n")
    header = f"# {skill.name}\n\n{picker}"
    sections = (
        "## When to use\n\n"
        f"{_scope_line(skill)}\n\n"
        f"{core_block}"
        f"{examples_block}"
        f"{going_deeper}"
    )
    toc = ""
    if len((header + sections).splitlines()) > _TOC_LINE_THRESHOLD:
        toc = _toc_for_body(sections)
    return header + toc + sections


def _gen_header(skill: Skill, *, with_examples: bool = False) -> str:
    """A one-block 'generated — edit the source, not me' banner for the collapsed
    lens-bundle files. These are pure generated artifacts assembled from the research
    docs (and, for `body.md`, the lens's hand-refined examples.md); a contributor who
    edits a collapsed copy directly would diverge it from its source (the
    `tooling.cli drift` / regenerate gate catches that after the fact — this header
    prevents it up front). An HTML comment so it renders invisibly and is
    markdownlint-clean. `with_examples` names examples.md as a source only for the file
    that actually inlines it (body.md), not tool-rules.md / sources.md."""
    examples = (
        f" and skills/{skill.name}/examples.md (worked examples)" if with_examples else ""
    )
    return (
        "<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.\n"
        f"     Canonical sources: docs/research/{examples}.\n"
        "     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->\n\n"
    )


def generate_lens_bundle(skill: Skill, lenses_dir: Path, docs_root: str = ".",
                         skills_root: str = "skills") -> Path:
    """Write reference/lenses/<skill>/{body,tool-rules,sources}.md and return the
    dir. An artifact-shaped lens additionally gets one rubric file per artifact
    (<slug>.md, loaded on a presence hit — see _artifacts_block), mirroring how
    generate_skill replaces the standalone tree's heuristics.md the same way."""
    dest = Path(lenses_dir, skill.name)
    dest.mkdir(parents=True, exist_ok=True)
    # Only body.md inlines examples.md; tool-rules.md / sources.md draw from docs/research only.
    (dest / "body.md").write_text(
        _gen_header(skill, with_examples=True) + lens_bundle_body(skill, docs_root, skills_root),
        encoding="utf-8")
    if skill.shape == "artifact":
        for a in skill.artifacts:
            (dest / f"{a.slug}.md").write_text(
                _gen_header(skill) + build_artifact_rubric(skill, a, docs_root),
                encoding="utf-8")
    (dest / "tool-rules.md").write_text(
        _gen_header(skill) + build_reference(skill, "tooling", docs_root), encoding="utf-8")
    (dest / "sources.md").write_text(
        _gen_header(skill) + build_reference(skill, "references", docs_root), encoding="utf-8")
    return dest


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

    # Routes from the router that touch this entrypoint's lenses. A route's
    # note travels with it even when the note calls out a lens the shape
    # filter excluded from `run` (e.g. a repo-shaped auto-include on a
    # diff-shaped entrypoint) — otherwise that lens has no path into this
    # entrypoint at all: not bundled (shape-filtered), not in the run list
    # (shape-filtered), and silently missing from the note too.
    rows = []
    if manifest.router:
        for route in manifest.router.routes:
            if any(lens in lens_names for lens in route.run):
                run = ", ".join(f"`{lens}`" for lens in route.run if lens in lens_names)
                if route.note:
                    run += f" — {_escape_table_cell(route.note)}"
                rows.append(f"| {_escape_table_cell(route.when)} | {run} |")
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


def generate_collapsed(manifest: Manifest, docs_root: str = ".", skills_root: str = "skills",
                       collapsed_root: str = "collapsed") -> list[Path]:
    """Emit the collapsed form: 4 entrypoint skills (each bundling its shape's
    lenses + synthesis) plus a generated .claude-plugin/plugin.json. Prunes any
    entrypoint directory no longer in the manifest so the committed tree can't go
    stale."""
    written: list[Path] = []
    skills_dir = Path(collapsed_root, "skills")
    # Guard the prune below: it rmtree's every child of `skills_dir` not in the
    # manifest. If a miscall points `skills_dir` at — or above — the standalone
    # skills tree (e.g. collapsed_root="." with skills_root="skills"), that prune
    # would silently delete the real skills. Refuse instead. `is_relative_to` is
    # already true when the two paths are equal, so it covers both the
    # same-directory and skills-nested-under-prune-target cases in one check.
    skills_root_resolved = Path(skills_root).resolve()
    skills_dir_resolved = skills_dir.resolve()
    if skills_root_resolved.is_relative_to(skills_dir_resolved):
        raise CollapsedOverlapError(
            f"refusing to generate collapsed output into {skills_dir}: its prune "
            f"step would delete the standalone skills tree at {skills_root}; "
            f"collapsed_root must not overlap skills_root")
    current = {ep.name for ep in manifest.entrypoints}
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            if child.is_dir() and child.name not in current:
                shutil.rmtree(child)   # prune a removed entrypoint
    for ep in manifest.entrypoints:
        out = Path(collapsed_root, "skills", ep.name)
        lenses_dir = out / "reference" / "lenses"
        lenses_dir.mkdir(parents=True, exist_ok=True)
        (out / "evals").mkdir(parents=True, exist_ok=True)
        (out / "SKILL.md").write_text(build_entrypoint_md(manifest, ep), encoding="utf-8")
        (out / "reference" / "synthesis.md").write_text(
            build_collapsed_synthesis(manifest), encoding="utf-8")
        ep_lenses = entrypoint_lenses(manifest, ep)
        current_lens_names = {skill.name for skill in ep_lenses}
        # Prune a lens dropped from this entrypoint (deleted, reshaped, or
        # unbundled) the same way the loop above prunes a removed entrypoint —
        # otherwise its stale reference/lenses/<name>/ lingers in the committed
        # tree forever with nothing to remove it.
        for child in lenses_dir.iterdir():
            if child.is_dir() and child.name not in current_lens_names:
                shutil.rmtree(child)
        for skill in ep_lenses:
            generate_lens_bundle(skill, lenses_dir,
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
