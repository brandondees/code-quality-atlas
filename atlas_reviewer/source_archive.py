# SPDX-License-Identifier: MIT
"""Bound a source tarball's unpacked size before it reaches a runner (D39).

The upload cap bounds the compressed bytes only, and gzip packs a run of
one byte about 1,000 to 1: a 9 MiB archive can unpack to about 9 GiB.
`measure` walks the tar stream in memory, counting members and summing
their sizes, and refuses the archive at the first header over a cap,
before that member's data is decompressed. `GzipFile` decompresses every
gzip member, not only the first.

The walk fails closed. Python's tarfile and the runner's GNU tar disagree
on input either reads leniently: a header one rejects and the other
accepts, or a pax key one applies and the other ignores, lets the runner
see members and sizes measure did not count. So measure reads the blocks
itself and accepts only what `git archive` writes, in a form both readers
read the same way:

- ustar headers whose checksum matches and whose numeric fields are plain
  octal;
- regular files, directories, symlinks and hardlinks, only files carrying
  data;
- pax global headers holding only `comment`, and pax extended headers
  holding only `path`, `linkpath` and `mtime`, each key once, so no pax
  record changes a size; and GNU long names and links;
- metadata under a per-entry cap, checked before the entry is read, and
  under an archive-wide total;
- a zero block ending the archive, followed only by zero padding.

It skips exactly the data bytes it counts and keeps only counters, never
the members or the pax keys. Anything else, including an exception from
the reader, is a refusal. Nothing is written to disk.
"""

from __future__ import annotations

import gzip
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass

from atlas_reviewer.ports import BoundaryError

# Working defaults pending the owner (D39).
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 50_000
MAX_METADATA_BYTES = 1024 * 1024
# 50,000 members each carrying a pax path of about 300 bytes.
MAX_METADATA_TOTAL_BYTES = 16 * 1024 * 1024
# GNU tar and `git archive` pad the end to a 10 KiB record; zero padding up
# to this is accepted after the end block, and anything else is refused.
MAX_TRAILING_ZERO_BYTES = 1024 * 1024

_BLOCK = 512
_ZERO_BLOCK = b"\0" * _BLOCK
_READ_CHUNK = 64 * 1024
_MAGICS = frozenset((b"ustar\x0000", b"ustar  \0"))
_NUMERIC_FIELDS = (
    (100, 108),  # mode
    (108, 116),  # uid
    (116, 124),  # gid
    (124, 136),  # size
    (136, 148),  # mtime
)
# Python's tarfile leaves these empty on a non-device member, which both
# readers take as 0; `git archive` writes zeros.
_DEVICE_FIELDS = ((329, 337), (337, 345))
_SIZE_FIELD = (124, 136)
_CHECKSUM_FIELD = (148, 156)
_OCTAL = re.compile(rb" *([0-7]+)[ \0]*")
_OCTAL_OR_EMPTY = re.compile(rb" *[0-7]*[ \0]*")
_FILE_TYPES = frozenset((b"0", b"\0"))
_LINK_AND_DIR_TYPES = frozenset((b"1", b"2", b"5"))
# A pax global header may hold only what `git archive` writes there, so the
# global keys both readers carry to later members hold at most this one.
_GLOBAL_KEYS = frozenset((b"comment",))
# Per-member keys whose meaning both readers share; none of them is a size.
_MEMBER_KEYS = frozenset((b"path", b"linkpath", b"mtime"))
_PAX_KEYS = {b"g": _GLOBAL_KEYS, b"x": _MEMBER_KEYS}
_NAME_TYPES = frozenset((b"L", b"K"))
_PAX_LENGTH = re.compile(rb"([1-9][0-9]*) ")
_PAX_MTIME = re.compile(rb"[0-9]+(?:\.[0-9]+)?")


@dataclass(frozen=True)
class UnpackLimits:
    max_bytes: int = MAX_UNPACKED_BYTES
    max_members: int = MAX_MEMBERS
    max_metadata_bytes: int = MAX_METADATA_BYTES
    max_metadata_total_bytes: int = MAX_METADATA_TOTAL_BYTES

    def __post_init__(self) -> None:
        sizes = (
            self.max_bytes,
            self.max_members,
            self.max_metadata_bytes,
            self.max_metadata_total_bytes,
        )
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
    """Counters only: the walk never keeps a member, a name or a pax key."""

    limits: UnpackLimits
    members: int = 0
    total: int = 0
    metadata: int = 0
    pending: frozenset[bytes] = frozenset()


