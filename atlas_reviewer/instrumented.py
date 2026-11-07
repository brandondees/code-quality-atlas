# SPDX-License-Identifier: MIT
"""A `GitHubReader` wrapper that records every read as a telemetry event.

Step labels use only controller-side identifiers (PR, run, job and artifact
numbers), never untrusted strings such as branch names, and a failed read
re-raises with its label and timing (see `Telemetry.span`).
"""

from __future__ import annotations

from collections.abc import Callable

from atlas_reviewer.ports import GitHubReader, Json, Listing
from atlas_reviewer.telemetry import Fields, Telemetry

EVIDENCE, SOURCE = "evidence fetch", "source fetch"


def _listing(result: Listing) -> Fields:
    return {
        "items": len(result.items),
        "pages": result.pages_read,
        "truncated": result.truncated,
    }


def _size(result: bytes | str) -> Fields:
    return {"bytes" if isinstance(result, bytes) else "chars": len(result)}


class InstrumentedGitHub:
    def __init__(self, inner: GitHubReader, telemetry: Telemetry) -> None:
        self._inner = inner
        self._t = telemetry

    def _read[T](
        self,
        step: str,
        fn: Callable[[], T],
        after: Callable[[T], Fields],
        phase: str = EVIDENCE,
    ) -> T:
        return self._t.span(phase, step, fn, after=after)

    def get_pull(self, repo: str, number: int) -> Json:
        return self._read(
            f"pull #{number}", lambda: self._inner.get_pull(repo, number), lambda _: {}
        )

    def get_pull_diff(self, repo: str, number: int) -> str:
        return self._read(
            f"diff of #{number}", lambda: self._inner.get_pull_diff(repo, number), _size
        )

    def list_check_runs(self, repo: str, sha: str) -> Listing:
        return self._read(
            "check runs", lambda: self._inner.list_check_runs(repo, sha), _listing
        )

    def list_workflow_runs(self, repo: str, branch: str) -> Listing:
        return self._read(
            "workflow runs",
            lambda: self._inner.list_workflow_runs(repo, branch),
            _listing,
        )

    def list_run_jobs(self, repo: str, run_id: int) -> Listing:
        return self._read(
            f"jobs of run {run_id}",
            lambda: self._inner.list_run_jobs(repo, run_id),
            _listing,
        )

    def list_run_artifacts(self, repo: str, run_id: int) -> Listing:
        return self._read(
            f"artifacts of run {run_id}",
            lambda: self._inner.list_run_artifacts(repo, run_id),
            _listing,
        )

    def get_job_logs(self, repo: str, job_id: int, max_bytes: int) -> bytes:
        return self._read(
            f"log of job {job_id}",
            lambda: self._inner.get_job_logs(repo, job_id, max_bytes),
            _size,
        )

    def download_artifact(self, repo: str, artifact_id: int, max_bytes: int) -> bytes:
        return self._read(
            f"artifact {artifact_id}",
            lambda: self._inner.download_artifact(repo, artifact_id, max_bytes),
            _size,
        )

    def get_tarball(self, repo: str, sha: str) -> bytes:
        return self._read(
            f"tarball of {sha[:12]}",
            lambda: self._inner.get_tarball(repo, sha),
            _size,
            SOURCE,
        )

    def get_issue(self, repo: str, number: int) -> Json:
        return self._read(
            f"issue #{number}",
            lambda: self._inner.get_issue(repo, number),
            lambda _: {},
        )
