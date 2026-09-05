# SPDX-License-Identifier: MIT
# tooling/manifest.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tooling.evals import D8_MIN_SCENARIOS
from tooling.sections import extract_section


@dataclass
class Source:
    category: int
    source: str  # "<path>#<n>"

    def __post_init__(self) -> None:
        # Validate the "<path>#<n>" shape up front so a malformed source raises a
        # clear error here rather than a bare IndexError/ValueError later in .section.
        if "#" not in self.source:
            raise ValueError(f"source must be '<path>#<section>', got {self.source!r}")
        fragment = self.source.rsplit("#", 1)[1]
        if not fragment.isdigit():
            raise ValueError(
                f"source section must be a non-negative integer, got {self.source!r}"
            )
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

    name: str  # human label, e.g. "SKILL.md / agent skill"
    detect: str  # the presence signal, e.g. "a SKILL.md file is added or changed"
    rubric: int  # the rubric research section (also in built_from)
    slug: str  # filename stem for the bundled rubric, e.g. "skill-md"


@dataclass
class Skill:
    name: str
    description: str
    shape: str
    built_from: list[Source]
    # Not read by anything downstream (verified: no generator, router, or
    # entrypoint code touches it). Optional rather than deleted outright --
    # every existing manifest entry still writes one and there's no value in
    # forcing a mechanical edit across all of them -- but a dead field
    # shouldn't force a new entry to supply a value it needs for nothing
    # (#381; contrast `primary_owner`, deleted outright since setting it also
    # cost nothing to skip).
    wave: int = 0
    cross_ref: list[int] = field(default_factory=list)
    design: bool = False  # diff lens that also applies to design docs/plans
    picker: str = ""  # one-line differentiator for the router catalog
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

    def __post_init__(self) -> None:
        # Structural invariants a caller shouldn't be able to construct
        # around, mirroring Source.__post_init__'s pattern -- these were
        # previously enforced only by validate(), so a Skill built directly
        # (a test fixture, a future call site) and never passed to
        # validate() could carry a self-contradictory shape/design or
        # shape/artifacts combination that _scope_line, the router catalog,
        # and entrypoint_lenses would then each read differently (#381).
        if self.design and self.shape != "diff":
            raise ValidationError(
                f"{self.name}: design applies only to diff-shaped lenses"
            )
        if self.shape == "artifact" and not self.artifacts:
            raise ValidationError(
                f"{self.name}: an artifact-shaped lens needs a non-empty `artifacts` table"
            )


@dataclass
class Route:
    when: str  # the change shape, e.g. "Schema migration or backfill"
    run: list[str]  # skill names to run for it
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
    body: str = ""  # richer "When to use" text; falls back to description


@dataclass
class Tension:
    between: list[str]  # the two lenses that pull opposite ways
    about: str  # what they disagree on, one line
    resolve: str  # the default the synthesizer applies


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
    body: str = ""  # richer "When to use" text; falls back to description


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


def _validate_skill_identity(s: Skill, seen: set[str]) -> None:
    if not _NAME_RE.match(s.name) or len(s.name) > 64:
        raise ValidationError(f"invalid name: {s.name!r} (lowercase/hyphen, <=64)")
    if any(w in s.name for w in _RESERVED):
        raise ValidationError(f"name uses reserved word: {s.name!r}")
    if s.name in seen:
        raise ValidationError(f"duplicate skill name: {s.name!r}")
    seen.add(s.name)


def _validate_skill_metadata(s: Skill) -> None:
    if not s.description or len(s.description) > 1024:
        raise ValidationError(
            f"{s.name}: description must be non-empty and <=1024 chars"
        )
    if s.shape not in _SHAPES:
        raise ValidationError(
            f"{s.name}: shape must be diff|repo|decision|artifact, got {s.shape!r}"
        )
    if s.tier not in ("floor", "preference"):
        raise ValidationError(
            f"{s.name}: tier must be floor|preference, got {s.tier!r}"
        )
    if s.eval_min is not None and s.eval_min < D8_MIN_SCENARIOS:
        raise ValidationError(
            f"{s.name}: eval_min must be >={D8_MIN_SCENARIOS} (D8's baseline), "
            f"got {s.eval_min!r}"
        )


