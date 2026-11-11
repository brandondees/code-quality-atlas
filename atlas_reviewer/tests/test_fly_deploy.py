# SPDX-License-Identifier: MIT
"""The Fly one-off deploy config stays a non-service, non-root, hashed image.

`fly.toml` and the Dockerfile are parsed. The entrypoint is run against a
stub CLI. The runbook checks parse each fenced command, so a comment or a
``timeout`` / ``env`` prefix cannot hide the ``fly`` invocation. They
confirm a command or warning is written down, not that Fly accepts it.
Nothing here builds the image or calls Fly.
"""

import os
import re
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import NamedTuple

import pytest

from atlas_reviewer import cli
from atlas_reviewer.domain import CleanupStatus
from atlas_reviewer.notes import CLEANUP_SENTENCE

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT_PATH = ROOT / "atlas_reviewer" / "docker-entrypoint.sh"
ENTRYPOINT = ENTRYPOINT_PATH.read_text(encoding="utf-8")
RUNBOOK = (ROOT / "atlas_reviewer" / "deploy-fly.md").read_text(encoding="utf-8")
README = (ROOT / "atlas_reviewer" / "README.md").read_text(encoding="utf-8")

SECRET_NAMES = (
    cli.ENV_APP_ID,
    cli.ENV_APP_KEY,
    cli.ENV_INSTALLATION_ID,
    cli.ENV_SPRITES_TOKEN,
    cli.ENV_OPENROUTER_KEY,
)
APP_NAME = "atlas-reviewer"
SECRET_FILE_PATTERNS = (".env", "*.env", "secrets.env", "*.pem")


def dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    joined, pending = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        joined.append(pending + line)
        pending = ""
    assert not pending, "Dockerfile ends inside a continuation"
    pairs = []
    for line in joined:
        keyword, _, rest = line.partition(" ")
        pairs.append((keyword.upper(), " ".join(rest.split())))
    return pairs


INSTRUCTIONS = dockerfile_instructions(DOCKERFILE)


def args_of(keyword: str) -> list[str]:
    return [rest for kw, rest in INSTRUCTIONS if kw == keyword]


def test_fly_toml_names_the_app_and_publishes_nothing():
    config = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))
    assert config == {
        "app": APP_NAME,
        "primary_region": "iad",
        "build": {"dockerfile": "Dockerfile"},
    }


def test_image_is_pinned_python_312_slim_installed_with_hashes_as_non_root():
    assert args_of("FROM") == [
        (
            "python:3.12.16-slim-bookworm"
            "@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df"
        )
    ]
    installs = [r for r in args_of("RUN") if r.startswith("pip install")]
    assert installs == [
        (
            "pip install --require-hashes --only-binary=:all: "
            "-r /tmp/requirements.txt && rm /tmp/requirements.txt"
        )
    ]
    assert "useradd --create-home --uid 10001 --shell /bin/false atlas" in args_of(
        "RUN"
    )
    assert args_of("USER") == ["atlas"]
    keywords = [kw for kw, _ in INSTRUCTIONS]
    last_run = max(i for i, kw in enumerate(keywords) if kw == "RUN")
    assert keywords.index("USER") > last_run
    assert args_of("ENTRYPOINT") == ['["/usr/local/bin/atlas-reviewer"]']
    for keyword in ("EXPOSE", "ARG", "VOLUME", "HEALTHCHECK", "ADD"):
        assert keyword not in keywords
    for name in SECRET_NAMES:
        assert name not in DOCKERFILE


def test_image_copies_exactly_the_files_the_controller_reads():
    sources = [rest.split()[0] for rest in args_of("COPY")]
    assert sources == [
        "requirements.txt",
        "atlas_reviewer/*.py",
        "collapsed/skills/reviewing-a-change/SKILL.md",
        "collapsed/skills/reviewing-a-change/reference/lenses",
        "skills/choosing-review-lenses/SKILL.md",
        "atlas_reviewer/docker-entrypoint.sh",
    ]
    assert (ROOT / "collapsed/skills/reviewing-a-change/SKILL.md").is_file()
    assert (ROOT / "skills/choosing-review-lenses/SKILL.md").is_file()
    bodies = list(
        (ROOT / "collapsed/skills/reviewing-a-change/reference/lenses").glob(
            "*/body.md"
        )
    )
    assert len(bodies) >= 4


def test_secret_files_stay_out_of_git_and_the_build_context():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in SECRET_FILE_PATTERNS:
        assert pattern in gitignore
        assert f"**/{pattern}" in dockerignore


