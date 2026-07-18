# SPDX-License-Identifier: MIT
# tooling/generate_synthesizer.py
"""Renders the synthesizer skill: the back half of composition, merging the
findings of the lenses the router picked into one deduplicated, ranked report
with a single verdict."""
from __future__ import annotations
import json
import yaml
from pathlib import Path
from tooling.manifest import Manifest
from tooling.generate_common import _escape_table_cell


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
        floor = _escape_table_cell(mode.floor)
        if mode.floor == "escalating":
            effect = "round-based escalation (as today) — later re-review rounds raise the floor"
        else:
            effect = f"pinned at {floor} — report everything down to {floor}, nothing below"
        lines.append(f"| **{mode.name}** | {floor} | {effect} |")
    return "\n".join(lines).rstrip() + "\n\n"   # block ends with a blank line; "" when no modes


def build_synthesizer_md(manifest: Manifest) -> str:
    """The back half of composition: merges the findings of the lenses the
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
        f"| `{t.between[0]}` ↔ `{t.between[1]}` | {_escape_table_cell(t.about)} | "
        f"{_escape_table_cell(t.resolve)} |"
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
        "*without* setting this PR's verdict — the diff did not introduce it. "
        "Same for a floor-tier finding the repo's `.code-quality-atlas/"
        "preferences.md` has `acknowledge`d (Q13): it still appears in the "
        "report, tagged `acknowledged deviation: <reason>`, but the "
        "acknowledgement alone does not drive the verdict to block — the team "
        "recorded and accepted it. A `suppress`ed preference-tier finding never "
        "reaches this report at all; only `acknowledge` (floor-tier) leaves a "
        "visible trace. If every lens found nothing, the whole report is \"No "
        "findings\" — do not "
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
        "including on a \"No findings\" report.\n"
        "7. **Note the process** — close with 0-3 one-line observations on the "
        "*review process itself*, never on the reviewed code: a lens that "
        "should have run per the router's own criteria but didn't, a finding two "
        "lenses disagreed on with no entry in the tensions table above, or "
        "output that broke the finding contract. This is the suite's own "
        "self-improvement signal — every lens carries a one-line prompt to "
        "report a misfire here instead of inventing its own feedback format. "
        "When the process worked, write exactly \"Process: clean\" and stop — "
        "the same anti-invention discipline the lenses apply to findings, "
        "never a note manufactured to fill the section.\n\n"
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
        "context to confirm, or \"nothing\">.\n\n"
        "Process notes\n"
        "- <one-line process observation>, or exactly \"Process: clean\" if none.\n"
        "```\n\n"
        "Omit any **findings** section with nothing in it — including **Routed**, "
        "**Improvements**, and **Pre-existing** (the last two are absent entirely "
        "unless the team opted into improvement-valence / Boy-Scout surfacing). "
        "**Coverage & limitations** and **Process notes** are the exceptions: both "
        "are always present, even on a \"No findings\" report. "
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
        "- [self-improvement loop](../../docs/self-improvement-loop.md) — why "
        "Process notes exist, the opt-in feedback tiers a repo can turn on to "
        "keep them (`.code-quality-atlas/preferences.md`), and where the signal "
        "goes from there.\n"
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
