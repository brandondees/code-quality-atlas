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

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from atlas_reviewer.bridge_staging import HISTORY_BUNDLE_MAX_BYTES

# The ref name the staging's fetch step expects the bundle to carry.
ATLAS_HISTORY_REF = "refs/heads/atlas-history"

# The phase a failed acquisition's reason is recorded under: never the
# service's `progress` phase, whose records the keep-or-cancel reader
# parses as cumulative lens state.
HISTORY_PHASE = "history"

# The coarse reasons a failed acquisition notes through its `note`
# callback (D80's wiring, round 1 of #860): controller constants only,
# never error text and never credential material -- the operator sees
# WHY an acquisition found nothing without the failure growing a surface
# that could carry a secret or remote text.
INIT_FAILED = "init_failed"
FETCH_FAILED = "fetch_failed"
FETCH_TIMED_OUT = "fetch_timed_out"
HEAD_MOVED = "head_moved"
UPDATE_REF_FAILED = "update_ref_failed"
BUNDLE_FAILED = "bundle_failed"
TIMED_OUT = "timed_out"
OVER_CAP = "over_cap"

# The environment a git child gets (round 2 of #860): an allowlist,
# not the controller's whole environment -- the controller's env holds
# every credential the service runs with, and a `git fetch` needs only
# the path, the locale, and the proxy/CA material its HTTPS transport
# honors. `GIT_TERMINAL_PROMPT` is pinned to 0: a credential prompt
# would hang until the timeout, silently.
_GIT_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "CURL_CA_BUNDLE",
    "GIT_SSL_CAINFO",
    "GIT_SSL_CAPATH",
    "GIT_SSL_NO_VERIFY",
)


def _git_env(*extra: tuple[str, str]) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name in _GIT_ENV_PASSTHROUGH
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(dict(extra))
    return env


# Every git call is bounded (round 1 of #860, resilience): the
# acquisition runs synchronously before the lens fan-out, so a stalled
# fetch or a wedged local git must cost the review a bounded wait, not
# an indefinite one. The fetch's bound is generous because it carries
# the pull request's whole ancestry over HTTPS.
HISTORY_GIT_TIMEOUT_S = 120.0
HISTORY_FETCH_TIMEOUT_S = 300.0


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
    note: Callable[[str], None] | None = None,
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
    fails or runs past its bound, a tip that does not match the
    provenance, or a bundle over `cap` -- the runner's own cap, whose
    excess is already the named no-history gap. The fetch's credentials
    travel in the process environment (`GIT_CONFIG_COUNT` extra-header
    config), never on the command line, and no error text is returned:
    a lost acquisition is silent by contract, because history's
    fail-open rule is the named gap, not a failed run. What the operator
    does see is WHY: each failure path notes one coarse reason through
    `note` (a module constant above -- `fetch_failed`, `head_moved`,
    `over_cap`, ...), never error text and never credential material
    (round 1 of #860: a permanently broken acquisition must be
    distinguishable from an ordinary no-history run)."""
    note = note or (lambda reason: None)
    workdir.mkdir(parents=True, exist_ok=True)
    repo = workdir / "history"
    # The credential rides `env=`, the documented GIT_CONFIG_* plumbing:
    # argv is readable to anything on the host (`ps`, /proc), the
    # environment of the one process is not (round 1 of #860). The env
    # is the allowlist, plus exactly the credential header.
    credential = (
        (
            ("GIT_CONFIG_COUNT", "1"),
            ("GIT_CONFIG_KEY_0", "http.extraHeader"),
            ("GIT_CONFIG_VALUE_0", "Authorization: token " + token),
        )
        if token
        else ()
    )
    fetch_env = _git_env(*credential)
    try:
        init = subprocess.run(
            ["git", "init", "-q", str(repo)],
            capture_output=True,
            check=False,
            timeout=HISTORY_GIT_TIMEOUT_S,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired:
        note(TIMED_OUT)
        return None
    if init.returncode != 0:
        note(INIT_FAILED)
        return None

    def git(*argv: str) -> bool | None:
        """False on a failure the caller names; None when the call ran
        past its bound -- the timeout is already noted, and the caller
        must not name it again."""
        try:
            done = subprocess.run(
                ["git", *argv],
                cwd=repo,
                capture_output=True,
                check=False,
                timeout=HISTORY_GIT_TIMEOUT_S,
                env=_git_env(),
            )
        except subprocess.TimeoutExpired:
            note(TIMED_OUT)
            return None
        return done.returncode == 0

    try:
        fetch = subprocess.run(
            [
                "git",
                "fetch",
                "-q",
                "--no-tags",
                url,
                f"+{head_ref}:refs/history/head",
            ],
            cwd=repo,
            capture_output=True,
            check=False,
            timeout=HISTORY_FETCH_TIMEOUT_S,
            env=fetch_env,
        )
    except subprocess.TimeoutExpired:
        note(FETCH_TIMED_OUT)
        return None
    if fetch.returncode != 0:
        note(FETCH_FAILED)
        return None
    try:
        fetched = subprocess.run(
            ["git", "rev-parse", "refs/history/head"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=HISTORY_GIT_TIMEOUT_S,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired:
        note(TIMED_OUT)
        return None
    if fetched.returncode != 0 or fetched.stdout.strip() != head_sha:
        note(HEAD_MOVED)
        return None
    ran = git("update-ref", ATLAS_HISTORY_REF, head_sha)
    if ran is None:
        return None
    if not ran:
        note(UPDATE_REF_FAILED)
        return None
    bundle_path = workdir / "history.bundle"
    ran = git("bundle", "create", str(bundle_path), ATLAS_HISTORY_REF)
    if ran is None:
        return None
    if not ran:
        note(BUNDLE_FAILED)
        return None
    data = bundle_path.read_bytes()
    if len(data) > cap:
        note(OVER_CAP)
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
