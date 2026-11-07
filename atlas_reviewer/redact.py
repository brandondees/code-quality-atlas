# SPDX-License-Identifier: MIT
"""Secret redaction for untrusted text. Pure: no I/O.

`RedactedText` can only be minted by `redact()`, so any field typed
`RedactedText` (every untrusted input a prompt accepts) has been through
this module. The patterns are best-effort, not a guarantee: a secret in a
format listed nowhere below still passes through, which is why the
controller also scrubs the exact values of its own credentials.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

_MINT = object()
_MIN_KNOWN_SECRET_LEN = 8
TRUNCATION_MARKER = "\n[... truncated by atlas_reviewer ...]\n"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("model-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("aws-key-id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*")),
)

# The name may carry `_`/`-`/`.`-joined prefixes and suffixes
# (`DB_PASSWORD`, `client_secret`, `AWS_SECRET_ACCESS_KEY`, `tokens`) and may
# be a quoted JSON/YAML key. `\b` alone cannot anchor it: `_` is a word
# character, so `OPENAI_API_KEY` has no boundary before `API`. The bounded
# repeats keep matching linear on adversarial logs (`a_a_a_...`).
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])"
    r"((?:[A-Za-z0-9]{1,40}[_.-]){0,6}"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credentials?)s?"
    r"(?:[_.-][A-Za-z0-9]{1,40}){0,6}[\"']?)"
    r"(\s*[:=]\s*)([\"']?)[^\s\"']{8,}"
)


@dataclass(frozen=True)
class RedactedText:
    text: str
    redaction_count: int
    truncated_from: int | None = None
    _mint: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._mint is not _MINT:
            raise TypeError("RedactedText can only be created by redact()")


def redact(
    raw: str,
    known_secrets: Sequence[str] = (),
    max_chars: int | None = None,
) -> RedactedText:
    text, count = _scrub_known(raw, known_secrets)
    for label, pattern in _PATTERNS:
        text, hits = pattern.subn(f"[REDACTED:{label}]", text)
        count += hits
    text, hits = _ASSIGNMENT.subn(r"\1\2\3[REDACTED:assignment]", text)
    count += hits
    cut = max_chars is not None and len(text) > max_chars
    return RedactedText(
        _truncate(text, max_chars), count, len(text) if cut else None, _MINT
    )


@dataclass(frozen=True)
class Redactor:
    """`redact` bound to the controller's own credential values. `sources`
    are read on every call, so a token minted mid-review is scrubbed too."""

    known_secrets: tuple[str, ...] = ()
    sources: tuple[Callable[[], Sequence[str]], ...] = ()

    def __call__(self, raw: str, max_chars: int | None = None) -> RedactedText:
        dynamic = tuple(s for source in self.sources for s in source())
        return redact(raw, (*self.known_secrets, *dynamic), max_chars)


def _scrub_known(raw: str, known_secrets: Sequence[str]) -> tuple[str, int]:
    usable = sorted(
        (s for s in known_secrets if len(s) >= _MIN_KNOWN_SECRET_LEN),
        key=len,
        reverse=True,
    )
    text, count = raw, 0
    for secret in usable:
        count += text.count(secret)
        text = text.replace(secret, "[REDACTED:controller-credential]")
    return text, count


def _truncate(text: str, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATION_MARKER
