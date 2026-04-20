"""Chaos / fault-injection scenarios."""

from __future__ import annotations

import asyncio

import pytest

from LifecycleHook import (
    LifecycleHook,
    LifecycleInvariantError,
    LifecyclePhase,
    LifecycleRegistry,
)


def test_chaos_hanging_hook_is_cancelled() -> None:
    async def run() -> None:
        reg = LifecycleRegistry(default_timeout_s=0.02)

        async def hang() -> None:
            while True:
                await asyncio.sleep(0.1)

        reg.register(LifecycleHook(LifecyclePhase.STARTING, hang))
        with pytest.raises(LifecycleInvariantError):
            await reg.run_starting()

    asyncio.run(run())


def test_chaos_many_failing_stopping_hooks_all_drain() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        drained: list[int] = []

        def make(label: int, should_fail: bool):  # type: ignore[no-untyped-def]
            async def inner() -> None:
                if should_fail:
                    raise RuntimeError(f"fail-{label}")
                drained.append(label)
            return inner

        for i in range(20):
            reg.register(
                LifecycleHook(
                    LifecyclePhase.STOPPING,
                    make(i, i % 3 == 0),
                )
            )
        await reg.run_stopping()
        # Every non-failing hook drained (LIFO order).
        expected = [i for i in range(19, -1, -1) if i % 3 != 0]
        assert drained == expected

    asyncio.run(run())


def test_chaos_zero_default_timeout_rejected() -> None:
    with pytest.raises(LifecycleInvariantError):
        LifecycleRegistry(default_timeout_s=0.0)
    with pytest.raises(LifecycleInvariantError):
        LifecycleRegistry(default_timeout_s=-1.0)


def test_chaos_register_non_hook_rejected() -> None:
    reg = LifecycleRegistry()
    for bad in (None, "hook", 42, object()):
        with pytest.raises(LifecycleInvariantError):
            reg.register(bad)  # type: ignore[arg-type]


def test_chaos_ready_after_failure_never_fires() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def fail() -> None:
            raise SystemError("catastrophic")

        reg.register(LifecycleHook(LifecyclePhase.STARTING, fail))
        with pytest.raises(SystemError):
            await reg.run_starting()
        for _ in range(5):
            with pytest.raises(LifecycleInvariantError):
                await reg.run_ready()
        assert not reg.ready_fired

    asyncio.run(run())


def test_chaos_stopping_twice_rejected() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        await reg.run_stopping()
        with pytest.raises(LifecycleInvariantError):
            await reg.run_stopping()

    asyncio.run(run())


def test_chaos_stopped_terminal_is_idempotent_guard() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        await reg.run_stopped()
        assert reg.stopped
        with pytest.raises(LifecycleInvariantError):
            await reg.run_stopped()

    asyncio.run(run())
