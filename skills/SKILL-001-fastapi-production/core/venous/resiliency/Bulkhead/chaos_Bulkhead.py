"""Chaos / game-day tests for Bulkhead.

Simulates:
- callable raises → permit must be released.
- callable hangs longer than wait deadline → concurrent callers rejected with
  BulkheadFull; no wrapped invocation after timeout.
- burst of 1000 rejections → counters + meter remain consistent.
- cross-partition flood → unrelated partitions remain healthy.
- cancelled task while holding a permit → permit released, bulkhead reusable.
"""

from __future__ import annotations

import asyncio

import pytest

from Bulkhead import (
    BulkheadFull,
    InMemoryBulkhead,
    PartitionConfig,
    PartitionRegistry,
)


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def test_chaos_callable_always_raises_permits_released() -> None:
    bh = InMemoryBulkhead(name="burn", max_concurrent_calls=3, max_wait_duration_ms=500)

    async def boom() -> None:
        raise OSError("dep flapping")

    async def drive() -> None:
        for _ in range(200):
            with pytest.raises(OSError):
                await bh.submit(boom)

    _run(drive())
    assert bh.in_flight() == 0
    assert bh.available_permits() == 3


def test_chaos_deadline_exceeded_storm_never_admits_second() -> None:
    bh = InMemoryBulkhead(name="storm", max_concurrent_calls=1, max_wait_duration_ms=10)
    started = asyncio.Event()
    block = asyncio.Event()
    invoked: list[int] = []

    async def hang() -> None:
        started.set()
        await block.wait()

    async def should_never_run() -> None:
        invoked.append(1)  # pragma: no cover — BH_INV_02 forbids this path.

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        for _ in range(500):
            with pytest.raises(BulkheadFull):
                await bh.submit(should_never_run)
        block.set()
        await hang_task

    _run(drive())
    assert invoked == []
    assert bh.total_rejected() == 500


def test_chaos_partition_flood_leaves_siblings_healthy() -> None:
    reg = PartitionRegistry()
    noisy = reg.register(
        PartitionConfig("noisy", max_concurrent_calls=1, max_wait_duration_ms=0)
    )
    quiet = reg.register(
        PartitionConfig("quiet", max_concurrent_calls=5, max_wait_duration_ms=1000)
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def work(i: int) -> int:
        return i

    async def drive() -> None:
        hang_task = asyncio.create_task(noisy.submit(hang))
        await started.wait()
        for _ in range(100):
            with pytest.raises(BulkheadFull):
                await noisy.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        results = await asyncio.gather(*(quiet.submit(work, i) for i in range(30)))
        assert sorted(results) == list(range(30))
        block.set()
        await hang_task

    _run(drive())
    assert noisy.total_rejected() == 100
    assert quiet.total_rejected() == 0


def test_chaos_cancelled_submit_releases_permit() -> None:
    bh = InMemoryBulkhead(name="cancel", max_concurrent_calls=1, max_wait_duration_ms=200)

    async def slow() -> None:
        await asyncio.sleep(5.0)

    async def drive() -> None:
        task = asyncio.create_task(bh.submit(slow))
        await asyncio.sleep(0.01)  # allow task to acquire the permit + start sleep
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Permit MUST have been released via the finally branch in submit.
        assert bh.available_permits() == 1

        async def quick() -> str:
            return "ok"

        assert await bh.submit(quick) == "ok"

    _run(drive())


def test_chaos_large_burst_counters_sane() -> None:
    bh = InMemoryBulkhead(name="burst", max_concurrent_calls=4, max_wait_duration_ms=2000)

    async def work(i: int) -> int:
        await asyncio.sleep(0.001)
        return i

    async def drive() -> None:
        total = 500
        results = await asyncio.gather(*(bh.submit(work, i) for i in range(total)))
        assert sorted(results) == list(range(total))
        assert bh.total_admitted() == total
        assert bh.in_flight() == 0
        assert bh.max_observed_in_flight() <= 4

    _run(drive())


def test_chaos_meter_survives_error_path() -> None:
    bh = InMemoryBulkhead(name="meter-err", max_concurrent_calls=1, max_wait_duration_ms=0)
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        # First rejection.
        with pytest.raises(BulkheadFull):
            await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        # Unblock, then more rejections once capacity is freed? No — as soon as
        # hang finishes, future calls admit. Assert meter count is exactly 1.
        block.set()
        await hang_task

    _run(drive())
    assert bh.meter.count_for("meter-err") == 1
