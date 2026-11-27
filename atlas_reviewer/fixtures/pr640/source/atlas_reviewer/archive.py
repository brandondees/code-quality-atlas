# SPDX-License-Identifier: MIT
"""Read an untrusted ZIP (a GitHub Actions artifact) in memory, within
hard limits. Pure: bytes in, text out; nothing is written to disk and
nothing is executed.

Whole-archive rejections: over the compressed-size cap, not a ZIP, more
entries than the entry cap. Per-entry rejections (the rest of the archive
is still read): absolute, drive-letter or `..` paths; symlinks and any
other non-regular file; encrypted entries; file types outside the text
allowlist; binary content; a declared or actual compression ratio over
the cap; an entry over the per-entry size cap. Once the total uncompressed
budget is spent, every remaining entry is skipped.

The entry cap is checked on the raw central directory before `zipfile`
parses it (which builds one `ZipInfo` per entry): the end record, and a
ZIP64 record wherever its locator is present, are found where CPython
3.12's `zipfile` looks for them, and the same directory bytes are walked
header by header without building anything. A count the end record
under-states is caught by that walk. An archive whose records cannot be
located is left to `zipfile`, which rejects it, and the cap is checked
again on what `zipfile` builds, in case another version locates them
differently.

Declared sizes are checked before decompressing anything. They also bound
what is decompressed: CPython's `zipfile` never yields more than an entry's
declared size and verifies its CRC-32 at the end, so an entry whose header
under-declares its size fails as unreadable. Each read is capped at the
limit and at the declared size regardless, in case that library behaviour
ever changes, and an entry that produces fewer bytes than it declared (a
STORED entry over-declaring its size, with the CRC of what it holds,
raises nothing) is skipped. The total budget is charged what each entry
actually produced, or its declared size when the read failed part-way.
"""

from __future__ import annotations

import io
import re
import stat
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath

TEXT_SUFFIXES = frozenset(
    {
        ".txt",
        ".log",
        ".json",
        ".xml",
        ".sarif",
        ".md",
        ".csv",
        ".tsv",
        ".lcov",
        ".out",
        ".yml",
        ".yaml",
    }
)
_DRIVE = re.compile(r"^[A-Za-z]:")
_ENCRYPTED_FLAG = 0x1
_END = b"PK\x05\x06"
_END_SIZE = 22
_END64_LOCATOR = b"PK\x06\x07"
_END64 = b"PK\x06\x06"
_END64_SIZE = 56
_CENTRAL = b"PK\x01\x02"
_CENTRAL_SIZE = 46
_MAX_COMMENT = 0xFFFF
_READ_ERRORS = (
    zipfile.BadZipFile,
    NotImplementedError,
    RuntimeError,
    zlib.error,
    EOFError,
    OSError,
    ValueError,
)


@dataclass(frozen=True)
class ArchiveLimits:
    max_compressed_bytes: int = 10 * 1024 * 1024
    max_total_uncompressed_bytes: int = 20 * 1024 * 1024
    max_entry_bytes: int = 5 * 1024 * 1024
    max_entries: int = 200
    max_ratio: float = 100.0


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    text: str


@dataclass(frozen=True)
class ArchiveRead:
    """`rejected` is set when nothing was read; `skipped` lists entries
    left out of an otherwise-read archive, each with its reason."""

    members: tuple[ArchiveMember, ...] = ()
    skipped: tuple[str, ...] = ()
    rejected: str | None = None


class _Budget:
    def __init__(self, total: int) -> None:
        self.left = total


DEFAULT_LIMITS = ArchiveLimits()


def read_zip(data: bytes, limits: ArchiveLimits = DEFAULT_LIMITS) -> ArchiveRead:
    if len(data) > limits.max_compressed_bytes:
        return ArchiveRead(
            rejected=f"archive is {len(data)} bytes, over the "
            f"{limits.max_compressed_bytes}-byte compressed cap"
        )
    over = _over_entry_cap(data, limits.max_entries)
    if over:
        return ArchiveRead(rejected=f"{over}, over the {limits.max_entries}-entry cap")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return _read_entries(zf, limits)
    except _READ_ERRORS as exc:
        return ArchiveRead(rejected=f"not a readable ZIP ({type(exc).__name__})")


def _over_entry_cap(data: bytes, cap: int) -> str | None:
    """Why the central directory holds more than `cap` entries, or None."""
    found = _central_directory(data)
    if found is None:
        return None
    claimed, start, size = found
    if claimed is not None and claimed > cap:
        return f"{claimed} entries"
    count, pos, stop = 0, start, min(start + size, len(data))
    while pos + _CENTRAL_SIZE <= stop and data.startswith(_CENTRAL, pos):
        count += 1
        if count > cap:
            return f"more than {cap} entries in the central directory"
        name, extra, comment = struct.unpack_from("<HHH", data, pos + 28)
        pos += _CENTRAL_SIZE + name + extra + comment
    return None


