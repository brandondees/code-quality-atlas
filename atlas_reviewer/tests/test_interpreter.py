# SPDX-License-Identifier: MIT
"""D29: tools run a Python resolved by absolute path before unpack, never
the image's pyenv shim, which picks its version from the PR's
`.python-version`; and the probe's diagnostics test that hypothesis."""

import os
import shutil
import subprocess
import time

import pytest

from atlas_reviewer.domain import CleanupStatus, RunnerStatus
from atlas_reviewer.fakes import PYENV_PYTHON, ExecRule, FakeSprites, MemoryLedger
from atlas_reviewer.interpreter import (
    CANDIDATE_BOUND_S,
    NEUTRAL_DIR,
    PYENV_VERSIONS,
    SYSTEM_PYTHON,
    TrustedPython,
    choose_python,
    resolve_script,
    shim_script,
    summarize,
    with_python,
)
from atlas_reviewer.ports import StreamTimeoutError
from atlas_reviewer.runner import (
    DEFAULT_TOOLS,
    MINIMAL_ENV,
    TRIVIAL_TOOL,
    RunnerJob,
    ToolAbsent,
    ToolRan,
    ToolSpec,
    exec_argv,
    run_disposable,
    strip_start,
)
from atlas_reviewer.telemetry import Telemetry

from .helpers import FakeClock

NAME = "cqa-rev-20261107-120000-abc123"
RULES = (
    ExecRule("tar -xzf", "", 0),
    ExecRule("-I --version", "Python 3.13.7", 0),
    ExecRule("compileall", "", 0),
    ExecRule("echo posix-sh", "posix-sh", 0),
    ExecRule("find .", "3", 0),
)


def review(api, tools=DEFAULT_TOOLS, diagnose=False):
    telemetry = Telemetry(FakeClock())
    outcome = run_disposable(
        api, MemoryLedger(), RunnerJob(b"tarball", tools, diagnose=diagnose),
        name=NAME, deadline_s=600.0, clock=FakeClock(), telemetry=telemetry,
    )  # fmt: skip
    return outcome, telemetry.events


def scripts(api):
    """The command inside each exec's start/stdin/exit-marker wrapper."""
    return [
        c[2].split("{ ", 1)[1].rsplit("\n}", 1)[0] for c in api.calls if c[0] == "exec"
    ]


def pyenv(version):
    return f"{PYENV_VERSIONS}/{version}/bin/python3"


# --- choosing the interpreter ----------------------------------------------


def lines(*pairs):
    return "\n".join(f"atlas-python:{p}:{v}" for p, v in pairs)


def test_the_newest_pyenv_version_wins_by_number_not_by_text():
    text = lines(
        (pyenv("3.9.18"), "3.9.18"),
        (pyenv("3.13.7"), "3.13.7"),
        (pyenv("3.12.10"), "3.12.10"),
        (SYSTEM_PYTHON, "3.14.0"),
    )
    assert choose_python(text) == TrustedPython(pyenv("3.13.7"), "3.13.7")


def test_the_system_python_is_the_fallback_and_none_is_unknown():
    assert choose_python(lines((SYSTEM_PYTHON, "3.12.3"))) == TrustedPython(
        SYSTEM_PYTHON, "3.12.3"
    )
    assert choose_python("") is None
    assert choose_python("sh: 1: no such file") is None


@pytest.mark.parametrize(
    "path",
    [
        "/.sprite/bin/python3",
        "/work/.venv/bin/python3",
        f"{PYENV_VERSIONS}/../../../../work/bin/python3",
        f"{PYENV_VERSIONS}/../bin/python3",
        f"{PYENV_VERSIONS}/3.13.7/bin/python3.13",
        "/usr/local/bin/python3",
        "/usr/bin/python3x",
    ],
)
def test_only_the_two_trusted_path_shapes_are_accepted(path):
    assert choose_python(lines((path, "3.13.7"))) is None


def test_a_malformed_version_line_is_ignored():
    text = f"atlas-python:{pyenv('3.13.7')}:3.13\natlas-python:{SYSTEM_PYTHON}:x.y.z"
    assert choose_python(text) is None


