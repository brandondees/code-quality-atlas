# SPDX-License-Identifier: MIT
# tooling/drift.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from tooling.manifest import Source
from tooling.sections import section_hash


class DriftError(Exception):
    """Raised when drift cannot be computed — e.g. a referenced source research
    file is missing or unreadable. Distinct from a *detected* drift (which is a
    normal DriftReport result)."""


@dataclass
class DriftReport:
    skill: str
    changed: list[Source]


def _read_provenance(skill_md: Path) -> tuple[str, list[dict]]:
    # `utf-8-sig` drops a BOM and `\r\n` -> `\n` normalizes a Windows checkout,
    # so the `---\n` fence split works regardless of line endings/encoding mark.
    text = skill_md.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    # Frontmatter is the block between the first two `---` fences. Limit the
    # split to 2 so a `---` in the body can't shift the parse, and validate the
    # shape so a malformed header/body gives a clear ValueError, not Index/Type/KeyError.
    parts = text.split("---\n", 2)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError(f"{skill_md}: missing or malformed YAML frontmatter")
    front = yaml.safe_load(parts[1])
    if (not isinstance(front, dict) or "name" not in front
            or not isinstance(front.get("provenance"), dict)
            or "built_from" not in front["provenance"]):
        raise ValueError(
            f"{skill_md}: frontmatter must define `name` and `provenance.built_from`")
    return front["name"], front["provenance"]["built_from"]


def check_drift(skills_root: str = "skills", docs_root: str = ".") -> list[DriftReport]:
    reports: list[DriftReport] = []
    for skill_md in sorted(Path(skills_root).glob("*/SKILL.md")):
        name, built_from = _read_provenance(skill_md)
        changed: list[Source] = []
        for b in built_from:
            src = Source(category=b["category"], source=b["source"])
            # A renamed/missing source file (OSError) or one that isn't valid
            # UTF-8 (UnicodeDecodeError, a ValueError subclass — not an OSError)
            # would otherwise escape with no skill/path context; surface both as
            # a DriftError the CLI can report cleanly.
            try:
                source_text = Path(docs_root, src.path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise DriftError(
                    f"{name}: cannot read source {src.path!r}: {exc}") from exc
            current = section_hash(source_text, src.section)
            if current != b["hash"]:
                changed.append(src)
        if changed:
            reports.append(DriftReport(skill=name, changed=changed))
    return reports
