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
class Artifact:
    """One row of an artifact-shaped lens's detect→rubric table (D15). `rubric`
    is the research section the artifact is reviewed against and must also appear
    in the lens's `built_from` (so the existing drift checker tracks it); `slug`
    names the bundled rubric file `reference/<slug>.md`."""
    name: str        # human label, e.g. "SKILL.md / agent skill"
    detect: str      # the presence signal, e.g. "a SKILL.md file is added or changed"
    rubric: int      # the rubric research section (also in built_from)
    slug: str        # filename stem for the bundled rubric, e.g. "skill-md"


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
    artifacts: list[Artifact] = field(default_factory=list)  # shape: artifact only
    # Q13 team-preferences overlay: whole-lens tier (coarse; per-check granularity
    # is a later refinement, see docs/team-preferences-overlay.md, section 9,
    # "Open questions"). "floor" lenses assert broken/unsafe and can only be
    # `acknowledge`d, never silently `suppress`ed, by a repo's
    # .code-quality-atlas/preferences.md.
    tier: str = "preference"


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
class Mode:
    """A review-depth mode: how *much* to run and at what severity floor.

    `breadth` is a human-readable selector label rendered into the router.
    `floor` is a severity level from the synthesizer's `severity_order`
    (pin the floor at that level) or the literal "escalating" (the
    round-based default). `triggers` are natural-language phrases that
    select this mode in the entrypoint/router body (D7-portable).
    """
    name: str
    breadth: str
    floor: str
    triggers: list[str]
    note: str = ""


@dataclass
class Entrypoint:
    """A collapsed-form entrypoint skill that bundles a review shape's lenses.

    Membership = skills whose `shape` is in `shapes`, plus (when `include_design`)
    the design-capable lenses regardless of shape (so the decision entrypoint can
    carry the ◆ diff lenses). `body` is optional richer when-to-use text."""
    name: str
    description: str
    shapes: list[str]
    include_design: bool = False
    body: str = ""


@dataclass
class Manifest:
    taxonomy_version: str
    skills: list[Skill]
    router: Router | None = None
    synthesizer: Synthesizer | None = None
    modes: list[Mode] = field(default_factory=list)
    entrypoints: list[Entrypoint] = field(default_factory=list)


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
        if s.shape not in ("diff", "repo", "decision", "artifact"):
            raise ValidationError(
                f"{s.name}: shape must be diff|repo|decision|artifact, got {s.shape!r}")
        if s.tier not in ("floor", "preference"):
            raise ValidationError(
                f"{s.name}: tier must be floor|preference, got {s.tier!r}")
        if s.design and s.shape != "diff":
            raise ValidationError(
                f"{s.name}: design applies only to diff-shaped lenses")
        if s.shape == "artifact":
            if not s.artifacts:
                raise ValidationError(
                    f"{s.name}: an artifact-shaped lens needs a non-empty `artifacts` table")
            built_cats = {src.category for src in s.built_from}
            seen_slugs: set[str] = set()
            for a in s.artifacts:
                if not a.name or not a.detect:
                    raise ValidationError(
                        f"{s.name}: each artifact needs `name` and `detect`")
                if not _NAME_RE.match(a.slug):
                    raise ValidationError(
                        f"{s.name}: artifact slug must be lowercase/hyphen, got {a.slug!r}")
                if a.slug in seen_slugs:
                    raise ValidationError(
                        f"{s.name}: duplicate artifact slug {a.slug!r}")
                seen_slugs.add(a.slug)
                if a.rubric not in built_cats:
                    raise ValidationError(
                        f"{s.name}: artifact {a.name!r} rubric #{a.rubric} is not in built_from")
        elif s.artifacts:
            raise ValidationError(
                f"{s.name}: `artifacts` is only valid on an artifact-shaped lens")
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
    if manifest.modes:
        allowed_floors = set()
        if manifest.synthesizer:
            allowed_floors = set(manifest.synthesizer.severity_order)
        allowed_floors.add("escalating")
        seen_modes: set[str] = set()
        for mode in manifest.modes:
            if not mode.name or not _NAME_RE.match(mode.name):
                raise ValidationError(f"invalid mode name: {mode.name!r}")
            if mode.name in seen_modes:
                raise ValidationError(f"duplicate mode name: {mode.name}")
            seen_modes.add(mode.name)
            if not mode.breadth.strip():
                raise ValidationError(f"mode {mode.name}: breadth must be non-empty")
            if not mode.triggers:
                raise ValidationError(f"mode {mode.name}: needs at least one trigger phrase")
            if mode.floor not in allowed_floors:
                raise ValidationError(
                    f"mode {mode.name}: floor {mode.floor!r} is not a severity level "
                    f"in severity_order nor 'escalating' ({sorted(allowed_floors)})"
                )
    if manifest.entrypoints:
        if manifest.synthesizer is None:
            raise ValidationError(
                "entrypoints require a synthesizer (synthesis.md is bundled into every entrypoint)")
        skill_names = {s.name for s in manifest.skills}
        reserved = set(skill_names)
        if manifest.router:
            reserved.add(manifest.router.name)
        if manifest.synthesizer:
            reserved.add(manifest.synthesizer.name)
        seen_eps: set[str] = set()
        covered: set[str] = set()
        for ep in manifest.entrypoints:
            if ep.name in seen_eps:
                raise ValidationError(f"duplicate entrypoint name: {ep.name}")
            seen_eps.add(ep.name)
            if ep.name in reserved:
                raise ValidationError(
                    f"entrypoint {ep.name} collides with an existing skill/router/synthesizer name")
            if not re.fullmatch(r"[a-z0-9-]{1,64}", ep.name):
                raise ValidationError(
                    f"entrypoint {ep.name!r}: name must be 1-64 lowercase letters, digits, "
                    "or hyphens (it becomes a directory under collapsed/skills/)")
            if not ep.description:
                raise ValidationError(f"entrypoint {ep.name}: description must be non-empty")
            if len(ep.description) > 1024:
                raise ValidationError(f"entrypoint {ep.name}: description exceeds 1024 chars")
            if not ep.shapes:
                raise ValidationError(f"entrypoint {ep.name}: shapes must be non-empty")
            for shape in ep.shapes:
                if shape not in {"diff", "repo", "decision", "artifact"}:
                    raise ValidationError(f"entrypoint {ep.name}: unknown shape {shape!r}")
            for s in manifest.skills:
                if s.shape in ep.shapes or (ep.include_design and s.design):
                    covered.add(s.name)
        orphans = skill_names - covered
        if orphans:
            raise ValidationError(
                f"lenses not covered by any entrypoint: {sorted(orphans)}")