def _validate_skill_artifacts(s: Skill) -> None:
    # design-requires-diff and artifact-shape-requires-artifacts are
    # enforced in Skill.__post_init__ (unconditionally, at construction —
    # every Skill in manifest.skills already passed through it, load_manifest
    # being the only production construction site), not re-checked here.
    if s.shape == "artifact":
        built_cats = {src.category for src in s.built_from}
        seen_slugs: set[str] = set()
        for a in s.artifacts:
            if not a.name or not a.detect:
                raise ValidationError(
                    f"{s.name}: each artifact needs `name` and `detect`"
                )
            if not _NAME_RE.match(a.slug):
                raise ValidationError(
                    f"{s.name}: artifact slug must be lowercase/hyphen, got {a.slug!r}"
                )
            if a.slug in seen_slugs:
                raise ValidationError(f"{s.name}: duplicate artifact slug {a.slug!r}")
            seen_slugs.add(a.slug)
            if a.rubric not in built_cats:
                raise ValidationError(
                    f"{s.name}: artifact {a.name!r} rubric #{a.rubric} is not in built_from"
                )
    elif s.artifacts:
        raise ValidationError(
            f"{s.name}: `artifacts` is only valid on an artifact-shaped lens"
        )


def _validate_skill_built_from_shape(s: Skill) -> None:
    if len(s.picker) > 160:
        raise ValidationError(f"{s.name}: picker must be <=160 chars")
    if not s.built_from:
        raise ValidationError(f"{s.name}: built_from must be non-empty")
    categories = [src.category for src in s.built_from]
    if len(categories) != len(set(categories)):
        raise ValidationError(f"{s.name}: built_from lists a category more than once")
    for c in s.cross_ref:
        if c not in categories:
            raise ValidationError(
                f"{s.name}: cross_ref category {c} is not in built_from"
            )


