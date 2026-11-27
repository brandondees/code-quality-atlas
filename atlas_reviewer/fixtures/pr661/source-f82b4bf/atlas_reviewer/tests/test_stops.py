# SPDX-License-Identifier: MIT
"""Real-signal tests for `atlas_reviewer.stops`.

The Sprite-lifecycle tests (`test_runner_lifecycle.py` et al.) reach the
module's one call site (`runner.py`'s `with held():`) but never actually
deliver a signal, so none of `_on_stop`, `install_interrupts`, or the
`held()`/`raise_if_stopped()` deferral logic is exercised directly. These
tests send a real `SIGINT` to the current process instead."""

import os
import signal
import time

import pytest

from atlas_reviewer import stops

# Signal delivery is asynchronous (the interpreter's eval loop runs the
# handler at its next opportunity, not synchronously inside `os.kill`).
# Generous enough for a loaded CI box, short enough not to slow the suite.
_SETTLE_S = 0.2


@pytest.fixture(autouse=True)
def _isolated_signal_state():
    """Give each test a clean `_state` and restore whatever SIGINT/SIGTERM
    disposition preceded it, so a test here can't leak a changed handler
    (or a stale `pending`/`depth`) into the rest of the suite -- including
    pytest's own Ctrl-C handling."""
    previous = {sig: signal.getsignal(sig) for sig in stops._STOPS}
    stops._state.depth = 0
    stops._state.pending = False
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        stops._state.depth = 0
        stops._state.pending = False


def _send(sig: signal.Signals) -> None:
    os.kill(os.getpid(), sig)
    time.sleep(_SETTLE_S)


def test_install_interrupts_wires_both_signals():
    stops.install_interrupts()
    assert signal.getsignal(signal.SIGINT) is stops._on_stop
    assert signal.getsignal(signal.SIGTERM) is stops._on_stop


def test_signal_outside_hold_raises_immediately():
    stops.install_interrupts()
    with pytest.raises(KeyboardInterrupt):
        _send(signal.SIGINT)


def test_signal_during_hold_defers_until_raise_if_stopped():
    stops.install_interrupts()
    with stops.held():
        _send(signal.SIGINT)
        # Held open: deferred, not raised.
    # `held()` exited normally -- the docstring's "stays pending until
    # raise_if_stopped" case.
    with pytest.raises(KeyboardInterrupt):
        stops.raise_if_stopped()


def test_raise_if_stopped_is_noop_when_nothing_pending():
    stops.install_interrupts()
    stops.raise_if_stopped()  # must not raise


def test_raise_if_stopped_is_noop_while_still_held():
    stops.install_interrupts()
    with stops.held():
        _send(signal.SIGINT)
        stops.raise_if_stopped()  # depth > 0: no-op, stays pending
    with pytest.raises(KeyboardInterrupt):
        stops.raise_if_stopped()


def test_exception_already_unwinding_drops_the_pending_stop():
    """The module's documented safety property: a stop that arrives while
    another exception is already unwinding through `held()` is dropped, so
    it can't mask the real error -- and does not resurface later."""
    stops.install_interrupts()
    with pytest.raises(ValueError, match="boom"), stops.held():
        _send(signal.SIGINT)
        raise ValueError("boom")
    stops.raise_if_stopped()  # the dropped stop must not raise here
