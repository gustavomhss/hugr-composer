"""Chaos / game-day tests for CircuitBreaker.

Simulates flaky dependencies, repeated force_open churn, probe-storm conditions,
and concurrent transitions to confirm the breaker never enters an illegal state.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from CircuitBreaker import (
    CircuitOpenError,
    InMemoryCircuitBreaker,
)


def test_chaos_flapping_dependency_eventually_trips_breaker() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "svc", minimum_number_of_calls=5, cooldown_ms=10_000,
        )
        # Mostly failing traffic — rate >>50%.
        for i in range(20):
            if i % 5 == 0:
                breaker.on_success(1.0)
            else:
                breaker.on_failure(RuntimeError("x"), 1.0)
        assert breaker.state == "open"

        async def fn() -> str:
            return "ok"

        with pytest.raises(CircuitOpenError):
            await breaker.call(fn)

    asyncio.run(run())


def test_chaos_probe_storm_during_halfopen() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "svc", permitted_calls_in_half_open=1, cooldown_ms=5,
        )
        breaker.force_open("test")
        time.sleep(0.02)
        granted: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            ok = breaker.allow_probe()
            with lock:
                granted.append(ok)

        ts = [threading.Thread(target=worker) for _ in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        # Exactly one probe permit MUST have been granted.
        assert sum(1 for g in granted if g) == 1

    asyncio.run(run())


def test_chaos_repeated_force_open_stays_stable() -> None:
    breaker = InMemoryCircuitBreaker("svc")
    for i in range(500):
        breaker.force_open(f"iter-{i}")
    assert breaker.state == "open"
    # Only ONE transition event should have been emitted despite 500 calls.
    open_events = [e for e in breaker.events if e.to_state == "open"]
    assert len(open_events) == 1


def test_chaos_concurrent_mixed_outcomes_preserve_state_invariant() -> None:
    breaker = InMemoryCircuitBreaker("svc", minimum_number_of_calls=3)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def succ_worker() -> None:
        try:
            for _ in range(50):
                breaker.on_success(1.0)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def fail_worker() -> None:
        try:
            for _ in range(50):
                breaker.on_failure(RuntimeError("x"), 1.0)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=succ_worker) for _ in range(4)]
    ts += [threading.Thread(target=fail_worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    # State MUST remain one of the three legal values.
    assert breaker.state in ("closed", "open", "half_open")


def test_chaos_wrapped_fn_raises_systemexit() -> None:
    # SystemExit is a BaseException — the wrapper MUST classify it as failure
    # and propagate, not swallow.
    async def run() -> None:
        breaker = InMemoryCircuitBreaker("svc", minimum_number_of_calls=5)

        async def exit_hard() -> str:
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            await breaker.call(exit_hard)
        # One failure was recorded.
        assert len(breaker._window) == 1

    asyncio.run(run())


def test_chaos_huge_window_does_not_leak_memory() -> None:
    breaker = InMemoryCircuitBreaker("svc", window_size=10)
    for _ in range(10_000):
        breaker.on_success(1.0)
    # Bounded deque is enforced by maxlen.
    assert len(breaker._window) == 10


def test_chaos_back_to_back_recovery_cycles() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "svc", minimum_number_of_calls=2, cooldown_ms=5,
            permitted_calls_in_half_open=1,
        )

        async def healthy() -> str:
            return "ok"

        for _ in range(3):
            breaker.on_failure(RuntimeError("x"), 1.0)
            breaker.on_failure(RuntimeError("x"), 1.0)
            assert breaker.state == "open"
            time.sleep(0.02)
            await breaker.call(healthy)
            assert breaker.state == "closed"

    asyncio.run(run())
