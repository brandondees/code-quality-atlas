# SPDX-License-Identifier: MIT
"""The runner-side bound on unpacking a source tarball (D39).

Defence in depth behind `source_archive.measure`: the controller's parser
cannot be proven to read every archive the way the runner's GNU tar does,
so the runner holds the same caps by GNU tar's own reading before it
writes anything. `tar -xOzf` streams every member's data as extraction
would write it (sparse files expanded) through `head -c`, and `tar -tzf`
lists every member through `head -n`; past `max_bytes` or `max_members`
the archive is refused and nothing is extracted. Extraction then runs
under `ulimit -f`, so no one file can grow past `max_bytes` whatever the
headers claim. Any failure removes the partial tree and exits non-zero,
so no later step sees it.

The script assumes a POSIX `/bin/sh` that counts `ulimit -f` in 512-byte
blocks (dash, and bash in POSIX mode), and GNU tar's `-O` and `-t`
(verify on the Sprite image).
"""

from __future__ import annotations

import re
import shlex

from atlas_reviewer.source_archive import DEFAULT_UNPACK, UnpackLimits

REFUSED_TAG = "__ATLAS_UNPACK_REFUSED__"
ULIMIT_BLOCK_BYTES = 512
# 128 + SIGXFSZ: the kernel stops a write past `ulimit -f` with this signal.
FILE_TOO_LARGE = 153
_REFUSED = re.compile(rf"^{REFUSED_TAG}:(bytes|members|file)$", re.MULTILINE)
_REASONS = {
    "bytes": "its files hold over {max_bytes} bytes",
    "members": "it lists over {max_members} members",
    "file": "a file grew past {max_bytes} bytes while it was written",
}


def file_size_blocks(max_bytes: int) -> int:
    return -(-max_bytes // ULIMIT_BLOCK_BYTES)


def unpack_script(
    archive: str,
    dest: str,
    tar_options: str = "",
    limits: UnpackLimits = DEFAULT_UNPACK,
    timeout: str = "",
) -> str:
    """A subshell that unpacks `archive` into `dest` within `limits` or
    exits non-zero, printing `REFUSED_TAG` when a limit was the reason.
    `timeout` prefixes each tar run; paths are quoted here, `tar_options`
    is controller-chosen and inserted as is."""
    status = shlex.quote(f"{archive}.status")
    a, d = shlex.quote(archive), shlex.quote(dest)
    return (
        "( set +e; "
        f"n=$( {{ {timeout}tar -xOzf {a}; echo $? > {status}; }} "
        f"| head -c {limits.max_bytes + 1} | wc -c ); "
        f'[ "$n" -le {limits.max_bytes} ] || {{ echo {REFUSED_TAG}:bytes; exit 3; }}; '
        f'[ "$(cat {status})" = 0 ] || exit 2; '
        f"m=$( {{ {timeout}tar -tzf {a}; echo $? > {status}; }} "
        f"| head -n {limits.max_members + 1} | wc -l ); "
        f'[ "$m" -le {limits.max_members} ] || {{ echo {REFUSED_TAG}:members; exit 3; }}; '
        f'[ "$(cat {status})" = 0 ] || exit 2; '
        f"rm -f {status}; mkdir -p {d}; "
        f"( ulimit -f {file_size_blocks(limits.max_bytes)} && "
        f"exec {timeout}tar -xzf {a} -C {d} {tar_options} ); x=$?; "
        f'if [ "$x" != 0 ]; then rm -rf {d}; fi; '
        f'if [ "$x" = {FILE_TOO_LARGE} ]; then echo {REFUSED_TAG}:file; fi; '
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
        max_bytes=limits.max_bytes, max_members=limits.max_members
    )
    return (
        f"the runner refused to unpack the source archive: {reason}; "
        "nothing it unpacked is kept"
    )
