# SPDX-License-Identifier: MIT
"""The closed, read-only git tool bridge over a staged runner (D31 gap 2,
D34 (2), D39), plus the two structured execution tools `run_tests` and
`mutate` (D80).

`run_bridge` stages the sources on a fresh disposable runner
(`bridge_staging`) and hands a `Bridge` to the caller. Each `Bridge.call`
is validated first (`bridge_args`); an invalid call never runs. A valid
git call becomes a fixed git argv, every value shell-quoted, run through
the runner's one exec wrapper under `timeout` and a file-size limit. The
two execution tools run the staged HEAD tree's pytest on a fresh
disposable copy of that tree (`stage_copy_steps`), the argv built by the
bridge: the model names a test selector or a mutant spec -- a path, a
line and one closed-set operator -- never a shell string. Output
comes back base64-encoded, so neither the exec framing nor in-band text
can bend it, and is capped at the tool's byte and line bounds with the
cut reported. Every call, rejected or run, is in the bridge's ledger.

Results are repository content and are not redacted (D34's secret rule):
each is scanned with `detect_secrets`, and every hit is reported by path,
line and pattern, never by value; a hit outside HEAD or in a file the PR
did not change is pre-existing. Runtime text (git's stderr, a test
process's stderr) is redacted. Test output is PR-controlled untrusted
text like any other result: size-capped, scanned, nonce-fenced by the
caller, and never anything but evidence a finding may cite -- it cannot
assert one.
"""

from __future__ import annotations

import ast
import base64
import codecs
import hashlib
import io
import itertools
import json
import os
import re
import tarfile
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from atlas_reviewer.approval import RunApprovals
from atlas_reviewer.bridge_args import (
    MAX_READ_LINES,
    QUOTED_CHARS,
    TOOLS,
    Call,
    RejectedError,
    Rev,
    path_problem,
    validate,
)
from atlas_reviewer.bridge_staging import (
    BRIDGE_ROOT,
    GIT_ENV,
    GIT_OPTIONS,
    PYTEST_CANDIDATES,
    SCRATCH_DIR,
    SourceTrees,
    Staged,
    as_nobody,
    check_sizes,
    guarded_env_exports,
    history_fetch_script,
    mutant_commit_steps,
    parse_history,
    parse_staged,
    quote,
    stage,
    stage_copy_steps,
    stage_script,
    upload_history_bundle,
)
from atlas_reviewer.diffs import risk_tier, split_files
from atlas_reviewer.domain import CleanupStatus, RunnerReport, RunnerStatus
from atlas_reviewer.grounding import (
    GroundingCommand,
    GroundingPlan,
    GroundingResult,
    grounding_plan,
)
from atlas_reviewer.guest_unpack import KILL_AFTER_S
from atlas_reviewer.interpreter import TrustedPython
from atlas_reviewer.notes import quote_untrusted
from atlas_reviewer.ports import (
    BoundaryError,
    Clock,
    RunnerLedger,
    SpritesApi,
    StreamTimeoutError,
)
from atlas_reviewer.prompt import RepoText
from atlas_reviewer.redact import RedactedText, Redactor, SecretScan, detect_secrets
from atlas_reviewer.runner import (
    DEFAULT_CREATE_RETRIES,
    FIRST_FRAME_BUDGET_S,
    GUEST_TAIL_CHARS,
    UNPACK_BUDGET_S,
    Session,
    SetupSpec,
    guest_text,
    run_session,
)
from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits
from atlas_reviewer.telemetry import ERROR, Telemetry

HEADER = "__ATLAS_BRIDGE__"
UNKNOWN_TOOL = "(unknown tool)"
RUN_HEADER = "__ATLAS_RUN__"
MUT_HEADER = "__ATLAS_MUT__"
STAGE_HEADER = "__ATLAS_STAGE__"
STDERR_BYTES = 2_000
STDERR_CHARS = 1_000
# 512-byte blocks under dash (8 MiB); a shell counting 1 KiB blocks allows 16.
RAW_OUTPUT_BLOCKS = 16_384
# The hard limit's own cap, in the same 512-byte blocks (512 MiB). Under
# dash a plain `ulimit -f` sets BOTH limits, which made every later
# raise-permitted attempt fail with EPERM -- the reviewed repo's own test
# suite raises its soft file-size limit when its tests stage bridges and
# write their fixtures, and under a hard limit pinned at the soft one
# every such raise is refused. The exec sets the soft limit at today's
# bound first (leaving the inherited hard) and then the hard cap; the
# measured result inside a bounded exec on the local runner is exactly
# soft 8388608 / hard 536870912, and on the live runner the exec's user is
# root, so the raise always takes before the guard drops to nobody. The
# cap sits at 512 MiB because the raises a reviewed repo legitimately
# makes reach 256 MiB: the #661 anchor's own guest unpack sets
# `ulimit -f 524288` (256 MiB, both limits) when its tests stage nested
# bridges, and a cap below that refuses the raise, collapses those
# suites, and turns the sweep's scoped runs for their modules
# inconclusive -- measured on the anchor, baseline exit 1, before the
# cap moved above it. The cap is enforced inside the exec on both
# executors: the guest inherits the 512 MiB hard and cannot raise its
# own hard above it (the raise test pins the refusal), and the only case
# the hard-set itself skips is an inherited hard already BELOW the cap --
# a raise the executor may not make -- where that lower inherited hard is
# the bound. Outside a bounded exec nothing here applies: a bare process
# on a host whose inherited hard is unlimited can raise as it likes,
# which is the host's own posture, not the exec's. The trade-off the cap
# buys: PR code running inside the runner can raise its own file-size
# limit up to the cap before the kernel stops it, so a PR test can write
# up to 512 MiB per stream where the soft limit would have stopped it at
# 8 -- bounded, documented, and above what the repo's own tests
# legitimately raise to, while the run's own output stays bounded by the
# soft limit and the read caps, and the writes land in the disposable
# copy `rm -rf` reclaims.
HARD_OUTPUT_BLOCKS = 1_048_576
# The two ulimit commands every bounded exec opens with (see
# HARD_OUTPUT_BLOCKS for why there are two).
FILE_LIMIT_CMDS = (
    f"ulimit -S -f {RAW_OUTPUT_BLOCKS} 2>/dev/null || ulimit -f {RAW_OUTPUT_BLOCKS}; "
    f"ulimit -H -f {HARD_OUTPUT_BLOCKS} 2>/dev/null || true"
)
EXEC_SLACK_S = 15.0
# The mutation edit runs under its own `timeout`, and a `mutate` call runs
# two test processes (baseline, mutated), that edit, and two staging
# checkouts of the head tree, inside one exec budget.
MUTATE_EDIT_TIMEOUT_S = 30
MUTATE_EDIT_SLACK_S = 30.0
MUTATE_STAGE_SLACK_S = 60.0
# A re-stage (round 2) rebuilds the repository and trees from freshly
# uploaded, digest-checked tarballs, and re-applies a recorded mutation.
RESTAGE_BUDGET_S = UNPACK_BUDGET_S + MUTATE_EDIT_TIMEOUT_S + EXEC_SLACK_S
_TIMED_OUT = 124
_KILLED = 137
_FILE_TOO_LARGE = 153
_GREP_NO_MATCH = 1
_B64 = r"[A-Za-z0-9+/=]*"
_REPLY = re.compile(
    rf"{HEADER} (\d+) (\d+) (\d+) (\d+) (\d+)(?:\n({_B64}))?(?:\n({_B64}))?",
    re.ASCII,
)
# The final pytest summary line, `-q`'s last line of output: counts and
# labels, or "no tests ran", then the elapsed seconds. Nothing else in the
# output is parsed for anything.
_SUMMARY = re.compile(
    r"^[= ]*((?:\d+ [a-z]+(?:, )?)+|no tests ran) in \d+(?:\.\d+)?s.*[= ]*$"
)
_SUMMARY_TOKENS = re.compile(r"(\d+) ([a-z]+)")
_PLURAL = {"error": "errors", "warning": "warnings"}
_DIGIT = re.compile(r"\d+", re.ASCII)
_MUT_COMMIT = re.compile(r"[0-9a-f]{40}")
_HUNK = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_PLAIN_PATH = re.compile(r"[\x21-\x7e]+")
_CONTINUATION = bytes(range(0x80, 0xC0))

# The tools that execute PR-controlled code on a staged copy (D80). One
# test process runs at a time: the lens loop runs a turn's calls in order,
# and each call's script runs its processes to completion before it
# returns.
RUN_TOOLS = frozenset({"run_tests", "mutate", "run_probe"})
BASH_TOOLS = frozenset({"bash"})
HISTORY_TOOLS = frozenset({"git_log", "git_show", "git_blame"})

# The file-content tools answered from the controller's own copy of the
# trees and the deterministic splice (D80 round 2): executed code can
# leave processes running in the runner (the per-call sweep that once
# killed them is retired -- see D80's update), so nothing read back from
# the runner is trusted as content. `read_file` and `list_files` are always
# local; `grep` is local only in its fixed-string mode -- a substring
# scan is linear and cannot crash -- while the regex mode stays on the
# runner, where `timeout` bounds it, where a bad pattern is git's exit
# status (a gap, not a `re.error`), and where the dialect is git grep's
# POSIX basic regex, unchanged since before the local path existed
# (D80 round 3).
LOCAL_TOOLS = frozenset({"read_file", "grep", "list_files"})

# The tools that still read the runner's repository (the diff trio):
# executed code can leave processes running between the rebuild and the
# read (the per-call sweep is retired -- see D80's update), so the
# integrity here rests on the re-stage from the controller-held tarballs
# and on the finding gate, whose quotes verify against controller-held
# head content a forged diff cannot mint.

PYTEST_FLAGS = ("-q", "--color=no", "-p", "no:cacheprovider")

_DIFF = ("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--find-renames")


class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed out"
    TOO_LARGE = "output over the raw limit"
    REJECTED = "rejected"
    OVER_SESSION_LIMIT = "session limit reached"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolLimits:
    """`max_bytes` and `max_lines` bound what one call returns;
    `timeout_s` is the in-runner `timeout`, at least 1 (`timeout 0`
    disables it)."""

    max_bytes: int
    timeout_s: int
    max_lines: int | None = None

    def __post_init__(self) -> None:
        sizes = (self.max_bytes, self.timeout_s, self.max_lines or 1)
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("tool limits must be positive integers")


@dataclass(frozen=True)
class SessionLimits:
    """Bounds on what one attempt of a lens may spend of the bridge
    session it runs on (#693): calls made (rejected ones too) and output
    bytes shown. A call is never shown more than the output left; once
    either is spent, calls are refused without running. `max_test_runs`
    and `max_mutants` (D80) bound the two execution tools below the call
    cap, so a lens cannot spend its whole session on executions; each
    `mutate` call runs two test processes (the baseline and the mutated
    run) but spends one mutant. A lens's retry
    runs on the same disposable runner session, so `begin_attempt` starts
    these counters over per attempt -- a retry begins with the full
    budget, and the session as a whole is bounded by the review's wall
    clock instead."""

    max_calls: int = 64
    max_output_bytes: int = 1024 * 1024
    # Provisional defaults pending the owner (D39's standing rule): each
    # below the default call cap, so executions cannot be the whole of an
    # attempt's budget.
    max_test_runs: int = 8
    max_mutants: int = 8

    def __post_init__(self) -> None:
        sizes = (
            self.max_calls,
            self.max_output_bytes,
            self.max_test_runs,
            self.max_mutants,
        )
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("session limits must be positive integers")


# Working defaults pending the owner (D39): D31's 12 turns per lens at a
# few calls each, and its about 10k characters of tool output per turn.
DEFAULT_SESSION = SessionLimits()

# The controller's own listing of the PR's renames, for `diff_file`.
RENAME_LIMITS = ToolLimits(1024 * 1024, 10)

# D31's proposed bounds, working defaults pending the owner (D34).
DEFAULT_LIMITS: Mapping[str, ToolLimits] = MappingProxyType(
    {
        "diff_stat": ToolLimits(16 * 1024, 10),
        "diff_file": ToolLimits(32 * 1024, 10),
        "list_files": ToolLimits(32 * 1024, 10, 2_000),
        "read_file": ToolLimits(32 * 1024, 10, MAX_READ_LINES),
        "grep": ToolLimits(32 * 1024, 15, 200),
        # D80: `timeout_s` is one test process's wall clock (a `mutate`
        # call runs two of them), and `max_bytes` caps one run's captured
        # output, shown from its end where pytest's summary and its
        # failures sit. Provisional defaults pending the owner (D39's
        # standing rule), bounded by the same session limits as reads.
        # The 2026-11-26 environment-parity slice (D80's update) raises
        # the two execution tools' per-process clock from 60s to 180s,
        # because the repo's own full suite takes about 74s on the box --
        # a whole-suite baseline under `mutate` (two processes, one call)
        # could not fit under the old cap, and every whole-suite run
        # timed out into an INCONCLUSIVE. `ATLAS_TEST_TIMEOUT_S`
        # overrides it between 30s and 600s (`run_tool_limits`); the
        # review's wall clocks still bound everything above this.
        "run_tests": ToolLimits(16 * 1024, 180),
        "mutate": ToolLimits(16 * 1024, 180),
        # The probe runs one bounded pytest process like run_tests does
        # (D80's probe-tool update), so it shares the clock and the output
        # cap; the override applies to it with the run tools.
        "run_probe": ToolLimits(16 * 1024, 180),
        # The read-only history tools (D80's git-history update): a log
        # and a blame are line-shaped reads, a show is byte-shaped; all
        # three are read-only over the staged repository's real history.
        "git_log": ToolLimits(16 * 1024, 15, 200),
        "git_show": ToolLimits(16 * 1024, 15),
        "git_blame": ToolLimits(16 * 1024, 15, 200),
        # The bash tool (D80's bash-tool update): one bounded command in
        # the copy, the same output cap and a line cap like a read, and a
        # clock like the execution tools'.
        "bash": ToolLimits(16 * 1024, 60, 200),
    }
)

# The operator's override for one test process's wall clock
# (`run_tool_limits`): a setting, not a credential, so the service child
# is allowed to receive it (service_run._CHILD_ALLOWED).
TEST_TIMEOUT_ENV = "ATLAS_TEST_TIMEOUT_S"
_TEST_TIMEOUT_MIN_S = 30
_TEST_TIMEOUT_MAX_S = 600


def run_tool_limits(
    env: Mapping[str, str],
    limits: Mapping[str, ToolLimits] = DEFAULT_LIMITS,
) -> Mapping[str, ToolLimits]:
    """The execution tools' effective limits: `limits` with
    `ATLAS_TEST_TIMEOUT_S`'s per-process test clock applied to
    `run_tests` and `mutate` when the variable names one. An unset or
    empty variable is the defaults unchanged. A value that is not an
    integer, or outside the 30-600s bounds -- below 30s cannot run a
    real suite, above 600s can eat a lens wall by itself -- raises
    `BoundaryError` naming the variable, which `run_bridge` turns into
    the run's named FAILED report."""
    raw = env.get(TEST_TIMEOUT_ENV, "")
    if raw == "":
        return limits
    try:
        seconds = int(raw)
    except ValueError:
        raise BoundaryError(
            f"{TEST_TIMEOUT_ENV} must be an integer number of seconds, not {raw!r}"
        ) from None
    if not _TEST_TIMEOUT_MIN_S <= seconds <= _TEST_TIMEOUT_MAX_S:
        raise BoundaryError(
            f"{TEST_TIMEOUT_ENV} must be between {_TEST_TIMEOUT_MIN_S} "
            f"and {_TEST_TIMEOUT_MAX_S} seconds, not {seconds}"
        )
    return MappingProxyType(
        {
            **limits,
            "run_tests": replace(limits["run_tests"], timeout_s=seconds),
            "mutate": replace(limits["mutate"], timeout_s=seconds),
            "run_probe": replace(limits["run_probe"], timeout_s=seconds),
        }
    )


# -------------------------------------------------------------------- tools


@dataclass(frozen=True)
class _Plan:
    """The git argv after `git <options>` and the view of its output that
    is returned (`$1` is the raw output file)."""

    argv: tuple[str, ...]
    view: str = 'cat "$1"'
    nul_records: bool = False


def _plan(call: Call, commits: Mapping[Rev, str], paths: tuple[str, ...]) -> _Plan:
    """`paths` are what `diff_file` diffs: its path, and the other side of
    a rename it is part of."""
    commit = commits
    span = f"{commit[Rev.BASE]}...{commit[Rev.HEAD]}"
    rev = commit.get(call.get("rev")) if "rev" in dict(call.args) else None
    pathspec = _pathspec(call.get("prefix")) if "prefix" in dict(call.args) else ()
    match call.tool:
        case "diff_stat":
            return _Plan((*_DIFF, "--stat=200", span))
        case "renames":
            return _Plan((*_DIFF, "-z", "--name-status", "--diff-filter=R", span))
        case "diff_file":
            view = f'tail -c +{call.get("offset") + 1} "$1"'
            return _Plan((*_DIFF, span, "--", *paths), view)
        case "list_files":
            ls_tree = ("ls-tree", "-r", "-z", "--name-only", str(rev), *pathspec)
            return _Plan(ls_tree, nul_records=True)
        case "read_file":
            view = f"sed -n '{call.get('start')},{call.get('end')}p' \"$1\""
            return _Plan(("cat-file", "blob", f"{rev}:{call.get('path')}"), view)
    mode = "-E" if call.get("regex") else "-F"
    grep = ("grep", "-z", "-n", "-I", "--no-color", "--max-count=50", mode)
    return _Plan((*grep, "-e", call.get("pattern"), str(rev), *pathspec))


def _pathspec(prefix: str) -> tuple[str, ...]:
    return ("--", prefix) if prefix else ()


def call_script(
    staged: Staged,
    call: Call,
    limits: ToolLimits,
    paths: tuple[str, ...] = (),
    commits: Mapping[Rev, str] | None = None,
) -> str:
    """Runs one tool into files under the bridge root, then prints a
    header (git's exit status, the view's, the bytes and lines of the
    view, and the bytes of its capped part) and that capped part and
    stderr, each base64-encoded on its own line. The controller checks
    the decoded part against its byte count, so a failed encoding is an
    error, not an empty result. `commits` is the revision map the call
    resolves against: the bridge's own, which carries MUTANT (D80) once a
    `mutate` call has made one; None means the staged revisions."""
    plan = _plan(call, staged.commits if commits is None else commits, paths)
    git = " ".join((quote(staged.git), "--git-dir=repo.git", *GIT_OPTIONS))
    argv = " ".join(quote(a) for a in plan.argv)
    z = " -z" if plan.nul_records else ""
    lines = f"head{z} -n {limits.max_lines} view | " if limits.max_lines else ""
    count = "tr -dc '\\000' < view | wc -c" if plan.nul_records else "wc -l < view"
    return "; ".join(
        (
            f"cd {quote(staged.root)}",
            f"export {' '.join(GIT_ENV)}",
            (
                f"( {FILE_LIMIT_CMDS}; exec timeout -k {KILL_AFTER_S} "
                f"{limits.timeout_s} {git} {argv} ) > out 2> err"
            ),
            "s=$?",
            f"view() {{ {plan.view}; }}",
            "view out > view",
            "v=$?",
            f"{lines}head -c {limits.max_bytes} {'' if lines else 'view'} > shown",
            f'echo "{HEADER} $s $v $(wc -c < view) $({count}) $(wc -c < shown)"',
            "base64 -w0 < shown; echo",
            f"head -c {STDERR_BYTES} err | base64 -w0; echo",
            "rm -f out err view shown",
        )
    )


