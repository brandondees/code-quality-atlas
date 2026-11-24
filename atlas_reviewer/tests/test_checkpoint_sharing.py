# SPDX-License-Identifier: MIT
"""Issue #819 (D95), the checkpoint slice: one shared post-setup
checkpoint, baked once by a setup pass with egress allowed and the
deny-all flip verified, and restored by every lens runner instead of
re-running the setup there. The lifecycle tests use the fakes' per-exec
policy record and per-sprite checkpoint records; the coordinator tests
run the multi-lens fan-out through the local runner. Nothing here
contacts GitHub, a live Sprite or a model."""

from dataclasses import replace

import pytest

from atlas_reviewer.domain import CleanupStatus, PrEvent, RunnerStatus
from atlas_reviewer.fakes import (
    ExecRule,
    FakeSprites,
    MemoryLedger,
    ScriptedLensModel,
)
from atlas_reviewer.local_runner import LocalSprites
from atlas_reviewer.ports import BoundaryError, NotFoundError
from atlas_reviewer.runner import (
    DEFAULT_CREATE_RETRIES,
    RestoreRefusedError,
    SetupSpec,
    bake_setup,
    run_session,
)

from .agentic import LENS, READ_ALL, final
from .helpers import HEAD, FakeClock
from .test_coordinator import OTHER

EVENT_BAKE = PrEvent("example-org/example-app", 7, HEAD)

NAME = "cqa-rev-20261123-130000-abc123"
SETUP_ECHO = ("echo", "atlas-setup-ran")
SPEC = SetupSpec((SETUP_ECHO,))
BAKE_NAME = "cqa-rev-setup"
# The clean-egress answer: each connect attempts and reports timeout,
# which is what the deny-all policy produces on a live runner; the echo
# rule is the setup command's own success answer.
DENY_EGRESS = (
    ExecRule(
        "create_connection",
        "atlas-egress:1.1.1.1:443:tried:timeout:0\n"
        "atlas-egress:example.com:443:tried:timeout:0",
        0,
    ),
    ExecRule("atlas-setup-ran", "", 0),
)


def ops(api):
    return [c[0] for c in api.calls]


def test_the_setup_pass_bakes_a_checkpoint_and_destroys_the_setup_runner():
    """The bake's own order, end to end: the setup execs with egress
    allowed, the verified flip, the egress proof, then the checkpoint --
    and the setup runner destroyed once the checkpoint is made, so no
    second long-lived runner needs holding awake."""
    api = FakeSprites(rules=DENY_EGRESS)
    baked = bake_setup(
        api, MemoryLedger(), SPEC, name=NAME, deadline_s=120.0, clock=FakeClock()
    )
    assert baked.checkpoint_id == "v1"
    assert baked.report is not None
    assert baked.report.status is RunnerStatus.COMPLETED
    assert baked.report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()
    sequence = ops(api)
    flip = sequence.index("set_network_policy")
    assert sequence[flip : flip + 3] == [
        "set_network_policy",
        "get_network_policy",
        "set_memory_limit",
    ]
    assert sequence[flip + 3 : flip + 6] == ["exec", "checkpoint", "delete"]
    assert api.policy_deny_at_exec == [False, False, True]
    assert api.policies_sent == [(NAME, [{"action": "deny", "domain": "*"}])]


def test_a_bake_whose_checkpoint_call_fails_yields_no_checkpoint():
    api = FakeSprites(rules=DENY_EGRESS, fail_on={"checkpoint": BoundaryError("boom")})
    baked = bake_setup(
        api, MemoryLedger(), SPEC, name=NAME, deadline_s=120.0, clock=FakeClock()
    )
    assert baked.checkpoint_id is None
    assert baked.report is not None
    assert baked.report.status is RunnerStatus.FAILED
    assert api.live_names() == ()


def test_a_restoring_runner_flips_first_restores_then_proves_egress():
    """The restore's own order: deny-all is set and read back before the
    restore (a control-plane call), the restored state is what the egress
    proof then examines, and every exec of the review runs denied -- the
    checkpoint carries no policy, the runner's own flip is the gate."""
    api = FakeSprites(rules=DENY_EGRESS)
    api.create(BAKE_NAME)
    api.checkpoint(BAKE_NAME, "bake")
    before = len(api.calls)
    seen: list[str | None] = []

    def body(session):
        seen.append(api._sprites[NAME].restored_from)
        session.exec("body", "true")
        return "done"

    report = run_session(
        api, MemoryLedger(), body, name=NAME, deadline_s=120.0,
        clock=FakeClock(), restore="v1",
    )  # fmt: skip
    assert report.status is RunnerStatus.COMPLETED, report.note
    sequence = ops(api)[before:]
    assert sequence[:5] == [
        "create",
        "set_network_policy",
        "get_network_policy",
        "restore",
        "set_memory_limit",
    ]
    assert api.policy_deny_at_exec == [True, True]
    assert seen == ["v1"]


