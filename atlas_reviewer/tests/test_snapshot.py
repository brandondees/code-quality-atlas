# SPDX-License-Identifier: MIT
"""The PR snapshot builder, and the committed parity anchors' fixtures.

The pure assembly is tested against canned payloads; the committed
anchors are tested against the parity keys they serve; and each anchor
runs the real `eval-run` driver end to end, offline, with the scripted
reviewer -- the stage-0 check the parity brief's slice S3 asks for: the
live context builders, the coordinator, the draft and the run file all
over the recorded snapshot, spending nothing."""

import io
import json
import subprocess
from pathlib import Path

import pytest

from atlas_reviewer import cli
from atlas_reviewer.github_fixture import FixtureGitHub
from atlas_reviewer.snapshot import (
    GhApiReader,
    SnapshotFetchError,
    SnapshotSpec,
    resolve_commits,
    select_before,
    write_snapshot,
)
from atlas_reviewer.tests.helpers import FIXTURE

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PR640 = REPO_ROOT / "atlas_reviewer" / "fixtures" / "pr640"
PR661 = REPO_ROOT / "atlas_reviewer" / "fixtures" / "pr661"
SAMPLE_SCENARIOS = FIXTURE / "scenarios"

HEAD_640 = "0fe45e5ea79f3abd8e07488a01b623186df96692"
BASE_640 = "771925a538d6744b6017175e8fe5f170abf27a6d"
HEAD_661 = "28854775e5965eb554b368cc3a543969a635b681"
BASE_661 = "f82b4bf18b252daf76759f21d2b09ed4f09d39c9"


# --- the pure assembly ---


def test_select_before_keeps_strictly_older_and_keeps_a_pending_remark():
    entries = [
        {"id": 1, "created_at": "2026-11-13T19:32:00Z"},
        {"id": 2, "created_at": "2026-11-13T19:33:07Z"},
        {"id": 3, "created_at": "2026-11-13T19:33:08Z"},
        {"id": 4},
    ]
    kept = select_before(entries, "2026-11-13T19:33:07Z", "created_at")
    assert [e["id"] for e in kept] == [1, 4]
    # A pending review has no submitted_at yet: it reads as older than
    # any instant and is kept, whatever the cutoff.
    assert select_before(entries, "2026-11-13T19:33:07Z", "submitted_at") == entries


def _seed_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)

    def git(*args, **kwargs):
        return subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (path / "a.txt").write_text("one\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").strip()
    (path / "b.txt").write_text("two\n")
    git("add", "-A")
    git("commit", "-qm", "first\n\nthe body")
    first = git("rev-parse", "HEAD").strip()
    (path / "c.txt").write_text("three\n")
    git("add", "-A")
    git("commit", "-qm", "second")
    head = git("rev-parse", "HEAD").strip()
    return base, first, head


