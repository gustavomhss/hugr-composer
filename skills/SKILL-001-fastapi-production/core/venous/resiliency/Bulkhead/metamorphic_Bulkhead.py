"""Metamorphic + differential tests for Bulkhead.

Algebraic properties:
- available_permits() + in_flight() == capacity at every observable moment.
- snapshot(bulkhead) is idempotent under repeated read — no mutation side effect.
- doubling capacity ⇒ at most 2× concurrent admissions (monotone in capacity).
- rejection count equals meter.count_for(name) for each partition.
- registry.route(r) is functionally equivalent to registry.get(router(r)).
"""

from __future__ import annotations

import asyncio

import pytest

from Bulkhead import (
    BulkheadFull,
    InMemoryBulkhead,
    PartitionConfig,
    PartitionRegistry,
    snapshot,
)


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def test_metamorphic_permits_sum_equals_capacity() -> None:
    bh = InMemoryBulkhead(name="sum", max_concurrent_calls=5, max_wait_duration_ms=1000)

    async def work() -> None:
        await asyncio.sleep(0.001)

    async def drive() -> None:
        tasks = [asyncio.create_task(bh.submit(work)) for _ in range(50)]
        for _ in range(100):
            # Invariant MUST hold on every read.
            assert bh.available_permits() + bh.in_flight() == 5
            await asyncio.sleep(0)
        await asyncio.gather(*tasks)
        assert bh.available_permits() + bh.in_flight() == 5

    _run(drive())


def test_metamorphic_snapshot_is_readonly_projection() -> None:
    bh = InMemoryBulkhead(name="snap", max_concurrent_calls=3, max_wait_duration_ms=100)

    async def work() -> None:
        return None

    async def drive() -> None:
        await bh.submit(work)

    _run(drive())

    s1 = snapshot(bh)
    s2 = snapshot(bh)
    assert s1 == s2
    assert s1.name == "snap"
    assert s1.capacity == 3


def test_metamorphic_capacity_monotone_in_max_observed() -> None:
    """Doubling capacity MUST never shrink the observed peak — more slots = more parallelism."""

    async def run(cap: int) -> int:
        bh = InMemoryBulkhead(
            name=f"cap-{cap}", max_concurrent_calls=cap, max_wait_duration_ms=5000
        )

        async def work() -> None:
            await asyncio.sleep(0.01)

        await asyncio.gather(*(bh.submit(work) for _ in range(20)))
        return bh.max_observed_in_flight()

    async def drive() -> tuple[int, int]:
        return await run(2), await run(4)

    lo, hi = _run(drive())  # type: ignore[misc]
    assert lo <= 2
    assert hi <= 4
    assert hi >= lo  # monotone — never regresses with more capacity


def test_metamorphic_rejection_count_equals_meter_count() -> None:
    bh = InMemoryBulkhead(name="mirror", max_concurrent_calls=1, max_wait_duration_ms=0)
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        for _ in range(7):
            with pytest.raises(BulkheadFull):
                await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        block.set()
        await hang_task

    _run(drive())
    assert bh.total_rejected() == 7
    assert bh.meter.count_for("mirror") == 7


def test_differential_route_equals_get_router_result() -> None:
    reg = PartitionRegistry()
    reg.register(PartitionConfig("a", max_concurrent_calls=1, max_wait_duration_ms=10))
    reg.register(PartitionConfig("b", max_concurrent_calls=1, max_wait_duration_ms=10))

    def router(req: dict[str, object]) -> str:
        return str(req.get("dep", "a"))

    reg.set_router(router)
    r_a = reg.route({"dep": "a"})
    r_b = reg.route({"dep": "b"})
    assert r_a is reg.get("a")
    assert r_b is reg.get("b")
    assert r_a is not r_b  # BH_INV_04 — distinct partitions, distinct instances.
