"""Hypothesis state-machine exploration of CircuitBreaker lifecycle.

Reaches every state (closed / open / half_open) via the outcome-hook and
allow_probe APIs and asserts the global state invariants after each step.
"""

from __future__ import annotations

import time

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from CircuitBreaker import STATES, InMemoryCircuitBreaker


class CircuitBreakerMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.breaker = InMemoryCircuitBreaker(
            "svc",
            minimum_number_of_calls=2,
            cooldown_ms=5,
            permitted_calls_in_half_open=2,
            window_size=4,
        )

    @rule(ok=st.booleans())
    def record_outcome(self, ok: bool) -> None:
        if not hasattr(self, "breaker"):
            return
        if ok:
            self.breaker.on_success(1.0)
        else:
            self.breaker.on_failure(RuntimeError("x"), 1.0)

    @rule()
    def force_open_op(self) -> None:
        if not hasattr(self, "breaker"):
            return
        self.breaker.force_open("hypothesis")

    @rule()
    def probe_op(self) -> None:
        if not hasattr(self, "breaker"):
            return
        self.breaker.allow_probe()

    @rule()
    def wait_tick(self) -> None:
        # Let the cooldown window elapse occasionally so open->half_open is reachable.
        time.sleep(0.01)

    @invariant()
    def state_in_enum(self) -> None:
        if not hasattr(self, "breaker"):
            return
        assert self.breaker.state in STATES

    @invariant()
    def probes_are_bounded(self) -> None:
        if not hasattr(self, "breaker"):
            return
        assert 0 <= self.breaker._probes_in_flight <= self.breaker._permitted_calls_in_half_open

    @invariant()
    def open_has_no_probes(self) -> None:
        if not hasattr(self, "breaker"):
            return
        if self.breaker.state == "open":
            assert self.breaker._probes_in_flight == 0


# Hypothesis hook
TestCircuitBreakerMachine = CircuitBreakerMachine.TestCase
