# SPDX-License-Identifier: MIT
"""Live, read-only GitHub REST adapter.

Only `GET` is ever sent. The token is expected to be a GitHub App
installation token scoped to contents/checks/actions/pull_requests read
(plus issues read only if `--include-issues` is used). Only the first page
of each list endpoint is read.
"""

from __future__ import annotations

import json
from urllib.parse import quote, urlsplit

from atlas_reviewer.http import REDIRECT_STATUSES, HttpResponse, Transport, safe_url
from atlas_reviewer.ports import BoundaryError, Json, NotFoundError

API_URL = "https://api.github.com"
_JSON = "application/vnd.github+json"
_DIFF = "application/vnd.github.diff"


class GitHubClient:
    def __init__(
        self,
        transport: Transport,
        token: str,
        api_url: str = API_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self._transport = transport
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "code-quality-atlas-reviewer",
        }

    def _get(self, path: str, accept: str = _JSON) -> bytes:
        url = f"{self._api_url}{path}"
        resp = self._transport.request(
            "GET", url, self._headers(accept), None, self._timeout_s
        )
        if resp.status in REDIRECT_STATUSES:
            resp = self._follow_without_credentials(resp)
        return _checked(resp, url)

    def _follow_without_credentials(self, resp: HttpResponse) -> HttpResponse:
        location = resp.header("Location")
        if not location or urlsplit(location).scheme != "https":
            raise BoundaryError("GitHub redirect without an https Location")
        headers = {"User-Agent": "code-quality-atlas-reviewer"}
        return self._transport.request("GET", location, headers, None, self._timeout_s)

    def _json(self, path: str) -> Json:
        try:
            data = json.loads(self._get(path))
        except json.JSONDecodeError as exc:
            raise BoundaryError(f"GitHub returned non-JSON for {path}") from exc
        if not isinstance(data, dict):
            raise BoundaryError(f"GitHub returned a non-object for {path}")
        return data

    def get_pull(self, repo: str, number: int) -> Json:
        return self._json(f"/repos/{repo}/pulls/{number}")

    def get_pull_diff(self, repo: str, number: int) -> str:
        return self._get(f"/repos/{repo}/pulls/{number}", accept=_DIFF).decode(
            "utf-8", errors="replace"
        )

    def list_check_runs(self, repo: str, sha: str) -> Json:
        return self._json(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100")

    def list_workflow_runs(self, repo: str, branch: str) -> Json:
        return self._json(
            f"/repos/{repo}/actions/runs?event=pull_request&per_page=50&branch={quote(branch, safe='')}"
        )

    def list_run_artifacts(self, repo: str, run_id: int) -> Json:
        return self._json(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")

    def get_run_logs(self, repo: str, run_id: int) -> bytes:
        return self._get(f"/repos/{repo}/actions/runs/{run_id}/logs")

    def get_tarball(self, repo: str, sha: str) -> bytes:
        return self._get(f"/repos/{repo}/tarball/{sha}")

    def get_issue(self, repo: str, number: int) -> Json:
        return self._json(f"/repos/{repo}/issues/{number}")


def _checked(resp: HttpResponse, url: str) -> bytes:
    if resp.status == 404:
        raise NotFoundError(f"GitHub 404 for {safe_url(url)}")
    if not 200 <= resp.status < 300:
        raise BoundaryError(f"GitHub HTTP {resp.status} for {safe_url(url)}")
    return resp.body
