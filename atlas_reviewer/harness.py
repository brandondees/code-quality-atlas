# SPDX-License-Identifier: MIT
"""The skill-bundle harness: prompts built from this repo's collapsed
`reviewing-a-change` entrypoint and its `choosing-review-lenses` picker,
sent through a `ModelProvider`."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path

from atlas_reviewer.budget import input_token_bound
from atlas_reviewer.picker import load_picker
from atlas_reviewer.ports import ModelProvider, Narrative, PickRequest, ReviewRequest
from atlas_reviewer.prompt import Prompt, UntrustedBlock, build_prompt
from atlas_reviewer.redact import Redactor

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE = REPO_ROOT / "collapsed" / "skills" / "reviewing-a-change" / "SKILL.md"
NARRATIVE_CHARS = 20_000
PICK_REPLY_CHARS = 4_000
NONCE_CHARS = 16


def load_bundle(path: Path = DEFAULT_BUNDLE) -> str:
    return path.read_text(encoding="utf-8")


class SkillBundleHarness:
    name = "skill-bundle"

    def __init__(
        self,
        provider: ModelProvider,
        bundle: str,
        redactor: Redactor,
        nonce: Callable[[], str] = lambda: secrets.token_hex(NONCE_CHARS // 2),
        picker: str | None = None,
    ) -> None:
        self._provider = provider
        self._bundle = bundle
        self._redactor = redactor
        self._nonce = nonce
        self._picker = load_picker() if picker is None else picker

    def review(self, request: ReviewRequest) -> Narrative:
        text = self._provider.complete(self._review_prompt(request, self._nonce()))
        return Narrative(
            self.name, self._provider.name, self._redactor(text, NARRATIVE_CHARS)
        )

    def pick(self, request: PickRequest) -> str:
        prompt = build_prompt(
            _subject(request.repo, request.pr_number, request.head_sha),
            self._picker,
            request.blocks,
            self._nonce(),
            instructions=request.instructions,
            procedure="lens picker",
        )
        return self._redactor(self._provider.complete(prompt), PICK_REPLY_CHARS).text

    def prompt_tokens(self, request: ReviewRequest) -> int:
        """An upper bound for any nonce of `NONCE_CHARS` ASCII characters,
        the only part of the prompt that differs per call. Each copy of the
        nonce inside a block is swapped for a shorter marker, so the longest
        prompt is one whose nonce occurs in no block: it is measured with a
        placeholder of the same UTF-8 length made of a character no block
        contains."""
        prompt = self._review_prompt(request, _absent_placeholder(request.blocks))
        return input_token_bound(prompt.system + prompt.user)

    def _review_prompt(self, request: ReviewRequest, nonce: str) -> Prompt:
        return build_prompt(
            _subject(request.repo, request.pr_number, request.head_sha),
            self._bundle,
            request.blocks,
            nonce,
            request.lenses,
            request.lens_coverage,
        )

    def usage_lines(self) -> tuple[str, ...]:
        return self._provider.usage_lines()


def _absent_placeholder(blocks: tuple[UntrustedBlock, ...]) -> str:
    """`NONCE_CHARS` UTF-8 bytes of one four-byte character absent from every
    block; a prompt within any token bound cannot hold all ~1M of them."""
    present = set().union(*(b.content.text for b in blocks))
    char = next(chr(c) for c in range(0x10000, 0x110000) if chr(c) not in present)
    return char * (NONCE_CHARS // 4)


def _subject(repo: str, pr_number: int, head_sha: str) -> str:
    return f"{repo} pull request #{pr_number} at {head_sha}"
