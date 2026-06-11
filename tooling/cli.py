# tooling/cli.py
from __future__ import annotations
import argparse
from pathlib import Path
from tooling.manifest import load_manifest, validate
from tooling.generate import generate_router, generate_skill, primary_owners
from tooling.drift import check_drift
from tooling.evals import load_evals, validate_evals, EvalError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skills")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--manifest", default="skills/manifest.yaml")
    g.add_argument("--docs-root", default=".")
    g.add_argument("--skills-root", default="skills")

    d = sub.add_parser("drift")
    d.add_argument("--skills-root", default="skills")
    d.add_argument("--docs-root", default=".")

    e = sub.add_parser("eval")
    e.add_argument("--skills-root", default="skills")
    e.add_argument("--skill", default=None, help="validate one skill; default: all")

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        manifest = load_manifest(args.manifest)
        validate(manifest, docs_root=args.docs_root)
        owners = primary_owners(manifest)
        for skill in manifest.skills:
            out = generate_skill(skill, manifest.taxonomy_version,
                                 docs_root=args.docs_root, skills_root=args.skills_root,
                                 owners=owners)
            print(f"generated {out}")
        if manifest.router is not None:
            out = generate_router(manifest, skills_root=args.skills_root)
            print(f"generated {out}")
        return 0

    if args.cmd == "drift":
        reports = check_drift(skills_root=args.skills_root, docs_root=args.docs_root)
        if not reports:
            print("No drift: all skills are in sync with their source research.")
            return 0
        for r in reports:
            secs = ", ".join(f"#{s.section}" for s in r.changed)
            print(f"DRIFT: {r.skill} — changed sources: {secs}")
        return 1

    if args.cmd == "eval":
        if args.skill:
            eval_files = [Path(args.skills_root, args.skill, "evals", "eval.json")]
        else:
            eval_files = sorted(Path(args.skills_root).glob("*/evals/eval.json"))
        ok = True
        for path in eval_files:
            name = path.parent.parent.name
            if not path.exists():
                print(f"MISSING: {name} — no evals/eval.json")
                ok = False
                continue
            try:
                doc = load_evals(str(path))
                validate_evals(doc)
                print(f"OK: {name} ({len(doc.scenarios)} scenarios)")
            except EvalError as exc:
                print(f"INVALID: {name} — {exc}")
                ok = False
        return 0 if ok else 1

    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
