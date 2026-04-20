"""Hypothesis state-machine exploration of IdempotentConsumer lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from IdempotentConsumer import EchoMessage, build_echo_consumer


class IdempotentConsumerMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.consumer, self.inbox, self.outbox = build_echo_consumer()
        # Ground-truth model: set of keys that have been observed.
        self.seen_keys: set[str] = set()
        # Ground-truth model: total deliveries per key.
        self.deliveries: dict[str, int] = {}

    @rule(key=st.integers(min_value=0, max_value=4))
    def deliver(self, key: int) -> None:
        k = f"k-{key}"
        self.consumer.handle(EchoMessage(id=k))
        self.deliveries[k] = self.deliveries.get(k, 0) + 1
        self.seen_keys.add(k)

    @invariant()
    def effect_runs_equals_distinct_keys(self) -> None:
        if not hasattr(self, "consumer"):
            return
        # IDC-INV-01: one effect per distinct key, regardless of deliveries.
        assert self.consumer.effect_runs == len(self.seen_keys)

    @invariant()
    def inbox_records_one_per_distinct_key(self) -> None:
        if not hasattr(self, "consumer"):
            return
        stored_keys = {r["message_id"] for r in self.inbox.store_snapshot}
        assert stored_keys == self.seen_keys

    @invariant()
    def outbox_has_one_message_per_distinct_key(self) -> None:
        if not hasattr(self, "consumer"):
            return
        # The EchoConsumer emits exactly one outbox message per first delivery.
        assert len(self.outbox.store_snapshot) == len(self.seen_keys)

    @invariant()
    def duplicate_count_equals_redeliveries(self) -> None:
        if not hasattr(self, "consumer"):
            return
        total_deliveries = sum(self.deliveries.values())
        first_deliveries = len(self.seen_keys)
        assert self.consumer.duplicate_calls == total_deliveries - first_deliveries

    @invariant()
    def cache_matches_seen_keys(self) -> None:
        if not hasattr(self, "consumer"):
            return
        cache_keys = {c["key"] for c in self.consumer.cache_snapshot}
        assert cache_keys == self.seen_keys


# Hypothesis hook
TestIdempotentConsumerMachine = IdempotentConsumerMachine.TestCase
