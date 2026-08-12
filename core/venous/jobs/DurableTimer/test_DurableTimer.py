"""Unit tests for DurableTimer — three per invariant."""

from __future__ import annotations

import asyncio

import pytest
from DurableTimer import (
    DurableTimer,
    DurableTimerError,
    InMemoryTimerService,
    TimerStatus,
)


# ---------------------------------------------------------------------------
# DT_INV_01 — fired timer recorded in the event log
# ---------------------------------------------------------------------------
def test_inv_fire_recorded_confirms() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=0.1)
    asyncio.run(svc.start(t))
    svc.fire("w-1", "t-1")
    events = svc.event_log("w-1")
    kinds = [e[2] for e in events]
    assert kinds == ["scheduled", "fired"]


def test_inv_fire_recorded_prevents() -> None:
    # Firing a timer that was never scheduled MUST raise.
    svc = InMemoryTimerService()
    with pytest.raises(DurableTimerError):
        svc.fire("w-1", "ghost")


def test_inv_fire_recorded_under_failure() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=0.1)
    asyncio.run(svc.start(t))
    svc.fire("w-1", "t-1")
    # Double-fire MUST raise.
    with pytest.raises(DurableTimerError, match="DT-INV-01"):
        svc.fire("w-1", "t-1")


# ---------------------------------------------------------------------------
# DT_INV_02 — wall-clock sleep FORBIDDEN in workflow surface
# ---------------------------------------------------------------------------
def test_inv_no_wallclock_sleep_confirms() -> None:
    svc = InMemoryTimerService()
    public = {m for m in dir(svc) if not m.startswith("_")}
    # Only the declared surface.
    assert {"start", "cancel"}.issubset(public)


def test_inv_no_wallclock_sleep_prevents() -> None:
    svc = InMemoryTimerService()
    public = {m for m in dir(svc) if not m.startswith("_")}
    for forbidden in ("sleep", "wait", "delay", "block", "pause"):
        assert forbidden not in public


def test_inv_no_wallclock_sleep_under_failure() -> None:
    # DurableTimer dataclass has no `.sleep()` method either.
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=0.0)
    public = {m for m in dir(t) if not m.startswith("_")}
    for forbidden in ("sleep", "wait", "wait_for"):
        assert forbidden not in public


# ---------------------------------------------------------------------------
# DT_INV_03 — canceled never fires
# ---------------------------------------------------------------------------
def test_inv_canceled_never_fires_confirms() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=1.0)
    asyncio.run(svc.start(t))
    asyncio.run(svc.cancel("w-1", "t-1"))
    assert svc.status_of("w-1", "t-1") is TimerStatus.CANCELED


def test_inv_canceled_never_fires_prevents() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=1.0)
    asyncio.run(svc.start(t))
    asyncio.run(svc.cancel("w-1", "t-1"))
    with pytest.raises(DurableTimerError, match="DT-INV-03"):
        svc.fire("w-1", "t-1")


def test_inv_canceled_never_fires_under_failure() -> None:
    svc = InMemoryTimerService()
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=1.0)
    asyncio.run(svc.start(t))
    svc.fire("w-1", "t-1")
    # Canceling a fired timer MUST raise (it cannot un-fire).
    with pytest.raises(DurableTimerError, match="DT-INV-03"):
        asyncio.run(svc.cancel("w-1", "t-1"))


# ---------------------------------------------------------------------------
# DT_INV_04 — delay_s non-negative
# ---------------------------------------------------------------------------
def test_inv_delay_nonnegative_confirms() -> None:
    DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=0.0)
    DurableTimer(workflow_id="w-1", timer_id="t-2", delay_s=60.0)


def test_inv_delay_nonnegative_prevents() -> None:
    with pytest.raises(DurableTimerError, match="DT-INV-04"):
        DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=-1.0)
    with pytest.raises(DurableTimerError, match="DT-INV-04"):
        DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=-0.0001)


def test_inv_delay_nonnegative_under_failure() -> None:
    with pytest.raises(DurableTimerError, match="DT-INV-04"):
        DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s="one")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DT_INV_05 — no per-worker cap on concurrent scheduled timers
# ---------------------------------------------------------------------------
def test_inv_no_worker_cap_confirms() -> None:
    svc = InMemoryTimerService()

    async def schedule_many() -> None:
        for i in range(10_000):
            await svc.start(DurableTimer(workflow_id="w-1", timer_id=f"t-{i}", delay_s=0.0))

    asyncio.run(schedule_many())
    # No exception, all scheduled.
    assert len(svc.event_log("w-1")) == 10_000


def test_inv_no_worker_cap_prevents() -> None:
    # No public attribute called max_timers / timer_cap etc.
    svc = InMemoryTimerService()
    public = {m for m in dir(svc) if not m.startswith("_")}
    for forbidden in ("max_timers", "timer_cap", "concurrent_limit"):
        assert forbidden not in public


def test_inv_no_worker_cap_under_failure() -> None:
    svc = InMemoryTimerService()
    # Scheduling the same (workflow, timer_id) twice MUST raise — that is
    # the ONLY legitimate rejection reason at schedule time.
    t = DurableTimer(workflow_id="w-1", timer_id="t-1", delay_s=0.0)
    asyncio.run(svc.start(t))
    with pytest.raises(DurableTimerError):
        asyncio.run(svc.start(t))
