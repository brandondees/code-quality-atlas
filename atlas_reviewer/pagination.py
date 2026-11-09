# SPDX-License-Identifier: MIT
"""Parse GitHub's `Link` response header (RFC 8288). Pure.

GitHub paginates list endpoints with `Link: <url>; rel="next", ...`
(https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api).
A quoted parameter value may hold commas, semicolons or a whole
`<url>; rel=next`, so the header is scanned token by token rather than
split. Relation types compare case-insensitively, and only a link's first
`rel` counts (RFC 8288 section 3.3).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

DEFAULT_MAX_PAGES = 10
_TARGET = re.compile(r"\s*<([^>]*)>")
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_PARAM = re.compile(rf"\s*;\s*([^\s=;,]+)\s*(?:=\s*({_QUOTED}|[^\s;,]*))?")
_UNTIL_COMMA = re.compile(rf'(?:{_QUOTED}|"|[^",])*')
_ESCAPE = re.compile(r"\\(.)")


def next_link(header: str | None) -> str | None:
    """The `rel="next"` target, or None on the last page."""
    for url, rel in _links(header or ""):
        if "next" in rel.lower().split():
            return url
    return None


def _links(header: str) -> Iterator[tuple[str, str]]:
    pos = 0
    while pos < len(header):
        if target := _TARGET.match(header, pos):
            pos = target.end()
            rel = None
            while param := _PARAM.match(header, pos):
                pos = param.end()
                name, value = param.groups()
                if rel is None and name.lower() == "rel" and value is not None:
                    rel = _unquote(value)
            yield target.group(1), rel or ""
        rest = _UNTIL_COMMA.match(header, pos)
        pos = (rest.end() if rest else len(header)) + 1


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _ESCAPE.sub(r"\1", value[1:-1])
    return value
