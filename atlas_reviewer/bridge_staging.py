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
from atlas_reviewer.guest_unpack import (
    unpack_refusal,
    unpack_script,
)
from atlas_reviewer.interpreter import (
    CANDIDATE_BOUND_S,
    PYENV_VERSIONS,
    SYSTEM_PYTHON,
    TrustedPython,
    bounded,
    trusted_path,
)
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
MUTANT_REF = "refs/tags/atlas-mutant"
MUTANT_TAG = "atlas-mutant"
SCRATCH_DIR = "scratch"
SCRATCH_WORK = "work"
_SHA = re.compile(r"[0-9a-f]{40}")
# The pythons the pytest probe asks about, in pick order: the pyenv
# versions (the guest shell expands the glob), then the system one. The
# same trusted shapes `interpreter` accepts; a caller may name further
# literal candidates (the tests point it at this machine's venv).
PYTEST_CANDIDATES = (f"{PYENV_VERSIONS}/*/bin/python3", SYSTEM_PYTHON)
PYTEST_TAG = "atlas-pytest"
_PYTEST_RE = re.compile(
    re.escape(PYTEST_TAG)
    + r":(/[A-Za-z0-9._/+-]{1,200}):"
    + r"(\d+)\.(\d+)\.(\d+)\s*$",
    re.MULTILINE,
)

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
    # The interpreter the execution tools (D80) run tests and mutants
    # with: the newest pyenv python (or the system one) whose `-I -m
    # pytest` the staging probe confirmed importable, resolved before any
    # PR content is unpacked. None when no candidate has pytest, which
    # makes `run_tests` and `mutate` unavailable, not broken.
    pytest: TrustedPython | None = None
    # The GitHub head SHA the head tree was fetched at (provenance, D80):
    # a test or mutant result is tagged with it, so a lens can cite the
    # evidence at the head it belongs to (D73).
    head_sha: str = ""

    @property
    def revs(self) -> frozenset[Rev]:
        return frozenset(self.commits)

    @property
    def scratch(self) -> str:
        """The scratch directory one execution tool call stages its
        disposable copy of HEAD in, removed again by the call's own
        script. The copy is built from the bare repository's objects
        (`stage_copy_steps`), so what the tests write into it -- and what
        a hostile test replaces elsewhere -- never reaches the next
        call's copy, the mutant commit, or anything else a later call
        trusts."""
        return f"{self.root}/{SCRATCH_DIR}/{SCRATCH_WORK}"


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


def git_resolve_script(
    root: str, pytest_candidates: Sequence[str] = PYTEST_CANDIDATES
) -> str:
    """Finds git at one of `GIT_PATHS` without consulting PATH, before any
    PR content is in the runner, creates the bridge root, and probes each
    candidate interpreter for a pytest it can run isolated (D80). Each
    candidate is bounded on its own, so one hung interpreter cannot stop
    the rest being found, and the script still exits nonzero when git is
    missing."""
    candidates = " ".join(GIT_PATHS)
    words = " ".join(pytest_candidates)
    query = "import sys, pytest; print('%d.%d.%d' % sys.version_info[:3])"
    probe = bounded(f'"$p" -I -c "{query}"', CANDIDATE_BOUND_S)
    pytest_loop = (
        f"for p in {words}; do "
        f'if [ -x "$p" ] && v=$({probe} 2>/dev/null); then '
        f'echo "{PYTEST_TAG}:$p:$v"; fi; done'
    )
    return (
        f"mkdir -p {quote(root)}/trees && g=''; for p in {candidates}; do "
        'if [ -z "$g" ] && [ -f "$p" ] && [ -x "$p" ]; then g=$p; fi; done; '
        f'if [ -n "$g" ]; then echo "{GIT_TAG}:$g"; "$g" --version; '
        f"else echo {GIT_TAG}:none; fi; "
        f'{pytest_loop}; test -n "$g"'
    )


