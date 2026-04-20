"""Behavioral end-to-end scenarios for DurableTimer."""

from __future__ import annotations

import asyncio

import pytest

from DurableTimer import (
    DurableTimer,
    DurableTimerError,
    InMemoryTimerService,
    TimerStatus,
)


def test_scenario_schedule_fire_recorded_in_history() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="backoff-1", delay_s=0.5)
    asyncio.run(svc.start(t))
    svc.fire("w-1", "backoff-1")
    log = svc.event_log("w-1")
    assert [e[2] for e in log] == ["scheduled", "fired"]


def test_scenario_cancel_preempts_fire() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="wait-1", delay_s=10)
    asyncio.run(svc.start(t))
    asyncio.run(svc.cancel("w-1", "wait-1"))
    with pytest.raises(DurableTimerError):
        svc.fire("w-1", "wait-1")
    assert svc.status_of("w-1", "wait-1") is TimerStatus.CANCELED


def test_scenario_multiple_timers_per_workflow() -> None:
    svc = InMemoryTimerService()
    for i in range(5):
        asyncio.run(svc.start(DurableTimer(workflow_id="w-1", timer_id=f"t-{i}", delay_s=float(i))))
    svc.fire("w-1", "t-0")
    svc.fire("w-1", "t-2")
    log = svc.event_log("w-1")
    assert sum(1 for e in log if e[2] == "scheduled") == 5
    assert sum(1 for e in log if e[2] == "fired") == 2


def test_scenario_cancel_idempotent() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=1.0)
    asyncio.run(svc.start(t))
    asyncio.run(svc.cancel("w-1", "t-1"))
    asyncio.run(svc.cancel("w-1", "t-1"))  # no error
    assert svc.status_of("w-1", "t-1") is TimerStatus.CANCELED


def test_scenario_cross_workflow_isolation() -> None:
    svc = InMemoryTimerService()
    asyncio.run(svc.start(DurableTimer(workflow_id="w-1", timer_id="t", delay_s=0.0)))
    asyncio.run(svc.start(DurableTimer(workflow_id="w-2", timer_id="t", delay_s=0.0)))
    assert svc.status_of("w-1", "t") is TimerStatus.SCHEDULED
    assert svc.status_of("w-2", "t") is TimerStatus.SCHEDULED
    svc.fire("w-1", "t")
    assert svc.status_of("w-1", "t") is TimerStatus.FIRED
    assert svc.status_of("w-2", "t") is TimerStatus.SCHEDULED
