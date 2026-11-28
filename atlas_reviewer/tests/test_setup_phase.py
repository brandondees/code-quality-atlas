# SPDX-License-Identifier: MIT
"""Issue #819 (D95): the reviewed repo's setup phase. The parse
(`repo_config`'s `review_setup_commands:` line, read from the default
branch), the runner lifecycle's order -- the setup commands run with
egress still allowed, the deny-all flip and its read-back sit between
them and every exec of the review, and the behavioral egress check
proves the flip held -- the bridge's pass-through, and the CLI and
coordinator plumbing. Nothing here contacts GitHub, a live Sprite or a
model: the fakes record the policy each exec ran under, and the local
runner answers the egress check with the outcome the deny-all policy
produces."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from atlas_reviewer.bridge import Status, run_bridge
from atlas_reviewer.bridge_staging import SourceTrees
from atlas_reviewer.cli import (
    _SETUP_FETCH_NOTE,
    _SETUP_LOOKUP_NOTE,
    _SETUP_OVERBOUND_NOTE,
    _setup_commands,
)
from atlas_reviewer.domain import CleanupStatus, PrEvent, RunnerStatus
from atlas_reviewer.fakes import ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.ports import BoundaryError, NotFoundError, ResponseTooLargeError
from atlas_reviewer.redact import Redactor
from atlas_reviewer.repo_config import parse_setup_commands, read_repo_config
from atlas_reviewer.runner import SetupSpec, run_session

from .helpers import HEAD, OLD, FakeClock, source_tarball
from .test_bridge_runs import framed
from .test_bridge_runs import staged as staged_reply

LINE = "review_setup_commands: {value}"
EVENT = PrEvent("example-org/example-app", 42, HEAD)
NAME = "cqa-rev-20261123-120000-abc123"
SETUP_ECHO = ("echo", "atlas-setup-ran")
# The clean-egress answer: each connect attempts and reports timeout,
# which is what the deny-all policy produces on a live runner; the echo
# rule is the setup command's own success answer. The egress rule
# answers with the verdict lines the real script would print.
DENY_EGRESS = (
    ExecRule(
        "create_connection",
        "atlas-egress:1.1.1.1:443:tried:timeout:0\n"
        "atlas-egress:example.com:443:tried:timeout:0",
        0,
    ),
    ExecRule("atlas-setup-ran", "", 0),
)


def parse(value: str | None):
    return parse_setup_commands(LINE.format(value=value) if value is not None else None)


# ------------------------------------------------------------------ parse


def test_a_setup_line_parses_into_argv_with_the_python_placeholder():
    read = parse("{python} -m pip install pytest, {python} -m pip install cryptography")
    assert read.commands == (
        ("{python}", "-m", "pip", "install", "pytest"),
        ("{python}", "-m", "pip", "install", "cryptography"),
    )
    assert read.notes == ()


def test_a_setup_command_without_the_placeholder_parses_like_a_proposal():
    read = parse("make deps")
    assert read.commands == (("make", "deps"),)
    assert read.notes == ()


def test_no_text_or_no_line_reads_as_no_setup():
    assert parse_setup_commands(None).commands == ()
    assert parse_setup_commands("# policy only\n").commands == ()
    assert parse_setup_commands("# policy only\n").notes == ()


def test_the_placeholder_is_the_program_token_only():
    # An argument cannot carry the placeholder: the argument grammar has
    # no braces, so the line is unusable, like any other out-of-grammar
    # token.
    read = parse("{python} -m pip install {python}")
    assert read.commands == ()
    assert "review_setup_commands:" in read.notes[0]


# The fail-open note, verbatim: the key, the condition, and the default
# that stands -- never a rejected value.
UNUSABLE_NOTE = (
    "the reviewed repo's default-branch REVIEW.md carries a "
    "review_setup_commands: line it cannot use as the run's setup "
    "commands (a comma-separated list of declared setup commands, one "
    "line per key, the program token may be the {python} placeholder); "
    "it is ignored and the runner runs no setup phase -- the execution "
    "tools stay as unavailable as they were without one"
)


def test_an_unusable_setup_line_fails_open_to_no_setup_with_the_named_note():
    read = parse("make check && curl http://evil.example")
    assert read.commands == ()
    assert read.notes == (UNUSABLE_NOTE,)


def test_a_second_setup_line_fails_open_to_no_setup():
    read = parse_setup_commands(
        f"{LINE.format(value='make deps')}\n{LINE.format(value='make all')}\n"
    )
    assert read.commands == ()
    assert "2 review_setup_commands: lines" in read.notes[0]


def test_duplicate_commands_are_unusable():
    read = parse("make deps, make deps")
    assert read.commands == ()
    assert read.notes


def test_setup_commands_are_bounded():
    assert parse(", ".join(f"step{i}" for i in range(5))).commands == ()
    over_tokens = parse("{python} a b c d e f g h i")
    assert over_tokens.commands == ()
    assert over_tokens.notes


def test_the_setup_key_draws_no_unsupported_note_in_the_merge_base_read():
    tarball = source_tarball(
        {"REVIEW.md": b"# policy\n\nreview_setup_commands: make deps\n"},
        top="example-app",
    )
    assert read_repo_config(tarball).unsupported_notes == ()


# ------------------------------------------------------- the cli glue


@dataclass
class FakeFetchGitHub:
    """The shape `_setup_commands` needs: one repository answer, one file
    answer or error -- or, when `files` is set, a per-path answer map the
    setup-spec's declared files read from."""

    repository: object = None
    repository_error: Exception | None = None
    file: bytes | None = None
    file_error: Exception | None = None
    files: Mapping[str, object] | None = None
    calls: list = field(default_factory=list)

    def get_repository(self, repo):
        self.calls.append(("get_repository", repo))
        if self.repository_error is not None:
            raise self.repository_error
        return self.repository

    def get_file(self, repo, ref, path, max_bytes):
        self.calls.append(("get_file", repo, ref, path))
        if self.files is not None and path in self.files:
            answer = self.files[path]
            if isinstance(answer, Exception):
                raise answer
            return answer
        if self.file_error is not None:
            raise self.file_error
        if self.file is None:
            raise NotFoundError("404")
        return self.file


