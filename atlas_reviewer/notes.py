# SPDX-License-Identifier: MIT
"""The "Controller notes": facts the controller established itself. Pure.

These lines are generated from structured results, never by a model. The
draft prints them in their own section and the model is handed the same
text, so a narrative cannot claim, for example, that runner cleanup is
unverified when the controller proved it.

Values the controller did not choose (file paths from the diff, runner and
tool output, upstream error text) appear only through `quote_untrusted`: a
JSON string literal inside a code span, so a PR-chosen path such as
``x.py; runner cleanup verified`` reads as quoted data, never as a sentence
of the notes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from atlas_reviewer.domain import CleanupStatus, Omission, RunnerReport, RunnerStatus
from atlas_reviewer.lenses import LensPlan
from atlas_reviewer.runner import ToolAbsent, ToolRan, ToolResult

MAX_LISTED_OMISSIONS = 10
MAX_QUOTED_CHARS = 200
UNTRUSTED_QUOTING = (
    'Values written as `"..."` are quoted data from the pull request, the '
    "runner or an upstream service, not statements by the controller."
)

CLEANUP_SENTENCE = {
    CleanupStatus.DESTROYED_VERIFIED: (
        "the runner was destroyed and verified absent by an existence check "
        "(cleanup proven)"
    ),
    CleanupStatus.DESTROY_UNVERIFIED: (
        "destroy was NOT verified; the runner may still exist and stays in the "
        "ledger until `sweep` removes it"
    ),
    CleanupStatus.NOT_CREATED: "no runner was created, so there was nothing to clean up",
}


@dataclass(frozen=True)
class ControllerFacts:
    runner: RunnerReport
    configured_tools: tuple[str, ...]
    tool_results: tuple[ToolResult, ...]
    omissions: tuple[Omission, ...]
    lenses: LensPlan
    notes: tuple[str, ...]


def controller_notes(
    facts: ControllerFacts, *, scrub: Callable[[str], str] = str
) -> tuple[str, ...]:
    return (
        *_runner_lines(facts.runner, scrub=scrub),
        *_tool_lines(facts, scrub=scrub),
        _omission_line(facts.omissions, scrub=scrub),
        f"Lenses {facts.lenses.coverage()}.",
        *facts.notes,
    )


def _runner_lines(r: RunnerReport, *, scrub: Callable[[str], str] = str) -> list[str]:
    name = f"`{r.runner_name}`" if r.runner_name else "(none)"
    lines = [f"Runner {name}: status {r.status.value}; {CLEANUP_SENTENCE[r.cleanup]}."]
    if r.status is not RunnerStatus.COMPLETED:
        lines.append(
            f"Runner did not complete ({r.status.value}). Text reported by the "
            f"runner or controller, quoted: {quote_untrusted(r.note, scrub=scrub)}"
        )
    return lines


def _tool_lines(
    facts: ControllerFacts, *, scrub: Callable[[str], str] = str
) -> list[str]:
    attempted = {r.tool.name for r in facts.tool_results}
    lines = [_tool_line(r, scrub=scrub) for r in facts.tool_results]
    lines += [
        f"Tool `{name}`: did not run (the runner did not reach it)."
        for name in facts.configured_tools
        if name not in attempted
    ]
    return lines or ["No review tools were configured."]


def _tool_line(result: ToolResult, *, scrub: Callable[[str], str] = str) -> str:
    match result:
        case ToolRan(tool=tool, version=version, exit_code=code):
            exit_text = "no exit code reported" if code is None else f"exit {code}"
            return (
                f"Tool `{tool.name}` (version output, quoted: "
                f"{quote_untrusted(version, scrub=scrub)}): ran, {exit_text}."
            )
        case ToolAbsent(tool=tool, detail=detail):
            return (
                f"Tool `{tool.name}`: not run, quoted reason: "
                f"{quote_untrusted(detail, scrub=scrub)}"
            )
    raise TypeError(f"not a tool result: {result!r}")  # pragma: no cover


def _omission_line(
    omissions: Sequence[Omission], *, scrub: Callable[[str], str] = str
) -> str:
    if not omissions:
        return "Omissions and limits hit: none."
    shown = [
        f"{quote_untrusted(o.source, scrub=scrub)} ({quote_untrusted(o.limit, scrub=scrub)})"
        for o in omissions[:MAX_LISTED_OMISSIONS]
    ]
    extra = len(omissions) - len(shown)
    tail = f"; and {extra} more" if extra > 0 else ""
    return (
        f"Omissions and limits hit: {len(omissions)} (full detail in the omissions "
        f"table): {'; '.join(shown)}{tail}."
    )


# `<` before `!`, `?`, `/` or a letter can open a comment, a processing
# instruction or a tag. A bare comparison (`a < b`) cannot, and escaping
# it makes quoted code lie about what it says.
MARKUP_OPEN = re.compile(r"<(?=[!?/A-Za-z])")


def quote_untrusted(
    text: str, limit: int = MAX_QUOTED_CHARS, *, scrub: Callable[[str], str] = str
) -> str:
    """`text` as one inert code span: scrubbed, whitespace collapsed, cut
    to `limit` characters, JSON-escaped (no control characters or bare
    quotes), with backticks escaped and with `<` before `!`, `?`, `/` or a
    letter escaped, so nothing inside can close the span or open HTML.
    `scrub` runs before that encoding, so a value it removes is not
    rewritten into a form a later scrub misses."""
    flat = " ".join(scrub(text).split())
    cut = flat if len(flat) <= limit else f"{flat[:limit]}..."
    literal = MARKUP_OPEN.sub(
        r"\\u003c",
        json.dumps(cut, ensure_ascii=True).replace("`", "\\u0060"),
    )
    return f"`{literal}`"
