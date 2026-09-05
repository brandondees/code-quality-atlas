# SPDX-License-Identifier: MIT
# tooling/generate_skill.py
"""Renders a standalone lens's SKILL.md and its bundled reference/ files
(heuristics or artifact rubrics, tool-rules, sources)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import yaml

from tooling.generate_common import (
    _cross_ref_note,
    _escape_table_cell,
    _gen_header,
    _gen_trailer,
    _scope_line,
    build_reference,
    mechanizing_and_process_notes,
    reviewer_discipline_intro,
)
from tooling.manifest import Artifact, Skill
from tooling.sections import (
    extract_bullets,
    extract_section,
    extract_subsection,
    is_priority,
    section_hash,
    strip_priority,
)

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
            extract_subsection(extract_section(text, src.section), "heuristics")
        )
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
                stacklevel=2,
            )
        budget = max(
            _TOP_CHECKS_BUDGET - _CROSS_REF_QUOTA * len(crosses), len(primaries)
        )
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
            checks.extend(non_prio[: base + (1 if i < rem else 0)])
    # Cross-ref categories keep their small position-based quota and ignore the
    # priority marker — a factor is force-surfaced only in the lens that *owns*
    # it, not in every lens that shares the category. Markers are still stripped.
    for bullets in crosses:
        checks.extend(strip_priority(b) for b in bullets[:_CROSS_REF_QUOTA])
    return checks


def _all_heuristics_bullets(skill: Skill, docs_root: str = ".") -> list[str]:
    """Every heuristics bullet across built_from, in source order, exactly as
    reference/heuristics.md (build_reference) renders them. Compared against
    top_checks's budgeted subset to detect a lens whose full checklist already
    fits the inline budget (#391 problem 3): for those, reference/heuristics.md
    is a verbatim duplicate of `## Top checks`, not a deeper disclosure level."""
    bullets: list[str] = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        body = strip_priority(
            extract_subsection(extract_section(text, src.section), "heuristics").strip()
        )
        bullets.extend(extract_bullets(body))
    return bullets


def build_skill_md(
    skill: Skill,
    taxonomy_version: str,
    docs_root: str = ".",
    owners: dict[int, str] | None = None,
) -> str:
    built_from = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        built_from.append(
            {
                "category": src.section,
                "source": src.source,
                "hash": section_hash(text, src.section),
            }
        )
    front = {
        "name": skill.name,
        "description": skill.description,
        "provenance": {"taxonomy_version": taxonomy_version, "built_from": built_from},
    }
    fm = yaml.safe_dump(
        front, sort_keys=False, default_flow_style=False, allow_unicode=True
    ).strip()
    # A one-line scannable summary (the same `picker` the router catalog uses),
    # surfaced at the top of each lens so the lens is recognizable at a glance
    # without reading the full trigger-rich description below it.
    tagline = f"*{skill.picker.strip()}*\n\n" if skill.picker else ""
    # The "checks" surface differs by shape: a diff/repo/decision lens inlines the
    # head of its checklist; an artifact lens instead lists its detect→rubric table,
    # because its checks live in per-artifact bundled rubrics loaded on a presence hit
    # (D15 — pay only when the artifact is present).
    if skill.shape == "artifact":
        rows = "\n".join(
            f"| {_escape_table_cell(a.name)} | {_escape_table_cell(a.detect)} | "
            f"[reference/{a.slug}.md](reference/{a.slug}.md) |"
            for a in skill.artifacts
        )
        core_block = (
            "## Artifacts\n\n"
            "Detect which artifact the change adds or touches, then open its rubric "
            "and review the artifact against that published standard:\n\n"
            "| Artifact | Activate when | Rubric to apply |\n"
            "|---|---|---|\n"
            f"{rows}\n\n"
        )
        going_deeper = (
            "## Going deeper\n\n"
            + "".join(
                f"- [reference/{a.slug}.md](reference/{a.slug}.md) — the rubric for "
                f"{a.name}; open it on a presence hit and review against it.\n"
                for a in skill.artifacts
            )
            + "- [examples.md](examples.md) — concrete good/bad findings, and the "
            "output format to match.\n"
            "- [reference/tool-rules.md](reference/tool-rules.md) — the tools that "
            "mechanize part of each rubric; for wiring up checks, not needed for the "
            "judgment review itself.\n"
            "- [reference/sources.md](reference/sources.md) — the published standards "
            "behind each rubric; for provenance, not needed during a review.\n"
        )
    else:
        check_list = top_checks(skill, docs_root)
        checks = "\n".join(f"- {c}" for c in check_list)
        # When the whole checklist already fits the inline budget, `## Top checks`
        # already *is* the full checklist — reference/heuristics.md would be a
        # verbatim duplicate, not a deeper disclosure level (#391 problem 3).
        heuristics_is_duplicate = check_list == _all_heuristics_bullets(
            skill, docs_root
        )
        lead_in = (
            "This is the full checklist — nothing else to open for it:\n\n"
            if heuristics_is_duplicate
            else "The head of the full checklist — enough for a first pass without "
            "opening any reference file:\n\n"
        )
        core_block = (
            f"## Top checks\n\n{lead_in}{checks}\n{_cross_ref_note(skill, owners)}\n"
        )
        heuristics_pointer = (
            ""
            if heuristics_is_duplicate
            else "- [reference/heuristics.md](reference/heuristics.md) — the full "
            "checklist; open it when the change sits squarely in this lens's "
            "domain.\n"
        )
        going_deeper = (
            "## Going deeper\n\n"
            f"{heuristics_pointer}"
            "- [examples.md](examples.md) — concrete good/bad findings, and the output "
            "format to match.\n"
            "- [reference/tool-rules.md](reference/tool-rules.md) — static-analysis rules "
            "covering the mechanical subset; for wiring up linters, not needed for the "
            "judgment review itself.\n"
            "- [reference/sources.md](reference/sources.md) — the research behind each "
            "check; for provenance, not needed during a review.\n"
        )
    body = (
        f"# {skill.name}\n\n"
        f"{tagline}"
        "## When to use\n\n"
        f"{skill.description}\n\n"
        f"{_scope_line(skill)}\n\n"
        f"{reviewer_discipline_intro(skill)}"
        f"{core_block}"
        f"{mechanizing_and_process_notes()}"
        f"{going_deeper}"
    )
    return f"---\n{fm}\n---\n\n{body}" + _gen_trailer(skill)


def build_artifact_rubric(
    skill: Skill, artifact: Artifact, docs_root: str = "."
) -> str:
    """The bundled rubric file for one artifact of an artifact-shaped lens: the
    heuristics, references, and tooling of that artifact's rubric section, loaded
    on a presence hit. Subsection headings are promoted ### → ## so the file's
    heading levels increment by one (H1 title → H2 sections)."""
    src = next(s for s in skill.built_from if s.section == artifact.rubric)
    section = extract_section(
        Path(docs_root, src.path).read_text(encoding="utf-8"), src.section
    )

    def block(kind: str) -> str:
        body = strip_priority(extract_subsection(section, kind).strip())
        return ("## " + body[4:]) if body.startswith("### ") else body

    parts = [
        f"# Rubric — {artifact.name}",
        (
            f"Review a **{artifact.name}** against its published standard. Activate "
            f"when {artifact.detect}. Report only real deviations from the standard; "
            'if the artifact is well-formed, reply "No findings".'
        ),
    ]
    parts += [
        b for b in (block("heuristics"), block("references"), block("tooling")) if b
    ]
    return "\n\n".join(parts) + "\n"


def generate_skill(
    skill: Skill,
    taxonomy_version: str,
    docs_root: str = ".",
    skills_root: str = "skills",
    owners: dict[int, str] | None = None,
) -> Path:
    out = Path(skills_root, skill.name)
    (out / "reference").mkdir(parents=True, exist_ok=True)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(
        build_skill_md(skill, taxonomy_version, docs_root, owners), encoding="utf-8"
    )
    # An artifact lens replaces the single concatenated heuristics.md with one
    # bundled rubric file per artifact (loaded on a presence hit); the combined
    # tool-rules.md / sources.md still back the Mechanizing and Going-deeper links.
    if skill.shape == "artifact":
        for a in skill.artifacts:
            (out / "reference" / f"{a.slug}.md").write_text(
                _gen_header(skill) + build_artifact_rubric(skill, a, docs_root),
                encoding="utf-8",
            )
    else:
        # Skip (and prune a stale copy of) reference/heuristics.md when it would be
        # a verbatim duplicate of `## Top checks` — see build_skill_md (#391).
        heuristics_path = out / "reference" / "heuristics.md"
        if top_checks(skill, docs_root) == _all_heuristics_bullets(skill, docs_root):
            if heuristics_path.exists():
                heuristics_path.unlink()
        else:
            heuristics_path.write_text(
                _gen_header(skill) + build_reference(skill, "heuristics", docs_root),
                encoding="utf-8",
            )
    (out / "reference" / "tool-rules.md").write_text(
        _gen_header(skill) + build_reference(skill, "tooling", docs_root),
        encoding="utf-8",
    )
    (out / "reference" / "sources.md").write_text(
        _gen_header(skill) + build_reference(skill, "references", docs_root),
        encoding="utf-8",
    )
    if not (out / "examples.md").exists():
        (out / "examples.md").write_text(
            f"# Examples — {skill.name}\n\n"
            "<!-- Add concrete good/bad input→finding pairs during refinement. -->\n",
            encoding="utf-8",
        )
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(
            json.dumps({"skills": [skill.name], "scenarios": []}, indent=2) + "\n",
            encoding="utf-8",
        )
    return out