def _validate_skill_sources(
    s: Skill, docs_root: str, primaries: dict[int, list[str]]
) -> None:
    for src in s.built_from:
        try:
            text = Path(docs_root, src.path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValidationError(
                f"{s.name}: cannot read source file {src.path}: {exc}"
            ) from exc
        try:
            extract_section(text, src.section)
        except KeyError as exc:
            raise ValidationError(
                f"{s.name}: source not found: section #{src.section} in {src.path}"
            ) from exc
        if src.category not in s.cross_ref:
            primaries.setdefault(src.category, []).append(s.name)


def _validate_primary_owners(primaries: dict[int, list[str]]) -> None:
    # G1: one primary owner per category — skills sharing a category must mark
    # all but one claim as cross_ref so findings don't double-report.
    for category, owners in sorted(primaries.items()):
        if len(owners) > 1:
            raise ValidationError(
                f"category #{category} has multiple primary owners: {', '.join(owners)} "
                f"— mark all but one with cross_ref: [{category}]"
            )


def _validate_skills(manifest: Manifest, docs_root: str) -> set[str]:
    seen: set[str] = set()
    primaries: dict[int, list[str]] = {}
    for s in manifest.skills:
        _validate_skill_identity(s, seen)
        _validate_skill_metadata(s)
        _validate_skill_artifacts(s)
        _validate_skill_built_from_shape(s)
        _validate_skill_sources(s, docs_root, primaries)
    _validate_primary_owners(primaries)
    return seen


def _validate_router_identity(r: Router, seen: set[str]) -> None:
    if not _NAME_RE.match(r.name) or len(r.name) > 64 or r.name in seen:
        raise ValidationError(f"router: invalid or duplicate name {r.name!r}")
    if not r.description or len(r.description) > 1024:
        raise ValidationError("router: description must be non-empty and <=1024 chars")
    if len(r.body) > 1024:
        raise ValidationError("router: body must be <=1024 chars")


def _validate_router_route_shapes(route: Route) -> None:
    if route.shapes is None:
        return
    if not isinstance(route.shapes, list) or not all(
        isinstance(shape, str) for shape in route.shapes
    ):
        raise ValidationError(
            f"router: route {route.when!r}: shapes must be a list of strings"
        )
    if not route.shapes:
        raise ValidationError(
            f"router: route {route.when!r}: shapes must be non-empty if set"
        )
    for shape in route.shapes:
        if shape not in _SHAPES:
            raise ValidationError(
                f"router: route {route.when!r}: unknown shape {shape!r}"
            )


def _validate_router_route(route: Route, seen: set[str]) -> None:
    if not route.when or not route.run:
        raise ValidationError("router: every route needs `when` and `run`")
    _validate_router_route_shapes(route)
    for lens in route.run:
        if lens not in seen:
            raise ValidationError(
                f"router: route {route.when!r} runs unknown skill {lens!r}"
            )


def _validate_router_pickers(manifest: Manifest) -> None:
    # The catalog lists every lens by its picker line; a missing picker
    # would silently leave that lens undiscoverable to the router.
    for s in manifest.skills:
        if not s.picker:
            raise ValidationError(
                f"{s.name}: picker is required when a router is defined"
            )


def _validate_router(manifest: Manifest, seen: set[str]) -> None:
    if manifest.router is None:
        return
    r = manifest.router
    _validate_router_identity(r, seen)
    if not r.routes:
        raise ValidationError("router: routes must be non-empty")
    for route in r.routes:
        _validate_router_route(route, seen)
    _validate_router_pickers(manifest)


def _validate_synthesizer(manifest: Manifest, seen: set[str]) -> None:
    if manifest.synthesizer is None:
        return
    sy = manifest.synthesizer
    if not _NAME_RE.match(sy.name) or len(sy.name) > 64 or sy.name in seen:
        raise ValidationError(f"synthesizer: invalid or duplicate name {sy.name!r}")
    if not sy.description or len(sy.description) > 1024:
        raise ValidationError(
            "synthesizer: description must be non-empty and <=1024 chars"
        )
    if len(sy.severity_order) < 2:
        raise ValidationError("synthesizer: severity_order needs at least two levels")
    if len(sy.severity_order) != len(set(sy.severity_order)):
        raise ValidationError("synthesizer: severity_order has duplicate levels")
    # A tension is only meaningful between two known, distinct lenses;
    # an unknown name would print a dangling reference in the merged report.
    for t in sy.tensions:
        if len(t.between) != 2 or t.between[0] == t.between[1]:
            raise ValidationError(
                f"synthesizer: tension `between` must name two distinct lenses, got {t.between}"
            )
        for lens in t.between:
            if lens not in seen:
                raise ValidationError(
                    f"synthesizer: tension references unknown skill {lens!r}"
                )
        if not t.about or not t.resolve:
            raise ValidationError(
                f"synthesizer: tension {t.between} needs `about` and `resolve`"
            )


def _validate_prepass_identity(p: Prepass, seen: set[str]) -> None:
    if not _NAME_RE.match(p.name) or len(p.name) > 64 or p.name in seen:
        raise ValidationError(f"prepass: invalid or duplicate name {p.name!r}")
    if not p.description or len(p.description) > 1024:
        raise ValidationError("prepass: description must be non-empty and <=1024 chars")
    if len(p.body) > 1024:
        raise ValidationError("prepass: body must be <=1024 chars")


def _validate_prepass_tables_nonempty(p: Prepass) -> None:
    # Each of the four tables is load-bearing in the generated skill: without
    # discovery there is nothing to run, without families nothing to map output
    # onto, without dispositions a hit has no defined outcome, and without the
    # rules the pre-pass is a tool-output dump rather than a review step.
    for attr in ("discover", "families", "dispositions", "rules"):
        if not getattr(p, attr):
            raise ValidationError(f"prepass: {attr} must be non-empty")


def _validate_prepass_discover(p: Prepass) -> None:
    for d in p.discover:
        if not d.source or not d.tells:
            raise ValidationError(
                "prepass: every discover entry needs `source` and `tells`"
            )


def _validate_prepass_families(p: Prepass, seen: set[str]) -> None:
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
                "family whose output no lens owns has nowhere to send its hits"
            )
        for lens in f.grounds:
            if lens not in seen:
                raise ValidationError(
                    f"prepass: family {f.kind!r} grounds unknown skill {lens!r}"
                )


def _validate_prepass_dispositions(p: Prepass) -> None:
    seen_dispositions: set[str] = set()
    for disp in p.dispositions:
        if not disp.name or not disp.when or not disp.do:
            raise ValidationError(
                "prepass: every disposition needs `name`, `when`, and `do`"
            )
        if disp.name in seen_dispositions:
            raise ValidationError(f"prepass: duplicate disposition {disp.name!r}")
        seen_dispositions.add(disp.name)


def _validate_prepass_rules(p: Prepass) -> None:
    for r in p.rules:
        if not r.name or not r.rule:
            raise ValidationError("prepass: every rule needs `name` and `rule`")