# The read-only history tools (D80's git-history update, the scope
# addendum's slice H): git_log over the pull request's commit range,
# git_show for a commit -- or a commit plus path -- and git_blame for a
# path and line span, against the real history the staged repository
# fetched from the controller's bundle. A revision is valid when it is an
# ancestor of the pull request's head or of its base tip -- the PR's
# range, or anything reachable from base -- and anything else is refused
# before git runs. The tools are read-only: log, show and blame write
# nothing, run under the same runner sandbox (deny-all egress, the
# timeout and the byte/line caps), and never touch the working copy.


def bash_script(
    staged: Staged, call: Call, limits: ToolLimits, path: str | None = None
) -> str:
    """One exec for `bash` (D80's bash-tool update): the same disposable
    copy of the head tree `run_tests` builds, a `.git` file that points
    the copy's git at the staged repository -- so git history over the
    pull request's range is readable inside the copy, the way the
    history tools read it -- then the model's one command run as the
    non-root user through the same guard, under the same clock and
    output caps and the runner's verified deny-all policy. The copy is
    removed again: nothing the command writes reaches the repository's
    trees, and anything it writes into the staged repository itself is
    discarded by the next call's re-stage -- later calls never read what
    an earlier command left behind. `path` replaces the exec's minimal
    PATH (`/usr/bin:/bin`) inside the copy: the controller's grounding
    pre-pass passes the setup-provisioned tools' own bin directory, so
    the repo's declared commands resolve the way the setup environment
    provides them; the model's bash keeps the minimal env."""
    scratch = quote(staged.scratch)
    root = quote(staged.root)
    assert staged.shim_python is not None  # the caller refuses the call before this
    command = call.get("command")
    guarded = as_nobody(staged.shim_python, f"/bin/sh -c {quote(command)}")
    env_exports = guarded_env_exports(staged.scratch) + (
        f" export PATH={quote(path)};" if path else ""
    )
    return "\n".join(
        (
            f"cd {root}",
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            "stage=$?",
            f'echo "{STAGE_HEADER} $stage"',
            'if [ "$stage" = 0 ]; then',
            f"  ( cd {scratch}; {FILE_LIMIT_CMDS};",
            env_exports,
            "  export PYTHONDONTWRITEBYTECODE=1;",
            (
                f"  exec timeout -k {KILL_AFTER_S} {limits.timeout_s} "
                f"{guarded} ) > out 2> err"
            ),
            "  s=$?",
            f"  tail -c {limits.max_bytes} out > shown",
            f'  echo "{RUN_HEADER} $s $(wc -c < out) $(wc -l < out) $(wc -c < shown)"',
            "  base64 -w0 < shown; echo",
            f"  head -c {STDERR_BYTES} err | base64 -w0; echo",
            "fi",
            f"rm -rf {root}/{SCRATCH_DIR} out err shown",
        )
    )


def _grounding_path(python: TrustedPython) -> str:
    """The PATH the grounding pre-pass's commands run under: the trusted
    interpreter's own bin directory first -- where the setup spec's
    `pip install --no-user` puts the repo's declared tools' executables,
    which the runner's minimal env (`/usr/bin:/bin`) does not carry --
    then the usual system dirs."""
    bin_dir = python.path.rsplit("/", 1)[0]
    parts = [bin_dir] if bin_dir != "/usr/bin" else []
    return ":".join((*parts, "/usr/local/bin", "/usr/bin", "/bin"))


def history_script(staged: Staged, call: Call, limits: ToolLimits) -> str:
    """One history tool's exec, framed like the other git tools'. The rev
    guard runs first inside the exec: a revision neither the head nor the
    base tip reaches exits 99, which the controller reports as a rejected
    call carrying the guard's own text."""
    git = " ".join((quote(staged.git), "--git-dir=repo.git", *GIT_OPTIONS))
    head = quote(staged.history_head)
    base = quote(staged.history_base)
    if call.tool == "git_log":
        argv = f"log --oneline --no-decorate {base}..{head}"
        precheck = "true"
    elif call.tool == "git_show":
        rev = quote(call.get("rev"))
        path = call.get("path")
        arg = f"{rev} -- {quote(path)}" if path else rev
        argv = f"show {arg}"
        # The guard runs with the same staged-repository git the tool
        # itself uses: a bare `git` would read whatever the runner's
        # default repository is, which is not the reviewed history.
        precheck = (
            f"{git} merge-base --is-ancestor {rev} {head} || "
            f"{git} merge-base --is-ancestor {rev} {base}"
        )
    else:
        path = quote(call.get("path"))
        start = call.get("line")
        end = call.get("end_line") or start
        argv = f"blame --date=short -L {start},{end} {head} -- {path}"
        precheck = "true"
    shown_source = (
        f"head -n {limits.max_lines} out | head -c {limits.max_bytes}"
        if limits.max_lines
        else f"head -c {limits.max_bytes} out"
    )
    # The control structures join with newlines: a `; `-joined `then;` or
    # `else;` is a shell syntax error, and the exec would answer nothing.
    return "\n".join(
        (
            f"cd {quote(staged.root)}",
            f"export {' '.join(GIT_ENV)}",
            f"if {precheck}; then",
            (
                f"  ( {FILE_LIMIT_CMDS}; exec timeout -k {KILL_AFTER_S} "
                f"{limits.timeout_s} {git} {argv} ) > out 2> err"
            ),
            "  s=$?",
            "else",
            f"  s={_REFUSED_EXIT}",
            '  echo "the revision is outside the pull request range and base history" > out',
            "fi",
            "v=0",
            f"{shown_source} > shown",
            f'echo "{HEADER} $s $v $(wc -c < out) $(wc -l < out) $(wc -c < shown)"',
            "base64 -w0 < shown; echo",
            f"head -c {STDERR_BYTES} err 2>/dev/null | base64 -w0; echo",
            "rm -f out err shown",
        )
    )


def _page(call: Call, reply: _Reply) -> tuple[int, bytes]:
    """The shown bytes without a UTF-8 character split by the cut: an
    incomplete one at the end when the output was cut there, and the rest
    of one at the start of a `diff_file` page past offset 0 (it belongs to
    the page before). Returns how many leading bytes were dropped."""
    data = reply.content
    offset = call.get("offset") if call.tool == "diff_file" else 0
    skipped = _continuation_bytes(data) if offset else 0
    cut_end = len(data) < reply.total_bytes
    end = len(data) - (_incomplete_tail(data) if cut_end else 0)
    return skipped, data[skipped : max(end, skipped)]


def _continuation_bytes(data: bytes) -> int:
    head = data[:3]
    return len(head) - len(head.lstrip(_CONTINUATION))


def _incomplete_tail(data: bytes) -> int:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    decoder.decode(data, final=False)
    pending, _ = decoder.getstate()
    return len(pending)


class _LostOutputError(BoundaryError):
    """The tool ran, but its output did not arrive intact."""


def _rename_pairs(reply: _Reply) -> Mapping[str, tuple[str, str]]:
    """`R<score>\0<old>\0<new>\0` per rename (`--name-status -z`), keyed
    by both sides. A listing that failed or was cut raises, since a
    `diff_file` without it could show a rename as an add or a delete."""
    if reply.code != 0 or reply.shown_bytes < reply.total_bytes:
        raise BoundaryError(
            f"the PR's renames could not be listed in full (exit {reply.code})"
        )
    fields = reply.content.decode("utf-8", errors="replace").split("\0")
    pairs = [
        (old, new)
        for status, old, new in zip(
            fields[0::3], fields[1::3], fields[2::3], strict=False
        )
        if status.startswith("R")
    ]
    return MappingProxyType({path: pair for pair in pairs for path in pair})


@dataclass(frozen=True)
class BridgeSecret:
    """A possible committed secret in a result: its pattern label and,
    where the result locates it, the path and line (in the revision read,
    or the head side of a diff). Never the value."""

    label: str
    path: str | None
    line: int | None
    preexisting: bool


class MutantOutcome(StrEnum):
    """What a `mutate` call's mutant did, as the controller established it
    from the two runs' reported exits and its own parse of their summary
    lines (D80). Only a mutant whose baseline run passed and whose mutated
    run also passed is `survived` -- the finding a lens may report. An
    inconclusive mutant is never a survived one: it is a gap, whatever the
    lens wanted it to be."""

    SURVIVED = "survived"
    KILLED = "killed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class TestSummary:
    """The counts on one run's final pytest summary line, parsed from the
    run's captured output and nothing else in it. `ran` is False when the
    line said no test ran; a summary the output did not carry is None on
    the run record, and the exit status decides alone."""

    counts: tuple[tuple[str, int], ...] = ()
    ran: bool = True

    def count(self, label: str) -> int:
        return sum(n for name, n in self.counts if name == label)

    @property
    def ran_any(self) -> bool:
        """Whether a test is reported to have run to a pass or a failure:
        skips and deselections are not runs."""
        return self.ran and any(
            self.count(label) for label in ("passed", "failed", "errors")
        )

    def render(self) -> str:
        """The counts as one controller-written fragment, in the order a
        reader expects them."""
        order = ("passed", "failed", "errors", "skipped")
        named = [(label, self.count(label)) for label in order]
        named += [pair for pair in self.counts if pair[0] not in order]
        shown = [f"{n} {label}" for label, n in named if n]
        if not self.ran:
            shown.append("no test ran")
        return ", ".join(shown) if shown else "no counts reported"


@dataclass(frozen=True)
class RunRecord:
    """One test process as the controller established it: the exit status
    the guest reported -- in-band evidence, not proof, like every status
    the exec stream carries -- and the summary the controller parsed from
    the captured output itself."""

    exit: int
    summary: TestSummary | None = None


@dataclass(frozen=True)
class MutationRecord:
    """The one mutation a `mutate` call applied: one operator at one line
    of one file of the staged copy (D80), the statement before and after
    it (PR content, quoted wherever the controller renders it), and the
    commit the mutated tree is reachable at -- empty when none was made."""

    operator: str
    path: str
    line: int
    before: str
    after: str
    commit: str
    # `drop-operand`'s kept-operand index (D80's 2026-11-26 update),
    # carried so a re-staged re-apply splices the same operand; None for
    # every other operator.
    operand: int | None = None


@dataclass(frozen=True)
class BridgeResult:
    """`content` is repository content, unredacted (D34); `error` is
    runtime text and redacted. `values` are the flagged secret values,
    kept only to scrub published output. Neither is in `repr`. The
    execution tools (D80) carry their run records, the mutation a `mutate`
    call applied, and the mutant's outcome."""

    tool: str
    args: str
    status: Status
    content: RepoText = field(repr=False)
    error: RedactedText | None
    shown_bytes: int
    total_bytes: int
    total_lines: int
    truncated: bool
    seconds: float
    secrets: tuple[BridgeSecret, ...] = ()
    next_offset: int | None = None
    values: tuple[str, ...] = field(default=(), repr=False, compare=False)
    runs: tuple[RunRecord, ...] = ()
    mutation: MutationRecord | None = None
    outcome: MutantOutcome | None = None
    outcome_reason: str = ""
    head_sha: str = ""
    # The proposed command a pre-approved addition ran (S7, D88):
    # the proposal's validated name, empty for every other result. The
    # name may be shown because it is schema-validated config (the
    # parse's own grammar), not model text.
    approved: str = ""


@dataclass(frozen=True)
class CallRecord:
    """One line of the coverage ledger: what was asked and how much came
    back, never the content."""

    tool: str
    args: str
    status: Status
    shown_bytes: int
    total_bytes: int
    truncated: bool
    seconds: float
    secrets: int


@dataclass(frozen=True)
class _Reply:
    code: int
    view_code: int
    total_bytes: int
    total_lines: int
    shown_bytes: int
    content: bytes
    stderr: bytes

    def problem(self) -> str | None:
        """Why the reply cannot be trusted as the tool's output, if it can't."""
        if self.view_code != 0:
            return f"the runner could not cut the output (exit {self.view_code})"
        if len(self.content) != self.shown_bytes:
            return (
                f"the runner's encoded output held {len(self.content)} of "
                f"{self.shown_bytes} bytes"
            )
        return None


def parse_reply(text: str) -> _Reply | None:
    """The last header the script printed and the base64 lines after it;
    None when there is none or it does not parse."""
    _, found, rest = text.rpartition(f"{HEADER} ")
    match = _REPLY.fullmatch(f"{HEADER} {rest}") if found else None
    if match is None:
        return None
    code, view_code, total, lines, shown = (int(match.group(i)) for i in range(1, 6))
    try:
        content, stderr = (
            base64.b64decode(match.group(i) or "", validate=True) for i in (6, 7)
        )
    except ValueError:
        return None
    return _Reply(code, view_code, total, lines, shown, content, stderr)


_REFUSED_EXIT = 99
_CODE_STATUS = {
    0: Status.OK,
    _TIMED_OUT: Status.TIMED_OUT,
    _KILLED: Status.TIMED_OUT,
    _FILE_TOO_LARGE: Status.TOO_LARGE,
    # The history tools' rev guard (D80's git-history update): a revision
    # outside the pull request's range and base's history is the model's
    # error to re-aim -- a rejected call, not a failed one.
    _REFUSED_EXIT: Status.REJECTED,
}


def _status(tool: str, code: int) -> Status:
    no_match = tool == "grep" and code == _GREP_NO_MATCH
    return Status.OK if no_match else _CODE_STATUS.get(code, Status.FAILED)


# ------------------------------------------------------------ run tools (D80)

# The one refusal MUTATION_SCRIPT can produce for a machinery failure
# rather than a mis-aim: the temporary write's OSError. The caller maps
# aim refusals to REJECTED (the model re-aims) and this one to the
# inconclusive path, where the executed work is charged.
_WRITE_REFUSAL = "the copy could not be written"

MUTATION_SCRIPT = """\
import ast, base64, os, sys

path, line, operator = sys.argv[1], int(sys.argv[2]), sys.argv[3]
operand = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None


def refuse(reason):
    print("no " + base64.b64encode(reason.encode()).decode())
    raise SystemExit(0)


try:
    with open(path, "rb") as handle:
        raw = handle.read()
    source = raw.decode("utf-8")
except (OSError, UnicodeDecodeError):
    refuse("the file could not be read as UTF-8 text")
try:
    tree = ast.parse(source)
except SyntaxError:
    refuse("the file does not parse")
kind = {
    "negate-condition": (ast.If, ast.While, ast.IfExp),
    "remove-guard": (ast.If,),
    "drop-operand": (ast.BoolOp,),
    "break-continue": (ast.Break, ast.Continue),
    "flip-compare": (ast.Compare,),
}[operator]
at_line = sorted(
    (node for node in ast.walk(tree) if getattr(node, "lineno", None) == line),
    key=lambda node: node.col_offset,
)
target = next((node for node in at_line if isinstance(node, kind)), None)
if target is None:
    if at_line:
        refuse("the operator does not apply to the statement at that line")
    refuse("no statement starts at that line")

# The edit is a span splice, not a whole-module rewrite: only the mutated
# span changes, so the rest of the file stays byte-identical -- comments,
# string quoting and formatting included -- and the mutated run's source
# is the head source plus one edit. Line offsets are computed over "\\n"
# only, matching how the parser numbers lines.
# The AST's column offsets are UTF-8 byte offsets, not character
# indices: a column past a multi-byte character names a position one or
# more characters earlier in the decoded text, so every column is
# converted to its character index against the line's own bytes before
# it is added to the line's offset.
byte_lines = raw.split(b"\\n")
char_lines = source.split("\\n")
if len(byte_lines) != len(char_lines):
    refuse("the file's byte and character line counts disagree")

offsets = [0]
for part in char_lines:
    offsets.append(offsets[-1] + len(part) + 1)

def span(lineno, col, end_lineno, end_col):
    line = byte_lines[lineno - 1]
    end_line = byte_lines[end_lineno - 1]
    return (
        offsets[lineno - 1] + len(line[:col].decode("utf-8")),
        offsets[end_lineno - 1] + len(end_line[:end_col].decode("utf-8")),
    )

FLIPS = {
    "Eq": ("==", "!="),
    "NotEq": ("!=", "=="),
    "Lt": ("<", ">="),
    "LtE": ("<=", ">"),
    "Gt": (">", "<="),
    "GtE": (">=", "<"),
    "Is": ("is", "is not"),
    "IsNot": ("is not", "is"),
    "In": ("in", "not in"),
    "NotIn": ("not in", "in"),
}

if operator == "negate-condition":
    start, end = span(
        target.test.lineno, target.test.col_offset,
        target.test.end_lineno, target.test.end_col_offset,
    )
    replacement = "not (" + source[start:end] + ")"
elif operator == "remove-guard":
    start, end = span(
        target.body[0].lineno, target.body[0].col_offset,
        target.body[-1].end_lineno, target.body[-1].end_col_offset,
    )
    replacement = "pass"
elif operator == "drop-operand":
    if operand is None:
        refuse("drop-operand names the operand it keeps")
    if not 1 <= operand <= len(target.values):
        refuse("the operand index is out of range")
    kept = target.values[operand - 1]
    # The whole `and`/`or` expression is the mutated span; the kept
    # operand's own source is what replaces it, so the others drop.
    start, end = span(
        target.lineno, target.col_offset, target.end_lineno, target.end_col_offset,
    )
    kstart, kend = span(
        kept.lineno, kept.col_offset, kept.end_lineno, kept.end_col_offset,
    )
    replacement = source[kstart:kend]
elif operator == "break-continue":
    start, end = span(
        target.lineno, target.col_offset, target.end_lineno, target.end_col_offset,
    )
    replacement = "continue" if isinstance(target, ast.Break) else "break"
else:
    left_end = (
        target.left.end_lineno, target.left.end_col_offset,
    )
    right_start = (
        target.comparators[0].lineno, target.comparators[0].col_offset,
    )
    start, end = span(left_end[0], left_end[1], right_start[0], right_start[1])
    region = source[start:end]
    name = type(target.ops[0]).__name__
    if name not in FLIPS:
        refuse("that comparison operator has no flip")
    old_text, new_text = FLIPS[name]
    if region.strip() != old_text:
        refuse("the comparison's spelling is not the operator the AST named")
    lead = region[: len(region) - len(region.lstrip())]
    replacement = lead + new_text + region[len(lead) + len(old_text):]
before = source[start:end]
mutated = source[:start] + replacement + source[end:]
try:
    compile(mutated, path, "exec")
except SyntaxError:
    refuse("the mutated file does not compile")
temporary = path + ".atlas-mutant"
try:
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(mutated)
    os.replace(temporary, path)
except OSError:
    refuse("the copy could not be written")
print(
    "ok " + base64.b64encode(before.encode()).decode()
    + " " + base64.b64encode(replacement.encode()).decode()
)
"""