def test_a_restore_the_api_refuses_propagates_for_the_callers_retry():
    """A restore that did not happen raises `RestoreRefusedError` past
    the run's report -- the denied network is never re-opened on this
    runner; the caller's retry is a fresh runner running the setup phase
    itself -- and the runner is still destroyed and its ledger entry
    cleared."""
    api = FakeSprites(rules=DENY_EGRESS)

    def body(session):
        session.exec("body", "true")
        return "done"

    with pytest.raises(RestoreRefusedError) as exc_info:
        run_session(
            api, MemoryLedger(), body, name=NAME, deadline_s=120.0,
            clock=FakeClock(), restore="v9",
        )  # fmt: skip
    assert "checkpoint restore" in str(exc_info.value)
    assert "v9" in str(exc_info.value)
    assert api.live_names() == ()
    assert ops(api)[:4] == [
        "create",
        "set_network_policy",
        "get_network_policy",
        "restore",
    ]


def test_a_restoring_local_runner_answers_the_egress_proof_with_the_policy():
    """The local runner cannot enforce a network policy, so its egress
    answer is the outcome deny-all produces -- the same modeling choice
    its scoped sweep makes -- and the restored run completes."""
    api = LocalSprites()
    api.create(BAKE_NAME)
    api.checkpoint(BAKE_NAME, "bake")
    seen: list[str | None] = []

    def body(session):
        seen.append(api._sprites[NAME].restored_from)
        session.exec("body", "true")
        return "done"

    report = run_session(
        api, MemoryLedger(), body, name=NAME, deadline_s=300.0,
        clock=FakeClock(), restore="v1",
    )  # fmt: skip
    assert report.status is RunnerStatus.COMPLETED, report.note
    assert seen == ["v1"]
    assert all(api.policy_deny_at_exec)


# ------------------------------------------------- the coordinator pass


class _Recording(LocalSprites):
    """Keeps the restore records past each runner's destroy -- the fake
    stores them on the sprite, and a destroyed sprite is gone."""

    def __init__(self):
        super().__init__()
        self.restores: list[tuple[str, str]] = []

    def restore(self, name, checkpoint_id):
        super().restore(name, checkpoint_id)
        self.restores.append((name, checkpoint_id))


def _denies_by_runner(api):
    grouped: dict[str, list[bool]] = {}
    for name, denied in api.policy_deny_named:
        grouped.setdefault(name, []).append(denied)
    return grouped


def _run_lenses(tmp_path, sprites, names, model, **kw):
    from atlas_reviewer.coordinator import review_lenses
    from atlas_reviewer.redact import Redactor

    from .agentic import BODY, DIFF, LENS, LIMITS, trees
    from .test_coordinator import EVENT, OTHER, OTHER_BODY, StubLibrary, ledger
    from .test_keepalive import TaskServer, socket_path

    tasks = TaskServer(socket_path(tmp_path))
    tasks.start()
    try:
        result = review_lenses(
            EVENT, names, DIFF, trees(),
            library=StubLibrary({LENS: BODY, OTHER: OTHER_BODY}),
            model=model,
            limits=replace(LIMITS, pool_size=2), ledger=ledger(tmp_path),
            sprites=sprites, runner_ledger=MemoryLedger(), redactor=Redactor(),
            clock=FakeClock(), nonce=lambda: "f00dfeedf00dfeed",
            bridge_root=str(tmp_path / "bridge"), task_socket=str(tasks.path),
            **kw,
        )  # fmt: skip
    finally:
        tasks.close()
        assert tasks.tasks == {}, tasks.order
    return result


def test_every_lens_restores_the_one_checkpoint_and_none_reruns_setup(tmp_path):
    """The acceptance's reuse shape: the bake runs once, every lens
    runner restores that checkpoint, and no lens runner runs a setup exec
    of its own -- every lens exec from the first on runs denied."""
    api = _Recording()
    result = _run_lenses(
        tmp_path, api, [LENS, OTHER],
        ScriptedLensModel([final(), final()]), setup=SPEC,
    )  # fmt: skip
    assert api.live_names() == ()
    # The two planned lenses restore the bake's checkpoint; the
    # continuation rounds the unread-file rule starts restore it too.
    assert len(api.restores) >= 2, api.restores
    assert all(checkpoint == "v1" for _name, checkpoint in api.restores)
    denies = _denies_by_runner(api)
    bake_flags = [
        flags
        for name, flags in denies.items()
        if name not in {runner for runner, _ in api.restores}
    ]
    assert len(bake_flags) == 1 and bake_flags[0][:2] == [False, False]
    # The bake's own runner: two setup execs with egress allowed, then
    # only denied execs. Every lens runner: only denied execs, the
    # restore having replaced the setup phase.
    for name, flags in denies.items():
        if name in {runner for runner, _ in api.restores}:
            assert flags and all(flags), name
    assert [lens.index for lens in result.lenses][:2] == [1, 2]