def test_the_interpreter_is_substituted_quoted_and_literally():
    odd = TrustedPython(pyenv("3.13.7+local"), "3.13.7")
    assert with_python("{python} -I -m x {python}", odd) == (
        f"{odd.path} -I -m x {odd.path}"
    )
    assert with_python("{python} '{other}'", odd) == f"{odd.path} '{{other}}'"


# --- a python tool can only name the resolved interpreter -------------------


@pytest.mark.parametrize(
    ("binary", "version_cmd", "run_cmd"),
    [
        ("python3", "python3 --version", "python3 -m compileall ."),
        ("python3", "{python} --version", "python3 -m compileall ."),
        ("ruff", "{python} --version", "{python} -m ruff check ."),
    ],
)
def test_tool_specs_must_route_python_through_the_placeholder(
    binary, version_cmd, run_cmd
):
    with pytest.raises(ValueError, match="must use \\{python\\}"):
        ToolSpec("t", binary, version_cmd, run_cmd)


@pytest.mark.parametrize(
    ("version_cmd", "run_cmd"),
    [
        ("{python} --version", "{python} -I -m compileall ."),
        ("{python} -I --version", "{python} -m compileall ."),
        ("{python} -I --version", "{python} -m -I compileall ."),
    ],
)
def test_python_tools_must_run_isolated_in_both_commands(version_cmd, run_cmd):
    with pytest.raises(ValueError, match="followed by -I"):
        ToolSpec("t", "python3", version_cmd, run_cmd)
    assert ToolSpec("t", "python3", "{python} -I --version", "{python} -Im x").run_cmd


def test_the_default_tool_runs_isolated_by_placeholder():
    (tool,) = DEFAULT_TOOLS
    assert tool.needs_python
    assert tool.version_cmd == "{python} -I --version"
    assert tool.run_cmd == "{python} -I -m compileall -q ."


# --- the runner -------------------------------------------------------------


def test_the_interpreter_is_resolved_before_any_pr_byte_reaches_the_sprite():
    api = FakeSprites(rules=RULES)
    outcome, events = review(api)
    assert outcome.report.status is RunnerStatus.COMPLETED
    sent = scripts(api)
    resolve = next(i for i, s in enumerate(sent) if "atlas-python:" in s)
    upload = next(i for i, s in enumerate(sent) if "cat > /tmp/atlas-source" in s)
    assert resolve < upload
    assert f"cd {NEUTRAL_DIR}" in sent[resolve]
    assert api.stdin_seen[resolve] == b""
    assert outcome.python == TrustedPython(PYENV_PYTHON, "3.13.7")
    interp = next(e for e in events if e.phase == "interpreter")
    assert interp.fields["python"] == PYENV_PYTHON
    assert interp.fields["python_version"] == "3.13.7"


def test_python_tools_run_the_absolute_interpreter_isolated_never_a_shim():
    api = FakeSprites(rules=RULES)
    outcome, _ = review(api)
    (result,) = outcome.results
    assert isinstance(result, ToolRan)
    assert result.version == "Python 3.13.7"
    tool_scripts = [s for s in scripts(api) if s.startswith("cd /work &&")]
    assert tool_scripts == [
        f"cd /work && {PYENV_PYTHON} -I --version",
        f"cd /work && timeout --kill-after=5 120 {PYENV_PYTHON} -I -m compileall -q .",
    ]


def test_every_exec_of_a_review_runs_under_the_minimal_environment():
    api = FakeSprites(rules=RULES)
    _, events = review(api, (*DEFAULT_TOOLS, TRIVIAL_TOOL))
    prefix = ("/usr/bin/env", "-i", *MINIMAL_ENV, "/bin/sh", "-c")
    assert all(argv[:7] == prefix for argv in api.argv_seen)
    assert "/.sprite" not in " ".join(MINIMAL_ENV)
    assert {e.fields["env"] for e in events if e.phase == "exec"} == {"minimal"}


