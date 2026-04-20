"""Hypothesis state-machine exploration of TimeoutBudget derivation / expiration."""

from __future__ import annotations

import time

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from TimeoutBudget import (
    MonotonicTimeoutBudget,
    TimeoutBudgetExpired,
    TimeoutBudgetInvariantError,
)


class TimeoutBudgetMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.root = MonotonicTimeoutBudget.from_ms(total_ms=1000, origin="sm")
        self.budget: MonotonicTimeoutBudget = self.root

    @rule(req=st.integers(min_value=1, max_value=5000))
    def derive_step(self, req: int) -> None:
        self.budget = self.budget.derive(child_max_ms=req)
        # TB-INV-04: child deadline NEVER exceeds the root deadline.
        assert self.budget.deadline_ns <= self.root.deadline_ns

    @rule(local=st.integers(min_value=1, max_value=5000))
    def for_call_step(self, local: int) -> None:
        if self.budget.expired():
            try:
                self.budget.for_call(max_ms=local)
                raise AssertionError("expired budget accepted for_call")
            except TimeoutBudgetExpired:
                return
        eff = self.budget.for_call(max_ms=local)
        # TB-INV-01: effective MUST never exceed local.
        assert eff <= local

    @rule()
    def burn_step(self) -> None:
        # Consume a small slice of real time — remaining_ms MUST not grow.
        before = self.budget.remaining_ms()
        time.sleep(0.001)
        after = self.budget.remaining_ms()
        assert after <= before

    @rule()
    def immutability_probe(self) -> None:
        # TB-INV-04: direct writes to frozen fields MUST be rejected.
        try:
            self.budget.deadline_ns = 0  # type: ignore[misc]  # TB-INV-04 probe
            raise AssertionError("frozen field accepted write")
        except TimeoutBudgetInvariantError:
            return

    @invariant()
    def deadline_bounded_by_root(self) -> None:
        if not hasattr(self, "budget"):
            return
        assert self.budget.deadline_ns <= self.root.deadline_ns

    @invariant()
    def remaining_is_nonnegative(self) -> None:
        if not hasattr(self, "budget"):
            return
        assert self.budget.remaining_ms() >= 0


# Hypothesis hook
TestTimeoutBudgetMachine = TimeoutBudgetMachine.TestCase
