# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    # Q21: an opt-in, per-lens raised eval-scenario floor (the hardened,
    # adversarial/red-team-weighted bar from the threat-modeling lens's eval
    # design, docs/threat-modeling-design-time-security.md §5), risk-tiered
    # rather than applied uniformly so lenses not yet hardened keep passing
    # `tooling.cli eval` at D8's baseline. None (the default) means "use the
    # D8 baseline of 3" — set only on lenses whose eval suite has actually
    # been raised to this bar.
    eval_min: int | None = None


@dataclass
class Route:
    when: str                # the change shape, e.g. "Schema migration or backfill"
    run: list[str]           # skill names to run for it
    note: str = ""
    # Which collapsed-entrypoint shape(s) this route's own *topic* belongs to
    # (diff|repo|decision|artifact, matching Skill.shape/Entrypoint.shapes) --
    # distinct from which lenses it runs, which can span shapes (e.g. a design
    # doc route running design-capable diff lenses). None defaults to ["diff"],
    # the shape nearly every route describes; only the repo-audit, decision, and
    # artifact rows need an explicit tag. See build_entrypoint_md's routes filter.
    shapes: list[str] | None = None


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
class DiscoverySource:
    """One place the pre-pass looks to learn which deterministic tools the
    reviewed repo already runs. `tells` says what that source establishes that
    the others don't (enforced vs. merely installed vs. documented)."""
    source: str
    tells: str


@dataclass
class ToolFamily:
    """A family of deterministic tools and the atlas lenses whose findings its
    output can evidence. `grounds` names real lenses and is validated, so a
    renamed lens can't leave a dangling pointer in the generated table."""
    kind: str
    tools: str
    grounds: list[str]


@dataclass
class Disposition:
    """What the owning lens does with one tool hit. Exactly one applies per hit
    — passing a hit through unexamined is not a disposition."""
    name: str
    when: str
    do: str


@dataclass
class PrepassRule:
    """One standing discipline rule for the pre-pass (what keeps tool grounding
    from degrading the review rather than improving it)."""
    name: str
    rule: str


@dataclass
class Prepass:
    """The deterministic-tool evidence pre-pass (G34 Tier 1): runs between the
    router's lens selection and the lenses themselves. Built entirely from the
    manifest, like the router and synthesizer."""
    name: str
    description: str
    discover: list[DiscoverySource]
    families: list[ToolFamily]
    dispositions: list[Disposition]
    rules: list[PrepassRule]
    body: str = ""           # richer "When to use" text; falls back to description


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
    prepass: Prepass | None = None
    synthesizer: Synthesizer | None = None
    modes: list[Mode] = field(default_factory=list)
    entrypoints: list[Entrypoint] = field(default_factory=list)


_NAME_RE = re.compile(r"^[a-z0-9-]+$")
_RESERVED = ("anthropic", "claude")
_SHAPES = ("diff", "repo", "decision", "artifact")


class ValidationError(Exception):
    pass


def _validate_skills(manifest: Manifest, docs_root: str) -> set[str]:
    seen: set[str] = set()
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
        if s.shape not in _SHAPES:
            raise ValidationError(
                f"{s.name}: shape must be diff|repo|decision|artifact, got {s.shape!r}")
        if s.tier not in ("floor", "preference"):
            raise ValidationError(
                f"{s.name}: tier must be floor|preference, got {s.tier!r}")
        if s.eval_min is not None and s.eval_min < 3:
            raise ValidationError(
                f"{s.name}: eval_min must be >=3 (D8's baseline), got {s.eval_min!r}")
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
    return seen


def _validate_router(manifest: Manifest, seen: set[str]) -> None:
    if manifest.router is None:
        return
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
        if route.shapes is not None:
            if (not isinstance(route.shapes, list)
                    or not all(isinstance(shape, str) for shape in route.shapes)):
                raise ValidationError(
                    f"router: route {route.when!r}: shapes must be a list of strings")
            if not route.shapes:
                raise ValidationError(f"router: route {route.when!r}: shapes must be non-empty if set")
            for shape in route.shapes:
                if shape not in _SHAPES:
                    raise ValidationError(
                        f"router: route {route.when!r}: unknown shape {shape!r}")
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


def _validate_synthesizer(manifest: Manifest, seen: set[str]) -> None:
    if manifest.synthesizer is None:
        return
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