def test_the_cli_glue_reads_the_default_branch_file():
    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        file=b"# policy\n\nreview_setup_commands: {python} -m pip install pytest\n",
    )
    spec, notes = _setup_commands(github, EVENT)
    assert spec is not None
    assert spec.commands == (("{python}", "-m", "pip", "install", "pytest"),)
    assert notes == ()
    assert github.calls == [
        ("get_repository", EVENT.repo),
        ("get_file", EVENT.repo, "main", "REVIEW.md"),
    ]


def test_no_default_branch_file_is_the_silent_unconfigured_repo():
    github = FakeFetchGitHub(repository={"default_branch": "main"})
    assert _setup_commands(github, EVENT) == (None, ())


def test_a_repo_level_lookup_failure_is_a_named_gap_with_no_setup():
    github = FakeFetchGitHub(repository_error=NotFoundError("404"))
    assert _setup_commands(github, EVENT) == (None, (_SETUP_LOOKUP_NOTE,))
    github2 = FakeFetchGitHub(repository={"default_branch": ""})
    assert _setup_commands(github2, EVENT) == (None, (_SETUP_LOOKUP_NOTE,))


def test_a_failed_fetch_or_an_over_bound_file_names_its_own_gap():
    github = FakeFetchGitHub(
        repository={"default_branch": "main"}, file_error=BoundaryError("boom")
    )
    assert _setup_commands(github, EVENT) == (None, (_SETUP_FETCH_NOTE,))
    overbound = FakeFetchGitHub(
        repository={"default_branch": "main"}, file_error=ResponseTooLargeError("over")
    )
    assert _setup_commands(overbound, EVENT) == (None, (_SETUP_OVERBOUND_NOTE,))


def test_the_cli_glue_never_carries_a_failed_reads_error_text():
    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        file_error=BoundaryError("secret-value leaked into the error"),
    )
    _got, notes = _setup_commands(github, EVENT)
    assert "secret-value" not in notes[0]


# ------------------------------------------------- the lifecycle order


def ops(api):
    return [c[0] for c in api.calls]


def _scripts(api):
    return [argv[-1] for argv in api.argv_seen]


def run_setup(api, spec, deadline_s=120.0):
    def body(session):
        session.exec("body", "true")
        return "done"

    return run_session(
        api,
        MemoryLedger(),
        body,
        name=NAME,
        deadline_s=deadline_s,
        clock=FakeClock(),
        setup=spec,
    )


