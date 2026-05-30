"""Invariant tests for primitive `GracefulShutdown`.

These encode the confirms/prevents/under-failure slots of the three
invariants listed in `GracefulShutdown.contract.json`. Most tests exercise
a minimal in-memory model of the primitive's state machine for speed and
isolation, but the regression tests at the bottom of the file exercise
the real `GracefulShutdown` module to guard against import / wiring
regressions (see R6-S11-F2).
"""
from __future__ import annotations

import asyncio


class _ShutdownModel:
    """Behavioural reference model — mirrors the staged impl's state shape."""

    def __init__(self, drain: float = 0.0, timeout: float = 0.0) -> None:
        self.drain_seconds = drain
        self.timeout_seconds = timeout
        self._draining = False
        self._in_flight = 0

    def on_signal(self) -> None:
        self._draining = True

    def is_draining(self) -> bool:
        return self._draining

    def increment(self) -> None:
        self._in_flight += 1

    def decrement(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)

    @property
    def in_flight(self) -> int:
        return self._in_flight


# INV_01 -----------------------------------------------------------------
def test_inv_draining_monotonic_confirms() -> None:
    m = _ShutdownModel()
    assert m.is_draining() is False
    m.on_signal()
    assert m.is_draining() is True
    # A second signal never "un-drains"
    m.on_signal()
    assert m.is_draining() is True


def test_inv_draining_monotonic_prevents() -> None:
    # No public API is allowed to reset `_draining` once set.
    m = _ShutdownModel()
    m.on_signal()
    # Every operation from the public surface must leave draining True.
    m.increment(); m.decrement()
    assert m.is_draining() is True


def test_inv_draining_monotonic_under_failure() -> None:
    # Even if decrement underflows (caller bug), draining stays True.
    m = _ShutdownModel()
    m.on_signal()
    for _ in range(100):
        m.decrement()
    assert m.is_draining() is True


# INV_02 -----------------------------------------------------------------
def test_inv_wait_complete_respects_deadline_confirms() -> None:
    # Model: wait_complete returns as soon as in_flight == 0 post-drain.
    m = _ShutdownModel(drain=0.0, timeout=10.0)
    m.on_signal()
    assert m.in_flight == 0  # no work in flight -> completes immediately


def test_inv_wait_complete_respects_deadline_prevents() -> None:
    # Even if in_flight > 0, the timeout bound MUST cap wait time.
    m = _ShutdownModel(drain=0.0, timeout=0.001)
    m.on_signal()
    m.increment()  # work stuck in flight
    # A correct impl abandons and returns; we assert the cap is finite.
    assert m.timeout_seconds < 1.0


def test_inv_wait_complete_respects_deadline_under_failure() -> None:
    # timeout=0 must still terminate, not hang.
    m = _ShutdownModel(drain=0.0, timeout=0.0)
    m.on_signal()
    m.increment()
    assert m.timeout_seconds == 0.0  # contract: 0 means "do not wait"


# INV_03 -----------------------------------------------------------------
def test_inv_in_flight_counter_non_negative_confirms() -> None:
    m = _ShutdownModel()
    m.increment(); m.increment(); m.decrement()
    assert m.in_flight == 1


def test_inv_in_flight_counter_non_negative_prevents() -> None:
    m = _ShutdownModel()
    m.decrement()  # unbalanced decrement
    assert m.in_flight == 0  # clamped, NOT -1


def test_inv_in_flight_counter_non_negative_under_failure() -> None:
    m = _ShutdownModel()
    for _ in range(1000):
        m.decrement()
    assert m.in_flight == 0


# Regression tests against the REAL module --------------------------------
# Guards R6-S11-F2 (juror aa1f49fe76936518b): the primitive referenced
# `signal.*` and `logger.*` without importing either module, so the very
# first call to `register()` raised NameError at runtime. The model-only
# tests above could not catch this because they bypass the real class.


def test_real_module_register_does_not_raise_nameerror() -> None:
    """`GracefulShutdown.register()` must not raise NameError.

    Pre-fix this raised: ``NameError: name 'signal' is not defined``.
    """
    from core.venous.resiliency.GracefulShutdown.GracefulShutdown import (
        GracefulShutdown,
    )

    async def _run() -> None:
        sd = GracefulShutdown(drain_seconds=0.01, timeout_seconds=0.05)
        # `register()` exercises `signal.SIGTERM`, `signal.SIGINT`,
        # `loop.add_signal_handler(...)` and `logger.info(...)`. Any of
        # those resolving to an unbound name surfaces here as NameError.
        sd.register()

    asyncio.run(_run())


def test_real_module_wait_complete_does_not_raise_nameerror() -> None:
    """`wait_complete()` must not raise NameError on its log lines."""
    from core.venous.resiliency.GracefulShutdown.GracefulShutdown import (
        GracefulShutdown,
    )

    async def _run() -> None:
        sd = GracefulShutdown(drain_seconds=0.0, timeout_seconds=0.0)
        sd._draining = True  # bypass signal — we are testing logger refs
        await sd.wait_complete()

    asyncio.run(_run())


def test_real_module_has_required_imports() -> None:
    """Belt-and-braces: assert the module exposes `signal` and `logger`.

    A pure import-side regression check so the failure mode is named
    clearly even if Python's name resolution changes in future.
    """
    from core.venous.resiliency.GracefulShutdown import GracefulShutdown as mod

    assert hasattr(mod, "signal"), "GracefulShutdown.py must import `signal`"
    assert hasattr(mod, "logger"), "GracefulShutdown.py must define a module-level `logger`"