def test_a_python_tool_is_not_run_without_a_trusted_interpreter():
    api = FakeSprites(rules=RULES, pythons=(("/.sprite/bin/python3", "3.12.0"),))
    outcome, events = review(api)
    (result,) = outcome.results
    assert isinstance(result, ToolAbsent)
    assert result.detail == "no trusted Python interpreter was resolved"
    assert outcome.python is None
    assert not any(s.startswith("cd /work &&") for s in scripts(api))
    assert next(e for e in events if e.phase == "interpreter").fields == {
        "python": "none found"
    }
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_a_run_without_python_tools_or_diagnostics_does_not_resolve_one():
    api = FakeSprites(rules=RULES)
    outcome, _ = review(api, (TRIVIAL_TOOL,))
    assert outcome.python is None
    assert not any("atlas-python:" in s for s in scripts(api))
    assert outcome.diagnostics == ()


def test_a_review_never_runs_the_probe_diagnostics():
    api = FakeSprites(rules=RULES)
    outcome, events = review(api)
    assert outcome.diagnostics == ()
    assert "diagnostic" not in {e.phase for e in events}
    assert not any(argv[0] == "/bin/sh" for argv in api.argv_seen)


# --- the probe's diagnostics ------------------------------------------------


def test_the_diagnostics_record_the_shim_versions_and_the_bare_python3_last():
    api = FakeSprites(
        rules=(
            *RULES,
            ExecRule("readlink -f", "atlas-diag:target:/.sprite/bin/python3", 0),
            ExecRule("ls -1", "3.13.7\n3.11.9", 0),
            ExecRule("PYENV_VERSION=", "Python 3.13.7", 0),
            ExecRule("timeout -k 2 15 python3", "", 124),
        )
    )
    outcome, events = review(api, diagnose=True)
    assert outcome.report.status is RunnerStatus.COMPLETED
    got = [(d.name, d.exit_code, d.detail) for d in outcome.diagnostics]
    assert got == [
        ("shim", 0, "target=/.sprite/bin/python3"),
        ("pyenv versions", 0, "3.13.7,3.11.9"),
        ("trusted python after unpack", 0, "Python 3.13.7"),
        ("shim with PYENV_VERSION", 0, "Python 3.13.7"),
        ("bare python3 in the checkout", 124, "(no output)"),
    ]
    assert outcome.diagnostics[-1].expectation.startswith("expected-may-hang")
    sent = scripts(api)
    assert sent[-1] == ("cd /work && /usr/bin/timeout -k 2 15 python3 --version")
    assert sent[-2] == (
        "cd /work && PYENV_VERSION=3.13.7 "
        "/usr/bin/timeout -k 2 15 /.sprite/bin/python3 --version"
    )
    assert [a[0] for a in api.argv_seen][-2:] == ["/bin/sh", "/bin/sh"]
    assert api.timeouts_seen[-1] == 25.0
    recorded = [e for e in events if e.phase == "diagnostic"]
    assert [e.step for e in recorded] == [d.name for d in outcome.diagnostics]
    assert recorded[-1].fields["exit_status"] == 124
    shim_exec = next(e for e in events if e.step == "shim" and e.phase == "exec")
    assert shim_exec.fields["env"] == "minimal"


def test_shim_and_version_diagnostics_run_before_the_upload():
    api = FakeSprites(rules=RULES)
    review(api, diagnose=True)
    sent = scripts(api)
    upload = next(i for i, s in enumerate(sent) if "cat > /tmp/atlas-source" in s)
    assert any("readlink -f" in s for s in sent[:upload])
    assert any("ls -1" in s for s in sent[:upload])


def test_a_hanging_diagnostic_is_recorded_and_the_sprite_still_destroyed():
    class BareHangs(FakeSprites):
        def exec(self, name, argv, stdin, timeout_s, first_byte_s=None):
            if "15 python3 --version" in argv[-1]:
                raise StreamTimeoutError(
                    "POST x: response incomplete after 17 byte(s) within 25s",
                    b"\x01__ATLAS_START__\n",
                )
            return super().exec(name, argv, stdin, timeout_s, first_byte_s)

    outcome, _ = review(BareHangs(rules=RULES), diagnose=True)
    assert outcome.report.status is RunnerStatus.COMPLETED
    bare = outcome.diagnostics[-1]
    assert bare.exit_code is None
    assert bare.detail.startswith(
        "exec failed: exec / bare python3 in the checkout failed after 0.0s"
    )
    assert "output stopped before the exit marker after 17 byte(s)" in bare.detail
    assert outcome.report.cleanup is CleanupStatus.DESTROYED_VERIFIED