# Plain-scalar prose fields. A bare " #" inside one is read by YAML as a comment
# and silently truncates the value (e.g. a route note "… pairs with #16 …" loses
# everything from "#16", dropping the cross-reference). description/picker are
# written as ">" block scalars, where "#" is literal, so they are exempt.
_PLAIN_PROSE_KEYS = ("note", "when", "about", "resolve")
_KEY_RE = re.compile(r"^(\s*)(?:- )?([\w-]+):\s*(.*)$")
_COMMENT_RISK = re.compile(r"\s#")


def _check_comment_truncation(raw: str, path: str) -> None:
    """Reject an unquoted prose value containing " #": YAML would treat it as a
    comment and silently drop the rest of the value. Tell the author to quote it
    rather than shipping a truncated note. (Found via PR #37: two router notes
    truncated at "pairs with" / "drift;" because of a bare #16 / #14.)"""
    prose_indent: int | None = None
    for n, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            prose_indent = None
            continue
        m = _KEY_RE.match(line)
        if m:
            indent, key, val = len(m.group(1)), m.group(2), m.group(3)
            if key in _PLAIN_PROSE_KEYS and val[:1] not in ('"', "'", ">", "|", ""):
                if _COMMENT_RISK.search(" " + val):
                    _raise_truncation(path, n, key)
                prose_indent = indent  # scan its continuation lines too
            else:
                prose_indent = None
            continue
        # a continuation line of the current plain prose value
        if prose_indent is not None and len(line) - len(line.lstrip()) > prose_indent:
            if _COMMENT_RISK.search(line):
                _raise_truncation(path, n, "value continuation")
        else:
            prose_indent = None


def _raise_truncation(path: str, line_no: int, key: str) -> None:
    raise ValidationError(
        f"{path}:{line_no}: unquoted {key} contains ' #' — YAML reads it as a "
        f"comment and silently truncates the value. Wrap the value in quotes "
        f'(e.g. note: "… pairs with #16 …").')


def _list_field(s: dict, key: str, skill_index: int) -> list:
    # A missing key or an explicit YAML null (bare "key:") both normalize to
    # [] -- but any other non-list value (e.g. `cross_ref: false`) is a
    # malformed manifest, not a normalization case, and must raise the same
    # actionable ValidationError every other malformed field gets here (#140,
    # #142 review).
    value = s.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(
            f"skill #{skill_index}: {key!r} must be a list, got {type(value).__name__}")
    return value


