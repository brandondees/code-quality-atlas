# SPDX-License-Identifier: MIT
# tooling/generate_prepass.py
"""Renders the deterministic-tool evidence pre-pass: the step between the
router's lens selection and the lenses themselves, which runs the linters,
type checkers, scanners, and data/infra tools the reviewed repository has
already configured and turns their output into evidence each lens confirms,
contextualizes, or dismisses (map-gaps G34 Tier 1, enacting G5)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tooling.generate_common import _escape_table_cell
from tooling.manifest import Manifest, Prepass


def build_prepass_md(manifest: Manifest) -> str:
    """The pre-pass skill. Like the router and synthesizer it is built entirely
    from the manifest (provenance carries no research sections), so regeneration
    is triggered by manifest edits, not docs drift."""
    p = manifest.prepass
    front = {
        "name": p.name,
        "description": p.description,
        "provenance": {"taxonomy_version": manifest.taxonomy_version, "built_from": []},
    }
    fm = yaml.safe_dump(
        front, sort_keys=False, default_flow_style=False, allow_unicode=True
    ).strip()
    router_name = manifest.router.name if manifest.router else "choosing-review-lenses"
    synth_name = (
        manifest.synthesizer.name
        if manifest.synthesizer
        else "synthesizing-review-findings"
    )
    body = (
        f"# {p.name}\n\n"
        "## When to use\n\n"
        f"{p.body or p.description}\n\n"
        f"**Shape: composition.** Runs after `{router_name}` has picked the "
        "lenses and before those lenses judge the change. It adds no checks of "
        "its own — it gathers evidence, and every finding it contributes is "
        "owned and stated by a lens.\n\n"
        + _why_section()
        + _discover_section(p)
        + _run_section()
        + _families_section(p)
        + _dispositions_section(p)
        + _rules_section(p)
        + _handoff_section(synth_name)
        + "## Going deeper\n\n"
        f"- [{router_name}](../{router_name}/SKILL.md) — picks the lenses this "
        "pre-pass gathers evidence for.\n"
        f"- [{synth_name}](../{synth_name}/SKILL.md) — merges the lenses' "
        "findings, including the ones this pre-pass evidenced, into one verdict.\n"
        "- Each lens's own `reference/tool-rules.md` — the specific rule ids in "
        "that lens's domain, for wiring a tool up in a repo that has none.\n"
    )
    return f"---\n{fm}\n---\n\n{body}"


def _why_section() -> str:
    """The G5 rationale, plus its inverse — why tool output never becomes a
    verdict on its own. Static: no manifest input."""
    return (
        "## Why this runs first\n\n"
        "Where a mature linter or scanner already covers a category, the lens's "
        "job is to **triage its output, not to re-derive the finding by "
        "judgment alone**. A rule id is reproducible, cheap, and checkable by "
        "the author; a judgment call is none of those. Running the repo's own "
        "tools first means the review spends its judgment where judgment is the "
        "only thing that works — whether the invariant is right, whether the "
        "boundary belongs, whether the change should exist at all — instead of "
        "re-deriving by inference what the repo's own linter already prints.\n\n"
        "The inverse matters just as much: **tool output is an input, never a "
        "verdict.** A hit that no lens confirms is not a finding, and a clean "
        "run is not an approval.\n\n"
    )


def _discover_section(p: Prepass) -> str:
    """Step 1 — the ordered inventory table, enforced before installed before
    documented, from the manifest's `discover:` list."""
    rows = "\n".join(
        f"| {_escape_table_cell(d.source)} | {_escape_table_cell(d.tells)} |"
        for d in p.discover
    )
    return (
        "## 1. Discover what the repo already runs\n\n"
        "Read, in this order — the earlier sources say what is **enforced**, "
        "the later ones what is merely installed or documented:\n\n"
        "| Look at | What it tells you |\n"
        "|---|---|\n"
        f"{rows}\n\n"
        "Write down the resulting inventory before running anything: tool, the "
        "command that invokes it, its config file, and whether CI gates on it. "
        "If the repo configures **nothing**, say so and go straight to the "
        "lenses — an empty inventory is a valid, reportable result.\n\n"
    )


def _run_section() -> str:
    """Step 2 — how to actually invoke the discovered tools: tool-native scope,
    the repo's own config, and what to capture. Static: no manifest input."""
    return (
        "## 2. Run them, scoped and under their own config\n\n"
        "- **Scope to what is under review — through each tool's own idea of "
        "scope.** Linters and type checkers usually take a file list, and on a "
        "diff review that is what to pass. Plenty of tools have no meaningful "
        "per-file mode: a dependency auditor reads the lockfile, a coverage "
        "threshold is computed over the project, an IaC validator works per "
        "directory or stack, a data tool works over its DAG. For those, use the "
        "tool's own documented diff mode if it has one, otherwise its normal "
        "project scope — then **filter the output** to what the change touches "
        'rather than pretending the run was scoped. Record which it was: "ran '
        'over the tree, filtered to the diff" is a different fact from "ran '
        'over the 6 changed files," and only one of them says anything about '
        "the rest of the repo.\n"
        "- **Use the repo's config, never your own defaults.** Output about a "
        "rule set the team never chose is noise, and reporting it as findings "
        "is how a review loses its credibility on the first PR.\n"
        "- **Prefer the documented entry point** (`make lint`, `npm run check`, "
        "`pre-commit run --files ...`) — it is what a human would have run and "
        "it already carries the repo's arguments — **but only while it "
        "preserves the scope you need.** A `make lint` that always sweeps the "
        "whole tree costs more than the review's budget and surfaces findings "
        "the diff did not cause; when that happens, invoke the adopted tool "
        "directly, still under the repo's config, with the changed files.\n"
        "- **Capture the raw output**, including exit codes and any tool that "
        "failed to start. What did not run is as important to the report as "
        "what did.\n\n"
    )


