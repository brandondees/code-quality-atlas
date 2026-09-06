# SPDX-License-Identifier: MIT
# tooling/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from tooling.drift import DriftError, check_drift
from tooling.evals import D8_MIN_SCENARIOS, EvalError, load_evals, validate_evals
from tooling.generate_collapsed import CollapsedOverlapError, generate_collapsed
from tooling.generate_common import primary_owners
from tooling.generate_doc_counts import DocCountAnchorError, sync_doc_counts
from tooling.generate_prepass import generate_prepass
from tooling.generate_router import generate_router
from tooling.generate_skill import generate_skill
from tooling.generate_synthesizer import generate_synthesizer
from tooling.manifest import ValidationError, load_manifest, validate


def _add_generate_subparser(sub: argparse._SubParsersAction) -> None:
    g = sub.add_parser("generate")
    g.add_argument(
        "--manifest",
        default="skills/manifest.yaml",
        help="the skills manifest to generate from",
    )
    g.add_argument(
        "--docs-root",
        default=".",
        help="repo root the manifest's research-section paths resolve against",
    )
    g.add_argument(
        "--skills-root",
        default="skills",
        help="directory to write generated standalone skills into",
    )
    g.add_argument(
        "--collapsed-root",
        default="collapsed",
        help="directory to write the generated collapsed entrypoints into",
    )


def _add_drift_subparser(sub: argparse._SubParsersAction) -> None:
    d = sub.add_parser("drift")
    d.add_argument(
        "--skills-root",
        default="skills",
        help="directory of generated skills to check for drift",
    )
    d.add_argument(
        "--docs-root",
        default=".",
        help="repo root each skill's source research resolves against",
    )


def _add_eval_subparser(sub: argparse._SubParsersAction) -> None:
    e = sub.add_parser("eval")
    e.add_argument(
        "--skills-root",
        default="skills",
        help="directory of skills whose evals/eval.json to validate",
    )
    e.add_argument("--skill", default=None, help="validate one skill; default: all")
    e.add_argument(
        "--manifest",
        default="skills/manifest.yaml",
        help="source of each lens's eval_min (Q21); a missing or "
        "malformed manifest fails the eval command loudly rather "
        "than silently falling back to D8's baseline, since that "
        "would silently under-enforce every lens's raised floor",
    )


