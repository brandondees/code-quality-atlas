# SPDX-License-Identifier: MIT
# tooling/drift.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tooling.frontmatter import read_frontmatter
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
    # Validate the shape so a malformed header/body gives a clear
    # ValueError, not Index/Type/KeyError.
    _, front = read_frontmatter(skill_md)
    if (
        not isinstance(front, dict)
        or "name" not in front
        or not isinstance(front.get("provenance"), dict)
        or "built_from" not in front["provenance"]
    ):
        raise ValueError(
            f"{skill_md}: frontmatter must define `name` and `provenance.built_from`"
        )
    return front["name"], front["provenance"]["built_from"]


def check_drift(skills_root: str = "skills", docs_root: str = ".") -> list[DriftReport]:
    reports: list[DriftReport] = []
    for skill_md in sorted(Path(skills_root).glob("*/SKILL.md")):
        name, built_from = _read_provenance(skill_md)
        # The container itself (not just its entries) can be malformed, e.g.
        # `built_from: null` or `built_from: 5` in the frontmatter -- that
        # would otherwise reach `for b in built_from` below and raise an
        # unwrapped TypeError ("'NoneType'/'int' object is not iterable")
        # instead of a clear DriftError. Mirrors manifest.py's _load_skills
        # container-level guard on raw_built (issue #555 round 2).
        if not isinstance(built_from, list):
            raise DriftError(
                f"{name}: 'built_from' must be a list, got {type(built_from).__name__}"
            )
        changed: list[Source] = []
        for b in built_from:
            # A built_from entry that isn't a mapping at all (e.g. a bare string
            # or YAML null) would otherwise reach `b["category"]` below and raise
            # an unwrapped TypeError ("string indices must be integers" / "'NoneType'
            # object is not subscriptable") with no skill context -- the same
            # malformed-input shape as the KeyError/ValueError cases just below,
            # just one step earlier (issue #555, filed from #554's review threads).
            if not isinstance(b, dict):
                raise DriftError(
                    f"{name}: malformed built_from entry {b!r}: expected a mapping"
                )
            # A non-string/null `source` (e.g. `source: 5` or `source: null`)
            # would otherwise reach Source.__post_init__'s `"#" not in self.source`
            # check below and raise an unwrapped TypeError ("argument of type
            # 'int'/'NoneType' is not iterable") instead of a clear DriftError --
            # the sibling shape to the non-mapping check just above (issue #555).
            if "source" in b and not isinstance(b["source"], str):
                raise DriftError(
                    f"{name}: malformed built_from entry {b!r}: source must be a "
                    f"string, got {type(b['source']).__name__}"
                )
            # A built_from entry missing `category`/`source`/`hash` (KeyError), or
            # one whose `category`/`source` is malformed enough for Source's own
            # validation to reject it (ValueError -- e.g. a bool category, which
            # is a subtype of int in Python and would otherwise silently
            # masquerade as category 1), must surface as a DriftError naming the
            # skill, like every other malformed-input case in this function --
            # not a bare KeyError/ValueError traceback with no skill context
            # (mirrors the missing-source-file and renumbered-section guards
            # just below, and issue #107's original fix for this same function).
            try:
                src = Source(category=b["category"], source=b["source"])
                expected_hash = b["hash"]
            except KeyError as exc:
                raise DriftError(
                    f"{name}: malformed built_from entry {b!r}: missing field {exc}"
                ) from exc
            except ValueError as exc:
                raise DriftError(
                    f"{name}: malformed built_from entry {b!r}: {exc}"
                ) from exc
            # A renamed/missing source file (OSError) or one that isn't valid
            # UTF-8 (UnicodeDecodeError, a ValueError subclass — not an OSError)
            # would otherwise escape with no skill/path context; surface both as
            # a DriftError the CLI can report cleanly.
            try:
                source_text = Path(docs_root, src.path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise DriftError(
                    f"{name}: cannot read source {src.path!r}: {exc}"
                ) from exc
            # A source section can legitimately disappear from a research doc
            # after a skill was generated from it -- renumbered during a
            # taxonomy promotion, or its heading text edited out -- the exact
            # "the source changed under a generated skill" case this command
            # exists to catch, not an internal programming error. Left
            # uncaught, extract_section's KeyError escaped check_drift as a
            # raw traceback (unlike the OSError/UnicodeDecodeError case just
            # above, fixed for a missing *file* by #107 but never extended to
            # a missing *section* within an existing file).
            try:
                current = section_hash(source_text, src.section)
            except KeyError as exc:
                raise DriftError(
                    f"{name}: source section #{src.section} not found in "
                    f"{src.path!r} ({exc}) -- was it renumbered or removed?"
                ) from exc
            if current != expected_hash:
                changed.append(src)
        if changed:
            reports.append(DriftReport(skill=name, changed=changed))
    return reports
