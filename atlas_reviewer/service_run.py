# SPDX-License-Identifier: MIT
"""Run one queued commit through the existing ``review`` command.

The child is ``python -m atlas_reviewer review``. It receives an allowlist
of environment variables: the model key, the Sprites token, a read-only
installation token, and the process basics (``PATH``, ``HOME``, language
and CA paths). The webhook secret, the App private key, and anything else
the parent holds, including a Fly API token, are not passed on. When the
queue cancels the job, or the wall-clock deadline passes, the child is
signalled SIGTERM, which the CLI turns into the stop that deletes its
Sprite, and the result is not a draft to post. Exit codes 0, 4 and 5 are
the CLI's finished reviews (complete, incomplete coverage, changes
requested). Any other exit, or a finished process with no draft file, is
a failure and produces no report.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas_reviewer.domain import PrEvent
from atlas_reviewer.ledger import make_private_dirs
from atlas_reviewer.verdict import parse_status

WEBHOOK_SECRET_ENV = "ATLAS_GITHUB_WEBHOOK_SECRET"
APP_KEY_ENV = "ATLAS_GITHUB_APP_PRIVATE_KEY"
READ_TOKEN_ENV = "ATLAS_GITHUB_INSTALLATION_TOKEN"
# The child reviews with a read-only installation token. The App private
# key stays in the parent, so the child cannot mint a write token.
# Passed through to the child. Everything else the parent holds stays there.
_CHILD_ALLOWED = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "PYTHONIOENCODING",
        "PYTHONHASHSEED",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "ATLAS_OPENROUTER_API_KEY",
        "ATLAS_SPRITES_TOKEN",
        READ_TOKEN_ENV,
    }
)
# The parent stops the child after this long even if the child is still
# running. The controller has its own shorter caps; this is the wall
# around a child that never hits them.
REVIEW_DEADLINE_S = 1200.0
_DEADLINE_EXIT = -1
# The CLI's review exits. 4 is incomplete file coverage and 5 is a finished
# review that requests changes. Both still wrote a draft.
POSTABLE_EXITS = frozenset({0, 4, 5})
_STOP_WAIT_S = 5.0
_QUOTED = re.compile(r"`(\"(?:\\.|[^\"\\])*\")`")

Popen = Callable[..., Any]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class RunConfig:
    provider: str
    allow_live_inference: bool
    state_root: Path


@dataclass(frozen=True)
class ReviewReport:
    """What the posted comment lists, taken from the draft the CLI wrote."""

    lenses_run: tuple[str, ...]
    lenses_not_run: tuple[str, ...]
    files_note: str
    files_not_read: tuple[str, ...]
    limit_stops: tuple[str, ...]
    cost_lines: tuple[str, ...]
    recommended_event: str


@dataclass(frozen=True)
class ReviewRun:
    ok: bool
    report: ReviewReport | None = None
    error: str = ""


def run_dir(root: Path, event: PrEvent) -> Path:
    repo = event.repo.replace("/", "-")
    return root / "runs" / f"{repo}-{event.pr_number}-{event.head_sha}"


def review_argv(config: RunConfig, directory: Path) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "atlas_reviewer",
        "--state-dir",
        str(directory / "state"),
        "review",
        "--event",
        str(directory / "event.json"),
        "--out",
        str(directory / "draft.md"),
        "--events",
        str(directory / "events.jsonl"),
        "--provider",
        config.provider,
    ]
    if config.provider == "openrouter" and config.allow_live_inference:
        argv.append("--allow-live-inference")
    return argv


def child_env(env: Mapping[str, str], *, token: str = "") -> dict[str, str]:
    """The review process gets only ``_CHILD_ALLOWED``. ``token`` is a
    read-only installation token, when the parent minted one."""
    cleaned = {key: value for key, value in env.items() if key in _CHILD_ALLOWED}
    if token:
        cleaned[READ_TOKEN_ENV] = token
    return cleaned


def make_runner(
    config: RunConfig,
    env: Mapping[str, str],
    *,
    popen: Popen = subprocess.Popen,
    sleeper: Sleeper = time.sleep,
    deadline_s: float = REVIEW_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
    read_token: Callable[[Mapping[str, str], PrEvent], tuple[str, str]] | None = None,
) -> Callable[[PrEvent, threading.Event], ReviewRun]:
    mint = read_token or _read_token

    def run(event: PrEvent, cancel: threading.Event) -> ReviewRun:
        directory = run_dir(config.state_root, event)
        make_private_dirs(directory)
        _write_event(directory / "event.json", event)
        stderr_path = directory / "stderr.txt"
        argv = review_argv(config, directory)
        token, mint_error = mint(env, event)
        if mint_error:
            return ReviewRun(False, error=mint_error)
        code = run_process(
            argv,
            child_env(env, token=token),
            cancel,
            stderr_path,
            popen=popen,
            sleeper=sleeper,
            deadline_s=deadline_s,
            clock=clock,
        )
        if code == _DEADLINE_EXIT:
            return ReviewRun(False, error="review deadline")
        if code is None or cancel.is_set():
            return ReviewRun(False, error="superseded")
        if code not in POSTABLE_EXITS:
            return ReviewRun(False, error=f"review exited {code}: {_tail(stderr_path)}")
        draft_path = directory / "draft.md"
        if not draft_path.is_file():
            return ReviewRun(False, error=f"review exited {code} without a draft")
        try:
            draft = draft_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return ReviewRun(
                False, error=f"could not read the draft: {type(exc).__name__}"
            )
        return ReviewRun(True, summarize_draft(draft))

    return run


def run_process(
    argv: Sequence[str],
    env: Mapping[str, str],
    cancel: threading.Event,
    stderr_path: Path,
    *,
    popen: Popen = subprocess.Popen,
    sleeper: Sleeper = time.sleep,
    poll_s: float = 0.05,
    deadline_s: float = REVIEW_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
) -> int | None:
    """The child's exit code, None when ``cancel`` stopped it, or
    ``_DEADLINE_EXIT`` when ``deadline_s`` passed."""
    fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    handle = os.fdopen(fd, "ab")
    try:
        proc = popen(
            list(argv),
            env=dict(env),
            stdout=subprocess.DEVNULL,
            stderr=handle,
        )
        started = clock()
        while True:
            if cancel.is_set():
                _stop(proc)
                return None
            if clock() - started >= deadline_s:
                _stop(proc)
                return _DEADLINE_EXIT
            code = proc.poll()
            if code is not None:
                return code
            sleeper(poll_s)
    finally:
        handle.close()


def summarize_draft(draft: str) -> ReviewReport:
    """Lenses, coverage, limit rows and cost lines from a controller draft.

    The one-shot draft does not list every path a model call saw. The
    files section is the controller's coverage note, plus any path the
    draft's opening warning quotes as not reviewed in full.
    """
    status = parse_status(draft) or {}
    recommended = status.get("review_event")
    run: list[str] = []
    skipped: list[str] = []
    for cells in _table(section(draft, "Review lenses")):
        name = cells[0]
        kind = cells[1] if len(cells) > 1 else ""
        why = cells[4] if len(cells) > 4 else ""
        if kind == "run whole":
            run.append(name)
        else:
            skipped.append(f"{name}: {why}" if why else name)
    note = "The draft has no diff-coverage note."
    for line in section(draft, "Controller notes").splitlines():
        if "Diff coverage" in line:
            note = line.lstrip("- ").strip()
            break
    preamble = draft.split("\n## ", 1)[0]
    return ReviewReport(
        tuple(run),
        tuple(skipped),
        note,
        _quoted_strings(preamble),
        tuple(
            " | ".join(cells)
            for cells in _table(section(draft, "Omissions and limits hit"))
        ),
        tuple(_bullets(section(draft, "Model usage"))),
        recommended if isinstance(recommended, str) else "",
    )


def section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker) :]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _table(text: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if not cells or cells[0] in {"Lens", "Source"} or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    return tuple(rows)


def _bullets(text: str) -> tuple[str, ...]:
    return tuple(
        line[2:].strip() for line in text.splitlines() if line.startswith("- ")
    )


def _quoted_strings(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for raw in _QUOTED.findall(text):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, str) and value and value not in found:
            found.append(value)
    return tuple(found)


def _read_token(env: Mapping[str, str], event: PrEvent) -> tuple[str, str]:
    """A read-only installation token for the child, or ``("", "")`` when
    the parent has no App key (offline). The second value is an error
    label when a live mint fails. The key itself is never returned."""
    key = env.get(APP_KEY_ENV, "")
    if not key:
        return "", ""
    app_id = env.get("ATLAS_GITHUB_APP_ID", "")
    installation = env.get("ATLAS_GITHUB_INSTALLATION_ID", "")
    if (
        not app_id.isdigit()
        or not installation.isascii()
        or not installation.isdigit()
        or int(installation) < 1
    ):
        return "", "could not mint a read token"
    from atlas_reviewer.clock import SystemClock
    from atlas_reviewer.github_auth import READ_PERMISSIONS, AppInstallationTokens
    from atlas_reviewer.http import UrllibTransport

    try:
        tokens = AppInstallationTokens(
            UrllibTransport(),
            SystemClock(),
            app_id=app_id,
            private_key=key.replace("\\n", "\n") if "\n" not in key else key,
            installation_id=int(installation),
            permissions=READ_PERMISSIONS,
            repositories=(event.repo.split("/", 1)[1],),
        )
        return tokens.token(), ""
    except (OSError, ValueError, RuntimeError) as exc:
        return "", f"could not mint a read token ({type(exc).__name__})"


def _write_event(path: Path, event: PrEvent) -> None:
    payload = json.dumps(
        {"repo": event.repo, "pr_number": event.pr_number, "head_sha": event.head_sha}
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _tail(path: Path, limit: int = 500) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=_STOP_WAIT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=_STOP_WAIT_S)