def load_manifest(path: str) -> Manifest:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    _check_comment_truncation(raw, path)
    data = yaml.safe_load(raw)
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
            artifacts = [Artifact(name=a["name"], detect=a["detect"],
                                  rubric=a["rubric"], slug=a["slug"])
                         for a in _list_field(s, "artifacts", i)]
            skills.append(Skill(
                name=s["name"],
                # description is a required key (KeyError -> ValidationError
                # below if absent), but a *present* bare `description:` null
                # slips past that guard -- `None.strip()` would crash the
                # same way picker's did (review follow-up on #142).
                description=(s["description"] or "").strip(),
                shape=s["shape"],
                wave=s["wave"],
                built_from=built,
                primary_owner=s.get("primary_owner"),
                cross_ref=_list_field(s, "cross_ref", i),
                design=s.get("design", False),
                # Same bare-null gap as cross_ref/artifacts: .get(key, "")
                # only substitutes "" when the key is absent, not when it's
                # present-but-null (#142 review).
                picker=(s.get("picker") or "").strip(),
                artifacts=artifacts,
                tier=s.get("tier", "preference"),
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
                # Same bare-null gap as skill.description/picker (#142 review):
                # a present-but-null "description:" slips past the KeyError
                # guard and would crash `.strip()` on None.
                description=(r["description"] or "").strip(),
                # Same bare-null gap, two fields over: a present-but-null
                # "routes:" would crash `for x in r["routes"]` with
                # TypeError, and a present-but-null "note:" on a route
                # would leak None past a caller expecting str (CodeRabbit
                # review on #145).
                routes=[Route(when=x["when"], run=x["run"], note=x.get("note") or "")
                        for x in (r["routes"] or [])],
                # Same bare-null gap as description above: .get(key, "")
                # only substitutes "" when the key is absent, not when
                # it's present-but-null (CodeRabbit review on #145).
                body=(r.get("body") or "").strip(),
            )
        except KeyError as e:
            raise ValidationError(f"router: missing field {e}") from e
    synthesizer = None
    if "synthesizer" in data:
        sy = data["synthesizer"]
        try:
            synthesizer = Synthesizer(
                name=sy["name"],
                # Same bare-null gap as skill.description/picker (#142 review):
                # a present-but-null "description:" slips past the KeyError
                # guard and would crash `.strip()` on None.
                description=(sy["description"] or "").strip(),
                severity_order=sy["severity_order"],
                tensions=[Tension(between=t["between"],
                                  # Same gap, one field over, for a tension's
                                  # required prose fields (#142 review).
                                  about=(t["about"] or "").strip(),
                                  resolve=(t["resolve"] or "").strip())
                          # .get(key, []) only substitutes [] when the key
                          # is absent, not when it's present-but-null; a
                          # bare "tensions:" would crash the iteration with
                          # TypeError (CodeRabbit review on #145).
                          for t in (sy.get("tensions") or [])],
            )
        except KeyError as e:
            raise ValidationError(f"synthesizer: missing field {e}") from e
    modes: list[Mode] = []
    for i, raw_mode in enumerate(data.get("modes", []) or []):
        try:
            modes.append(Mode(
                name=raw_mode["name"],
                breadth=raw_mode["breadth"],
                floor=raw_mode["floor"],
                # Same bare-null gap as tensions above: a present-but-null
                # "triggers:" would crash `list(...)` with TypeError
                # (CodeRabbit review on #145).
                triggers=list(raw_mode.get("triggers") or []),
                # Same bare-null gap as skill.picker (#142 review): .get(key,
                # "") only substitutes "" when the key is absent, not when
                # it's present-but-null. A bare "note:" doesn't crash here
                # (nothing calls .strip() on it in this function), but it
                # would crash downstream in generate.py's modes_section,
                # which does `m.note.strip()`.
                note=raw_mode.get("note") or "",
            ))
        except (KeyError, TypeError) as e:
            raise ValidationError(f"modes[{i}] in {path}: malformed mode ({e})")
    entrypoints: list[Entrypoint] = []
    for i, raw_ep in enumerate(data.get("entrypoints", []) or []):
        try:
            shapes = raw_ep["shapes"]
            if not isinstance(shapes, list) or not all(isinstance(x, str) for x in shapes):
                raise ValidationError(
                    f"entrypoints[{i}] in {path}: 'shapes' must be a list of strings "
                    f"(got {shapes!r}) — use 'shapes: [diff]', not 'shapes: diff'")
            entrypoints.append(Entrypoint(
                name=raw_ep["name"],
                # Same bare-null gap as skill.description/picker (#142
                # review): a present-but-null "description:" slips past the
                # KeyError guard and would crash `.strip()` on None.
                description=(raw_ep["description"] or "").strip(),
                shapes=list(shapes),
                include_design=bool(raw_ep.get("include_design", False)),
                # Same bare-null gap as description above: .get(key, "")
                # only substitutes "" when the key is absent, not when
                # it's present-but-null (CodeRabbit review on #145).
                body=(raw_ep.get("body") or "").strip(),
            ))
        except (KeyError, TypeError) as e:
            raise ValidationError(f"entrypoints[{i}] in {path}: malformed entrypoint ({e})")
    return Manifest(taxonomy_version=data["taxonomy_version"], skills=skills,
                    router=router, synthesizer=synthesizer, modes=modes,
                    entrypoints=entrypoints)
