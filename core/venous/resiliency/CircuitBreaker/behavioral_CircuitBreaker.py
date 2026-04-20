"""Behavioral end-to-end scenarios for CircuitBreaker — proves invariants at runtime."""

from __future__ import annotations

import asyncio
import time

import pytest

from CircuitBreaker import (
    CircuitOpenError,
    InMemoryCircuitBreaker,
)


def test_scenario_trip_then_open_rejects_calls() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker("payments", minimum_number_of_calls=3, cooldown_ms=10_000)

        async def flaky() -> str:
            raise RuntimeError("503")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(flaky)
        assert breaker.state == "open"

        # Once open, further calls are fast-failed without hitting flaky().
        with pytest.raises(CircuitOpenError):
            await breaker.call(flaky)

    asyncio.run(run())


def test_scenario_cooldown_then_probe_then_recover() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "payments", minimum_number_of_calls=2, cooldown_ms=20,
            permitted_calls_in_half_open=1,
        )
        breaker.on_failure(RuntimeError("x"), 1.0)
        breaker.on_failure(RuntimeError("x"), 1.0)
        assert breaker.state == "open"
        time.sleep(0.05)

        async def healthy() -> str:
            return "ok"

        result = await breaker.call(healthy)
        assert result == "ok"
        assert breaker.state == "closed"

    asyncio.run(run())


def test_scenario_probe_failure_slams_open_again() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "payments", minimum_number_of_calls=2, cooldown_ms=10,
            permitted_calls_in_half_open=1,
        )
        breaker.on_failure(RuntimeError("x"), 1.0)
        breaker.on_failure(RuntimeError("x"), 1.0)
        assert breaker.state == "open"
        time.sleep(0.03)

        async def still_broken() -> str:
            raise RuntimeError("still sick")

        with pytest.raises(RuntimeError):
            await breaker.call(still_broken)
        assert breaker.state == "open"

    asyncio.run(run())


def test_scenario_force_open_by_operator() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker("db", cooldown_ms=10_000)
        breaker.force_open("manual_failover")
        assert breaker.state == "open"

        async def will_never_run() -> str:
            raise AssertionError("must not be invoked")  # pragma: no cover

        with pytest.raises(CircuitOpenError):
            await breaker.call(will_never_run)

    asyncio.run(run())


def test_scenario_healthy_traffic_stays_closed() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker("cache", minimum_number_of_calls=3)

        async def healthy() -> int:
            return 42

        for _ in range(20):
            result = await breaker.call(healthy)
            assert result == 42
        assert breaker.state == "closed"

    asyncio.run(run())


def test_scenario_state_transitions_are_observable() -> None:
    async def run() -> None:
        breaker = InMemoryCircuitBreaker(
            "search", minimum_number_of_calls=2, cooldown_ms=15,
            permitted_calls_in_half_open=1,
        )
        breaker.on_failure(RuntimeError("x"), 1.0)
        breaker.on_failure(RuntimeError("x"), 1.0)
        time.sleep(0.04)
        await breaker.call(lambda: asyncio.sleep(0, result="ok"))  # type: ignore[arg-type]

        transitions = [(e.from_state, e.to_state) for e in breaker.events]
        # Closed -> open -> half_open -> closed is observable end to end.
        assert ("closed", "open") in transitions
        assert ("open", "half_open") in transitions
        assert ("half_open", "closed") in transitions

    asyncio.run(run())
