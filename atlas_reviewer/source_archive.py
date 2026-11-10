# SPDX-License-Identifier: MIT
"""Bound a source tarball's unpacked size before it reaches a runner (D39).

The upload cap bounds the compressed bytes only, and gzip packs a run of
one byte about 1,000 to 1: a 9 MiB archive can unpack to about 9 GiB.
`measure` walks the tar headers in memory, counting members and summing
their declared sizes, and refuses the archive at the first header over a
cap, so the controller never decompresses more than the cap to find out.
`GzipFile` decompresses every gzip member, which tarfile's own `r|gz` does
not: it stops at the first member's end, so a second member could hide the
big file. tarfile still reads the decompressed stream without seeking, so a
header is seen, and refused, before its data is read.
Nothing is written to disk. The runner's `tar` reads the same headers
(Python's `tarfile` and GNU tar agreeing on them is (verify)).
"""

from __future__ import annotations

import gzip
import io
import tarfile
import zlib
from dataclasses import dataclass

from atlas_reviewer.ports import BoundaryError

# Working defaults pending the owner (D39).
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 50_000


@dataclass(frozen=True)
class UnpackLimits:
    max_bytes: int = MAX_UNPACKED_BYTES
    max_members: int = MAX_MEMBERS

    def __post_init__(self) -> None:
        sizes = (self.max_bytes, self.max_members)
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("unpack limits must be positive integers")


DEFAULT_UNPACK = UnpackLimits()


@dataclass(frozen=True)
class Unpacked:
    members: int
    total_bytes: int


def measure(data: bytes, limits: UnpackLimits = DEFAULT_UNPACK) -> Unpacked:
    """Raises `BoundaryError` for an archive that is not a readable gzip
    tar, has more than `max_members` members, or declares more than
    `max_bytes` in all."""
    members = total = 0
    try:
        with (
            gzip.GzipFile(fileobj=io.BytesIO(data)) as stream,
            tarfile.open(fileobj=stream, mode="r|") as tar,
        ):
            for member in tar:
                members, total = members + 1, total + member.size
                _within(members, total, limits)
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise BoundaryError(
            f"source archive is not a readable gzip tar: {type(exc).__name__}"
        ) from None
    return Unpacked(members, total)


def _within(members: int, total: int, limits: UnpackLimits) -> None:
    if members > limits.max_members:
        raise BoundaryError(
            f"source archive has over {limits.max_members} members; not unpacked"
        )
    if total > limits.max_bytes:
        raise BoundaryError(
            f"source archive unpacks to over {limits.max_bytes} bytes "
            f"(at least {total}); not unpacked"
        )
