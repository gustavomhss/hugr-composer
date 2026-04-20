"""Behavioral end-to-end scenarios for Bulkhead — proves invariants at runtime."""

from __future__ import annotations

import asyncio

import pytest

from Bulkhead import (
    BulkheadFull,
    InMemoryBulkhead,
    PartitionConfig,
    PartitionRegistry,
    RejectionMeter,
    RequestRejectionLedger,
    snapshot,
)


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def test_scenario_noisy_dependency_does_not_drown_unrelated_traffic() -> None:
    """Nygard Release It! Chapter 5 — one slow dep MUST NOT exhaust another's pool."""
    reg = PartitionRegistry()
    fraud = reg.register(PartitionConfig("fraud", max_concurrent_calls=1, max_wait_duration_ms=0))
    billing = reg.register(
        PartitionConfig("billing", max_concurrent_calls=4, max_wait_duration_ms=1000)
    )

    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def billing_call(i: int) -> int:
        await asyncio.sleep(0.005)
        return i

    async def drive() -> None:
        hang_task = asyncio.create_task(fraud.submit(hang))
        await started.wait()
        # Fraud is fully saturated → rejects.
        with pytest.raises(BulkheadFull):
            await fraud.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        # Billing sails through — isolation holds.
        results = await asyncio.gather(*(billing.submit(billing_call, i) for i in range(20)))
        assert sorted(results) == list(range(20))
        block.set()
        await hang_task

    _run(drive())
    assert billing.total_rejected() == 0
    assert fraud.total_rejected() == 1


def test_scenario_slot_occupancy_respects_capacity_under_load() -> None:
    bh = InMemoryBulkhead(name="pool", max_concurrent_calls=4, max_wait_duration_ms=2000)

    async def work(i: int) -> int:
        await asyncio.sleep(0.005)
        return i

    async def drive() -> None:
        results = await asyncio.gather(*(bh.submit(work, i) for i in range(50)))
        assert sorted(results) == list(range(50))

    _run(drive())
    stats = snapshot(bh)
    assert stats.max_observed_in_flight <= 4
    assert stats.in_flight == 0
    assert stats.total_admitted == 50


def test_scenario_rejection_metric_carries_partition_label() -> None:
    meter = RejectionMeter()
    bh = InMemoryBulkhead(
        name="fraud",
        max_concurrent_calls=1,
        max_wait_duration_ms=0,
        meter=meter,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        for _ in range(3):
            with pytest.raises(BulkheadFull):
                await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        block.set()
        await hang_task

    _run(drive())
    assert [e.partition for e in meter.events] == ["fraud"] * 3


def test_scenario_intra_request_retry_blocked_with_ledger() -> None:
    ledger = RequestRejectionLedger()
    bh = InMemoryBulkhead(
        name="fraud",
        max_concurrent_calls=1,
        max_wait_duration_ms=0,
        ledger=ledger,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        # First attempt rejected → ledger records.
        with pytest.raises(BulkheadFull):
            await bh.submit(lambda: asyncio.sleep(0), request_id="rqA")  # type: ignore[arg-type]
        # Retry inside same request → rejected without even queuing.
        with pytest.raises(BulkheadFull):
            await bh.submit(lambda: asyncio.sleep(0), request_id="rqA")  # type: ignore[arg-type]
        block.set()
        await hang_task

    _run(drive())
    assert ledger.has_rejection("rqA", "fraud")
    assert bh.total_rejected() == 2


def test_scenario_partition_router_dispatches_to_named_partition() -> None:
    reg = PartitionRegistry()
    reg.register(PartitionConfig("fraud", max_concurrent_calls=1, max_wait_duration_ms=1000))
    reg.register(PartitionConfig("billing", max_concurrent_calls=2, max_wait_duration_ms=1000))

    def router(req: dict[str, object]) -> str:
        dep = req.get("dependency")
        return str(dep) if isinstance(dep, str) else "fraud"

    reg.set_router(router)

    async def work(x: int) -> int:
        return x + 1

    async def drive() -> None:
        a = reg.route({"dependency": "fraud"})
        b = reg.route({"dependency": "billing"})
        r1 = await a.submit(work, 10)
        r2 = await b.submit(work, 20)
        assert r1 == 11
        assert r2 == 21
        assert a.name == "fraud"
        assert b.name == "billing"

    _run(drive())


def test_scenario_callable_exception_releases_permit() -> None:
    bh = InMemoryBulkhead(name="errs", max_concurrent_calls=2, max_wait_duration_ms=500)

    async def boom() -> None:
        raise RuntimeError("dep failed")

    async def drive() -> None:
        for _ in range(10):
            with pytest.raises(RuntimeError):
                await bh.submit(boom)
        # After all failures, both permits MUST be free.
        assert bh.available_permits() == 2
        assert bh.in_flight() == 0

    _run(drive())
