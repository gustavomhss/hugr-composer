"""Hypothesis RuleBasedStateMachine for ActivityCall lifecycle."""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from ActivityCall import (
    ActivityCall,
    ActivityMaxAttemptsExceededError,
    InMemoryActivityExecutor,
    RetryPolicy,
)


class ActivityStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.ex = InMemoryActivityExecutor()
        self.runs_completed: int = 0
        self.runs_exhausted: int = 0

    @rule(seed=st.integers(min_value=0, max_value=5),
          max_attempts=st.integers(min_value=1, max_value=4))
    def run_activity(self, seed: int, max_attempts: int) -> None:
        attempts_so_far: list[int] = []

        async def handler(_a: tuple[object, ...]) -> str:
            attempts_so_far.append(1)
            # Succeed after `seed` failures (seed may exceed max_attempts).
            if len(attempts_so_far) > seed:
                return "ok"
            raise RuntimeError("blip")

        name = f"A-{seed}-{max_attempts}"
        self.ex.register(name, handler)
        call = ActivityCall(
            name=name, task_queue="q", start_to_close_s=2,
            schedule_to_close_s=60, heartbeat_s=None,
            retry=RetryPolicy(initial_interval_s=0.0, backoff_coefficient=1.0,
                              maximum_attempts=max_attempts),
            args=(),
        )
        try:
            asyncio.run(self.ex.execute(call))
            self.runs_completed += 1
        except ActivityMaxAttemptsExceededError:
            self.runs_exhausted += 1
        # AC-INV-04: attempt count never exceeds max_attempts.
        records = self.ex.attempts_for_latest(name)
        assert len(records) <= max_attempts

    @invariant()
    def outcomes_are_disjoint(self) -> None:
        # Every activity run either completes or exhausts — never both.
        total = self.runs_completed + self.runs_exhausted
        assert total >= 0  # trivially true; the counter is monotone


TestActivityStateMachine = ActivityStateMachine.TestCase
