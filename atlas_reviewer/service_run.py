# SPDX-License-Identifier: MIT
"""Run one queued commit through the existing ``review`` command.

The child is ``python -m atlas_reviewer review``. It inherits the
controller's credentials and not the webhook secret. When the queue
cancels the job, the child is signalled SIGTERM, which the CLI turns into
the stop that deletes its Sprite, and the result is not a draft to post.
Exit codes 0, 4 and 5 are the CLI's finished reviews (complete, incomplete
coverage, changes requested). Any other exit, or a finished process with
no draft file, is a failure and produces no report.
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
    return root / "runs" / f"{event.pr_number}-{event.head_sha}"


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


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """The review process does not need the webhook secret, so it is left
    out of the child's environment."""
    return {key: value for key, value in env.items() if key != WEBHOOK_SECRET_ENV}


def make_runner(
    config: RunConfig,
    env: Mapping[str, str],
    *,
    popen: Popen = subprocess.Popen,
    sleeper: Sleeper = time.sleep,
) -> Callable[[PrEvent, threading.Event], ReviewRun]:
    def run(event: PrEvent, cancel: threading.Event) -> ReviewRun:
        directory = run_dir(config.state_root, event)
        make_private_dirs(directory)
        _write_event(directory / "event.json", event)
        stderr_path = directory / "stderr.txt"
        argv = review_argv(config, directory)
        code = run_process(
            argv,
            child_env(env),
            cancel,
            stderr_path,
            popen=popen,
            sleeper=sleeper,
        )
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
) -> int | None:
    """The child's exit code, or None when ``cancel`` stopped it."""
    handle = stderr_path.open("ab")
    try:
        proc = popen(
            list(argv),
            env=dict(env),
            stdout=subprocess.DEVNULL,
            stderr=handle,
        )
        while True:
            if cancel.is_set():
                _stop(proc)
                return None
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