def _validate_prepass(manifest: Manifest, seen: set[str]) -> None:
    if manifest.prepass is None:
        return
    p = manifest.prepass
    _validate_prepass_identity(p, seen)
    _validate_prepass_tables_nonempty(p)
    _validate_prepass_discover(p)
    _validate_prepass_families(p, seen)
    _validate_prepass_dispositions(p)
    _validate_prepass_rules(p)


def _validate_composition_names(manifest: Manifest) -> None:
    """The router / pre-pass / synthesizer each generate into skills/<name>/, so
    two sharing a name would silently overwrite one another's SKILL.md. Each is
    already checked against the *lens* names in its own validator; this catches
    the collisions only visible across the three of them."""
    names = [
        c.name
        for c in (manifest.router, manifest.prepass, manifest.synthesizer)
        if c is not None
    ]
    if len(names) != len(set(names)):
        raise ValidationError(
            f"router/prepass/synthesizer must have distinct names, got {names}"
        )


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
            raise ValidationError(
                f"mode {mode.name}: needs at least one trigger phrase"
            )
        if mode.floor not in allowed_floors:
            raise ValidationError(
                f"mode {mode.name}: floor {mode.floor!r} is not a severity level "
                f"in severity_order nor 'escalating' ({sorted(allowed_floors)})"
            )


def _entrypoint_reserved_names(manifest: Manifest, skill_names: set[str]) -> set[str]:
    reserved = set(skill_names)
    if manifest.router:
        reserved.add(manifest.router.name)
    if manifest.prepass:
        reserved.add(manifest.prepass.name)
    if manifest.synthesizer:
        reserved.add(manifest.synthesizer.name)
    return reserved


def _validate_entrypoint_identity(
    ep: Entrypoint, reserved: set[str], seen_eps: set[str]
) -> None:
    if ep.name in seen_eps:
        raise ValidationError(f"duplicate entrypoint name: {ep.name}")
    seen_eps.add(ep.name)
    if ep.name in reserved:
        raise ValidationError(
            f"entrypoint {ep.name} collides with an existing skill/router/synthesizer name"
        )
    if not re.fullmatch(r"[a-z0-9-]{1,64}", ep.name):
        raise ValidationError(
            f"entrypoint {ep.name!r}: name must be 1-64 lowercase letters, digits, "
            "or hyphens (it becomes a directory under collapsed/skills/)"
        )
    if not ep.description:
        raise ValidationError(f"entrypoint {ep.name}: description must be non-empty")
    if len(ep.description) > 1024:
        raise ValidationError(f"entrypoint {ep.name}: description exceeds 1024 chars")


def _validate_entrypoint_shapes(ep: Entrypoint) -> None:
    if not ep.shapes:
        raise ValidationError(f"entrypoint {ep.name}: shapes must be non-empty")
    for shape in ep.shapes:
        if shape not in _SHAPES:
            raise ValidationError(f"entrypoint {ep.name}: unknown shape {shape!r}")


def _validate_entrypoints(manifest: Manifest) -> None:
    if not manifest.entrypoints:
        return
    if manifest.synthesizer is None:
        raise ValidationError(
            "entrypoints require a synthesizer (synthesis.md is bundled into every entrypoint)"
        )
    skill_names = {s.name for s in manifest.skills}
    reserved = _entrypoint_reserved_names(manifest, skill_names)
    seen_eps: set[str] = set()
    covered: set[str] = set()
    for ep in manifest.entrypoints:
        _validate_entrypoint_identity(ep, reserved, seen_eps)
        _validate_entrypoint_shapes(ep)
        for s in manifest.skills:
            if s.shape in ep.shapes or (ep.include_design and s.design):
                covered.add(s.name)
    orphans = skill_names - covered
    if orphans:
        raise ValidationError(
            f"lenses not covered by any entrypoint: {sorted(orphans)}"
        )


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
        f'(e.g. note: "… pairs with #16 …").'
    )


