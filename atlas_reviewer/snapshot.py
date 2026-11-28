# SPDX-License-Identifier: MIT
"""The read-only PR snapshot builder behind the parity anchors' eval
fixtures (issue #713's harness-parity slice E, the parity brief's S3).

`eval-run` reviews a recorded fixture; this module builds one from a pull
request as it stood at a recorded head (the anchor): the PR's fields with
the anchor's head SHA, the diff against the anchor's merge base, the
PR's commits up to the anchor, the reviews, review threads and
conversation comments posted before the anchor push, the CI evidence at
every retained commit with the jobs' logs where GitHub still serves
them, the head and merge-base trees, and the self-contained git history
bundle the staging's history fetch reads (`history.bundle`, its ref
`refs/heads/atlas-history` at the anchor head — the shape
`bridge_staging.upload_history_bundle` and the README's eval-fixture
section document; the eval loader that fills from it is the git-history
slice's wiring).

Network reads happen only in this build step, through a read-only
`SnapshotReader` (the shipped one shells out to `gh api`); everything the
fixtures carry is committed and offline afterward. The local-git side —
the ancestor set, the diff, the trees and the bundle — reads only the
repository the builder runs in.

Nothing here redacts: the fixture is the raw record, and the review path
redacts at read time, exactly as it redacts live GitHub responses.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from atlas_reviewer.ports import Json

# The log-download order and bounds mirror the review path's ingest caps
# (`gather.IngestConfig`): failing jobs first, then the anchor run's,
# then the rest, within a per-build count and byte bound.
FAILING_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "action_required", "cancelled"}
)
DEFAULT_MAX_LOGS = 20
DEFAULT_LOG_BYTES = 5 * 1024 * 1024
_PAGE = 100
_RAW_ACCEPT = "application/vnd.github.raw"


class SnapshotFetchError(RuntimeError):
    """One read-only GitHub read the build needed failed. A job log's
    read is the one the build tolerates (an expired log is simply
    absent); every other read fails the build, because a fixture that
    silently lacks its PR or its listings would review as something it
    is not."""


@dataclass(frozen=True)
class SnapshotSpec:
    """The anchor a fixture records. `cutoff` is an ISO-8601 instant: a
    remark posted at or after it is not in the fixture, because the
    reviewer the anchor records ran on the conversation as the anchor
    push left it. `body` overrides the PR's body when GitHub's current
    body is not the anchor-time one (GitHub does not expose body edit
    history; #661's round-5 body ships beside its parity key)."""

    repo: str
    pr_number: int
    head_sha: str
    base_sha: str
    branch: str
    cutoff: str
    body: str | None = None


class SnapshotReader(Protocol):
    """The three read-only shapes the build needs: one JSON object, one
    paginated listing, and raw bytes."""

    def get(self, path: str) -> Json: ...

    def items(self, path: str, key: str | None = None) -> list[Json]: ...

    def raw(self, path: str, *, accept: str | None = None) -> bytes: ...


@dataclass(frozen=True)
class SnapshotReport:
    """What one build wrote, for the manifest and the tests' provenance
    assertions."""

    files: tuple[str, ...]
    commits: int
    remarks: int
    check_runs: int
    workflow_runs: int
    job_logs: int


def git_commit_entry(repo_root: Path, sha: str) -> Json:
    """One commit as GitHub's pull-commits listing serves it, rebuilt
    from the commit object itself: the SHA, the full message, the
    committer date and the parents. The fields the review path parses
    are the record; nothing is invented."""
    raw = _git(
        repo_root, "show", "-s", "--format=%H%x0f%P%x0f%cI%x0f%B", "--no-patch", sha
    )
    sha_line, parents, date, message = raw.rstrip("\n").split("\x0f", 3)
    return {
        "sha": sha_line,
        "commit": {
            "message": message,
            "committer": {"date": date},
        },
        "parents": [{"sha": p} for p in parents.split()],
    }


def resolve_commits(
    repo_root: Path,
    spec: SnapshotSpec,
    listing: list[Json],
    ancestors: frozenset[str],
) -> tuple[list[Json], str]:
    """The PR's commits as they stood at the anchor, oldest first in
    history order: every commit `base..head` reaches. The current
    listing's entry is used where it covers a commit; a commit the
    branch later rebased away -- one the current listing no longer
    names at all -- is rebuilt from the commit object (`git_commit_entry`),
    the same fields GitHub serves. The returned source names which happened,
    for the manifest."""
    ordered = _git(
        repo_root, "rev-list", "--reverse", f"{spec.base_sha}..{spec.head_sha}"
    ).split()
    by_sha = {e["sha"]: e for e in listing if isinstance(e.get("sha"), str)}
    entries = []
    rebuilt = 0
    for sha in ordered:
        if sha not in ancestors:
            continue
        entry = by_sha.get(sha)
        if entry is None:
            entry = git_commit_entry(repo_root, sha)
            rebuilt += 1
        entries.append(entry)
    source = (
        "github-listing"
        if not rebuilt
        else (
            "github-listing+git-reconstructed"
            if rebuilt < len(entries)
            else "git-reconstructed"
        )
    )
    return entries, source


def _utc_z(instant: str) -> str:
    """One ISO-8601 instant in the shape GitHub's timestamps carry
    (`...Z`), whatever offset it was written with; a value that does not
    parse is returned unchanged, and the caller that owns the format
    fails loudly on it instead."""
    try:
        parsed = datetime.fromisoformat(instant)
    except ValueError:
        return instant
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def select_before(entries: list[Json], cutoff: str, field: str) -> list[Json]:
    """The remarks posted strictly before `cutoff`. The cutoff is
    normalized to UTC in GitHub's timestamp shape first (`...Z`), so the
    lexicographic comparison is within one format whatever offset the
    cutoff or the committer was written with -- an explicit `--cutoff`
    with a non-UTC offset must not read as a different instant than it
    names. An entry whose field is absent or null -- a pending review's
    missing `submitted_at` -- is kept: it is older than any instant, the
    same reading the conversation block's ordering gives it."""
    cutoff = _utc_z(cutoff)
    return [
        e
        for e in entries
        if not isinstance(e.get(field), str) or e.get(field, "") < cutoff
    ]


def write_snapshot(
    out: Path,
    spec: SnapshotSpec,
    *,
    pull: Json,
    diff: str,
    commits: list[Json],
    issue_comments: list[Json],
    reviews: list[Json],
    review_comments: list[Json],
    check_runs: list[Json],
    workflow_runs: list[Json],
    jobs: dict[int, list[Json]],
    artifacts: dict[int, list[Json]],
    logs: dict[int, bytes],
    default_branch: str,
    review_md: bytes,
    agents_md: bytes,
    diff_paths: int,
    commits_source: str,
    trees: dict[str, bytes],
    bundle: bytes,
) -> SnapshotReport:
    """Assemble and write the fixture directory. `trees` maps the
    recorded tarball file names to the exact bytes GitHub serves for
    that revision (`source.tar.gz` for the head tree,
    `source-<base7>.tar.gz` for the merge base's) — the bytes the live
    review's `get_tarball` would fetch, committed verbatim so the
    fixture carries no loose tree for the repo-wide content gates to
    re-lint. Everything else is the caller-fetched record, already
    filtered."""
    out.mkdir(parents=True, exist_ok=True)
    anchor_pull = dict(pull)
    head = dict(anchor_pull.get("head") or {})
    head["sha"] = spec.head_sha
    head["ref"] = spec.branch
    # The nested repository objects GitHub embeds under head/base carry
    # the repo's live counters (issue count, size, pushed_at), which move
    # on every rebuild; the loader reads only the SHAs and refs, so the
    # volatile copies are dropped and a rebuild stays byte-stable.
    head.pop("repo", None)
    anchor_pull["head"] = head
    base = dict(anchor_pull.get("base") or {})
    base.pop("repo", None)
    anchor_pull["base"] = base
    anchor_pull["changed_files"] = diff_paths
    if spec.body is not None:
        # A `--body-file` override is a body reconstructed offline (e.g.
        # #661's round-5 body), and the reconstruction file's leading
        # HTML comment is provenance for the fixture's human reader — it
        # names the graded finding and the deviations, so it must never
        # ride into the body the replayed reviewer reads. The body text
        # itself, its stale-CI citations included, is kept whole; the
        # provenance lives in the fixture's FIXTURE.md and in the parity
        # key's own copy of the file. A PR body that was never
        # overridden (the `pull.json` GitHub serves today) is recorded
        # verbatim, its own leading comments included.
        anchor_pull["body"] = _reconstructed_body(spec.body)

    _write_json(
        out / "event.json",
        {"repo": spec.repo, "pr_number": spec.pr_number, "head_sha": spec.head_sha},
    )
    _write_json(out / "pull.json", anchor_pull)
    (out / "pull.diff").write_text(diff, encoding="utf-8")
    _write_json(out / "pull-commits.json", commits)
    _write_json(out / "issue-comments.json", issue_comments)
    _write_json(out / "reviews.json", reviews)
    _write_json(out / "review-comments.json", review_comments)
    _write_json(
        out / "check-runs.json",
        {"total_count": len(check_runs), "check_runs": check_runs},
    )
    _write_json(
        out / "workflow-runs.json",
        {"total_count": len(workflow_runs), "workflow_runs": workflow_runs},
    )
    for run_id, entries in sorted(jobs.items()):
        _write_json(
            out / f"jobs-{run_id}.json",
            {"total_count": len(entries), "jobs": entries},
        )
    for run_id, entries in sorted(artifacts.items()):
        _write_json(
            out / f"artifacts-{run_id}.json",
            {"total_count": len(entries), "artifacts": entries},
        )
    for job_id, text in sorted(logs.items()):
        (out / f"job-log-{job_id}.txt").write_bytes(text)
    _write_json(out / "repository.json", {"default_branch": default_branch})
    _write_json(out / "compare.json", {"merge_base_commit": {"sha": spec.base_sha}})
    (out / "REVIEW.md").write_bytes(review_md)
    (out / "agents-md.txt").write_bytes(agents_md)
    (out / "history.bundle").write_bytes(bundle)
    # The merged loader's contract (`history_source.fixture_history`):
    # the bundle loads only when `history-base.txt` sits beside it, so
    # the manifest's merge base is written out verbatim -- without it the
    # eval would stage no history and report the named no-history gap
    # while still reading green.
    (out / "history-base.txt").write_text(f"{spec.base_sha}\n", encoding="utf-8")
    for name, data in trees.items():
        (out / name).write_bytes(data)
    _write_json(
        out / "snapshot.json",
        {
            "repo": spec.repo,
            "pr_number": spec.pr_number,
            "head_sha": spec.head_sha,
            "base_sha": spec.base_sha,
            "branch": spec.branch,
            "cutoff": spec.cutoff,
            "commits_source": commits_source,
            "counts": {
                "commits": len(commits),
                "issue_comments": len(issue_comments),
                "reviews": len(reviews),
                "review_comments": len(review_comments),
                "check_runs": len(check_runs),
                "workflow_runs": len(workflow_runs),
                "job_logs": len(logs),
            },
        },
    )
    files = tuple(sorted(p.name for p in out.iterdir()))
    return SnapshotReport(
        files=files,
        commits=len(commits),
        remarks=len(issue_comments) + len(reviews) + len(review_comments),
        check_runs=len(check_runs),
        workflow_runs=len(workflow_runs),
        job_logs=len(logs),
    )


def _reconstructed_body(body: str) -> str:
    """The replayed body an override file carries: the file's leading
    HTML comment block -- the reconstruction's provenance note for the
    fixture's human reader -- is removed, and everything after it is the
    body. A body whose first content is not an HTML comment, or whose
    comment never closes, is kept whole: the builder never guesses at
    where a provenance note ends."""
    stripped = body.lstrip()
    if not stripped.startswith("<!--"):
        return body
    end = stripped.find("-->")
    if end == -1:
        return body
    return stripped[end + len("-->") :].lstrip("\n")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# --- the GitHub side (the build step's network reads) ---


@dataclass(frozen=True)
class FetchedSnapshot:
    """Everything one GitHub read pass returned, already the shapes
    `write_snapshot` takes beside the CI gather."""

    pull: Json
    commits_all: list[Json]
    issue_comments: list[Json]
    reviews: list[Json]
    review_comments: list[Json]
    default_branch: str
    review_md: bytes
    agents_md: bytes
    head_tree: bytes
    base_tree: bytes


def fetch_snapshot(spec: SnapshotSpec, reader: SnapshotReader) -> FetchedSnapshot:
    """Read everything the fixture carries from GitHub, read-only. The
    default-branch `REVIEW.md` and `AGENTS.md` come from the default
    branch as it stands today (the owner's setup decision: setup uses
    today's default-branch REVIEW.md), not the anchor-time one; the two
    trees come as the exact tarball bytes GitHub serves for those
    revisions, which is what a live review's `get_tarball` fetches. The
    setup spec's `review_setup_files:` line's files are deliberately not
    recorded: the replayed setup phase would run the spec's install
    against a real package index, which the offline stage-0 contract
    cannot carry; the replay names the gap instead, and the fixture's
    FIXTURE.md documents the deviation."""
    pull = reader.get(f"repos/{spec.repo}/pulls/{spec.pr_number}")
    commits_all = reader.items(f"repos/{spec.repo}/pulls/{spec.pr_number}/commits")
    issue_comments = reader.items(f"repos/{spec.repo}/issues/{spec.pr_number}/comments")
    reviews = reader.items(f"repos/{spec.repo}/pulls/{spec.pr_number}/reviews")
    review_comments = reader.items(f"repos/{spec.repo}/pulls/{spec.pr_number}/comments")
    repository = reader.get(f"repos/{spec.repo}")
    branch = repository.get("default_branch")
    default_branch = branch if isinstance(branch, str) and branch else "main"
    review_md = reader.raw(
        f"repos/{spec.repo}/contents/REVIEW.md?ref={default_branch}",
        accept=_RAW_ACCEPT,
    )
    return FetchedSnapshot(
        pull=pull,
        commits_all=commits_all,
        issue_comments=issue_comments,
        reviews=reviews,
        review_comments=review_comments,
        default_branch=default_branch,
        review_md=review_md,
        agents_md=reader.raw(
            f"repos/{spec.repo}/contents/AGENTS.md?ref={default_branch}",
            accept=_RAW_ACCEPT,
        ),
        head_tree=reader.raw(f"repos/{spec.repo}/tarball/{spec.head_sha}"),
        base_tree=reader.raw(f"repos/{spec.repo}/tarball/{spec.base_sha}"),
    )


def collect_ci(
    spec: SnapshotSpec,
    reader: SnapshotReader,
    commits: list[Json],
    *,
    max_logs: int = DEFAULT_MAX_LOGS,
    log_bytes: int = DEFAULT_LOG_BYTES,
) -> tuple[
    list[Json],
    list[Json],
    dict[int, list[Json]],
    dict[int, list[Json]],
    dict[int, bytes],
]:
    """The CI record at the anchor: the check runs at every retained
    commit (deduplicated by id), the head branch's workflow runs at the
    retained commits, each run's jobs and artifact listing, and the jobs'
    logs where GitHub still serves them -- failing jobs first, then the
    anchor run's, then the rest, within the count and byte bounds. A log
    the fetch cannot read is simply absent: the review path records its
    own gap when a fixture run asks for it, the same named UNKNOWN a
    failed live fetch leaves."""
    shas = {c["sha"] for c in commits if isinstance(c.get("sha"), str)}
    check_runs: dict[int, Json] = {}
    for sha in sorted(shas):
        for run in reader.items(
            f"repos/{spec.repo}/commits/{sha}/check-runs", "check_runs"
        ):
            run_id = run.get("id")
            if isinstance(run_id, int):
                check_runs[run_id] = run
    workflow_runs = [
        run
        for run in reader.items(
            f"repos/{spec.repo}/actions/runs?branch={spec.branch}", "workflow_runs"
        )
        if run.get("head_sha") in shas
    ]
    jobs: dict[int, list[Json]] = {}
    artifacts: dict[int, list[Json]] = {}
    for run in workflow_runs:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        jobs[run_id] = reader.items(
            f"repos/{spec.repo}/actions/runs/{run_id}/jobs", "jobs"
        )
        artifacts[run_id] = reader.items(
            f"repos/{spec.repo}/actions/runs/{run_id}/artifacts", "artifacts"
        )
    logs = _logs(spec, reader, jobs, spec.head_sha, max_logs, log_bytes)
    return (
        sorted(check_runs.values(), key=lambda run: run["id"]),
        workflow_runs,
        jobs,
        artifacts,
        logs,
    )


def _logs(
    spec: SnapshotSpec,
    reader: SnapshotReader,
    jobs: dict[int, list[Json]],
    head_sha: str,
    max_logs: int,
    log_bytes: int,
) -> dict[int, bytes]:
    """Failing jobs first -- whatever run or commit they belong to,
    newest run first -- then the anchor run's remaining jobs, then the
    rest; the count cap stops the build, the byte cap bounds each read."""
    failing: list[int] = []
    anchor_jobs: list[int] = []
    rest: list[int] = []
    for run_id in sorted(jobs, reverse=True):
        for job in jobs[run_id]:
            job_id = job.get("id")
            if not isinstance(job_id, int):
                continue
            if job.get("conclusion") in FAILING_CONCLUSIONS:
                failing.append(job_id)
            elif job.get("head_sha") == head_sha:
                anchor_jobs.append(job_id)
            else:
                rest.append(job_id)
    wanted = list(dict.fromkeys([*failing, *anchor_jobs, *rest]))[:max_logs]
    logs: dict[int, bytes] = {}
    for job_id in wanted:
        try:
            raw = reader.raw(f"repos/{spec.repo}/actions/jobs/{job_id}/logs")
        except SnapshotFetchError:
            continue
        logs[job_id] = raw[:log_bytes]
    return logs


# --- the local-git side (no network) ---

# The repository-location overrides an operator's environment may carry:
# any of these would redirect the builder's `-C repo_root` subprocesses at
# another repository, index or object store, so every git subprocess runs
# without them. Everything else in the environment is inherited as the
# operator set it.
_REPO_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_GRAFT_FILE",
    "GIT_NAMESPACE",
)