def _pytest_argv(staged: Staged, selector: str) -> str:
    """The one argv shape the execution tools run, built here and never by
    the model: the trusted interpreter staging resolved, isolated (`-I`,
    so no `PYTHON*` variable and no user site reach it), `-B` (isolated
    mode ignores `PYTHONDONTWRITEBYTECODE`, so the flag is what keeps
    bytecode out of the copy the mutant is committed from), pytest module
    mode (so a PR file named `pytest.py` cannot shadow the runner
    machinery), fixed flags, and the model's selector as one positional
    argument."""
    flags = " ".join(PYTEST_FLAGS)
    assert staged.pytest is not None  # the caller refuses the call before this
    return f"{staged.pytest.quoted} -I -B -m pytest {flags}{_selector(selector)}"


def _selector(selector: str) -> str:
    return f" {quote(selector)}" if selector else ""


# ------------------------------------------------- controller-side contents


def _tree_files(tarball: bytes) -> dict[str, bytes]:
    """The controller's own copy of one staged tree, extracted in memory
    from the tarball it already holds (`D80` round 2): the same
    `--strip-components=1` shape the runner's extraction uses, keeping
    every regular file. Names decode the way tar names do (the
    filesystem encoding, with surrogates for bytes that are not UTF-8);
    a name the read tools would refuse (`path_problem`'s rules) still
    lives in the map -- `list_files` lists it and marks it unreadable,
    and `grep` can match inside it, exactly as the runner's tools did --
    while `read_file` can never name it: `validate` rejects such a path
    before anything runs. Nothing is extracted to disk."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for member in archive:
            if not member.isreg():
                continue
            _, _, name = member.name.partition("/")
            if not name or name.endswith("/"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:  # pragma: no cover - isreg implies bytes
                continue
            files[name] = extracted.read()
    return files


# The comparison flip's spelling pairs, keyed by the ast operator class
# name: negation pairs, longest first when it matters (`is not` before
# `is`). The runner's MUTATION_SCRIPT carries the same table; the parity
# test pins the two together.
_COMPARE_FLIPS = {
    "Eq": ("==", "!="),
    "NotEq": ("!=", "=="),
    "Lt": ("<", ">="),
    "LtE": ("<=", ">"),
    "Gt": (">", "<="),
    "GtE": (">=", "<"),
    "Is": ("is", "is not"),
    "IsNot": ("is not", "is"),
    "In": ("in", "not in"),
    "NotIn": ("not in", "in"),
}


_SPLICE_KINDS = {
    "negate-condition": (ast.If, ast.While, ast.IfExp),
    "remove-guard": (ast.If,),
    "drop-operand": (ast.BoolOp,),
    "break-continue": (ast.Break, ast.Continue),
    "flip-compare": (ast.Compare,),
}


def _splice_target(at_line: list[ast.AST], operator: str) -> ast.AST | None:
    """The node at the named line the operator applies to: the first node
    of the operator's kind in source-column order."""
    kind = _SPLICE_KINDS[operator]
    return next((node for node in at_line if isinstance(node, kind)), None)


def _splice_edit(
    source: str,
    span: Callable[[int, int, int | None, int | None], tuple[int, int]],
    target: ast.AST,
    operator: str,
    operand: int | None,
) -> tuple[int, int, str] | None:
    """The mutated span and its replacement text, or None when the edit
    does not apply -- the same per-operator shapes MUTATION_SCRIPT
    splices, pinned together by the parity test."""
    if operator == "negate-condition":
        assert isinstance(target, (ast.If, ast.While, ast.IfExp))
        start, end = span(
            target.test.lineno, target.test.col_offset,
            target.test.end_lineno, target.test.end_col_offset,
        )  # fmt: skip
        return start, end, f"not ({source[start:end]})"
    if operator == "remove-guard":
        assert isinstance(target, ast.If)
        start, end = span(
            target.body[0].lineno, target.body[0].col_offset,
            target.body[-1].end_lineno, target.body[-1].end_col_offset,
        )  # fmt: skip
        return start, end, "pass"
    if operator == "drop-operand":
        assert isinstance(target, ast.BoolOp)
        if operand is None or not 1 <= operand <= len(target.values):
            return None
        kept = target.values[operand - 1]
        # The whole `and`/`or` expression is the mutated span; the kept
        # operand's own source is what replaces it, so the others drop.
        start, end = span(
            target.lineno, target.col_offset, target.end_lineno, target.end_col_offset,
        )  # fmt: skip
        kstart, kend = span(
            kept.lineno, kept.col_offset, kept.end_lineno, kept.end_col_offset,
        )  # fmt: skip
        return start, end, source[kstart:kend]
    if operator == "break-continue":
        assert isinstance(target, (ast.Break, ast.Continue))
        start, end = span(
            target.lineno, target.col_offset, target.end_lineno, target.end_col_offset,
        )  # fmt: skip
        return start, end, "continue" if isinstance(target, ast.Break) else "break"
    assert isinstance(target, ast.Compare)
    # end_lineno/end_col_offset are Optional in the ast stubs but set for
    # every node a parse produces -- the same cast span's body makes.
    start, end = span(
        target.left.end_lineno or target.left.lineno,
        target.left.end_col_offset or target.left.col_offset,
        target.comparators[0].lineno, target.comparators[0].col_offset,
    )  # fmt: skip
    region = source[start:end]
    pair = _COMPARE_FLIPS.get(type(target.ops[0]).__name__)
    if pair is None or region.strip() != pair[0]:
        return None
    lead = region[: len(region) - len(region.lstrip())]
    return start, end, lead + pair[1] + region[len(lead) + len(pair[0]) :]


def _splice(
    content: bytes, line: int, operator: str, operand: int | None = None
) -> tuple[bytes, str, str] | None:
    """The controller-side form of `MUTATION_SCRIPT`'s span splice (D80
    round 2): the same parse, the same mutated span, the same replacement
    -- `None` when the edit does not apply, `operand` naming the operand
    `drop-operand` keeps. One splice semantics for the runner's mutant
    commit and the controller's mutant map; the parity between this and
    the script is pinned by
    `test_the_controller_splice_matches_the_runner_script`."""
    try:
        source = content.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError):
        return None
    at_line = sorted(
        (node for node in ast.walk(tree) if getattr(node, "lineno", None) == line),
        key=lambda node: getattr(node, "col_offset", 0),
    )
    span = _line_span(source, content)

    target = _splice_target(at_line, operator)
    if target is None:
        return None
    located = _splice_edit(source, span, target, operator, operand)
    if located is None:
        return None
    start, end, replacement = located
    before = source[start:end]
    mutated = f"{source[:start]}{replacement}{source[end:]}"
    try:
        compile(mutated, "<mutant>", "exec")
    except SyntaxError:
        return None
    return mutated.encode("utf-8"), before, replacement


def _line_span(
    source: str, raw: bytes | None = None
) -> Callable[[int, int, int | None, int | None], tuple[int, int]]:
    """The line/column → offset span over one source text, computed over
    `"\\n"` only the way the parser numbers lines -- the one builder both
    the controller's splice and its aim check span with.

    The AST's column offsets are **UTF-8 byte** offsets, not character
    indices -- a column past a multi-byte character names a position one
    or more characters earlier in the decoded text -- so every column is
    converted to its character index before it is added to the line's
    offset. That needs the line's own bytes, which only the caller that
    still holds the raw file provides; a span built without them passes
    columns through unchanged (an ASCII-only file's columns coincide,
    and the callers that hold the bytes always pass them)."""
    byte_lines = raw.split(b"\n") if raw is not None else None
    if byte_lines is not None:
        # The decoded text and the raw bytes must agree on the line
        # count: a split that disagrees decodes nothing this file
        # produced.
        assert len(byte_lines) == len(source.split("\n"))

    def _char_col(lineno: int, byte_col: int) -> int:
        if byte_lines is None:
            return byte_col
        return len(byte_lines[lineno - 1][:byte_col].decode("utf-8"))

    offsets = [0]
    for part in source.split("\n"):
        offsets.append(offsets[-1] + len(part) + 1)

    def span(
        lineno: int, col: int, end_lineno: int | None, end_col: int | None
    ) -> tuple[int, int]:
        # end_lineno/end_col_offset are Optional in the ast stubs but set
        # for every node a parse produces.
        return (
            offsets[lineno - 1] + _char_col(lineno, col),
            offsets[(end_lineno or lineno) - 1]
            + _char_col(end_lineno or lineno, end_col or col),
        )

    return span


def _aim_refusal(
    content: bytes, line: int, operator: str, operand: int | None
) -> str | None:
    """The controller-side form of `MUTATION_SCRIPT`'s refusal reasons
    (D80's 2026-11-26 update, round-2 review of #845): the same checks in
    the script's own order, with its own reason strings, run against the
    controller's own copy of the head tree **before any exec** -- a
    mis-aimed `mutate` is refused before its baseline can run, so the
    refusal really spends nothing (the execution caps count what ran, and
    nothing ran), instead of the old post-exec refusal that let a lens
    burn a full baseline per mis-aim without ever taking a `max_mutants`
    slot. The script's refusal step stays as the parity backstop for an
    aim that slips past this check; the reasons' parity with the script
    is pinned alongside the splice's."""
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError:
        return "the file could not be read as UTF-8 text"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "the file does not parse"
    kind = _SPLICE_KINDS[operator]
    at_line = sorted(
        (node for node in ast.walk(tree) if getattr(node, "lineno", None) == line),
        key=lambda node: getattr(node, "col_offset", 0),
    )
    target = next((node for node in at_line if isinstance(node, kind)), None)
    if target is None:
        return (
            "the operator does not apply to the statement at that line"
            if at_line
            else "no statement starts at that line"
        )
    span = _line_span(source, content)
    if operator == "drop-operand":
        assert isinstance(target, ast.BoolOp)
        if operand is None:
            return "drop-operand names the operand it keeps"
        if not 1 <= operand <= len(target.values):
            return "the operand index is out of range"
    elif operator == "flip-compare":
        assert isinstance(target, ast.Compare)
        name = type(target.ops[0]).__name__
        if name not in _COMPARE_FLIPS:
            return "that comparison operator has no flip"
        old_text, _replacement = _COMPARE_FLIPS[name]
        start, end = span(
            target.left.end_lineno or target.left.lineno,
            target.left.end_col_offset or target.left.col_offset,
            target.comparators[0].lineno,
            target.comparators[0].col_offset,
        )
        if source[start:end].strip() != old_text:
            return "the comparison's spelling is not the operator the AST named"
    if _splice(content, line, operator, operand) is None:
        return "the mutated file does not compile"
    return None


class _MissingPath(ValueError):
    """A read named a path the controller's copy of the tree does not
    hold; the message keeps the shape the runner's git error had."""


def _local_reply(
    code: int, content: bytes, total_bytes: int, total_lines: int
) -> _Reply:
    """The framed reply a controller-served read would have produced: the
    same fields the exec framing carries, so `_result`'s capping,
    rendering, secret scan and ledger apply unchanged."""
    return _Reply(
        code=code,
        view_code=0,
        total_bytes=total_bytes,
        total_lines=total_lines,
        shown_bytes=len(content),
        content=content,
        stderr=b"",
    )


def _shown_bytes(data: bytes, max_bytes: int) -> bytes:
    """`data` capped at `max_bytes`, cut only between whole UTF-8
    characters -- the same cut the exec's `head -c` and the framing's
    page repair produced."""
    if len(data) <= max_bytes:
        return data
    cut = data[:max_bytes]
    return cut[: len(cut) - _incomplete_tail(cut)]


def _local_read(files: Mapping[str, bytes], call: Call, limits: ToolLimits) -> _Reply:
    """`read_file` from the controller's copy: the same `sed -n
    start,end p` window, byte and line caps, and cut semantics."""
    content = files.get(call.get("path"))
    if content is None:
        raise _MissingPath(
            f"fatal: path '{call.get('path')}' does not exist in the staged tree"
        )
    lines = content.splitlines(keepends=True)
    window_lines = lines[call.get("start") - 1 : call.get("end")]
    window = b"".join(window_lines)
    shown_lines = (
        window_lines[: limits.max_lines]
        if limits.max_lines is not None
        else window_lines
    )
    shown = _shown_bytes(b"".join(shown_lines), limits.max_bytes)
    return _local_reply(0, shown, len(window), window.count(b"\n"))


def _local_grep(
    files: Mapping[str, bytes], call: Call, limits: ToolLimits, rev_id: str
) -> _Reply:
    """`grep` from the controller's copy, in the records shape the runner's
    `git grep -z -n -I --max-count=50` produced: `<staged id>:<path>`,
    the line number, the line; binary files (a NUL in the first 8,000
    bytes, git's `-I` heuristic) are skipped; fifty matches a file. Only
    the fixed-string mode lives here: a substring scan is linear, cannot
    crash and means exactly what `git grep -F` means. The regex mode is
    dispatched to the runner, where `timeout` bounds it, a bad pattern is
    git's exit status rather than a `re.error`, and the dialect is POSIX
    extended regex (`git grep -E`; D80 round 3)."""
    pattern = call.get("pattern")
    prefix = call.get("prefix")
    needle = pattern.encode("utf-8")
    chunks: list[bytes] = []
    for path in sorted(files):
        if prefix and not (path == prefix or path.startswith(f"{prefix}/")):
            continue
        data = files[path]
        if b"\x00" in data[:8_000]:
            continue
        split = data.split(b"\n")
        if data.endswith(b"\n"):
            split = split[:-1]
        count = 0
        for number, line in enumerate(split, 1):
            hit = needle in line
            if hit:
                chunks.append(
                    f"{rev_id}:{path}\0{number}\0".encode("utf-8", "surrogateescape")
                    + line
                    + b"\n"
                )
                count += 1
                if count >= 50:
                    break
    text = b"".join(chunks)
    # The runner's cut was newline-based for grep (only the fields within
    # a record are NUL-separated; the records end with newlines), so the
    # line cap keeps whole records and the count is the record count.
    shown_lines = (
        text.splitlines(keepends=True)[: limits.max_lines]
        if limits.max_lines is not None
        else text.splitlines(keepends=True)
    )
    shown = _shown_bytes(b"".join(shown_lines), limits.max_bytes)
    code = 0 if text else _GREP_NO_MATCH
    return _local_reply(code, shown, len(text), text.count(b"\n"))


def _capped_nul_records(text: bytes, limits: ToolLimits) -> bytes:
    """The `head -z -n <max_lines> | head -c <max_bytes>` cut of a
    NUL-terminated record stream (`list_files`'s shape: one name per
    NUL-terminated record)."""
    if limits.max_lines is not None:
        positions = [i for i, byte in enumerate(text) if byte == 0]
        if len(positions) >= limits.max_lines:
            text = text[: positions[limits.max_lines - 1] + 1]
    return _shown_bytes(text, limits.max_bytes)


def _local_list(files: Mapping[str, bytes], call: Call, limits: ToolLimits) -> _Reply:
    """`list_files` from the controller's copy: the names under the
    prefix, in tree order (`ls-tree -r --name-only`'s sorted order), the
    NUL-record framing and caps the runner's listing had."""
    prefix = call.get("prefix")
    names = sorted(
        path
        for path in files
        if not prefix or path == prefix or path.startswith(f"{prefix}/")
    )
    encoded = [name.encode("utf-8", "surrogateescape") for name in names]
    cut = limits.max_lines is not None and len(encoded) > limits.max_lines
    shown_names = encoded[: limits.max_lines] if cut else encoded
    # Every record carries its own NUL, exactly as `ls-tree -z` emitted
    # them, so a cut listing stays parse-complete and the cut is reported
    # by the byte totals.
    raw = b"".join(name + b"\0" for name in shown_names)
    total = b"".join(name + b"\0" for name in encoded)
    shown = _shown_bytes(raw, limits.max_bytes)
    return _local_reply(0, shown, len(total), total.count(b"\0"))


def run_test_script(
    staged: Staged, call: Call, limits: ToolLimits, argv: str | None = None
) -> str:
    """One exec for `run_tests` (D80): a fresh disposable copy of the
    head tree staged from the repository's objects (`stage_copy_steps` --
    its exit is framed as its own STAGE block, so a copy that could not
    be built is a staging failure, never a test result), one bounded
    pytest process in it, its output captured and shown from the end (the
    summary and the failures sit there), framed like every bridge reply,
    and the copy removed again -- whatever the tests wrote dies with it,
    and nothing it wrote or replaced reaches a later call.

    `argv`, when given, is the bridge-built argv of a pre-approved
    proposed command (S7, D88): the declared command replaces the pytest
    invocation -- the proposal's own tokens, each quoted, run from the
    same disposable copy under the same `timeout`, output cap and
    environment, with no shell and no selector appended. Nothing about
    the copy, the framing or the caps changes with it."""
    scratch = quote(staged.scratch)
    root = quote(staged.root)
    if argv is None:
        # The built-in entry needs the pytest-capable interpreter the
        # staging resolved; an approved command does not name pytest, but
        # neither ever runs as root -- both go through the no-root guard,
        # which runs through the resolved interpreter -- the caller
        # refuses each before this.
        assert staged.pytest is not None  # the caller refuses the call before this
        assert staged.shim_python is not None  # the refusals above guarantee it
        run_argv = as_nobody(staged.shim_python, _pytest_argv(staged, call.get("path")))
    else:
        assert staged.shim_python is not None  # the refusals above guarantee it
        run_argv = as_nobody(staged.shim_python, argv)
    return "\n".join(
        (
            f"cd {root}",
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            "stage=$?",
            f'echo "{STAGE_HEADER} $stage"',
            'if [ "$stage" = 0 ]; then',
            f"  ( cd {scratch}; {FILE_LIMIT_CMDS};",
            guarded_env_exports(staged.scratch),
            "  export PYTHONDONTWRITEBYTECODE=1;",
            (
                f"  exec timeout -k {KILL_AFTER_S} {limits.timeout_s} "
                f"{run_argv} ) > out 2> err"
            ),
            "  s=$?",
            f"  tail -c {limits.max_bytes} out > shown",
            f'  echo "{RUN_HEADER} $s $(wc -c < out) $(wc -l < out) $(wc -c < shown)"',
            "  base64 -w0 < shown; echo",
            f"  head -c {STDERR_BYTES} err | base64 -w0; echo",
            "fi",
            f"rm -rf {root}/{SCRATCH_DIR} out err shown",
        )
    )


# The probe file's name: one throwaway test module per call, at the
# copy's root (the same import context the repo's own root tests have),
# with a controller-chosen suffix so it cannot shadow a real test file.
PROBE_NAME_PREFIX = "test_atlas_probe_"


