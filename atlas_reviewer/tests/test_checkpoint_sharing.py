# SPDX-License-Identifier: MIT
"""Issue #819 (D95), the checkpoint slice: one shared post-setup
checkpoint, baked once by a setup pass with egress allowed and the
deny-all flip verified, and restored by every lens runner instead of
re-running the setup there. The lifecycle tests use the fakes' per-exec
policy record and per-sprite checkpoint records; the coordinator tests
run the multi-lens fan-out through the local runner. Nothing here
contacts GitHub, a live Sprite or a model."""

from dataclasses import replace

from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.local_runner import LocalSprites
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.runner import SetupSpec, bake_setup, run_session

from .agentic import final
from .helpers import FakeClock

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


def test_a_restore_the_api_refuses_fails_the_run_named():
    api = FakeSprites(rules=DENY_EGRESS)
    before = len(api.calls)

    def body(session):
        session.exec("body", "true")
        return "done"

    report = run_session(
        api, MemoryLedger(), body, name=NAME, deadline_s=120.0,
        clock=FakeClock(), restore="v9",
    )  # fmt: skip
    assert report.status is RunnerStatus.FAILED
    assert "checkpoint restore" in report.note
    assert "v9" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert ops(api)[before:][:4] == [
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


def _run_two_lenses(tmp_path, sprites, script, **kw):
    from atlas_reviewer.coordinator import review_lenses
    from atlas_reviewer.fakes import ScriptedLensModel
    from atlas_reviewer.redact import Redactor

    from .agentic import BODY, DIFF, LENS, LIMITS, trees
    from .test_coordinator import EVENT, OTHER, OTHER_BODY, StubLibrary, ledger
    from .test_keepalive import TaskServer, socket_path

    tasks = TaskServer(socket_path(tmp_path))
    tasks.start()
    try:
        result = review_lenses(
            EVENT, [LENS, OTHER], DIFF, trees(),
            library=StubLibrary({LENS: BODY, OTHER: OTHER_BODY}),
            model=ScriptedLensModel(script),
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
    result = _run_two_lenses(tmp_path, api, [final(), final()], setup=SPEC)
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
    result = _run_two_lenses(tmp_path, api, [final(), final()], setup=SPEC)
    assert api.live_names() == ()
    assert api.restores == []
    # Every runner (the two planned lenses, plus any continuation rounds)
    # ran the fallback setup phase: two deny-False execs each -- the
    # interpreter resolution and the setup command -- before its own flip.
    for name, flags in _denies_by_runner(api).items():
        assert flags[:2] == [False, False], name
        assert flags[2:] and all(flags[2:]), name
    assert [lens.index for lens in result.lenses][:2] == [1, 2]