def _validate_prepass(manifest: Manifest, seen: set[str]) -> None:
    if manifest.prepass is None:
        return
    p = manifest.prepass
    if not _NAME_RE.match(p.name) or len(p.name) > 64 or p.name in seen:
        raise ValidationError(f"prepass: invalid or duplicate name {p.name!r}")
    if not p.description or len(p.description) > 1024:
        raise ValidationError("prepass: description must be non-empty and <=1024 chars")
    if len(p.body) > 1024:
        raise ValidationError("prepass: body must be <=1024 chars")
    # Each of the four tables is load-bearing in the generated skill: without
    # discovery there is nothing to run, without families nothing to map output
    # onto, without dispositions a hit has no defined outcome, and without the
    # rules the pre-pass is a tool-output dump rather than a review step.
    for attr in ("discover", "families", "dispositions", "rules"):
        if not getattr(p, attr):
            raise ValidationError(f"prepass: {attr} must be non-empty")
    for d in p.discover:
        if not d.source or not d.tells:
            raise ValidationError("prepass: every discover entry needs `source` and `tells`")
    seen_kinds: set[str] = set()
    for f in p.families:
        if not f.kind or not f.tools:
            raise ValidationError("prepass: every family needs `kind` and `tools`")
        if f.kind in seen_kinds:
            raise ValidationError(f"prepass: duplicate family kind {f.kind!r}")
        seen_kinds.add(f.kind)
        if not f.grounds:
            raise ValidationError(
                f"prepass: family {f.kind!r} must ground at least one lens — a tool "
                "family whose output no lens owns has nowhere to send its hits")
        for lens in f.grounds:
            if lens not in seen:
                raise ValidationError(
                    f"prepass: family {f.kind!r} grounds unknown skill {lens!r}")
    seen_dispositions: set[str] = set()
    for disp in p.dispositions:
        if not disp.name or not disp.when or not disp.do:
            raise ValidationError(
                "prepass: every disposition needs `name`, `when`, and `do`")
        if disp.name in seen_dispositions:
            raise ValidationError(f"prepass: duplicate disposition {disp.name!r}")
        seen_dispositions.add(disp.name)
    for r in p.rules:
        if not r.name or not r.rule:
            raise ValidationError("prepass: every rule needs `name` and `rule`")


def _validate_composition_names(manifest: Manifest) -> None:
    """The router / pre-pass / synthesizer each generate into skills/<name>/, so
    two sharing a name would silently overwrite one another's SKILL.md. Each is
    already checked against the *lens* names in its own validator; this catches
    the collisions only visible across the three of them."""
    names = [c.name for c in (manifest.router, manifest.prepass, manifest.synthesizer)
             if c is not None]
    if len(names) != len(set(names)):
        raise ValidationError(
            f"router/prepass/synthesizer must have distinct names, got {names}")


def _validate_modes(manifest: Manifest) -> None:
    if not manifest.modes:
        return
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


def _validate_entrypoints(manifest: Manifest) -> None:
    if not manifest.entrypoints:
        return
    if manifest.synthesizer is None:
        raise ValidationError(
            "entrypoints require a synthesizer (synthesis.md is bundled into every entrypoint)")
    skill_names = {s.name for s in manifest.skills}
    reserved = set(skill_names)
    if manifest.router:
        reserved.add(manifest.router.name)
    if manifest.prepass:
        reserved.add(manifest.prepass.name)
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
            if shape not in _SHAPES:
                raise ValidationError(f"entrypoint {ep.name}: unknown shape {shape!r}")
        for s in manifest.skills:
            if s.shape in ep.shapes or (ep.include_design and s.design):
                covered.add(s.name)
    orphans = skill_names - covered
    if orphans:
        raise ValidationError(
            f"lenses not covered by any entrypoint: {sorted(orphans)}")


def validate(manifest: Manifest, docs_root: str = ".") -> None:
    seen = _validate_skills(manifest, docs_root)
    _validate_router(manifest, seen)
    _validate_prepass(manifest, seen)
    _validate_synthesizer(manifest, seen)
    _validate_composition_names(manifest)
    _validate_modes(manifest)
    _validate_entrypoints(manifest)


# Plain-scalar prose fields. A bare " #" inside one is read by YAML as a comment
# and silently truncates the value (e.g. a route note "… pairs with #16 …" loses
# everything from "#16", dropping the cross-reference). description/picker are
# written as ">" block scalars, where "#" is literal, so they are exempt.
_PLAIN_PROSE_KEYS = ("note", "when", "about", "resolve", "tells", "do", "rule", "tools")
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