def _families_section(p: Prepass) -> str:
    """Step 3 — the tool-family → owning-lens routing table from the manifest's
    `families:` list, whose `grounds` names validation has already checked."""
    rows = "\n".join(
        f"| {_escape_table_cell(f.kind)} | {_escape_table_cell(f.tools)} | "
        + ", ".join(f"`{lens}`" for lens in f.grounds)
        + " |"
        for f in p.families
    )
    return (
        "## 3. Route each hit to the lens that owns it\n\n"
        "Tool families and the lenses whose findings their output can evidence. "
        "The named tools are recognition aids for the inventory in step 1, not "
        "a list to install:\n\n"
        "| Family | Tools you may find configured | Grounds |\n"
        "|---|---|---|\n"
        f"{rows}\n\n"
        "A hit in a family no selected lens owns is still worth passing along "
        "to the lens nearest it — but it never becomes a finding on its own "
        "authority.\n\n"
    )


def _dispositions_section(p: Prepass) -> str:
    """Step 4 — the exhaustive per-hit disposition table from the manifest's
    `dispositions:` list; the prose names them inline so the set reads as closed."""
    rows = "\n".join(
        f"| **{_escape_table_cell(d.name)}** | {_escape_table_cell(d.when)} | "
        f"{_escape_table_cell(d.do)} |"
        for d in p.dispositions
    )
    names = ", ".join(f"**{d.name}**" for d in p.dispositions)
    return (
        "## 4. Confirm, contextualize, or dismiss — every hit, exactly once\n\n"
        f"Each hit gets exactly one of {names}. Passing a hit through "
        "unexamined is not a fourth option: an unreviewed tool dump is what the "
        "author already had before the review started.\n\n"
        "| Disposition | When | What to do |\n"
        "|---|---|---|\n"
        f"{rows}\n\n"
    )


def _rules_section(p: Prepass) -> str:
    # Not a table, so no cell escaping — but a `|`-free rule can still carry a
    # folded newline; collapse whitespace so each rule stays one bullet.
    items = "\n".join(f"- **{r.name}.** {' '.join(r.rule.split())}" for r in p.rules)
    return f"## Discipline\n\n{items}\n\n"


def _handoff_section(synth_name: str) -> str:
    """What leaves this pass: the per-lens evidence bundle and the three-fact
    coverage line the synthesizer's Coverage & limitations section reserves."""
    return (
        "## What to hand on\n\n"
        "Two things go forward from this pass:\n\n"
        "1. **An evidence bundle per lens** — the hits routed to it, each with "
        "the tool, the rule id, and the location, so the lens can confirm, "
        "contextualize, or dismiss them alongside its own reading of the code.\n"
        "2. **A coverage line** for the merged report's *Coverage & limitations* "
        f"section, which `{synth_name}` already reserves. Three facts, one line "
        "each when non-empty:\n\n"
        "```text\n"
        "Tools run: <tool (rule set), ...> over <scope>.\n"
        "Not run: <tool> — <missing toolchain | timed out | untrusted branch | "
        "not configured>.\n"
        "No deterministic coverage: <lens or category names> — judgment only.\n"
        "```\n\n"
        "That last line is the one a reader cannot reconstruct for themselves, "
        "and the one a confident-looking review most often omits. A category "
        "with no tool behind it is not a category that passed.\n\n"
    )


def build_collapsed_prepass(manifest: Manifest) -> str:
    """The pre-pass as a bundled reference file for a collapsed entrypoint (no
    frontmatter, no `Going deeper`). Mirrors build_collapsed_synthesis: the
    section's relative links (`../<router>/SKILL.md`) point outside the bundle
    and would 404, and the file is Read directly rather than navigated from."""
    full = build_prepass_md(manifest)
    if not full.startswith("---\n"):
        raise ValueError("build_prepass_md output has no leading frontmatter to strip")
    end = full.find("\n---\n", len("---\n"))  # closing fence of the first block only
    if end == -1:
        raise ValueError("build_prepass_md frontmatter block is not terminated")
    body = full[end + len("\n---\n") :].lstrip("\n")
    marker = "\n## Going deeper\n"
    idx = body.find(marker)
    if idx != -1:
        body = body[:idx].rstrip() + "\n"
    return body


def generate_prepass(manifest: Manifest, skills_root: str = "skills") -> Path:
    out = Path(skills_root, manifest.prepass.name)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(build_prepass_md(manifest), encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(
            json.dumps({"skills": [manifest.prepass.name], "scenarios": []}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    return out