def test_setup_commands_run_while_egress_is_allowed_then_everything_runs_denied():
    """The order the issue's acceptance rests on: the setup execs run
    before the policy flip (egress still allowed), the flip and its
    read-back sit between the last setup exec and the first exec of the
    review, and every exec after the flip runs under exactly deny-all."""
    api = FakeSprites(rules=DENY_EGRESS)
    report = run_setup(api, SetupSpec((SETUP_ECHO,)))
    assert report.status is RunnerStatus.COMPLETED, report.note
    # Execs in order: the interpreter resolution, the setup command --
    # both while egress is still allowed -- then the egress proof and
    # the body's exec, both under the verified deny-all.
    assert api.policy_deny_at_exec == [False, False, True, True]
    sequence = ops(api)
    flip = sequence.index("set_network_policy")
    assert sequence[flip : flip + 3] == [
        "set_network_policy",
        "get_network_policy",
        "set_memory_limit",
    ]
    assert [i for i, c in enumerate(sequence) if c == "exec" and i < flip] == [1, 2]


def test_a_failing_setup_command_fails_the_run_and_still_destroys():
    api = FakeSprites(rules=(ExecRule("atlas-setup-ran", "boom", 1),) + DENY_EGRESS)
    report = run_setup(api, SetupSpec((SETUP_ECHO,)))
    assert report.status is RunnerStatus.FAILED
    assert "setup command 1 failed" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()


def test_a_missing_interpreter_for_the_setup_phase_fails_the_run():
    api = FakeSprites(rules=DENY_EGRESS, pythons=())
    report = run_setup(api, SetupSpec((("{python}", "--version"),)))
    assert report.status is RunnerStatus.FAILED
    assert "no trusted interpreter" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_an_open_egress_check_after_the_flip_fails_the_run():
    api = FakeSprites(
        rules=(
            ExecRule(
                "create_connection",
                "atlas-egress:1.1.1.1:443:tried:connected:0\n"
                "atlas-egress:example.com:443:tried:connected:0",
                0,
            ),
            ExecRule("atlas-setup-ran", "", 0),
        )
    )
    report = run_setup(api, SetupSpec((SETUP_ECHO,)))
    assert report.status is RunnerStatus.FAILED
    assert "did not hold" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_the_egress_proof_runs_only_when_a_setup_phase_ran():
    api = FakeSprites(rules=DENY_EGRESS)
    run_setup(api, SetupSpec((SETUP_ECHO,)))
    assert sum(1 for s in _scripts(api) if "atlas-egress" in s) >= 1
    plain = FakeSprites(rules=DENY_EGRESS)
    run_setup(plain, None)
    assert sum(1 for s in _scripts(plain) if "atlas-egress" in s) == 0
    # And the plain run keeps today's lifecycle exactly: deny-all before
    # any exec at all.
    assert ops(plain)[:3] == ["create", "set_network_policy", "get_network_policy"]
    assert all(plain.policy_deny_at_exec)


def test_an_empty_spec_is_the_ordinary_runner():
    api = FakeSprites(rules=DENY_EGRESS)
    report = run_setup(api, SetupSpec(()))
    assert report.status is RunnerStatus.COMPLETED
    assert ops(api)[:3] == ["create", "set_network_policy", "get_network_policy"]
    assert all(api.policy_deny_at_exec)


def test_a_hung_setup_command_ends_at_the_deadline_and_destroys():
    """The fail-closed claim's timed-out leg, pinned: a setup command that
    hangs past its budget is ended by the run's watchdog (the fake's hung
    exec ends only when the Sprite is destroyed), the run is not
    completed, and the runner is destroyed verified -- while egress is
    still allowed, exactly the state the flip must end."""
    api = FakeSprites(rules=DENY_EGRESS, hang_on="atlas-setup-ran")
    report = run_setup(api, SetupSpec((SETUP_ECHO,)), deadline_s=0.05)
    assert report.status is RunnerStatus.DEADLINE_EXCEEDED
    assert "exec connection closed" in report.note
    assert report.cleanup is CleanupStatus.DESTROYED_VERIFIED
    assert api.live_names() == ()


# ------------------------------------------------------ the bridge pass


def _trees():
    from atlas_reviewer.bridge_staging import SourceTrees

    source = source_tarball({"calc.py": b"def total(xs):\n    return sum(xs)\n"})
    return SourceTrees(source, source, OLD, HEAD)