def _central_directory(data: bytes) -> tuple[int | None, int, int] | None:
    """(claimed entries, start, size) of the central directory that
    CPython's `zipfile` will parse, located as its `_EndRecData` and
    `_EndRecData64` locate it, or None where `zipfile` finds none and fails.
    The claimed count is None when it is only the ZIP64 marker."""
    end = len(data) - _END_SIZE
    if not (end >= 0 and data.startswith(_END, end) and data.endswith(b"\0\0")):
        end = data.rfind(_END, max(0, len(data) - _END_SIZE - _MAX_COMMENT - 1))
        if end < 0 or end + _END_SIZE > len(data):
            return None
    claimed: int | None
    claimed, size = struct.unpack_from("<HI", data, end + 10)
    location = end
    locator = end - 20
    if locator >= 0 and data.startswith(_END64_LOCATOR, locator):
        (reloff,) = struct.unpack_from("<Q", data, locator + 8)
        fixed = locator - _END64_SIZE
        if reloff > fixed:
            return None
        at = reloff if data.startswith(_END64, reloff) or reloff == fixed else fixed
        if not data.startswith(_END64, at):
            return None
        claimed, size = struct.unpack_from("<QQ", data, at + 32)
        location = at
    elif claimed == 0xFFFF:
        claimed = None
    start = location - size
    return None if start < 0 else (claimed, start, size)


def _read_entries(zf: zipfile.ZipFile, limits: ArchiveLimits) -> ArchiveRead:
    infos = zf.infolist()
    if len(infos) > limits.max_entries:
        return ArchiveRead(
            rejected=f"{len(infos)} entries, over the {limits.max_entries}-entry cap"
        )
    budget = _Budget(limits.max_total_uncompressed_bytes)
    members: list[ArchiveMember] = []
    skipped: list[str] = []
    for info in (i for i in infos if not i.is_dir()):
        result = _entry(zf, info, limits, budget)
        if isinstance(result, ArchiveMember):
            members.append(result)
        else:
            skipped.append(f"{_printable(info.filename)}: {result}")
    return ArchiveRead(tuple(members), tuple(skipped))


def _entry(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, limits: ArchiveLimits, budget: _Budget
) -> ArchiveMember | str:
    """The declared size is charged before decompressing, so an entry that
    fails mid-read (a bad CRC is only detected at its end) still spends the
    budget its decompression cost."""
    refusal = _refuse_header(info, limits) or _refuse_budget(info, budget)
    if refusal:
        return refusal
    cap = min(limits.max_entry_bytes, budget.left, info.file_size)
    budget.left -= info.file_size
    try:
        data = _bounded_read(zf, info, cap)
    except _READ_ERRORS as exc:
        return f"unreadable entry ({type(exc).__name__})"
    if data is None:  # pragma: no cover -- zipfile stops at the declared size
        return "decompresses past its declared size or the size caps"
    budget.left += info.file_size - len(data)
    if len(data) != info.file_size:
        return f"decompressed to {len(data)} bytes, not the declared {info.file_size}"
    if b"\x00" in data:
        return "binary content"
    return ArchiveMember(info.filename, data.decode("utf-8", errors="replace"))


# zipfile bounds DEFLATE output by max_length; BZIP2 and LZMA can expand a
# whole chunk before trimming to the declared size.
_BOUNDED_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


def _refuse_header(info: zipfile.ZipInfo, limits: ArchiveLimits) -> str | None:
    checks = (
        (_unsafe_path(info.filename), "unsafe path (absolute, drive or `..`)"),
        (not _regular_file(info), "not a regular file (symlink or special file)"),
        (bool(info.flag_bits & _ENCRYPTED_FLAG), "encrypted entry"),
        (
            info.compress_type not in _BOUNDED_METHODS,
            "compression method not STORED or DEFLATED",
        ),
        (
            PurePosixPath(info.filename).suffix.lower() not in TEXT_SUFFIXES,
            "file type not on the text allowlist",
        ),
        (
            info.file_size > limits.max_entry_bytes,
            "declared size over the per-entry cap",
        ),
        (
            info.file_size / max(info.compress_size, 1) > limits.max_ratio,
            f"declared compression ratio over {limits.max_ratio:g}:1",
        ),
    )
    return next((reason for failed, reason in checks if failed), None)


def _refuse_budget(info: zipfile.ZipInfo, budget: _Budget) -> str | None:
    if budget.left <= 0 or info.file_size > budget.left:
        return "total uncompressed budget spent"
    return None


def _unsafe_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    return (
        not name
        or "\x00" in name
        or normalized.startswith("/")
        or bool(_DRIVE.match(normalized))
        or ".." in parts
    )


def _regular_file(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_IFMT(mode) in (0, stat.S_IFREG)


def _bounded_read(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes | None:
    with zf.open(info) as fh:
        data = fh.read(cap + 1)
    return None if len(data) > cap else data


def _printable(name: str) -> str:
    return "".join(c if c.isprintable() else "?" for c in name)[:200]