def choose_pytest(
    text: str, candidates: Sequence[str] = PYTEST_CANDIDATES
) -> TrustedPython | None:
    """The newest pyenv interpreter, else the system one, among those the
    guest reported with an importable pytest. Only paths of the trusted
    shapes, or exactly a literal candidate the controller itself named,
    are accepted from the guest's answer; unreported candidates count as
    unavailable."""
    found = [
        (path, (int(a), int(b), int(c)))
        for path, a, b, c in _PYTEST_RE.findall(text)
        if trusted_path(path) or path in candidates
    ]
    pyenv = sorted((c for c in found if c[0] != SYSTEM_PYTHON), key=_newest)
    system = [c for c in found if c[0] == SYSTEM_PYTHON]
    chosen = [*pyenv, *system][:1]
    return next((TrustedPython(p, ".".join(map(str, v))) for p, v in chosen), None)


def _newest(candidate: tuple[str, tuple[int, int, int]]) -> tuple[int, ...]:
    return tuple(-n for n in candidate[1])


def stage_copy_steps(root: str, git: str, scratch: str, head: str) -> tuple[str, ...]:
    """Builds one fresh disposable copy of the HEAD tree from the bare
    repository's own objects (D80 round 1): `read-tree <head-commit>`
    rebuilds a scratch index from the recorded HEAD commit and
    `checkout-index` writes that tree out, so the copy comes from git's
    hash-checked object store and never from `trees` or a previous
    scratch. Nothing PR-controlled code wrote or replaced between calls
    -- in `trees`, the scratch, or the index file -- can change what a
    later execution call stages; the only thing executed code can take
    from the session is its own remaining availability (deleting the
    repository makes later calls fail, recorded as gaps). The step
    removes any index file a previous call left behind, so `read-tree`
    always builds the index anew; the commit is named by its recorded id,
    not by the `HEAD` symref the staging repository leaves at its unborn
    default branch."""
    g = _git_cmd(git, root)
    index = f"GIT_INDEX_FILE={quote(root)}/index-stage"
    # The bare repository refuses index operations; naming the bridge root
    # as the invocation's work tree satisfies the check, and nothing is
    # written there -- `read-tree` touches only the index, and
    # `checkout-index` writes to the `--prefix` directory.
    work_tree = f"--work-tree={quote(root)}"
    return (
        f"rm -rf {quote(f'{root}/{SCRATCH_DIR}')} {quote(root)}/index-stage",
        f"mkdir -p {quote(f'{root}/{SCRATCH_DIR}')}",
        f"{index} {g} {work_tree} read-tree {quote(head)}",
        f"{index} {g} {work_tree} checkout-index -a -f --prefix={quote(scratch)}/",
    )


