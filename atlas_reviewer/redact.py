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

_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_KEY_BASE64 = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_KEY_HEADER = re.compile(r"\b(?:Proc-Type|DEK-Info|Comment):")
_KEY_LINE_MIN = 16
_QUOTING = re.compile(r"^[\"'`(]+|(?:\\n|[\"'`,;)\\])+$")
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
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
    r"(\s*(?::\s*[A-Za-z_][\w.\[\]|, ]{0,200}?(?==))?[:=]\s*)"
    r"(?:(\")(?:[^\"\\\n]|\\.){8,}\"|(')(?:[^'\\\n]|\\.){8,}'|([\"']?)[^\s\"']{8,})"
)
# `known_secrets: tuple[str, ...]` is a type annotation, not a value; a
# value shaped like a subscripted type is left alone after a bare `:`.
_ANNOTATION = re.compile(r"[A-Za-z_][\w.]*\[[\w.\[\],|]*\]*,?")


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
    text, hits = _private_keys(text)
    count += hits
    for label, pattern in _PATTERNS:
        text, hits = pattern.subn(f"[REDACTED:{label}]", text)
        count += hits
    text, hits = _ASSIGNMENT.subn(_assignment, text)
    count += hits
    cut = max_chars is not None and len(text) > max_chars
    return RedactedText(
        _truncate(text, max_chars), count, len(text) if cut else None, _MINT
    )


def tail(redacted: RedactedText, max_chars: int) -> RedactedText:
    """The last `max_chars` of already-redacted text, from the first whole
    line. Cutting after redaction keeps a block that straddles the cut (a
    private key) recognisable while it is scrubbed."""
    text = redacted.text
    if len(text) <= max_chars:
        return redacted
    start = len(text) - max(max_chars, 0)
    cut = text[start:]
    if text[start - 1] != "\n":
        cut = cut[cut.find("\n") + 1 :]
    return RedactedText(cut, redacted.redaction_count, len(text), _MINT)


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


def _assignment(m: re.Match[str]) -> str:
    """A quoted value is replaced through the matching closing quote, so
    spaces, the other quote and backslash-escaped quotes stay inside it; an
    unquoted one up to the first space or quote."""
    name, sep, double, single, open_quote = m.group(1, 2, 3, 4, 5)
    quote = double or single
    if quote:
        return f"{name}{sep}{quote}[REDACTED:assignment]{quote}"
    value = m.group(0)[len(name) + len(sep) :]
    if "=" not in sep and _ANNOTATION.fullmatch(value):
        return m.group(0)
    return f"{name}{sep}{open_quote}[REDACTED:assignment]"


def _private_keys(text: str) -> tuple[str, int]:
    """Each BEGIN through the next END. A BEGIN with no END after it (a log
    cut before the key's END line, or code that only mentions the marker)
    is removed with the key material that follows it, not through the end
    of the text: a diff is redacted whole, and swallowing to the end hid
    every later file. Linear: once no END follows a BEGIN, none follows
    any later BEGIN either, so the END search is not repeated."""
    kept: list[str] = []
    count = pos = 0
    ends_left = True
    while (begin := _KEY_BEGIN.search(text, pos)) is not None:
        kept.append(text[pos : begin.start()])
        count += 1
        end = _KEY_END.search(text, begin.end()) if ends_left else None
        if end is None:
            ends_left = False
            kept.append("[REDACTED:private-key-unterminated]")
            pos = _key_material_end(text, begin.end())
            continue
        kept.append("[REDACTED:private-key]")
        pos = end.end()
    kept.append(text[pos:])
    return "".join(kept), count


def _key_material_end(text: str, pos: int) -> int:
    """Where an unterminated key's material ends: the rest of the BEGIN
    line, then every following line that is a PEM header or ends in a
    base64 run (whatever precedes it: a diff marker, a log timestamp,
    indentation, quoting), across blank lines between them. A short base64
    line counts only straight after a full one (a key's last line) or as
    the text's final line (a log cut mid-key), and only when padded or
    alone on its line (so `<timestamp> next step` is kept)."""
    line_end = text.find("\n", pos)
    if line_end == -1:
        return len(text)
    swallowed, last_was_full = line_end, False
    while line_end < len(text):
        nxt = text.find("\n", line_end + 1)
        end = len(text) if nxt == -1 else nxt
        line = text[line_end + 1 : end]
        tokens = line.split()
        if not tokens:
            last_was_full = False
        else:
            token = _QUOTING.sub("", tokens[-1])
            is_base64 = bool(token) and _KEY_BASE64.fullmatch(token) is not None
            if _KEY_HEADER.search(line) or (is_base64 and len(token) >= _KEY_LINE_MIN):
                swallowed, last_was_full = end, True
            elif (
                is_base64
                and (last_was_full or nxt == -1)
                and _alone_or_padded(token, tokens)
            ):
                swallowed, last_was_full = end, False
            else:
                break
        line_end = end
    return swallowed


def _alone_or_padded(token: str, tokens: list[str]) -> bool:
    return token.endswith("=") or sum(t not in ("+", "-") for t in tokens) == 1


def _truncate(text: str, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATION_MARKER
