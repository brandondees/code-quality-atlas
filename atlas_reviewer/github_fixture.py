# SPDX-License-Identifier: MIT
"""Offline `GitHubReader` backed by a fixture directory (for `--dry-run`).

Layout: `pull.json`, `pull.diff`, `check-runs.json`, `workflow-runs.json`,
`artifacts-<run_id>.json`, `logs-<run_id>.txt` (zipped on read, as GitHub
serves logs), `issue-<n>.json`, and a `source/` tree served as the head-SHA
tarball. A file that is absent behaves like a GitHub 404.
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

from atlas_reviewer.ports import BoundaryError, Json, NotFoundError


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

    def get_pull(self, repo: str, number: int) -> Json:
        self.calls.append(("get_pull", repo, str(number)))
        return self._json("pull.json")

    def get_pull_diff(self, repo: str, number: int) -> str:
        self.calls.append(("get_pull_diff", repo, str(number)))
        return self._file("pull.diff").read_text(encoding="utf-8")

    def list_check_runs(self, repo: str, sha: str) -> Json:
        self.calls.append(("list_check_runs", repo, sha))
        return self._json("check-runs.json")

    def list_workflow_runs(self, repo: str, branch: str) -> Json:
        self.calls.append(("list_workflow_runs", repo, branch))
        return self._json("workflow-runs.json")

    def list_run_artifacts(self, repo: str, run_id: int) -> Json:
        self.calls.append(("list_run_artifacts", repo, str(run_id)))
        return self._json(f"artifacts-{run_id}.json")

    def get_run_logs(self, repo: str, run_id: int) -> bytes:
        self.calls.append(("get_run_logs", repo, str(run_id)))
        text = self._file(f"logs-{run_id}.txt").read_text(encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("job/1_run.txt", text)
        return buf.getvalue()

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
