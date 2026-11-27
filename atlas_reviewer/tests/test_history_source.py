# SPDX-License-Identifier: MIT
"""The controller's history acquisition: the bundle built from the pull
request's real commits, the fixture loader, and the wiring that carries
them into the runner."""

import subprocess
from pathlib import Path

import pytest

from atlas_reviewer.history_source import (
    FETCH_FAILED,
    FETCH_TIMED_OUT,
    HEAD_MOVED,
    OVER_CAP,
    TIMED_OUT,
    HistoryBundle,
    bundle_from_repository,
    fixture_history,
)

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _repo_with_history(path: Path) -> tuple[str, str, str]:
    """A real repository with base <- mid <- head, and the SHAs of the
    merge-base (base) and the head: the pull request's own shape."""
    path.mkdir(parents=True)
    env = {**ENV, "GIT_CONFIG_GLOBAL": "/dev/null"}

    def git(*argv: str) -> str:
        return subprocess.run(
            ["git", *argv],
            cwd=path,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    (path / "calc.py").write_text("def total(xs):\n    return sum(xs)\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (path / "calc.py").write_text("def total(xs):\n    return sum(xs)  # mid\n")
    git("add", "-A")
    git("commit", "-qm", "mid")
    head = git("rev-parse", "HEAD")
    return base, head, "main"


def test_the_bundle_carries_the_prs_history_and_its_merge_base(tmp_path):
    """The bundle is built from the pull request's real head ref: the
    fetched tip is verified against the review's own provenance SHA, the
    bundle's ref is the name the staging's fetch step expects, and the
    base it carries is the merge-base the diff was built against -- an
    ancestor the bundle's own history includes."""
    origin = tmp_path / "origin.git"
    base, head, _branch = _repo_with_history(tmp_path / "work")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(tmp_path / "work"), str(origin)],
        check=True,
    )
    bundle = bundle_from_repository(
        str(origin), "refs/heads/main", head, base, tmp_path / "work"
    )
    assert bundle is not None
    assert bundle.base_sha == base
    # The bundle names its ref the way the staging's fetch expects, and
    # its ancestry carries the merge-base: clone it and read.
    check = tmp_path / "check"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "work"), str(check)], check=True
    )
    staged = tmp_path / "staged.bundle"
    staged.write_bytes(bundle.bundle)
    fetched = subprocess.run(
        [
            "git",
            "--git-dir",
            str(check / ".git"),
            "fetch",
            "-q",
            str(staged),
            "refs/heads/atlas-history:refs/atlas-history/head",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fetched.returncode == 0, fetched.stderr
    got = subprocess.run(
        [
            "git",
            "--git-dir",
            str(check / ".git"),
            "rev-parse",
            "refs/atlas-history/head",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert got == head
    contains = subprocess.run(
        [
            "git",
            "--git-dir",
            str(check / ".git"),
            "merge-base",
            "--is-ancestor",
            base,
            got,
        ],
        capture_output=True,
        check=False,
    )
    assert contains.returncode == 0


def test_a_head_that_does_not_match_the_provenance_acquires_nothing(tmp_path):
    """The fetched tip must be the SHA the review is about: a ref that
    moved (a push landing between the trees' fetch and the bundle's)
    acquires nothing, and the review keeps the named gap."""
    origin = tmp_path / "origin.git"
    base, head, branch = _repo_with_history(tmp_path / "work")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(tmp_path / "work"), str(origin)],
        check=True,
    )
    # The remote's ref moves past the head the review is about.
    subprocess.run(
        ["git", "commit", "-qm", "moved", "--allow-empty"],
        cwd=tmp_path / "work",
        check=True,
        env={**ENV, "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    subprocess.run(
        ["git", "push", "-q", str(origin), branch], cwd=tmp_path / "work", check=True
    )
    reasons = []
    bundle = bundle_from_repository(
        str(origin), f"refs/heads/{branch}", head, base, tmp_path / "work",
        note=reasons.append,
    )  # fmt: skip
    assert bundle is None
    assert reasons == [HEAD_MOVED]


def test_an_over_cap_bundle_acquires_nothing(tmp_path):
    """A bundle over the runner's cap is the named no-history gap: the
    acquisition returns None instead of handing the staging a bundle it
    will refuse."""
    origin = tmp_path / "origin.git"
    base, head, _branch = _repo_with_history(tmp_path / "work")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(tmp_path / "work"), str(origin)],
        check=True,
    )
    reasons = []
    bundle = bundle_from_repository(
        str(origin), "refs/heads/main", head, base, tmp_path / "work", cap=1,
        note=reasons.append,
    )  # fmt: skip
    assert bundle is None
    assert reasons == [OVER_CAP]


def test_a_failed_fetch_acquires_nothing(tmp_path):
    origin = tmp_path / "missing.git"
    _base, head, _branch = _repo_with_history(tmp_path / "work")
    reasons = []
    assert (
        bundle_from_repository(
            str(origin),
            "refs/heads/main",
            head,
            head,
            tmp_path / "work",
            note=reasons.append,
        )
        is None
    )
    assert reasons == [FETCH_FAILED]


def test_the_token_rides_the_environment_and_never_the_command_line(tmp_path):
    """The fetch's credential is process-environment config
    (GIT_CONFIG_COUNT extra-header plumbing): no git call's argv carries
    the token, and the authenticated fetch still succeeds against a real
    local origin -- the plumbing works, not just the redaction (round 1
    of #860, security)."""
    origin = tmp_path / "origin.git"
    base, head, _branch = _repo_with_history(tmp_path / "work")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(tmp_path / "work"), str(origin)],
        check=True,
    )
    seen: list[tuple[tuple[str, ...], dict | None]] = []
    real_run = subprocess.run

    def run(argv, **kw):
        seen.append((tuple(argv), kw.get("env")))
        return real_run(argv, **kw)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(subprocess, "run", run)
    # An unrelated controller credential must not reach the git children
    # (round 2 of #860): the env is an allowlist, not the whole
    # environment -- and the prompt pin is set, so a credential prompt
    # can never hang the fetch until its timeout.
    monkey.setenv("ATLAS_CONTROLLER_SECRET", "do-not-leak")
    try:
        bundle = bundle_from_repository(
            str(origin),
            "refs/heads/main",
            head,
            base,
            tmp_path / "work",
            token="secret-installation-token",
        )
    finally:
        monkey.undo()
    assert bundle is not None
    for argv, env in seen:
        assert "secret-installation-token" not in " ".join(argv)
        assert "ATLAS_CONTROLLER_SECRET" not in env
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert "PATH" in env
    fetch = next(env for argv, env in seen if "fetch" in argv)
    assert fetch["GIT_CONFIG_COUNT"] == "1"
    assert fetch["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert fetch["GIT_CONFIG_VALUE_0"] == (
        "Authorization: token secret-installation-token"
    )


