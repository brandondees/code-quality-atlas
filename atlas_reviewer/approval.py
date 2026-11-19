# SPDX-License-Identifier: MIT
"""The operator-approval gate behind the #734 execution-tool allow-list
(config slice S7, D88).

A repo's requested additions to the allow-list -- the declared test
commands its default-branch `REVIEW.md` proposes for `run_tests` -- are
**proposals**, and a proposal only ever becomes an **operator-approval
request**: a blocked command routes to the `ApprovalChannel` port, and
every outcome other than an explicit `APPROVED` denies. That covers a
timeout, an error, a malformed answer, and the run's wall or dollar limit
being reached while the request waits; waiting counts against the run's
wall clock, because the wait is the calling lens's own elapsed time and
the gate bounds the wait by the wall that remains.

The port is deliberately left open: the plan does not specify the
operator-approval channel or who the operator is for a non-allowlisted
installation, and nothing here invents one. The production default is
`NeverApproved`, a channel that never approves -- so on a deployed
service every blocked command is denied and named as an unapproved gap,
and no proposal is ever granted. A real channel joins by implementing
`ApprovalChannel`; it must answer by the deadline it is given (on the
caller's clock scale), and any exception it raises denies fail-closed.

An approved addition lives in run-scoped state that dies with the run:
`RunApprovals` is built per lens run, its approvals never persist, are
never cached across runs or PRs, and are never written to the state
volume. The scope is deliberately the narrow reading of the #734
decision's "within the same run": an approval granted for one lens run's
staged runner is not carried to another lens's runner -- that would
propagate a grant beyond the runner it was given for, the shape
never-auto-granted exists to prevent. A second lens that needs the same
command requests it for its own run.

The notes the gate writes are fixed phrases with counts -- how many
commands the run's allow-list proposes, how many are approved so far --
and never the raw rejected value: an invalid proposal is refused before
this module is ever reached (`repo_config` fails the whole line open to
deny with a named note), so the only command names that reach a request
are ones the parse already validated to a markup-free grammar, and the
model cannot mint a note, because a name it invents matches no proposal
and is refused without a note.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from atlas_reviewer.ports import Clock

# How long one approval request may wait, on top of the run's remaining
# wall: the shorter of this and the wall that is left bounds the wait, so
# one wait cannot park the whole review wall in a single channel call (the
# same shape `runner`'s own bounded waits keep). Provisional default
# pending the owner (D39's standing rule, D88).
MAX_APPROVAL_WAIT_S = 30.0


class ApprovalOutcome(StrEnum):
    """What the operator-approval channel answered. Only an explicit
    `APPROVED` grants; every other value -- and every error, timeout and
    limit reached while waiting -- denies."""

    APPROVED = "approved"
    DENIED = "denied"
    NO_ANSWER = "no answer"


@dataclass(frozen=True)
class CommandProposal:
    """One proposed addition to the execution-tool allow-list, parsed and
    validated from the repo's default-branch `REVIEW.md` (config slice
    S7, D88). `name` is the exact token a `run_tests` call names to use
    it; `argv` is the argv the bridge builds and runs -- program first,
    the proposal's own fixed arguments, no shell, no environment change,
    every path workspace-relative. The bridge never builds argv from
    anything the model sent: the model's part is the exact-match `name`
    and, for the built-in entry alone, the test selector."""

    name: str
    argv: tuple[str, ...]


class ApprovalChannel(Protocol):
    """The operator-approval channel, left open (D88): the plan does not
    specify the channel or who the operator is for a non-allowlisted
    installation. `request` asks one proposal and answers by `deadline`
    (absolute, on the caller's clock scale) with one outcome; only
    `APPROVED` grants. A channel that raises, answers late, or answers
    with anything else is denied by the gate, never retried within the
    run."""

    def request(
        self, proposal: CommandProposal, deadline: float
    ) -> ApprovalOutcome: ...


class NeverApproved:
    """The production default channel: it never approves. Every blocked
    command is denied and named as an unapproved gap, so a deployed
    service grants nothing until a real channel exists (D88)."""

    def request(self, proposal: CommandProposal, deadline: float) -> ApprovalOutcome:
        return ApprovalOutcome.NO_ANSWER


# The fixed refusal reasons. Each names the condition and the counts --
# how many commands the run's allow-list proposes, how many are approved
# -- and never the command text. The counts come from the gate's own
# state, so they are controller facts, not author text.
_DENIED = (
    "the operator denied the proposed test command; the run's allow-list "
    "holds {proposed} proposed and {approved} approved, and the command "
    "stays unapproved -- the built-in pytest entry stands"
)
_NO_ANSWER = (
    "no operator approval arrived within the run's remaining wall; the "
    "run's allow-list holds {proposed} proposed and {approved} approved, "
    "and the command stays unapproved -- the built-in pytest entry stands"
)
_WALL_NO_ROOM = (
    "the run's wall clock has no room left to wait for an approval; the "
    "command stays unapproved and the built-in pytest entry stands"
)
_WALL_SPENT_WAITING = (
    "the run's wall clock ran out while the approval waited; the command "
    "stays unapproved and the built-in pytest entry stands"
)
_DOLLAR_SPENT = (
    "the run's dollar limit is spent, so no approval may be waited for; "
    "the command stays unapproved and the built-in pytest entry stands"
)
_DOLLAR_SPENT_WAITING = (
    "the run's dollar limit was reached while the approval waited; the "
    "command stays unapproved and the built-in pytest entry stands"
)


@dataclass
class RunApprovals:
    """The run-scoped gate between a proposed command and the runner:
    `admit` turns a blocked command into one operator-approval request
    and denies everything that is not an explicit `APPROVED` -- a denial
    or a no-answer, an error the channel raised, the wait's own wall and
    dollar bounds, and the wall or dollar limit reaching the run while
    the request waited. Outcomes are sticky for the run: a proposal
    denied once is never re-requested, so a lens cannot spend its session
    re-asking, and an approved one stays approved for the run. The state
    dies with the lens run's bridge; nothing here persists.

    `wall_left` is the seconds remaining on the run's wall clock and
    `budget_ok` whether the run's dollar bound still has room; both are
    the caller's live checks (the service glue wires them to the review's
    deadline and spend), and the wait is bounded by the shorter of the
    wall that is left and `MAX_APPROVAL_WAIT_S`. The channel is called
    with an absolute deadline on `clock`'s scale; an exception out of it
    is a `NO_ANSWER`, fail-closed."""

    proposals: Mapping[str, CommandProposal]
    channel: ApprovalChannel
    clock: Clock
    wall_left: Callable[[], float]
    budget_ok: Callable[[], bool]
    _approved: set[str] = field(default_factory=set, init=False, repr=False)
    _refused: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def proposal(self, name: str) -> CommandProposal | None:
        """The proposal `name` names, or None: the exact-match lookup the
        bridge gates the argv on. The model's own string is never argv;
        a name that matches nothing is refused before this is asked."""
        return self.proposals.get(name)

    def approved_count(self) -> int:
        return len(self._approved)

    def admit(self, name: str) -> tuple[bool, str]:
        """Whether `name` may run in this run: `(True, "")` when it is
        approved (already, or by the channel's answer to the request this
        call routes), else `(False, reason)` with the fixed refusal
        reason. A name the run's allow-list does not propose never gets
        here -- the bridge refuses it as an unknown command before
        asking."""
        if name in self._approved:
            return True, ""
        refused = self._refused.get(name)
        if refused is not None:
            return False, refused
        proposal = self.proposals.get(name)
        if proposal is None:  # pragma: no cover - the bridge gates on this
            return False, _no_proposal()
        if self.wall_left() <= 0.0:
            return self._deny(name, _WALL_NO_ROOM)
        if not self.budget_ok():
            return self._deny(name, _DOLLAR_SPENT)
        wait_s = min(MAX_APPROVAL_WAIT_S, self.wall_left())
        deadline = self.clock.monotonic() + wait_s
        try:
            outcome = self.channel.request(proposal, deadline)
        except Exception:  # noqa: BLE001 -- a channel's failure is the run's denial, fail closed
            outcome = ApprovalOutcome.NO_ANSWER
        if outcome is ApprovalOutcome.APPROVED:
            if self.wall_left() <= 0.0:
                return self._deny(name, _WALL_SPENT_WAITING)
            if not self.budget_ok():
                return self._deny(name, _DOLLAR_SPENT_WAITING)
            self._approved.add(name)
            return True, ""
        if outcome is ApprovalOutcome.DENIED:
            return self._deny(name, _DENIED)
        return self._deny(name, _NO_ANSWER)

    def _deny(self, name: str, reason: str) -> tuple[bool, str]:
        text = reason.format(proposed=len(self.proposals), approved=len(self._approved))
        self._refused[name] = text
        return False, text


def _no_proposal() -> str:
    return (
        "the named command is not one this run's allow-list proposes; the "
        "built-in pytest entry stands"
    )
