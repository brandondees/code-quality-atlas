# SPDX-License-Identifier: MIT
"""The controller's acquisition of the pull request's real git history
(D80's git-history update, wired): the review's lenses read `git_log`,
`git_show` and `git_blame` against a **git bundle** the staging fetches
into the staged repository, so the tools and the bash copy's own `git`
see the pull request's commits instead of the staging repo's synthetic
ones. The bundle is built once per review, before the lens fan-out, and
carried into every lens's runner.

Two sources feed the same shape: the live review fetches the pull
request's head ref over HTTPS with the App's credentials
(`bundle_from_repository`), and an eval run loads the fixture's own
bundle (`fixture_history`). The acquisition is a controller-side read
of the repository the review is about that writes nothing to it, and
the bytes it produces are controller-held input the runner already
treats that way (digest-checked in staging, served only through the
sandboxed tools). A fetch that fails, a head that does not match the
review's own proven SHA, or a bundle over the runner's cap acquires
nothing: the review proceeds exactly as it did before this module
existed, with the history tools' named no-history gap -- the gap is the
contract, never a failed run."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from atlas_reviewer.bridge_staging import HISTORY_BUNDLE_MAX_BYTES

# The ref name the staging's fetch step expects the bundle to carry.
ATLAS_HISTORY_REF = "refs/heads/atlas-history"


@dataclass(frozen=True)
class HistoryBundle:
    """The controller-built bundle of the pull request's real history,
    and the merge-base commit the tools' `base..head` range is built on
    -- an ancestor the bundle's own ancestry carries, so the range
    resolves inside the bundle even when the base branch's tip has moved
    past the fork point the diff was built against."""

    bundle: bytes
    base_sha: str


def bundle_from_repository(
    url: str,
    head_ref: str,
    head_sha: str,
    merge_base_sha: str,
    workdir: Path,
    *,
    token: str | None = None,
    cap: int = HISTORY_BUNDLE_MAX_BYTES,
) -> HistoryBundle | None:
    """Fetch `head_ref` (the pull request's own ref, whose tip can move)
    from `url`, verify the fetched tip is still the SHA the review is
    about (`head_sha`, the trees' own provenance -- the check that makes
    a push landing between the diff's fetch and this one acquire
    nothing), name the tip `refs/heads/atlas-history` (the name the
    staging's fetch step expects), bundle its ancestry -- which carries
    `merge_base_sha`, the merge-base the diff was built against -- and
    return the bundle with that base.

    None on every way this can fail or not be worth doing: a fetch that
    fails, a tip that does not match the provenance, or a bundle over
    `cap` -- the runner's own cap, whose excess is already the named
    no-history gap. The fetch's credentials travel in the process
    environment (`GIT_CONFIG_COUNT` extra-header config), never on the
    command line, and no error text is returned: a lost acquisition is
    silent by contract, because history's fail-open rule is the named
    gap, not a failed run."""
    workdir.mkdir(parents=True, exist_ok=True)
    repo = workdir / "history"
    config = ["-c", "http.extraHeader=Authorization: token " + token] if token else []
    init = subprocess.run(
        ["git", "init", "-q", str(repo)], capture_output=True, check=False
    )
    if init.returncode != 0:
        return None

    def git(*argv: str) -> bool:
        done = subprocess.run(
            ["git", *config, *argv],
            cwd=repo,
            capture_output=True,
            check=False,
        )
        return done.returncode == 0

    if not git("fetch", "-q", "--no-tags", url, f"+{head_ref}:refs/history/head"):
        return None
    fetched = subprocess.run(
        ["git", "rev-parse", "refs/history/head"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode != 0 or fetched.stdout.strip() != head_sha:
        return None
    if not git("update-ref", ATLAS_HISTORY_REF, head_sha):
        return None
    bundle_path = workdir / "history.bundle"
    if not git("bundle", "create", str(bundle_path), ATLAS_HISTORY_REF):
        return None
    data = bundle_path.read_bytes()
    if len(data) > cap:
        return None
    return HistoryBundle(bundle=data, base_sha=merge_base_sha)


def fixture_history(fixtures: Path) -> HistoryBundle | None:
    """The eval fixture's own history: `history.bundle` is the bundle the
    staging fetches (built by the fixture builder from the pull request's
    real commits), and `history-base.txt` carries the merge-base commit
    the tools' `base..head` range is built on. A fixture that ships
    neither is the ordinary no-bundle run: the history tools report the
    named gap, exactly as a live review whose acquisition found nothing."""
    bundle = fixtures / "history.bundle"
    base = fixtures / "history-base.txt"
    if not bundle.is_file() or not base.is_file():
        return None
    return HistoryBundle(
        bundle=bundle.read_bytes(),
        base_sha=base.read_text(encoding="utf-8").strip(),
    )