def _git_env() -> dict[str, str]:
    """The environment the builder's git subprocesses run under: the
    caller's, minus the repository-location overrides above."""
    return {
        k: v for k, v in os.environ.items() if k not in _REPO_LOCATION_VARS
    }  # fmt: skip


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_git_env(),
    )
    return result.stdout


def git_ensure_commit(repo_root: Path, sha: str) -> None:
    """The anchor commits may sit on a merged-and-deleted branch; fetch
    the exact SHA when the checkout does not hold it (the build step's
    one git-side network read), and refuse when it is not served."""
    probe = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-t", sha],
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )
    if probe.returncode == 0 and probe.stdout.strip() == "commit":
        return
    subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", sha],
        capture_output=True,
        text=True,
        check=True,
        env=_git_env(),
    )


def git_ancestors(repo_root: Path, head_sha: str) -> frozenset[str]:
    """Every commit the anchor reaches, as one rev-list set."""
    return frozenset(_git(repo_root, "rev-list", head_sha).split())


def git_diff(repo_root: Path, base_sha: str, head_sha: str) -> str:
    """The PR's diff at the anchor: the merge-base diff, renames found,
    the same shape GitHub's PR diff endpoint serves."""
    return _git(repo_root, "diff", "--find-renames", f"{base_sha}...{head_sha}")