def _list_field(s: dict, key: str, where: str) -> list:
    # A missing key or an explicit YAML null (bare "key:") both normalize to
    # [] -- but any other non-list value (e.g. `cross_ref: false`) is a
    # malformed manifest, not a normalization case, and must raise the same
    # actionable ValidationError every other malformed field gets here (#140,
    # #142 review). Also used for top-level `modes`/`entrypoints`,
    # `synthesizer.tensions`, and the prepass `discover`/`families`/
    # `dispositions`/`rules` tables (#381), which had the same gap under
    # their own `x.get(...) or []` normalization: a falsy non-list (`{}`,
    # `0`, `false`) silently passed as though absent, and a truthy scalar
    # (`tensions: 5`) escaped as a raw TypeError from the list comprehension/
    # enumerate() that consumed it, in both cases bypassing load_manifest's
    # ValidationError contract entirely (CodeRabbit review on #411).
    value = s.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(
            f"{where}: {key!r} must be a list, got {type(value).__name__}"
        )
    return value


def _prose(
    mapping: dict,
    key: str,
    where: str,
    *,
    required: bool = True,
    collapse: bool = False,
    null_ok: bool = False,
    strip: bool = True,
) -> str:
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
    if not isinstance(mapping, dict):
        raise ValidationError(
            f"{where}: must be a mapping, got {type(mapping).__name__}"
        )
    if key not in mapping:
        if required:
            raise ValidationError(f"{where}: missing field {key!r}")
        return ""
    value = mapping[key]
    if value is None:
        if required and not null_ok:
            raise ValidationError(
                f"{where}: {key!r} must be a non-empty string, got null"
            )
        return ""
    if not isinstance(value, str):
        raise ValidationError(
            f"{where}: {key!r} must be a string, got {type(value).__name__}"
        )
    if not strip:
        return value
    return " ".join(value.split()) if collapse else value.strip()


def _str_list(mapping: dict, key: str, where: str) -> list[str]:
    """A list-of-strings field. A present-but-null value normalizes to [] (the
    emptiness is caught by validation, with a message about the *table* rather
    than about Python types); a non-list, or any non-string entry, is malformed."""
    if not isinstance(mapping, dict):
        raise ValidationError(
            f"{where}: must be a mapping, got {type(mapping).__name__}"
        )
    value = mapping.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(
            f"{where}: {key!r} must be a list, got {type(value).__name__}"
        )
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(
                f"{where}: every {key!r} entry must be a string, "
                f"got {type(item).__name__} ({item!r})"
            )
    return list(value)


def _optional_str_list(mapping: dict, key: str, where: str) -> list[str] | None:
    """Like `_str_list`, but a present-but-null or absent value stays `None`
    rather than normalizing to `[]` — for a field whose absence is itself
    meaningful (`Route.shapes`: `None` means "defaults to `['diff']`",
    distinct from an explicit, empty list)."""
    if not isinstance(mapping, dict):
        raise ValidationError(
            f"{where}: must be a mapping, got {type(mapping).__name__}"
        )
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValidationError(
            f"{where}: {key!r} must be a list, got {type(value).__name__}"
        )
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(
                f"{where}: every {key!r} entry must be a string, "
                f"got {type(item).__name__} ({item!r})"
            )
    return list(value)


def _load_skills(data: dict, path: str) -> list[Skill]:
    if not isinstance(data["skills"], list):
        raise ValidationError(
            f"{path}: 'skills' must be a list, got {type(data['skills']).__name__}"
        )
    skills = []
    for i, s in enumerate(data["skills"]):
        if not isinstance(s, dict):
            raise ValidationError(
                f"skill #{i}: must be a mapping, got {type(s).__name__}"
            )
        try:
            raw_built = s["built_from"]
            if not isinstance(raw_built, list):
                raise ValidationError(
                    f"skill #{i}: 'built_from' must be a list, "
                    f"got {type(raw_built).__name__}"
                )
            built = [
                Source(category=b["category"], source=b["source"]) for b in raw_built
            ]
            artifacts = [
                Artifact(
                    name=_prose(a, "name", f"skill #{i} artifact"),
                    detect=_prose(a, "detect", f"skill #{i} artifact"),
                    rubric=a["rubric"],
                    slug=_prose(
                        a, "slug", f"skill #{i} artifact", null_ok=True, strip=False
                    ),
                )
                for a in _list_field(s, "artifacts", f"skill #{i}")
            ]
            wave = s.get("wave", 0)
            if not isinstance(wave, int) or isinstance(wave, bool):
                raise ValidationError(
                    f"skill #{i}: 'wave' must be an integer, got {type(wave).__name__}"
                )
            eval_min = s.get("eval_min")
            if eval_min is not None and (
                not isinstance(eval_min, int) or isinstance(eval_min, bool)
            ):
                raise ValidationError(
                    f"skill #{i}: 'eval_min' must be an integer, "
                    f"got {type(eval_min).__name__}"
                )
            skills.append(
                Skill(
                    name=_prose(s, "name", f"skill #{i}", null_ok=True, strip=False),
                    description=_prose(s, "description", f"skill #{i}", null_ok=True),
                    shape=s["shape"],
                    wave=wave,
                    built_from=built,
                    cross_ref=_list_field(s, "cross_ref", f"skill #{i}"),
                    design=s.get("design", False),
                    picker=_prose(s, "picker", f"skill #{i}", required=False),
                    artifacts=artifacts,
                    tier=s.get("tier", "preference"),
                    eval_min=eval_min,
                )
            )
        except KeyError as e:
            raise ValidationError(f"skill #{i}: missing field {e}") from e
        except ValueError as e:  # malformed Source string
            raise ValidationError(f"skill #{i}: {e}") from e
    return skills


