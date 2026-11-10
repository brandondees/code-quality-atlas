# SPDX-License-Identifier: MIT
"""Bound a source tarball's unpacked size before it reaches a runner (D39).

The upload cap bounds the compressed bytes only, and gzip packs a run of
one byte about 1,000 to 1: a 9 MiB archive can unpack to about 9 GiB.
`measure` walks the tar headers in memory, counting members and summing
their declared sizes, and refuses the archive at the first header over a
cap. The stream reads one 10 KiB record at a time, so up to that much of a
member is decompressed with its header; the rest is not, once a cap is
exceeded. `GzipFile` decompresses every gzip member, which tarfile's own
`r|gz` does not.

The walk fails closed. Python's tarfile and the runner's GNU tar disagree
on damaged input: tarfile ends the archive at a header it cannot parse
while GNU tar skips it and keeps extracting, so anything measure does not
fully understand is refused rather than read the lenient way. It accepts
only the member types `git archive` writes (regular files, directories,
symlinks, hardlinks) plus pax and GNU long-name metadata, each metadata
entry under a size cap and checked before it is read; headers whose
fields all parse, with non-negative sizes and no sparse-file pax keys;
and an archive that ends at a zero block followed only by zero padding.
Any other outcome, including an exception from the reader, is a refusal.
Nothing is written to disk.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from dataclasses import dataclass
from typing import IO, Self, cast

from atlas_reviewer.ports import BoundaryError

# Working defaults pending the owner (D39).
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 50_000
MAX_METADATA_BYTES = 1024 * 1024
# GNU tar and `git archive` pad the end to a 10 KiB record; zero padding up
# to this is accepted after the end block, and anything else is refused.
MAX_TRAILING_ZERO_BYTES = 1024 * 1024
# A pax global header, then a pax or GNU long-name header, then the member:
# deeper nesting is not something `git archive` writes.
MAX_METADATA_DEPTH = 3

_BLOCK = 512
_ZERO_BLOCK = b"\0" * _BLOCK
_MEMBER_TYPES = frozenset(
    (
        tarfile.REGTYPE,
        tarfile.AREGTYPE,
        tarfile.DIRTYPE,
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
    )
)
_METADATA_TYPES = frozenset(
    (
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    )
)
_PAX_SIZE = re.compile(r"[0-9]+")
_READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class UnpackLimits:
    max_bytes: int = MAX_UNPACKED_BYTES
    max_members: int = MAX_MEMBERS
    max_metadata_bytes: int = MAX_METADATA_BYTES

    def __post_init__(self) -> None:
        sizes = (self.max_bytes, self.max_members, self.max_metadata_bytes)
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in sizes):
            raise ValueError("unpack limits must be positive integers")


DEFAULT_UNPACK = UnpackLimits()


@dataclass(frozen=True)
class Unpacked:
    members: int
    total_bytes: int


def _refusal(reason: str) -> BoundaryError:
    return BoundaryError(f"source archive is not a readable gzip tar: {reason}")


@dataclass
class _Walk:
    limits: UnpackLimits
    depth: int = 0


def measure(data: bytes, limits: UnpackLimits = DEFAULT_UNPACK) -> Unpacked:
    """Raises `BoundaryError` for an archive that is not a readable gzip
    tar as described above, has more than `max_members` members, or declares
    more than `max_bytes` in all."""
    try:
        with (
            gzip.GzipFile(fileobj=io.BytesIO(data)) as stream,
            tarfile.open(
                fileobj=stream, mode="r|", tarinfo=_reader(_Walk(limits))
            ) as tar,
        ):
            counted = _counted(tar, limits)
            _only_zero_padding(tar)
            return counted
    except BoundaryError:
        raise
    except Exception as exc:  # noqa: BLE001 - any reader failure is a refusal
        raise _refusal(type(exc).__name__) from None


def _counted(tar: tarfile.TarFile, limits: UnpackLimits) -> Unpacked:
    members = total = 0
    for member in tar:
        members, total = members + 1, total + member.size
        _within(members, total, limits)
    if members == 0:
        raise _refusal("it holds no members")
    return Unpacked(members, total)


def _only_zero_padding(tar: tarfile.TarFile) -> None:
    """After the end block, GNU tar stops reading. Anything there other than
    zero padding is content measure did not count, so it is refused."""
    fileobj = _stream(tar)
    seen = 0
    while chunk := fileobj.read(_READ_CHUNK):
        seen += len(chunk)
        if chunk.strip(b"\0") or seen > MAX_TRAILING_ZERO_BYTES:
            raise _refusal("data follows the end-of-archive block")


def _reader(walk: _Walk) -> type[tarfile.TarInfo]:
    """A `TarInfo` whose header reads go through `_header`. tarfile calls
    `fromtarfile` for each member and `_fromtarfile` for the header after a
    pax or long-name entry, so both are routed."""

    class _Checked(tarfile.TarInfo):
        @classmethod
        def fromtarfile(cls, tar: tarfile.TarFile) -> Self:
            return cast(Self, _header(cls, tar, walk))

        @classmethod
        def _fromtarfile(cls, tar: tarfile.TarFile, **_: object) -> Self:
            return cast(Self, _header(cls, tar, walk))

    return _Checked


def _header(
    cls: type[tarfile.TarInfo], tar: tarfile.TarFile, walk: _Walk
) -> tarfile.TarInfo:
    """One header and, for metadata, the member it describes. Only a zero
    block reaches tarfile as an end of archive; every other problem is a
    refusal, which tarfile cannot mistake for the end."""
    fileobj = _stream(tar)
    buf = fileobj.read(_BLOCK)
    if buf == _ZERO_BLOCK:
        raise tarfile.EOFHeaderError("end of archive")  # type: ignore[attr-defined]
    if len(buf) != _BLOCK:
        raise _refusal("it ends without an end-of-archive block")
    if _checksum_failed(buf):
        raise _refusal("header checksum failed")
    info = _parsed(cls, buf, tar)
    _check_header(info, walk.limits)
    info.offset = fileobj.tell() - _BLOCK
    member = _processed(info, tar, walk)
    _check_member(member)
    return member


def _stream(tar: tarfile.TarFile) -> IO[bytes]:
    if tar.fileobj is None:
        raise tarfile.StreamError("source stream is closed")
    return cast(IO[bytes], tar.fileobj)


def _checksum_failed(buf: bytes) -> bool:
    """The stored checksum matches neither the unsigned nor the signed sum
    of the header with its checksum field read as spaces."""
    try:
        stored = int(buf[148:156].strip(b"\0 ") or b"0", 8)
    except ValueError:
        return True
    body = buf[:148] + b" " * 8 + buf[156:]
    unsigned = sum(body)
    signed = sum(b if b < 128 else b - 256 for b in body)
    return stored not in (unsigned, signed)


def _parsed(
    cls: type[tarfile.TarInfo], buf: bytes, tar: tarfile.TarFile
) -> tarfile.TarInfo:
    try:
        return cls.frombuf(buf, tar.encoding, tar.errors)
    except tarfile.HeaderError:
        raise _refusal("a header field does not parse") from None


def _check_header(info: tarfile.TarInfo, limits: UnpackLimits) -> None:
    if info.size < 0:
        raise _refusal("a header declares a negative size")
    if info.type in _METADATA_TYPES:
        if info.size > limits.max_metadata_bytes:
            raise _refusal(
                f"a metadata entry declares {info.size} bytes, over the "
                f"{limits.max_metadata_bytes}-byte cap; not read"
            )
    elif info.type not in _MEMBER_TYPES:
        raise _refusal(f"member type {info.type!r} is not accepted")


def _processed(
    info: tarfile.TarInfo, tar: tarfile.TarFile, walk: _Walk
) -> tarfile.TarInfo:
    """tarfile's own processing: data offset for a member, payload and the
    following header for metadata. Nesting is bounded so a chain of
    metadata entries cannot pile up in memory."""
    nested = info.type in _METADATA_TYPES
    walk.depth += nested
    try:
        if walk.depth > MAX_METADATA_DEPTH:
            raise _refusal("metadata entries are nested too deep")
        return info._proc_member(tar)  # type: ignore[attr-defined]
    except tarfile.HeaderError:
        raise _refusal(
            "a metadata entry does not parse or has no member after it"
        ) from None
    finally:
        walk.depth -= nested


def _check_member(member: tarfile.TarInfo) -> None:
    """The member as GNU tar will see it, pax fields applied."""
    pax = member.pax_headers
    if any(key.startswith("GNU.sparse") for key in pax):
        raise _refusal("sparse files are not accepted")
    if "size" in pax and not _PAX_SIZE.fullmatch(pax["size"]):
        raise _refusal("a pax size field does not parse")
    if member.size and not member.isreg():
        raise _refusal("a non-file member declares data")


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