def git_diff_path_count(repo_root: Path, base_sha: str, head_sha: str) -> int:
    listing = _git(
        repo_root, "diff", "--find-renames", "--name-only", f"{base_sha}...{head_sha}"
    )
    return len({line for line in listing.splitlines() if line.strip()})


def git_cutoff(repo_root: Path, head_sha: str) -> str:
    """The cutoff the anchor push implies: the anchor commit's own
    committer date, converted to UTC in the shape GitHub's timestamps
    carry (`...Z`), so the `select_before` comparisons stay lexicographic
    within one format whatever offset the committer's machine wrote."""
    instant = _git(repo_root, "show", "-s", "--format=%cI", head_sha).strip()
    return _utc_z(instant)


def git_bundle(repo_root: Path, head_sha: str, dest: Path) -> None:
    """The self-contained history bundle the staging's history fetch
    reads: its ref `refs/heads/atlas-history` sits at the anchor head,
    with no prerequisite -- the staged repository's git is synthetic, so
    a bundle that assumed the base's objects could not be fetched there.
    The ref is the bundle command's own addressing need, not a change to
    the checkout: a ref the operator's repository already carries by
    that name is saved and restored to its own value after the build,
    and one that did not exist is deleted again -- the builder leaves
    the operator's refs exactly as it found them, whatever the bundle's
    outcome."""
    probe = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "refs/heads/atlas-history"],
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )  # fmt: skip
    preexisting = probe.stdout.strip() if probe.returncode == 0 else None
    _git(repo_root, "update-ref", "refs/heads/atlas-history", head_sha)
    try:
        subprocess.run(
            [
                "git", "-C", str(repo_root),
                "bundle", "create", str(dest), "refs/heads/atlas-history",
            ],
            capture_output=True,
            text=True,
            check=True,
            env=_git_env(),
        )  # fmt: skip
    finally:
        if preexisting is not None:
            _git(repo_root, "update-ref", "refs/heads/atlas-history", preexisting)
        else:
            _git(repo_root, "update-ref", "-d", "refs/heads/atlas-history")