def measure(data: bytes, limits: UnpackLimits = DEFAULT_UNPACK) -> Unpacked:
    """Raises `BoundaryError` for an archive that is not a readable gzip
    tar as described above, has more than `max_members` members, or declares
    more than `max_bytes` in all."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            walk = _Walk(limits)
            for block in _headers(stream):
                _entry(block, stream, walk)
            _ended(walk)
            _only_zero_padding(stream)
            return Unpacked(walk.members, walk.total)
    except BoundaryError:
        raise
    except Exception as exc:  # noqa: BLE001 - any reader failure is a refusal
        raise _refusal(type(exc).__name__) from None


def _headers(stream: io.BufferedIOBase) -> Iterator[bytes]:
    """Each header block up to the first zero block, which ends the archive."""
    while (block := stream.read(_BLOCK)) != _ZERO_BLOCK:
        if len(block) != _BLOCK:
            raise _refusal("it ends without an end-of-archive block")
        if _checksum_failed(block):
            raise _refusal("header checksum failed")
        if block[257:265] not in _MAGICS:
            raise _refusal("a header is not a ustar header")
        yield block


def _entry(block: bytes, stream: io.BufferedIOBase, walk: _Walk) -> None:
    _check_numeric_fields(block)
    start, stop = _SIZE_FIELD
    size = _octal(block[start:stop])
    kind = block[156:157]
    if kind in _PAX_KEYS or kind in _NAME_TYPES:
        _metadata(kind, _read_metadata(size, stream, walk), walk)
    else:
        _member(kind, size, stream, walk)


def _check_numeric_fields(block: bytes) -> None:
    """Python's `int(field, 8)` accepts `1_000` and `0o1000`, which GNU tar
    rejects, reading the header's data as more headers. Only plain octal is
    accepted; base-256 numbers, which `git archive` never writes, are not."""
    fields = [(_OCTAL, field) for field in _NUMERIC_FIELDS]
    fields += [(_OCTAL_OR_EMPTY, field) for field in _DEVICE_FIELDS]
    if any(not form.fullmatch(block[start:stop]) for form, (start, stop) in fields):
        raise _refusal("a numeric header field does not parse as plain octal")


def _octal(field: bytes) -> int:
    match = _OCTAL.fullmatch(field)
    if match is None:
        raise ValueError("not plain octal")
    return int(match.group(1), 8)


def _checksum_failed(block: bytes) -> bool:
    """The stored checksum is not plain octal, or matches neither the
    unsigned nor the signed sum of the header with its checksum field read
    as spaces."""
    start, stop = _CHECKSUM_FIELD
    try:
        stored = _octal(block[start:stop])
    except ValueError:
        return True
    body = block[:start] + b" " * (stop - start) + block[stop:]
    unsigned = sum(body)
    signed = sum(b if b < 128 else b - 256 for b in body)
    return stored not in (unsigned, signed)


def _read_metadata(size: int, stream: io.BufferedIOBase, walk: _Walk) -> bytes:
    """The entry's payload, read only once both metadata caps allow it."""
    limits = walk.limits
    if size > limits.max_metadata_bytes:
        raise _refusal(
            f"a metadata entry declares {size} bytes, over the "
            f"{limits.max_metadata_bytes}-byte cap; not read"
        )
    walk.metadata += size
    if walk.metadata > limits.max_metadata_total_bytes:
        raise _refusal(
            f"metadata entries declare over {limits.max_metadata_total_bytes} "
            "bytes in all; not read"
        )
    payload = _read_exactly(stream, _padded(size))
    return payload[:size]


def _metadata(kind: bytes, payload: bytes, walk: _Walk) -> None:
    if kind in walk.pending:
        raise _refusal("a metadata entry repeats before its member")
    if kind in _PAX_KEYS:
        _check_pax(payload, _PAX_KEYS[kind])
    walk.pending |= {kind}


def _check_pax(payload: bytes, allowed: frozenset[bytes]) -> None:
    """Each record is `<length> <key>=<value>\\n`, its key allowed and not
    repeated, so an entry holds at most as many records as keys it may."""
    seen: set[bytes] = set()
    for key, value in _pax_records(payload):
        if key not in allowed:
            raise _refusal(f"pax key {key.decode(errors='replace')!r} is not accepted")
        if key in seen:
            raise _refusal("a pax key repeats")
        if key == b"mtime" and not _PAX_MTIME.fullmatch(value):
            raise _refusal("a pax mtime does not parse")
        seen.add(key)


def _pax_records(payload: bytes) -> Iterator[tuple[bytes, bytes]]:
    pos = 0
    while pos < len(payload):
        key, value, pos = _pax_record(payload, pos)
        yield key, value


def _pax_record(payload: bytes, pos: int) -> tuple[bytes, bytes, int]:
    """The record at `pos`, whose length counts the whole record, and the
    position after it. Every byte of the payload must belong to a record."""
    length = _PAX_LENGTH.match(payload, pos)
    if length is None:
        raise _refusal("a pax record does not parse")
    end = pos + int(length.group(1))
    key, equals, value = payload[length.end() : end].partition(b"=")
    if end > len(payload) or not (key and equals and value.endswith(b"\n")):
        raise _refusal("a pax record does not parse")
    return key, value[:-1], end


def _member(kind: bytes, size: int, stream: io.BufferedIOBase, walk: _Walk) -> None:
    if kind not in _FILE_TYPES and kind not in _LINK_AND_DIR_TYPES:
        raise _refusal(f"member type {kind!r} is not accepted")
    if size and kind not in _FILE_TYPES:
        raise _refusal("a non-file member declares data")
    walk.members += 1
    walk.total += size
    walk.pending = frozenset()
    _within(walk.members, walk.total, walk.limits)
    _skip(stream, _padded(size))


def _ended(walk: _Walk) -> None:
    if walk.pending:
        raise _refusal("a metadata entry has no member after it")
    if walk.members == 0:
        raise _refusal("it holds no members")


def _padded(size: int) -> int:
    return size + -size % _BLOCK


def _read_exactly(stream: io.BufferedIOBase, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise _refusal("it ends inside an entry's data")
    return data


def _skip(stream: io.BufferedIOBase, size: int) -> None:
    while size:
        size -= len(_read_exactly(stream, min(size, _READ_CHUNK)))


def _only_zero_padding(stream: io.BufferedIOBase) -> None:
    """After the end block, GNU tar stops reading. Anything there other than
    zero padding is content measure did not count, so it is refused."""
    seen = 0
    while chunk := stream.read(_READ_CHUNK):
        seen += len(chunk)
        if chunk.strip(b"\0") or seen > MAX_TRAILING_ZERO_BYTES:
            raise _refusal("data follows the end-of-archive block")


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
