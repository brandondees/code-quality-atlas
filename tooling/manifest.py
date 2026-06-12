# SPDX-License-Identifier: MIT
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
        # Validate the "<path>#<n>" shape up front so a malformed source raises a
        # clear error here rather than a bare IndexError/ValueError later in .section.
        if "#" not in self.source:
            raise ValueError(
                f"source must be '<path>#<section>', got {self.source!r}")
        fragment = self.source.rsplit("#", 1)[1]
        if not fragment.isdigit():
            raise ValueError(
                f"source section must be a non-negative integer, got {self.source!r}")
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
    design: bool = False     # diff lens that also applies to design docs/plans
    picker: str = ""         # one-line differentiator for the router catalog


@dataclass
class Route:
    when: str                # the change shape, e.g. "Schema migration or backfill"
    run: list[str]           # skill names to run for it
    note: str = ""


@dataclass
class Router:
    name: str
    description: str
    routes: list[Route]
    body: str = ""           # richer "When to use" text; falls back to description


@dataclass
class Tension:
    between: list[str]       # the two lenses that pull opposite ways
    about: str               # what they disagree on, one line
    resolve: str             # the default the synthesizer applies


@dataclass
class Synthesizer:
    name: str
    description: str
    severity_order: list[str]  # most → least severe, the ranking scale
    tensions: list[Tension]


@dataclass
class Manifest:
    taxonomy_version: str
    skills: list[Skill]
    router: Router | None = None
    synthesizer: Synthesizer | None = None


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
        if s.shape not in ("diff", "repo", "decision"):
            raise ValidationError(f"{s.name}: shape must be diff|repo|decision, got {s.shape!r}")
        if s.design and s.shape != "diff":
            raise ValidationError(
                f"{s.name}: design applies only to diff-shaped lenses")
        if len(s.picker) > 160:
            raise ValidationError(f"{s.name}: picker must be <=160 chars")
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
    if manifest.router is not None:
        r = manifest.router
        if not _NAME_RE.match(r.name) or len(r.name) > 64 or r.name in seen:
            raise ValidationError(f"router: invalid or duplicate name {r.name!r}")
        if not r.description or len(r.description) > 1024:
            raise ValidationError("router: description must be non-empty and <=1024 chars")
        if len(r.body) > 1024:
            raise ValidationError("router: body must be <=1024 chars")
        if not r.routes:
            raise ValidationError("router: routes must be non-empty")
        for route in r.routes:
            if not route.when or not route.run:
                raise ValidationError("router: every route needs `when` and `run`")
            for lens in route.run:
                if lens not in seen:
                    raise ValidationError(
                        f"router: route {route.when!r} runs unknown skill {lens!r}")
        # The catalog lists every lens by its picker line; a missing picker
        # would silently leave that lens undiscoverable to the router.
        for s in manifest.skills:
            if not s.picker:
                raise ValidationError(
                    f"{s.name}: picker is required when a router is defined")
    if manifest.synthesizer is not None:
        sy = manifest.synthesizer
        if not _NAME_RE.match(sy.name) or len(sy.name) > 64 or sy.name in seen:
            raise ValidationError(f"synthesizer: invalid or duplicate name {sy.name!r}")
        if not sy.description or len(sy.description) > 1024:
            raise ValidationError("synthesizer: description must be non-empty and <=1024 chars")
        if len(sy.severity_order) < 2:
            raise ValidationError("synthesizer: severity_order needs at least two levels")
        if len(sy.severity_order) != len(set(sy.severity_order)):
            raise ValidationError("synthesizer: severity_order has duplicate levels")
        # A tension is only meaningful between two known, distinct lenses;
        # an unknown name would print a dangling reference in the merged report.
        for t in sy.tensions:
            if len(t.between) != 2 or t.between[0] == t.between[1]:
                raise ValidationError(
                    f"synthesizer: tension `between` must name two distinct lenses, got {t.between}")
            for lens in t.between:
                if lens not in seen:
                    raise ValidationError(
                        f"synthesizer: tension references unknown skill {lens!r}")
            if not t.about or not t.resolve:
                raise ValidationError(
                    f"synthesizer: tension {t.between} needs `about` and `resolve`")


def load_manifest(path: str) -> Manifest:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    # Guard the parsed structure before indexing into it, so a malformed or
    # partially-written manifest yields a ValidationError naming the file and the
    # offending key rather than a raw TypeError/KeyError into manifest.py internals.
    if not isinstance(data, dict):
        raise ValidationError(
            f"{path}: expected a YAML mapping, got {type(data).__name__}")
    for key in ("skills", "taxonomy_version"):
        if key not in data:
            raise ValidationError(f"{path}: missing required key {key!r}")
    if not isinstance(data["skills"], list):
        raise ValidationError(
            f"{path}: 'skills' must be a list, got {type(data['skills']).__name__}")
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
                design=s.get("design", False),
                picker=s.get("picker", "").strip(),
            ))
        except KeyError as e:
            raise ValidationError(f"skill #{i}: missing field {e}") from e
        except ValueError as e:  # malformed Source string
            raise ValidationError(f"skill #{i}: {e}") from e
    router = None
    if "router" in data:
        r = data["router"]
        try:
            router = Router(
                name=r["name"],
                description=r["description"].strip(),
                routes=[Route(when=x["when"], run=x["run"], note=x.get("note", ""))
                        for x in r["routes"]],
                body=r.get("body", "").strip(),
            )
        except KeyError as e:
            raise ValidationError(f"router: missing field {e}") from e
    synthesizer = None
    if "synthesizer" in data:
        sy = data["synthesizer"]
        try:
            synthesizer = Synthesizer(
                name=sy["name"],
                description=sy["description"].strip(),
                severity_order=sy["severity_order"],
                tensions=[Tension(between=t["between"],
                                  about=t["about"].strip(),
                                  resolve=t["resolve"].strip())
                          for t in sy.get("tensions", [])],
            )
        except KeyError as e:
            raise ValidationError(f"synthesizer: missing field {e}") from e
    return Manifest(taxonomy_version=data["taxonomy_version"], skills=skills,
                    router=router, synthesizer=synthesizer)