def run_probe_script(staged: Staged, call: Call, limits: ToolLimits) -> str:
    """One exec for `run_probe` (D80's 2026-11-26 update): the same
    disposable copy of the head tree `run_tests` builds, with the model's
    one throwaway test file written into it at the copy's root under a
    controller-chosen `test_atlas_probe_<hex>.py` name no repo file can
    shadow (base64-decoded, so the content cannot bend the script), then
    the same
    bounded guarded pytest run -- the selector names what runs, the probe
    file itself when none was given -- and the copy removed again. The
    file never reaches the repository, the trees, or any later call: it
    dies with the copy, exactly like the test-run writes it may make."""
    scratch = quote(staged.scratch)
    root = quote(staged.root)
    assert staged.pytest is not None  # the caller refuses the call before this
    assert staged.shim_python is not None  # the caller refuses the call before this
    content = base64.b64encode(call.get("content").encode("utf-8")).decode()
    probe_path = f"{PROBE_NAME_PREFIX}{uuid4().hex[:8]}.py"
    # The model never names the probe file -- its name is the controller's
    # -- so the optional selector is a `::node-id` suffix appended to the
    # path (`::test_x`), or empty for the whole file.
    selector = probe_path + call.get("selector")
    run_argv = as_nobody(staged.shim_python, _pytest_argv(staged, selector))
    return "\n".join(
        (
            f"cd {root}",
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            "stage=$?",
            f'echo "{STAGE_HEADER} $stage"',
            'if [ "$stage" = 0 ]; then',
            f"  printf %s {quote(content)} | base64 -d > {scratch}/{quote(probe_path)}",
            f"  ( cd {scratch}; {FILE_LIMIT_CMDS};",
            guarded_env_exports(staged.scratch),
            "  export PYTHONDONTWRITEBYTECODE=1;",
            (
                f"  exec timeout -k {KILL_AFTER_S} {limits.timeout_s} "
                f"{run_argv} ) > out 2> err"
            ),
            "  s=$?",
            f"  tail -c {limits.max_bytes} out > shown",
            f'  echo "{RUN_HEADER} $s $(wc -c < out) $(wc -l < out) $(wc -c < shown)"',
            "  base64 -w0 < shown; echo",
            f"  head -c {STDERR_BYTES} err | base64 -w0; echo",
            "fi",
            f"rm -rf {root}/{SCRATCH_DIR} out err shown",
        )
    )


def mutate_script(staged: Staged, call: Call, limits: ToolLimits) -> str:
    """One exec for `mutate` (D80): the baseline run on a copy staged
    from the repository's objects, a **fresh** copy staged again for the
    mutation (F2: the baseline run's writes must not carry into the
    mutated tree or the mutant commit), then the single-operator mutation
    applied by the fixed script (the model named only a path, a line and
    an operator), the mutated tree committed and its id recorded, then
    the mutated run. Each staging step's exit is its own STAGE block: a
    copy that could not be built ends the exec after the last block it
    could make, and the controller reports it as a staging failure, never
    a test result. A mutation that did not apply, or a tree that could
    not be committed, ends after the baseline -- inconclusive, never a
    survived mutant."""
    scratch = quote(staged.scratch)
    root = quote(staged.root)
    assert staged.pytest is not None  # the caller refuses the call before this
    assert staged.shim_python is not None  # the caller refuses the call before this
    run = (
        f"( cd {scratch}; {FILE_LIMIT_CMDS}; "
        f"{guarded_env_exports(staged.scratch)}"
        "export PYTHONDONTWRITEBYTECODE=1; "
        f"exec timeout -k {KILL_AFTER_S} {limits.timeout_s} "
        f"{as_nobody(staged.shim_python, _pytest_argv(staged, call.get('tests')))} )"
    )
    operand = call.get("operand")
    operand_arg = "" if operand is None else f" {operand}"
    edit = (
        f"( cd {scratch}; exec timeout -k {KILL_AFTER_S} "
        f"{MUTATE_EDIT_TIMEOUT_S} "
        f"{staged.pytest.quoted} -I -c {quote(MUTATION_SCRIPT)} "
        f"{quote(call.get('path'))} {call.get('line')} "
        f"{quote(call.get('operator'))}{operand_arg} ) > mut 2> mut_err"
    )
    commit = "; ".join(
        mutant_commit_steps(
            staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
        )
    )

    def framed_run(name: str) -> str:
        return "\n".join(
            (
                f"  {run} > {name}_out 2> {name}_err",
                f"  {name}=$?",
                f"  tail -c {limits.max_bytes} {name}_out > {name}_shown",
                (
                    f'  echo "{RUN_HEADER} ${name} $(wc -c < {name}_out) '
                    f'$(wc -l < {name}_out) $(wc -c < {name}_shown)"'
                ),
                "  base64 -w0 < " + name + "_shown; echo",
                f"  head -c {STDERR_BYTES} {name}_err | base64 -w0; echo",
            )
        )

    return "\n".join(
        (
            f"cd {root}",
            f"export {' '.join(GIT_ENV)} PYTHONDONTWRITEBYTECODE=1",
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            "stage=$?",
            f'echo "{STAGE_HEADER} $stage"',
            'if [ "$stage" = 0 ]; then',
            framed_run("b"),
            # The second staging and everything past it run only when the
            # first copy was built: a staging failure skips the run it
            # would serve (F4), and a failed re-stage skips the mutation
            # it would serve.
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            "  stage=$?",
            f'  echo "{STAGE_HEADER} $stage"',
            '  if [ "$stage" = 0 ]; then',
            f"    {edit}",
            "    m=$?",
            "    payload=$(head -n 1 mut)",
            "    c=-",
            "    case $payload in",
            f'    "ok "*) cmt=$({commit}) 2>> mut_err ;;',
            "    esac",
            "    case $cmt in",
            "    atlas-mutant:*) c=${cmt#atlas-mutant:} ;;",
            "    esac",
            f'    echo "{MUT_HEADER} $m $c"',
            '    printf "%s" "$payload" | base64 -w0; echo',
            f"    head -c {STDERR_BYTES} mut_err | base64 -w0; echo",
            '    if [ "$c" != "-" ]; then',
            framed_run("s"),
            "    fi",
            "  fi",
            "fi",
            (
                f"rm -rf {root}/{SCRATCH_DIR} b_out b_err b_shown mut mut_err "
                "s_out s_err s_shown index-stage index-mutant"
            ),
        )
    )


def restage_script(
    staged: Staged,
    mutation: MutationRecord | None,
    unpack: UnpackLimits,
    digests: Mapping[Rev, str],
) -> str:
    """Rebuilds the staged repository, trees and scratch from the freshly
    uploaded, digest-checked tarballs (D80 round 2). Executed PR code
    cannot be prevented from writing into the runner -- it is the same
    user -- and git does **not** re-verify a loose object on read, so an
    in-place overwrite of a blob file is served verbatim by every later
    read and by a copy staged from the object store. The one source of
    truth executed code cannot touch is the controller's own copy of the
    trees, so a re-stage removes everything it could have rewritten and
    rebuilds it from those bytes; the staged commits are deterministic
    (fixed identity and date), so the recorded BASE/HEAD ids come back
    exactly. When a mutant is recorded, the same span splice re-applies
    to a fresh copy and the mutant commit is re-created -- deterministic
    for the same reason -- so the recorded mutant id comes back too and
    `read_file`/`grep` at MUTANT keep serving the mutation the record
    names. `stage_script`'s digest checks run first: a tarball rewritten
    in the upload-to-verify window stops the staging."""
    # Only the mutation re-splice needs the pytest-capable interpreter,
    # and a runner that carries one is guaranteed there by the mutate
    # call's own gate. A plain re-stage -- what a read tool's `_exec`
    # runs after the grounding pre-pass executed a command and made the
    # bridge suspect (#871) -- has no such caller gate: the staging
    # probe legitimately finds no pytest on the image, so the re-stage
    #     must rebuild exactly as the initial staging did, without one.
    root = quote(staged.root)
    steps = [
        f"cd {root}",
        (
            f"rm -rf {quote(staged.root)}/repo.git {quote(staged.root)}/trees "
            f"{quote(staged.root)}/{SCRATCH_DIR} "
            f"{quote(staged.root)}/index-stage {quote(staged.root)}/index-mutant "
            # The staging commits' own index files must go too: their
            # cached stat entries (the tarballs' fixed mtimes and sizes
            # extract identically) would let `git add` skip re-hashing,
            # and the blobs they name exist only in the repository this
            # rebuild just deleted.
            f"{quote(staged.root)}/index-base {quote(staged.root)}/index-head "
            f"{quote(staged.root)}/index-default"
        ),
        stage_script(
            staged.root,
            staged.git,
            tuple(staged.commits),
            unpack,
            digests=digests,
        ),
        "staged=$?",
    ]
    if mutation is not None:
        # The mutate call's own gate guarantees a pytest-capable
        # interpreter and the guard's interpreter for a recorded mutation:
        # the re-splice runs the mutation script through both.
        mutation_py = staged.pytest
        assert mutation_py is not None
        assert staged.shim_python is not None
        steps += [
            'if [ "$staged" = 0 ]; then',
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            (
                f"  ( cd {quote(staged.scratch)}; exec timeout -k {KILL_AFTER_S} "
                f"{MUTATE_EDIT_TIMEOUT_S} "
                f"{mutation_py.quoted} -I -c {quote(MUTATION_SCRIPT)} "
                f"{quote(mutation.path)} {mutation.line} "
                f"{quote(mutation.operator)}"
                f"{'' if mutation.operand is None else f' {mutation.operand}'}"
                " ) > mut 2> mut_err"
            ),
            "  m=$?",
            "  payload=$(head -n 1 mut)",
            "  c=-",
            "  case $payload in",
            '  "ok "*) cmt=$('
            + "; ".join(
                mutant_commit_steps(
                    staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
                )
            )
            + ") 2>> mut_err ;;",
            "  esac",
            "  case $cmt in",
            "    atlas-mutant:*) c=${cmt#atlas-mutant:} ;;",
            "  esac",
            f'  echo "{MUT_HEADER} $m $c"',
            '  printf "%s" "$payload" | base64 -w0; echo',
            f"  head -c {STDERR_BYTES} mut_err | base64 -w0; echo",
            "fi",
        ]
    return "\n".join(steps)


@dataclass(frozen=True)
class _RunBlock:
    code: int
    total_bytes: int
    total_lines: int
    shown_bytes: int
    content: bytes
    stderr: bytes

    def problem(self) -> str | None:
        """Why the block cannot be trusted as the run's output, if it can't."""
        if len(self.content) != self.shown_bytes:
            return (
                f"the runner's encoded output held {len(self.content)} of "
                f"{self.shown_bytes} bytes"
            )
        return None


@dataclass(frozen=True)
class _MutBlock:
    apply_exit: int
    commit: str
    payload: bytes
    stderr: bytes


@dataclass(frozen=True)
class _StageBlock:
    """One staging step's exit status. A nonzero one means the disposable
    copy of HEAD could not be built, and everything after it that needed
    the copy was skipped -- never a test result (D80 round 1)."""

    code: int


def parse_run_blocks(
    text: str,
) -> tuple[_RunBlock | _MutBlock | _StageBlock, ...] | None:
    """The staging, run and mutation blocks an execution tool's exec
    printed, in order; None when there is no block at all or a
    header-shaped line does not parse. The test processes' own output
    reaches this stream only base64-encoded, so every header line here is
    the script's own, and a line that merely looks like one is a refusal
    of the whole reply."""
    blocks: list[_RunBlock | _MutBlock | _StageBlock] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith(f"{STAGE_HEADER} "):
            fields = line.split(" ")
            if len(fields) == 2 and _DIGIT.fullmatch(fields[1]):
                blocks.append(_StageBlock(int(fields[1])))
                continue
            return None
        if not line.startswith((f"{RUN_HEADER} ", f"{MUT_HEADER} ")):
            continue
        payload = lines[index] if index < len(lines) else ""
        index += 1
        fields = line.split(" ")
        if (
            fields[0] == RUN_HEADER
            and len(fields) == 5
            and all(_DIGIT.fullmatch(f) for f in fields[1:])
        ):
            # The stderr line after the content line is empty exactly when
            # `parse_exit` stripped the whole empty line, so it is optional
            # and decodes to nothing (the same optional shape `_REPLY`'s
            # own stderr group has).
            stderr_line = lines[index] if index < len(lines) else ""
            try:
                content = base64.b64decode(payload, validate=True)
                stderr = base64.b64decode(stderr_line, validate=True)
            except ValueError:
                return None
            index += 1
            blocks.append(
                _RunBlock(
                    int(fields[1]), int(fields[2]), int(fields[3]),
                    int(fields[4]), content, stderr,
                )
            )  # fmt: skip
        elif (
            fields[0] == MUT_HEADER
            and len(fields) == 3
            and _DIGIT.fullmatch(fields[1])
            and (fields[2] == "-" or _MUT_COMMIT.fullmatch(fields[2]))
        ):
            # The mutation step's own stderr follows the payload, and is
            # empty exactly when `parse_exit` stripped the empty line.
            stderr_line = lines[index] if index < len(lines) else ""
            try:
                decoded = base64.b64decode(payload, validate=True)
                stderr = base64.b64decode(stderr_line, validate=True)
            except ValueError:
                return None
            index += 1
            blocks.append(_MutBlock(int(fields[1]), fields[2], decoded, stderr))
        else:
            return None
    return tuple(blocks) or None


def parse_summary(text: str) -> TestSummary | None:
    """The counts on the last pytest summary line of one run's captured
    output, and nothing else in it; None when the output carries no line
    of that shape (then `mutant_outcome` treats a passing exit as
    unproven -- F7: a verdict may not rest on an exit alone). The LAST
    summary-shaped line wins, so PR output printed after pytest's own
    summary replaces the parsed counts; that is inside the owned in-band
    threat model (D80), and the summary is parsed only for counts, never
    for instructions."""
    for line in reversed(text.splitlines()):
        match = _SUMMARY.match(line.strip())
        if match is None:
            continue
        if match.group(1) == "no tests ran":
            return TestSummary((), ran=False)
        counts = []
        for number, label in _SUMMARY_TOKENS.findall(match.group(1)):
            counts.append((int(number), _PLURAL.get(label, label)))
        merged: dict[str, int] = {}
        for number, label in counts:
            merged[label] = merged.get(label, 0) + number
        return TestSummary(tuple(sorted(merged.items())))
    return None


def parse_mutation(payload: bytes, apply_exit: int) -> tuple[bool, str, str, str]:
    """The mutation step's answer as `(applied, before, after, reason)`:
    the payload the fixed script printed -- `ok <before> <after>` or
    `no <reason>`, each field base64-encoded -- or, when the step itself
    failed, a controller-written reason. The reason text is the
    controller's or the controller script's own, never the PR's."""
    if apply_exit != 0:
        return False, "", "", f"the mutation step failed (exit {apply_exit})"
    text = payload.decode("utf-8", errors="replace").rstrip("\n")
    status, _, rest = text.partition(" ")
    if status == "ok":
        fields = rest.split(" ")
        if len(fields) == 2:
            try:
                before = base64.b64decode(fields[0], validate=True).decode(
                    "utf-8", errors="replace"
                )
                after = base64.b64decode(fields[1], validate=True).decode(
                    "utf-8", errors="replace"
                )
            except ValueError:
                return False, "", "", "the mutation step did not report its edit"
            return True, before, after, ""
    if status == "no":
        try:
            reason = base64.b64decode(rest, validate=True).decode(
                "utf-8", errors="replace"
            )
        except ValueError:
            return False, "", "", "the mutation step refused without a reason"
        return False, "", "", reason
    return False, "", "", "the mutation step did not report its edit"


def mutation_refusal(payload: bytes, apply_exit: int) -> str | None:
    """The fixed script's own refusal reason -- why the mutation did not
    apply -- or None when the step did not refuse. Only the script's
    `no <reason>` answer at exit 0 is a refusal: a step that failed
    outright (a nonzero exit) is not, and stays the inconclusive path
    mutant_outcome already names, because a machinery failure is not the
    model's error to re-aim."""
    if apply_exit != 0:
        return None
    text = payload.decode("utf-8", errors="replace").rstrip("\n")
    status, _, rest = text.partition(" ")
    if status != "no":
        return None
    try:
        return base64.b64decode(rest, validate=True).decode("utf-8", errors="replace")
    except ValueError:
        return "the mutation step refused without a reason"


def mutant_outcome(
    applied: bool,
    apply_reason: str,
    baseline: _RunBlock,
    mutated: _RunBlock | None,
    summary_baseline: TestSummary | None,
    summary_mutated: TestSummary | None,
) -> tuple[MutantOutcome, str]:
    """The verdict on one mutant (D80), and its controller-written reason.
    Only a mutant whose baseline run passed -- and whose summary shows at
    least one test run -- and whose mutated run also passed with a
    summary that shows one is `survived`. An already-failing, empty or
    all-skipping baseline, a timed-out run, a run whose output carries no
    summary line (F7: the exit alone never proves a test ran), a mutated
    run where no test ran, and a mutated run that is not a test result
    are all inconclusive. The summary is the controller's own parse of
    the captured output; what PR code can shape -- its exits and what it
    prints -- is D80's owned in-band caveat."""
    if not applied:
        return MutantOutcome.INCONCLUSIVE, f"the mutation did not apply: {apply_reason}"
    if baseline.code in (_TIMED_OUT, _KILLED):
        return MutantOutcome.INCONCLUSIVE, "the baseline run hit its wall clock"
    if baseline.code == 5:
        return (
            MutantOutcome.INCONCLUSIVE,
            "no test was collected for the baseline run (exit 5)",
        )
    if baseline.code == 4:
        return (
            MutantOutcome.INCONCLUSIVE,
            "the test run stopped before collecting (exit 4)",
        )
    if baseline.code != 0:
        return (
            MutantOutcome.INCONCLUSIVE,
            f"the baseline run already fails (exit {baseline.code})",
        )
    if summary_baseline is None:
        return (
            MutantOutcome.INCONCLUSIVE,
            "the baseline run's output carries no summary",
        )
    if not summary_baseline.ran_any:
        return MutantOutcome.INCONCLUSIVE, "no test ran in the baseline run"
    if mutated is None:
        return MutantOutcome.INCONCLUSIVE, "the mutated run did not run"
    if mutated.code in (_TIMED_OUT, _KILLED):
        return MutantOutcome.INCONCLUSIVE, "the mutated run hit its wall clock"
    if summary_mutated is None:
        return MutantOutcome.INCONCLUSIVE, "the mutated run's output carries no summary"
    if not summary_mutated.ran_any:
        return MutantOutcome.INCONCLUSIVE, "no test ran in the mutated run"
    if mutated.code == 0:
        return (
            MutantOutcome.SURVIVED,
            "the baseline run passed and the mutated run passed too",
        )
    if mutated.code in (1, 2):
        return MutantOutcome.KILLED, f"the mutated run failed (exit {mutated.code})"
    return (
        MutantOutcome.INCONCLUSIVE,
        f"the mutated run ended at exit {mutated.code}, not a test result",
    )


def _run_status(code: int) -> Status:
    """A run's exit status as the tool's status: the process running to one
    of pytest's own outcomes (passed, failed, interrupted, an internal or
    usage error, nothing collected) is the tool working -- the test result
    is the record, not a failure of the tool; a killed process is a
    timeout."""
    if code in (_TIMED_OUT, _KILLED):
        return Status.TIMED_OUT
    return Status.OK if 0 <= code <= 5 else Status.FAILED


def _summary_of(block: _RunBlock) -> TestSummary | None:
    return parse_summary(block.content.decode("utf-8", errors="replace"))


def _single_run(
    blocks: tuple[_RunBlock | _MutBlock | _StageBlock, ...],
) -> tuple[_StageBlock, _RunBlock | None]:
    """`run_tests`'s reply is a staging block and -- when the copy was
    built -- one run block; the script skips the run when staging failed,
    so a lone staging block is that failure's shape. Any other shape is a
    boundary error -- a gap -- never a `ValueError` escaping the exec's
    failure handling (F5)."""
    if (
        len(blocks) == 2
        and isinstance(blocks[0], _StageBlock)
        and isinstance(blocks[1], _RunBlock)
    ):
        return blocks[0], blocks[1]
    if len(blocks) == 1 and isinstance(blocks[0], _StageBlock):
        return blocks[0], None
    raise BoundaryError("the run_tests reply is not a staging step and one test run")