def _prose(mapping: dict, key: str, where: str, *, required: bool = True,
           collapse: bool = False, null_ok: bool = False, strip: bool = True) -> str:
    """A prose field, type-checked before normalization.

    Coercing with `str(...)` is the trap this exists to avoid: it turns a bare
    `key:` (YAML null) into the literal `"None"`, which then satisfies every
    downstream non-empty check and renders as the word "None" in a generated
    table. A number is no better — it survives `str()` and crashes `.strip()`
    otherwise. Anything that isn't a string is a malformed manifest, and says
    so (regardless of `required`/`null_ok`/`strip` — those only decide what
    counts as *absent* or how a valid string gets normalized, never what
    counts as a valid *type*). `collapse` folds internal whitespace (for a
    value written across several YAML lines that must render as one table
    cell); ignored when `strip=False`.

    `required` and `null_ok` are independent: `required` governs a *missing*
    key (KeyError-shaped); `null_ok` governs a *present-but-null* one
    (`key:` with nothing after the colon). Most callers (prepass) want a
    present-but-null value to be exactly as invalid as a missing one — the
    default. A handful of longer-standing fields (skill/router/synthesizer/
    mode/entrypoint name-and-description-shaped fields) were historically
    written as `mapping["key"] or ""` — key must be present, but a bare null
    quietly normalizes to "" rather than erroring — and that tolerance is
    locked in by existing manifests and tests; `null_ok=True` preserves it
    for exactly those callers without loosening the still-strict prepass ones.

    `strip=False` opts an identifier-shaped field (name, slug) out of
    whitespace normalization entirely: those are validated downstream by
    `_NAME_RE`/`re.fullmatch`, which a stray leading/trailing space should
    fail rather than have silently trimmed away before the check ever sees
    it (round-2 review on #349) — unlike free-text prose fields (description,
    body, note), where trimming incidental whitespace is the desired
    normalization.
    """
    if key not in mapping:
        if required:
            raise ValidationError(f"{where}: missing field {key!r}")
        return ""
    value = mapping[key]
    if value is None:
        if required and not null_ok:
            raise ValidationError(f"{where}: {key!r} must be a non-empty string, got null")
        return ""
    if not isinstance(value, str):
        raise ValidationError(
            f"{where}: {key!r} must be a string, got {type(value).__name__}")
    if not strip:
        return value
    return " ".join(value.split()) if collapse else value.strip()


def _str_list(mapping: dict, key: str, where: str) -> list[str]:
    """A list-of-strings field. A present-but-null value normalizes to [] (the
    emptiness is caught by validation, with a message about the *table* rather
    than about Python types); a non-list, or any non-string entry, is malformed."""
    value = mapping.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(
            f"{where}: {key!r} must be a list, got {type(value).__name__}")
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(
                f"{where}: every {key!r} entry must be a string, "
                f"got {type(item).__name__} ({item!r})")
    return list(value)


