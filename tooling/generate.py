# SPDX-License-Identifier: MIT
# tooling/generate.py
from __future__ import annotations
import json
import yaml
from pathlib import Path
from tooling.manifest import Manifest, Skill, Source
from tooling.sections import (extract_bullets, extract_section,
                              extract_subsection, section_hash)

_KIND_TITLE = {
    "heuristics": "Reviewable heuristics",
    "tooling": "Tool rules to triage",
    "references": "References to mine",
}


def build_reference(skill: Skill, kind: str, docs_root: str = ".") -> str:
    """Concatenate the `kind` subsection from each source category into one
    reference file, each under a `## From category #n` header, with a ToC."""
    if kind not in _KIND_TITLE:
        raise ValueError(f"unknown kind {kind!r}; must be one of {list(_KIND_TITLE)}")
    entries = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        body = extract_subsection(extract_section(text, src.section), kind).strip()
        if body:
            entries.append((src.section, body))
    toc = "\n".join(f"- From category #{n}" for n, _ in entries)
    parts = [f"## From category #{n}\n\n{body}" for n, body in entries]
    header = f"# {_KIND_TITLE[kind]} — {skill.name}\n\n## Contents\n{toc}\n"
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
        budget = max(_TOP_CHECKS_BUDGET - _CROSS_REF_QUOTA * len(crosses),
                     len(primaries))
        base, rem = divmod(budget, len(primaries))
        for i, bullets in enumerate(primaries):
            checks.extend(bullets[:base + (1 if i < rem else 0)])
    for bullets in crosses:
        checks.extend(bullets[:_CROSS_REF_QUOTA])
    return checks


def _scope_line(skill: Skill) -> str:
    if skill.shape == "repo":
        return ("**Shape: repo.** Run against the whole repository (scheduled or "
                "on demand), not a single diff.")
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
    checks = "\n".join(f"- {c}" for c in top_checks(skill, docs_root))
    body = (
        f"# {skill.name}\n\n"
        "## When to use\n\n"
        f"{skill.description}\n\n"
        f"{_scope_line(skill)}\n\n"
        "## Reviewer discipline\n\n"
        "Report only real problems. If the code correctly handles the case, reply "
        "\"No findings\" and stop — do not invent issues, and do not suggest changes to "
        "code that is already correct. This guards against false positives on correct "
        "code; still report every genuine issue you do find, with its full detail.\n\n"
        "## Top checks\n\n"
        "The head of the full checklist — enough for a first pass without opening "
        "any reference file:\n\n"
        f"{checks}\n"
        f"{_cross_ref_note(skill, owners)}\n"
        "## Going deeper\n\n"
        "- [reference/heuristics.md](reference/heuristics.md) — the full checklist; "
        "open it when the change sits squarely in this lens's domain.\n"
        "- [examples.md](examples.md) — concrete good/bad findings, and the output "
        "format to match.\n"
        "- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules "
        "covering the mechanical subset; for wiring up linters, not needed for the "
        "judgment review itself.\n"
        "- [reference/sources.md](reference/sources.md) — the research behind each "
        "check; for provenance, not needed during a review.\n"
    )
    return f"---\n{fm}\n---\n\n{body}"


def generate_skill(skill: Skill, taxonomy_version: str,
                   docs_root: str = ".", skills_root: str = "skills",
                   owners: dict[int, str] | None = None) -> Path:
    out = Path(skills_root, skill.name)
    (out / "reference").mkdir(parents=True, exist_ok=True)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(
        build_skill_md(skill, taxonomy_version, docs_root, owners), encoding="utf-8")
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


def primary_owners(manifest: Manifest) -> dict[int, str]:
    """category -> the skill that primarily owns it (G1 guarantees uniqueness)."""
    owners: dict[int, str] = {}
    for s in manifest.skills:
        for src in s.built_from:
            if src.category not in s.cross_ref:
                owners[src.category] = s.name
    return owners


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
        f"{r.description}\n\n"
        "## How to pick\n\n"
        "- Run **2-4 content lenses** per change; more dilutes attention and "
        "duplicates findings. `reviewing-pr-and-process-hygiene` is **additive** "
        "— on any PR it rides on top of those lenses and does not spend one of "
        "the 2-4 slots.\n"
        "- Match the change against the routes below; when a change is several "
        "things at once, combine rows but keep the cap.\n"
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
        "`reviewing-naming-and-readability` + `checking-restraint`.\n\n"
        "## Routes\n\n"
        "| When reviewing… | Run |\n"
        "|---|---|\n"
        f"{routes_table}\n\n"
        "## Catalog\n\n"
        "◆ = design-capable (also works on design docs and plans).\n\n"
        "**Diff-shaped — run on a change:**\n\n"
        f"{catalog('diff')}\n\n"
        "**Repo-shaped — run on the whole repository, scheduled or on demand:**\n\n"
        f"{catalog('repo')}\n"
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
