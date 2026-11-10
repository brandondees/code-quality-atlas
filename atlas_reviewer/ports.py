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

from atlas_reviewer.prompt import LoadedLens, Prompt, UntrustedBlock
from atlas_reviewer.redact import RedactedText

Json = Mapping[str, Any]


class BoundaryError(RuntimeError):
    """An external API (GitHub, Sprites, a model provider) failed or
    returned something this service cannot use."""


class NotFoundError(BoundaryError):
    """The external resource does not exist (HTTP 404)."""


class ResponseTooLargeError(BoundaryError):
    """A download exceeded the byte cap the caller set for it."""


class StreamTimeoutError(BoundaryError):
    """A streamed response stopped arriving. `received` is every body byte
    that did arrive, and `first_byte` says the wait that ran out was the
    one for the first of them."""

    def __init__(
        self, message: str, received: bytes = b"", *, first_byte: bool = False
    ) -> None:
        super().__init__(message)
        self.received = received
        self.first_byte = first_byte


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class TokenSource(Protocol):
    """Hands out a GitHub token. The live source mints short-lived App
    installation tokens; a fixed token exists only in `fakes`, for tests."""

    def token(self) -> str: ...


@dataclass(frozen=True)
class Listing:
    """Every entry of one paginated GitHub list, up to the page cap.
    `truncated` means a further page existed and was not read."""

    items: tuple[Json, ...]
    truncated: bool
    pages_read: int


class GitHubReader(Protocol):
    """Read-only GitHub access. There is deliberately no write method."""

    def get_pull(self, repo: str, number: int) -> Json: ...

    def get_pull_diff(self, repo: str, number: int) -> str: ...

    def list_check_runs(self, repo: str, sha: str) -> Listing: ...

    def list_pull_commits(self, repo: str, number: int) -> Listing: ...

    def list_workflow_runs(self, repo: str, branch: str) -> Listing: ...

    def list_workflow_runs_at(self, repo: str, sha: str) -> Listing: ...

    def list_run_jobs(self, repo: str, run_id: int) -> Listing: ...

    def list_run_artifacts(self, repo: str, run_id: int) -> Listing: ...

    def get_job_logs(self, repo: str, job_id: int, max_bytes: int) -> bytes: ...

    def download_artifact(
        self, repo: str, artifact_id: int, max_bytes: int
    ) -> bytes: ...

    def get_tarball(self, repo: str, sha: str) -> bytes: ...

    def get_issue(self, repo: str, number: int) -> Json: ...

    def list_issue_comments(self, repo: str, number: int) -> Listing: ...

    def list_review_comments(self, repo: str, number: int) -> Listing: ...

    def list_reviews(self, repo: str, number: int) -> Listing: ...

    def get_compare(self, repo: str, base: str, head: str) -> Json: ...


class SpritesApi(Protocol):
    """The outside (control-plane) Sprites API. Only the controller holds
    it; nothing running inside a Sprite ever sees its credential."""

    def create(self, name: str) -> None: ...

    def set_network_policy(self, name: str, rules: Sequence[Json]) -> None: ...

    def get_network_policy(self, name: str) -> Json: ...

    def set_memory_limit(self, name: str, limit_mb: int) -> None: ...

    def exec(
        self,
        name: str,
        argv: Sequence[str],
        stdin: bytes,
        timeout_s: float,
        first_byte_s: float | None = None,
    ) -> bytes:
        """Raises `StreamTimeoutError` when no output byte arrives within
        `first_byte_s` or the whole response takes longer than `timeout_s`."""
        ...

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

    def usage_lines(self) -> tuple[str, ...]:
        """One line per model call made (or refused), with cost."""
        ...


@dataclass(frozen=True)
class ReviewRequest:
    repo: str
    pr_number: int
    head_sha: str
    blocks: tuple[UntrustedBlock, ...]
    lenses: tuple[LoadedLens, ...] = ()
    lens_coverage: str = ""


@dataclass(frozen=True)
class PickRequest:
    """One lens-picker call: `instructions` is trusted controller text, and
    `blocks` carry the PR's paths and text as untrusted data."""

    repo: str
    pr_number: int
    head_sha: str
    instructions: str
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

    def pick(self, request: PickRequest) -> str:
        """The lens picker's raw reply: untrusted model output."""
        ...

    def prompt_tokens(self, request: ReviewRequest) -> int:
        """The input-token bound `review` would send for this request."""
        ...

    def usage_lines(self) -> tuple[str, ...]: ...
