"""Unit tests for DistributedLock — 3 per invariant (confirms / prevents / under_failure)."""

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


# ---------------------------------------------------------------------------
# DL_INV_01 — at most one holder
# ---------------------------------------------------------------------------
def test_inv_mutual_exclusion_confirms() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h1 = await lock.try_lock("r", "o1", lease_s=30)
        assert h1 is not None
        h2 = await lock.try_lock("r", "o2", lease_s=30)
        assert h2 is None
    _run(scenario())


def test_inv_mutual_exclusion_prevents() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        await lock.try_lock("r", "o1", lease_s=30)
        # 20 distinct competitors — none succeed while the lease is active.
        outcomes = [
            await lock.try_lock("r", f"o{i}", lease_s=30) for i in range(2, 22)
        ]
        assert all(h is None for h in outcomes)
    _run(scenario())


def test_inv_mutual_exclusion_under_failure() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        async def attempt(i: int) -> LockHandle | None:
            return await lock.try_lock("r", f"o{i}", lease_s=30)
        results = await asyncio.gather(*[attempt(i) for i in range(50)])
        assert sum(1 for h in results if h is not None) == 1
    _run(scenario())


# ---------------------------------------------------------------------------
# DL_INV_02 — lease auto-release
# ---------------------------------------------------------------------------
def test_inv_lease_expiry_confirms() -> None:
    async def scenario() -> None:
        clock = FakeClock(start=0.0)
        lock = InMemoryDistributedLock(clock=clock)
        h1 = await lock.try_lock("r", "o1", lease_s=5)
        assert h1 is not None
        clock.advance(6.0)  # past lease expiry
        h2 = await lock.try_lock("r", "o2", lease_s=5)
        assert h2 is not None
        assert h2.owner_id == "o2"
    _run(scenario())


def test_inv_lease_expiry_prevents() -> None:
    # Before the lease elapses, a second caller MUST NOT acquire the lock.
    async def scenario() -> None:
        clock = FakeClock()
        lock = InMemoryDistributedLock(clock=clock)
        await lock.try_lock("r", "o1", lease_s=10)
        clock.advance(5.0)  # half the lease
        h2 = await lock.try_lock("r", "o2", lease_s=10)
        assert h2 is None
    _run(scenario())


def test_inv_lease_expiry_under_failure() -> None:
    # A sequence of crashed holders whose leases keep expiring — a fresh caller
    # after each expiry MUST be able to acquire the lock.
    async def scenario() -> None:
        clock = FakeClock()
        lock = InMemoryDistributedLock(clock=clock)
        for i in range(5):
            h = await lock.try_lock("r", f"o{i}", lease_s=2)
            assert h is not None, f"iteration {i} failed to acquire"
            # Holder "crashes" — we skip unlock and advance past lease.
            clock.advance(3.0)
    _run(scenario())


# ---------------------------------------------------------------------------
# DL_INV_03 — unlock rejects foreign owner
# ---------------------------------------------------------------------------
def test_inv_owner_fencing_confirms() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "o1", lease_s=30)
        assert h is not None
        await lock.unlock(h)  # owner's own handle
        # Resource is now free.
        assert not lock.is_held("r")
    _run(scenario())


def test_inv_owner_fencing_prevents() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "o1", lease_s=30)
        assert h is not None
        stolen = LockHandle(resource_id="r", owner_id="o2", lease_s=30)
        with pytest.raises(LockOwnershipError):
            await lock.unlock(stolen)
        # Resource STILL held by the rightful owner.
        assert lock.current_holder("r") == "o1"
    _run(scenario())


def test_inv_owner_fencing_under_failure() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "real-owner", lease_s=30)
        assert h is not None
        # Many thieves attempting to release — each is rejected, holder intact.
        for i in range(20):
            with pytest.raises(LockOwnershipError):
                await lock.unlock(
                    LockHandle(resource_id="r", owner_id=f"thief{i}", lease_s=30),
                )
        assert lock.current_holder("r") == "real-owner"
    _run(scenario())


# ---------------------------------------------------------------------------
# DL_INV_04 — lease_s positive
# ---------------------------------------------------------------------------
def test_inv_lease_bound_confirms() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        h = await lock.try_lock("r", "o", lease_s=1)
        assert h is not None
        assert h.lease_s == 1
    _run(scenario())


def test_inv_lease_bound_prevents() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        for bad in (0, -1, -999):
            with pytest.raises(DistributedLockError):
                await lock.try_lock("r", "o", lease_s=bad)
        # Boolean is not an int in this context.
        with pytest.raises(DistributedLockError):
            await lock.try_lock("r", "o", lease_s=True)  # type: ignore[arg-type]
    _run(scenario())


def test_inv_lease_bound_under_failure() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        with pytest.raises(DistributedLockError):
            await lock.try_lock("r", "o", lease_s=10**7)  # above MAX
    _run(scenario())


# ---------------------------------------------------------------------------
# DL_INV_05 — no fairness guarantee
# ---------------------------------------------------------------------------
def test_inv_no_fairness_confirms() -> None:
    """The spec only promises single-holder; fairness is NOT guaranteed."""
    async def scenario() -> None:
        clock = FakeClock()
        lock = InMemoryDistributedLock(clock=clock)
        owners_seen: list[str] = []
        for _ in range(5):
            for i in range(3):
                h = await lock.try_lock("r", f"o{i}", lease_s=1)
                if h is not None:
                    owners_seen.append(h.owner_id)
                    await lock.unlock(h)
            clock.advance(2.0)  # expire anyway
        # Invariant is simply: every acquirer was a registered owner.
        assert all(o.startswith("o") for o in owners_seen)
    _run(scenario())


def test_inv_no_fairness_prevents() -> None:
    # No API call or data field declares fairness.
    lock = InMemoryDistributedLock()
    public_surface = {m for m in dir(lock) if not m.startswith("_")}
    for forbidden in ("acquire_fair", "fair_acquire", "queue_position"):
        assert forbidden not in public_surface


def test_inv_no_fairness_under_failure() -> None:
    """Under contention, order of acquisition is unspecified — at least one
    wins and the others see None. This is the only runtime guarantee."""
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        async def attempt(i: int) -> LockHandle | None:
            return await lock.try_lock("r", f"o{i}", lease_s=60)
        results = await asyncio.gather(*[attempt(i) for i in range(10)])
        winners = [r for r in results if r is not None]
        assert len(winners) == 1
    _run(scenario())