def test_entrypoint_does_not_print_the_environment():
    assert ENTRYPOINT.startswith("#!/bin/sh\n")
    assert "set -eu" in ENTRYPOINT
    for name in SECRET_NAMES:
        assert name not in ENTRYPOINT
    code = "\n".join(
        line for line in ENTRYPOINT.splitlines() if not line.lstrip().startswith("#")
    )
    assert not re.search(
        r"\b(?:printenv|env|export|set)\b", code.replace("set -eu", "")
    )
    assert '$@" >' not in code
    subprocess.run(["sh", "-n", str(ENTRYPOINT_PATH)], check=True)


STUB_CLI = """\
import os, pathlib, signal, sys, time
from atlas_reviewer.stops import install_interrupts

marker = pathlib.Path(os.environ["STUB_MARKER"])
if sys.argv[1] == "boot":
    marker.write_text("booting")
    time.sleep(30)
install_interrupts()
received = marker.with_name("signals")
for sig in (signal.SIGINT, signal.SIGTERM):
    def record(signum, frame, installed=signal.getsignal(sig)):
        with received.open("a") as f:
            f.write(signal.Signals(signum).name + "\\n")
        installed(signum, frame)
    signal.signal(sig, record)
marker.write_text(" ".join(sys.argv[1:]))
if sys.argv[1] == "exit":
    sys.exit(int(sys.argv[2]))
try:
    time.sleep(30)
finally:
    marker.write_text("finally started")
    time.sleep(1 if sys.argv[1] == "slow-cleanup" else 0)
    marker.write_text("finally ran")
"""


