# SPDX-License-Identifier: MIT
# tooling/generate_router.py
"""Renders the router skill: the composition layer that routes a 'what am I
reviewing' situation to the recommended range of lenses, plus a one-line
catalog of every lens."""
from __future__ import annotations
import json
import yaml
from pathlib import Path
from tooling.manifest import Manifest
from tooling.generate_common import _escape_table_cell, modes_section


def build_router_md(manifest: Manifest) -> str:
    """The composition layer: routes a 'what am I reviewing' situation to the
    recommended range of lenses worth running, plus a one-line catalog of every
    lens. Built entirely from the manifest — provenance carries no research
    sections, so regeneration is triggered by manifest edits, not docs drift."""
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
            run += f" — {_escape_table_cell(route.note)}"
        rows.append(f"| {_escape_table_cell(route.when)} | {run} |")
    routes_table = "\n".join(rows)

    # Repo-shaped lenses that also auto-include at diff scope (see the How to
    # pick auto-include callout) get a one-clause caveat here so the Catalog
    # doesn't read as though they never run against a single change.
    _diff_scoped_exception = {
        "auditing-documentation-health": (
            "also auto-included, diff-scoped, on a docs-only change — see "
            "How to pick"),
    }

    def catalog(shape: str) -> str:
        lines = []
        for s in manifest.skills:
            if s.shape != shape:
                continue
            mark = " ◆" if s.design else ""
            exception = _diff_scoped_exception.get(s.name)
            suffix = f" ({exception})" if exception else ""
            lines.append(f"- `{s.name}`{mark} — {s.picker}{suffix}")
        return "\n".join(lines)

    body = (
        f"# {r.name}\n\n"
        "## When to use\n\n"
        f"{r.body or r.description}\n\n"
        "## How to pick\n\n"
        "- **Load team preferences first.** If the reviewed repo has "
        "`.code-quality-atlas/preferences.md`, read it before ranking: apply any "
        "lens-selection/weighting directives to which lenses run and how they're "
        "prioritized within the active depth mode's breadth (a preference "
        "re-ranks or mutes within that breadth; it does not widen or override "
        "the depth mode itself), then pass the remaining directives (thresholds, "
        "house conventions, scoped exemptions, standing "
        "acknowledgements, improvement-valence verbosity) down to each selected "
        "lens — each lens applies what's relevant to its own checks, honoring its "
        "tier (floor lenses accept `acknowledge`, never a silent `suppress`; see "
        "each lens's own Team preferences note). Absent the file, route exactly "
        "as below — today's defaults, unchanged.\n"
        "- **The 3-8 figure is a starting recommendation for focused "
        "single-change review, not a strict limit.** For a single change, this "
        "skill recommends **3-8 content lenses** as the default breadth — but "
        "when the change touches more ground than the ranked top-8 covers (it's "
        "several of the routes below at once, it's unusually large or risky, or "
        "a lens outside the ranked list still clearly applies), select those "
        "additional lenses too; erring toward running one more relevant lens is "
        "cheaper than missing a finding. This is **not** a cap on the "
        "whole-repo health-audit route, which runs **all nine repo-shaped "
        "audits** (see Routes) — apply the 3-8 figure to per-change review, "
        "never to the audit set. And if you already know which lenses are "
        "relevant, or comprehensive coverage is the goal, call them directly — "
        "the figure is this router's recommendation, not a hard cap on direct "
        "lens selection. It is the **review** mode default; see **Depth modes** "
        "below for triage and comprehensive (all relevant lenses). "
        "`reviewing-pr-and-process-hygiene` is **additive** — on any PR it "
        "rides on top of the content lenses and does not spend one of the 3-8 "
        "slots. Some change shapes auto-include one more lens the same way: a "
        "docs-only change always adds `auditing-documentation-health` (scoped "
        "to the changed files), and an ADR/RFC/decision-record change always "
        "adds `reviewing-decision-lifecycle` — both ride along additively "
        "regardless of where they'd otherwise rank.\n"
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
