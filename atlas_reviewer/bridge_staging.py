# SPDX-License-Identifier: MIT
"""Option B source staging for the bridge (D31, D34 (2), D39).

The base (merge-base) and head tarballs, plus an optional default-branch
tarball, are uploaded into a fresh runner and committed into a bare
repository there with a fixed identity and date. HEAD's parent is BASE;
DEFAULT is a separate root commit. Staging reports the synthetic commit
ids, which differ from the GitHub SHAs (kept in `SourceTrees` as
provenance); tools refer only to those ids.

Git is found at a fixed absolute path, never through PATH, before any PR
content is in the runner, and every git call gets the same hardening:
no system or user config, no hooks, fsmonitor, pager, transport or
colour, literal pathspecs, and repository attributes that override any
in-tree `.gitattributes`. Nothing from the PR is checked out, built or
executed.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from atlas_reviewer.bridge_args import Rev
from atlas_reviewer.ports import BoundaryError, GitHubReader, Json
from atlas_reviewer.runner import (
    GUEST_TAIL_CHARS,
    MAX_TARBALL_BYTES,
    UNPACK_BUDGET_S,
    VERSION_CHARS,
    Session,
    guest_text,
    refused_archive,
)
from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits

BRIDGE_ROOT = "/work/bridge"
GIT_PATHS = ("/usr/bin/git", "/bin/git")
GIT_TAG = "atlas-git"
STAGED_TAG = "atlas-staged"
EXTRACT_TIMEOUT_S = 60
KILL_AFTER_S = 2
_SHA = re.compile(r"[0-9a-f]{40}")

# Fixed git options: no hooks, no fsmonitor, no pager, no transport, no
# colour, unusual paths C-quoted, no line-ending or filter conversion.
GIT_OPTIONS = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=",
    "-c", "core.pager=cat",
    "-c", "protocol.allow=never",
    "-c", "color.ui=never",
    "-c", "core.quotePath=true",
    "-c", "core.autocrlf=false",
    "-c", "core.safecrlf=false",
)  # fmt: skip
# No system or user config, no replace refs, literal pathspecs (no `:(...)`
# magic or globs), no system attributes, never a prompt, no optional locks.
GIT_ENV = (
    "GIT_CONFIG_NOSYSTEM=1",
    "GIT_CONFIG_GLOBAL=/dev/null",
    "GIT_NO_REPLACE_OBJECTS=1",
    "GIT_LITERAL_PATHSPECS=1",
    "GIT_ATTR_NOSYSTEM=1",
    "GIT_TERMINAL_PROMPT=0",
    "GIT_OPTIONAL_LOCKS=0",
    "GIT_PAGER=cat",
)
# `$GIT_DIR/info/attributes` outranks every in-tree `.gitattributes`: no
# conversion, filter or keyword expansion on add, and no diff driver.
ATTRIBUTES = "* -text !eol -filter -ident !diff !working-tree-encoding"
_IDENTITY = (
    "GIT_AUTHOR_NAME=atlas-bridge",
    "GIT_AUTHOR_EMAIL=atlas-bridge@invalid",
    "GIT_AUTHOR_DATE='@0 +0000'",
    "GIT_COMMITTER_NAME=atlas-bridge",
    "GIT_COMMITTER_EMAIL=atlas-bridge@invalid",
    "GIT_COMMITTER_DATE='@0 +0000'",
)


@dataclass(frozen=True)
class SourceTrees:
    """GitHub tarballs (one top-level directory each) and the GitHub SHAs
    they were fetched at, kept as provenance."""

    base: bytes
    head: bytes
    base_sha: str
    head_sha: str
    default: bytes | None = None
    default_sha: str | None = None

    def staged(self) -> tuple[tuple[Rev, bytes], ...]:
        trees = (
            (Rev.BASE, self.base),
            (Rev.HEAD, self.head),
            (Rev.DEFAULT, self.default),
        )
        return tuple((rev, data) for rev, data in trees if data is not None)


@dataclass(frozen=True)
class Staged:
    root: str
    git: str
    commits: Mapping[Rev, str]
    git_version: str = ""

    @property
    def revs(self) -> frozenset[Rev]:
        return frozenset(self.commits)


def fetch_sources(
    github: GitHubReader,
    repo: str,
    base_ref: str,
    head_sha: str,
    max_bytes: int = MAX_TARBALL_BYTES,
) -> SourceTrees:
    """The merge base of `base_ref` and the head, and both tarballs.
    Raises `BoundaryError` for a malformed compare reply or an oversized
    tarball; no default-branch tree is fetched here."""
    base_sha = parse_merge_base(github.get_compare(repo, base_ref, head_sha))
    base, head = (github.get_tarball(repo, sha) for sha in (base_sha, head_sha))
    trees = SourceTrees(base, head, base_sha, head_sha)
    check_sizes(trees, max_bytes)
    return trees


def parse_merge_base(data: Json) -> str:
    commit = data.get("merge_base_commit")
    sha = commit.get("sha") if isinstance(commit, Mapping) else None
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise BoundaryError("GitHub compare reply has no 40-hex merge_base_commit.sha")
    return sha


def check_sizes(
    trees: SourceTrees,
    max_bytes: int = MAX_TARBALL_BYTES,
    unpack: UnpackLimits = DEFAULT_UNPACK,
) -> None:
    """Every tree within the upload cap, readable and within the unpack
    caps (`source_archive`), or `BoundaryError` naming each that is not."""
    refused = [
        f"{rev} {reason}"
        for rev, data in trees.staged()
        if (reason := _refusal(data, max_bytes, unpack)) is not None
    ]
    if refused:
        raise BoundaryError(f"source tree refused: {'; '.join(refused)}")


def _refusal(data: bytes, max_bytes: int, unpack: UnpackLimits) -> str | None:
    if len(data) > max_bytes:
        return f"is {len(data)} bytes, over the {max_bytes}-byte upload cap"
    reason = refused_archive(data, unpack)
    return None if reason is None else f"is refused: {reason}"


def quote(value: str) -> str:
    return shlex.quote(value)


def git_resolve_script(root: str) -> str:
    """Finds git at one of `GIT_PATHS` without consulting PATH, before any
    PR content is in the runner, and creates the bridge root."""
    candidates = " ".join(GIT_PATHS)
    return (
        f"mkdir -p {quote(root)}/trees && g=''; for p in {candidates}; do "
        'if [ -z "$g" ] && [ -f "$p" ] && [ -x "$p" ]; then g=$p; fi; done; '
        f'if [ -n "$g" ]; then echo "{GIT_TAG}:$g"; "$g" --version; '
        f"else echo {GIT_TAG}:none; false; fi"
    )


def choose_git(code: int | None, text: str) -> tuple[str, str]:
    """The reported git path, accepted only if it is exactly one of
    `GIT_PATHS`, and its version line (untrusted, for telemetry)."""
    _, found, after = text.rpartition(f"{GIT_TAG}:")
    path, _, version = after.partition("\n")
    if code != 0 or not found or path not in GIT_PATHS:
        raise BoundaryError(
            f"no trusted git in the runner (exit {code}): "
            f"{guest_text(text, GUEST_TAIL_CHARS)}"
        )
    return path, guest_text(version, VERSION_CHARS)


def _git_cmd(git: str, root: str) -> str:
    return " ".join((quote(git), f"--git-dir={quote(root)}/repo.git", *GIT_OPTIONS))


def stage_script(root: str, git: str, revs: Sequence[Rev]) -> str:
    """One exec: extract each uploaded tarball, commit its tree into a
    fresh bare repository, print each commit id. Runs in a `set -e`
    subshell so the exit marker is still printed on failure."""
    g = _git_cmd(git, root)
    steps = [
        f"cd {quote(root)}",
        f"export {' '.join(GIT_ENV)} {' '.join(_IDENTITY)}",
        f"{g} init -q --bare {quote(root)}/repo.git",
        f"printf '%s\\n' {quote(ATTRIBUTES)} > repo.git/info/attributes",
        *(step for rev in revs for step in _commit_steps(root, g, rev)),
    ]
    return f"( set -e; {'; '.join(steps)} )"


def _commit_steps(root: str, g: str, rev: Rev) -> tuple[str, ...]:
    name = rev.value.lower()
    tree = f"{quote(root)}/trees/{name}"
    index = f"GIT_INDEX_FILE={quote(root)}/index-{name}"
    parent = ' -p "$c_base"' if rev is Rev.HEAD else ""
    return (
        f"mkdir -p {tree}",
        (
            f"timeout -k {KILL_AFTER_S} {EXTRACT_TIMEOUT_S} tar -xzf {name}.tar.gz -C {tree} "
            "--strip-components=1 --no-same-owner --no-same-permissions"
        ),
        f"rm -f {name}.tar.gz",
        f"(cd {tree} && {index} {g} --work-tree=. add -A -f .)",
        f"t=$({index} {g} write-tree)",
        f'c_{name}=$({g} commit-tree "$t"{parent} -m {name})',
        f'echo "{STAGED_TAG}:{name}:$c_{name}"',
    )


def parse_staged(code: int | None, text: str, revs: Sequence[Rev]) -> dict[Rev, str]:
    found = dict(
        re.findall(
            rf"^{STAGED_TAG}:(base|head|default):([0-9a-f]{{40}})$", text, re.MULTILINE
        )
    )
    commits = {rev: found.get(rev.value.lower(), "") for rev in revs}
    if code != 0 or not all(commits.values()):
        raise BoundaryError(
            f"bridge staging failed (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
        )
    return commits


def stage(session: Session, trees: SourceTrees, root: str = BRIDGE_ROOT) -> Staged:
    """Raises `BoundaryError` when git is missing or untrusted, an upload
    falls short, or staging does not report every commit."""
    git, version = choose_git(
        *session.exec("resolve git", git_resolve_script(root), stage="bridge staging")
    )
    revs = tuple(rev for rev, _ in trees.staged())
    for rev, data in trees.staged():
        session.upload(
            data,
            f"{quote(root)}/{rev.value.lower()}.tar.gz",
            f"{rev.value} tree upload",
        )
    code, text = session.exec(
        "stage repository",
        stage_script(root, git, revs),
        stage="bridge staging",
        budget_s=UNPACK_BUDGET_S,
    )
    return Staged(root, git, MappingProxyType(parse_staged(code, text, revs)), version)