def test_without_an_interpreter_only_the_bare_python3_check_runs_after_unpack():
    api = FakeSprites(rules=RULES, pythons=())
    outcome, _ = review(api, diagnose=True)
    assert [d.name for d in outcome.diagnostics] == [
        "shim",
        "pyenv versions",
        "bare python3 in the checkout",
    ]


def test_guest_output_is_reduced_to_one_printable_line():
    assert summarize("atlas-diag:shebang:#!/usr/bin/env bash\x1b[31m\n") == (
        "shebang=#!/usr/bin/env bash [31m"
    )
    assert summarize("x" * 500) == "x" * 200
    assert summarize("  \n") == "(no output)"


# --- the scripts, run for real in a local shell (no Sprite, no network) -----

needs_posix = pytest.mark.skipif(
    not (os.path.exists("/usr/bin/env") and os.path.exists("/bin/sh")),
    reason="needs a POSIX /usr/bin/env and /bin/sh",
)


def sh(script, stdin=b""):
    done = subprocess.run(
        list(exec_argv(script, len(stdin))),
        input=stdin,
        capture_output=True,
        timeout=30,
        check=True,
    )
    return strip_start(done.stdout.decode())


@needs_posix
def test_the_wrapper_really_runs_with_only_the_minimal_environment(monkeypatch):
    monkeypatch.setenv("PYENV_VERSION", "3.12")
    monkeypatch.setenv("PATH", f"/.sprite/bin:{os.environ['PATH']}")
    seen = sh("env").splitlines()[:-1]
    assert set(MINIMAL_ENV) <= set(seen)
    shell_own = {"PWD", "OLDPWD", "SHLVL", "_"}
    assert {line.split("=", 1)[0] for line in seen} - shell_own == {
        "PATH",
        "HOME",
        "LANG",
    }


@needs_posix
@pytest.mark.skipif(not os.path.exists("/usr/bin/timeout"), reason="no timeout")
def test_a_hung_candidate_is_bounded_and_later_ones_are_still_found(tmp_path):
    hung = tmp_path / "hung"
    hung.write_text("#!/bin/sh\nsleep 30\n")
    hung.chmod(0o755)
    script = resolve_script().replace(
        f"{PYENV_VERSIONS}/*/bin/python3", f"{hung} {PYENV_VERSIONS}/*/bin/python3"
    )
    assert f"/usr/bin/timeout -k 2 {CANDIDATE_BOUND_S} " in script
    started = time.monotonic()
    out = sh(script)
    assert time.monotonic() - started < CANDIDATE_BOUND_S + 4
    if os.path.exists(SYSTEM_PYTHON):
        assert f"atlas-python:{SYSTEM_PYTHON}:" in out


@needs_posix
@pytest.mark.skipif(not os.path.exists(SYSTEM_PYTHON), reason="no /usr/bin/python3")
@pytest.mark.skipif(not os.path.exists("/usr/bin/timeout"), reason="no timeout")
def test_the_resolve_script_really_finds_the_system_python():
    """Every candidate query runs under /usr/bin/timeout; without it each
    one fails and nothing is found."""
    out = sh(resolve_script())
    python = choose_python(out)
    assert python is not None
    if not os.path.isdir(PYENV_VERSIONS):
        assert python.path == SYSTEM_PYTHON
    assert python.version.count(".") == 2


@needs_posix
@pytest.mark.skipif(shutil.which("grep") is None, reason="no grep")
def test_the_shim_script_reads_the_shim_as_text_without_running_it(tmp_path):
    shim = tmp_path / "python3"
    marker = tmp_path / "ran"
    shim.write_text(
        f'#!/usr/bin/env bash\ntouch {marker}\nexec "/pyenv/libexec/pyenv" exec "$@"\n'
    )
    shim.chmod(0o755)
    out = summarize(sh(shim_script(str(shim))))
    assert f"target={shim}" in out
    assert "shebang=#!/usr/bin/env bash" in out
    assert 'exec_line=exec "/pyenv/libexec/pyenv" exec "$@"' in out
    assert not marker.exists()
    assert summarize(sh(shim_script(str(tmp_path / "gone")))) == (
        f"absent={tmp_path / 'gone'}"
    )
