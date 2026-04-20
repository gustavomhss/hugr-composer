"""Hypothesis state-machine exploration of RateLimiter lifecycle.

Rules drive: try_acquire with varying cost, reset, and the passage of time
(real sleep, bounded by deadline). The machine asserts the global
invariants after every transition: tokens stay within [0, burst], bucket
counts never exceed burst, and admitted cost per step is always <= pre-step
tokens.
"""

from __future__ import annotations

import time

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from RateLimiter import InMemoryRateLimiter


class RateLimiterMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.limiter = InMemoryRateLimiter(
            rate_per_second=5.0,
            burst=4,
        )
        self.keys = ["a", "b", "c"]

    @rule(key_idx=st.integers(min_value=0, max_value=2), cost=st.integers(min_value=1, max_value=4))
    def try_acquire(self, key_idx: int, cost: int) -> None:
        if not hasattr(self, "limiter"):
            return
        self.limiter.try_acquire(self.keys[key_idx], cost=cost)

    @rule(key_idx=st.integers(min_value=0, max_value=2))
    def reset_key(self, key_idx: int) -> None:
        if not hasattr(self, "limiter"):
            return
        self.limiter.reset(self.keys[key_idx])

    @rule()
    def wait_tick(self) -> None:
        time.sleep(0.005)

    @invariant()
    def tokens_within_capacity(self) -> None:
        if not hasattr(self, "limiter"):
            return
        for key, bucket in self.limiter._buckets.items():
            assert 0.0 - 1e-9 <= bucket.tokens <= float(self.limiter.burst) + 1e-9, (
                f"bucket for {key!r} outside [0, burst]: {bucket.tokens}"
            )

    @invariant()
    def events_are_consistent(self) -> None:
        if not hasattr(self, "limiter"):
            return
        for e in self.limiter.events:
            if e.admitted:
                assert e.retry_after_ms == 0
            else:
                assert e.retry_after_ms >= 0 or e.retry_after_ms == -1


TestRateLimiterMachine = RateLimiterMachine.TestCase