def _load_router(data: dict) -> Router | None:
    if "router" not in data:
        return None
    r = data["router"]
    if not isinstance(r, dict):
        raise ValidationError(f"router: must be a mapping, got {type(r).__name__}")
    try:
        raw_routes = r["routes"]
        if raw_routes is not None and not isinstance(raw_routes, list):
            raise ValidationError(
                f"router: 'routes' must be a list, got {type(raw_routes).__name__}"
            )
        return Router(
            name=_prose(r, "name", "router", null_ok=True, strip=False),
            description=_prose(r, "description", "router", null_ok=True),
            routes=[
                Route(
                    when=_prose(x, "when", "router route"),
                    run=_str_list(x, "run", "router route"),
                    note=_prose(x, "note", "router route", required=False),
                    shapes=_optional_str_list(x, "shapes", "router route"),
                )
                for x in (raw_routes or [])
            ],
            body=_prose(r, "body", "router", required=False),
        )
    except KeyError as e:
        raise ValidationError(f"router: missing field {e}") from e


def _load_prepass(data: dict) -> Prepass | None:
    if "prepass" not in data:
        return None
    p = data["prepass"]
    try:
        # Every prose field goes through _prose(), which *rejects* a
        # non-string rather than coercing it. The sibling blocks' looser
        # `null_ok=True` tolerance (present-but-null normalizes to "") is
        # not enough here: `str(value)` would turn a bare `source:` (YAML
        # null) into the literal string "None", which then sails past
        # _validate_prepass's non-empty check and ships a table row
        # reading "None" (CodeRabbit review on #206). A number would
        # instead raise a raw AttributeError from `.strip()`. Both are
        # malformed-manifest cases and both must surface as the
        # ValidationError naming the field. Each list field is routed
        # through _list_field rather than `p.get(x) or []`, so a truthy
        # non-list (`discover: 5`) raises instead of iterating character-
        # by-character, and a falsy-but-present non-list (`rules: {}`)
        # raises instead of silently normalizing to [] (#381).
        return Prepass(
            name=_prose(p, "name", "prepass"),
            description=_prose(p, "description", "prepass"),
            body=_prose(p, "body", "prepass", required=False),
            discover=[
                DiscoverySource(
                    source=_prose(d, "source", "prepass discover", collapse=True),
                    tells=_prose(d, "tells", "prepass discover"),
                )
                for d in _list_field(p, "discover", "prepass")
            ],
            families=[
                ToolFamily(
                    kind=_prose(f, "kind", "prepass family"),
                    tools=_prose(f, "tools", "prepass family", collapse=True),
                    grounds=_str_list(f, "grounds", "prepass family"),
                )
                for f in _list_field(p, "families", "prepass")
            ],
            dispositions=[
                Disposition(
                    name=_prose(d, "name", "prepass disposition"),
                    when=_prose(d, "when", "prepass disposition"),
                    do=_prose(d, "do", "prepass disposition"),
                )
                for d in _list_field(p, "dispositions", "prepass")
            ],
            rules=[
                PrepassRule(
                    name=_prose(r, "name", "prepass rule"),
                    rule=_prose(r, "rule", "prepass rule"),
                )
                for r in _list_field(p, "rules", "prepass")
            ],
        )
    except KeyError as e:
        raise ValidationError(f"prepass: missing field {e}") from e
    except TypeError as e:
        raise ValidationError(f"prepass: malformed entry ({e})") from e


