# tooling/drift.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from tooling.manifest import Source
from tooling.sections import section_hash


@dataclass
class DriftReport:
    skill: str
    changed: list[Source]


def _read_provenance(skill_md: Path) -> tuple[str, list[dict]]:
    text = skill_md.read_text(encoding="utf-8")
    # Frontmatter is the block between the first two `---` fences. Limit the
    # split to 2 so a `---` in the body can't shift the parse, and validate the
    # shape so a malformed/missing header gives a clear error, not IndexError.
    parts = text.split("---\n", 2)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError(f"{skill_md}: missing or malformed YAML frontmatter")
    front = yaml.safe_load(parts[1])
    prov = front["provenance"]
    return front["name"], prov["built_from"]


def check_drift(skills_root: str = "skills", docs_root: str = ".") -> list[DriftReport]:
    reports: list[DriftReport] = []
    for skill_md in sorted(Path(skills_root).glob("*/SKILL.md")):
        name, built_from = _read_provenance(skill_md)
        changed: list[Source] = []
        for b in built_from:
            src = Source(category=b["category"], source=b["source"])
            current = section_hash(Path(docs_root, src.path).read_text(encoding="utf-8"),
                                   src.section)
            if current != b["hash"]:
                changed.append(src)
        if changed:
            reports.append(DriftReport(skill=name, changed=changed))
    return reports