@pytest.fixture
def entrypoint(tmp_path):
    """The real entrypoint with /home/atlas moved under tmp_path, and a
    `python` on PATH that runs a stub CLI instead of the controller."""
    home = tmp_path / "home"
    home.mkdir()
    script = tmp_path / "entrypoint.sh"
    script.write_text(ENTRYPOINT.replace("/home/atlas", str(home)))
    stub = tmp_path / "stub_cli.py"
    stub.write_text(STUB_CLI)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "python"
    wrapper.write_text(
        f'#!/bin/sh\n[ "$1 $2" = "-m atlas_reviewer" ] || exit 99\nshift 2\n'
        f'exec "{sys.executable}" "{stub}" "$@"\n'
    )
    wrapper.chmod(0o755)
    marker = tmp_path / "marker"

    def start(*args, **env):
        environ = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": str(ROOT),
            "STUB_MARKER": str(marker),
            **env,
        }
        return subprocess.Popen(
            ["sh", str(script), *args],
            env=environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    return start, home, marker


def wait_for(path, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def test_without_a_hold_the_entrypoint_execs_the_cli_and_writes_the_event(entrypoint):
    start, home, marker = entrypoint
    proc = start("exit", "4", ATLAS_EVENT_JSON='{"pr_number": 1}')
    assert proc.wait(timeout=10) == 4
    assert marker.read_text() == "exit 4"
    event = home / "event.json"
    assert event.read_text() == '{"pr_number": 1}\n'
    assert event.stat().st_mode & 0o077 == 0
    assert not (home / "out").exists()


def test_a_hold_records_the_exit_code_and_ends_on_sigint_with_that_code(entrypoint):
    start, home, _ = entrypoint
    proc = start("exit", "4", ATLAS_HOLD_SECONDS="30")
    code_file = home / "out" / "exit-code"
    wait_for(code_file)
    assert code_file.read_text() == "4\n"
    time.sleep(0.2)
    assert proc.poll() is None, "the Machine should still be held"
    began = time.monotonic()
    proc.send_signal(signal.SIGINT)
    assert proc.wait(timeout=10) == 4
    assert time.monotonic() - began < 5


def test_a_hold_of_zero_exits_right_after_the_cli(entrypoint):
    start, home, _ = entrypoint
    proc = start("exit", "0", ATLAS_HOLD_SECONDS="0")
    assert proc.wait(timeout=10) == 0
    assert (home / "out" / "exit-code").read_text() == "0\n"
    assert "review exited 0; holding 0s" in proc.stderr.read()


def wait_for_text(path, text, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not (path.exists() and path.read_text() == text):
        assert time.monotonic() < deadline, f"{path} never read {text!r}"
        time.sleep(0.02)


def test_a_stop_before_the_cli_is_ready_still_ends_it_without_a_hold(entrypoint):
    """The CLI has started but not installed its handlers, so the
    forwarded SIGTERM ends it with the default action."""
    start, home, marker = entrypoint
    proc = start("boot", ATLAS_HOLD_SECONDS="30")
    wait_for_text(marker, "booting")
    proc.send_signal(signal.SIGINT)
    assert proc.wait(timeout=10) == 128 + signal.SIGTERM
    assert (home / "out" / "exit-code").read_text() == f"{128 + signal.SIGTERM}\n"
    assert "holding" not in proc.stderr.read()


def test_sigint_during_the_review_reaches_the_cli_finally_and_skips_the_hold(
    entrypoint,
):
    """The entrypoint forwards the stop as SIGTERM, because `sh` starts
    the CLI with SIGINT ignored; the CLI unwinds and exits as for SIGINT."""
    start, home, marker = entrypoint
    proc = start("wait", ATLAS_HOLD_SECONDS="30")
    wait_for_text(marker, "wait")
    proc.send_signal(signal.SIGINT)
    status = proc.wait(timeout=10)
    assert marker.read_text() == "finally ran"
    assert marker.with_name("signals").read_text() == "SIGTERM\n"
    assert status == 128 + signal.SIGINT
    assert (home / "out" / "exit-code").read_text() == f"{status}\n"
    assert "holding" not in proc.stderr.read()


def test_a_second_stop_cannot_cut_the_cli_cleanup_short(entrypoint):
    start, home, marker = entrypoint
    proc = start("slow-cleanup", ATLAS_HOLD_SECONDS="30")
    wait_for_text(marker, "slow-cleanup")
    proc.send_signal(signal.SIGTERM)
    wait_for_text(marker, "finally started")
    proc.send_signal(signal.SIGTERM)
    status = proc.wait(timeout=10)
    assert marker.read_text() == "finally ran"
    assert marker.with_name("signals").read_text() == "SIGTERM\n"
    assert status == 128 + signal.SIGINT
    assert (home / "out" / "exit-code").read_text() == f"{status}\n"


@pytest.mark.parametrize("hold", ["ten", "-1", "1.5"])
def test_a_hold_that_is_not_whole_seconds_is_refused_before_the_cli(entrypoint, hold):
    start, _, marker = entrypoint
    proc = start("exit", "0", ATLAS_HOLD_SECONDS=hold)
    assert proc.wait(timeout=10) == 2
    assert not marker.exists()


def test_the_cli_unwinds_on_sigint_even_when_started_with_it_ignored():
    code = (
        "import os, signal, time\n"
        "from atlas_reviewer.stops import install_interrupts\n"
        "install_interrupts()\n"
        "try:\n"
        "    os.kill(os.getpid(), signal.SIGINT)\n"
        "    time.sleep(10)\n"
        "finally:\n"
        "    print('finally ran', flush=True)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.stdout == "finally ran\n"
    assert proc.returncode == -signal.SIGINT


def shell_blocks(text: str) -> list[str]:
    return re.findall(r"```sh\n(.*?)```", text, flags=re.DOTALL)


class ShellCommand(NamedTuple):
    """One command from a fenced block.

    ``prefix`` holds a leading ``timeout <seconds>``, ``env``, or
    ``NAME=value``. ``program`` is the argv those wrappers run. A full-line
    comment is not a command.
    """

    prefix: tuple[str, ...]
    program: tuple[str, ...]


_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _peel_wrappers(words: list[str]) -> ShellCommand:
    index = 0
    while index < len(words):
        word = words[index]
        if word == "timeout" and index + 1 < len(words) and words[index + 1].isdigit():
            index += 2
            continue
        if word == "env":
            index += 1
            while index < len(words):
                if words[index] == "-u" and index + 1 < len(words):
                    index += 2
                    continue
                if words[index].startswith("-") or _ASSIGNMENT.match(words[index]):
                    index += 1
                    continue
                break
            continue
        if _ASSIGNMENT.match(word):
            index += 1
            continue
        break
    return ShellCommand(tuple(words[:index]), tuple(words[index:]))


def shell_commands(block: str) -> list[ShellCommand]:
    """Commands in one fenced sh block, comments dropped, wrappers kept."""
    lines = []
    for line in block.replace("flyp() {", "").splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(re.sub(r"\s+#.*$", "", line))
    joined = re.sub(r"\\\n\s*", " ", "\n".join(lines))
    commands = []
    for segment in re.split(r"\n|\|\||&&|\||;|\$\(|\(|\)", joined):
        words = segment.split()
        if not words or words[0].startswith("#"):
            continue
        commands.append(_peel_wrappers(words))
    return commands


def fly_invocations(text: str) -> list[ShellCommand]:
    found = []
    for block in shell_blocks(text):
        for command in shell_commands(block):
            if command.program and command.program[0] in ("fly", "flyp"):
                found.append(command)
    return found


def _is_machine_run(command: ShellCommand) -> bool:
    return command.program[:3] in {
        ("fly", "machine", "run"),
        ("flyp", "machine", "run"),
    }


def _assigns_api_token(words: tuple[str, ...]) -> bool:
    return any(word.startswith("FLY_API_TOKEN=") for word in words)


def fly_commands(text: str) -> list[str]:
    return [" ".join(command.program) for command in fly_invocations(text)]


def test_every_runbook_fly_command_names_its_app_or_org():
    commands = fly_commands(RUNBOOK)
    assert len(commands) > 20
    for command in commands:
        if command in ('fly "$@"', f"flyp apps destroy {APP_NAME} --yes"):
            continue
        assert "--app atlas-reviewer" in command or "--org personal" in command, command


def test_only_the_token_mint_and_the_wrapper_call_fly_without_the_org_token():
    invocations = fly_invocations(RUNBOOK)
    for command in invocations:
        assert "env" not in command.prefix, command
        assert not _assigns_api_token(command.prefix + command.program), command
    bare = [" ".join(c.program) for c in invocations if c.program[0] == "fly"]
    mint = (
        "fly tokens create org --org personal --name atlas-reviewer "
        '--expiry 168h > "$SECRETS_DIR/fly-personal.token"'
    )
    runs = [c for c in invocations if _is_machine_run(c)]
    # The held review is the one flyp machine run. Every other machine
    # run is a raw fly command: timeout cannot call the flyp function.
    # An extra `timeout 45 flyp machine run` is a machine run too.
    held = [c for c in runs if c.program[0] == "flyp"]
    one_off = [c for c in runs if c.program[0] == "fly"]
    assert bare == [mint, 'fly "$@"', *[" ".join(c.program) for c in one_off]]
    assert len(held) == 1 and held[0].prefix == ()
    assert "--rm" not in held[0].program and "--detach" not in held[0].program
    assert len(one_off) == 3
    detached = [c for c in one_off if "--detach" in c.program]
    wrapped = [c for c in one_off if c.prefix == ("timeout", "45")]
    assert len(detached) == 1 and len(wrapped) == 2
    assert set(detached + wrapped) == set(one_off)
    assert "timeout" not in detached[0].prefix
    assert "--sequence" in detached[0].program and "review" in detached[0].program
    for command in one_off:
        assert "--rm" in command.program
        assert "--app" in command.program and "atlas-reviewer" in command.program
    # The token reaches fly through the subshell export, not an argv
    # assignment and not an exported personal-token name.
    exports = [
        command.program
        for block in shell_blocks(RUNBOOK)
        for command in shell_commands(block)
        if command.program[:1] == ("export",)
    ]
    assert ("export", 'FLY_API_TOKEN="$FLY_PERSONAL_API_TOKEN"') in [
        (words[0], words[1]) for words in exports if len(words) > 1
    ]
    assert not any(
        word.startswith("FLY_PERSONAL_API_TOKEN") for words in exports for word in words
    )


def test_runbook_creates_the_app_if_missing_before_setting_secrets():
    assert (
        "flyp apps list --org personal --quiet | grep -qx atlas-reviewer ||\n"
        "  flyp apps create atlas-reviewer --org personal"
    ) in RUNBOOK
    assert RUNBOOK.index("## Create the app") < RUNBOOK.index("## Secrets")


def test_runbook_keeps_secrets_files_outside_the_checkout():
    assert 'SECRETS_DIR="$HOME/atlas-secrets"' in RUNBOOK
    assert '>> "$SECRETS_DIR/secrets.env")' in RUNBOOK
    assert (
        'flyp secrets import --stage --app atlas-reviewer < "$SECRETS_DIR/secrets.env"'
        in RUNBOOK
    )
    assert "/path/to/" not in RUNBOOK
    for name in SECRET_NAMES:
        assert name in RUNBOOK
    for forbidden in ("BEGIN PRIVATE KEY", "sk-or-", "ghp_", "github_pat_", "FlyV1"):
        assert forbidden not in RUNBOOK
        assert forbidden not in DOCKERFILE


def block_with(marker: str) -> str:
    (block,) = [b for b in shell_blocks(RUNBOOK) if marker in b]
    return block


def test_the_private_key_append_is_safe_to_run_twice(tmp_path):
    (tmp_path / "github-app.pem").write_text("FAKE-KEY-LINE-1\nFAKE-KEY-LINE-2\n")
    env = {**os.environ, "SECRETS_DIR": str(tmp_path)}
    for _ in range(2):
        subprocess.run(["sh", "-c", block_with("github-app.pem")], env=env, check=True)
    secrets = tmp_path / "secrets.env"
    assert secrets.read_text() == (
        "ATLAS_GITHUB_APP_PRIVATE_KEY=FAKE-KEY-LINE-1\\nFAKE-KEY-LINE-2\\n\n"
    )
    assert secrets.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(("age_h", "warns"), [(1, False), (150, True)])
def test_runbook_warns_before_the_fly_token_expires(tmp_path, age_h, warns):
    (tmp_path / "fly-personal.minted").write_text(
        f"{int(time.time()) - age_h * 3600}\n"
    )
    check = block_with("minted=$(cat")
    proc = subprocess.run(
        ["sh", "-c", check], env={**os.environ, "SECRETS_DIR": str(tmp_path)},
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert ("renew it" in proc.stdout) is warns
    assert 'date +%s > "$SECRETS_DIR/fly-personal.minted"' in RUNBOOK
    assert "To renew, run the mint block again" in RUNBOOK


def test_the_copy_step_survives_a_missing_file():
    copy = block_with("flyp ssh sftp get /home/atlas/out/draft.md")
    for name in ("draft.md", "events.jsonl"):
        assert f'|| echo "no {name} on the Machine"' in copy


def test_an_unverified_cleanup_in_the_draft_sends_the_operator_to_sweep_by_name():
    check = block_with("destroy was NOT verified")
    assert '"$RUN_DIR/draft.md"' in check
    assert RUNBOOK.index(check) < RUNBOOK.index("### Release and destroy the Machine")
    after = RUNBOOK.split(check, 1)[1].split("\n### ", 1)[0]
    assert "sweep --event ... --force-live" in after
    assert "(#recover-a-runner-sprite-by-name)" in after
    assert (
        "destroy was NOT verified" in CLEANUP_SENTENCE[CleanupStatus.DESTROY_UNVERIFIED]
    )


def test_a_review_writes_to_the_machine_disk_and_is_held_not_removed():
    review = block_with("-- review --event")
    assert "--rm" not in review
    for flag in (
        '--name "$NAME"',
        "--restart no",
        "--entrypoint /usr/local/bin/atlas-reviewer",
        '--env ATLAS_EVENT_JSON="$EVENT"',
        "--env ATLAS_HOLD_SECONDS=",
        "--out /home/atlas/out/draft.md",
        "--events /home/atlas/out/events.jsonl",
    ):
        assert flag in review
    assert "--port" not in review
    short = [
        b
        for b in shell_blocks(RUNBOOK)
        if "-- sweep --event" in b or b.rstrip().endswith("-- probe-runner\n)")
    ]
    assert len(short) == 2
    review_seq = block_with("-- probe-runner --sequence review")
    for block in (*short, review_seq):
        runs = [c for c in shell_commands(block) if _is_machine_run(c)]
        assert len(runs) == 1, block
        assert runs[0].program[0] == "fly"
        assert "--rm" in runs[0].program
        assert "--restart" in runs[0].program and "no" in runs[0].program
        assert "env" not in runs[0].prefix
        assert not _assigns_api_token(runs[0].prefix + runs[0].program)
        commands = shell_commands(block)
        assert ("unset", "FLY_ACCESS_TOKEN") in [c.program for c in commands]
        assert ("export", 'FLY_API_TOKEN="$FLY_PERSONAL_API_TOKEN"') in [
            c.program for c in commands
        ]
    for block in short:
        (run,) = [c for c in shell_commands(block) if _is_machine_run(c)]
        assert run.prefix == ("timeout", "45")
        assert "--detach" not in run.program
    (review_run,) = [c for c in shell_commands(review_seq) if _is_machine_run(c)]
    # Any timeout wrapper, not only `timeout 45`. A `timeout 90` in front
    # of this fly would cut off a review sequence that is still working.
    assert "timeout" not in review_run.prefix
    assert "--detach" in review_run.program
    assert "If `MACHINE_ID` is empty, stop" in RUNBOOK
    review_at = RUNBOOK.index("-- probe-runner --sequence review")
    logs_line = 'flyp logs --app atlas-reviewer --machine "$MACHINE_ID" --no-tail'
    logs_at = RUNBOOK.index(logs_line, review_at)
    restage_at = RUNBOOK.index("grep -E", review_at)
    assert review_at < logs_at < restage_at
    assert "Main child exited normally with code: 0" in RUNBOOK[review_at:logs_at]
    assert "flyp secrets list --app atlas-reviewer" in block_with("grep -E")


def test_a_review_is_waited_for_copied_released_and_destroyed_in_that_order():
    steps = [
        "cat /home/atlas/out/exit-code",
        "flyp ssh sftp get /home/atlas/out/draft.md",
        "flyp ssh sftp get /home/atlas/out/events.jsonl",
        "flyp image show --app atlas-reviewer",
        'flyp machine stop "$MACHINE_ID" --app atlas-reviewer\n',
        'flyp machine wait "$MACHINE_ID" --app atlas-reviewer --state stopped',
        'flyp machine destroy "$MACHINE_ID" --app atlas-reviewer\n',
    ]
    positions = [RUNBOOK.index(step) for step in steps]
    assert positions == sorted(positions)
    assert 'RUN_DIR="$HOME/atlas-runs/$NAME"' in RUNBOOK
    assert RUNBOOK.index("flyp machine list --app atlas-reviewer") < RUNBOOK.index(
        "-- review --event"
    )


def test_runbook_has_a_hard_stop_and_recovers_sprites_by_name():
    assert (
        'flyp machine stop "$MACHINE_ID" --app atlas-reviewer --signal SIGINT --timeout 120'
        in RUNBOOK
    )
    assert 'flyp machine destroy "$MACHINE_ID" --app atlas-reviewer --force' in RUNBOOK
    assert "`fly apps destroy` does not remove Sprites" in RUNBOOK
    assert "sweep --runner" in RUNBOOK
    assert "runner Sprite for this review:" in RUNBOOK
    recover = RUNBOOK.split("### Recover a runner Sprite by name", 1)[1]
    sweep = block_with("-- sweep --event")
    assert "-- sweep --event /home/atlas/event.json --force-live" in sweep
    assert sweep.rstrip().endswith(")")
    assert recover.index("flyp machine list --app atlas-reviewer") < recover.index(
        sweep
    )


def test_runbook_publishes_a_per_commit_label_and_never_releases():
    assert 'LABEL="reviewer-$(git rev-parse --short=12 HEAD)"' in RUNBOOK
    assert 'IMAGE="registry.fly.io/atlas-reviewer:$LABEL"' in RUNBOOK
    deploys = [c for c in fly_commands(RUNBOOK) if " deploy " in f" {c} "]
    assert deploys
    for command in deploys:
        assert command.startswith("flyp deploy --build-only --push"), command
    assert f"flyp apps destroy {APP_NAME} --yes" in RUNBOOK


def test_runbook_records_the_accepted_costs():
    costs = RUNBOOK.split("## Accepted costs", 1)[1].split("\n## ", 1)[0]
    assert "every Machine of the app" in costs
    assert "whole dev lock" in costs


def test_runbook_keeps_what_the_first_deploy_showed():
    for text in (
        "--depot=false",
        "Do not run `fly secrets deploy`",
        "Main child exited normally with code:",
        "fly machine status <id>",
        "exit_code=",
        "fly logs --no-tail",
        "leave `fly.toml` unchanged",
        "## What the 2026-11-10 deploy showed",
    ):
        assert text in RUNBOOK, text
    assert RUNBOOK.index("flyp logs --app atlas-reviewer") < RUNBOOK.index(
        "-- review --event"
    )
    wait = RUNBOOK.split("### Wait for the review to exit", 1)[1].split("\n### ", 1)[0]
    flat = " ".join(wait.split())
    assert "they appear only when the hold ends or the Machine stops" in flat
    assert "never in place of the poll" in flat
    assert "2026-11-10" not in wait


def test_readme_points_at_the_runbook():
    assert "deploy-fly.md" in README
    assert "D37" in README
    flat = " ".join(README.split())
    for text in (
        "Do not run `fly secrets deploy`",
        "--depot=false",
        "Main child exited normally with code:",
        "exit_code=",
        "leave `fly.toml` unchanged",
        "Start `fly logs` before the run",
    ):
        assert text in flat, text
