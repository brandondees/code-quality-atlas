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

import base64
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from atlas_reviewer.bridge_args import Rev
from atlas_reviewer.guest_unpack import (
    KILL_AFTER_S,
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
COLLECT_TAG = "atlas-collect"
_SHA = re.compile(r"[0-9a-f]{40}")
# The pythons the pytest probe asks about, in pick order: the pyenv
# versions (the guest shell expands the glob), then the system one. The
# same trusted shapes `interpreter` accepts; a caller may name further
# literal candidates (the tests point it at this machine's venv).
PYTEST_CANDIDATES = (f"{PYENV_VERSIONS}/*/bin/python3", SYSTEM_PYTHON)
PYTEST_TAG = "atlas-pytest"
SHIM_TAG = "atlas-shim"
_PYTEST_RE = re.compile(
    re.escape(PYTEST_TAG)
    + r":(/[A-Za-z0-9._/+-]{1,200}):"
    + r"(\d+)\.(\d+)\.(\d+)\s*$",
    re.MULTILINE,
)
_SHIM_RE = re.compile(
    re.escape(SHIM_TAG) + r":(/[A-Za-z0-9._/+-]{1,200}):" + r"(\d+)\.(\d+)\.(\d+)\s*$",
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
    # The interpreter the no-root guard runs through (D80's 2026-11-26
    # update): the pytest-capable one when there is one, else the first
    # candidate that runs at all -- the guard only needs to execute, the
    # approved proposed commands only need the guard, and decoupling the
    # two keeps an approved command available on a runner whose
    # interpreter has no pytest. None when no candidate even runs, which
    # refuses the execution tools (there is nothing to execute tests
    # with, guard or not).
    shim_python: TrustedPython | None = None
    # The real history the staged repository carries (D80's git-history
    # update): the shas the history tools name and guard with -- the pull
    # request's head and its base tip -- set only when the run's staging
    # carried a history bundle; empty means the history tools report the
    # named no-history gap.
    history_head: str = ""
    history_base: str = ""
    # Why the history is absent, when it is: the over-cap bundle, a fetch
    # that failed, or a bundle whose head is not the pull request's. The
    # history tools' named gap carries it; an empty string means the
    # history is present (or the run staged no bundle and asked for none).
    history_note: str = ""
    # The GitHub head SHA the head tree was fetched at (provenance, D80):
    # a test or mutant result is tagged with it, so a lens can cite the
    # evidence at the head it belongs to (D73).
    head_sha: str = ""
    # The collection probe's verdict (the 2026-11-26 environment-parity
    # slice, D80's update): whether `pytest --co -q` collects the staged
    # copy's tests, run as the same non-root user the execution tools
    # run as. False when collection failed, with `collection_note`
    # carrying the output tail that says why -- the named gap the
    # execution tools report instead of silent INCONCLUSIVE mutants and
    # red baselines. True-with-no-note also when no pytest was staged at
    # all (the tools are refused on the missing interpreter before the
    # verdict could matter).
    collection_ok: bool = True
    collection_note: str = ""
    # Whether the collection probe ran (it runs whenever a pytest-capable
    # interpreter was staged): the probe executes the staged copy's own
    # conftest.py -- PR code, in the runner, with the staged repository
    # reachable -- so the bridge built on this staging starts suspect and
    # its first runner-side read or execution copy re-stages from the
    # controller-held tarballs, whatever the probe's verdict was.
    collection_ran: bool = False

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
    candidate interpreter twice, each bounded on its own so one hung
    interpreter cannot stop the rest being found: once for a pytest it can
    run isolated (D80), and once for running at all -- the no-root guard
    (`as_nobody`) runs through an interpreter, and the execution tools'
    guard needs one even where pytest is absent. The script still exits
    nonzero when git is missing."""
    candidates = " ".join(GIT_PATHS)
    words = " ".join(pytest_candidates)
    query = "import sys, pytest; print('%d.%d.%d' % sys.version_info[:3])"
    plain = "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    probe = bounded(f'"$p" -I -c "{query}"', CANDIDATE_BOUND_S)
    shim_probe = bounded(f'"$p" -I -c "{plain}"', CANDIDATE_BOUND_S)
    pytest_loop = (
        f"for p in {words}; do "
        f'if [ -x "$p" ]; then '
        f'v=$({probe} 2>/dev/null) && echo "{PYTEST_TAG}:$p:$v"; '
        f'v=$({shim_probe} 2>/dev/null) && echo "{SHIM_TAG}:$p:$v"; '
        "fi; done"
    )
    return (
        f"mkdir -p {quote(root)}/trees && g=''; for p in {candidates}; do "
        'if [ -z "$g" ] && [ -f "$p" ] && [ -x "$p" ]; then g=$p; fi; done; '
        f'if [ -n "$g" ]; then echo "{GIT_TAG}:$g"; "$g" --version; '
        f"else echo {GIT_TAG}:none; fi; "
        f'{pytest_loop}; test -n "$g"'
    )


def choose_pytest(
    text: str,
    candidates: Sequence[str] = PYTEST_CANDIDATES,
) -> TrustedPython | None:
    """The interpreter the guest reported with an importable pytest. The
    default order is the newest pyenv interpreter, else the system one.
    Only paths of the trusted shapes, or exactly a literal candidate the
    controller itself named, are accepted from the guest's answer;
    unreported candidates count as unavailable."""
    found = [
        (path, (int(a), int(b), int(c)))
        for path, a, b, c in _PYTEST_RE.findall(text)
        if trusted_path(path) or path in candidates
    ]
    pyenv = sorted((c for c in found if c[0] != SYSTEM_PYTHON), key=_newest)
    system = [c for c in found if c[0] == SYSTEM_PYTHON]
    chosen = [*pyenv, *system][:1]
    return next((TrustedPython(p, ".".join(map(str, v))) for p, v in chosen), None)


def choose_shim(
    text: str,
    candidates: Sequence[str] = PYTEST_CANDIDATES,
    pytest: TrustedPython | None = None,
) -> TrustedPython | None:
    """The interpreter the no-root guard runs through: the pytest-capable
    one when the probe found it (the guard then shares the tests' own
    environment), else the first candidate that ran at all, in probe
    order. The same trusted shapes apply; unreported candidates count as
    absent."""
    if pytest is not None:
        return pytest
    found = [
        (path, (int(a), int(b), int(c)))
        for path, a, b, c in _SHIM_RE.findall(text)
        if trusted_path(path) or path in candidates
    ]
    chosen = sorted(found, key=_newest)[:1] if found else []
    return next((TrustedPython(p, ".".join(map(str, v))) for p, v in chosen), None)


def _newest(candidate: tuple[str, tuple[int, int, int]]) -> tuple[int, ...]:
    return tuple(-n for n in candidate[1])


# The execution tools' test processes never run as root (Brandon's Nov 25
# decision, D80's 2026-11-26 update): the Sprite's exec user is root, and
# a root test process defeats the access controls some of the repo's own
# tests exercise -- the round log's locked-file test fails its baseline
# because a `chmod(0)` read does not stop root. The guard is a
# controller-built shim run by the trusted interpreter the staging probe
# resolved: a root caller drops to the standard `nobody` uid and gid
# (65534, supplementary groups cleared, `setgroups` first while still
# root) before `execvp`ing the rest of the argv (PATH searched, the way
# the shell's exec resolved a bare program name); a caller that is already
# not root execs directly, because the decision's condition -- the tests
# do not run as root -- already holds there. Every element after the shim
# stays a separate shell argument exactly as it was: the model's selector
# keeps its shlex-quoting, and no untrusted text is ever embedded in
# Python source. A drop that cannot happen despite a root caller exits
# 126 with the reason on stderr: a named failure, never a root run.
NOBODY_UID = 65534
DROP_SHIM = (
    "import os, sys\n"
    "if os.geteuid() == 0:\n"
    "    try:\n"
    f"        os.setgroups([])\n        os.setgid({NOBODY_UID})\n"
    f"        os.setuid({NOBODY_UID})\n"
    "    except OSError as exc:\n"
    "        sys.stderr.write(f'atlas-privilege-drop failed: {exc}\\n')\n"
    "        sys.exit(126)\n"
    "os.execvp(sys.argv[1], sys.argv[1:])\n"
)


def as_nobody(python: TrustedPython, argv: str) -> str:
    """`argv` prefixed with the no-root guard shim run by the trusted
    `python`: the process `argv` names never executes as root."""
    return f"{python.quoted} -I -c {shlex.quote(DROP_SHIM)} {argv}"


def guarded_env_exports(scratch: str) -> str:
    """The environment the guarded execs run under, set inside their own
    subshell: the no-root guard's user is not the user that built the
    copy, its `.git` file or the staged repository, and git (>= 2.35.2)
    refuses that ownership mismatch outright (`detected dubious
    ownership`) -- so any PR code running in the copy that invokes git
    (the model's bash command, a repo's own test suite) would otherwise
    fail there. The copy is declared a safe directory via the
    environment: protected config, honored in the subshell where it is
    set, and unreachable from repo-local config. Scoped to the copy's
    own path, never `*`. `scratch` is the raw path; the quoting is this
    helper's own contract, so no caller can hand it a pre-quoted word
    and double-quote the value."""
    return (
        "export GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        f"GIT_CONFIG_VALUE_0={shlex.quote(scratch)}; "
    )


# The collection probe's own bound (D80's 2026-11-26 update): collecting
# the staged copy's tests imports every test module once; a repo of this
# size collects in tens of seconds, and the bound exists so a module that
# hangs at import cannot eat the staging budget. The exec's window is the
# bound plus the kill slack and the copy's staging.
# The history bundle's upload (D80's git-history update): the controller
# uploads it in chunks -- one exec's stdin caps at EXEC_STDIN_MAX_BYTES --
# and the staging step concatenates the parts, fetches the bundle's ref
# into the staged repository, and verifies the fetched head is the pull
# request's own. Above the cap the history tools report the named
# no-history gap instead of a partial history.
HISTORY_CHUNK_BYTES = 8 * 1024 * 1024
HISTORY_BUNDLE_MAX_BYTES = 6 * HISTORY_CHUNK_BYTES
HISTORY_BUNDLE_FILE = "history.bundle"
HISTORY_REF = "refs/heads/atlas-history"
HISTORY_FETCHED_REF = "refs/atlas-history/head"


def upload_history_bundle(session: Session, bundle: bytes, root: str) -> None:
    """The history bundle, chunked across the exec-stdin cap: each part is
    one bounded upload; the staging step concatenates them. Above the cap
    the refusal is the run's named gap, never a silent partial history."""
    if len(bundle) > HISTORY_BUNDLE_MAX_BYTES:
        raise BoundaryError(
            "the history bundle exceeds "
            f"{HISTORY_BUNDLE_MAX_BYTES} bytes ({len(bundle)} given); the "
            "history tools will report no history for this run"
        )
    chunks = [
        bundle[i : i + HISTORY_CHUNK_BYTES]
        for i in range(0, len(bundle), HISTORY_CHUNK_BYTES)
    ]
    for index, chunk in enumerate(chunks):
        session.upload(
            chunk,
            f"{root}/{HISTORY_BUNDLE_FILE}.part{index:02d}",
            "history bundle part",
        )


def history_fetch_script(root: str, git: str, base: str, head: str) -> str:
    """One staging exec (D80's git-history update): concatenate the
    bundle's parts, fetch its ref into the staged repository, and verify
    the fetched head is the pull request's own. The verdict is one
    `atlas-history` tag line; a fetch that fails is a staging failure
    named like the others, and the parts and the bundle file are removed
    whatever happened."""
    quoted_root = shlex.quote(root)
    quoted_file = shlex.quote(f"{root}/{HISTORY_BUNDLE_FILE}")
    # The control structures join with newlines: a `; `-joined `then;` or
    # `else;` is a shell syntax error, and the exec would answer nothing.
    return "\n".join(
        (
            f"cd {quoted_root}",
            f"cat {quoted_file}.part* > {quoted_file} 2>/dev/null",
            "rm -f " + quoted_file + ".part*",
            (
                f"if {quote(git)} --git-dir=repo.git fetch -q {quoted_file} "
                f"{HISTORY_REF}:refs/atlas-history/head; then"
            ),
            (
                f"  got=$({quote(git)} --git-dir=repo.git rev-parse "
                "refs/atlas-history/head^{commit})"
            ),
            f'  if [ "$got" = {quote(head)} ]; then',
            '    echo "atlas-history:ok"',
            "  else",
            '    echo "atlas-history:wrong-head:$got"',
            "  fi",
            "else",
            '  echo "atlas-history:fetch-failed"',
            "fi",
            f"rm -f {quoted_file}",
        )
    )


def parse_history(code: int | None, text: str, head: str) -> bool:
    """The history step's verdict: True when the bundle's ref fetched and
    its head is the pull request's own. A missing verdict or a failed
    fetch is a staging failure, named; a wrong head is too -- a bundle
    that does not carry what it claims must not be served as history."""
    # The verdict is everything after the tag up to the line's end: the
    # wrong-head verdict carries the SHA the bundle actually served, and
    # a `[^:\n]` body would stop at that colon and leave the branch
    # unreachable -- a wrong-head bundle would degrade as "gave no
    # verdict" instead of naming the head it carried.
    found = re.findall(r"^atlas-history:(\S+)$", text, re.MULTILINE)
    if code != 0 or not found:
        raise BoundaryError(
            "the history bundle gave no verdict "
            f"(exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
        )
    verdict = found[-1]
    if verdict == "ok":
        return True
    if verdict.startswith("wrong-head:"):
        raise BoundaryError(
            "the history bundle's head is not the pull request's: "
            f"{verdict.removeprefix('wrong-head:')}"
        )
    raise BoundaryError(
        "the history bundle could not be fetched into the staged repository"
    )


COLLECTION_BOUND_S = 300
COLLECTION_BUDGET_S = COLLECTION_BOUND_S + KILL_AFTER_S + 60.0


def collection_script(
    root: str,
    git: str,
    scratch: str,
    head: str,
    python: TrustedPython,
) -> str:
    """One staging exec (D80's 2026-11-26 update): a fresh disposable copy
    of the HEAD tree (`stage_copy_steps` -- its exit is framed as its own
    STAGE block, so a copy that could not be built is a staging failure,
    never a verdict), then `pytest --co -q` in it, run as the same
    non-root user the execution tools run as, bounded on its own. The
    verdict is one `atlas-collect` line -- the exit status and a tail of
    the combined output base64-encoded -- so a collection or import
    failure reaches the controller as the named `test environment is
    broken` gap instead of surfacing later as silent INCONCLUSIVE
    mutants."""
    quoted_root = shlex.quote(root)
    quoted_scratch = shlex.quote(scratch)
    collect = (
        f"( cd {quoted_scratch}; ulimit -f 16384; "
        f"{guarded_env_exports(scratch)}"
        "export PYTHONDONTWRITEBYTECODE=1; "
        f"exec timeout -k {KILL_AFTER_S} {COLLECTION_BOUND_S} "
        f"{as_nobody(python, python.quoted + ' -I -B -m pytest --co -q')} "
        ") > collect_out 2> collect_err"
    )
    return "\n".join(
        (
            f"cd {quoted_root}",
            *stage_copy_steps(root, git, scratch, head),
            "stage=$?",
            'if [ "$stage" = 0 ]; then',
            collect,
            "  s=$?",
            "  cat collect_out collect_err > collect_both 2>/dev/null",
            f'  echo "{COLLECT_TAG}:$s:$(tail -c 1024 collect_both | base64 -w0)"',
            "else",
            f'  echo "{COLLECT_TAG}:-1:"',
            "fi",
            f"rm -rf {quoted_root}/{SCRATCH_DIR} collect_out collect_err collect_both",
        )
    )


def parse_collection(code: int | None, text: str) -> tuple[bool, str]:
    """The collection probe's verdict from its `atlas-collect` line: exit
    0 is a working environment; any other exit is a broken one whose note
    is the decoded output tail. A missing line, a non-zero exec, or a
    `-1` (the copy could not be built) raises `BoundaryError` -- those
    are staging failures, not verdicts."""
    found = re.findall(
        rf"^{COLLECT_TAG}:(-?\d+):([A-Za-z0-9+/=]*)$", text, re.MULTILINE
    )
    if code != 0 or not found:
        raise BoundaryError(
            "the collection probe gave no verdict "
            f"(exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
        )
    exit_status, tail = found[-1]
    if exit_status == "-1":
        raise BoundaryError(
            "the head copy for the collection probe could not be built: "
            f"{guest_text(text, GUEST_TAIL_CHARS)}"
        )
    if exit_status in ("0", "5"):
        # 0 collects; 5 is pytest's "no tests collected" -- a diff whose
        # copy carries no test files is not a broken environment, and the
        # execution tools still work on it (a selector or an approved
        # command can name what to run). Any other exit is collection or
        # import failure: the named broken-environment gap.
        return True, ""
    return False, guest_text(base64.b64decode(tail).decode("utf-8", "replace"), 512)


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
        # The copy is the PR's own writable space: its tests and the
        # collection probe run in it as the no-root guard's user, which
        # on a root runner is not the user that built it -- and a test
        # suite that writes into its own checkout (a conftest generating
        # a file, a codegen test) fails on a read-only tree. Everything
        # outside the copy -- the staged repository, the trees, the
        # controller's indexes -- keeps the builder's ownership. The
        # mkdir is the scratch work directory's own creation: the
        # `mkdir -p` above makes the scratch root, and `checkout-index`
        # creates the work directory only when the tree has an entry --
        # an empty head tree must stage and collect nothing, not fail
        # the copy build on a chmod of a path that was never made.
        f"mkdir -p {quote(scratch)} && chmod -R a+rwX {quote(scratch)}",
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
    `GIT_PATHS`, and its version line (untrusted, for telemetry). The
    version is the first line after the path, cut at the first `atlas-`
    marker: the same exec carries the pytest probe's labelled output, the
    live run's telemetry showed it glued past git's own newline, and the
    version is the one field that must not quote the probe's lines."""
    _, found, after = text.rpartition(f"{GIT_TAG}:")
    path, _, version = after.partition("\n")
    version = version.split("atlas-")[0].rstrip()
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
    history_bundle: bytes | None = None,
    history_base: str = "",
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
    shim = choose_shim(text, pytest_candidates, pytest)
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
    collection_ok, collection_note = True, ""
    if pytest is not None:
        scratch = f"{root}/{SCRATCH_DIR}/{SCRATCH_WORK}"
        code, text = session.exec(
            "collection probe",
            collection_script(root, git, scratch, commits[Rev.HEAD], pytest),
            stage="bridge staging",
            budget_s=COLLECTION_BUDGET_S,
        )
        collection_ok, collection_note = parse_collection(code, text)
    history_head, history_note = "", ""
    if history_bundle is not None:
        # The history is optional context: a bundle over the cap, a fetch
        # that failed, or a bundle that is not what it claims degrade to
        # the named no-history gap on the history tools -- the review's
        # other tools are untouched -- never a failed run.
        try:
            upload_history_bundle(session, history_bundle, root)
            code, text = session.exec(
                "history fetch",
                history_fetch_script(root, git, history_base, trees.head_sha),
                stage="bridge staging",
                budget_s=UNPACK_BUDGET_S,
            )
            if parse_history(code, text, trees.head_sha):
                history_head = trees.head_sha
        except BoundaryError as exc:
            history_note = str(exc)
    return Staged(
        root,
        git,
        MappingProxyType(commits),
        version,
        pytest,
        shim,
        history_head,
        history_base,
        history_note,
        trees.head_sha,
        collection_ok,
        collection_note,
        pytest is not None,
    )
