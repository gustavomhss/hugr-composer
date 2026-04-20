"""Behavioral end-to-end scenarios — proves invariants at runtime."""

from __future__ import annotations

import asyncio

import pytest

from LifecycleHook import (
    LifecycleHook,
    LifecycleInvariantError,
    LifecyclePhase,
    LifecycleRegistry,
)


def test_scenario_full_boot_and_shutdown() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        trail: list[str] = []

        async def warm_cache() -> None:
            trail.append("warm")

        async def ready() -> None:
            trail.append("ready")

        async def drain_db() -> None:
            trail.append("drain-db")

        async def close_queue() -> None:
            trail.append("close-queue")

        async def terminal() -> None:
            trail.append("stopped")

        reg.register(LifecycleHook(LifecyclePhase.STARTING, warm_cache))
        reg.register(LifecycleHook(LifecyclePhase.READY, ready))
        reg.register(LifecycleHook(LifecyclePhase.STOPPING, drain_db))
        reg.register(LifecycleHook(LifecyclePhase.STOPPING, close_queue))
        reg.register(LifecycleHook(LifecyclePhase.STOPPED, terminal))

        await reg.run_starting()
        await reg.run_ready()
        await reg.run_stopping()
        await reg.run_stopped()

        # STOPPING LIFO: close_queue before drain_db.
        assert trail == ["warm", "ready", "close-queue", "drain-db", "stopped"]
        assert reg.ready_fired
        assert reg.stopped

    asyncio.run(run())


def test_scenario_startup_failure_aborts_ready_then_drains() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        trail: list[str] = []

        async def migrate() -> None:
            trail.append("migrate")
            raise RuntimeError("db schema out of date")

        async def ready() -> None:
            trail.append("ready")  # MUST NOT fire

        async def drain() -> None:
            trail.append("drain")

        reg.register(LifecycleHook(LifecyclePhase.STARTING, migrate))
        reg.register(LifecycleHook(LifecyclePhase.READY, ready))
        reg.register(LifecycleHook(LifecyclePhase.STOPPING, drain))
        with pytest.raises(RuntimeError):
            await reg.run_starting()
        with pytest.raises(LifecycleInvariantError):
            await reg.run_ready()
        await reg.run_stopping()
        assert trail == ["migrate", "drain"]

    asyncio.run(run())


def test_scenario_ready_fires_exactly_once_across_attempts() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        count = [0]

        async def r() -> None:
            count[0] += 1

        reg.register(LifecycleHook(LifecyclePhase.READY, r))
        await reg.run_ready()
        with pytest.raises(LifecycleInvariantError):
            await reg.run_ready()
        assert count[0] == 1

    asyncio.run(run())


def test_scenario_slow_hook_is_cancelled_per_policy() -> None:
    async def run() -> None:
        reg = LifecycleRegistry(default_timeout_s=0.05)

        async def hang() -> None:
            await asyncio.sleep(10.0)

        reg.register(LifecycleHook(LifecyclePhase.STARTING, hang))
        with pytest.raises(LifecycleInvariantError):
            await reg.run_starting()

    asyncio.run(run())


def test_scenario_duplicate_registration_blocked_per_phase() -> None:
    async def cb() -> None:
        return None

    reg = LifecycleRegistry()
    reg.register(LifecycleHook(LifecyclePhase.STARTING, cb))
    with pytest.raises(LifecycleInvariantError):
        reg.register(LifecycleHook(LifecyclePhase.STARTING, cb))


def test_scenario_stopping_drains_even_with_failures() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        trail: list[str] = []

        async def ok1() -> None:
            trail.append("ok1")

        async def fail() -> None:
            raise RuntimeError("boom")

        async def ok2() -> None:
            trail.append("ok2")

        reg.register(LifecycleHook(LifecyclePhase.STOPPING, ok1))
        reg.register(LifecycleHook(LifecyclePhase.STOPPING, fail))
        reg.register(LifecycleHook(LifecyclePhase.STOPPING, ok2))
        # LIFO: ok2, fail (swallowed), ok1.
        await reg.run_stopping()
        assert trail == ["ok2", "ok1"]

    asyncio.run(run())
