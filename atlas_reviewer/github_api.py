# SPDX-License-Identifier: MIT
"""Live, read-only GitHub REST adapter.

Only `GET` is ever sent. The token comes from a `TokenSource` (live: a
short-lived App installation token scoped to contents/checks/actions/
pull_requests read, plus issues read only with `--include-issues`).

Every list endpoint is followed through its `Link: rel="next"` pages up to
a hard page cap; a list cut off by the cap comes back `truncated`, and the
caller reports what it did not read. A `next` link pointing anywhere but
this API is refused, so the token is never sent to another host.
"""

from __future__ import annotations

import json
from urllib.parse import quote, urlsplit

from atlas_reviewer.http import REDIRECT_STATUSES, HttpResponse, Transport, safe_url
from atlas_reviewer.pagination import DEFAULT_MAX_PAGES, next_link
from atlas_reviewer.ports import (
    BoundaryError,
    Json,
    Listing,
    NotFoundError,
    TokenSource,
)

API_URL = "https://api.github.com"
_JSON = "application/vnd.github+json"
_DIFF = "application/vnd.github.diff"
_PER_PAGE = 100
_MAX_REDIRECTS = 3


class GitHubClient:
    def __init__(
        self,
        transport: Transport,
        tokens: TokenSource,
        api_url: str = API_URL,
        timeout_s: float = 30.0,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self._transport = transport
        self._tokens = tokens
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_pages = max_pages

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tokens.token()}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "code-quality-atlas-reviewer",
        }

    def _fetch(
        self, url: str, accept: str = _JSON, max_bytes: int | None = None
    ) -> HttpResponse:
        """Redirects within this API keep the request headers (a transferred
        repository); once the chain leaves the API, the token is dropped for
        the rest of it, so a pre-signed download never sees it."""
        headers = self._headers(accept)
        resp = self._transport.request(
            "GET", url, headers, None, self._timeout_s, max_bytes
        )
        for _ in range(_MAX_REDIRECTS):
            if resp.status not in REDIRECT_STATUSES:
                break
            location = resp.header("Location")
            if not location or urlsplit(location).scheme != "https":
                raise BoundaryError("GitHub redirect without an https Location")
            if not location.startswith(f"{self._api_url}/"):
                headers = {"User-Agent": "code-quality-atlas-reviewer"}
            resp = self._transport.request(
                "GET", location, headers, None, self._timeout_s, max_bytes
            )
        _check(resp, url)
        return resp

    def _get(
        self, path: str, accept: str = _JSON, max_bytes: int | None = None
    ) -> bytes:
        return self._fetch(f"{self._api_url}{path}", accept, max_bytes).body

    def _json(self, path: str) -> Json:
        return _object(self._get(path), path)

    def _list(self, path: str, key: str | None) -> Listing:
        """`key` names the array inside each page's object; None means the
        page is the array itself (as for a pull request's commits)."""
        url: str | None = f"{self._api_url}{path}"
        items: list[Json] = []
        pages = 0
        while url is not None and pages < self._max_pages:
            resp = self._fetch(url)
            entries = (
                _array(resp.body, path)
                if key is None
                else _object(resp.body, path).get(key)
            )
            if not isinstance(entries, list):
                raise BoundaryError(
                    f"GitHub list {path.split('?', 1)[0]} has no {key!r} array"
                )
            items.extend(entries)
            pages += 1
            url = self._same_api(next_link(resp.header("Link")))
        return Listing(tuple(items), truncated=url is not None, pages_read=pages)

    def _same_api(self, url: str | None) -> str | None:
        if url is None or url.startswith(f"{self._api_url}/"):
            return url
        raise BoundaryError(f"refusing a pagination link off the API: {safe_url(url)}")

    def get_pull(self, repo: str, number: int) -> Json:
        return self._json(f"/repos/{repo}/pulls/{number}")

    def get_pull_diff(self, repo: str, number: int) -> str:
        return self._get(f"/repos/{repo}/pulls/{number}", accept=_DIFF).decode(
            "utf-8", errors="replace"
        )

    def list_check_runs(self, repo: str, sha: str) -> Listing:
        return self._list(
            f"/repos/{repo}/commits/{sha}/check-runs?per_page={_PER_PAGE}",
            "check_runs",
        )

    def list_pull_commits(self, repo: str, number: int) -> Listing:
        """GitHub lists at most 250 commits of a pull request."""
        return self._list(
            f"/repos/{repo}/pulls/{number}/commits?per_page={_PER_PAGE}", None
        )

    def list_workflow_runs(self, repo: str, branch: str) -> Listing:
        return self._list(
            f"/repos/{repo}/actions/runs?per_page={_PER_PAGE}"
            f"&branch={quote(branch, safe='')}",
            "workflow_runs",
        )

    def list_workflow_runs_at(self, repo: str, sha: str) -> Listing:
        return self._list(
            f"/repos/{repo}/actions/runs?per_page={_PER_PAGE}"
            f"&head_sha={quote(sha, safe='')}",
            "workflow_runs",
        )

    def list_run_jobs(self, repo: str, run_id: int) -> Listing:
        return self._list(
            f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page={_PER_PAGE}", "jobs"
        )

    def list_run_artifacts(self, repo: str, run_id: int) -> Listing:
        return self._list(
            f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page={_PER_PAGE}",
            "artifacts",
        )

    def get_job_logs(self, repo: str, job_id: int, max_bytes: int) -> bytes:
        return self._get(
            f"/repos/{repo}/actions/jobs/{job_id}/logs", max_bytes=max_bytes
        )

    def download_artifact(self, repo: str, artifact_id: int, max_bytes: int) -> bytes:
        return self._get(
            f"/repos/{repo}/actions/artifacts/{artifact_id}/zip", max_bytes=max_bytes
        )

    def get_tarball(self, repo: str, sha: str) -> bytes:
        return self._get(f"/repos/{repo}/tarball/{sha}")

    def get_issue(self, repo: str, number: int) -> Json:
        return self._json(f"/repos/{repo}/issues/{number}")

    def list_issue_comments(self, repo: str, number: int) -> Listing:
        """A pull request's conversation comments; its issue number is its
        PR number."""
        return self._list(
            f"/repos/{repo}/issues/{number}/comments?per_page={_PER_PAGE}", None
        )

    def list_review_comments(self, repo: str, number: int) -> Listing:
        return self._list(
            f"/repos/{repo}/pulls/{number}/comments?per_page={_PER_PAGE}", None
        )

    def list_reviews(self, repo: str, number: int) -> Listing:
        return self._list(
            f"/repos/{repo}/pulls/{number}/reviews?per_page={_PER_PAGE}", None
        )


def _object(body: bytes, path: str) -> Json:
    path = path.split("?", 1)[0]
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BoundaryError(f"GitHub returned non-JSON for {path}") from exc
    if not isinstance(data, dict):
        raise BoundaryError(f"GitHub returned a non-object for {path}")
    return data


def _array(body: bytes, path: str) -> list[Json]:
    path = path.split("?", 1)[0]
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BoundaryError(f"GitHub returned non-JSON for {path}") from exc
    if not isinstance(data, list):
        raise BoundaryError(f"GitHub returned a non-array for {path}")
    return data


def _check(resp: HttpResponse, url: str) -> None:
    if resp.status == 404:
        raise NotFoundError(f"GitHub 404 for {safe_url(url)}")
    if not 200 <= resp.status < 300:
        raise BoundaryError(f"GitHub HTTP {resp.status} for {safe_url(url)}")
