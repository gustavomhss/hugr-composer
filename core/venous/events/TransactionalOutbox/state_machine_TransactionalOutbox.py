"""Hypothesis state-machine exploration of TransactionalOutbox lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from TransactionalOutbox import (
    InMemoryTransactionalOutbox,
    OutboxMessage,
    TransactionalOutboxInvariantError,
)


class OutboxMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self._acks: dict[str, bool] = {}

        def publisher(m: OutboxMessage) -> bool:
            return self._acks.get(m.message_id, True)

        self.outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
        self.scope = None
        self.key_sequences: dict[str, list[int]] = {}
        self.committed_ids: set[str] = set()

    @rule()
    def begin_op(self) -> None:
        if self.scope is not None:
            try:
                self.outbox.begin()
                raise AssertionError("nested begin accepted")
            except TransactionalOutboxInvariantError:
                return
        self.scope = self.outbox.begin()

    @rule(dest=st.integers(min_value=0, max_value=4), key_tag=st.integers(min_value=0, max_value=3))
    def enqueue_op(self, dest: int, key_tag: int) -> None:
        key = f"K{key_tag}"
        if self.scope is None:
            try:
                self.outbox.enqueue(f"d{dest}", {"n": 1}, key=key)
                raise AssertionError("enqueue outside txn accepted")
            except TransactionalOutboxInvariantError:
                return
        self.outbox.enqueue(f"d{dest}", {"n": 1}, key=key)

    @rule()
    def commit_op(self) -> None:
        if self.scope is None:
            return
        staged = list(self.scope.txn.staged)
        self.scope.commit()
        for m in staged:
            self.key_sequences.setdefault(m.key, []).append(m.sequence)
            self.committed_ids.add(m.message_id)
        self.scope = None

    @rule()
    def rollback_op(self) -> None:
        if self.scope is None:
            return
        self.scope.rollback()
        self.scope = None

    @rule()
    def relay_op(self) -> None:
        if self.scope is not None:
            return  # cannot relay while a txn is open for clarity
        self.outbox.relay_once(limit=50)

    @invariant()
    def per_key_order_preserved(self) -> None:
        if not hasattr(self, "outbox"):
            return
        for _key, seqs in self.key_sequences.items():
            assert seqs == sorted(seqs)

    @invariant()
    def store_contains_only_committed(self) -> None:
        if not hasattr(self, "outbox"):
            return
        stored_ids = {row["message_id"] for row in self.outbox.store_snapshot}
        # All stored ids MUST be committed (no dirty reads of staged rows).
        assert stored_ids.issubset(self.committed_ids)

    @invariant()
    def no_active_txn_after_commit_or_rollback(self) -> None:
        if not hasattr(self, "outbox"):
            return
        if self.scope is None:
            cur = self.outbox.current_transaction
            assert cur is None or not cur.active


# Hypothesis hook
TestOutboxMachine = OutboxMachine.TestCase
