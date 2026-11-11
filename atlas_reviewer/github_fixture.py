# SPDX-License-Identifier: MIT
"""Offline `GitHubReader` backed by a fixture directory (for `--dry-run`).

Layout: `pull.json`, `pull.diff`, `pull-commits.json`,
`issue-comments.json`, `review-comments.json` and `reviews.json` (arrays,
as GitHub serves them), `check-runs.json` (the runs at every commit;
`list_check_runs` serves those at one SHA), `workflow-runs.json` (every run
listed under the head branch's name; `list_workflow_runs_at` serves those at one SHA),
`jobs-<run_id>.json`, `job-log-<job_id>.txt`, `artifacts-<run_id>.json`,
`artifact-<id>/` (a directory zipped on read, as GitHub serves artifacts),
`issue-<n>.json`, `compare.json`, and a `source/` tree served as the
tarball at any SHA.
Each list file is one page (`truncated` is never set). A file that is
absent behaves like a GitHub 404; a download over its byte cap raises
`ResponseTooLargeError`, as the live client does.
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

from atlas_reviewer.ports import (
    BoundaryError,
    Json,
    Listing,
    NotFoundError,
    ResponseTooLargeError,
)


class FixtureGitHub:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.calls: list[tuple[str, ...]] = []

    def _file(self, name: str) -> Path:
        path = self._root / name
        if not path.is_file():
            raise NotFoundError(f"fixture {name} not found")
        return path

    def _json(self, name: str) -> Json:
        try:
            data = json.loads(self._file(name).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BoundaryError(f"fixture {name} is not JSON") from exc
        if not isinstance(data, dict):
            raise BoundaryError(f"fixture {name} is not an object")
        return data

    def _list(self, name: str, key: str) -> Listing:
        entries = self._json(name).get(key)
        if not isinstance(entries, list):
            raise BoundaryError(f"fixture {name} has no {key!r} array")
        return Listing(tuple(entries), truncated=False, pages_read=1)

    @staticmethod
    def _capped(data: bytes, max_bytes: int, what: str) -> bytes:
        if len(data) > max_bytes:
            raise ResponseTooLargeError(f"fixture {what} exceeded {max_bytes} bytes")
        return data

    def get_pull(self, repo: str, number: int) -> Json:
        self.calls.append(("get_pull", repo, str(number)))
        return self._json("pull.json")

    def get_pull_diff(self, repo: str, number: int) -> str:
        self.calls.append(("get_pull_diff", repo, str(number)))
        return self._file("pull.diff").read_text(encoding="utf-8")

    def _array(self, name: str) -> Listing:
        try:
            data = json.loads(self._file(name).read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise BoundaryError(f"fixture {name} is not JSON") from exc
        if not isinstance(data, list):
            raise BoundaryError(f"fixture {name} is not an array")
        return Listing(tuple(data), truncated=False, pages_read=1)

    def list_check_runs(self, repo: str, sha: str) -> Listing:
        """The check runs at `sha`, as GitHub lists them for one commit."""
        self.calls.append(("list_check_runs", repo, sha))
        runs = self._list("check-runs.json", "check_runs").items
        at = tuple(r for r in runs if isinstance(r, dict) and r.get("head_sha") == sha)
        return Listing(at, truncated=False, pages_read=1)

    def list_pull_commits(self, repo: str, number: int) -> Listing:
        self.calls.append(("list_pull_commits", repo, str(number)))
        return self._array("pull-commits.json")

    def list_issue_comments(self, repo: str, number: int) -> Listing:
        self.calls.append(("list_issue_comments", repo, str(number)))
        return self._array("issue-comments.json")

    def list_review_comments(self, repo: str, number: int) -> Listing:
        self.calls.append(("list_review_comments", repo, str(number)))
        return self._array("review-comments.json")

    def list_reviews(self, repo: str, number: int) -> Listing:
        self.calls.append(("list_reviews", repo, str(number)))
        return self._array("reviews.json")

    def get_compare(self, repo: str, base: str, head: str) -> Json:
        self.calls.append(("get_compare", repo, f"{base}...{head}"))
        return self._json("compare.json")

    def list_workflow_runs(self, repo: str, branch: str) -> Listing:
        self.calls.append(("list_workflow_runs", repo, branch))
        return self._list("workflow-runs.json", "workflow_runs")

    def list_workflow_runs_at(self, repo: str, sha: str) -> Listing:
        self.calls.append(("list_workflow_runs_at", repo, sha))
        runs = self._list("workflow-runs.json", "workflow_runs").items
        at = tuple(r for r in runs if isinstance(r, dict) and r.get("head_sha") == sha)
        return Listing(at, truncated=False, pages_read=1)

    def list_run_jobs(self, repo: str, run_id: int) -> Listing:
        self.calls.append(("list_run_jobs", repo, str(run_id)))
        return self._list(f"jobs-{run_id}.json", "jobs")

    def list_run_artifacts(self, repo: str, run_id: int) -> Listing:
        self.calls.append(("list_run_artifacts", repo, str(run_id)))
        return self._list(f"artifacts-{run_id}.json", "artifacts")

    def get_job_logs(self, repo: str, job_id: int, max_bytes: int) -> bytes:
        self.calls.append(("get_job_logs", repo, str(job_id)))
        data = self._file(f"job-log-{job_id}.txt").read_bytes()
        return self._capped(data, max_bytes, f"job log {job_id}")

    def download_artifact(self, repo: str, artifact_id: int, max_bytes: int) -> bytes:
        self.calls.append(("download_artifact", repo, str(artifact_id)))
        folder = self._root / f"artifact-{artifact_id}"
        if not folder.is_dir():
            raise NotFoundError(f"fixture artifact-{artifact_id}/ not found")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                zf.write(path, path.relative_to(folder).as_posix())
        return self._capped(buf.getvalue(), max_bytes, f"artifact {artifact_id}")

    def get_tarball(self, repo: str, sha: str) -> bytes:
        self.calls.append(("get_tarball", repo, sha))
        source = self._root / "source"
        if not source.is_dir():
            raise NotFoundError("fixture source/ not found")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            tf.add(source, arcname=f"{repo.replace('/', '-')}-{sha[:7]}")
        return buf.getvalue()

    def get_issue(self, repo: str, number: int) -> Json:
        self.calls.append(("get_issue", repo, str(number)))
        return self._json(f"issue-{number}.json")