def _bridge_report(api, trees, tmp_path):
    import sys

    from atlas_reviewer.bridge import run_bridge
    from atlas_reviewer.redact import Redactor

    return run_bridge(
        api,
        MemoryLedger(),
        trees,
        lambda bridge: "staged",
        redactor=Redactor(),
        changed=frozenset(),
        name=NAME,
        deadline_s=300.0,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        pytest_candidates=(sys.executable,),
        setup=SetupSpec((SETUP_ECHO,)),
    )


def test_run_bridge_runs_the_setup_phase_before_the_flip_and_the_staging(tmp_path):
    """Through the bridge's own entry point: the setup execs precede the
    flip, and every exec after it -- the egress proof, the git
    resolution, the uploads and the repository build -- runs under
    verified deny-all."""
    from atlas_reviewer.local_runner import LocalSprites

    api = LocalSprites()
    report = _bridge_report(api, _trees(), tmp_path)
    assert report.status is RunnerStatus.COMPLETED, report.note
    denies = api.policy_deny_at_exec
    # The interpreter resolution and the setup command ran with egress
    # still allowed; every exec from the egress proof on ran denied.
    assert denies[:2] == [False, False]
    assert denies[2:] and all(denies[2:])
    sequence = ops(api)
    flip = sequence.index("set_network_policy")
    assert sequence[flip : flip + 2] == ["set_network_policy", "get_network_policy"]
    assert flip == 3  # the create, then the two setup execs, then the flip


def test_run_bridge_uploads_nothing_before_the_flip(tmp_path):
    from atlas_reviewer.local_runner import LocalSprites

    api = LocalSprites()
    report = _bridge_report(api, _trees(), tmp_path)
    assert report.status is RunnerStatus.COMPLETED, report.note
    flip = ops(api).index("get_network_policy")
    upload_positions = [
        i
        for i, c in enumerate(api.calls)
        if c[0] == "exec" and ("base.tar.gz" in c[2] or "head.tar.gz" in c[2])
    ]
    assert upload_positions, "the trees are uploaded"
    assert all(i > flip for i in upload_positions)


# ------------------------------------------------- the coordinator plumb


def test_the_coordinator_carries_the_setup_spec_into_the_lens_runner(tmp_path):
    """The setup spec rides `review_lens` into the lens run's runner: the
    lens's own runner ran the setup phase before its flip, recorded by
    the fake's per-exec policy record -- the plumb a dropped kwarg would
    lose."""
    from atlas_reviewer.local_runner import LocalSprites

    from .agentic import final
    from .test_coordinator import review

    api = LocalSprites()
    result, _model, sprites = review(
        tmp_path,
        [final()],
        sprites=api,
        setup=SetupSpec((SETUP_ECHO,)),
    )
    assert sprites is api
    denies = api.policy_deny_at_exec
    # The setup phase's two execs ran before the flip; every exec from
    # the egress proof on -- staging, the lens hold, the model session's
    # bridge calls -- ran under verified deny-all.
    assert denies[:2] == [False, False]
    assert denies[2:] and all(denies[2:])
    (lens,) = result.lenses
    assert lens.index == 1


# ------------------------------------------------- the per-lens chain


