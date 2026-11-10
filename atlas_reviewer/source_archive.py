# SPDX-License-Identifier: MIT
"""Bound a source tarball's unpacked size before it reaches a runner (D39).

The upload cap bounds the compressed bytes only, and gzip packs a run of
one byte about 1,000 to 1: a 9 MiB archive can unpack to about 9 GiB.
`measure` walks the tar headers in memory, counting members and summing
their declared sizes, and refuses the archive at the first header over a
cap. The stream reads one 10 KiB record to parse a header, so that much of
the following member is decompressed with it; the rest is not, once the cap
is exceeded. `GzipFile` decompresses every gzip member, which tarfile's own
`r|gz` does not: it stops at the first member's end, so a second member
could hide the big file. A header whose checksum fails is refused rather
than taken as the end of the archive: GNU tar skips that header and keeps
extracting, so the members after it would otherwise go uncounted.
`ignore_zeros` is not used. It would skip the bad header, but it also reads
gzip that is not a tar as an empty archive and accepts it. Nothing is
written to disk. Other differences between Python's `tarfile` and the
runner's GNU tar remain (verify).
"""

from __future__ import annotations

import gzip
import io
import tarfile
import zlib
from dataclasses import dataclass
from typing import Self

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


_BLOCK = 512


class _ChecksumChecked(tarfile.TarInfo):
    """`TarFile.next` treats a bad checksum as the end of the archive and
    returns None. GNU tar skips that block and keeps extracting, so the
    header is refused here, before `next` can swallow the error."""

    @classmethod
    def fromtarfile(cls, tar: tarfile.TarFile) -> Self:
        fileobj = tar.fileobj
        if fileobj is None:
            raise tarfile.StreamError("source stream is closed")
        buf = fileobj.read(_BLOCK)
        if _checksum_failed(buf):
            raise BoundaryError(
                "source archive is not a readable gzip tar: header checksum failed; "
                "not unpacked"
            )
        info = cls.frombuf(buf, tar.encoding, tar.errors)
        info.offset = fileobj.tell() - _BLOCK
        return info._proc_member(tar)  # type: ignore[attr-defined]


def _checksum_failed(buf: bytes) -> bool:
    """A full, non-zero block whose stored checksum matches neither the
    unsigned nor the signed header sum. A short read or a zero end block is
    left to tarfile, which already ends the archive on those."""
    if len(buf) != _BLOCK or buf == b"\0" * _BLOCK:
        return False
    try:
        stored = int(buf[148:156].strip(b"\0 ") or b"0", 8)
    except ValueError:
        return True
    body = buf[:148] + b" " * 8 + buf[156:]
    unsigned = sum(body)
    signed = sum(b if b < 128 else b - 256 for b in body)
    return stored not in (unsigned, signed)


def measure(data: bytes, limits: UnpackLimits = DEFAULT_UNPACK) -> Unpacked:
    """Raises `BoundaryError` for an archive that is not a readable gzip
    tar, has more than `max_members` members, or declares more than
    `max_bytes` in all. A header whose checksum fails is not a readable
    archive: the runner's tar would skip it and keep extracting."""
    try:
        with (
            gzip.GzipFile(fileobj=io.BytesIO(data)) as stream,
            tarfile.open(fileobj=stream, mode="r|", tarinfo=_ChecksumChecked) as tar,
        ):
            return _counted(tar, limits)
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise BoundaryError(
            f"source archive is not a readable gzip tar: {type(exc).__name__}"
        ) from None


def _counted(tar: tarfile.TarFile, limits: UnpackLimits) -> Unpacked:
    members = total = 0
    for member in tar:
        members, total = members + 1, total + member.size
        _within(members, total, limits)
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