def _mutant_shape(
    blocks: tuple[_RunBlock | _MutBlock | _StageBlock, ...],
) -> tuple[
    _StageBlock,
    _RunBlock | None,
    _StageBlock | None,
    _MutBlock | None,
    _RunBlock | None,
]:
    """`mutate`'s reply is a staging block, then -- when the copy was
    built -- the baseline run, then the second staging block, then, when
    that copy was built too, the mutation block and, when the mutation
    applied and the tree committed, the mutated run. Each shorter shape
    is the script stopping after the step that failed, and every other
    shape is a boundary error -- a gap -- never a crash."""
    if not blocks or not isinstance(blocks[0], _StageBlock):
        raise BoundaryError("the mutate reply does not start with a staging step")
    stage1 = blocks[0]
    rest = blocks[1:]
    if not rest:
        return stage1, None, None, None, None
    if not isinstance(rest[0], _RunBlock):
        raise BoundaryError("the mutate reply's baseline run is missing")
    baseline = rest[0]
    rest = rest[1:]
    if not rest:
        raise BoundaryError("the mutate reply ends without its second staging step")
    if not isinstance(rest[0], _StageBlock):
        raise BoundaryError("the mutate reply's second staging step is missing")
    stage2 = rest[0]
    rest = rest[1:]
    if not rest:
        return stage1, baseline, stage2, None, None
    if not isinstance(rest[0], _MutBlock):
        raise BoundaryError("the mutate reply's mutation step is missing")
    applied = rest[0]
    rest = rest[1:]
    if not rest:
        return stage1, baseline, stage2, applied, None
    if not isinstance(rest[0], _RunBlock):
        raise BoundaryError("the mutate reply's mutated run is missing")
    return stage1, baseline, stage2, applied, rest[0]


@dataclass(frozen=True)
class _Where:
    path: str | None
    line: int | None
    preexisting: bool


_NOWHERE = _Where(None, None, False)


@dataclass(frozen=True)
class _View:
    """The shown text, where each of its lines comes from, and whether all
    of the output could be shown (False when some of it did not parse)."""

    text: str
    places: list[_Where]
    complete: bool = True


def _view(
    call: Call,
    raw: bytes,
    commit: str,
    preexisting: Callable[[Rev, str], bool],
    paths: tuple[str, ...] = (),
) -> _View:
    text = raw.decode("utf-8", errors="replace")
    match call.tool:
        case "read_file":
            rev, path, start = call.get("rev"), call.get("path"), call.get("start")
            return _View(
                text,
                [
                    _Where(path, start + i, preexisting(rev, path))
                    for i in range(text.count("\n") + 1)
                ],
            )
        case "grep":
            return _grep_view(text, commit, call.get("rev"), preexisting)
        case "list_files":
            return _list_view(raw)
        case "diff_file":
            return _View(text, _diff_places(text.split("\n"), paths[0], paths[-1]))
    return _View(text, [])


def _list_view(raw: bytes) -> _View:
    """One name per line, exactly as `read_file` takes it back. A name it
    would refuse (a control character, a leading `-`, not UTF-8, ...) is
    shown as a JSON string and marked; a name cut short by the cap is
    dropped."""
    *names, last = raw.split(b"\0")
    return _View("\n".join(map(_listed, names)), [], last == b"")


def _listed(name: bytes) -> str:
    text = name.decode("utf-8", errors="replace")
    problem = path_problem(text) if text.encode() == name else "is not valid UTF-8"
    if problem is None:
        return text
    return f"{json.dumps(text)} (not readable by read_file: path {problem})"


def _grep_records(text: str, commit: str) -> tuple[list[tuple[str, str, str]], bool]:
    """`<commit>:<path>\\0<line>\\0<text>\\n` per match (`git grep -z -n`).
    The fields are split on NUL first: a path may hold a newline but a
    matched line cannot, so each line's text ends at its first newline and
    the next record's `<commit>:<path>` follows it. A record that is cut
    short or out of step (a NUL inside a matched line) ends the parse;
    the flag says whether every byte was accounted for."""
    fields = text.split("\0")
    prefix = f"{commit}:"
    head = fields[0]
    records: list[tuple[str, str, str]] = []
    for line, rest in zip(fields[1::2], fields[2::2], strict=False):
        match, newline, after = rest.partition("\n")
        if not (head.startswith(prefix) and line.isdigit() and newline):
            return records, False
        records.append((head[len(prefix) :], line, match))
        head = after
    return records, head == "" and len(fields) % 2 == 1


def _grep_view(
    text: str, commit: str, rev: Rev, preexisting: Callable[[Rev, str], bool]
) -> _View:
    records, complete = _grep_records(text, commit)
    return _View(
        "\n".join(f"{_shown_path(p)}:{n}:{t}" for p, n, t in records),
        [_Where(p, int(n), preexisting(rev, p)) for p, n, _ in records],
        complete,
    )


def _shown_path(path: str) -> str:
    return path if _PLAIN_PATH.fullmatch(path) and ":" not in path else json.dumps(path)


def _diff_places(lines: Iterable[str], base_path: str, path: str) -> list[_Where]:
    """Head-side lines (in `path`) of added and context lines, base-side
    (in `base_path`, which differs for a rename) of removed ones; added
    lines are new in the PR, the rest pre-existing. Lines before the
    page's first hunk header are not located."""
    places: list[_Where] = []
    base = head = None
    for line in lines:
        hunk = _HUNK.match(line)
        if hunk:
            base, head = int(hunk.group(1)), int(hunk.group(2))
        place, base, head = _diff_line(line, (base_path, path), base, head, bool(hunk))
        places.append(place)
    return places


def _diff_line(
    line: str,
    sides: tuple[str, str],
    base: int | None,
    head: int | None,
    is_hunk: bool,
) -> tuple[_Where, int | None, int | None]:
    base_path, path = sides
    if is_hunk or base is None or head is None:
        return _Where(path, None, False), base, head
    kind = line[:1]
    if kind == "+":
        return _Where(path, head, False), base, head + 1
    if kind == "-":
        return _Where(base_path, base, True), base + 1, head
    if kind == " ":
        return _Where(path, head, True), base + 1, head + 1
    return _Where(path, None, False), base, head


def _secrets(scan: SecretScan, places: Sequence[_Where]) -> tuple[BridgeSecret, ...]:
    def where(line: int) -> _Where:
        return places[line - 1] if 0 < line <= len(places) else _NOWHERE

    return tuple(
        BridgeSecret(
            hit.label,
            where(hit.line).path,
            where(hit.line).line,
            where(hit.line).preexisting,
        )
        for hit in scan.hits
    )


SWEEP_CAP = 24
# One scoped run's wall clock, matched to the execution tools' own
# per-process budget (#843): a whole-suite baseline took about 74 seconds
# on the box, and a slow suite timed out into INCONCLUSIVE under the old
# 60-second bound exactly the way `run_tests`' did before its raise.
SWEEP_RUN_BOUND_S = 180
# The pass's wall budget, derived from the per-run bound rather than
# carried beside it, so the two cannot silently desync again: the budget
# holds about five of the scoped runs the bound allows, and a group the
# remainder cannot start is inconclusive, named, never an unbounded exec.
SWEEP_BUDGET_S = 5.0 * SWEEP_RUN_BOUND_S
SWEEP_TAG = "atlas-sweep"
_BASELINE_TAG = "atlas-baseline"
# The plan's operator ranking: the mutation classes the parity key's
# mutants are -- a dropped BoolOp operand, a break that should be a
# continue -- sweep before the comparison flips and the guard negations,
# which is the ordering that lets the anchors' own mutants into a capped
# plan instead of the first alphabetical file's.
_SWEEP_OPERATOR_RANK: Mapping[str, int] = MappingProxyType(
    {
        "drop-operand": 0,
        "break-continue": 0,
        "flip-compare": 1,
        "negate-condition": 2,
    }
)
# A file with no added line of its own (its guards came in through the
# called-function widening) cannot be near the diff; the sentinel keeps
# its guards ranked behind every changed file's own.
_NO_DIFF_DISTANCE = 1 << 30

# The grounding pre-pass's clocks: one declared command runs at most as
# long as an execution tool's test process (#843), and the pass's wall
# budget holds about three of those runs -- a repo whose CI runs a lint, a
# type check and a test suite fits; a command the remainder cannot start
# is named, never silently skipped.
GROUNDING_RUN_BOUND_S = 180
GROUNDING_BUDGET_S = 3.0 * GROUNDING_RUN_BOUND_S


