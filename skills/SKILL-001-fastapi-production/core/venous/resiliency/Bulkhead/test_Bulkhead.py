"""Unit tests for Bulkhead — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest

from Bulkhead import (
    BulkheadFull,
    BulkheadInvariantError,
    InMemoryBulkhead,
    PartitionConfig,
    PartitionRegistry,
    RejectionMeter,
    RequestRejectionLedger,
)


def _run(coro: object) -> object:
    """Execute ``coro`` on a fresh asyncio loop (keeps tests synchronous)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# BH_INV_01 — capacity ceiling: in_flight NEVER exceeds max_concurrent_calls
# ---------------------------------------------------------------------------
def test_inv_capacity_ceiling_confirms() -> None:
    bh = InMemoryBulkhead(
        name="fraud",
        max_concurrent_calls=3,
        max_wait_duration_ms=1000,
    )
    peak = {"value": 0}

    async def work() -> int:
        n = bh.in_flight()
        if n > peak["value"]:
            peak["value"] = n
        await asyncio.sleep(0.01)
        return n

    async def drive() -> None:
        results = await asyncio.gather(*(bh.submit(work) for _ in range(10)))
        assert all(r <= 3 for r in results)

    _run(drive())
    assert peak["value"] <= 3
    assert bh.max_observed_in_flight() <= 3


