# SPDX-License-Identifier: MIT
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atlas_reviewer.domain import (
    Conclusion,
    EvidenceItem,
    Provenance,
    SourceKey,
    SourceKind,
    ToolInfo,
)
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.redact import redact

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample-pr"
HEAD = "3f6c1e9b2a7d4c8e0f1a2b3c4d5e6f708192a3b4"
OLD = "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a291807"
NOW = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)


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