def test_the_per_lens_chain_setup_then_probe_then_a_real_run(tmp_path):
    """The offline chain the shared checkpoint's retirement left (D95's
    2026-11-26 update): every lens's own runner runs the repo's declared
    install with egress still open, the deny-all flip is set and verified,
    the staging probe finds the pytest-capable interpreter, and
    `run_tests` returns a real run -- exit 0 with pytest's own summary
    counts -- never the tool-missing gap."""
    sprites = FakeSprites(
        rules=(
            ExecRule("pip install", "", 0),
            ExecRule(
                "atlas-git",
                (
                    "atlas-git:/usr/bin/git\ngit version 2.43.0\n"
                    "atlas-pytest:/usr/bin/python3:3.12.3\n"
                    "atlas-shim:/usr/bin/python3:3.12.3\n"
                ),
                0,
            ),
            ExecRule(
                "atlas-staged",
                f"atlas-staged:base:{'b' * 40}\natlas-staged:head:{'c' * 40}\n",
                0,
            ),
            ExecRule("atlas-collect", "atlas-collect:0:", 0),
            ExecRule(
                "__ATLAS_RUN__",
                staged_reply() + framed(0, b"1 passed in 0.01s\n"),
                0,
            ),
        )
    )
    results = []

    def body(bridge):
        assert bridge.staged.pytest is not None, (
            "the probe must find the interpreter the setup installed"
        )
        results.append(bridge.call("run_tests", {}))
        return "done"

    report = run_bridge(
        sprites,
        MemoryLedger(),
        SourceTrees(
            source_tarball(
                {
                    "calc.py": b"def total(xs):\n    return sum(xs)\n",
                    "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
                }
            ),
            source_tarball(
                {
                    "calc.py": b"def total(xs):\n    return sum(xs)\n",
                    "test_calc.py": b"from calc import total\n\ndef test_total():\n    assert total([1]) == 1\n",
                }
            ),
            OLD,
            HEAD,
        ),
        body,
        redactor=Redactor(),
        changed=frozenset({"calc.py"}),
        name=NAME,
        deadline_s=300.0,
        clock=FakeClock(),
        root=str(tmp_path / "bridge"),
        setup=SetupSpec((("pip", "install", "pytest"),)),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    (run_tests,) = results
    assert run_tests.status is Status.OK
    (record,) = run_tests.runs
    assert record.exit == 0
    assert record.summary.render() == "1 passed"
    # The order the chain rests on: the setup exec ran while egress was
    # still allowed; the staging probe's and the test run's execs ran
    # under verified deny-all, after the setup. No second runner and no
    # checkpoint: the fake saw one sprite whose execs carry this whole
    # chain, in this order.
    scripts = _scripts(sprites)
    setup_index = next(i for i, script in enumerate(scripts) if "pip install" in script)
    probe_index = next(i for i, script in enumerate(scripts) if "atlas-git" in script)
    run_index = next(i for i, script in enumerate(scripts) if "__ATLAS_RUN__" in script)
    assert setup_index < probe_index < run_index
    denied = [flagged for _name, flagged in sprites.policy_deny_named]
    assert denied[setup_index] is False
    assert denied[probe_index] and denied[run_index]
    assert all(flagged for flagged in denied[setup_index + 1 :])
    assert [op for op, *_rest in sprites.calls].count("create") == 1


# ------------------------------------------------- the setup files


def test_a_files_line_parses_beside_the_commands_line():
    read = parse_setup_commands(
        "review_setup_commands: {python} -m pip install --no-user -r requirements.txt\n"
        "review_setup_files: requirements.txt\n"
    )
    assert read.commands == (
        ("{python}", "-m", "pip", "install", "--no-user", "-r", "requirements.txt"),
    )
    assert read.files == ("requirements.txt",)
    assert read.notes == ()


def test_a_files_line_alone_is_unusable_and_names_its_key():
    read = parse_setup_commands("review_setup_files: requirements.txt\n")
    assert read.commands == ()
    assert read.files == ()
    assert len(read.notes) == 1
    assert "review_setup_files:" in read.notes[0]


def test_an_unusable_files_line_fails_the_whole_spec_open():
    commands = "review_setup_commands: {python} -m pip install pytest\n"
    for files in (
        "review_setup_files:\n",
        "review_setup_files: /etc/passwd\n",
        "review_setup_files: ../secrets.txt\n",
        "review_setup_files: a.txt, a.txt\n",
        "review_setup_files: a\\\\b.txt\n",
        "review_setup_files: requirements.txt\nreview_setup_files: requirements.txt\n",
    ):
        raw = commands + files
        read = parse_setup_commands(raw)
        assert read.commands == (), raw
        assert read.files == (), raw
        assert read.notes and "review_setup_files:" in read.notes[0], raw


def test_the_setup_files_key_draws_no_unsupported_note_in_the_merge_base_read():
    """The merge-base read's unsupported scan matches every unfenced
    `review_*:` line, so a known key missing from `_KNOWN_KEYS` draws a
    false 'unsupported key' note on this repo's own REVIEW.md on every
    read. Goes through `read_repo_config`, the scan's own path -- the
    round-4 review of #843: the first version of this test called
    `parse_setup_commands`, which never produces unsupported notes, and
    so passed whatever `_KNOWN_KEYS` held."""
    tarball = source_tarball(
        {
            "REVIEW.md": (
                b"# policy\n\nreview_setup_commands: make deps\n"
                b"review_setup_files: requirements.txt\n"
            )
        },
        top="example-app",
    )
    assert read_repo_config(tarball).unsupported_notes == ()


def test_the_cli_glue_fetches_the_declared_files_from_the_same_branch():
    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        files={
            "REVIEW.md": (
                b"# policy\n\n"
                b"review_setup_commands: {python} -m pip install --no-user -r requirements.txt\n"
                b"review_setup_files: requirements.txt\n"
            ),
            "requirements.txt": b"pytest==8.0.0\n",
        },
    )
    spec, notes = _setup_commands(github, EVENT)
    assert spec is not None
    assert spec.files["requirements.txt"] == b"pytest==8.0.0\n"
    assert notes == ()
    assert github.calls == [
        ("get_repository", EVENT.repo),
        ("get_file", EVENT.repo, "main", "REVIEW.md"),
        ("get_file", EVENT.repo, "main", "requirements.txt"),
    ]


