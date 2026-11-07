# SPDX-License-Identifier: MIT
"""In-memory stand-ins for the Sprites API, the runner ledger, and a
GitHub token source.

Used by the test suite and by `--dry-run`; none ever touches a real API.
`FakeSprites` records every control-plane call in order so a caller can
assert on lifecycle (policy before exec, destroy always), and answers the
runner's tool-availability probe from its `installed` set and its
interpreter resolution from `pythons`.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from atlas_reviewer.interpreter import PYENV_VERSIONS, PYTHON_TAG
from atlas_reviewer.ports import BoundaryError, Json, NotFoundError
from atlas_reviewer.runner import EXIT_MARKER, EXIT_NOT_FOUND, PROBE_TAG, START_MARKER

_HANG_LIMIT_S = 10.0
_FEED_RE = re.compile(r"head -c (\d+) \| ")
PYENV_PYTHON = f"{PYENV_VERSIONS}/3.13.7/bin/python3"


@dataclass(frozen=True)
class ExecRule:
    """Answer any exec whose script contains `match`."""

    match: str
    stdout: str
    exit_code: int

    def handler(self, _script: str, _stdin: bytes) -> tuple[str, int]:
        return self.stdout, self.exit_code


@dataclass
class _Sprite:
    network_rules: list[Json] = field(default_factory=list)
    memory_mb: int | None = None
    destroyed: threading.Event = field(default_factory=threading.Event)


@dataclass
class FakeSprites:
    """`installed=None` reports every probed binary present; `pythons` are
    the `(path, version)` pairs the interpreter resolution reports, verbatim
    (so a test can report a path the runner must refuse)."""

    rules: Sequence[ExecRule] = ()
    installed: frozenset[str] | None = None
    pythons: tuple[tuple[str, str], ...] = ((PYENV_PYTHON, "3.13.7"),)
    fail_on: Mapping[str, BoundaryError] = field(default_factory=dict)
    policy_read_back: Json | None = None
    hang_on: str | None = None
    delete_takes_effect: bool = True
    calls: list[tuple[str, ...]] = field(default_factory=list)
    stdin_seen: list[bytes] = field(default_factory=list)
    timeouts_seen: list[float] = field(default_factory=list)
    first_bytes_seen: list[float | None] = field(default_factory=list)
    argv_seen: list[tuple[str, ...]] = field(default_factory=list)
    _sprites: dict[str, _Sprite] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_script(cls, script: Mapping[str, Any]) -> FakeSprites:
        """`{"installed": [...], "exec": [{"match", "stdout", "exit_code"}]}`"""
        installed = script.get("installed")
        return cls(
            rules=tuple(
                ExecRule(e["match"], e["stdout"], int(e["exit_code"]))
                for e in script.get("exec", ())
            ),
            installed=None if installed is None else frozenset(installed),
        )

    def live_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sprites)

    def _record(self, *call: str) -> None:
        with self._lock:
            self.calls.append(call)
        failure = self.fail_on.get(call[0])
        if failure is not None:
            raise failure

    def _get(self, name: str) -> _Sprite:
        with self._lock:
            sprite = self._sprites.get(name)
        if sprite is None:
            raise NotFoundError(f"sprite {name} not found")
        return sprite

    def create(self, name: str) -> None:
        self._record("create", name)
        with self._lock:
            if name in self._sprites:
                raise BoundaryError(f"sprite {name} already exists")
            self._sprites[name] = _Sprite()

    def set_network_policy(self, name: str, rules: Sequence[Json]) -> None:
        self._record("set_network_policy", name)
        self._get(name).network_rules = [dict(r) for r in rules]

    def get_network_policy(self, name: str) -> Json:
        self._record("get_network_policy", name)
        sprite = self._get(name)
        return self.policy_read_back or {"rules": list(sprite.network_rules)}

    def set_memory_limit(self, name: str, limit_mb: int) -> None:
        self._record("set_memory_limit", name)
        self._get(name).memory_mb = limit_mb

    def exec(
        self,
        name: str,
        argv: Sequence[str],
        stdin: bytes,
        timeout_s: float,
        first_byte_s: float | None = None,
    ) -> bytes:
        script = argv[-1]
        self._record("exec", name, script)
        sprite = self._get(name)
        self.stdin_seen.append(stdin)
        self.timeouts_seen.append(timeout_s)
        self.first_bytes_seen.append(first_byte_s)
        self.argv_seen.append(tuple(argv))
        if self.hang_on is not None and self.hang_on in script:
            # Ignores timeout_s on purpose: models a stuck exec that only
            # destroying the Sprite can end.
            sprite.destroyed.wait(_HANG_LIMIT_S)
            raise BoundaryError("exec connection closed")
        stdout, code = self._answer(script, _fed(script, stdin))
        start = f"{START_MARKER}\n" if START_MARKER in script else ""
        return b"\x01" + f"{start}{stdout}\n{EXIT_MARKER}{code}\n".encode()

    def _answer(self, script: str, stdin: bytes) -> tuple[str, int]:
        if PROBE_TAG in script:
            return self._probe(script), 0
        if PYTHON_TAG in script:
            return "\n".join(f"{PYTHON_TAG}:{p}:{v}" for p, v in self.pythons), 0
        if "wc -c" in script and _FEED_RE.search(script):
            return str(len(stdin)), 0
        for rule in self.rules:
            if rule.match in script:
                return rule.handler(script, stdin)
        return "sh: command not found", EXIT_NOT_FOUND

    def _probe(self, script: str) -> str:
        names = script.split("for b in ", 1)[1].split(";", 1)[0].split()
        return "\n".join(
            f"{PROBE_TAG}:present:{n}:/usr/bin/{n}:/usr/bin/{n}"
            if self._has(n)
            else f"{PROBE_TAG}:absent:{n}"
            for n in names
        )

    def _has(self, binary: str) -> bool:
        return self.installed is None or binary in self.installed

    def delete(self, name: str) -> None:
        self._record("delete", name)
        sprite = self._get(name)
        sprite.destroyed.set()
        if self.delete_takes_effect:
            with self._lock:
                self._sprites.pop(name, None)

    def exists(self, name: str) -> bool:
        self._record("exists", name)
        with self._lock:
            return name in self._sprites


@dataclass
class MemoryLedger:
    names: set[str] = field(default_factory=set)

    def record(self, name: str) -> None:
        self.names.add(name)

    def clear(self, name: str) -> None:
        self.names.discard(name)

    def pending(self) -> tuple[str, ...]:
        return tuple(sorted(self.names))


@dataclass(frozen=True)
class StaticToken:
    """A pre-minted GitHub token. Tests only: live mode always mints App
    installation tokens (`github_auth.AppInstallationTokens`)."""

    value: str

    def token(self) -> str:
        return self.value


def _fed(script: str, stdin: bytes) -> bytes:
    """What the script itself reads: the `head -c N` feed's bytes, or
    nothing when its stdin is /dev/null."""
    feed = _FEED_RE.search(script)
    return stdin[: int(feed.group(1))] if feed else b""