def test_inv_capacity_ceiling_prevents() -> None:
    bh = InMemoryBulkhead(
        name="prevent",
        max_concurrent_calls=1,
        max_wait_duration_ms=0,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hold() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hold_task = asyncio.create_task(bh.submit(hold))
        await started.wait()
        # Second attempt MUST be rejected — capacity already saturated.
        with pytest.raises(BulkheadFull):
            await bh.submit(hold)
        block.set()
        await hold_task

    _run(drive())
    assert bh.total_rejected() == 1
    assert bh.in_flight() == 0


def test_inv_capacity_ceiling_under_failure() -> None:
    # Even when the wrapped fn raises, the permit MUST be released so the
    # ceiling is not eroded by leaked slots.
    bh = InMemoryBulkhead(
        name="burn",
        max_concurrent_calls=2,
        max_wait_duration_ms=500,
    )

    async def boom() -> None:
        raise RuntimeError("dep crashed")

    async def drive() -> None:
        for _ in range(20):
            with pytest.raises(RuntimeError):
                await bh.submit(boom)

    _run(drive())
    assert bh.in_flight() == 0
    assert bh.available_permits() == 2


# ---------------------------------------------------------------------------
# BH_INV_02 — wait deadline: beyond max_wait_duration_ms ⇒ BulkheadFull
# ---------------------------------------------------------------------------
def test_inv_wait_deadline_confirms() -> None:
    bh = InMemoryBulkhead(
        name="wait-ok",
        max_concurrent_calls=1,
        max_wait_duration_ms=200,
    )

    async def work() -> str:
        await asyncio.sleep(0.05)
        return "ok"

    async def drive() -> None:
        # Two sequential calls within the deadline both succeed.
        r1 = await bh.submit(work)
        r2 = await bh.submit(work)
        assert r1 == r2 == "ok"

    _run(drive())
    assert bh.total_admitted() == 2
    assert bh.total_rejected() == 0


def test_inv_wait_deadline_prevents() -> None:
    bh = InMemoryBulkhead(
        name="wait-miss",
        max_concurrent_calls=1,
        max_wait_duration_ms=30,
    )
    started = asyncio.Event()
    block = asyncio.Event()
    invoked: list[int] = []

    async def slow() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hold_task = asyncio.create_task(bh.submit(slow))
        await started.wait()

        async def never_run() -> None:
            invoked.append(1)

        with pytest.raises(BulkheadFull):
            await bh.submit(never_run)
        block.set()
        await hold_task

    _run(drive())
    # BH_INV_02: wrapped callable MUST NOT be invoked on timeout rejection.
    assert invoked == []
    assert bh.total_rejected() == 1


def test_inv_wait_deadline_under_failure() -> None:
    # Repeated deadline-exceeded rejections MUST keep the counter stable
    # (no permit leaks, no double-admission, no silent success).
    bh = InMemoryBulkhead(
        name="wait-storm",
        max_concurrent_calls=1,
        max_wait_duration_ms=10,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hold() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hold_task = asyncio.create_task(bh.submit(hold))
        await started.wait()
        for _ in range(25):
            with pytest.raises(BulkheadFull):
                await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type, return-value]
        block.set()
        await hold_task

    _run(drive())
    assert bh.total_rejected() == 25
    assert bh.in_flight() == 0
    # BH_INV_05 ties in: every rejection is metered with partition label.
    assert bh.meter.count_for("wait-storm") == 25


# ---------------------------------------------------------------------------
# BH_INV_03 — no intra-request retry
# ---------------------------------------------------------------------------
def test_inv_no_intra_request_retry_confirms() -> None:
    ledger = RequestRejectionLedger()
    bh = InMemoryBulkhead(
        name="alpha",
        max_concurrent_calls=1,
        max_wait_duration_ms=5,
        ledger=ledger,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hold() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hold_task = asyncio.create_task(bh.submit(hold))
        await started.wait()
        with pytest.raises(BulkheadFull):
            await bh.submit(lambda: asyncio.sleep(0), request_id="req-1")  # type: ignore[arg-type]
        block.set()
        await hold_task

    _run(drive())
    assert ledger.has_rejection("req-1", "alpha")


def test_inv_no_intra_request_retry_prevents() -> None:
    ledger = RequestRejectionLedger()
    ledger.record("req-7", "payments")
    bh = InMemoryBulkhead(
        name="payments",
        max_concurrent_calls=4,
        max_wait_duration_ms=500,
        ledger=ledger,
    )

    async def work() -> str:
        return "ok"

    async def drive() -> None:
        with pytest.raises(BulkheadFull):
            await bh.submit(work, request_id="req-7")

    _run(drive())
    assert bh.total_rejected() == 1


def test_inv_no_intra_request_retry_under_failure() -> None:
    ledger = RequestRejectionLedger()
    bh = InMemoryBulkhead(
        name="notify",
        max_concurrent_calls=1,
        max_wait_duration_ms=0,
        ledger=ledger,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hold() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hold_task = asyncio.create_task(bh.submit(hold))
        await started.wait()
        for _ in range(5):
            with pytest.raises(BulkheadFull):
                await bh.submit(
                    lambda: asyncio.sleep(0),  # type: ignore[arg-type]
                    request_id="req-x",
                )
        block.set()
        await hold_task

    _run(drive())
    # Ledger entry persists — BH_INV_03 is idempotent under repeated attempts.
    assert ledger.has_rejection("req-x", "notify")


# ---------------------------------------------------------------------------
# BH_INV_04 — partition isolation
# ---------------------------------------------------------------------------
def test_inv_partition_isolation_confirms() -> None:
    reg = PartitionRegistry()
    a = reg.register(PartitionConfig("fraud", max_concurrent_calls=2, max_wait_duration_ms=10))
    b = reg.register(PartitionConfig("billing", max_concurrent_calls=3, max_wait_duration_ms=10))
    assert a is not b
    assert a.max_concurrent_calls == 2
    assert b.max_concurrent_calls == 3
    assert a.available_permits() == 2
    assert b.available_permits() == 3


def test_inv_partition_isolation_prevents() -> None:
    reg = PartitionRegistry()
    reg.register(PartitionConfig("fraud", max_concurrent_calls=1, max_wait_duration_ms=0))
    with pytest.raises(BulkheadInvariantError):
        reg.register(PartitionConfig("fraud", max_concurrent_calls=99, max_wait_duration_ms=0))
    with pytest.raises(BulkheadInvariantError):
        reg.get("ghost-partition")


def test_inv_partition_isolation_under_failure() -> None:
    # Exhausting partition A MUST NOT affect partition B's permit count.
    reg = PartitionRegistry()
    a = reg.register(PartitionConfig("fraud", max_concurrent_calls=1, max_wait_duration_ms=0))
    b = reg.register(PartitionConfig("billing", max_concurrent_calls=2, max_wait_duration_ms=500))
    started = asyncio.Event()
    block = asyncio.Event()

    async def hold() -> None:
        started.set()
        await block.wait()

    async def work() -> str:
        await asyncio.sleep(0.01)
        return "b-ok"

    async def drive() -> None:
        hold_task = asyncio.create_task(a.submit(hold))
        await started.wait()
        # A is saturated → reject; B must still admit freely.
        with pytest.raises(BulkheadFull):
            await a.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        r1, r2 = await asyncio.gather(b.submit(work), b.submit(work))
        assert r1 == r2 == "b-ok"
        block.set()
        await hold_task

    _run(drive())
    assert a.total_rejected() == 1
    assert b.total_rejected() == 0


# ---------------------------------------------------------------------------
# BH_INV_05 — rejection metric labelled with partition name
# ---------------------------------------------------------------------------
def test_inv_rejection_metric_confirms() -> None:
    meter = RejectionMeter()
    bh = InMemoryBulkhead(
        name="inventory",
        max_concurrent_calls=1,
        max_wait_duration_ms=0,
        meter=meter,
    )
    started = asyncio.Event()
    block = asyncio.Event()

    async def hold() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hold_task = asyncio.create_task(bh.submit(hold))
        await started.wait()
        with pytest.raises(BulkheadFull):
            await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        block.set()
        await hold_task

    _run(drive())
    events = meter.events
    assert len(events) == 1
    assert events[0].partition == "inventory"


def test_inv_rejection_metric_prevents() -> None:
    # A meter MUST refuse to record a rejection without a partition label.
    meter = RejectionMeter()
    with pytest.raises(BulkheadInvariantError):
        meter.record("", "wait_timeout")


def test_inv_rejection_metric_under_failure() -> None:
    # Two partitions sharing a single meter produce two DISTINCT labels.
    meter = RejectionMeter()
    a = InMemoryBulkhead("a", max_concurrent_calls=1, max_wait_duration_ms=0, meter=meter)
    b = InMemoryBulkhead("b", max_concurrent_calls=1, max_wait_duration_ms=0, meter=meter)
    started_a, block_a = asyncio.Event(), asyncio.Event()
    started_b, block_b = asyncio.Event(), asyncio.Event()

    async def hold_a() -> None:
        started_a.set()
        await block_a.wait()

    async def hold_b() -> None:
        started_b.set()
        await block_b.wait()

    async def drive() -> None:
        ta = asyncio.create_task(a.submit(hold_a))
        tb = asyncio.create_task(b.submit(hold_b))
        await started_a.wait()
        await started_b.wait()
        with pytest.raises(BulkheadFull):
            await a.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        with pytest.raises(BulkheadFull):
            await b.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        block_a.set()
        block_b.set()
        await ta
        await tb

    _run(drive())
    labels = {e.partition for e in meter.events}
    assert labels == {"a", "b"}


# ---------------------------------------------------------------------------
# Public ``acquire()`` context manager — same invariants as ``submit``
# ---------------------------------------------------------------------------
def test_acquire_holds_permit_for_body_and_releases() -> None:
    """``async with acquire()`` increments in_flight for the body, decrements on exit."""
    bh = InMemoryBulkhead("q", max_concurrent_calls=2, max_wait_duration_ms=0)

    async def drive() -> None:
        assert bh.in_flight() == 0
        async with bh.acquire():
            assert bh.in_flight() == 1
            async with bh.acquire():
                assert bh.in_flight() == 2
            assert bh.in_flight() == 1
        assert bh.in_flight() == 0

    _run(drive())
    # Both permits were accounted.
    assert bh.total_admitted() == 2
    assert bh.total_rejected() == 0


def test_acquire_rejects_at_capacity_with_zero_wait() -> None:
    """Second concurrent acquire on a cap-1 partition with wait=0 MUST raise BulkheadFull."""
    bh = InMemoryBulkhead("q", max_concurrent_calls=1, max_wait_duration_ms=0)
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold_one() -> None:
        async with bh.acquire():
            started.set()
            await release.wait()

    async def drive() -> None:
        t = asyncio.create_task(hold_one())
        await started.wait()
        with pytest.raises(BulkheadFull):
            async with bh.acquire():
                raise AssertionError("body entered despite BulkheadFull expected")
        release.set()
        await t

    _run(drive())
    assert bh.total_rejected() == 1


def test_acquire_releases_permit_on_body_exception() -> None:
    """Exception inside the ``async with`` body MUST NOT leak the permit."""
    bh = InMemoryBulkhead("q", max_concurrent_calls=1, max_wait_duration_ms=0)

    async def drive() -> None:
        with pytest.raises(ValueError):
            async with bh.acquire():
                assert bh.in_flight() == 1
                raise ValueError("boom")
        assert bh.in_flight() == 0
        # Subsequent acquire succeeds — proves the permit was returned.
        async with bh.acquire():
            assert bh.in_flight() == 1

    _run(drive())
    assert bh.total_admitted() == 2


def test_acquire_honours_request_ledger_anti_retry() -> None:
    """Once a (request_id, partition) is rejected, further acquires for that request MUST fail fast."""
    ledger = RequestRejectionLedger()
    bh = InMemoryBulkhead(
        "q",
        max_concurrent_calls=1,
        max_wait_duration_ms=0,
        ledger=ledger,
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        async with bh.acquire():
            started.set()
            await release.wait()

    async def drive() -> None:
        t = asyncio.create_task(hold())
        await started.wait()
        # First attempt — capacity rejection records in ledger (wait_timeout).
        with pytest.raises(BulkheadFull):
            async with bh.acquire(request_id="req-42"):
                raise AssertionError("body entered despite BulkheadFull")
        # Now the partition is free again…
        release.set()
        await t
        assert bh.in_flight() == 0
        # …but the SAME request_id MUST still be rejected (BH_INV_03).
        with pytest.raises(BulkheadFull) as excinfo:
            async with bh.acquire(request_id="req-42"):
                raise AssertionError("retry should not have been admitted")
        assert "intra-request retry is FORBIDDEN" in str(excinfo.value)

    _run(drive())
    # One wait_timeout + one retry_forbidden = 2 recorded rejections.
    assert bh.total_rejected() == 2


def test_submit_is_sugar_over_acquire() -> None:
    """``submit(fn)`` must be observationally indistinguishable from ``async with acquire(): fn()``."""
    bh = InMemoryBulkhead("q", max_concurrent_calls=5, max_wait_duration_ms=0)

    sentinel = object()

    async def fn_a() -> object:
        return sentinel

    async def fn_b() -> object:
        async with bh.acquire():
            return sentinel

    async def drive() -> None:
        assert await bh.submit(fn_a) is sentinel
        assert await fn_b() is sentinel
        # Both paths incremented total_admitted once.
        assert bh.total_admitted() == 2

    _run(drive())