def mutant_commit_steps(
    root: str, git: str, scratch: str, head: str
) -> tuple[str, ...]:
    """Commits the mutated copy into the bare repository and moves
    `MUTANT_REF` onto it (D80). The bridge reads MUTANT at the commit id
    its own commit step recorded -- a content-addressed *name* the
    controller holds, whose content is protected by the re-stage (the
    repository is rebuilt from the digest-checked tarballs and the
    recorded mutation re-applied deterministically) and by the
    re-created-id check, **not** by git's read path: git does not
    re-verify a loose object on read. Executed code moving or forging the
    ref changes nothing the tools serve; the ref is bookkeeping only.
    Prints `MUTANT_TAG:<commit>` only when the ref moved; carries the
    staging commit identity of its own."""
    g = _git_cmd(git, root)
    index = f"GIT_INDEX_FILE={quote(root)}/index-mutant"
    return (
        f"export {' '.join(_IDENTITY)}",
        f"rm -f {quote(root)}/index-mutant",
        f"(cd {quote(scratch)} && {index} {g} --work-tree=. add -A -f .)",
        f"t=$({index} {g} write-tree)",
        f'c=$({g} commit-tree "$t" -p {quote(head)} -m atlas-mutant)',
        f'{g} update-ref {quote(MUTANT_REF)} "$c" && echo "{MUTANT_TAG}:$c"',
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


def stage_script(
    root: str,
    git: str,
    revs: Sequence[Rev],
    unpack: UnpackLimits = DEFAULT_UNPACK,
    digests: Mapping[Rev, str] | None = None,
) -> str:
    """One exec: extract each uploaded tarball within `unpack`
    (`guest_unpack`), commit its tree into a fresh bare repository, print
    each commit id. Runs in a `set -e` subshell so the exit marker is still
    printed on failure, and the first refused tree stops the rest. When
    `digests` names each tree's sha256 (the re-stage path, where executed
    code from an earlier call could have rewritten the uploaded file in
    the upload-to-verify window), each tarball is verified against its
    digest before anything is extracted, and a mismatch stops the
    staging."""
    g = _git_cmd(git, root)
    checks = [
        (
            f"printf '%s  {rev.value.lower()}.tar.gz\\n' {quote(digests[rev])} "
            "| sha256sum -c -"
        )
        for rev in revs
        if digests and rev in digests
    ]
    steps = [
        f"cd {quote(root)}",
        f"export {' '.join(GIT_ENV)} {' '.join(_IDENTITY)}",
        *checks,
        f"{g} init -q --bare {quote(root)}/repo.git",
        f"printf '%s\\n' {quote(ATTRIBUTES)} > repo.git/info/attributes",
        *(step for rev in revs for step in _commit_steps(root, g, rev, unpack)),
    ]
    return f"( set -e; {'; '.join(steps)} )"


def _commit_steps(root: str, g: str, rev: Rev, unpack: UnpackLimits) -> tuple[str, ...]:
    name = rev.value.lower()
    tree = f"{quote(root)}/trees/{name}"
    index = f"GIT_INDEX_FILE={quote(root)}/index-{name}"
    parent = ' -p "$c_base"' if rev is Rev.HEAD else ""
    return (
        unpack_script(
            f"{name}.tar.gz",
            f"{root}/trees/{name}",
            "--strip-components=1 --no-same-owner --no-same-permissions",
            unpack,
        ),
        f"rm -f {name}.tar.gz",
        f"(cd {tree} && {index} {g} --work-tree=. add -A -f .)",
        f"t=$({index} {g} write-tree)",
        f'c_{name}=$({g} commit-tree "$t"{parent} -m {name})',
        f'echo "{STAGED_TAG}:{name}:$c_{name}"',
    )


def parse_staged(
    code: int | None,
    text: str,
    revs: Sequence[Rev],
    unpack: UnpackLimits = DEFAULT_UNPACK,
) -> dict[Rev, str]:
    found = dict(
        re.findall(
            rf"^{STAGED_TAG}:(base|head|default):([0-9a-f]{{40}})$", text, re.MULTILINE
        )
    )
    commits = {rev: found.get(rev.value.lower(), "") for rev in revs}
    refused = unpack_refusal(text, unpack) if code != 0 else None
    if refused is not None:
        raise BoundaryError(f"bridge staging failed (exit {code}): {refused}")
    if code != 0 or not all(commits.values()):
        raise BoundaryError(
            f"bridge staging failed (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
        )
    return commits


def stage(
    session: Session,
    trees: SourceTrees,
    root: str = BRIDGE_ROOT,
    unpack: UnpackLimits = DEFAULT_UNPACK,
    pytest_candidates: Sequence[str] = PYTEST_CANDIDATES,
) -> Staged:
    """Raises `BoundaryError` when git is missing or untrusted, an upload
    falls short, the runner refuses a tree past `unpack`, or staging does
    not report every commit."""
    code, text = session.exec(
        "resolve git",
        git_resolve_script(root, pytest_candidates),
        stage="bridge staging",
    )
    git, version = choose_git(code, text)
    pytest = choose_pytest(text, pytest_candidates)
    revs = tuple(rev for rev, _ in trees.staged())
    for rev, data in trees.staged():
        session.upload(
            data,
            f"{quote(root)}/{rev.value.lower()}.tar.gz",
            f"{rev.value} tree upload",
        )
    code, text = session.exec(
        "stage repository",
        stage_script(root, git, revs, unpack),
        stage="bridge staging",
        budget_s=UNPACK_BUDGET_S,
    )
    commits = parse_staged(code, text, revs, unpack)
    return Staged(root, git, MappingProxyType(commits), version, pytest, trees.head_sha)