def test_a_declared_file_the_branch_lacks_leaves_no_setup_with_its_note():
    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        files={
            "REVIEW.md": (
                b"review_setup_commands: {python} -m pip install --no-user -r requirements.txt\n"
                b"review_setup_files: requirements.txt\n"
            ),
        },
    )
    spec, notes = _setup_commands(github, EVENT)
    assert spec is None
    assert len(notes) == 1
    assert "requirements.txt" in notes[0]
    assert "no setup phase runs" in notes[0]


def test_a_declared_file_over_its_bound_leaves_no_setup_with_its_note():
    github = FakeFetchGitHub(
        repository={"default_branch": "main"},
        files={
            "REVIEW.md": (
                b"review_setup_commands: {python} -m pip install --no-user -r requirements.txt\n"
                b"review_setup_files: requirements.txt\n"
            ),
            "requirements.txt": ResponseTooLargeError("over"),
        },
    )
    spec, notes = _setup_commands(github, EVENT)
    assert spec is None
    assert notes and "no setup phase runs" in notes[0]


def test_the_setup_phase_uploads_the_declared_files_before_the_commands():
    """The files the spec declares are in the setup directory under their
    own names before the first command execs: a relative
    `-r requirements.txt` resolves against them, and the bytes are the
    default branch's, uploaded before the deny-all flip like the
    commands themselves."""
    api = FakeSprites(rules=DENY_EGRESS)
    report = run_setup(
        api,
        SetupSpec((SETUP_ECHO,), {"requirements.txt": b"pytest==8.0.0\n"}),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    uploads = [c for c in api.calls if c[0] == "exec" and "requirements.txt" in c[2]]
    assert len(uploads) == 1
    script = uploads[0][2]
    # The neutral directory is the run's own (the runner name suffixes
    # it): concurrent local runners do not race the setup files'
    # uploads on one shared path.
    assert f"cat > /tmp/atlas-neutral-{NAME}/requirements.txt" in script
    command_execs = [c for c in api.calls if c[0] == "exec" and SETUP_ECHO[-1] in c[2]]
    assert len(command_execs) == 1
    # The upload exec sits between the interpreter resolution and the
    # setup command, all before the flip.
    assert api.calls.index(uploads[0]) < api.calls.index(command_execs[0])
    sequence = ops(api)
    flip = sequence.index("set_network_policy")
    execs_before = [i for i, c in enumerate(sequence) if c == "exec" and i < flip]
    assert len(execs_before) == 3


def test_a_nested_setup_file_gets_its_parent_directory_created():
    """The file-name grammar admits a nested path (`requirements/dev.txt`);
    the upload's own script creates the parent directory first, so a
    nested declared file lands where the command's relative path expects
    it instead of failing the setup phase on a missing directory."""
    api = FakeSprites(rules=DENY_EGRESS)
    report = run_setup(
        api,
        SetupSpec((SETUP_ECHO,), {"requirements/dev.txt": b"pytest==8.0.0\n"}),
    )
    assert report.status is RunnerStatus.COMPLETED, report.note
    uploads = [
        c for c in api.calls if c[0] == "exec" and "requirements/dev.txt" in c[2]
    ]
    assert len(uploads) == 1
    assert f"mkdir -p /tmp/atlas-neutral-{NAME}/requirements" in uploads[0][2], uploads[
        0
    ][2]