@dataclass
class Bridge:
    """The tools over one staged runner. `changed` are the paths the PR
    changes (from its diff): a secret found in any other file, or outside
    HEAD, is pre-existing. Every call, rejected or run, is in `calls` --
    the session's whole ledger, across every attempt it serves. The
    budget `session_limits` bounds is per attempt (#693): `begin_attempt`
    starts the attempt's counters over, so a lens's retry runs on a full
    budget instead of one its first attempt spent. `commits` starts as the
    staged revisions and gains MUTANT (D80) -- resolved at the moving
    `atlas-mutant` ref -- for as long as a `mutate` call has committed a
    mutant: `validate` reads it, so the latest mutant is readable exactly
    while it is the one the tag names."""

    session: Session
    staged: Staged
    redactor: Redactor
    clock: Clock
    changed: frozenset[str] = frozenset()
    limits: Mapping[str, ToolLimits] = DEFAULT_LIMITS
    session_limits: SessionLimits = DEFAULT_SESSION
    # The controller-held tarballs and their unpack caps (D80 round 2):
    # the one source of truth executed code cannot touch, and what a
    # re-stage rebuilds the runner's state from.
    trees: SourceTrees = field(default=SourceTrees(b"", b"", "", ""))
    unpack: UnpackLimits = DEFAULT_UNPACK
    calls: list[CallRecord] = field(default_factory=list)
    _flagged: list[str] = field(default_factory=list, repr=False)
    _renames: Mapping[str, tuple[str, str]] | None = field(default=None, repr=False)
    commits: Mapping[Rev, str] = field(default=MappingProxyType({}), repr=False)
    # Set whenever executed PR code has run in this runner (D80 round 2):
    # it may have rewritten anything it can reach -- loose objects in the
    # repository (git does not re-verify a loose object on read), refs,
    # `trees`, the scratch -- so the next call that reads or stages from
    # the runner's state re-stages from the controller-held tarballs
    # first. Cleared by a successful re-stage.
    _suspect: bool = field(default=False, repr=False)
    # The verdicts the sweep already ran for, keyed by the specs tuple
    # that produced them: the sweep is the controller's evidence
    # gathering, not the model's spend, so a retry attempt reads the
    # cached verdicts instead of re-running the mutants (the lenses run
    # in their own runners, so the cache is per lens session, not per
    # review).
    _sweep_cache: dict[tuple[SweepSpec, ...], tuple[SweepVerdict, ...]] = field(
        default_factory=dict, repr=False
    )
    # The mutation a `mutate` call applied and committed, if one did: a
    # re-stage re-applies it deterministically, so the recorded mutant id
    # and the tree it names survive the rebuild.
    _mutation: MutationRecord | None = field(default=None, repr=False)
    # The controller's own copy of every staged tree's files (D80 round
    # 2), built once from the tarballs it holds, plus the recorded
    # mutation's splice for MUTANT. `read_file`, `grep` and `list_files`
    # answer from these maps and never from the runner's state.
    _contents: dict[Rev, dict[str, bytes]] = field(default_factory=dict, repr=False)
    # The attempt now running, as `_spent`'s refusals name it, and the
    # counters its budget spends. Empty/unspent until `begin_attempt`.
    _attempt: str = field(default="", repr=False)
    _attempt_calls: int = field(default=0, repr=False)
    _attempt_shown: int = field(default=0, repr=False)
    _attempt_runs: int = field(default=0, repr=False)
    _attempt_mutants: int = field(default=0, repr=False)
    # The run-scoped operator-approval gate (S7, D88), None when the run
    # proposes no addition: the proposals the repo's default-branch
    # config named, the approval channel, and the approved set that dies
    # with this bridge. The gate is the only path an approved addition
    # takes to the argv builder, and it never grants on its own.
    approvals: RunApprovals | None = None
    # The history bundle the run staged, retained so a re-stage can
    # restore the real history it fetched (D80's git-history update): the
    # restage rebuilds the repository from the tarballs, whose synthesized
    # commits have no ancestors, and the bundle is the only source of the
    # real ones.
    history_bundle: bytes | None = field(default=None, repr=False)
    history_base: str = ""
    _history_lost: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if not self.commits:
            self.commits = self.staged.commits
        for rev, data in self.trees.staged():
            if rev in self.staged.commits:
                self._contents[rev] = _tree_files(data)

    def _mutant_contents(self) -> dict[str, bytes]:
        """MUTANT's controller-side map: the head tree with the recorded
        mutation spliced in by the same span-splice `MUTATION_SCRIPT`
        applies (their parity is pinned). A splice that does not re-apply
        cannot happen for a mutation the runner committed -- and would be
        a boundary error, not a silently wrong map."""
        head = dict(self._contents[Rev.HEAD])
        mutation = self._mutation
        assert mutation is not None
        spliced = _splice(
            head[mutation.path], mutation.line, mutation.operator, mutation.operand
        )
        if spliced is None:
            raise BoundaryError(
                "the recorded mutation does not re-apply to the controller's copy"
            )
        mutated, _before, _after = spliced
        head[mutation.path] = mutated
        return head

    def sweep_plan(self, diff: str, cap: int = SWEEP_CAP) -> tuple[SweepSpec, ...]:
        """The mutant specs the controller's pre-pass would sweep for this
        runner: the diff's changed conditions over the head tree's own
        parse (`sweep_specs`), against the controller's own copy of the
        staged head tree."""
        return sweep_specs(diff, self._contents.get(Rev.HEAD, {}), cap)

    def sweep(
        self,
        specs: Sequence[SweepSpec],
        *,
        clock: Clock,
        budget_s: float | None = None,
    ) -> tuple[SweepVerdict, ...]:
        """The controller's mutant pre-pass (D80's 2026-11-26 update):
        runs the caller's specs through the same machinery a `mutate` call
        uses -- the fixed script, fresh disposable copies, scoped test
        runs -- without spending the attempt's own call or mutant budget,
        because this is the controller's evidence gathering, not the
        model's. Memoized on the bridge: a retry attempt reads the cached
        verdicts instead of re-running the mutants. Specs no test file
        imports report inconclusive with that reason -- the sweep could
        not aim a run at them, and a lens must not read their absence as
        "swept clean". Groups whose baseline does not pass report
        inconclusive (the named broken-environment shape), the wall
        budget bounds the whole pass, and each group's exec budget is
        clamped to what is left of it: a group the remaining budget
        cannot even start is inconclusive, named, never an unbounded
        exec. Every exec runs PR code, so the bridge stays suspect
        between groups and the next read re-stages."""
        key = tuple(specs)
        cached = self._sweep_cache.get(key)
        if cached is not None:
            return cached
        if self.staged.pytest is None or self.staged.shim_python is None:
            # No pytest-capable interpreter (and no no-root guard) was
            # staged for this runner: the sweep's scoped runs cannot
            # start, so every spec is inconclusive with the named
            # environment gap -- the same verdict a `run_tests` or
            # `mutate` call on this runner reports -- never the
            # AssertionError the exec would otherwise die on.
            return tuple(
                SweepVerdict(
                    spec,
                    "inconclusive",
                    note=(
                        "no pytest-capable interpreter was staged for the "
                        "runner, so the sweep could not run it"
                    ),
                )
                for spec in specs
            )
        contents = self._contents.get(Rev.HEAD, {})
        groups = sweep_groups(specs, contents)
        grouped: set[SweepSpec] = {spec for group in groups for spec in group.specs}
        out: list[SweepVerdict] = [
            SweepVerdict(
                spec,
                "inconclusive",
                note=(
                    "no test file imports this module; the sweep could "
                    "not aim a run at it"
                ),
            )
            for spec in specs
            if spec not in grouped
        ]
        budget_s = SWEEP_BUDGET_S if budget_s is None else budget_s
        started = clock.monotonic()
        limits = ToolLimits(16 * 1024, SWEEP_RUN_BOUND_S)
        floor = SWEEP_RUN_BOUND_S + KILL_AFTER_S + EXEC_SLACK_S
        for group in groups:
            remaining = budget_s - (clock.monotonic() - started)
            if remaining <= 0:
                out.extend(
                    SweepVerdict(
                        spec,
                        "inconclusive",
                        note="the sweep's wall budget was spent before this mutant ran",
                    )
                    for spec in group.specs
                )
                continue
            if self._suspect:
                self._restage()
            # PR code runs during the exec, whatever its outcome: the
            # bridge is suspect from the moment the exec starts, so an
            # exec that raises -- a lost connection, a timed-out group --
            # still leaves every later read re-staging instead of serving
            # what the failed exec's mutants left behind.
            self._suspect = True
            budget = min(
                (1 + len(group.specs)) * (SWEEP_RUN_BOUND_S + KILL_AFTER_S + 30)
                + len(group.specs) * MUTATE_EDIT_TIMEOUT_S
                + EXEC_SLACK_S,
                remaining,
            )
            if budget < floor:
                out.extend(
                    SweepVerdict(
                        spec,
                        "inconclusive",
                        note=(
                            "the sweep's remaining wall budget could not "
                            "fit this group's runs"
                        ),
                    )
                    for spec in group.specs
                )
                continue
            _code, text = self.session.exec(
                "mutant sweep",
                sweep_script(self.staged, group, limits),
                stage="bridge",
                budget_s=budget,
            )
            out.extend(parse_sweep(text, group))
        verdicts = tuple(out)
        self._sweep_cache[key] = verdicts
        return verdicts

    def grounding_plan(self) -> GroundingPlan:
        """The reviewed repo's declared lint/type/test commands (the
        grounding pre-pass's inventory): parsed from the controller's own
        copy of the merge-base tree's CI workflows, the revision the
        review is anchored to. A workflow that does not parse is named in
        the plan, never silently skipped."""
        return grounding_plan(self._contents.get(Rev.BASE, {}))

    def grounding(
        self,
        commands: Sequence[GroundingCommand],
        *,
        clock: Clock,
        budget_s: float | None = None,
    ) -> tuple[GroundingResult, ...]:
        """The controller's grounding pre-pass (the protocol's step 4.3):
        runs each declared command in its own disposable copy of the head
        tree -- the same copy, guard, clock and framing the `bash` tool
        uses -- without spending the attempt's call budget, because this
        is the controller's evidence gathering, not the model's. The
        pass's wall budget bounds the whole sequence: a command the
        remainder cannot fit at its full per-command budget is named,
        never started into a clamped exec and never silently skipped.
        Every
        command runs PR code, so the bridge stays suspect between
        commands and the next read re-stages; a command that never
        started, a copy that could not be made, and a failed exec are
        all named results, because a gap the report cannot show is a gap
        the lens reads as a clean run."""
        budget_s = GROUNDING_BUDGET_S if budget_s is None else budget_s
        started = clock.monotonic()
        limits = ToolLimits(16 * 1024, GROUNDING_RUN_BOUND_S)
        per_command = GROUNDING_RUN_BOUND_S + EXEC_SLACK_S + MUTATE_STAGE_SLACK_S
        out: list[GroundingResult] = []
        if self.staged.shim_python is None:
            return tuple(
                GroundingResult(
                    command,
                    note=(
                        "no interpreter on the runner image runs the no-root "
                        "guard, so no command could start"
                    ),
                )
                for command in commands
            )
        for command in commands:
            remaining = budget_s - (clock.monotonic() - started)
            if remaining < per_command:
                # The sweep's own floor shape: a command the remaining
                # wall cannot fit at its full per-command budget is named
                # rather than started into a clamped exec -- a run
                # truncated by the pass's own budget would read as a
                # tool hit or a tool failure that CI's run never was.
                out.append(
                    GroundingResult(
                        command,
                        note=(
                            "the grounding pass's remaining wall could "
                            "not fit this command"
                        ),
                    )
                )
                continue
            out.append(self._grounding_command(command, limits, per_command))
        return tuple(out)

    def _grounding_command(
        self,
        command: GroundingCommand,
        limits: ToolLimits,
        per_command: float,
    ) -> GroundingResult:
        """One declared command's exec and its result. A failed exec is a
        named result -- the pass goes on to the next command -- because
        one broken command must not cost the review the rest of its
        inventory."""
        if self._suspect:
            self._restage()
        # The command's own exec runs PR code, whatever its outcome: the
        # bridge is suspect from the moment the exec starts.
        self._suspect = True
        call = Call("bash", (("command", command.command),))
        assert self.staged.shim_python is not None
        try:
            code, text = self.session.exec(
                "grounding",
                bash_script(
                    self.staged,
                    call,
                    limits,
                    path=_grounding_path(self.staged.shim_python),
                ),
                stage="bridge",
                budget_s=per_command,
            )
            blocks = parse_run_blocks(text) if code == 0 else None
            if blocks is None:
                raise BoundaryError(
                    f"no run reply (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
                )
        except StreamTimeoutError as exc:
            return GroundingResult(command, note=f"the exec failed: {exc}")
        except BoundaryError as exc:
            return GroundingResult(command, note=f"the exec failed: {exc}")
        stage, run = _single_run(blocks)
        if stage.code != 0:
            return GroundingResult(
                command,
                note=f"the staged copy could not be made (exit {stage.code})",
            )
        assert run is not None
        return GroundingResult(
            command,
            exit=run.code,
            tail=run.content.decode("utf-8", errors="replace"),
            stderr_tail=run.stderr.decode("utf-8", errors="replace"),
        )

    def begin_attempt(self, lens: str, number: int) -> None:
        """Start one attempt's budget (#693): the call and output counters
        the session limits spend begin again -- the execution tools' caps
        (D80) among them -- and a refusal names the attempt that spent
        them."""
        self._attempt = f"{lens} attempt {number}"
        self._attempt_calls = 0
        self._attempt_shown = 0
        self._attempt_runs = 0
        self._attempt_mutants = 0

    def flagged(self) -> tuple[str, ...]:
        """Every secret value found so far, for `Redactor.sources`."""
        return tuple(self._flagged)

    def call(self, tool: Any, args: Any) -> BridgeResult:
        spent = self._spent() or self._execution_spent(tool)
        if spent is not None:
            return self._logged(self._refused(tool, Status.OVER_SESSION_LIMIT, spent))
        try:
            checked = validate(tool, args, frozenset(self.commits))
        except RejectedError as exc:
            return self._logged(self._refused(tool, Status.REJECTED, str(exc)))
        if checked.tool == "run_tests" and checked.get("command"):
            refusal = self._command_refusal(checked.get("command"))
            if refusal is not None:
                return self._logged(self._refused(tool, *refusal))
        return self._logged(self._run(checked))

    def _command_refusal(self, name: str) -> tuple[Status, str] | None:
        """The refusal a `run_tests` `command` name earns before anything
        runs (S7, D88), or None when it may run. The name is an
        exact-match lookup against the run's allow-list: a name no
        proposal carries is a rejected call -- a fixed code, no echo --
        because the model cannot mint a command; a proposed one routes
        through the run-scoped gate, where only a **pre-approved**
        addition grants -- installation admins pre-approve a repo's extra
        commands on the S10 settings page (part B, D88's update), there
        is no live approval during a review, and until part B the
        production channel approves nothing -- and every other outcome is
        the unapproved gap, named with the counts."""
        if self.approvals is None:
            return (
                Status.REJECTED,
                (
                    "unknown-command: this run's allow-list proposes no test "
                    "commands; the built-in pytest entry stands"
                ),
            )
        proposal = self.approvals.proposal(name)
        if proposal is None:
            return (
                Status.REJECTED,
                (
                    "unknown-command: no test command by that name is proposed "
                    "for this run's allow-list; the built-in pytest entry stands"
                ),
            )
        approved, reason = self.approvals.admit(name)
        if approved:
            return None
        return (Status.UNAVAILABLE, f"unapproved-command: {reason}")

    def _command_argv(self, call: Call) -> str:
        """The bridge-built argv of the approved proposed command (S7,
        D88): the proposal's own validated tokens, each shell-quoted,
        joined -- the declared command exactly as it was proposed, with
        no selector appended and nothing the model sent interpolated.
        The caller refused every unapproved name before this runs."""
        name = call.get("command")
        assert self.approvals is not None
        proposal = self.approvals.proposal(name)
        assert proposal is not None  # the caller refused the call before this
        return " ".join(quote(token) for token in proposal.argv)

    def _spent(self) -> str | None:
        limits = self.session_limits
        scope = f" ({self._attempt})" if self._attempt else ""
        if self._attempt_calls >= limits.max_calls:
            return (
                f"session-limit: all {limits.max_calls} calls of this attempt "
                f"made{scope}"
            )
        if self._attempt_shown >= limits.max_output_bytes:
            return (
                f"session-limit: all {limits.max_output_bytes} output bytes of "
                f"this attempt shown{scope}"
            )
        return None

    def _execution_spent(self, tool: Any) -> str | None:
        """The per-attempt cap on the two execution tools (D80), refused
        like any other spent budget: a hard cap below the call cap, so a
        lens cannot spend its whole session on executions."""
        limits = self.session_limits
        if not (isinstance(tool, str) and tool in RUN_TOOLS):
            return None
        made, cap, kind = (
            (self._attempt_runs, limits.max_test_runs, "run_tests")
            if tool in ("run_tests", "run_probe")
            else (self._attempt_mutants, limits.max_mutants, "mutate")
        )
        if made >= cap:
            scope = f" ({self._attempt})" if self._attempt else ""
            return f"session-limit: all {cap} {kind} calls of this attempt made{scope}"
        return None

    def _output_left(self) -> int:
        return self.session_limits.max_output_bytes - self._attempt_shown

    def _refused(self, tool: Any, status: Status, reason: str) -> BridgeResult:
        """Names a known tool, or `UNKNOWN_TOOL`; the arguments are not shown."""
        name = tool if isinstance(tool, str) and tool in TOOLS else UNKNOWN_TOOL
        return BridgeResult(
            name, "", status, RepoText(""),
            self.redactor(reason, STDERR_CHARS), 0, 0, 0, False, 0.0,
        )  # fmt: skip

    def _run(self, call: Call) -> BridgeResult:
        tool_limits = self.limits[call.tool]
        limits = replace(
            tool_limits, max_bytes=min(tool_limits.max_bytes, self._output_left())
        )
        started = self.clock.monotonic()
        if call.tool in RUN_TOOLS:
            return self._run_exec(call, limits, started)
        if call.tool in BASH_TOOLS:
            refused = self._bash_refusal(call, started)
            if refused is not None:
                return refused
            return self._exec_bash(call, limits, started)
        if call.tool in HISTORY_TOOLS:
            if not self.staged.history_head or self._history_lost:
                return self._history_gap(call, started)
            return self._run_history(call, limits, started)
        if call.tool in LOCAL_TOOLS and not (call.tool == "grep" and call.get("regex")):
            return self._run_local(call, limits, started)
        try:
            paths = self._diff_paths(call)
            reply = self._exec(call, limits, paths)
        except StreamTimeoutError as exc:
            return self._failed(call, Status.TIMED_OUT, str(exc), started)
        except _LostOutputError as exc:
            return self._failed(call, Status.FAILED, str(exc), started)
        except BoundaryError as exc:
            return self._failed(call, Status.UNAVAILABLE, str(exc), started)
        return self._result(call, reply, paths, self.clock.monotonic() - started)

    def _run_local(
        self, call: Call, limits: ToolLimits, started: float
    ) -> BridgeResult:
        """`read_file`, fixed-string `grep` and `list_files` are answered
        from the controller's own copy of the trees and the recorded
        mutation's splice (D80 round 2's decision): executed PR code can
        leave processes running in the runner (the per-call sweep that
        once killed them is retired -- see D80's update), so nothing read
        back from the runner is trusted as content -- these tools serve
        the controller-held bytes and never exec. The regex mode of
        `grep` is not among them: it stays on the runner (D80 round 3),
        inside the re-staged, timeout-bounded exec the diff trio rides.
        The result then runs through the same rendering, capping, secret
        scan and ledger the runner-served results use."""
        rev = call.get("rev")
        files = self._contents.get(rev)
        if files is None:  # pragma: no cover - validate gates the revisions
            return self._failed(
                call, Status.UNAVAILABLE, f"no controller copy of {rev}", started
            )
        try:
            if call.tool == "read_file":
                reply = _local_read(files, call, limits)
            elif call.tool == "grep":
                reply = _local_grep(files, call, limits, self.commits[rev])
            else:
                reply = _local_list(files, call, limits)
        except _MissingPath as exc:
            return self._failed(call, Status.FAILED, str(exc), started)
        return self._result(call, reply, (), self.clock.monotonic() - started)

    def _mutate_aim_refusal(self, call: Call, started: float) -> BridgeResult | None:
        """The mis-aim gate (round-2 review of #845): the controller's own
        copy of the head tree answers the aim check with no exec, so a
        mis-aimed `mutate` is refused before its baseline can run and the
        refusal really spends nothing -- the execution caps count what
        ran, and nothing ran -- where the old post-exec refusal let a
        lens burn a full baseline per mis-aim without ever taking a
        `max_mutants` slot. The runner script's refusal step stays as the
        parity backstop for an aim that slips past this check.

        A file the parser cannot even process -- a nesting so deep the
        parser exhausts its stack, or a resource failure -- is a
        machinery gap, not a mis-aim: the preflight reports it as the
        named unavailable result (a tool gap that holds the review at
        COMMENT, and charges nothing, because nothing ran) instead of
        letting the exception escape the bridge with no structured
        result."""
        try:
            refusal = _aim_refusal(
                self._contents.get(Rev.HEAD, {}).get(call.get("path"), b""),
                call.get("line"),
                call.get("operator"),
                call.get("operand"),
            )
        except (RecursionError, MemoryError) as exc:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                "the mutant preflight could not parse the head file: "
                f"{type(exc).__name__}",
                started,
            )
        if refusal is not None:
            return self._refused(
                call.tool, Status.REJECTED, f"the mutant was refused: {refusal}"
            )
        return None

    def _runner_gates(
        self, call: Call, argv: str | None, started: float
    ) -> BridgeResult | None:
        """The execution tools' runner gates, in the order the slices
        established: a missing pytest-capable interpreter, then a missing
        no-root-guard interpreter, then a failed collection probe. The
        built-in `run_tests` entry needs the pytest-capable interpreter
        itself; a proposed command (S7, D88) does not."""
        if argv is None and self.staged.pytest is None:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                "no pytest-capable interpreter was staged for the runner",
                started,
            )
        if self.staged.shim_python is None:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                "no interpreter on the runner image runs the no-root "
                "guard, so the execution tools cannot start",
                started,
            )
        if not self.staged.collection_ok:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                "the test environment is broken: pytest collection failed "
                f"in the staged copy: {self.staged.collection_note}",
                started,
            )
        return None

    def _run_exec(self, call: Call, limits: ToolLimits, started: float) -> BridgeResult:
        """`run_tests` and `mutate` (D80): one exec per call, its reply
        parsed into run blocks (and, for `mutate`, the mutation's), the
        mutant's verdict computed here from the runs' exits and the
        controller's own parse of their summary lines -- never from text
        the test processes chose to print. A missing interpreter, a
        malformed reply and a lost output are gaps, never crashes; the
        verdicts themselves are in-band evidence, like every status the
        exec stream carries. A `run_tests` call naming an approved
        proposed command (S7, D88) runs the proposal's own bridge-built
        argv instead of the pytest one. Neither ever runs as root
        (Brandon's Nov 25 decision): both go through the no-root guard,
        which runs through the interpreter the staging probe resolved --
        the pytest-capable one when there is one, else any candidate that
        runs -- so a runner with no interpreter at all refuses both,
        named. The built-in entry also needs the pytest-capable
        interpreter itself. A runner whose collection probe failed (the
        test environment cannot import or collect the repo's tests)
        refuses both with that named gap -- the run would only produce
        INCONCLUSIVE mutants and red baselines the lens cannot read as
        evidence."""
        command = call.get("command") if call.tool == "run_tests" else ""
        argv = self._command_argv(call) if command else None
        refused = self._runner_gates(call, argv, started)
        if refused is not None:
            return refused
        if call.tool == "mutate":
            refused = self._mutate_aim_refusal(call, started)
            if refused is not None:
                return refused
        try:
            # Since the last execution could have rewritten anything it
            # could reach, the execution starts from a re-staged,
            # digest-checked repository and trees.
            if self._suspect:
                self._restage()
            budget = (
                2 * limits.timeout_s
                + MUTATE_EDIT_TIMEOUT_S
                + 2 * KILL_AFTER_S
                + EXEC_SLACK_S
                + MUTATE_EDIT_SLACK_S
                + MUTATE_STAGE_SLACK_S
                if call.tool == "mutate"
                else limits.timeout_s + EXEC_SLACK_S + MUTATE_STAGE_SLACK_S
            )
            # PR code runs during the exec, whatever its outcome: the
            # bridge is suspect from the moment the exec starts, so an
            # exec that raises -- a lost connection mid-run -- still
            # leaves every later read re-staging instead of serving what
            # the failed run's code left behind.
            self._suspect = True
            code, text = self.session.exec(
                f"bridge {call.tool}",
                mutate_script(self.staged, call, limits)
                if call.tool == "mutate"
                else run_probe_script(self.staged, call, limits)
                if call.tool == "run_probe"
                else run_test_script(self.staged, call, limits, argv),
                stage="bridge",
                budget_s=budget,
            )
            blocks = parse_run_blocks(text) if code == 0 else None
            if blocks is None:
                raise BoundaryError(
                    f"no run reply (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
                )
            for block in blocks:
                if isinstance(block, _RunBlock) and (problem := block.problem()):
                    raise _LostOutputError(problem)
            if call.tool == "mutate":
                mut = next((b for b in blocks if isinstance(b, _MutBlock)), None)
                if mut is not None:
                    refusal = mutation_refusal(mut.payload, mut.apply_exit)
                    if refusal is not None and refusal != _WRITE_REFUSAL:
                        # A mis-aimed mutant is the model's error to
                        # re-aim (D80's 2026-11-26 update): a refused
                        # call, not an inconclusive verdict -- an
                        # inconclusive one is an execution gap that holds
                        # the review at COMMENT, and the model's own
                        # wrong line number must not cost the lens its
                        # clean state. The pre-exec aim check has already
                        # refused every mis-aim without an exec, so a
                        # refusal that arrives here is the runner
                        # script's own backstop -- or a machinery
                        # failure: the temporary write's OSError reads
                        # as a copy that could not be written, which is
                        # not an aim at all, and charging it as the
                        # model's free mis-aim would hide a broken
                        # runner behind a clean state. Machinery
                        # failures stay on the inconclusive path, where
                        # their executed work is charged.
                        return self._refused(
                            call.tool,
                            Status.REJECTED,
                            f"the mutant was refused: {refusal}",
                        )
            return self._run_result(call, blocks, started)
        except StreamTimeoutError as exc:
            return self._failed(call, Status.TIMED_OUT, str(exc), started)
        except _LostOutputError as exc:
            return self._failed(call, Status.FAILED, str(exc), started)
        except BoundaryError as exc:
            return self._failed(call, Status.UNAVAILABLE, str(exc), started)

    def _restage(self) -> None:
        """Rebuilds the runner's repository, trees and scratch from the
        controller-held tarballs (D80 round 2), because executed code can
        rewrite anything it can reach and git does not re-verify a loose
        object on read: the tarballs are the one source of truth it can
        never touch. The staging is deterministic, so the recorded BASE
        and HEAD ids must come back exactly -- anything else is a
        boundary error, a gap. A recorded
        mutation re-applies on a fresh copy, and the mutant commit is
        re-created with the same id, so the reads at MUTANT keep serving
        the mutation the record names. Cleared, the runner's state is
        exactly what the controller staged, with nothing alive that could
        rewrite it before the caller's read."""
        digests = {
            rev: hashlib.sha256(data).hexdigest() for rev, data in self.trees.staged()
        }
        for rev, data in self.trees.staged():
            self.session.upload(
                data,
                f"{quote(self.staged.root)}/{rev.value.lower()}.tar.gz",
                f"{rev.value} tree re-upload",
            )
        code, text = self.session.exec(
            "bridge restage",
            restage_script(self.staged, self._mutation, self.unpack, digests),
            stage="bridge staging",
            budget_s=RESTAGE_BUDGET_S,
        )
        commits = parse_staged(code, text, tuple(self.staged.commits), self.unpack)
        if commits != dict(self.staged.commits):
            raise BoundaryError(
                f"the re-staged commits differ from the recorded ones "
                f"(exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
            )
        if self.history_bundle is not None:
            # The restage rebuilt the repository from the tarballs: the
            # real history the bundle brought is gone with it, so the
            # bundle is re-uploaded and re-fetched here. A re-fetch that
            # fails marks the history lost -- the history tools then
            # report the named gap -- rather than failing the caller's
            # read, which has nothing to do with the bundle.
            try:
                upload_history_bundle(
                    self.session, self.history_bundle, self.staged.root
                )
                hcode, htext = self.session.exec(
                    "history re-fetch",
                    history_fetch_script(
                        self.staged.root,
                        self.staged.git,
                        self.history_base,
                        self.staged.history_head,
                    ),
                    stage="bridge staging",
                    budget_s=RESTAGE_BUDGET_S,
                )
                parse_history(hcode, htext, self.staged.history_head)
            except BoundaryError:
                self._history_lost = True
        if self._mutation is not None:
            blocks = parse_run_blocks(text)
            applied = next((b for b in blocks or () if isinstance(b, _MutBlock)), None)
            ok, _before, _after, _reason = (
                parse_mutation(applied.payload, applied.apply_exit)
                if applied is not None
                else (False, "", "", "no mutation step ran")
            )
            if not ok or applied is None or applied.commit != self._mutation.commit:
                raise BoundaryError(
                    "the re-applied mutant commit differs from the recorded one "
                    f"(exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
                )
        self._suspect = False

    def _run_result(
        self,
        call: Call,
        blocks: tuple[_RunBlock | _MutBlock | _StageBlock, ...],
        started: float,
    ) -> BridgeResult:
        seconds = self.clock.monotonic() - started
        if call.tool in ("run_tests", "run_probe"):
            stage, run = _single_run(blocks)
            if stage.code != 0:
                # F4: a copy that could not be staged is a staging
                # failure, never a test result -- the exit the failing
                # `cd` or `cp` left behind must not be read as pytest's.
                return self._failed(
                    call,
                    Status.UNAVAILABLE,
                    f"the staged copy could not be made (exit {stage.code})",
                    started,
                )
            assert (
                run is not None
            )  # the script runs the copy only when staging succeeded
            return self._exec_result(
                call,
                _run_status(run.code),
                (RunRecord(run.code, _summary_of(run)),),
                None,
                None,
                "",
                run,
                self.clock.monotonic() - started,
            )
        stage1, baseline, stage2, applied, mutated = _mutant_shape(blocks)
        if stage1.code != 0:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                f"the staged copy could not be made (exit {stage1.code})",
                started,
            )
        assert (
            baseline is not None
        )  # the script runs the copy only when staging succeeded
        if stage2 is not None and stage2.code != 0:
            # The second staging (F2's fresh copy for the mutation) failed:
            # the mutant never applied, and nothing after it ran.
            return self._exec_result(
                call,
                Status.OK,
                (RunRecord(baseline.code, _summary_of(baseline)),),
                None,
                MutantOutcome.INCONCLUSIVE,
                f"the mutated copy could not be staged (exit {stage2.code})",
                baseline,
                seconds,
            )
        assert stage2 is not None and applied is not None
        ok, before, after, apply_reason = parse_mutation(
            applied.payload, applied.apply_exit
        )
        outcome, outcome_reason = mutant_outcome(
            ok, apply_reason, baseline, mutated,
            _summary_of(baseline),
            _summary_of(mutated) if mutated is not None else None,
        )  # fmt: skip
        if ok and applied.commit not in ("-", ""):
            # MUTANT resolves at the commit id this bridge's own commit
            # step recorded (D80 rounds 1-2): the id is a
            # content-addressed *name* the controller holds, and what
            # protects the content behind it is the re-stage -- which
            # rebuilds the repository from the digest-checked tarballs
            # and re-applies the recorded mutation deterministically --
            # plus the re-created-id check, not git's read path (git does
            # not re-verify a loose object on read). Executed code moving
            # or forging the `atlas-mutant` ref changes nothing the read
            # tools serve; the ref stays as bookkeeping only.
            self.commits = MappingProxyType(
                {**self.staged.commits, Rev.MUTANT: applied.commit}
            )
        record = MutationRecord(
            call.get("operator"),
            call.get("path"),
            call.get("line"),
            before,
            after,
            "" if applied.commit in ("-", "") else applied.commit,
            call.get("operand"),
        )
        if record.commit:
            # A re-stage re-applies this mutation deterministically (D80
            # round 2), so the mutant tree the record names survives the
            # rebuild -- and the controller's own MUTANT map, what the
            # read tools actually serve, is the same splice applied to
            # its own copy of the head tree.
            self._mutation = record
            self._contents[Rev.MUTANT] = self._mutant_contents()
        runs: tuple[RunRecord, ...] = (RunRecord(baseline.code, _summary_of(baseline)),)
        if mutated is not None:
            runs += (RunRecord(mutated.code, _summary_of(mutated)),)
        return self._exec_result(
            call, Status.OK, runs, record, outcome, outcome_reason,
            mutated or baseline, seconds,
            edit_stderr=applied.stderr,
        )  # fmt: skip

    def _exec_result(
        self,
        call: Call,
        status: Status,
        runs: tuple[RunRecord, ...],
        mutation: MutationRecord | None,
        outcome: MutantOutcome | None,
        outcome_reason: str,
        block: _RunBlock,
        seconds: float,
        edit_stderr: bytes = b"",
    ) -> BridgeResult:
        text = block.content.decode("utf-8", errors="replace")
        scan = detect_secrets(text)
        stderr = block.stderr.decode("utf-8", errors="replace")
        if edit_stderr and not stderr:
            # F6: the mutation step's own stderr is runtime text like the
            # runs', redacted and shown the same way.
            stderr = edit_stderr.decode("utf-8", errors="replace")
        self._flagged.extend(scan.values)
        # Test output is not tree content: a hit has no location, and it is
        # not the PR's committed secret, so it is recorded as not
        # introduced (D80).
        secrets = tuple(BridgeSecret(hit.label, None, None, True) for hit in scan.hits)
        return BridgeResult(
            call.tool,
            call.args_json,
            status,
            RepoText(text),
            self.redactor(stderr, STDERR_CHARS) if stderr else None,
            len(block.content),
            block.total_bytes,
            block.total_lines,
            len(block.content) < block.total_bytes,
            seconds,
            secrets,
            None,
            scan.values,
            runs,
            mutation,
            outcome,
            outcome_reason,
            self.staged.head_sha,
            call.get("command") if call.tool == "run_tests" else "",
        )

    def _exec(
        self, call: Call, limits: ToolLimits, paths: tuple[str, ...] = ()
    ) -> _Reply:
        if self._suspect:
            # Executed code may have rewritten what the read tools serve
            # (D80 round 2): re-stage from the controller-held tarballs
            # before anything is served.
            self._restage()
        code, text = self.session.exec(
            f"bridge {call.tool}",
            call_script(self.staged, call, limits, paths, self.commits),
            stage="bridge",
            budget_s=limits.timeout_s + EXEC_SLACK_S,
        )
        reply = parse_reply(text) if code == 0 else None
        if reply is None:
            raise BoundaryError(
                f"no bridge reply (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
            )
        problem = reply.problem()
        if problem is not None:
            raise _LostOutputError(problem)
        return reply

    def _history_gap(self, call: Call, started: float) -> BridgeResult:
        """The named no-history gap: the run staged no history (or the
        staging's bundle flow degraded, `history_note` naming why), or the
        repository was re-staged after executed code ran and the re-fetch
        of the controller-held bundle failed. `git_log`, `git_show` and
        `git_blame` report this instead of running against a repository
        whose history is gone, where the range's log would be silently
        empty or the rev guard would reject reads the caller named
        correctly."""
        why = (
            self.staged.history_note
            or "no repository history was staged for this runner; "
            "the history tools read the bundle the run's staging "
            "carries, and this run staged none"
        )
        if self._history_lost:
            why = (
                "the re-staged repository lost the history bundle's "
                "fetch and the re-fetch failed: " + why
            )
        return self._failed(call, Status.UNAVAILABLE, why, started)

    def _bash_refusal(self, call: Call, started: float) -> BridgeResult | None:
        """The bash tool's one gate (D80's bash-tool update): the no-root
        guard's interpreter. The test environment's own refusals -- a
        missing pytest, a failed collection -- are not its gates: a broken
        pytest collection does not stop a ruff run or a git log."""
        if self.staged.shim_python is None:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                "no interpreter on the runner image runs the no-root "
                "guard, so the execution tools cannot start",
                started,
            )
        return None

    def _exec_bash(
        self, call: Call, limits: ToolLimits, started: float
    ) -> BridgeResult:
        """The bash tool's exec (D80's bash-tool update): the same
        disposable copy, guard, clock, output caps and framing the run
        tools use; the reply parses as one run block, and the exit maps
        through the same statuses. No run slot is spent: the bash call is
        bounded by the attempt's call budget and the lens's wall clocks,
        not by the test-run cap. The re-stage discipline applies as
        everywhere: the copy's `.git` file points at the staged
        repository itself, so the command can write into `repo.git` -- a
        later call's copy and git reads are built from the re-staged
        repository, never from what an earlier command left there."""
        try:
            # Since the last execution could have rewritten anything it
            # could reach -- the staged repository included, which the
            # copy's git points at -- the copy is built from a re-staged,
            # digest-checked repository. And the command's own exec runs
            # PR code, whatever its outcome: the bridge is suspect from
            # the moment the exec starts, so an exec that raises -- a
            # lost connection mid-command -- still leaves every later
            # read re-staging instead of serving what the failed command
            # left behind.
            if self._suspect:
                self._restage()
            self._suspect = True
            code, text = self.session.exec(
                "bridge bash",
                bash_script(self.staged, call, limits),
                stage="bridge",
                budget_s=limits.timeout_s + EXEC_SLACK_S + MUTATE_STAGE_SLACK_S,
            )
            blocks = parse_run_blocks(text) if code == 0 else None
            if blocks is None:
                raise BoundaryError(
                    f"no run reply (exit {code}): {guest_text(text, GUEST_TAIL_CHARS)}"
                )
            for block in blocks:
                if isinstance(block, _RunBlock) and (problem := block.problem()):
                    raise _LostOutputError(problem)
        except StreamTimeoutError as exc:
            return self._failed(call, Status.TIMED_OUT, str(exc), started)
        except _LostOutputError as exc:
            return self._failed(call, Status.FAILED, str(exc), started)
        except BoundaryError as exc:
            return self._failed(call, Status.UNAVAILABLE, str(exc), started)
        stage, run = _single_run(blocks)
        if stage.code != 0:
            return self._failed(
                call,
                Status.UNAVAILABLE,
                f"the staged copy could not be made (exit {stage.code})",
                started,
            )
        assert run is not None  # the script runs the copy only when staging succeeded
        return self._exec_result(
            call,
            _run_status(run.code),
            (RunRecord(run.code, _summary_of(run)),),
            None,
            None,
            "",
            run,
            self.clock.monotonic() - started,
        )

    def _run_history(
        self, call: Call, limits: ToolLimits, started: float
    ) -> BridgeResult:
        """The read-only history tools (D80's git-history update): one
        exec against the staged repository's real history, framed and
        parsed like the other git tools'. The rev guard inside the exec
        refuses a revision outside the pull request's range and base's
        history as a rejected call; the re-stage discipline applies as
        everywhere, because executed PR code may have rewritten the
        repository the history lives in -- and a re-stage whose re-fetch
        failed ends the call at the named gap, before the exec could read
        a repository without the history."""
        if self._suspect:
            self._restage()
        if self._history_lost:
            return self._history_gap(call, started)
        try:
            code, text = self.session.exec(
                f"bridge {call.tool}",
                history_script(self.staged, call, limits),
                stage="bridge",
                budget_s=limits.timeout_s + EXEC_SLACK_S,
            )
            reply = parse_reply(text) if code == 0 else None
            if reply is None:
                raise BoundaryError(
                    f"no bridge reply (exit {code}): "
                    f"{guest_text(text, GUEST_TAIL_CHARS)}"
                )
            problem = reply.problem()
            if problem is not None:
                raise _LostOutputError(problem)
        except StreamTimeoutError as exc:
            return self._failed(call, Status.TIMED_OUT, str(exc), started)
        except _LostOutputError as exc:
            return self._failed(call, Status.FAILED, str(exc), started)
        except BoundaryError as exc:
            return self._failed(call, Status.UNAVAILABLE, str(exc), started)
        return self._result(call, reply, (), self.clock.monotonic() - started)

    def _diff_paths(self, call: Call) -> tuple[str, ...]:
        """What `diff_file` diffs: its path, or both sides of the rename it
        is part of, so git pairs them instead of showing an add or a delete."""
        if call.tool != "diff_file":
            return ()
        path = call.get("path")
        return self._rename_map().get(path, (path,))

    def _rename_map(self) -> Mapping[str, tuple[str, str]]:
        """The PR's renames, listed once per bridge."""
        if self._renames is None:
            self._renames = _rename_pairs(
                self._exec(Call("renames", ()), RENAME_LIMITS)
            )
        return self._renames

    def _failed(
        self, call: Call, status: Status, detail: str, started: float
    ) -> BridgeResult:
        return BridgeResult(
            call.tool, call.args_json, status, RepoText(""),
            self.redactor(detail, STDERR_CHARS), 0, 0, 0, False,
            self.clock.monotonic() - started,
        )  # fmt: skip

    def _result(
        self, call: Call, reply: _Reply, paths: tuple[str, ...], seconds: float
    ) -> BridgeResult:
        limits = self.limits[call.tool]
        status = _status(call.tool, reply.code)
        commit = self.commits[call.get("rev")] if call.tool == "grep" else ""
        skipped, content = _page(call, reply)
        view = _view(call, content, commit, self._preexisting, paths)
        scan = detect_secrets(view.text)
        shown = len(content)
        cut = (
            shown < reply.total_bytes
            or (limits.max_lines is not None and reply.total_lines > limits.max_lines)
            or not view.complete
        )
        stderr = reply.stderr.decode("utf-8", errors="replace")
        self._flagged.extend(scan.values)
        return BridgeResult(
            call.tool,
            call.args_json,
            status,
            RepoText(view.text),
            self.redactor(stderr, STDERR_CHARS) if stderr else None,
            shown,
            reply.total_bytes,
            reply.total_lines,
            cut,
            seconds,
            _secrets(scan, view.places),
            (
                call.get("offset") + skipped + shown
                if cut and call.tool == "diff_file"
                else None
            ),
            scan.values,
        )

    def _preexisting(self, rev: Rev, path: str) -> bool:
        return rev is not Rev.HEAD or path not in self.changed

    def _logged(self, result: BridgeResult) -> BridgeResult:
        self.calls.append(
            CallRecord(
                result.tool,
                result.args,
                result.status,
                result.shown_bytes,
                result.total_bytes,
                result.truncated,
                result.seconds,
                len(result.secrets),
            )
        )
        self._attempt_calls += 1
        self._attempt_shown += result.shown_bytes
        # The execution caps count what ran (D80 round 1): a refused call
        # -- rejected arguments or an already-spent budget -- spent no
        # execution resource, so it takes no slot; a run that timed out
        # did run, and keeps its slot.
        spent_nothing = result.status in (Status.REJECTED, Status.OVER_SESSION_LIMIT)
        if result.tool in ("run_tests", "run_probe") and not spent_nothing:
            self._attempt_runs += 1
        elif result.tool == "mutate" and not spent_nothing:
            self._attempt_mutants += 1
        return result


