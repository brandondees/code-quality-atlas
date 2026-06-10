from __future__ import annotations
from dataclasses import dataclass, field
import re
from pathlib import Path
import yaml
from tooling.sections import extract_section


@dataclass
class Source:
    category: int
    source: str  # "<path>#<n>"

    @property
    def path(self) -> str:
        return self.source.rsplit("#", 1)[0]

    @property
    def section(self) -> int:
        return int(self.source.rsplit("#", 1)[1])


@dataclass
class Skill:
    name: str
    description: str
    shape: str
    wave: int
    built_from: list[Source]
    primary_owner: int | None = None
    cross_ref: list[int] = field(default_factory=list)


@dataclass
class Manifest:
    taxonomy_version: str
    skills: list[Skill]


_NAME_RE = re.compile(r"^[a-z0-9-]+$")
_RESERVED = ("anthropic", "claude")


class ValidationError(Exception):
    pass


def validate(manifest: Manifest, docs_root: str = ".") -> None:
    seen = set()
    for s in manifest.skills:
        if not _NAME_RE.match(s.name) or len(s.name) > 64:
            raise ValidationError(f"invalid name: {s.name!r} (lowercase/hyphen, <=64)")
        if any(w in s.name for w in _RESERVED):
            raise ValidationError(f"name uses reserved word: {s.name!r}")
        if s.name in seen:
            raise ValidationError(f"duplicate skill name: {s.name!r}")
        seen.add(s.name)
        if not s.description or len(s.description) > 1024:
            raise ValidationError(f"{s.name}: description must be non-empty and <=1024 chars")
        if s.shape not in ("diff", "repo"):
            raise ValidationError(f"{s.name}: shape must be diff|repo, got {s.shape!r}")
        if not s.built_from:
            raise ValidationError(f"{s.name}: built_from must be non-empty")
        for src in s.built_from:
            text = Path(docs_root, src.path).read_text(encoding="utf-8")
            try:
                extract_section(text, src.section)
            except KeyError:
                raise ValidationError(f"{s.name}: source not found: section #{src.section} in {src.path}")


def load_manifest(path: str) -> Manifest:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    skills = []
    for s in data["skills"]:
        built = [Source(category=b["category"], source=b["source"]) for b in s["built_from"]]
        skills.append(Skill(
            name=s["name"],
            description=s["description"].strip(),
            shape=s["shape"],
            wave=s["wave"],
            built_from=built,
            primary_owner=s.get("primary_owner"),
            cross_ref=s.get("cross_ref", []),
        ))
    return Manifest(taxonomy_version=data["taxonomy_version"], skills=skills)
