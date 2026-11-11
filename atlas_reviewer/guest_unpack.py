"""The runner-side bound on unpacking a source tarball (D39).

Defence in depth behind `source_archive.measure`: the controller's parser
cannot be proven to read every archive the way the runner's GNU tar does,
so the runner holds the same caps by GNU tar's own reading before it
writes anything:

- `tar -xOzf` streams every member's data as extraction would write it
  (sparse files expanded) through `head -c`, so past `max_bytes` the
  archive is refused;
- `tar -tzf` lists every member through `awk`, which refuses an archive
  listing over `max_members` members, a path nested deeper than
  `max_path_depth`, or paths that imply over `max_members` distinct parent
  directories. Extraction creates a directory for every parent of a member
  that the archive did not list first, and `ulimit -f` does not bound
  directories, so a few hundred bytes of deep paths can otherwise fill the
  disk;
- extraction then runs under `ulimit -f`, so no one file can grow past
  `max_bytes` whatever the headers claim.

Every tar run is under `timeout`. A tar stopped by it, an archive tar
cannot read, and a limit each print a tag the controller reports by name.
When the script itself finishes, a failed extraction removes the partial
tree. When the controller's exec deadline or the runner's death stops the
script first, nothing is cleaned up: the runner is destroyed instead.

The script assumes a POSIX `/bin/sh` that counts `ulimit -f` in 512-byte
blocks (dash, and bash in POSIX mode), GNU tar's `-O` and `-t`, `awk` and
`timeout` (verify on the Sprite image).
"""

from __future__ import annotations

import re
import shlex

from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits

REFUSED_TAG = "__ATLAS_UNPACK_REFUSED__"
ULIMIT_BLOCK_BYTES = 512
# 128 + SIGXFSZ: the kernel stops a write past `ulimit -f` with this signal.
FILE_TOO_LARGE = 153
# Each tar run, and the grace before `timeout` kills one that ignored TERM.
EXTRACT_TIMEOUT_S = 60
KILL_AFTER_S = 2
_TIMEOUT = f"timeout -k {KILL_AFTER_S} {EXTRACT_TIMEOUT_S} "
# `timeout`'s status when it stopped the command, and when it had to kill it.
_STOPPED = "124|137"
_REFUSED = re.compile(
    rf"^{REFUSED_TAG}:(bytes|members|dirs|file|timeout|unreadable)$", re.MULTILINE
)
_REASONS = {
    "bytes": "its files hold over {max_bytes} bytes",
    "members": "it lists over {max_members} members",
    "dirs": (
        "its paths nest over {max_path_depth} deep or imply over "
        "{max_members} directories"
    ),
    "file": "a file grew past {max_bytes} bytes while it was written",
    "timeout": "tar did not finish within {timeout_s} seconds",
    "unreadable": "tar could not read or list the archive",
}
# Reads `tar -t` lines. A directory's own line ends in a slash; every parent
# of a line is counted once, walking up only until a parent already counted,
# so the work is the number of new directories, which the cap bounds.
_LISTING = (
    '{ if (NR > max) { r = "members"; exit } '
    r'p = $0; sub(/\/$/, "", p); '
    'if (split(p, parts, "/") > depth) { r = "dirs"; exit } '
    r'while (sub(/\/[^\/]*$/, "", p) && !(p in seen)) '
    '{ seen[p] = 1; if (++n > max) { r = "dirs"; exit } } } '
    'END { print (r == "" ? "ok" : r) }'
)


def file_size_blocks(max_bytes: int) -> int:
    return -(-max_bytes // ULIMIT_BLOCK_BYTES)


def unpack_script(
    archive: str,
    dest: str,
    tar_options: str = "",
    limits: UnpackLimits = DEFAULT_UNPACK,
) -> str:
    """A subshell that unpacks `archive` into `dest` within `limits` or
    exits non-zero, printing `REFUSED_TAG` when a limit, a timeout or an
    unreadable archive was the reason. Paths are quoted here, `tar_options`
    is controller-chosen and inserted as is."""
    status = shlex.quote(f"{archive}.status")
    a, d = shlex.quote(archive), shlex.quote(dest)
    listing = shlex.quote(_LISTING)
    return (
        "( set +e; "
        f'tar_ok() {{ case "$(cat {status})" in 0) ;; '
        f"{_STOPPED}) echo {REFUSED_TAG}:timeout; exit 4;; "
        f"*) echo {REFUSED_TAG}:unreadable; exit 2;; esac; }}; "
        f"n=$( {{ {_TIMEOUT}tar -xOzf {a}; echo $? > {status}; }} "
        f"| head -c {limits.max_bytes + 1} | wc -c ); "
        f'[ "$n" -le {limits.max_bytes} ] || {{ echo {REFUSED_TAG}:bytes; exit 3; }}; '
        "tar_ok; "
        f"l=$( {{ {_TIMEOUT}tar -tzf {a}; echo $? > {status}; }} "
        f"| awk -v max={limits.max_members} "
        f"-v depth={limits.max_path_depth} {listing} ); "
        f'case "$l" in members|dirs) echo {REFUSED_TAG}:$l; exit 3;; esac; '
        "tar_ok; "
        f'[ "$l" = ok ] || {{ echo {REFUSED_TAG}:unreadable; exit 2; }}; '
        f"rm -f {status}; mkdir -p {d}; "
        f"( ulimit -f {file_size_blocks(limits.max_bytes)} && "
        f"exec {_TIMEOUT}tar -xzf {a} -C {d} {tar_options} ); x=$?; "
        f'if [ "$x" != 0 ]; then rm -rf {d}; fi; '
        f'case "$x" in {FILE_TOO_LARGE}) echo {REFUSED_TAG}:file;; '
        f"{_STOPPED}) echo {REFUSED_TAG}:timeout;; esac; "
        'exit "$x" )'
    )


def unpack_refusal(text: str, limits: UnpackLimits = DEFAULT_UNPACK) -> str | None:
    """Why the runner refused to unpack, from its tag, or None. The tag is
    read only from an exec that already failed, so a forged one can at
    most reword a failure."""
    match = _REFUSED.search(text)
    if match is None:
        return None
    reason = _REASONS[match.group(1)].format(
        max_bytes=limits.max_bytes,
        max_members=limits.max_members,
        max_path_depth=limits.max_path_depth,
        timeout_s=EXTRACT_TIMEOUT_S,
    )
    return f"the runner refused to unpack the source archive: {reason}"
