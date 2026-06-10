# tooling/generate.py
from __future__ import annotations
import json
import yaml
from pathlib import Path
from tooling.manifest import Skill, Source
from tooling.sections import extract_section, extract_subsection, section_hash

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


def build_skill_md(skill: Skill, taxonomy_version: str, docs_root: str = ".") -> str:
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
    body = (
        f"# {skill.name}\n\n"
        "## When to use\n\n"
        f"{skill.description}\n\n"
        "## Top checks\n\n"
        "Start with the full checklist, then escalate to the references as needed.\n\n"
        "- See [reference/heuristics.md](reference/heuristics.md) for the full review checklist.\n"
        "- See [reference/tool-rules.md](reference/tool-rules.md) for static-analysis rules to triage.\n"
        "- See [reference/sources.md](reference/sources.md) for the references behind each check.\n"
        "- See [examples.md](examples.md) for good/bad examples.\n"
    )
    return f"---\n{fm}\n---\n\n{body}"


def generate_skill(skill: Skill, taxonomy_version: str,
                   docs_root: str = ".", skills_root: str = "skills") -> Path:
    out = Path(skills_root, skill.name)
    (out / "reference").mkdir(parents=True, exist_ok=True)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(
        build_skill_md(skill, taxonomy_version, docs_root), encoding="utf-8")
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