def test_resolve_commits_prefers_the_listing_and_rebuilds_what_it_lost(tmp_path):
    """The anchor lineage is `base..head` in history order; the current
    listing's entry is used where it covers a commit, and a commit the
    branch rebased away -- absent from the listing -- is rebuilt from
    the commit object in the listing's shape."""
    base, first, head = _seed_repo(tmp_path)
    spec = SnapshotSpec("o/r", 1, head, base, "b", "2026-01-01T00:00:00Z")
    listing = [
        {
            "sha": first,
            "commit": {"message": "first\n\nthe body", "committer": {"date": "x"}},
            "parents": [{"sha": base}],
        }
    ]
    ancestors = frozenset(
        subprocess.run(
            ["git", "-C", str(tmp_path), "rev-list", head],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )
    commits, source = resolve_commits(tmp_path, spec, listing, ancestors)
    assert [c["sha"] for c in commits] == [first, head]
    assert source == "github-listing+git-reconstructed"
    assert commits[0] == listing[0]
    rebuilt = commits[1]
    assert rebuilt["sha"] == head
    assert rebuilt["commit"]["message"] == "second"
    assert rebuilt["commit"]["committer"]["date"]
    assert rebuilt["parents"] == [{"sha": first}]
    # A lineage the listing still covers whole needs no rebuild.
    commits2, source2 = resolve_commits(
        tmp_path,
        spec,
        listing * 0
        + [
            {
                "sha": first,
                "commit": {"message": "first\n\nthe body", "committer": {"date": "x"}},
                "parents": [{"sha": base}],
            },
            {
                "sha": head,
                "commit": {"message": "second", "committer": {"date": "y"}},
                "parents": [{"sha": first}],
            },
        ],
        ancestors,
    )
    assert [c["sha"] for c in commits2] == [first, head]
    assert source2 == "github-listing"


def _write(tmp_path: Path, spec: SnapshotSpec, **overrides) -> object:
    pull = {
        "number": spec.pr_number,
        "title": "t",
        "body": "github body",
        "user": {"login": "u"},
        "head": {"sha": "f" * 40, "ref": "later-branch"},
        "base": {"ref": "main"},
        "changed_files": 99,
        "labels": [],
        "requested_reviewers": [],
        "requested_teams": [],
        "draft": False,
    }
    kwargs = {
        "pull": pull,
        "diff": "diff --git a/x b/x",
        "commits": [{"sha": spec.head_sha, "commit": {"message": "m"}, "parents": []}],
        "issue_comments": [],
        "reviews": [],
        "review_comments": [],
        "check_runs": [{"id": 1, "head_sha": spec.head_sha, "name": "gate"}],
        "workflow_runs": [{"id": 5, "head_sha": spec.head_sha, "name": "ci"}],
        "jobs": {5: [{"id": 7, "head_sha": spec.head_sha, "name": "gate"}]},
        "artifacts": {5: []},
        "logs": {7: b"log"},
        "default_branch": "main",
        "review_md": b"setup spec",
        "agents_md": b"guidelines",
        "diff_paths": 1,
        "commits_source": "github-listing",
        "trees": {
            "source.tar.gz": b"head tarball",
            f"source-{spec.base_sha[:7]}.tar.gz": b"base tarball",
        },
        "bundle": b"bundle",
    }
    kwargs.update(overrides)
    return write_snapshot(tmp_path, spec, **kwargs)


def test_write_snapshot_writes_the_documented_fixture_shape(tmp_path):
    """The files the loader reads, each in the loader's own shape: the
    event, the anchor-headed pull, the diff, the filtered listings, the
    CI records, the setup files, the trees, the bundle, and the
    manifest."""
    spec = SnapshotSpec(
        "o/r", 7, "a" * 40, "b" * 40, "branch", "2026-01-01T00:00:00Z",
        body="anchor body",
    )  # fmt: skip
    report = _write(tmp_path / "fx", spec)
    names = report.files
    for name in (
        "event.json", "pull.json", "pull.diff", "pull-commits.json",
        "issue-comments.json", "reviews.json", "review-comments.json",
        "check-runs.json", "workflow-runs.json", "jobs-5.json",
        "artifacts-5.json", "job-log-7.txt", "repository.json",
        "compare.json", "REVIEW.md", "agents-md.txt",
        "source.tar.gz", "source-bbbbbbb.tar.gz",
        "history.bundle", "snapshot.json",
    ):  # fmt: skip
        assert name in names, names
    pull = json.loads((tmp_path / "fx" / "pull.json").read_text())
    assert pull["head"]["sha"] == spec.head_sha
    assert pull["head"]["ref"] == "branch"
    assert pull["body"] == "anchor body"
    assert pull["changed_files"] == 1
    assert json.loads((tmp_path / "fx" / "event.json").read_text()) == {
        "repo": "o/r",
        "pr_number": 7,
        "head_sha": spec.head_sha,
    }
    assert json.loads((tmp_path / "fx" / "compare.json").read_text()) == {
        "merge_base_commit": {"sha": spec.base_sha}
    }
    assert (
        json.loads((tmp_path / "fx" / "check-runs.json").read_text())["total_count"]
        == 1
    )
    assert (tmp_path / "fx" / "job-log-7.txt").read_bytes() == b"log"
    assert (tmp_path / "fx" / "history.bundle").read_bytes() == b"bundle"
    assert (tmp_path / "fx" / "source.tar.gz").read_bytes() == b"head tarball"
    assert (tmp_path / "fx" / "source-bbbbbbb.tar.gz").read_bytes() == b"base tarball"
    manifest = json.loads((tmp_path / "fx" / "snapshot.json").read_text())
    assert manifest["counts"]["commits"] == 1
    assert manifest["commits_source"] == "github-listing"


def test_the_gh_reader_paginates_and_names_a_failed_read():
    class FakeGh:
        def __init__(self, pages):
            self.pages = pages
            self.calls = []

        def _run(self, argv):
            self.calls.append(argv)
            page = self.pages[len(self.calls) - 1]
            return subprocess.CompletedProcess(argv, 0, json.dumps(page).encode(), b"")

    fake = FakeGh([[{"id": i} for i in range(100)], [{"id": 100}]])

    class Reader(GhApiReader):
        def __init__(self, fake):
            self.fake = fake

        def _run(self, argv):
            return self.fake._run(argv)

    out = Reader(fake).items("repos/o/r/pulls/1/commits")
    assert [e["id"] for e in out] == [*range(100), 100]
    assert all("per_page=100" in argv[2] for argv in fake.calls)

    class Broken(GhApiReader):
        def _run(self, argv):
            return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    with pytest.raises(SnapshotFetchError, match="boom"):
        Broken().get("repos/o/r")


# --- the committed parity anchors' fixtures ---


@pytest.mark.parametrize(
    "fixture_dir,pr,head,base",
    [
        pytest.param(PR640, 640, HEAD_640, BASE_640, id="pr640"),
        pytest.param(PR661, 661, HEAD_661, BASE_661, id="pr661"),
    ],
)
def test_the_committed_anchor_fixture_carries_the_documented_snapshot(
    fixture_dir: Path, pr: int, head: str, base: str
):
    """The fixture is the loader's own shape and the anchor the parity
    key grades: the event names the anchor head, the pull matches it,
    the trees and the diff exist, the history bundle's ref is the
    anchor, and the setup files came from today's default branch."""
    manifest = json.loads((fixture_dir / "snapshot.json").read_text())
    assert manifest["head_sha"] == head
    assert manifest["base_sha"] == base
    assert manifest["counts"]["commits"] > 0
    assert manifest["counts"]["check_runs"] > 0
    assert manifest["counts"]["workflow_runs"] > 0
    event = json.loads((fixture_dir / "event.json").read_text())
    assert event["pr_number"] == pr
    assert event["head_sha"] == head
    pull = json.loads((fixture_dir / "pull.json").read_text())
    assert pull["head"]["sha"] == head
    assert (fixture_dir / "pull.diff").read_text().startswith("diff --git ")
    head_tarball = fixture_dir / "source.tar.gz"
    base_tarball = fixture_dir / f"source-{base[:7]}.tar.gz"
    assert head_tarball.is_file() and head_tarball.stat().st_size > 1_000_000
    assert base_tarball.is_file() and base_tarball.stat().st_size > 1_000_000
    assert (fixture_dir / "REVIEW.md").is_file()
    assert (fixture_dir / "agents-md.txt").is_file()
    bundle_heads = subprocess.run(
        ["git", "bundle", "list-heads", str(fixture_dir / "history.bundle")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"{head} refs/heads/atlas-history" in bundle_heads


def test_the_640_fixture_serves_the_anchor_through_the_loader():
    """The fixture reads as GitHub would answer at the anchor: the check
    runs listed at the anchor SHA are the snapshot's, the remarks carry
    the prior rounds, the merge-base compare resolves to the base the
    diff is against, and the trees are the tarball bytes GitHub served,
    served verbatim at their SHAs."""
    repo = "brandondees/code-quality-atlas"
    gh = FixtureGitHub(PR640)
    listing = gh.list_check_runs(repo, HEAD_640)
    assert any(
        run.get("name") == "gate" and run.get("conclusion") == "success"
        for run in listing.items
    )
    reviews = gh.list_reviews(repo, 640)
    assert reviews.items
    compare = gh.get_compare(repo, "main", HEAD_640)
    assert compare["merge_base_commit"]["sha"] == BASE_640
    assert gh.get_tarball(repo, HEAD_640) == (PR640 / "source.tar.gz").read_bytes()
    assert (
        gh.get_tarball(repo, BASE_640)
        == (PR640 / f"source-{BASE_640[:7]}.tar.gz").read_bytes()
    )


# --- the builder command, offline through a fake reader ---


class _FakeRouteReader(GhApiReader):
    """A `SnapshotReader` that answers every read from a route table, so
    the `snapshot-build` command's own wiring runs offline: the git side
    (ancestors, diff, trees, bundle) is real, the GitHub side is this."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes

    def _path(self, path: str) -> object:
        for prefix in sorted(self.routes, key=len, reverse=True):
            if path == prefix or path.startswith(prefix):
                return self.routes[prefix]
        raise SnapshotFetchError(f"no route for {path}")

    def get(self, path: str) -> object:
        return self._path(path)

    def items(self, path: str, key: str | None = None) -> list[object]:
        payload = self._path(path)
        if key is not None:
            payload = payload[key]
        return payload

    def raw(self, path: str, *, accept: str | None = None) -> bytes:
        return self._path(path)


def test_the_snapshot_build_command_writes_the_fixture_offline(tmp_path, monkeypatch):
    """The real `snapshot-build` handler over a seeded local repo and a
    routed fake reader: the fixture lands complete, the pull is
    anchor-headed, the diff and trees come from the local git, the
    bundle's ref is the anchor head, and the report names the counts --
    a silent hole in any of those reads would review as something the
    PR is not."""
    base, first, head = _seed_repo(tmp_path / "seed")
    spec_repo = "o/r"
    monkeypatch.setattr(
        cli,
        "GhApiReader",
        lambda: _FakeRouteReader(
            {
                f"repos/{spec_repo}/pulls/9": {
                    "number": 9,
                    "title": "t",
                    "body": "github body",
                    "user": {"login": "u"},
                    "head": {"sha": "f" * 40, "ref": "branch"},
                    "base": {"ref": "main"},
                    "changed_files": 99,
                    "draft": False,
                },
                f"repos/{spec_repo}/pulls/9/commits": [],
                f"repos/{spec_repo}/pulls/9/reviews": [],
                f"repos/{spec_repo}/pulls/9/comments": [],
                f"repos/{spec_repo}/issues/9/comments": [],
                f"repos/{spec_repo}": {"default_branch": "main"},
                f"repos/{spec_repo}/contents/REVIEW.md?ref=main": b"setup",
                f"repos/{spec_repo}/contents/AGENTS.md?ref=main": b"guide",
                f"repos/{spec_repo}/commits/": {"check_runs": []},
                f"repos/{spec_repo}/actions/runs": {"workflow_runs": []},
                f"repos/{spec_repo}/tarball/{head}": b"head tarball bytes",
                f"repos/{spec_repo}/tarball/{base}": b"base tarball bytes",
            }
        ),
    )
    out = tmp_path / "fixture"
    out_err = io.StringIO()
    out_io = io.StringIO()
    code = cli.main(
        [
            "snapshot-build",
            "--repo",
            spec_repo,
            "--pr",
            "9",
            "--head-sha",
            head,
            "--base-sha",
            base,
            "--branch",
            "branch",
            "--cutoff",
            "2026-01-01T00:00:00Z",
            "--out",
            str(out),
            "--repo-root",
            str(tmp_path / "seed"),
        ],
        env={},
        out=out_io,
        err=out_err,
    )
    assert code == cli.EXIT_OK, out_err.getvalue()
    assert "snapshot written to" in out_io.getvalue()
    assert json.loads((out / "event.json").read_text())["head_sha"] == head
    assert json.loads((out / "pull.json").read_text())["head"]["sha"] == head
    assert "b.txt" in (out / "pull.diff").read_text()
    commits = json.loads((out / "pull-commits.json").read_text())
    assert [c["sha"] for c in commits] == [first, head]
    bundle_heads = subprocess.run(
        ["git", "bundle", "list-heads", str(out / "history.bundle")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"{head} refs/heads/atlas-history" in bundle_heads
    assert (out / "source.tar.gz").read_bytes() == b"head tarball bytes"
    assert (out / f"source-{base[:7]}.tar.gz").read_bytes() == b"base tarball bytes"


# --- the stage-0 runs: the real driver over the committed anchors ---
def _eval_run(tmp_path: Path, fixture_dir: Path, run_file: Path) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "eval-run",
            "--fixture",
            str(fixture_dir),
            "--lenses",
            "owners",
            "--lens-script",
            str(SAMPLE_SCENARIOS / "approve.json"),
            "--out",
            str(tmp_path / "draft.md"),
            "--run-file",
            str(run_file),
        ],
        env={},
        out=out,
        err=err,
    )
    return code, err.getvalue()


@pytest.mark.parametrize("fixture_dir", [PR640, PR661])
def test_the_anchor_fixture_runs_offline_through_eval_run(tmp_path, fixture_dir):
    """The offline stage-0 (the parity brief's slice E criterion): the
    real `eval-run` over the committed anchor, the scripted reviewer
    standing in for the model, the in-memory runner standing in for the
    Sprite -- the review completes, coverage is complete, and the run
    file the eval-parity gate scores is written. The staged copy's
    `pytest --co` collection probe ran against the anchor's own tree on
    the way."""
    run_file = tmp_path / f"{fixture_dir.name}-run.json"
    code, err = _eval_run(tmp_path, fixture_dir, run_file)
    assert code == cli.EXIT_OK, err
    payload = json.loads(run_file.read_text())
    assert payload["coverage_complete"] is True
    assert payload["lenses_not_run"] == [] and payload["lenses_failed"] == []
    assert payload["findings"] == []
    assert payload["head_sha"] == (
        HEAD_640 if fixture_dir.name == "pr640" else HEAD_661
    )
