"""Behavioral end-to-end scenarios for DistributedLock."""

from __future__ import annotations

import asyncio

import pytest

from DistributedLock import (
    FakeClock,
    InMemoryDistributedLock,
    LockHandle,
    LockOwnershipError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def test_scenario_critical_section_acquired_released() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("rare-task", "worker-a", lease_s=30)
        assert h is not None
        # Perform critical work here...
        await lock.unlock(h)
        # Resource is now free; next caller succeeds.
        h2 = await lock.try_lock("rare-task", "worker-b", lease_s=30)
        assert h2 is not None
    _run(scenario())


def test_scenario_crashed_holder_recovered_after_lease() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        lock = InMemoryDistributedLock(clock=clock)
        h1 = await lock.try_lock("res", "crashed-holder", lease_s=10)
        assert h1 is not None
        # Holder crashed — never unlocked. Time passes.
        clock.advance(11.0)
        h2 = await lock.try_lock("res", "replacement", lease_s=10)
        assert h2 is not None
        assert h2.owner_id == "replacement"
    _run(scenario())


def test_scenario_thief_cannot_release() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "legit", lease_s=60)
        assert h is not None
        thief_handle = LockHandle(resource_id="r", owner_id="thief", lease_s=60)
        with pytest.raises(LockOwnershipError):
            await lock.unlock(thief_handle)
        assert lock.current_holder("r") == "legit"
    _run(scenario())


def test_scenario_contending_workers_one_wins() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        async def worker(i: int) -> bool:
            h = await lock.try_lock("res", f"w{i}", lease_s=60)
            if h is None:
                return False
            await lock.unlock(h)
            return True
        # Only one worker can hold at any instant; some succeed serially.
        results = await asyncio.gather(*[worker(i) for i in range(50)])
        assert any(results)
    _run(scenario())


def test_scenario_release_is_idempotent() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "o", lease_s=30)
        assert h is not None
        await lock.unlock(h)
        # Second release — already free; must not raise.
        await lock.unlock(h)
        assert not lock.is_held("r")
    _run(scenario())


def test_scenario_independent_resources_do_not_interfere() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h_a = await lock.try_lock("res-a", "o1", lease_s=30)
        h_b = await lock.try_lock("res-b", "o1", lease_s=30)
        assert h_a is not None and h_b is not None
        # Two distinct resources: both held by same owner in parallel.
        assert lock.current_holder("res-a") == "o1"
        assert lock.current_holder("res-b") == "o1"
    _run(scenario())