def render(result: BridgeResult) -> str:
    """The result as the model reads it: one controller-written line, then
    the content. The arguments are the validated ones, shown as JSON; a
    rejected call shows none, only its code and reason. The execution
    tools' (D80) controller lines name the head SHA the runs are evidence
    about (D73), each run's exit and its parsed summary, and, for
    `mutate`, the mutant's verdict and the mutation itself, with the
    statement before and after it quoted as the data it is."""
    head = (
        f"{' '.join(filter(None, (result.tool, result.args)))}: {result.status.value}"
    )
    if result.truncated:
        head += (
            f"; output cut: {result.shown_bytes} of {result.total_bytes} bytes shown"
            f" ({result.total_lines} lines in all)"
        )
    if result.next_offset is not None:
        head += f"; next page at offset {result.next_offset}"
    if result.secrets:
        head += f"; {len(result.secrets)} possible committed secret(s) reported to the controller"
    if result.head_sha:
        head += f"; head {result.head_sha}"
    if result.approved:
        head += f"; {result.approved} ran as a pre-approved addition for this run"
    head += _run_lines(result)
    error = f"\nerror: {result.error.text}" if result.error else ""
    return f"{head}{error}\n{result.content.text}"


def _run_lines(result: BridgeResult) -> str:
    if not result.runs and result.mutation is None and result.outcome is None:
        return ""
    labels = (
        ("test run",) if result.tool == "run_tests" else ("baseline run", "mutated run")
    )
    lines = [
        f"\n{label}: exit {run.exit}{_summary_part(run.summary)}"
        for label, run in zip(labels, result.runs, strict=False)
    ]
    if result.tool == "mutate" and len(result.runs) < 2:
        lines.append("\nmutated run: not run")
    if result.outcome is not None:
        mutant = result.mutation.commit if result.mutation else ""
        named = f" {mutant}" if mutant else ""
        lines.append(f"\nmutant{named} {result.outcome.value}: {result.outcome_reason}")
    if result.mutation is not None:
        change = result.mutation
        before = quote_untrusted(change.before, QUOTED_CHARS, scrub=str)
        after = quote_untrusted(change.after, QUOTED_CHARS, scrub=str)
        lines.append(
            f"\nmutation at {change.path}:{change.line} ({change.operator}): "
            f"{before} -> {after} (quoted data)"
        )
    return "".join(lines)


def _summary_part(summary: TestSummary | None) -> str:
    if summary is None:
        return ""
    return f", {summary.render()}"


def run_bridge(
    api: SpritesApi,
    ledger: RunnerLedger,
    trees: SourceTrees,
    body: Callable[[Bridge], str],
    *,
    redactor: Redactor,
    changed: frozenset[str],
    name: str,
    deadline_s: float,
    clock: Clock,
    telemetry: Telemetry | None = None,
    limits: Mapping[str, ToolLimits] = DEFAULT_LIMITS,
    session_limits: SessionLimits = DEFAULT_SESSION,
    root: str = BRIDGE_ROOT,
    first_frame_s: float = FIRST_FRAME_BUDGET_S,
    unpack: UnpackLimits = DEFAULT_UNPACK,
    create_retries: int = DEFAULT_CREATE_RETRIES,
    create_gate: threading.Semaphore | None = None,
    pytest_candidates: Sequence[str] = PYTEST_CANDIDATES,
    # The interpreters the lifecycle's own resolution probes when the
    # caller names them (the eval run's staged interpreter, D98); None
    # probes the image's trusted shapes. When given it also names the
    # staging probe's pytest candidates, so the setup phase's interpreter
    # and the staged pytest are the same one.
    python_candidates: Sequence[str] | None = None,
    approvals: RunApprovals | None = None,
    setup: SetupSpec | None = None,
    env: Mapping[str, str] | None = None,
    history_bundle: bytes | None = None,
    history_base: str = "",
) -> RunnerReport:
    """Stage `trees` on a fresh disposable runner and hand `body` the
    bridge; the runner is always destroyed. Trees over the upload cap or
    past `unpack` are refused before anything is created, and the runner
    holds `unpack` again as it extracts them. `create_retries` and
    `create_gate` shape how the create behind staging is retried and
    bounded; see `runner.run_session`. `pytest_candidates` names the
    interpreters the staging probe asks about (D80); the default is the
    runner image's own pyenv versions and system python. `approvals` is
    the run-scoped operator-approval gate (S7, D88) -- the proposals the
    repo's default-branch config named, the channel that answers them,
    and the approved set that dies with this runner; None proposes
    nothing, and every `command` a call then names is refused. `setup`
    (issue #819, D95) is the repo's declared setup phase: it runs with
    egress still allowed, before the deny-all flip and before staging
    uploads anything, so its installs can reach their indexes."""
    telemetry = telemetry or Telemetry(clock)
    try:
        limits = run_tool_limits(env if env is not None else os.environ, limits)
    except BoundaryError as exc:
        telemetry.record("tool limits", "refused", status=ERROR, error=str(exc))
        return RunnerReport(
            RunnerStatus.FAILED, CleanupStatus.NOT_CREATED, name, str(exc)
        )
    try:
        check_sizes(trees, unpack=unpack)
    except BoundaryError as exc:
        telemetry.record("upload", "size check", status=ERROR, error=str(exc))
        return RunnerReport(
            RunnerStatus.FAILED, CleanupStatus.NOT_CREATED, name, str(exc)
        )

    def session_body(session: Session) -> str:
        staged = stage(
            session,
            trees,
            root,
            unpack,
            pytest_candidates if python_candidates is None else python_candidates,
            history_bundle=history_bundle,
            history_base=history_base,
        )
        telemetry.record(
            "bridge staging", "staged",
            {
                "revisions": len(staged.commits),
                "git": staged.git,
                "git_version": staged.git_version,
                "pytest": staged.pytest.path if staged.pytest else "none",
            },
        )  # fmt: skip
        return body(
            Bridge(
                session,
                staged,
                redactor,
                clock,
                changed,
                limits,
                session_limits,
                trees,
                unpack,
                approvals=approvals,
                history_bundle=history_bundle,
                history_base=history_base,
                # The collection probe executed the copy's own conftest.py
                # -- PR code, in the runner -- so the bridge's first
                # runner-side read or execution copy re-stages from the
                # controller-held tarballs, whatever the probe's verdict
                # was.
                _suspect=staged.collection_ran,
            )
        )

    return run_session(
        api, ledger, session_body, name=name, deadline_s=deadline_s, clock=clock,
        telemetry=telemetry, first_frame_s=first_frame_s,
        create_retries=create_retries, create_gate=create_gate, setup=setup,
        python_candidates=python_candidates,
    )  # fmt: skip


