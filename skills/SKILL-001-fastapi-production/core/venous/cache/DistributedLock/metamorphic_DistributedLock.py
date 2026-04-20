"""Metamorphic + differential tests for DistributedLock."""

from __future__ import annotations

import asyncio

import pytest

from DistributedLock import (
    FakeClock,
    InMemoryDistributedLock,
    LockOwnershipError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def test_metamorphic_unlock_then_acquire_is_noop_composition() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        for _ in range(10):
            h = await lock.try_lock("r", "o", lease_s=60)
            assert h is not None
            await lock.unlock(h)
        assert not lock.is_held("r")
    _run(scenario())


def test_metamorphic_lease_advance_then_reacquire() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        lock = InMemoryDistributedLock(clock=clock)
        for i in range(5):
            h = await lock.try_lock("r", f"o{i}", lease_s=3)
            assert h is not None
            clock.advance(4.0)  # advance past lease
            # New holder can acquire.
    _run(scenario())


def test_differential_handle_roundtrip_identity() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "owner", lease_s=30)
        assert h is not None
        # Handle fields reflect inputs.
        assert h.resource_id == "r"
        assert h.owner_id == "owner"
        assert h.lease_s == 30
    _run(scenario())


def test_metamorphic_ownership_fencing_composition() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "A", lease_s=30)
        assert h is not None
        # N attempts by thieves — none succeed.
        from DistributedLock import LockHandle
        for i in range(15):
            with pytest.raises(LockOwnershipError):
                await lock.unlock(LockHandle(resource_id="r", owner_id=f"X{i}", lease_s=30))
        # Owner can still unlock.
        await lock.unlock(h)
        assert not lock.is_held("r")
    _run(scenario())


def test_metamorphic_concurrent_acquires_preserve_single_holder() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        async def attempt(i: int):  # type: ignore[no-untyped-def]  # asyncio helper
            return await lock.try_lock("r", f"o{i}", lease_s=60)
        rounds = 3
        for _ in range(rounds):
            results = await asyncio.gather(*[attempt(i) for i in range(30)])
            winners = [h for h in results if h is not None]
            assert len(winners) == 1
            # Reset: owner releases.
            await lock.unlock(winners[0])
    _run(scenario())
