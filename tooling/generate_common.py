# SPDX-License-Identifier: MIT
# tooling/generate_common.py
"""Helpers shared by the generate_skill / generate_router / generate_synthesizer /
generate_collapsed modules: reference-file assembly, table-cell escaping, the
diff/repo/decision/artifact scope line, depth-mode rendering, and category
ownership. Split out of tooling/generate.py so each generation concern's edits
land in the file that owns it.

The leading underscore on names here (`_KIND_TITLE`, `_escape_table_cell`,
`_TOOLING_PREAMBLE`, `_scope_line`) marks them internal to skill generation,
not part of the manifest/skill-authoring API — not "local to this file"; they
are imported across the sibling generate_*.py modules by design."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from tooling.manifest import Manifest, Skill
from tooling.sections import extract_section, extract_subsection, strip_priority

_KIND_TITLE = {
    "heuristics": "Reviewable heuristics",
    "tooling": "Tool rules to triage",
    "references": "References to mine",
}


def _escape_table_cell(value: str) -> str:
    """Escape a manifest-sourced prose field before interpolating it into a
    Markdown pipe-table cell (#141). Unescaped, a literal `|` in the field
    splits the row into an extra column — silently corrupting every column
    after it — rather than failing loudly; an embedded newline (e.g. from a
    YAML `|`-style block scalar) breaks the row structure outright. Collapse
    any run of whitespace, including newlines, to a single space, then escape
    `|` as `\\|` so it renders as a literal pipe inside the cell."""
    return " ".join(value.split()).replace("|", "\\|")


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


def _gen_header(skill: Skill | None = None, *, with_examples: bool = False) -> str:
    """A one-block 'generated — edit the source, not me' banner for generated
    reference files (both the standalone tree's reference/*.md and the collapsed
    tree's reference/lenses/<lens>/*.md, plus the collapsed tree's per-entrypoint
    reference/synthesis.md, which has no single owning skill). Most of these are
    pure generated artifacts assembled from the research docs (and, for a
    body.md, the lens's hand-refined examples.md); a contributor who edits a
    generated copy directly would diverge it from its source (the
    `tooling.cli drift` / regenerate gate catches that after the fact — this
    header prevents it up front). An HTML comment so it renders invisibly and
    is markdownlint-clean.
    `with_examples` names examples.md as a source only for the file that
    actually inlines it (collapsed body.md), not tool-rules.md / sources.md /
    heuristics.md / synthesis.md — so `skill` is only dereferenced in that case
    and may be omitted (e.g. for synthesis.md, which isn't skill-scoped) whenever
    `with_examples` is left at its default of False; passing `with_examples=True`
    without a `skill` raises, since there's no skill to name the examples.md of.
    synthesis.md is the one file this header applies to that is *not*
    docs/research/-sourced (`build_synthesizer_md`/`build_collapsed_synthesis`
    are built entirely from `skills/manifest.yaml`, per their own docstrings) —
    `skill is None` is used as that signal to cite the right source rather than
    a hardcoded docs/research/ claim that would be wrong for it.

    Not applied to SKILL.md: its YAML frontmatter must be the first bytes in
    the file for skill discovery to parse it, so an HTML comment can't be
    prepended there. SKILL.md instead carries its own machine-readable
    generated marker via the frontmatter's `provenance:` block."""
    if with_examples and skill is None:
        raise ValueError(
            "_gen_header: with_examples=True requires a skill, to name its examples.md"
        )
    if skill is None:
        source = "skills/manifest.yaml"
    else:
        examples = (
            f" and skills/{skill.name}/examples.md (worked examples)"
            if with_examples
            else ""
        )
        source = f"docs/research/{examples}"
    return (
        "<!-- GENERATED by `python -m tooling.cli generate` — do not edit this file directly.\n"
        f"     Canonical sources: {source}.\n"
        "     Direct edits are overwritten on regeneration and fail the CI drift/regenerate gate. -->\n\n"
    )


def _gen_trailer(skill: Skill | None = None, *, with_examples: bool = False) -> str:
    """Trailing counterpart to `_gen_header`, for the two file kinds whose YAML
    frontmatter must be the first bytes for skill discovery to parse it — the
    standalone tree's `SKILL.md` (`generate_skill.build_skill_md`) and the
    collapsed tree's per-entrypoint `SKILL.md` (`generate_collapsed.build_entrypoint_md`)
    — so `_gen_header`'s leading comment can't be prepended there (issue #374:
    every other generated file carries a marker; these two carried none). Same
    marker text and same `skill`/`with_examples` semantics, appended after the
    body instead of before it."""
    return "\n" + _gen_header(skill, with_examples=with_examples).rstrip("\n") + "\n"


def build_reference(skill: Skill, kind: str, docs_root: str = ".") -> str:
    """Concatenate the `kind` subsection from each source category into one
    reference file, each under a `## From category #n` header, with a ToC."""
    if kind not in _KIND_TITLE:
        raise ValueError(f"unknown kind {kind!r}; must be one of {list(_KIND_TITLE)}")
    entries = []
    for src in skill.built_from:
        text = Path(docs_root, src.path).read_text(encoding="utf-8")
        body = strip_priority(
            extract_subsection(extract_section(text, src.section), kind).strip()
        )
        if body:
            entries.append((src.section, body))
    toc = "\n".join(f"- From category #{n}" for n, _ in entries)
    parts = [f"## From category #{n}\n\n{body}" for n, body in entries]
    preamble = f"{_TOOLING_PREAMBLE}\n" if kind == "tooling" else ""
    header = f"# {_KIND_TITLE[kind]} — {skill.name}\n\n{preamble}## Contents\n\n{toc}\n"
    return header + "\n" + "\n\n".join(parts) + "\n"


def _scope_line(skill: Skill) -> str:
    if skill.shape == "repo":
        return (
            "**Shape: repo.** Run against the whole repository (scheduled or "
            "on demand), not a single diff."
        )
    if skill.shape == "decision":
        return (
            "**Shape: decision.** Reviewed at decision time — an ADR, RFC, "
            "design doc, adoption PR, or deprecation/rollout plan — not a diff "
            "of implementation code. Apply the checks to the decision and its "
            "record (rationale, assumptions, alternatives, exit/rollback), not "
            "to lines of code."
        )
    if skill.shape == "artifact":
        return (
            "**Shape: artifact.** Presence-activated: run only when one of the "
            "artifacts in the table below is present in the change or repo. "
            "Detect the artifact, open its rubric, and review the artifact "
            "against that published standard — not the surrounding application "
            "code. Skip entirely when none of the listed artifacts are present."
        )
    if skill.design:
        return (
            "**Shape: diff — design-capable.** Also works on design docs and "
            "plans: apply the same checks to the proposed states, data flows, "
            "and failure paths before any code exists. When the design doc is "
            "specifically a decision record (an ADR, RFC, or adoption/"
            "deprecation plan), also run the shared **decision-record "
            "checklist** on top of this lens's own topical checks: is the "
            "rationale actually recorded (not just the outcome); are the "
            "stated assumptions still current; is there a revisit-trigger; is "
            "an exit, rollback, or sunset path defined; were real alternatives "
            "weighed, not just the chosen option justified after the fact? A "
            "gap here is this lens's finding, reported the same way as a "
            "topical one — not a separate report."
        )
    return (
        "**Shape: diff.** Written for concrete code; not meant for design "
        "docs or plans."
    )


def modes_section(manifest: Manifest) -> str:
    """The 'Depth modes' block for the router/entrypoints: separates relevance
    (which lenses apply) from breadth (how many to run). Empty string when no
    modes declared."""
    if not manifest.modes:
        return ""
    lines = [
        "## Depth modes",
        "",
        (
            "Routing first ranks **every** lens whose scope the change touches by "
            "**relevance** — it is no longer a hard cap. A depth mode then sets the "
            "**breadth** (how far down the ranked list to run, plus room for judgment "
            "calls above that floor) and the severity floor. Pick the mode from the "
            "request; default to **review**."
        ),
        "",
        "| Mode | Breadth | Triggers |",
        "|---|---|---|",
    ]
    for mode in manifest.modes:
        triggers = ", ".join(f'"{_escape_table_cell(t)}"' for t in mode.triggers)
        lines.append(
            f"| **{mode.name}** | {_escape_table_cell(mode.breadth.strip())} | {triggers} |"
        )
    notes = [(m.name, m.note.strip()) for m in manifest.modes if m.note.strip()]
    if notes:
        lines.append("")
        lines.extend(f"- **{name}** — {note}" for name, note in notes)
    return (
        "\n".join(lines).rstrip() + "\n\n"
    )  # block ends with a blank line; "" when no modes


def primary_owners(manifest: Manifest) -> dict[int, str]:
    """category -> the skill that primarily owns it (G1 guarantees uniqueness)."""
    owners: dict[int, str] = {}
    for s in manifest.skills:
        for src in s.built_from:
            if src.category not in s.cross_ref:
                owners[src.category] = s.name
    return owners


def _strip_leading_frontmatter_and_going_deeper(full: str, source: str) -> str:
    """Strips a generated SKILL.md's leading YAML frontmatter block and its
    trailing "## Going deeper" section, for reuse as a bundled reference file
    inside a collapsed entrypoint: no frontmatter (the file is Read directly,
    not resolved as a skill), and the "Going deeper" links are relative to
    the standalone tree and would 404 from inside the bundle (#392: this
    exact 11-line strip was previously duplicated byte-for-byte between
    generate_collapsed.py and generate_prepass.py). `source` names the
    function whose output is being stripped, for the raised error message
    only — this only ever operates on this suite's own generated output, so
    a malformed shape is a bug in that builder, not a malformed input to
    handle gracefully."""
    if not full.startswith("---\n"):
        raise ValueError(f"{source} output has no leading frontmatter to strip")
    end = full.find("\n---\n", len("---\n"))  # closing fence of the first block only
    if end == -1:
        raise ValueError(f"{source} frontmatter block is not terminated")
    body = full[end + len("\n---\n") :].lstrip("\n")
    marker = "\n## Going deeper\n"
    idx = body.find(marker)
    if idx != -1:
        body = body[:idx].rstrip() + "\n"
    return body


def _generate_composition(
    manifest: Manifest,
    name: str,
    skills_root: str,
    build_md: Callable[[Manifest], str],
) -> Path:
    """Shared writer for a single-instance composition skill — the router,
    synthesizer, and prepass each generate exactly one SKILL.md this same way
    (#392: previously the same 9-line writer, copied three times). `name` is
    the manifest component's own `.name` field (e.g. `manifest.router.name`)
    — passed explicitly rather than re-derived here, since which manifest
    attribute holds it differs per caller and this helper has no way to know
    which. `evals/eval.json` is seeded once, the first time this component is
    generated, and never overwritten thereafter: an author's own scenarios,
    once written, survive every later regeneration."""
    out = Path(skills_root, name)
    (out / "evals").mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(build_md(manifest), encoding="utf-8")
    if not (out / "evals" / "eval.json").exists():
        (out / "evals" / "eval.json").write_text(
            json.dumps({"skills": [name], "scenarios": []}, indent=2) + "\n",
            encoding="utf-8",
        )
    return out


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
            '"opted up" improvement-suggestion behavior above is active for this '
            "review."
        )
    return (
        f"**Team preferences.** If the reviewed repo has "
        f"`.code-quality-atlas/preferences.md`, apply it before reporting: "
        f"{allowance} Absent the file, apply this lens's defaults exactly as "
        f"written above. Read the overlay from the **base ref** of the change "
        f"under review — the `/atlas-review-pr` command reads it at the PR's base "
        f"ref and `/atlas-code-review` reads it from the base side of the diff "
        f"(`git show <base>:.code-quality-atlas/preferences.md`), and each "
        f"hands it down — never from the reviewed branch's working tree: an edit to "
        f"`preferences.md` made *by* the change under review governs later "
        f"reviews once merged, not the review of the change that makes it, "
        f"since otherwise a change could `suppress` its own findings.\n\n"
    )


def _process_notes_footer() -> str:
    """Q17/D17 stage 1: a one-line, uniform reflection prompt on every lens,
    routing self-improvement signal through the synthesizer's Process notes
    appendix rather than 24+ lenses each inventing a feedback format. Emitted
    by both a standalone SKILL.md and a collapsed lens bundle's body.md
    (#369 — previously standalone-only, so a collapsed-only session had no
    self-improvement feedback path at all)."""
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
            parts.append(
                f"category #{c} checks are shared with **{owner}** "
                f"(their primary owner)"
            )
    if not parts:
        return ""
    return (
        "\n**Shared categories:** "
        + "; ".join(parts)
        + ". When both lenses run on the same change, report each shared "
        "finding once, under the primary owner.\n"
    )


def reviewer_discipline_intro(skill: Skill) -> str:
    """'## Reviewer discipline' plus the report-only-real-problems and
    anti-churn paragraphs, this skill's own Team preferences note, and (for
    a diff-shaped lens) the pre-existing-attribution guard — the contract
    every standalone SKILL.md carries before its checklist section, and
    every collapsed lens bundle previously omitted entirely (#369: the
    collapsed form bundled only when-to-use + checklist + examples +
    going-deeper, so a collapsed-only session got no reviewer-discipline
    contract at all).

    The attribution (Boy-Scout) guard is diff-specific — it talks about
    "this PR", "touched code", and "a repo-wide hunt is the audits' job".
    That framing has no referent on a repo-shaped audit (everything is
    pre-existing; repo-wide hunting *is* its job) or the decision shape (it
    reviews an ADR, not a diff), so it's emitted only on diff-shaped lenses
    — mirroring how `_scope_line` already differentiates by shape."""
    attribution_guard = (
        (
            "**Pre-existing defects in touched code are surfaceable, not yours to "
            "fix.** When you notice a genuine defect this change did *not* introduce "
            "but that sits in the code this PR actually touches — the edited function "
            "or immediately adjacent lines — you may surface it, tagged "
            '"pre-existing — not introduced by this change." Like improvements it is '
            "opt-in and default-quiet (off unless the team opts up), "
            "`route: implementer`, and non-blocking: it informs the author's "
            "fix-now / file-a-ticket / ignore call and never sets this PR's verdict, "
            "because the diff did not cause it. Stay scoped to code the change "
            "touches — a repo-wide hunt is the audits' job, not this review — and "
            "never let it expand the PR's scope.\n\n"
        )
        if skill.shape == "diff"
        else ""
    )
    return (
        "## Reviewer discipline\n\n"
        "Report only real problems. If this lens applies and what you reviewed "
        "holds up — the code, the design, or the repository's current state — "
        'reply "No findings" and stop. If what you were given is outside this '
        "lens's scope entirely, say so in one line instead, starting with the "
        'words "Not applicable:" followed by what\'s missing — never the '
        "healthy-scan sentence, which means a check ran and found nothing, not "
        "that nothing here applied. Either way, do not invent issues. This "
        "guards against false positives on correct code; still report every "
        "genuine issue you do find, with its full detail.\n\n"
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
    )


def mechanizing_and_process_notes(
    tool_rules_link: str = "reference/tool-rules.md",
) -> str:
    """'## Mechanizing these checks' plus the Process notes footer — the
    tail-end discipline contract every standalone SKILL.md carries after its
    checklist section, and every collapsed lens bundle previously omitted
    entirely (#369). `tool_rules_link` differs by context: a standalone
    lens's own `reference/tool-rules.md` vs. a collapsed bundle's flat
    `tool-rules.md` sitting next to `body.md`."""
    return (
        "## Mechanizing these checks\n\n"
        "Where a finding here is one a tool can catch deterministically, surface "
        "that as an advisory `route: implementer` note next to the finding: the "
        "hand review caught it this time, and wiring the matching tool from "
        f"[{tool_rules_link}]({tool_rules_link}) into CI catches it "
        "automatically from then on. This is a suggestion to mechanize, not a "
        "defect — it never "
        "blocks a verdict, and it falls away on a repo that already runs the "
        "tool.\n\n" + _process_notes_footer()
    )