def test_a_timed_out_fetch_acquires_nothing(tmp_path, monkeypatch):
    """Every git call is bounded: a fetch that runs past its bound is
    killed and acquires nothing, with the coarse reason noted -- a
    stalled network costs the review a bounded wait, never an indefinite
    one (round 1 of #860, resilience)."""
    import atlas_reviewer.history_source as hs

    _base, head, _branch = _repo_with_history(tmp_path / "work")
    real_run = subprocess.run

    def run(argv, **kw):
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)
        return real_run(argv, **kw)

    monkeypatch.setattr(hs.subprocess, "run", run)
    reasons = []
    assert (
        bundle_from_repository(
            str(tmp_path / "missing.git"),
            "refs/heads/main",
            head,
            head,
            tmp_path / "work",
            note=reasons.append,
        )
        is None
    )
    assert reasons == [FETCH_TIMED_OUT]


def test_a_timed_out_local_git_call_acquires_nothing(tmp_path, monkeypatch):
    """The local calls -- the bundle build among them -- are bounded the
    same way: a wedged git that never finishes is killed and acquires
    nothing, noted."""
    import atlas_reviewer.history_source as hs

    origin = tmp_path / "origin.git"
    base, head, _branch = _repo_with_history(tmp_path / "work")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(tmp_path / "work"), str(origin)],
        check=True,
    )
    real_run = subprocess.run

    def run(argv, **kw):
        if "bundle" in argv:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)
        return real_run(argv, **kw)

    monkeypatch.setattr(hs.subprocess, "run", run)
    reasons = []
    assert (
        bundle_from_repository(
            str(origin),
            "refs/heads/main",
            head,
            base,
            tmp_path / "work",
            note=reasons.append,
        )
        is None
    )
    assert reasons == [TIMED_OUT]


def test_the_fixture_loader_reads_the_bundle_and_its_base(tmp_path):
    (tmp_path / "history.bundle").write_bytes(b"bundle bytes")
    (tmp_path / "history-base.txt").write_text("a" * 40 + "\n")
    loaded = fixture_history(tmp_path)
    assert loaded == HistoryBundle(bundle=b"bundle bytes", base_sha="a" * 40)


def test_a_fixture_without_history_is_the_ordinary_no_bundle_run(tmp_path):
    assert fixture_history(tmp_path) is None
    (tmp_path / "history.bundle").write_bytes(b"x")
    # A bundle without its base file is not a history the tools' range
    # can use: the loader declines rather than guessing.
    assert fixture_history(tmp_path) is None