# ------------------------------------------------- the controller sweep


@dataclass(frozen=True)
class SweepSpec:
    """One mutant the controller's pre-pass sweeps (D80's 2026-11-26
    update): a file, the line the condition or the break/continue starts
    on, the operator, and `drop-operand`'s kept operand. Built from the
    diff's added lines over the head tree's own AST, widened to the guards
    of the functions the diff changes or calls one hop away, ranked by
    relevance, deduplicated, and capped by the caller."""

    path: str
    line: int
    operator: str
    operand: int | None = None


@dataclass(frozen=True)
class SweepVerdict:
    """One swept mutant's outcome and its scoped run's exit. `note`
    carries the controller's own why for an inconclusive or refused
    mutant."""

    spec: SweepSpec
    outcome: str
    exit: int | None = None
    note: str = ""


@dataclass(frozen=True)
class SweepGroup:
    """The mutants one sweep exec serves: the module they mutate and the
    test files that import it -- the scoped selector each run executes,
    in place of the whole suite."""

    module: str
    selectors: tuple[str, ...]
    specs: tuple[SweepSpec, ...]


def added_lines(diff_text: str) -> frozenset[int]:
    """The head-side line numbers the diff adds: from each hunk's `@@`
    header the new side's start, counting every context and added line.
    The text is one file's diff (`split_files` splits it), so the `+++`
    header line sits before the first `@@` and every `+` line inside a
    hunk is a genuinely added line -- one whose content itself begins
    with `++` included."""
    added: set[int] = set()
    head = 0
    in_hunk = False
    for line in diff_text.split("\n"):
        if line.startswith("@@"):
            parts = line.split()
            new_side = next((p for p in parts if p.startswith("+")), None)
            if new_side is None:
                in_hunk = False
                continue
            head = int(new_side[1:].split(",")[0])
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added.add(head)
            head += 1
        elif in_hunk and (line.startswith(" ") or line == ""):
            head += 1
    return frozenset(added)


def _is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _imports_module(source: str, module: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module for alias in node.names):
                return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                # Both `import a.b.c`-style dotted modules and the
                # `from a.b import c` form, whose imported name joined to
                # the from-module is the dotted path -- the common test-file
                # spelling of `from atlas_reviewer import bridge`.
                node.module == module
                or any(
                    f"{node.module}.{alias.name}" == module
                    for alias in node.names
                    if alias.name != "*"
                )
            )
        ):
            return True
    return False


def _def_spans(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Every function definition as `(name, first line, last line)`, the
    span its body's guards live in. `end_lineno` is never None on a
    function node under this repo's 3.12 floor; the `or` is the type
    checker's."""
    spans: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.name, node.lineno, node.end_lineno or node.lineno))
    return spans


def _changed_spans(
    spans: Sequence[tuple[str, int, int]], added: frozenset[int]
) -> list[tuple[str, int, int]]:
    """The definitions whose OWN body the diff adds a line to: the
    functions the diff changes, whose every guard -- added or
    pre-existing -- is sweep-relevant, because the change is what moved
    their behavior. A line inside a nested def changes the nested def,
    not every function that encloses it, so an outer function's own
    guards do not rank as changed just because it contains one -- only
    the innermost def holding the added line claims it."""
    return [
        (name, start, end)
        for name, start, end in spans
        if any(_owned_by(line, (name, start, end), spans) for line in added)
    ]


def _owned_by(
    line: int,
    span: tuple[str, int, int],
    spans: Sequence[tuple[str, int, int]],
) -> bool:
    """Whether the line sits in the span and in no nested def inside it --
    the innermost def holding the line is the one the line changes."""
    _name, start, end = span
    if not start <= line <= end:
        return False
    return not any(
        inner_start >= start
        and inner_end <= end
        and (inner_start, inner_end) != (start, end)
        and inner_start <= line <= inner_end
        for _inner_name, inner_start, inner_end in spans
    )


def _call_names(
    tree: ast.AST,
    added: frozenset[int],
    changed: Sequence[tuple[str, int, int]],
) -> frozenset[str]:
    """The names the changed code calls, one hop: a call's own line is an
    added line, or it sits inside a function the diff changes. Both the
    plain and the attribute form count (`begin_post(job)` and
    `board.begin_post(job)` both name `begin_post`), so a caller spelling
    does not decide what the sweep can reach."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        line = node.lineno
        if line not in added and not any(
            start <= line <= end for _name, start, end in changed
        ):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return frozenset(names)


def _guard_tier(
    line: int,
    added: frozenset[int],
    changed: Sequence[tuple[str, int, int]],
    called: Sequence[tuple[str, int, int]],
) -> int | None:
    """How far the guard's line sits from the change, as the plan ranks
    relevance: 0 on an added line, 1 inside a function the diff changes,
    2 inside a function the changed code calls one hop away, None
    otherwise -- a guard nothing in the diff reaches is not swept."""
    if line in added:
        return 0
    if any(start <= line <= end for _name, start, end in changed):
        return 1
    if any(start <= line <= end for _name, start, end in called):
        return 2
    return None


def _distance_to_diff(line: int, added: frozenset[int]) -> int:
    """The guard's line's distance to the nearest added line of its own
    file; 0 on an added line itself, and the no-diff sentinel in a file
    whose guards came in only through the called-function widening."""
    if not added:
        return _NO_DIFF_DISTANCE
    return min(abs(line - target) for target in added)


def _rank(spec: SweepSpec, tier: int, distance: int) -> tuple[int, int, int, int, int]:
    """The plan's relevance order: the mutation classes the parity key's
    mutants are -- a dropped BoolOp operand, a break that should be a
    continue -- sweep before the comparison flips and the guard negations;
    then nearest to the change first, the added line itself over the
    changed function's other guards over the called function's."""
    return (
        _SWEEP_OPERATOR_RANK[spec.operator],
        tier,
        distance,
        spec.line,
        spec.operand or 0,
    )


def sweep_specs(
    diff: str,
    contents: Mapping[str, bytes],
    cap: int = SWEEP_CAP,
) -> tuple[SweepSpec, ...]:
    """The changed conditions and break/continue statements the sweep
    will try: every `if`/`while`/conditional expression, `and`/`or`
    operand, `break`/`continue` and comparison in the head tree's own
    parse whose line the diff reaches -- on an added line, inside a
    function the diff changes, or inside a function the changed code
    calls one hop away (the #640 anchor's `begin_post` cancel check is
    pre-existing code a changed caller reaches, and the #661 anchor's
    budget loop sits mid-file in an almost-wholly-new module). Deduplicated,
    ranked by relevance and capped by round-robin over the changed files,
    so no one file's alphabetical luck spends the cap another file's
    relevant guards never see. Test files name no mutant: the
    sweep mutates the code the tests import, never the tests themselves,
    and a test-file mutant would only spend the cap."""
    parsed: dict[str, tuple[ast.Module, frozenset[int]]] = {}
    file_diffs = {f.path: f.text for f in split_files(diff)}
    for path in sorted(file_diffs):
        if _is_test_path(path):
            continue
        data = contents.get(path)
        if data is None:
            continue
        try:
            module = ast.parse(data.decode("utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        parsed[path] = (module, added_lines(file_diffs[path]))
    spans_by_path: dict[str, list[tuple[str, int, int]]] = {}
    changed_by_path: dict[str, list[tuple[str, int, int]]] = {}
    called_names: set[str] = set()
    for path, (head, added) in parsed.items():
        spans = _def_spans(head)
        spans_by_path[path] = spans
        changed_by_path[path] = _changed_spans(spans, added)
        called_names |= _call_names(head, added, changed_by_path[path])
    order: list[tuple[tuple[int, str], list[tuple[SweepSpec, int, int]]]] = []
    for path in sorted(parsed, key=lambda p: (risk_tier(p).rank, p)):
        called = [
            (name, start, end)
            for name, start, end in spans_by_path[path]
            if name in called_names
        ]
        head, added = parsed[path]
        ranked = _file_specs(path, head, added, changed_by_path[path], called)
        order.append(((risk_tier(path).rank, path), ranked))
    return _round_robin(order, cap)


def _file_specs(
    path: str,
    tree: ast.AST,
    added: frozenset[int],
    changed: Sequence[tuple[str, int, int]],
    called: Sequence[tuple[str, int, int]],
) -> list[tuple[SweepSpec, int, int]]:
    """One changed file's sweep candidates with their relevance fields:
    the guards the diff reaches, each carrying its tier and its distance
    to the nearest added line, in the plan's rank order."""
    out: list[tuple[SweepSpec, int, int]] = []
    seen: set[tuple[str, int, str, int | None]] = set()

    def add(spec: SweepSpec, tier: int) -> None:
        key = (spec.path, spec.line, spec.operator, spec.operand)
        if key in seen:
            return
        seen.add(key)
        out.append((spec, tier, _distance_to_diff(spec.line, added)))

    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line is None:
            continue
        tier = _guard_tier(line, added, changed, called)
        if tier is None:
            continue
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            add(SweepSpec(path, line, "negate-condition"), tier)
        elif isinstance(node, ast.BoolOp):
            for operand in range(1, len(node.values) + 1):
                add(SweepSpec(path, line, "drop-operand", operand), tier)
        elif isinstance(node, (ast.Break, ast.Continue)):
            add(SweepSpec(path, line, "break-continue"), tier)
        elif isinstance(node, ast.Compare):
            add(SweepSpec(path, line, "flip-compare"), tier)
    out.sort(key=lambda item: _rank(item[0], item[1], item[2]))
    return out


def _round_robin(
    order: Sequence[tuple[tuple[int, str], list[tuple[SweepSpec, int, int]]]],
    cap: int,
) -> tuple[SweepSpec, ...]:
    """The cap spent round-robin over the changed files, one spec per file
    per pass in each file's own rank order, files in risk-tier then path
    order: a bigger diff sweeps every changed file's most relevant guards
    before any file's second pick, never the first `cap` specs of one
    file's alphabetical luck."""
    specs: list[SweepSpec] = []
    for _pass in itertools.count():
        if len(specs) >= cap:
            break
        took = False
        for _key, ranked in order:
            if len(specs) >= cap:
                break
            if _pass < len(ranked):
                specs.append(ranked[_pass][0])
                took = True
        if not took:
            break
    return tuple(specs[:cap])


def sweep_groups(
    specs: Sequence[SweepSpec], contents: Mapping[str, bytes]
) -> tuple[SweepGroup, ...]:
    """Groups the specs by the module they mutate, with the test files
    that import it as each group's scoped selector, in the plan's own
    rank order: a group's place is its best spec's place in the plan, so
    the sweep's shared wall budget spends on the most relevant module's
    runs before a lower-ranked one, and an alphabetical module prefix
    cannot starve the top-ranked spec's group into inconclusive (the
    #846 defect, moved from plan time back to run time, dies here for
    every plan whose files do not share a risk tier). Within one tier
    the plan's own round-robin interleaves the files, so the best ranks
    ascend in path order and the execution order is the plan's own
    file order; the wall budget names whatever did not run, never
    silently. A module no test file imports forms no group: its mutants
    would run nothing, and the report says so instead of running exit-5
    suites."""
    by_module: dict[str, list[SweepSpec]] = {}
    for spec in specs:
        by_module.setdefault(spec.path, []).append(spec)
    tests = sorted(path for path in contents if _is_test_path(path))
    built: list[tuple[int, SweepGroup]] = []
    for module in sorted(by_module):
        dotted = module.removesuffix(".py").replace("/", ".")
        importers = [
            path
            for path in tests
            if _imports_module(contents[path].decode("utf-8", errors="replace"), dotted)
        ]
        if importers:
            group = SweepGroup(module, tuple(importers), tuple(by_module[module]))
            best = min(specs.index(spec) for spec in group.specs)
            built.append((best, group))
    built.sort(key=lambda pair: pair[0])
    return tuple(group for _best, group in built)


def sweep_script(
    staged: Staged,
    group: SweepGroup,
    run_limit: ToolLimits,
) -> str:
    """One sweep exec (D80's 2026-11-26 update): for the group's module,
    one baseline run of its importing test files on a fresh copy, then --
    per mutant spec -- a fresh copy, the fixed mutation script applied in
    place, and the same scoped run on the mutated tree. Every copy is
    built from the repository's objects and thrown away after its run, so
    nothing a mutant's tests write reaches the next mutant or any later
    call; each run is bounded on its own and each reply is one
    `atlas-baseline` or `atlas-sweep` tag line, so the controller reads
    verdicts, never test output it would have to trust."""
    root = quote(staged.root)
    scratch = quote(staged.scratch)
    assert staged.pytest is not None
    assert staged.shim_python is not None
    flags = " ".join(PYTEST_FLAGS)
    selectors = " ".join(quote(s) for s in group.selectors)
    argv = f"{staged.pytest.quoted} -I -B -m pytest {flags} {selectors}"
    guarded = as_nobody(staged.shim_python, argv)

    def run_line(name: str) -> str:
        return (
            f"  ( cd {scratch}; {FILE_LIMIT_CMDS}; "
            f"{guarded_env_exports(staged.scratch)}"
            "export PYTHONDONTWRITEBYTECODE=1; "
            f"exec timeout -k {KILL_AFTER_S} {run_limit.timeout_s} {guarded} ) "
            f"> {name}_out 2> {name}_err"
        )

    def tag(name: str, tag_name: str, index: str) -> str:
        return (
            f'  echo "{tag_name}:{index}:$?:'
            f"$(cat {name}_out {name}_err 2>/dev/null "
            '| tail -c 200 | base64 -w0)"'
        )

    lines = [
        f"cd {root}",
        f"export {' '.join(GIT_ENV)} PYTHONDONTWRITEBYTECODE=1",
        *stage_copy_steps(
            staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
        ),
        "stage=$?",
        'if [ "$stage" = 0 ]; then',
        run_line("base"),
        tag("base", _BASELINE_TAG, group.module.replace("/", "%")),
        "fi",
        f"rm -rf {root}/{SCRATCH_DIR} base_out base_err",
    ]
    for index, spec in enumerate(group.specs):
        operand = "" if spec.operand is None else f" {spec.operand}"
        edit = (
            f"( cd {scratch}; exec timeout -k {KILL_AFTER_S} "
            f"{MUTATE_EDIT_TIMEOUT_S} "
            f"{staged.pytest.quoted} -I -c {quote(MUTATION_SCRIPT)} "
            f"{quote(spec.path)} {spec.line} "
            f"{quote(spec.operator)}{operand} ) > mut_out 2> mut_err"
        )
        lines += [
            *stage_copy_steps(
                staged.root, staged.git, staged.scratch, staged.commits[Rev.HEAD]
            ),
            "stage=$?",
            'if [ "$stage" = 0 ]; then',
            f"  {edit}",
            "  case $(head -n 1 mut_out) in",
            '  "no "*)',
            '    echo "'
            + SWEEP_TAG
            + f':{index}:R:-:$(tail -c 200 mut_out | base64 -w0)";;',
            "  esac",
            '  if [ $(head -n 1 mut_out | cut -d" " -f1) = "ok" ]; then',
            run_line("mut"),
            tag("mut", SWEEP_TAG, str(index)),
            "  fi",
            "fi",
            f"rm -rf {root}/{SCRATCH_DIR} mut_out mut_err",
        ]
    lines.append(f"rm -rf {root}/out err 2>/dev/null")
    return "\n".join(lines)


def parse_sweep(text: str, group: SweepGroup) -> tuple[SweepVerdict, ...]:
    """One sweep exec's reply as verdicts: the group's baseline exit rules
    the mutants' readings (a baseline that did not pass makes every
    mutant inconclusive -- the environment or the tests are broken, which
    is the named gap, not evidence either way), and each mutant's exit
    maps to survived (0), inconclusive (the wall clock, or no test
    collected), killed (any other exit), or the edit's own refusal."""
    baseline_re = re.compile(
        re.escape(_BASELINE_TAG) + r":([^:]*):(\d+):([A-Za-z0-9+/=]*)$", re.MULTILINE
    )
    baselines = {
        name.replace("%", "/"): int(exit)
        for name, exit, _tail in baseline_re.findall(text)
    }
    # The run tags carry the exit (the verdict maps from it, against the
    # group's baseline); the edit's own refusal carries `R:-` instead.
    sweep_re = re.compile(
        re.escape(SWEEP_TAG) + r":(\d+):(\d+):([A-Za-z0-9+/=]*)$", re.MULTILINE
    )
    refused_re = re.compile(
        re.escape(SWEEP_TAG) + r":(\d+):R:-:([A-Za-z0-9+/=]*)$", re.MULTILINE
    )
    tagged = {
        int(index): ("X", exit, tail) for index, exit, tail in sweep_re.findall(text)
    }
    for index, tail in refused_re.findall(text):
        tagged[int(index)] = ("R", "-", tail)
    verdicts: list[SweepVerdict] = []
    for index, spec in enumerate(group.specs):
        found = tagged.get(index)
        if found is None:
            verdicts.append(
                SweepVerdict(
                    spec,
                    "inconclusive",
                    note="the sweep exec gave no verdict for this mutant",
                )
            )
            continue
        kind, exit, tail = found
        if kind == "R":
            reason = "refused"
            try:
                reason = (
                    base64.b64decode(tail).decode("utf-8", errors="replace").strip()
                )
            except ValueError:
                pass
            verdicts.append(SweepVerdict(spec, "refused", note=reason))
            continue
        exit_value = int(exit)
        baseline = baselines.get(group.module)
        if baseline is None:
            verdicts.append(
                SweepVerdict(
                    spec, "inconclusive", note="no baseline ran for this group"
                )
            )
            continue
        if baseline not in (0, 5):
            verdicts.append(
                SweepVerdict(
                    spec,
                    "inconclusive",
                    exit=baseline,
                    note=f"the baseline run did not pass (exit {baseline})",
                )
            )
            continue
        if exit_value in (_TIMED_OUT, _KILLED):
            verdicts.append(
                SweepVerdict(
                    spec,
                    "inconclusive",
                    exit=exit_value,
                    note="the scoped run hit its wall clock",
                )
            )
        elif exit_value == 5:
            verdicts.append(
                SweepVerdict(
                    spec,
                    "inconclusive",
                    exit=exit_value,
                    note="no test was collected (exit 5)",
                )
            )
        elif exit_value == 0:
            verdicts.append(SweepVerdict(spec, "survived", exit=exit_value))
        else:
            verdicts.append(SweepVerdict(spec, "killed", exit=exit_value))
    return tuple(verdicts)
