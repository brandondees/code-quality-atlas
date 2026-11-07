# SPDX-License-Identifier: MIT
"""The skill-bundle harness: one prompt built from this repo's collapsed
`reviewing-a-change` entrypoint, sent through a `ModelProvider`."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path

from atlas_reviewer.ports import ModelProvider, Narrative, ReviewRequest
from atlas_reviewer.prompt import build_prompt
from atlas_reviewer.redact import Redactor

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE = REPO_ROOT / "collapsed" / "skills" / "reviewing-a-change" / "SKILL.md"
NARRATIVE_CHARS = 20_000


def load_bundle(path: Path = DEFAULT_BUNDLE) -> str:
    return path.read_text(encoding="utf-8")


class SkillBundleHarness:
    name = "skill-bundle"

    def __init__(
        self,
        provider: ModelProvider,
        bundle: str,
        redactor: Redactor,
        nonce: Callable[[], str] = lambda: secrets.token_hex(8),
    ) -> None:
        self._provider = provider
        self._bundle = bundle
        self._redactor = redactor
        self._nonce = nonce

    def review(self, request: ReviewRequest) -> Narrative:
        subject = (
            f"{request.repo} pull request #{request.pr_number} at {request.head_sha}"
        )
        prompt = build_prompt(
            subject,
            self._bundle,
            request.blocks,
            self._nonce(),
            request.lenses,
            request.lens_coverage,
        )
        text = self._provider.complete(prompt)
        return Narrative(
            self.name, self._provider.name, self._redactor(text, NARRATIVE_CHARS)
        )

    def usage_lines(self) -> tuple[str, ...]:
        return self._provider.usage_lines()
