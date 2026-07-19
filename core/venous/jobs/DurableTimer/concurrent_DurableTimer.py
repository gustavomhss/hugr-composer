"""Concurrency tests for DurableTimer."""

from __future__ import annotations

import asyncio

import pytest
from DurableTimer import (
    DurableTimer,
    DurableTimerError,
    InMemoryTimerService,
    TimerStatus,
)


def test_concurrent_schedule_many_distinct_timers() -> None:
    svc = InMemoryTimerService()

    async def run() -> None:
        await asyncio.gather(*(
            svc.start(DurableTimer(workflow_id="w", timer_id=f"t-{i}", delay_s=0.0))
            for i in range(200)
        ))

    asyncio.run(run())
    assert len(svc.event_log("w")) == 200


def test_concurrent_cancel_race_once_canceled_always_canceled() -> None:
    svc = InMemoryTimerService()
    asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id="t", delay_s=1.0)))

    async def try_cancel() -> None:
        try:
            await svc.cancel("w", "t")
        except DurableTimerError:
            pass

    async def run() -> None:
        await asyncio.gather(*(try_cancel() for _ in range(20)))

    asyncio.run(run())
    assert svc.status_of("w", "t") is TimerStatus.CANCELED


def test_concurrent_cancel_before_fire_fire_rejected() -> None:
    svc = InMemoryTimerService()
    asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id="t", delay_s=0.1)))
    # Cancel first.
    asyncio.run(svc.cancel("w", "t"))
    with pytest.raises(DurableTimerError):
        svc.fire("w", "t")


def test_concurrent_event_log_serializes_events() -> None:
    svc = InMemoryTimerService()

    async def one(i: int) -> None:
        await svc.start(DurableTimer(workflow_id="w", timer_id=f"t-{i}", delay_s=0.0))

    async def run() -> None:
        await asyncio.gather(*(one(i) for i in range(50)))

    asyncio.run(run())
    log = svc.event_log("w")
    seqs = [e[3] for e in log]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
