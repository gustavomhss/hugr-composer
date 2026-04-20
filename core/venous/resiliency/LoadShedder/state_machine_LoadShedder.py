"""Hypothesis state-machine exploration of LoadShedder.

Rules:
- admit requests at any priority under any pressure
- advance the fake clock
- mutate pressure signals arbitrarily

Invariants checked after every step:
- LSH-INV-01: last admission respects the cutoff AT DECISION TIME
- LSH-INV-03: cutoff change count never exceeds ticks / control_interval
- LSH-INV-05: current_cutoff() is always a valid priority
"""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from LoadShedder import InMemoryLoadShedder, Priority

_PRIORITIES: tuple[Priority, ...] = ("critical", "normal", "sheddable_plus", "sheddable")
_RANK: dict[str, int] = {"critical": 0, "normal": 1, "sheddable_plus": 2, "sheddable": 3}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


class LoadShedderMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.clock = _Clock()
        self.shedder = InMemoryLoadShedder(clock=self.clock, control_interval_ms=50)
        # Track cutoff changes per control-interval bucket.
        self.cutoff_changes: int = 0
        self.prev_cutoff: Priority = self.shedder.current_cutoff()
        self.total_ticks: float = 0.0

    @rule(
        priority=st.sampled_from(_PRIORITIES),
        queue_depth=st.integers(min_value=0, max_value=500),
        cpu=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    def admit_op(self, priority: Priority, queue_depth: int, cpu: float) -> None:
        if not hasattr(self, "shedder"):
            return
        before = self.shedder.current_cutoff()
        decision = self.shedder.admit(priority, queue_depth, cpu)
        after = self.shedder.current_cutoff()
        # LSH-INV-01: if admitted, priority rank <= cutoff rank AT DECISION TIME.
        # Use the post-decision cutoff as the decision cutoff (they match in
        # our impl because cutoff update happens inside the same critical section).
        if decision:
            assert _RANK[priority] <= _RANK[after]
        else:
            assert _RANK[priority] > _RANK[after]
        if before != after:
            self.cutoff_changes += 1

    @rule(dt=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    def tick(self, dt: float) -> None:
        if not hasattr(self, "clock"):
            return
        self.clock.advance(dt)
        self.total_ticks += dt

    @invariant()
    def cutoff_is_valid(self) -> None:
        if not hasattr(self, "shedder"):
            return
        assert self.shedder.current_cutoff() in _PRIORITIES

    @invariant()
    def shed_rate_bounded(self) -> None:
        if not hasattr(self, "shedder"):
            return
        r = self.shedder.shed_rate()
        assert 0.0 <= r <= 1.0

    @invariant()
    def hysteresis_bounded(self) -> None:
        # LSH-INV-03: number of cutoff changes is bounded by time / control_interval.
        if not hasattr(self, "shedder"):
            return
        # control_interval_ms = 50 → 0.05s. Allow one extra for the initial boundary.
        max_changes = int(self.total_ticks / 0.05) + 2
        assert self.cutoff_changes <= max_changes


TestLoadShedderMachine = LoadShedderMachine.TestCase
