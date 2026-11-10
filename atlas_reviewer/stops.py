# SPDX-License-Identifier: MIT
"""Stop signals as `KeyboardInterrupt`, held while a runner is deleted.

The first SIGINT or SIGTERM unwinds the stack, so `finally` blocks still
delete the runner Sprite; later ones are ignored, so a second stop cannot
cut that cleanup short (`CLEANUP_BUDGET_S` bounds it; SIGKILL still ends
the process). A stop that arrives inside `held()` waits out the block.
If that block is already unwinding another exception, the stop is dropped
and that exception stays the one that propagates. If the block finishes,
the stop stays pending until `raise_if_stopped`. `run_review` raises it
as soon as the runner phase returns, before any further GitHub or model
work. A caller that never raises it leaves the stop pending. A
non-interactive `sh` starts `&` jobs with SIGINT ignored, and the Fly
entrypoint starts the CLI that way.
"""

from __future__ import annotations

import signal
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_STOPS = (signal.SIGINT, signal.SIGTERM)
_state = threading.local()


def _on_stop(signum: int, frame: object) -> None:
    for stop in _STOPS:
        signal.signal(stop, signal.SIG_IGN)
    if getattr(_state, "depth", 0):
        _state.pending = True
        return
    raise KeyboardInterrupt


def install_interrupts() -> None:
    for stop in _STOPS:
        signal.signal(stop, _on_stop)


@contextmanager
def held() -> Iterator[None]:
    """Python runs signal handlers in the main thread, so this holds a
    stop only for code that runs there. It does not raise: an exception
    already unwinding would be replaced, and a finished body still has
    its result to return."""
    _state.depth = getattr(_state, "depth", 0) + 1
    try:
        yield
    finally:
        _state.depth -= 1
        if (
            not _state.depth
            and getattr(_state, "pending", False)
            and sys.exc_info()[1] is not None
        ):
            _state.pending = False


def raise_if_stopped() -> None:
    """Raise a stop `held` deferred, once the caller has kept its result.
    No-op while a hold is open, or when the stop was set aside because
    another exception was already unwinding.

    `run_session` and `run_disposable` leave the stop pending. `cli.main`
    raises it, and `run_review` raises it right after the runner phase.
    Any other caller has to call this itself, or the stop stays pending
    for whatever runs next in the process."""
    if getattr(_state, "depth", 0) or not getattr(_state, "pending", False):
        return
    _state.pending = False
    sys.stdout.flush()
    sys.stderr.flush()
    raise KeyboardInterrupt
