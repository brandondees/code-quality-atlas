# tooling/cli.py
from __future__ import annotations
import argparse
from tooling.manifest import load_manifest, validate
from tooling.generate import generate_skill
from tooling.drift import check_drift


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

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        manifest = load_manifest(args.manifest)
        validate(manifest, docs_root=args.docs_root)
        for skill in manifest.skills:
            out = generate_skill(skill, manifest.taxonomy_version,
                                 docs_root=args.docs_root, skills_root=args.skills_root)
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

    return 2