def load_manifest(path: str) -> Manifest:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    _check_comment_truncation(raw, path)
    # Syntactically-invalid YAML must surface the same way every other
    # malformed-input case in this function does — as a ValidationError naming
    # the file — not as a raw yaml.YAMLError escaping to a caller that only
    # catches ValidationError (found by the atlas's own review of PR #159:
    # a caller assuming "OSError or ValidationError covers every load failure"
    # crashed uncaught on a bad manifest instead of degrading gracefully).
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValidationError(f"{path}: invalid YAML: {exc}") from exc
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
            artifacts = [Artifact(name=_prose(a, "name", f"skill #{i} artifact"),
                                  detect=_prose(a, "detect", f"skill #{i} artifact"),
                                  rubric=a["rubric"],
                                  slug=_prose(a, "slug", f"skill #{i} artifact", null_ok=True, strip=False))
                         for a in _list_field(s, "artifacts", i)]
            skills.append(Skill(
                name=_prose(s, "name", f"skill #{i}", null_ok=True, strip=False),
                description=_prose(s, "description", f"skill #{i}", null_ok=True),
                shape=s["shape"],
                wave=s["wave"],
                built_from=built,
                primary_owner=s.get("primary_owner"),
                cross_ref=_list_field(s, "cross_ref", i),
                design=s.get("design", False),
                picker=_prose(s, "picker", f"skill #{i}", required=False),
                artifacts=artifacts,
                tier=s.get("tier", "preference"),
                eval_min=s.get("eval_min"),
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
                name=_prose(r, "name", "router", null_ok=True, strip=False),
                description=_prose(r, "description", "router", null_ok=True),
                routes=[Route(when=_prose(x, "when", "router route"), run=x["run"],
                              note=_prose(x, "note", "router route", required=False),
                              shapes=x.get("shapes"))
                        for x in (r["routes"] or [])],
                body=_prose(r, "body", "router", required=False),
            )
        except KeyError as e:
            raise ValidationError(f"router: missing field {e}") from e
    prepass = None
    if "prepass" in data:
        p = data["prepass"]
        try:
            # Every prose field goes through _prose(), which *rejects* a
            # non-string rather than coercing it. The sibling blocks' `or ""`
            # idiom is not enough here: `str(value)` would turn a bare
            # `source:` (YAML null) into the literal string "None", which then
            # sails past _validate_prepass's non-empty check and ships a table
            # row reading "None" (CodeRabbit review on #206). A number would
            # instead raise a raw AttributeError from `.strip()`. Both are
            # malformed-manifest cases and both must surface as the
            # ValidationError naming the field. `or []` on the lists is
            # deliberately *not* a default — an empty table fails
            # _validate_prepass loudly; it only keeps the failure a
            # ValidationError instead of a raw TypeError.
            prepass = Prepass(
                name=_prose(p, "name", "prepass"),
                description=_prose(p, "description", "prepass"),
                body=_prose(p, "body", "prepass", required=False),
                discover=[DiscoverySource(
                              source=_prose(d, "source", "prepass discover", collapse=True),
                              tells=_prose(d, "tells", "prepass discover"))
                          for d in (p.get("discover") or [])],
                families=[ToolFamily(kind=_prose(f, "kind", "prepass family"),
                                     tools=_prose(f, "tools", "prepass family",
                                                  collapse=True),
                                     grounds=_str_list(f, "grounds", "prepass family"))
                          for f in (p.get("families") or [])],
                dispositions=[Disposition(name=_prose(d, "name", "prepass disposition"),
                                          when=_prose(d, "when", "prepass disposition"),
                                          do=_prose(d, "do", "prepass disposition"))
                              for d in (p.get("dispositions") or [])],
                rules=[PrepassRule(name=_prose(r, "name", "prepass rule"),
                                   rule=_prose(r, "rule", "prepass rule"))
                       for r in (p.get("rules") or [])],
            )
        except KeyError as e:
            raise ValidationError(f"prepass: missing field {e}") from e
        except TypeError as e:
            raise ValidationError(f"prepass: malformed entry ({e})") from e
    synthesizer = None
    if "synthesizer" in data:
        sy = data["synthesizer"]
        try:
            synthesizer = Synthesizer(
                name=_prose(sy, "name", "synthesizer", null_ok=True, strip=False),
                description=_prose(sy, "description", "synthesizer", null_ok=True),
                severity_order=sy["severity_order"],
                tensions=[Tension(between=t["between"],
                                  about=_prose(t, "about", "synthesizer tension", null_ok=True),
                                  resolve=_prose(t, "resolve", "synthesizer tension", null_ok=True))
                          for t in (sy.get("tensions") or [])],
            )
        except KeyError as e:
            raise ValidationError(f"synthesizer: missing field {e}") from e
    modes: list[Mode] = []
    for i, raw_mode in enumerate(data.get("modes", []) or []):
        try:
            modes.append(Mode(
                name=raw_mode["name"],
                breadth=_prose(raw_mode, "breadth", f"modes[{i}] in {path}", null_ok=True),
                floor=raw_mode["floor"],
                triggers=list(raw_mode.get("triggers") or []),
                note=_prose(raw_mode, "note", f"modes[{i}] in {path}", required=False),
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
                name=_prose(raw_ep, "name", f"entrypoints[{i}] in {path}", null_ok=True, strip=False),
                description=_prose(raw_ep, "description", f"entrypoints[{i}] in {path}", null_ok=True),
                shapes=list(shapes),
                include_design=bool(raw_ep.get("include_design", False)),
                body=_prose(raw_ep, "body", f"entrypoints[{i}] in {path}", required=False),
            ))
        except (KeyError, TypeError) as e:
            raise ValidationError(f"entrypoints[{i}] in {path}: malformed entrypoint ({e})")
    return Manifest(taxonomy_version=data["taxonomy_version"], skills=skills,
                    router=router, prepass=prepass, synthesizer=synthesizer,
                    modes=modes, entrypoints=entrypoints)
