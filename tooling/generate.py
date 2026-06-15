# SPDX-License-Identifier: MIT
# tooling/generate.py
from __future__ import annotations
import json
import yaml
from pathlib import Path
from tooling.manifest import Manifest, Skill, Source
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
    # A one-line scannable summary (the same `picker` the router catalog uses),
    # surfaced at the top of each lens so the lens is recognizable at a glance
    # without reading the full trigger-rich description below it.
    tagline = f"*{skill.picker.strip()}*\n\n" if skill.picker else ""
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
        "## Top checks\n\n"
        "The head of the full checklist — enough for a first pass without opening "
        "any reference file:\n\n"
        f"{checks}\n"
        f"{_cross_ref_note(skill, owners)}\n"
        "## Mechanizing these checks\n\n"
        "Where a finding here is one a tool can catch deterministically, surface "
        "that as an advisory `route: implementer` note next to the finding: the "
        "hand review caught it this time, and wiring the matching tool from "
        "[reference/tool-rules.md](reference/tool-rules.md) into CI gates it going "
        "forward. This is a suggestion to mechanize, not a defect — it never "
        "blocks a verdict, and it falls away on a repo that already runs the "
        "tool.\n\n"
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
        f"{r.body or r.description}\n\n"
        "## How to pick\n\n"
        "- This skill recommends **2-4 content lenses** for a focused "
        "single-pass review. If you already know which lenses are relevant, or "
        "if comprehensive coverage is the goal, call them directly — the 2-4 "
        "figure is this router's own recommendation, not a hard cap on direct "
        "lens selection. `reviewing-pr-and-process-hygiene` is **additive** — on "
        "any PR it rides on top of the content lenses and does not spend one of "
        "the 2-4 slots.\n"
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
        + "\n## Routes\n\n"
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
        f"{catalog('decision')}\n"
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
        "without setting the engineering verdict. If every lens found nothing, the "
        "whole report is \"No findings\" — do not manufacture a harsher verdict "
        "than the findings justify.\n"
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
        "- **location** — file and line/range (the dedupe key, with root cause)\n"
        "- **severity** — one of the levels above\n"
        "- **valence** — `defect` (something is wrong) or `improvement` (a correct "
        "thing could be better). Defects are the default and drive the verdict; "
        "improvements are opt-in, `nit`-severity, and `route: implementer`.\n"
        "- **route** — who decides: `eng` (the default — engineering owns it), "
        "`implementer` (the change's author applies/defers/ignores), or "
        "`product` / `design` / `legal` / `leadership` when the decision authority "
        "sits outside engineering.\n"
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
        "configure the suite to churn.\n\n"
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
        "Tensions\n"
        "- <lens> ↔ <lens>: <how it was resolved here>\n\n"
        "Coverage & limitations\n"
        "- Lenses run: <names>. Not selected: <names, or \"none\">.\n"
        "- Not verifiable from this diff: <what needs runtime, data, or repo-wide "
        "context to confirm, or \"nothing\">.\n"
        "```\n\n"
        "Omit any **findings** section with nothing in it — including **Routed** "
        "and **Improvements** (the latter is absent entirely unless the team "
        "opted into improvement-valence suggestions). **Coverage & limitations** "
        "is the exception: it is always present, even on a \"No findings\" report. "
        "Keep each finding to one or two lines; the detail lives in the "
        "originating lens's output, not restated here.\n\n"
        "## Reviewer discipline\n\n"
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
