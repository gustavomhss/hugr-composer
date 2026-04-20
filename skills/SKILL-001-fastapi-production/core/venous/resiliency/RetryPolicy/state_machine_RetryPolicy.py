"""Hypothesis state-machine exploration of RetryPolicy lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from RetryPolicy import RetryBudget


class RetryBudgetMachine(RuleBasedStateMachine):
    """Explores RetryBudget state transitions — the shared, concurrent core."""

    @initialize(
        ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        floor=st.integers(min_value=0, max_value=5),
    )
    def setup(self, ratio: float, floor: int) -> None:
        self.budget = RetryBudget(budget_ratio=ratio, min_floor=floor)
        self.ratio = ratio
        self.floor = floor
        self.successes = 0
        self.retries = 0

    @rule()
    def record_success_op(self) -> None:
        self.budget.record_success()
        self.successes += 1

    @rule()
    def try_admit_retry_op(self) -> None:
        allowed = int(self.ratio * self.successes) + self.floor
        admitted = self.budget.try_admit_retry()
        if self.retries < allowed:
            assert admitted is True
            self.retries += 1
        else:
            assert admitted is False

    @invariant()
    def retries_never_exceed_allowance(self) -> None:
        if not hasattr(self, "budget"):
            return
        allowed = int(self.ratio * self.budget.successes) + self.floor
        # The SUT (system under test) may be ahead of our model by at most 0;
        # try_admit_retry atomically increments only if allowed.
        assert self.budget.retries <= allowed

    @invariant()
    def model_matches_sut(self) -> None:
        if not hasattr(self, "budget"):
            return
        assert self.budget.successes == self.successes
        assert self.budget.retries == self.retries


# Hypothesis hook
TestRetryBudgetMachine = RetryBudgetMachine.TestCase
