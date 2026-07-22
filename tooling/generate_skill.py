# SPDX-License-Identifier: MIT
# tooling/generate_skill.py
"""Renders a standalone lens's SKILL.md and its bundled reference/ files
(heuristics or artifact rubrics, tool-rules, sources)."""
from __future__ import annotations
import json
import warnings
import yaml
from pathlib import Path
from tooling.manifest import Artifact, Skill
from tooling.sections import (extract_bullets, extract_section,
                              extract_subsection, is_priority, section_hash,
                              strip_priority)
from tooling.generate_common import _escape_table_cell, _gen_header, _scope_line, build_reference

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


def _team_preferences_note(skill: Skill) -> str:
    """Q13: how this lens defers to a repo's `.code-quality-atlas/preferences.md`.
    Tier is coarse (whole-lens, not per-check — see
    docs/team-preferences-overlay.md, section 9, "Open questions"): a
    floor-tier lens can only be `acknowledge`d, never silently `suppress`ed,
    so a team can't make a security/correctness/data-safety/concurrency
    finding vanish outright."""
    if skill.tier == "floor":
        allowance = (
            "a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this "
            "lens's thresholds or selection, but this is a **floor-tier** lens: it "
            "can never `suppress` a finding outright. The strongest override "
            "available is `acknowledge` — a recorded rationale that keeps the "
            "finding visible, tagged `acknowledged deviation: <reason>`, and "
            "non-blocking rather than removing it."
        )
    else:
        allowance = (
            "a repo's `.code-quality-atlas/preferences.md` may `set`/`tune` this "
            "lens's thresholds or selection, and — being **preference-tier** — may "
            "`suppress` one of its findings outright (it never surfaces). Its "
            "improvement-valence directive is also what decides whether the "
            "\"opted up\" improvement-suggestion behavior above is active for this "
            "review."
        )
    return (
        f"**Team preferences.** If the reviewed repo has "
        f"`.code-quality-atlas/preferences.md`, apply it before reporting: "
        f"{allowance} Absent the file, apply this lens's defaults exactly as "
        f"written above.\n\n"
    )


def _process_notes_footer() -> str:
    """Q17/D17 stage 1: a one-line, uniform reflection prompt on every lens,
    routing self-improvement signal through the synthesizer's Process notes
    appendix rather than 24+ lenses each inventing a feedback format. Standalone
    SKILL.md only, mirroring Team preferences / Reviewer discipline / Mechanizing
    these checks, which the collapsed lens bundles (checklist + examples only)
    likewise omit."""
    return (
        "**Process notes.** If this lens misfired on this change — flagged "
        "correct code, missed an obvious issue squarely in its own scope, or "
        "its checklist didn't fit the change shape — say so in one line under "
        "`synthesizing-review-findings`'s **Process notes** appendix; that is "
        "not a defect finding. Say nothing if the lens worked as intended — "
        "never invent a process note to fill the section.\n\n"
    )


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
            f"| {_escape_table_cell(a.name)} | {_escape_table_cell(a.detect)} | "
            f"[reference/{a.slug}.md](reference/{a.slug}.md) |"
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
        f"{_team_preferences_note(skill)}"
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
        f"{_process_notes_footer()}"
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
                _gen_header(skill) + build_artifact_rubric(skill, a, docs_root), encoding="utf-8")
    else:
        (out / "reference" / "heuristics.md").write_text(
            _gen_header(skill) + build_reference(skill, "heuristics", docs_root), encoding="utf-8")
    (out / "reference" / "tool-rules.md").write_text(
        _gen_header(skill) + build_reference(skill, "tooling", docs_root), encoding="utf-8")
    (out / "reference" / "sources.md").write_text(
        _gen_header(skill) + build_reference(skill, "references", docs_root), encoding="utf-8")
    if not (out / "examples.md").exists():
        (out / "examples.md").write_text(
            f"# Examples — {skill.name}\n\n"
            "<!-- Add concrete good/bad input→finding pairs during refinement. -->\n",
            encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(json.dumps(
            {"skills": [skill.name], "scenarios": []}, indent=2) + "\n", encoding="utf-8")
    return out