def _load_synthesizer(data: dict) -> Synthesizer | None:
    if "synthesizer" not in data:
        return None
    sy = data["synthesizer"]
    try:
        return Synthesizer(
            name=_prose(sy, "name", "synthesizer", null_ok=True, strip=False),
            description=_prose(sy, "description", "synthesizer", null_ok=True),
            severity_order=_str_list(sy, "severity_order", "synthesizer"),
            tensions=[
                Tension(
                    between=_str_list(t, "between", "synthesizer tension"),
                    about=_prose(t, "about", "synthesizer tension", null_ok=True),
                    resolve=_prose(t, "resolve", "synthesizer tension", null_ok=True),
                )
                for t in _list_field(sy, "tensions", "synthesizer")
            ],
        )
    except KeyError as e:
        raise ValidationError(f"synthesizer: missing field {e}") from e


def _load_modes(data: dict, path: str) -> list[Mode]:
    modes: list[Mode] = []
    for i, raw_mode in enumerate(_list_field(data, "modes", path)):
        try:
            modes.append(
                Mode(
                    name=_prose(raw_mode, "name", f"modes[{i}] in {path}", strip=False),
                    breadth=_prose(
                        raw_mode, "breadth", f"modes[{i}] in {path}", null_ok=True
                    ),
                    floor=_prose(raw_mode, "floor", f"modes[{i}] in {path}"),
                    triggers=_str_list(raw_mode, "triggers", f"modes[{i}] in {path}"),
                    note=_prose(
                        raw_mode, "note", f"modes[{i}] in {path}", required=False
                    ),
                )
            )
        except (KeyError, TypeError) as e:
            raise ValidationError(f"modes[{i}] in {path}: malformed mode ({e})") from e
    return modes


def _load_entrypoints(data: dict, path: str) -> list[Entrypoint]:
    entrypoints: list[Entrypoint] = []
    for i, raw_ep in enumerate(_list_field(data, "entrypoints", path)):
        try:
            shapes = raw_ep["shapes"]
            if not isinstance(shapes, list) or not all(
                isinstance(x, str) for x in shapes
            ):
                raise ValidationError(
                    f"entrypoints[{i}] in {path}: 'shapes' must be a list of strings "
                    f"(got {shapes!r}) — use 'shapes: [diff]', not 'shapes: diff'"
                )
            entrypoints.append(
                Entrypoint(
                    name=_prose(
                        raw_ep,
                        "name",
                        f"entrypoints[{i}] in {path}",
                        null_ok=True,
                        strip=False,
                    ),
                    description=_prose(
                        raw_ep,
                        "description",
                        f"entrypoints[{i}] in {path}",
                        null_ok=True,
                    ),
                    shapes=list(shapes),
                    include_design=bool(raw_ep.get("include_design", False)),
                    body=_prose(
                        raw_ep, "body", f"entrypoints[{i}] in {path}", required=False
                    ),
                )
            )
        except (KeyError, TypeError) as e:
            raise ValidationError(
                f"entrypoints[{i}] in {path}: malformed entrypoint ({e})"
            ) from e
    return entrypoints


def load_manifest(path: str) -> Manifest:
    # A manifest file with invalid UTF-8 bytes must surface as a
    # ValidationError naming the file, same as every other malformed-input
    # case here — not a raw UnicodeDecodeError escaping to a caller that
    # only catches (OSError, ValidationError) (CodeRabbit review on #412;
    # mirrors the existing (OSError, UnicodeError) guard around a *source*
    # file's own read in `validate`, just applied to the manifest itself).
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"{path}: not valid UTF-8: {exc}") from exc
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
            f"{path}: expected a YAML mapping, got {type(data).__name__}"
        )
    for key in ("skills", "taxonomy_version"):
        if key not in data:
            raise ValidationError(f"{path}: missing required key {key!r}")
    # Split by manifest section (skills / router / prepass / synthesizer / modes /
    # entrypoints) rather than one 260-line function, mirroring how validate()
    # is already decomposed per section below (#381: load_manifest was the
    # unswept sibling of that decomposition, at cyclomatic complexity 41).
    return Manifest(
        taxonomy_version=data["taxonomy_version"],
        skills=_load_skills(data, path),
        router=_load_router(data),
        prepass=_load_prepass(data),
        synthesizer=_load_synthesizer(data),
        modes=_load_modes(data, path),
        entrypoints=_load_entrypoints(data, path),
    )
