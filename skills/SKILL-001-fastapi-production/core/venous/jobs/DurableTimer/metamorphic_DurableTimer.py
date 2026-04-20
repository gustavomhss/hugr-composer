"""Metamorphic + differential tests for DurableTimer."""

from __future__ import annotations

import asyncio

from DurableTimer import (
    DurableTimer,
    InMemoryTimerService,
)


def test_metamorphic_schedule_then_cancel_no_fire_event() -> None:
    svc = InMemoryTimerService()
    asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id="t", delay_s=0.0)))
    asyncio.run(svc.cancel("w", "t"))
    assert not any(e[2] == "fired" for e in svc.event_log("w"))


def test_metamorphic_event_log_append_only() -> None:
    svc = InMemoryTimerService()
    asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id="t", delay_s=0.0)))
    before = svc.event_log("w")
    svc.fire("w", "t")
    after = svc.event_log("w")
    assert len(after) == len(before) + 1
    for i, e in enumerate(before):
        assert after[i] == e


def test_differential_two_services_same_actions_same_log() -> None:
    a = InMemoryTimerService()
    b = InMemoryTimerService()
    for svc in (a, b):
        asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id="t", delay_s=0.0)))
        svc.fire("w", "t")
    assert [e[1:] for e in a.event_log("w")] == [e[1:] for e in b.event_log("w")]


def test_metamorphic_cross_workflow_no_event_leak() -> None:
    svc = InMemoryTimerService()
    asyncio.run(svc.start(DurableTimer(workflow_id="w-1", timer_id="t", delay_s=0.0)))
    asyncio.run(svc.start(DurableTimer(workflow_id="w-2", timer_id="t", delay_s=0.0)))
    log_w1 = svc.event_log("w-1")
    log_w2 = svc.event_log("w-2")
    # Events carry their workflow_id and belong only to that workflow's log.
    assert all(e[0] == "w-1" for e in log_w1)
    assert all(e[0] == "w-2" for e in log_w2)


def test_metamorphic_sequence_numbers_monotone() -> None:
    svc = InMemoryTimerService()
    for i in range(5):
        asyncio.run(svc.start(DurableTimer(workflow_id="w", timer_id=f"t-{i}", delay_s=0.0)))
    log = svc.event_log("w")
    seqs = [e[3] for e in log]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
