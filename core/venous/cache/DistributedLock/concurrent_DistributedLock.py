"""Concurrency / linearizability tests for DistributedLock."""

from __future__ import annotations

import asyncio

from DistributedLock import InMemoryDistributedLock, LockHandle


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def test_concurrent_single_winner_under_fanout() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        async def attempt(i: int) -> LockHandle | None:
            return await lock.try_lock("r", f"o{i}", lease_s=60)
        results = await asyncio.gather(*[attempt(i) for i in range(200)])
        winners = [h for h in results if h is not None]
        assert len(winners) == 1
    _run(scenario())


def test_concurrent_sequential_handoff() -> None:
    """Each acquirer eventually releases; next acquirer wins."""
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        seen: list[str] = []
        for i in range(100):
            h = await lock.try_lock("r", f"w{i}", lease_s=10)
            assert h is not None
            seen.append(h.owner_id)
            await lock.unlock(h)
        assert len(set(seen)) == 100
    _run(scenario())


def test_concurrent_independent_resources_no_contention() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        async def attempt(res: str) -> bool:
            h = await lock.try_lock(res, "o", lease_s=30)
            if h is None:
                return False
            await lock.unlock(h)
            return True
        resources = [f"res-{i}" for i in range(50)]
        results = await asyncio.gather(*[attempt(r) for r in resources])
        assert all(results)
    _run(scenario())


def test_concurrent_unlock_preserves_invariant() -> None:
    """While one owner holds, N other-owner unlocks all fail; holder stays."""
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "A", lease_s=60)
        assert h is not None
        async def thief(i: int) -> None:
            try:
                await lock.unlock(
                    LockHandle(resource_id="r", owner_id=f"T{i}", lease_s=60),
                )
            except Exception:  # noqa: BLE001 — deliberate broad catch; DL_INV_03 raises LockOwnershipError
                return
        await asyncio.gather(*[thief(i) for i in range(100)])
        assert lock.current_holder("r") == "A"
    _run(scenario())
