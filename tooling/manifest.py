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

    def __post_init__(self) -> None:
        if self.category != self.section:
            raise ValueError(
                f"manifest category {self.category} != source section {self.section}"
                f" for {self.source}"
            )

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
    primaries: dict[int, list[str]] = {}
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
        categories = [src.category for src in s.built_from]
        if len(categories) != len(set(categories)):
            raise ValidationError(
                f"{s.name}: built_from lists a category more than once")
        for c in s.cross_ref:
            if c not in categories:
                raise ValidationError(
                    f"{s.name}: cross_ref category {c} is not in built_from")
        for src in s.built_from:
            try:
                text = Path(docs_root, src.path).read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ValidationError(
                    f"{s.name}: cannot read source file {src.path}: {exc}") from exc
            try:
                extract_section(text, src.section)
            except KeyError:
                raise ValidationError(f"{s.name}: source not found: section #{src.section} in {src.path}")
            if src.category not in s.cross_ref:
                primaries.setdefault(src.category, []).append(s.name)
    # G1: one primary owner per category — skills sharing a category must mark
    # all but one claim as cross_ref so findings don't double-report.
    for category, owners in sorted(primaries.items()):
        if len(owners) > 1:
            raise ValidationError(
                f"category #{category} has multiple primary owners: {', '.join(owners)} "
                f"— mark all but one with cross_ref: [{category}]")


def load_manifest(path: str) -> Manifest:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    skills = []
    for i, s in enumerate(data["skills"]):
        try:
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
        except KeyError as e:
            raise ValidationError(f"skill #{i}: missing field {e}") from e
    return Manifest(taxonomy_version=data["taxonomy_version"], skills=skills)
