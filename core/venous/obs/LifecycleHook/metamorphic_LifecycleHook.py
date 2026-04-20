"""Metamorphic + differential tests — algebraic laws."""

from __future__ import annotations

import asyncio

from LifecycleHook import (
    LifecycleHook,
    LifecyclePhase,
    LifecycleRegistry,
)


def test_metamorphic_register_order_preserved_in_starting() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        order: list[str] = []

        def make(label: str):  # type: ignore[no-untyped-def]  # closure over label; return type depends on coroutine
            async def inner() -> None:
                order.append(label)
            return inner

        for label in ("x", "y", "z", "w"):
            reg.register(LifecycleHook(LifecyclePhase.STARTING, make(label)))
        await reg.run_starting()
        assert order == ["x", "y", "z", "w"]

    asyncio.run(run())


def test_metamorphic_stopping_reverses_registration() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        order: list[str] = []

        def make(label: str):  # type: ignore[no-untyped-def]
            async def inner() -> None:
                order.append(label)
            return inner

        labels = ["a", "b", "c", "d", "e"]
        for label in labels:
            reg.register(LifecycleHook(LifecyclePhase.STOPPING, make(label)))
        await reg.run_stopping()
        assert order == list(reversed(labels))

    asyncio.run(run())


def test_metamorphic_ready_state_monotonic() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        assert reg.ready_fired is False

        async def r() -> None:
            pass

        reg.register(LifecycleHook(LifecyclePhase.READY, r))
        await reg.run_ready()
        assert reg.ready_fired is True
        # ready_fired MUST stay True; no reset path.
        # (We cannot call run_ready again, so just verify the probe.)
        assert reg.ready_fired is True

    asyncio.run(run())


def test_metamorphic_stopped_state_monotonic() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()
        assert reg.stopped is False
        await reg.run_stopped()
        assert reg.stopped is True

    asyncio.run(run())


def test_differential_phase_enum_values() -> None:
    # Catalog contract: exactly four phases with fixed string values.
    assert LifecyclePhase.STARTING.value == "starting"
    assert LifecyclePhase.READY.value == "ready"
    assert LifecyclePhase.STOPPING.value == "stopping"
    assert LifecyclePhase.STOPPED.value == "stopped"
    assert len(list(LifecyclePhase)) == 4


def test_metamorphic_register_idempotent_across_phases() -> None:
    async def shared() -> None:
        return None

    reg = LifecycleRegistry()
    for phase in LifecyclePhase:
        # Same callback in different phases: allowed.
        reg.register(LifecycleHook(phase, shared))
    for phase in LifecyclePhase:
        assert len(reg.hooks_for(phase)) == 1
