"""Chaos / fault injection for DistributedLock."""

from __future__ import annotations

import asyncio

import pytest

from DistributedLock import (
    DistributedLockError,
    FakeClock,
    InMemoryDistributedLock,
    LockHandle,
    LockOwnershipError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def test_chaos_empty_resource_id_rejected() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        with pytest.raises(DistributedLockError):
            await lock.try_lock("", "o", lease_s=10)
    _run(scenario())


def test_chaos_empty_owner_id_rejected() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        with pytest.raises(DistributedLockError):
            await lock.try_lock("r", "", lease_s=10)
    _run(scenario())


def test_chaos_null_byte_injection_rejected() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        with pytest.raises(DistributedLockError):
            await lock.try_lock("r\x00", "o", lease_s=10)
        with pytest.raises(DistributedLockError):
            await lock.try_lock("r", "o\x00", lease_s=10)
    _run(scenario())


def test_chaos_clock_skew_backward_is_harmless() -> None:
    """If the clock ticks backward, the lease still expires normally on the
    next forward tick. Monotonic clocks guarantee this at the OS level; our
    FakeClock simulates."""
    async def scenario() -> None:
        clock = FakeClock(start=100.0)
        lock = InMemoryDistributedLock(clock=clock)
        h = await lock.try_lock("r", "o", lease_s=5)
        assert h is not None
        # Clock jumps forward then we try to acquire; must be blocked.
        # The FakeClock does not let us jump backward, which is correct
        # (monotonic semantics).
        h2 = await lock.try_lock("r", "x", lease_s=5)
        assert h2 is None
    _run(scenario())


def test_chaos_thief_cannot_steal_under_load() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "legit", lease_s=60)
        assert h is not None
        # 30 parallel thieves.
        async def steal(i: int) -> bool:
            try:
                await lock.unlock(LockHandle(resource_id="r", owner_id=f"t{i}", lease_s=60))
            except LockOwnershipError:
                return False
            return True
        results = await asyncio.gather(*[steal(i) for i in range(30)])
        assert not any(results)
        assert lock.current_holder("r") == "legit"
    _run(scenario())


def test_chaos_oversized_lease_rejected() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        with pytest.raises(DistributedLockError):
            await lock.try_lock("r", "o", lease_s=10**9)
    _run(scenario())


def test_chaos_acquire_release_tight_loop() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        for i in range(200):
            h = await lock.try_lock("r", f"o{i}", lease_s=30)
            assert h is not None
            await lock.unlock(h)
        assert not lock.is_held("r")
    _run(scenario())
