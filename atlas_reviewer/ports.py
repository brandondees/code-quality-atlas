# SPDX-License-Identifier: MIT
"""The small interfaces every adapter implements. No I/O here.

Each port has one fake/offline implementation (used by tests and
`--dry-run`) and at most one live one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from atlas_reviewer.prompt import Prompt, UntrustedBlock
from atlas_reviewer.redact import RedactedText

Json = Mapping[str, Any]


class BoundaryError(RuntimeError):
    """An external API (GitHub, Sprites, a model provider) failed or
    returned something this service cannot use."""


class NotFoundError(BoundaryError):
    """The external resource does not exist (HTTP 404)."""


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class GitHubReader(Protocol):
    """Read-only GitHub access. There is deliberately no write method."""

    def get_pull(self, repo: str, number: int) -> Json: ...

    def get_pull_diff(self, repo: str, number: int) -> str: ...

    def list_check_runs(self, repo: str, sha: str) -> Json: ...

    def list_workflow_runs(self, repo: str, branch: str) -> Json: ...

    def list_run_artifacts(self, repo: str, run_id: int) -> Json: ...

    def get_run_logs(self, repo: str, run_id: int) -> bytes: ...

    def get_tarball(self, repo: str, sha: str) -> bytes: ...

    def get_issue(self, repo: str, number: int) -> Json: ...


class SpritesApi(Protocol):
    """The outside (control-plane) Sprites API. Only the controller holds
    it; nothing running inside a Sprite ever sees its credential."""

    def create(self, name: str) -> None: ...

    def set_network_policy(self, name: str, rules: Sequence[Json]) -> None: ...

    def get_network_policy(self, name: str) -> Json: ...

    def set_memory_limit(self, name: str, limit_mb: int) -> None: ...

    def exec(
        self, name: str, argv: Sequence[str], stdin: bytes, timeout_s: float
    ) -> bytes: ...

    def delete(self, name: str) -> None: ...

    def exists(self, name: str) -> bool: ...


class RunnerLedger(Protocol):
    """Durable record of runners that may still exist, written *before*
    create so a crashed controller's runners can be swept later."""

    def record(self, name: str) -> None: ...

    def clear(self, name: str) -> None: ...

    def pending(self) -> tuple[str, ...]: ...


class ModelProvider(Protocol):
    name: str

    def complete(self, prompt: Prompt) -> str: ...


@dataclass(frozen=True)
class ReviewRequest:
    repo: str
    pr_number: int
    head_sha: str
    blocks: tuple[UntrustedBlock, ...]


@dataclass(frozen=True)
class Narrative:
    harness: str
    provider: str
    text: RedactedText


class ReviewHarness(Protocol):
    """Drives the skill bundle against one review request."""

    name: str

    def review(self, request: ReviewRequest) -> Narrative: ...