def _run_generate(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(args.manifest)
        validate(manifest, docs_root=args.docs_root)
    except (OSError, ValidationError) as exc:
        print(f"ERROR: {exc}")
        return 1
    owners = primary_owners(manifest)
    for skill in manifest.skills:
        out = generate_skill(
            skill,
            manifest.taxonomy_version,
            docs_root=args.docs_root,
            skills_root=args.skills_root,
            owners=owners,
        )
        print(f"generated {out}")
    if manifest.router is not None:
        out = generate_router(manifest, skills_root=args.skills_root)
        print(f"generated {out}")
    if manifest.prepass is not None:
        out = generate_prepass(manifest, skills_root=args.skills_root)
        print(f"generated {out}")
    if manifest.synthesizer is not None:
        out = generate_synthesizer(manifest, skills_root=args.skills_root)
        print(f"generated {out}")
    if manifest.entrypoints:
        # generate_collapsed refuses when its prune target would overlap the
        # standalone skills tree; report that cleanly instead of leaking a
        # traceback, matching the drift/eval branches. Catch the specific
        # error so an unrelated internal ValueError still surfaces as a bug.
        try:
            collapsed = generate_collapsed(
                manifest,
                docs_root=args.docs_root,
                skills_root=args.skills_root,
                collapsed_root=args.collapsed_root,
            )
        except CollapsedOverlapError as exc:
            print(f"ERROR: {exc}")
            return 1
        for out in collapsed:
            print(f"generated {out}")
    # Renders the manifest's lens/diff/repo/total counts into the handful
    # of hand-authored prose files that quote them (issue #372), matching
    # the drift-checkable pattern the rest of this branch already follows.
    try:
        doc_count_updates = sync_doc_counts(manifest, docs_root=args.docs_root)
    except (OSError, DocCountAnchorError) as exc:
        print(f"ERROR: {exc}")
        return 1
    for out in doc_count_updates:
        print(f"generated {out}")
    return 0


def _run_drift(args: argparse.Namespace) -> int:
    # check_drift's own glob (*/SKILL.md) would silently return [] for a
    # nonexistent or empty --skills-root, reporting "No drift" — a rename
    # or typo would turn a required CI gate into a green no-op (#367).
    # Counted here (rather than inside check_drift) so the same number
    # can also report how many skills were actually checked.
    skill_mds = sorted(Path(args.skills_root).glob("*/SKILL.md"))
    if not skill_mds:
        print(f"ERROR: no skills found under {args.skills_root}")
        return 1
    try:
        reports = check_drift(skills_root=args.skills_root, docs_root=args.docs_root)
    except DriftError as exc:
        print(f"ERROR: {exc}")
        return 1
    if not reports:
        if len(skill_mds) == 1:
            print("No drift: 1 skill is in sync with its source research.")
        else:
            print(
                f"No drift: all {len(skill_mds)} skills are in sync with "
                "their source research."
            )
        return 0
    for r in reports:
        secs = ", ".join(f"#{s.section}" for s in r.changed)
        print(f"DRIFT: {r.skill} — changed sources: {secs}")
    return 1


def _eval_skill_dirs(args: argparse.Namespace) -> list[Path] | None:
    """Resolve which skill directories `eval` should check, or None on error
    (the caller has already printed the matching ERROR line)."""
    if args.skill:
        return [Path(args.skills_root, args.skill)]
    # Enumerated by *directory*, not by globbing existing eval.json files:
    # globbing only files that already exist makes the MISSING branch in
    # _run_eval unreachable (a skill with no evals/ never produces a glob hit
    # to iterate), and silently drops a nonexistent/empty --skills-root to
    # zero iterations instead of failing (#367). Gated on a SKILL.md
    # existing, matching `drift`'s own definition of "a skill" — a stray
    # non-skill directory under --skills-root (a leftover cache dir, a
    # dot-prefixed tool dir) would otherwise be misreported as MISSING
    # instead of ignored.
    root = Path(args.skills_root)
    skill_dirs = (
        sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
        if root.is_dir()
        else []
    )
    if not skill_dirs:
        print(f"ERROR: no skills found under {args.skills_root}")
        return None
    return skill_dirs


def _eval_min_by_skill(args: argparse.Namespace) -> dict[str, int] | None:
    """Resolve each lens's eval-scenario floor (Q21) by skill name, or None
    on error (the caller has already printed the matching ERROR line)."""
    # A lens can opt into a raised eval-scenario floor via the manifest's
    # `eval_min`. This lookup is by skill *name*, so it's a harmless no-op
    # against collapsed/entrypoint runs (different names, never present in
    # manifest.skills). A manifest that can't be loaded at all is NOT
    # treated as harmless, though: silently falling back to D8's baseline of
    # 3 would silently un-enforce every hardened lens's raised floor and
    # still print "OK" — a CI gate must refuse to report success when it
    # isn't sure what floor it just checked against (found by the atlas's
    # own review of PR #159).
    try:
        return {
            s.name: s.eval_min
            for s in load_manifest(args.manifest).skills
            if s.eval_min is not None
        }
    except (OSError, ValidationError) as exc:
        print(
            f"ERROR: could not load {args.manifest} to resolve each lens's "
            f"eval-scenario floor (Q21): {exc}"
        )
        return None


def _run_eval(args: argparse.Namespace) -> int:
    skill_dirs = _eval_skill_dirs(args)
    if skill_dirs is None:
        return 1
    eval_min_by_skill = _eval_min_by_skill(args)
    if eval_min_by_skill is None:
        return 1
    ok = True
    for skill_dir in skill_dirs:
        name = skill_dir.name
        path = skill_dir / "evals" / "eval.json"
        if not path.exists():
            print(f"MISSING: {name} — no evals/eval.json")
            ok = False
            continue
        try:
            doc = load_evals(str(path))
            validate_evals(
                doc, min_scenarios=eval_min_by_skill.get(name, D8_MIN_SCENARIOS)
            )
            print(f"OK: {name} ({len(doc.scenarios)} scenarios)")
        except EvalError as exc:
            print(f"INVALID: {name} — {exc}")
            ok = False
    return 0 if ok else 1


_SUBCOMMANDS = {
    "generate": _run_generate,
    "drift": _run_drift,
    "eval": _run_eval,
}


def main(argv: list[str] | None = None) -> int:
    # prog matches the actual invocation (`python -m tooling.cli ...`, per
    # docs/runbooks/regenerating-skills.md) — "skills" is not a real command.
    parser = argparse.ArgumentParser(prog="python -m tooling.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_generate_subparser(sub)
    _add_drift_subparser(sub)
    _add_eval_subparser(sub)

    args = parser.parse_args(argv)
    return _SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
