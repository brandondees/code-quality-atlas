# tooling/sections.py
import re
import hashlib

_SECTION_START = re.compile(r"^## #(\d+)\b", re.MULTILINE)


def extract_section(markdown: str, n: int) -> str:
    """Return the text of the `## #n …` section, from its heading up to the
    next `## ` heading or end of document. Raises KeyError if not found."""
    starts = [(int(m.group(1)), m.start()) for m in _SECTION_START.finditer(markdown)]
    for i, (num, pos) in enumerate(starts):
        if num == n:
            end = starts[i + 1][1] if i + 1 < len(starts) else len(markdown)
            return markdown[pos:end].rstrip() + "\n"
    raise KeyError(f"section #{n} not found")


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


def section_hash(markdown: str, n: int) -> str:
    """SHA-256 (hex) of the normalized text of section #n."""
    normalized = extract_section(markdown, n).replace("\r\n", "\n").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()
