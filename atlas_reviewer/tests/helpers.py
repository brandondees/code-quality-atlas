# SPDX-License-Identifier: MIT
import io
import json
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from atlas_reviewer.domain import (
    Conclusion,
    EvidenceItem,
    Provenance,
    SourceKey,
    SourceKind,
    ToolInfo,
)
from atlas_reviewer.fakes import FakeSprites
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.lenses import LensLibrary
from atlas_reviewer.redact import redact

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample-pr"
HEAD = "3f6c1e9b2a7d4c8e0f1a2b3c4d5e6f708192a3b4"
OLD = "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a291807"
NOW = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)


def source_tarball(files: dict[str, bytes] | None = None, top: str = "src") -> bytes:
    """A real gzip tar with one top-level directory, as GitHub serves: every
    directory is an entry, listed before what is in it."""
    buf = io.BytesIO()
    made: set[str] = set()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, data in (files or {"app.py": b"print('ok')\n"}).items():
            full = f"{top}/{path}"
            for parent in reversed(list(PurePosixPath(full).parents)[:-1]):
                if str(parent) not in made:
                    made.add(str(parent))
                    info = tarfile.TarInfo(str(parent))
                    info.type, info.mode = tarfile.DIRTYPE, 0o755
                    tf.addfile(info)
            info = tarfile.TarInfo(full)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


SOURCE_TARBALL = source_tarball()


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> datetime:
        return NOW + timedelta(seconds=self.t)

    def monotonic(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def item(
    name: str = "gate",
    sha: str = HEAD,
    kind: SourceKind = SourceKind.CHECK_RUN,
    conclusion: Conclusion = Conclusion.SUCCESS,
) -> EvidenceItem:
    return EvidenceItem(
        head_sha=sha,
        provenance=Provenance(SourceKey(kind, name), f"{kind.value}:{name}"),
        tool=ToolInfo("github-actions", "unreported"),
        fetched_at=NOW,
        conclusion=conclusion,
        detail=redact(""),
    )


@dataclass
class CallbackRule:
    """An exec rule whose answer runs arbitrary test code (e.g. advancing a clock)."""

    match: str
    callback: object
    stdout: str = ""
    exit_code: int = 0

    def handler(self, script, stdin):
        self.callback()
        return self.stdout, self.exit_code


def fake_token(prefix: str, length: int = 36) -> str:
    """Token-shaped strings are built at runtime so no literal one is committed."""
    return prefix + ("Ab1" * length)[:length]


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, headers, body, timeout_s, max_bytes=None):
        self.requests.append((method, url, dict(headers), body, timeout_s, max_bytes))
        return self.responses.pop(0)

    def stream(self, method, url, headers, body, window, max_bytes=None):
        self.requests.append((method, url, dict(headers), body, window, max_bytes))
        return self.responses.pop(0)


def ok(payload=None, status=200, body=None, headers=None):
    raw = (
        body
        if body is not None
        else json.dumps(payload if payload is not None else {}).encode()
    )
    return HttpResponse(status, headers or {}, raw)


class StubLibrary(LensLibrary):
    """A lens bundle held in memory: lens name to body."""

    def __init__(self, bodies: dict[str, str]) -> None:
        self._bodies = bodies

    def names(self) -> frozenset[str]:
        return frozenset(self._bodies)

    def body(self, name: str) -> str | None:
        return self._bodies.get(name)


def small_bundle(*extra: str, chars: int = 100) -> StubLibrary:
    """Every critical-tier lens and each of `extra`, `chars` characters each,
    so the picker always has room to add a lens."""
    from atlas_reviewer.picker import CRITICAL_TIER

    return StubLibrary({n: n[0] * chars for n in (*CRITICAL_TIER, *extra)})


class LocalSprites(FakeSprites):
    """Runs the exec wrapper's argv here and answers with its stdout as
    one stdout frame, the shape the live exec stream has."""

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        self._record("exec", name, argv[-1])
        self._get(name)
        self.argv_seen.append(tuple(argv))
        self.timeouts_seen.append(timeout_s)
        done = subprocess.run(
            list(argv), input=stdin, capture_output=True, timeout=60, check=False
        )
        return b"\x01" + done.stdout