class GhApiReader:
    """The shipped read-only `SnapshotReader`: `gh api` subprocesses with
    the operator's own GitHub auth, nothing written to the API. Job-log
    reads pass the bytes through verbatim; a failed read raises
    `SnapshotFetchError` for the caller to name or tolerate."""

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, capture_output=True, check=False)

    def get(self, path: str) -> Json:
        result = self._run(["gh", "api", path])
        if result.returncode != 0:
            raise SnapshotFetchError(
                f"gh api {path}: {result.stderr.decode(errors='replace').strip()}"
            )
        return json.loads(result.stdout.decode())

    def items(self, path: str, key: str | None = None) -> list[Json]:
        """The listing at `path`, paginated to exhaustion at 100 a page.
        `key` names the array inside an object-shaped listing
        (`check_runs`, `workflow_runs`, ...); without it the path is an
        array-shaped endpoint."""
        out: list[Json] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            result = self._run(
                ["gh", "api", f"{path}{separator}per_page={_PAGE}&page={page}"]
            )
            if result.returncode != 0:
                raise SnapshotFetchError(
                    f"gh api {path}: {result.stderr.decode(errors='replace').strip()}"
                )
            payload = json.loads(result.stdout.decode())
            entries = payload if key is None else _array_field(payload, key, path)
            if not isinstance(entries, list):
                raise SnapshotFetchError(
                    f"gh api {path}: page {page} is not the listing it claims"
                )
            out.extend(entries)
            if len(entries) < _PAGE:
                return out
            page += 1

    def raw(self, path: str, *, accept: str | None = None) -> bytes:
        argv = (
            ["gh", "api", "-H", f"Accept: {accept}", path]
            if accept is not None
            else ["gh", "api", path, "--allow-escape-sequences"]
        )
        result = self._run(argv)
        if result.returncode != 0:
            raise SnapshotFetchError(
                f"gh api {path}: {result.stderr.decode(errors='replace').strip()}"
            )
        return result.stdout


def _array_field(payload: object, key: str, path: str) -> object:
    if not isinstance(payload, dict):
        raise SnapshotFetchError(f"gh api {path}: expected an object holding {key!r}")
    return payload.get(key)