def test_a_failed_bake_falls_back_to_per_lens_setup(tmp_path):
    """A bake that cannot make a checkpoint is named, and every lens runs
    the setup phase on its own runner -- the slice-1 shape, each with its
    own allowed window before its own flip. The fallback is the
    coordinator's, decided before a lens runner starts; a restore refused
    later never re-opens the network mid-runner."""

    class NoCheckpoint(_Recording):
        def checkpoint(self, name, comment):
            raise BoundaryError("the control plane refused the checkpoint")

    api = NoCheckpoint()
    result = _run_lenses(
        tmp_path, api, [LENS, OTHER],
        ScriptedLensModel([final(), final()]), setup=SPEC,
    )  # fmt: skip
    assert api.live_names() == ()
    assert api.restores == []
    # Every runner (the two planned lenses, plus any continuation rounds)
    # ran the fallback setup phase: two deny-False execs each -- the
    # interpreter resolution and the setup command -- before its own flip.
    for name, flags in _denies_by_runner(api).items():
        assert flags[:2] == [False, False], name
        assert flags[2:] and all(flags[2:]), name
    assert [lens.index for lens in result.lenses][:2] == [1, 2]


def test_a_recovered_bake_failure_does_not_hold_coverage_open(tmp_path):
    """The bake's failed report stays off the Runner line when the
    fallback recovered: a review whose lens runners all completed --
    here, a single lens that read everything and finished clean -- keeps
    `coverage_complete` true and can approve, instead of posting COMMENT
    on a provisioning pass that already redid its work."""

    class NoCheckpoint(_Recording):
        def checkpoint(self, name, comment):
            raise BoundaryError("the control plane refused the checkpoint")

    api = NoCheckpoint()
    result = _run_lenses(
        tmp_path, api, [LENS], ScriptedLensModel([READ_ALL, final()]),
        setup=SPEC,
    )  # fmt: skip
    assert api.restores == []
    assert result.coverage_complete is True


# ------------------------------------- the degrade path and the bake bounds


def test_a_restore_refusal_retries_the_lens_on_a_fresh_runner(tmp_path):
    """The documented degrade path, in the code: the lens whose restore
    was refused retries ONCE on a fresh runner running the setup phase
    itself -- its own provisioning allows egress again before its own
    flip, the denied network never re-opened -- and the lens completes."""

    class RefusingRestore(_Recording):
        def restore(self, name, checkpoint_id):
            raise NotFoundError(f"checkpoint {checkpoint_id} not found")

    api = RefusingRestore()
    result = _run_lenses(
        tmp_path, api, [LENS, OTHER],
        ScriptedLensModel([final(), final()]), setup=SPEC,
    )  # fmt: skip
    assert api.restores == []
    assert api.live_names() == ()
    # Every runner that ran the setup phase (the bake, plus each lens's
    # fresh retry runner) shows its two deny-False execs before its own
    # flip; nothing runs denied-before-flip anywhere else.
    for name, flags in _denies_by_runner(api).items():
        if flags[:1] == [False]:
            assert flags[:2] == [False, False], name
            assert flags[2:] and all(flags[2:]), name
    lens = next(entry for entry in result.lenses if entry.index == 1)
    assert lens.state.value == "complete" or lens.outcome is not None


def test_a_deterministic_setup_failure_runs_no_per_lens_setup(tmp_path):
    """A bake whose setup command failed would fail identically on every
    lens runner with egress open again, so the lenses run NO setup: the
    review continues on the unconfigured image's behavior, named."""
    api = _Recording()
    failing = SetupSpec((("false",),))
    result = _run_lenses(
        tmp_path, api, [LENS, OTHER],
        ScriptedLensModel([final(), final()]), setup=failing,
    )  # fmt: skip
    assert api.live_names() == ()
    # The bake's one deny-False exec pair is the only network window:
    # every lens runner ran with deny-all from its first exec.
    false_windows = [
        name
        for name, flags in _denies_by_runner(api).items()
        if any(not flag for flag in flags)
    ]
    assert len(false_windows) == 1
    assert api.restores == []
    lens = next(entry for entry in result.lenses if entry.index == 1)
    assert lens.state.value == "complete" or lens.outcome is not None


