"""Chaos / fault-injection for DurableTimer."""

from __future__ import annotations

import asyncio

import pytest

from DurableTimer import (
    DurableTimer,
    DurableTimerError,
    InMemoryTimerService,
)


def test_chaos_very_large_delay_accepted() -> None:
    t = DurableTimer(workflow_id="w", timer_id="t", delay_s=10**9)
    assert t.delay_s == 10**9


def test_chaos_float_precision_delays() -> None:
    for d in (0.0, 0.001, 1e-9, 1.5, 86400.0):
        t = DurableTimer(workflow_id="w", timer_id="t", delay_s=d)
        assert t.delay_s == d


def test_chaos_cancel_ghost_timer_errors() -> None:
    svc = InMemoryTimerService()
    with pytest.raises(DurableTimerError):
        asyncio.run(svc.cancel("w", "ghost"))


def test_chaos_rapid_schedule_then_fire_many() -> None:
    svc = InMemoryTimerService()
    for i in range(100):
        asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id=f"t-{i}", delay_s=0.0)))
        svc.fire("w", f"t-{i}")
    log = svc.event_log("w")
    assert sum(1 for e in log if e[2] == "fired") == 100


def test_chaos_fire_after_cancel_always_rejected() -> None:
    svc = InMemoryTimerService()
    for i in range(10):
        asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id=f"t-{i}", delay_s=1.0)))
        asyncio.run(svc.cancel("w", f"t-{i}"))
        with pytest.raises(DurableTimerError):
            svc.fire("w", f"t-{i}")


def test_chaos_duplicate_schedule_rejected() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w", timer_id="t", delay_s=0.0)
    asyncio.run(svc.start(t))
    with pytest.raises(DurableTimerError):
        asyncio.run(svc.start(t))
