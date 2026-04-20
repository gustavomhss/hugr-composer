"""Hypothesis state-machine exploration of Aggregate lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from Aggregate import AggregateInvariantError, OrderAggregate


class AggregateMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.order = OrderAggregate("SM-1", "cust")
        self.successful_commands = 1  # constructor's OrderPlaced event
        self.drained = 0

    @rule(qty=st.integers(min_value=-5, max_value=5), sku=st.text(min_size=1, max_size=5))
    def add_line_op(self, qty: int, sku: str) -> None:
        pre_version = self.order.version
        pre_summary = self.order.line_summary()
        if qty <= 0 or self.order.line_count >= OrderAggregate.MAX_LINES:
            try:
                self.order.add_line(sku, qty)
                raise AssertionError("illegal command unexpectedly accepted")
            except AggregateInvariantError:
                # AGG-INV-03: version MUST NOT move; state MUST be the prior snapshot.
                assert self.order.version == pre_version
                assert self.order.line_summary() == pre_summary
                return
        self.order.add_line(sku, qty)
        self.successful_commands += 1

    @rule()
    def drain_op(self) -> None:
        events = list(self.order.pull_events())
        self.drained += len(events)

    @invariant()
    def version_monotonic(self) -> None:
        if not hasattr(self, "order"):
            return
        # Version equals number of successful mutations.
        assert self.order.version == self.successful_commands

    @invariant()
    def bounded_lines(self) -> None:
        if not hasattr(self, "order"):
            return
        assert self.order.line_count <= OrderAggregate.MAX_LINES

    @invariant()
    def line_invariant_holds(self) -> None:
        if not hasattr(self, "order"):
            return
        # Every exposed line MUST have positive qty (AGG-INV-03).
        for _sku, qty in self.order.line_summary():
            assert qty > 0


# Hypothesis hook
TestAggregateMachine = AggregateMachine.TestCase
