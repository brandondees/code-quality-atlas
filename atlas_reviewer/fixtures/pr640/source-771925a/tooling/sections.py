# SPDX-License-Identifier: MIT
# tooling/sections.py
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator

_SECTION_START = re.compile(r"^## #(\d+)\b")
_ANY_H2 = re.compile(r"^## ")

# Opening fence marker for a fenced code block: 3+ backticks or tildes.
_FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")

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


class _FenceTracker:
    """Tracks fenced-code-block state across a Markdown document, line by
    line, so a heading- or bullet-like line inside a fence (``` or ~~~, any
    length, closing fence must match the opener's character and be at least
    as long) is treated as content, not real structure. Fence detection is
    gated on indentation `< 4`, matching CommonMark's rule that a 4+-space
    *indented* code block is never a fence, even if a line in it starts with
    backticks/tildes after stripping.

    Originally grown independently, twice, inside `generate_collapsed.py`'s
    `_strip_toc_section` and `_toc_for_body` (#313, then #317 for the second,
    unnoticed copy) and consolidated into one class there "so a third
    recurrence isn't possible" — a third recurrence happened anyway, in this
    module's own `extract_section`/`extract_subsection`/`extract_bullets`
    (#368), because they were whole-document MULTILINE regex scans with no
    fence tracking at all. Moved here so every fence-sensitive scanner in the
    package shares one implementation; `generate_collapsed.py` now imports
    this class instead of defining its own."""

    def __init__(self) -> None:
        self._fence: str | None = None

    def consume(self, line: str) -> bool:
        """Update state for `line`; return True if `line` is inside a fence
        (an opening or closing fence-marker line itself counts as inside)."""
        # CommonMark counts indentation in columns, where a tab advances to the
        # next multiple of 4 — not in raw leading-space characters. A leading
        # tab is 4 columns all by itself, so lstrip(" ") alone (which a tab
        # survives untouched) would misreport it as indent 0 and let a
        # tab-indented delimiter-like line wrongly open/close a fence.
        leading = line[: len(line) - len(line.lstrip(" \t"))]
        indent = len(leading.expandtabs(4))
        stripped = line.strip()
        if self._fence is not None:
            if (
                indent < 4
                and stripped
                and len(stripped) >= len(self._fence)
                and set(stripped) == {self._fence[0]}
            ):
                self._fence = None
            return True
        if indent < 4:
            match = _FENCE_OPEN_RE.match(stripped)
            if match:
                fence = match.group(1)
                # A backtick fence's info string may not itself contain a
                # backtick (CommonMark); a tilde fence has no such
                # restriction. Getting this wrong lets a line like
                # "```contains ` a backtick" open a fence that never
                # legitimately closes, swallowing every real heading/bullet
                # after it as "content".
                if fence[0] == "`" and "`" in stripped[match.end() :]:
                    return False
                self._fence = fence
                return True
        return False


def _iter_lines(text: str) -> Iterator[str]:
    """Yield each line of `text`, trailing `\\n` included except possibly on
    the last, splitting only on a literal `\\n`.

    Deliberately NOT `text.splitlines(keepends=True)`: that also treats
    `\\v`, `\\f`, `\\x1c`-`\\x1e`, NEL (`\\x85`), U+2028/U+2029, and a lone
    `\\r` as line breaks, while the `re.MULTILINE` `^`/`pattern.finditer`
    scan this replaced only ever treated `\\n` as one. Splitting on the
    wider set would let a `##`/`###`/`- `-prefixed fragment right after one
    of those characters be newly (mis)matched as if it started its own
    line — the same class of false-structure bug this module exists to
    prevent, just via a different trigger than a fence."""
    parts = text.split("\n")
    last = len(parts) - 1
    for i, part in enumerate(parts):
        yield part if i == last else part + "\n"


def _match_offsets(
    text: str, pattern: re.Pattern[str]
) -> list[tuple[int, re.Match[str]]]:
    """(offset, match) for each line in `text` matched by `pattern` at its
    start, skipping lines inside a fenced code block (see `_FenceTracker`).
    `offset` is the string index the line begins at, so callers can slice
    `text` the same way the old whole-document `pattern.finditer(text)` did."""
    results: list[tuple[int, re.Match[str]]] = []
    offset = 0
    fence = _FenceTracker()
    for line in _iter_lines(text):
        if not fence.consume(line):
            m = pattern.match(line)
            if m:
                results.append((offset, m))
        offset += len(line)
    return results


def extract_section(markdown: str, n: int) -> str:
    """Return the text of the `## #n …` section, from its heading up to the
    next H2 heading (`## …`, numbered OR not — e.g. a trailing `## Open threads`)
    or end of document. Raises KeyError if not found.

    The boundary is *any* H2, not just the next numbered section: otherwise the
    last numbered category in a file would absorb trailing non-numbered H2s (e.g.
    `## Open threads`), polluting its reference text and provenance hash and
    causing false drift.

    Fence-aware (#368): a `## `-prefixed line inside a fenced code block (a
    worked example showing Markdown structure) is example content, not a real
    heading, and can't start or end a section."""
    start = None
    for offset, m in _match_offsets(markdown, _SECTION_START):
        if int(m.group(1)) == n:
            start = offset
            break
    if start is None:
        raise KeyError(f"section #{n} not found")
    ends = [offset for offset, _ in _match_offsets(markdown, _ANY_H2) if offset > start]
    end = ends[0] if ends else len(markdown)
    return markdown[start:end].rstrip() + "\n"


_SUBHEADINGS = {
    "references": "### Key references",
    "tooling": "### Tooling rules",
    "heuristics": "### Reviewable heuristics",
}
_SUB_START = re.compile(r"^### ")


def extract_subsection(section_text: str, kind: str) -> str:
    """Return the body of a `### …` subsection matched by prefix for `kind`
    (references | tooling | heuristics). Empty string if absent or unknown kind.

    Fence-aware (#368): a `### `-prefixed line inside a fenced code block
    can't start or end a subsection."""
    prefix = _SUBHEADINGS.get(kind)
    if prefix is None:
        return ""
    starts = [offset for offset, _ in _match_offsets(section_text, _SUB_START)]
    for i, pos in enumerate(starts):
        line_end = section_text.index("\n", pos)
        heading = section_text[pos:line_end]
        if heading.startswith(prefix):
            end = starts[i + 1] if i + 1 < len(starts) else len(section_text)
            return section_text[pos:end].rstrip() + "\n"
    return ""


_BULLET = re.compile(r"^- ")


def extract_bullets(text: str) -> list[str]:
    """Return the top-level `- ` bullet items of `text`, each as a single
    string with its leading `- ` stripped and any continuation lines joined.
    Nested bullets stay part of their parent item.

    Fence-aware (#368): a `- `-prefixed line inside a fenced code block (e.g.
    a worked YAML example) is content of the enclosing bullet, not a phantom
    bullet of its own."""
    starts = [offset for offset, _ in _match_offsets(text, _BULLET)]
    items = []
    for i, pos in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        item = text[pos + 2 : end].strip()
        # A heading/horizontal rule after the last bullet is not bullet content.
        item = re.split(r"\n(?=#|---)", item)[0].strip()
        if item:
            items.append(" ".join(line.strip() for line in item.splitlines()))
    return items


def section_hash(markdown: str, n: int) -> str:
    """SHA-256 (hex) of the normalized text of section #n."""
    normalized = (
        extract_section(markdown, n).replace("\r\n", "\n").strip().encode("utf-8")
    )
    return hashlib.sha256(normalized).hexdigest()