def test_the_bake_is_skipped_when_no_lens_is_left_to_run():
    """Every lens reused by the delta prelude means no runner will
    restore anything: the bake -- a runner with egress allowed and real
    installs -- must not run for nothing."""
    from atlas_reviewer.coordinator import _bake_setup_pass

    api = FakeSprites(rules=DENY_EGRESS)
    baked = _bake_setup_pass(
        api, MemoryLedger(), SPEC, EVENT_BAKE, 1_000_000.0, FakeClock(),
        None, None, DEFAULT_CREATE_RETRIES, names=(),
    )  # fmt: skip
    assert baked is None
    assert api.calls == []


def test_the_bake_gets_its_own_wall_cap_not_the_whole_review_deadline():
    from atlas_reviewer.coordinator import _bake_setup_pass
    from atlas_reviewer.domain import RunnerStatus as _RS

    api = FakeSprites(rules=DENY_EGRESS)
    baked = _bake_setup_pass(
        api, MemoryLedger(), SPEC, EVENT_BAKE, 1_000_000.0, FakeClock(),
        None, None, DEFAULT_CREATE_RETRIES, names=[LENS], bake_wall_s=0.0,
    )  # fmt: skip
    assert baked is not None and baked.checkpoint_id is None
    assert baked.report is not None
    assert baked.report.status is _RS.DEADLINE_EXCEEDED
    assert not baked.setup_failed
    assert api.live_names() == ()


# -------------------------------- the deterministic/non-deterministic split


class _FailedBakeResolution(_Recording):
    """The bake runner's interpreter-resolution exec exits nonzero, while
    every other runner's resolution runs for real -- the machinery
    failure the classification must not read as deterministic."""

    def __init__(self, bake_name):
        super().__init__()
        self.bake_name = bake_name

    def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
        if name == self.bake_name and "atlas-python" in argv[-1]:
            self._record("exec", name, argv[-1])
            self._note_policy(name)
            return b"\x01__ATLAS_EXIT__=1\n"
        return super().exec(name, argv, stdin, timeout_s, first_byte_s)


def test_a_resolution_exec_failure_is_not_a_deterministic_failure():
    """The resolution exec failing to run is a machinery failure this run
    cannot distinguish from a transient one: the bake fails closed, but
    the classification stays non-deterministic -- the caller keeps its
    per-lens fallback. The resolution *running* and finding no trusted
    interpreter is the deterministic shape."""
    api = _FailedBakeResolution(NAME)
    baked = bake_setup(
        api, MemoryLedger(), SPEC, name=NAME, deadline_s=120.0, clock=FakeClock()
    )
    assert baked.checkpoint_id is None
    assert baked.report is not None
    assert baked.report.status is RunnerStatus.FAILED
    assert baked.setup_failed is False
    assert "interpreter resolution failed" in baked.report.note

    absent = FakeSprites(rules=DENY_EGRESS, pythons=())
    baked2 = bake_setup(
        absent, MemoryLedger(), SPEC, name=NAME, deadline_s=120.0, clock=FakeClock()
    )
    assert baked2.checkpoint_id is None
    assert baked2.setup_failed is True
    assert "no trusted interpreter" in baked2.report.note


def test_a_resolution_exec_failure_keeps_the_per_lens_fallback(tmp_path):
    """End to end: the bake's interpreter resolution fails to run, so the
    classification is non-deterministic and every lens falls back to
    running the setup phase on its own runner -- whose resolution
    succeeds -- and the review completes with its coverage gate open."""
    api = _FailedBakeResolution(bake_runner_name())
    result = _run_lenses(
        tmp_path, api, [LENS],
        ScriptedLensModel([READ_ALL, final()]), setup=SPEC,
    )  # fmt: skip
    assert api.restores == []
    # The fallback ran on the lens runners (their own resolution and
    # setup command, deny-False before their own flips); the bake's own
    # resolution failure is the only exec it ran.
    for name, flags in _denies_by_runner(api).items():
        if name != api.bake_name:
            assert flags[:2] == [False, False], name
            assert flags[2:] and all(flags[2:]), name
    assert result.coverage_complete is True


def bake_runner_name():
    from atlas_reviewer.coordinator import SETUP_LENS
    from atlas_reviewer.runner import lens_runner_name

    from .test_coordinator import EVENT

    return lens_runner_name(EVENT, SETUP_LENS)
