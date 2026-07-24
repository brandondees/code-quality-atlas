# SPDX-License-Identifier: MIT
# tooling/sections.py
import re
import hashlib

_SECTION_START = re.compile(r"^## #(\d+)\b", re.MULTILINE)
_ANY_H2 = re.compile(r"^## ", re.MULTILINE)

# A heuristic bullet may be flagged with this leading marker to force it into the
# inlined Top checks regardless of its position in the list — G9: deep but
# high-value factors otherwise never surface past the ~8-check budget in a
# bundled lens. The marker is a generator directive only: it is stripped from all
# rendered output (SKILL.md Top checks and reference/heuristics.md), while
# section_hash still hashes the raw source, so drift stays consistent.
PRIORITY_MARKER = "★ "


def is_priority(bullet: str) -> bool:
    """True if a bullet (leading '- ' already stripped) carries the marker."""
    return bullet.startswith(PRIORITY_MARKER)


def strip_priority(text: str) -> str:
    """Remove the priority marker wherever it leads a bullet, for clean output.
    A no-op on text that carries no marker."""
    return text.replace("- " + PRIORITY_MARKER, "- ").replace(PRIORITY_MARKER, "")


def extract_section(markdown: str, n: int) -> str:
    """Return the text of the `## #n …` section, from its heading up to the
    next H2 heading (`## …`, numbered OR not — e.g. a trailing `## Open threads`)
    or end of document. Raises KeyError if not found.

    The boundary is *any* H2, not just the next numbered section: otherwise the
    last numbered category in a file would absorb trailing non-numbered H2s (e.g.
    `## Open threads`), polluting its reference text and provenance hash and
    causing false drift."""
    start = None
    for m in _SECTION_START.finditer(markdown):
        if int(m.group(1)) == n:
            start = m.start()
            break
    if start is None:
        raise KeyError(f"section #{n} not found")
    ends = [m.start() for m in _ANY_H2.finditer(markdown) if m.start() > start]
    end = ends[0] if ends else len(markdown)
    return markdown[start:end].rstrip() + "\n"


_SUBHEADINGS = {
    "references": "### Key references",
    "tooling": "### Tooling rules",
    "heuristics": "### Reviewable heuristics",
}
_SUB_START = re.compile(r"^### ", re.MULTILINE)


def extract_subsection(section_text: str, kind: str) -> str:
    """Return the body of a `### …` subsection matched by prefix for `kind`
    (references | tooling | heuristics). Empty string if absent or unknown kind."""
    prefix = _SUBHEADINGS.get(kind)
    if prefix is None:
        return ""
    starts = [m.start() for m in _SUB_START.finditer(section_text)]
    for i, pos in enumerate(starts):
        line_end = section_text.index("\n", pos)
        heading = section_text[pos:line_end]
        if heading.startswith(prefix):
            end = starts[i + 1] if i + 1 < len(starts) else len(section_text)
            return section_text[pos:end].rstrip() + "\n"
    return ""


_BULLET = re.compile(r"^- ", re.MULTILINE)


def extract_bullets(text: str) -> list[str]:
    """Return the top-level `- ` bullet items of `text`, each as a single
    string with its leading `- ` stripped and any continuation lines joined.
    Nested bullets stay part of their parent item."""
    starts = [m.start() for m in _BULLET.finditer(text)]
    items = []
    for i, pos in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        item = text[pos + 2:end].strip()
        # A heading/horizontal rule after the last bullet is not bullet content.
        item = re.split(r"\n(?=#|---)", item)[0].strip()
        if item:
            items.append(" ".join(line.strip() for line in item.splitlines()))
    return items


def section_hash(markdown: str, n: int) -> str:
    """SHA-256 (hex) of the normalized text of section #n."""
    normalized = extract_section(markdown, n).replace("\r\n", "\n").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()
