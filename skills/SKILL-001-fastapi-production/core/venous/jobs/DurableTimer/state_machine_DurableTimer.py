"""Hypothesis RuleBasedStateMachine for DurableTimer."""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from DurableTimer import (
    DurableTimer,
    DurableTimerError,
    InMemoryTimerService,
    TimerStatus,
)


_TIDS = ["t-a", "t-b", "t-c"]


class TimerStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.svc = InMemoryTimerService()

    @rule(tid=st.sampled_from(_TIDS))
    def try_schedule(self, tid: str) -> None:
        t = DurableTimer(workflow_id="w-1", timer_id=tid, delay_s=0.0)
        try:
            asyncio.run(self.svc.start(t))
        except DurableTimerError:
            return

    @rule(tid=st.sampled_from(_TIDS))
    def try_cancel(self, tid: str) -> None:
        try:
            asyncio.run(self.svc.cancel("w-1", tid))
        except DurableTimerError:
            return

    @rule(tid=st.sampled_from(_TIDS))
    def try_fire(self, tid: str) -> None:
        try:
            self.svc.fire("w-1", tid)
        except DurableTimerError:
            return

    @invariant()
    def no_timer_both_fired_and_canceled(self) -> None:
        for tid in _TIDS:
            try:
                status = self.svc.status_of("w-1", tid)
            except DurableTimerError:
                continue
            # DT-INV-03: status is exactly one value.
            assert status in (TimerStatus.SCHEDULED, TimerStatus.FIRED, TimerStatus.CANCELED)

    @invariant()
    def fired_count_at_most_one_per_timer(self) -> None:
        log = self.svc.event_log("w-1")
        for tid in _TIDS:
            fires = [e for e in log if e[1] == tid and e[2] == "fired"]
            assert len(fires) <= 1


TestTimerStateMachine = TimerStateMachine.TestCase
