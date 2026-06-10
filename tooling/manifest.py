from __future__ import annotations
from dataclasses import dataclass, field
import yaml


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
