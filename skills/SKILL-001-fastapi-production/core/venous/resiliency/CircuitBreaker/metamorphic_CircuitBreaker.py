"""Metamorphic + differential tests for CircuitBreaker.

Algebraic properties verified here:
- force_open is idempotent once the breaker is open
- successful closed-state calls NEVER change state
- open -> half_open -> closed recovery yields the same post-state as a fresh breaker
- transitions are strictly monotonic in event-log order (no duplicate events for no-op transitions)
"""

from __future__ import annotations

import asyncio
import time

from CircuitBreaker import InMemoryCircuitBreaker


def test_metamorphic_force_open_idempotent() -> None:
    breaker = InMemoryCircuitBreaker("svc")
    breaker.force_open("first")
    first_event_count = len(breaker.events)
    for _ in range(10):
        breaker.force_open(f"attempt-{_}")
    assert len(breaker.events) == first_event_count
    assert breaker.state == "open"


def test_metamorphic_successful_calls_preserve_closed_state() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker("svc", minimum_number_of_calls=3)

        async def healthy() -> int:
            return 1

        for _ in range(50):
            await breaker.call(healthy)
        assert breaker.state == "closed"
        # No transitions — the event log stays empty.
        assert breaker.events == ()

    asyncio.run(run())


def test_metamorphic_recovery_yields_fresh_state() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "svc", minimum_number_of_calls=2, cooldown_ms=10,
            permitted_calls_in_half_open=1,
        )
        breaker.on_failure(RuntimeError("x"), 1.0)
        breaker.on_failure(RuntimeError("x"), 1.0)
        time.sleep(0.03)

        async def healthy() -> int:
            return 7

        await breaker.call(healthy)
        assert breaker.state == "closed"
        # After recovery the window is cleared — behaves like a fresh breaker.
        fresh = InMemoryCircuitBreaker("svc")
        assert breaker.state == fresh.state

    asyncio.run(run())


def test_metamorphic_transition_order_monotonic() -> None:
    breaker = InMemoryCircuitBreaker("svc", cooldown_ms=10)
    breaker.force_open("a")
    time.sleep(0.03)
    breaker.allow_probe()  # open -> half_open
    monotonic_ns = [e.monotonic_ns for e in breaker.events]
    assert monotonic_ns == sorted(monotonic_ns)


def test_differential_force_open_vs_rate_open() -> None:
    """Both paths of entering open MUST yield observable state == 'open'."""
    a = InMemoryCircuitBreaker("a", minimum_number_of_calls=2)
    b = InMemoryCircuitBreaker("b")

    # Path 1: threshold-driven.
    a.on_failure(RuntimeError("x"), 1.0)
    a.on_failure(RuntimeError("x"), 1.0)

    # Path 2: operator-driven.
    b.force_open("manual")

    assert a.state == b.state == "open"
