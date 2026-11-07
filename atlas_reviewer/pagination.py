# SPDX-License-Identifier: MIT
"""Parse GitHub's `Link` response header (RFC 8288). Pure.

GitHub paginates list endpoints with `Link: <url>; rel="next", ...`
(https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api).
"""

from __future__ import annotations

import re

DEFAULT_MAX_PAGES = 10
_LINK = re.compile(r"<([^>]*)>\s*;\s*([^,]*)")
_REL_NEXT = re.compile(r'(?i)\brel\s*=\s*"?([^";]*)"?')


def next_link(header: str | None) -> str | None:
    """The `rel="next"` target, or None on the last page."""
    for url, params in _LINK.findall(header or ""):
        rel = _REL_NEXT.search(params)
        if rel and "next" in rel.group(1).split():
            return url
    return None
