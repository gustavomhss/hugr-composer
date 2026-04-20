"""Concurrency / linearizability harness for Bulkhead.

Confirms that concurrent admissions and rejections keep the in-flight counter
bounded by capacity at every observable moment (BH_INV_01) and that every
rejection is metered (BH_INV_05) under race.
"""

from __future__ import annotations

import asyncio

from Bulkhead import InMemoryBulkhead, PartitionConfig, PartitionRegistry


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def test_concurrent_admissions_never_exceed_capacity() -> None:
    bh = InMemoryBulkhead(name="rc", max_concurrent_calls=5, max_wait_duration_ms=5000)
    peak: list[int] = [0]

    async def work() -> None:
        n = bh.in_flight()
        if n > peak[0]:
            peak[0] = n
        await asyncio.sleep(0.002)

    async def drive() -> None:
        # 200 callers, capacity 5 → some admitted, some wait, some rejected.
        await asyncio.gather(*(bh.submit(work) for _ in range(200)))

    _run(drive())
    assert peak[0] <= 5
    assert bh.max_observed_in_flight() <= 5
    assert bh.in_flight() == 0


def test_concurrent_rejection_storm_meter_accurate() -> None:
    bh = InMemoryBulkhead(name="storm", max_concurrent_calls=1, max_wait_duration_ms=5)
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def try_enter() -> bool:
        try:
            await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        except Exception:
            return False
        return True

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        outcomes = await asyncio.gather(
            *(try_enter() for _ in range(60)), return_exceptions=False
        )
        rejections = sum(1 for ok in outcomes if ok is False)
        assert rejections >= 1  # at least some MUST be rejected
        block.set()
        await hang_task
        assert bh.meter.count_for("storm") == rejections

    _run(drive())


def test_concurrent_cross_partition_isolation_under_race() -> None:
    reg = PartitionRegistry()
    a = reg.register(PartitionConfig("a", max_concurrent_calls=2, max_wait_duration_ms=5000))
    b = reg.register(PartitionConfig("b", max_concurrent_calls=3, max_wait_duration_ms=5000))

    async def work(x: int) -> int:
        await asyncio.sleep(0.001)
        return x

    async def drive() -> None:
        tasks_a = [a.submit(work, i) for i in range(40)]
        tasks_b = [b.submit(work, i) for i in range(40)]
        ra, rb = await asyncio.gather(
            asyncio.gather(*tasks_a), asyncio.gather(*tasks_b)
        )
        assert sorted(ra) == list(range(40))
        assert sorted(rb) == list(range(40))

    _run(drive())
    # BH_INV_01 under race: observed peaks MUST NOT exceed per-partition capacity.
    assert a.max_observed_in_flight() <= 2
    assert b.max_observed_in_flight() <= 3
    assert a.total_rejected() == 0
    assert b.total_rejected() == 0


def test_concurrent_invariant_linearizable_snapshot() -> None:
    """At every observation, available + in_flight == capacity (linearizable)."""
    bh = InMemoryBulkhead(name="lin", max_concurrent_calls=4, max_wait_duration_ms=3000)

    async def work() -> None:
        await asyncio.sleep(0.001)

    async def observer() -> None:
        for _ in range(500):
            assert bh.available_permits() + bh.in_flight() == 4
            await asyncio.sleep(0)

    async def drive() -> None:
        obs = asyncio.create_task(observer())
        await asyncio.gather(*(bh.submit(work) for _ in range(60)))
        await obs

    _run(drive())
