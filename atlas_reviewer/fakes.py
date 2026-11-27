# SPDX-License-Identifier: MIT
"""In-memory stand-ins for the Sprites API, the runner ledger, a GitHub
token source, and an agentic lens model.

Used by the test suite and by `--dry-run`; none ever touches a real API.
`FakeSprites` records every control-plane call in order so a caller can
assert on lifecycle (policy before exec, destroy always), and answers the
runner's tool-availability probe from its `installed` set and its
interpreter resolution from `pythons`.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from atlas_reviewer.bridge_staging import COLLECT_TAG
from atlas_reviewer.delta import DECISION_TARGET_PREFIX
from atlas_reviewer.interpreter import PYENV_VERSIONS, PYTHON_TAG
from atlas_reviewer.lens_loop import FinalReply, ModelTurn, TurnRequest, UserText
from atlas_reviewer.ports import BoundaryError, Json, NotFoundError, RefusedError
from atlas_reviewer.runner import (
    DENY_ALL,
    EXIT_MARKER,
    EXIT_NOT_FOUND,
    PROBE_TAG,
    START_MARKER,
)
from atlas_reviewer.synthesis import MERGE_TARGET_PREFIX

_HANG_LIMIT_S = 10.0
_FEED_RE = re.compile(r"head -c (\d+) \| \{ ")
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
    # Exit status of an `atlas-task-hold` exec. Tests set this to inject a
    # keepalive failure; the default is a hold that succeeds.
    hold_exit: int = 0
    delete_takes_effect: bool = True
    calls: list[tuple[str, ...]] = field(default_factory=list)
    stdin_seen: list[bytes] = field(default_factory=list)
    timeouts_seen: list[float] = field(default_factory=list)
    first_bytes_seen: list[float | None] = field(default_factory=list)
    argv_seen: list[tuple[str, ...]] = field(default_factory=list)
    policies_sent: list[tuple[str, list[Json]]] = field(default_factory=list)
    # Per exec, whether the sprite's network policy was exactly deny-all
    # when the exec ran (issue #819, D95): the order proof's raw
    # material -- setup execs answer False, every exec after the flip
    # answers True. The named twin pairs each entry with the runner it
    # belongs to, appended atomically with it, so interleaved runners'
    # execs can be checked per runner.
    policy_deny_at_exec: list[bool] = field(default_factory=list)
    policy_deny_named: list[tuple[str, bool]] = field(default_factory=list)
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
                raise RefusedError(f"Sprites HTTP 409: sprite {name} already exists")
            self._sprites[name] = _Sprite()

    def set_network_policy(self, name: str, rules: Sequence[Json]) -> None:
        self._record("set_network_policy", name)
        sent: list[Json] = [dict(r) for r in rules]
        self.policies_sent.append((name, sent))
        self._get(name).network_rules = sent

    def get_network_policy(self, name: str) -> Json:
        self._record("get_network_policy", name)
        sprite = self._get(name)
        if self.policy_read_back is not None:
            return self.policy_read_back
        return {"rules": list(sprite.network_rules)}

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
        denied = sprite.network_rules == list(DENY_ALL)
        self.policy_deny_at_exec.append(denied)
        self.policy_deny_named.append((name, denied))
        self.stdin_seen.append(stdin)
        self.timeouts_seen.append(timeout_s)
        self.first_bytes_seen.append(first_byte_s)
        self.argv_seen.append(tuple(argv))
        if self.hang_on is not None and self.hang_on in script:
            # Ignores timeout_s on purpose: models a stuck exec that only
            # destroying the Sprite can end.
            if not sprite.destroyed.wait(_HANG_LIMIT_S):
                raise BoundaryError("fake hang limit reached; nothing destroyed it")
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
        if "atlas-task-hold" in script:
            return "", self.hold_exit
        for rule in self.rules:
            if rule.match in script:
                return rule.handler(script, stdin)
        if COLLECT_TAG + ":" in script:
            # The collection probe the staging runs (D80's 2026-11-26
            # update): a fake whose scripted rules did not name a verdict
            # models a working environment -- the tests collect -- which
            # is what the scripted replies around it were written against.
            return "atlas-collect:0:", 0
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


@dataclass
class ScriptedLensModel:
    """A `LensModel` that plays a script: each turn takes the next entry,
    a `ModelTurn` or a function of the request, or raises it when it is a
    `BoundaryError`. Every request is kept. Past the script's end each
    turn fails.

    The delta review's controller-level turns are not script entries: a
    coordinator-decision turn (D83) is answered from `decisions` -- an
    empty tuple replies with no decisions, which the controller's
    validation refuses, falling back to re-running every lens -- so a
    script's entries stay aligned with the lens loop's own turns, the
    way the carry-forward turn is answered by its own entry."""

    script: list[Any]
    worst_usd: Decimal = Decimal("0.10")
    name: str = "scripted"
    requests: list[TurnRequest] = field(default_factory=list)
    decisions: tuple[Mapping[str, str], ...] = ()
    merge: Mapping[str, Any] | None = None
    """The merge/verify call's reply (the plan's step 7), when the test
    wants one: None answers the merge turn with an empty reply -- every
    finding stands -- so a script's entries stay aligned with the lens
    loop's own turns, the way the decision turn is answered."""

    def worst_case_usd(self, request: TurnRequest) -> Decimal:
        return self.worst_usd

    def output_tokens_within(self, request: TurnRequest, budget_usd: Decimal) -> int:
        """A fixed worst case: no smaller cap ever fits better."""
        return 0

    def turn(self, request: TurnRequest) -> ModelTurn:
        self.requests.append(request)
        if _is_decision_turn(request.messages):
            return FinalReply(
                json.dumps({"decisions": [dict(entry) for entry in self.decisions]}),
                self.worst_usd,
            )
        if _is_merge_turn(request.messages):
            reply = dict(self.merge) if self.merge is not None else {}
            return FinalReply(json.dumps(reply), self.worst_usd)
        if not self.script:
            raise BoundaryError("the scripted model has no turn left")
        step = self.script.pop(0)
        if isinstance(step, BoundaryError):
            raise step
        return step(request) if callable(step) else step


def _is_merge_turn(messages: tuple[object, ...]) -> bool:
    """Whether the turn to answer is the merge/verify call's turn (the
    plan's step 7): its first message opens with the controller's own
    merge subject, which no PR-written text can be the first line of."""
    return bool(
        messages
        and isinstance(messages[0], UserText)
        and messages[0].text.startswith(MERGE_TARGET_PREFIX)
    )


def _is_decision_turn(messages: tuple[object, ...]) -> bool:
    """Whether the turn to answer is the delta review's coordinator
    decision turn (D83): its first message opens with the controller's
    own decision subject, which no PR-written text can be the first line
    of."""
    return bool(
        messages
        and isinstance(messages[0], UserText)
        and messages[0].text.startswith(DECISION_TARGET_PREFIX)
    )


def _fed(script: str, stdin: bytes) -> bytes:
    """What the script itself reads: the `head -c N` feed's bytes, or
    nothing when its stdin is /dev/null."""
    feed = _FEED_RE.search(script)
    return stdin[: int(feed.group(1))] if feed else b""
