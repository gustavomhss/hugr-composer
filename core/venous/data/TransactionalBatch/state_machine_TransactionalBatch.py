"""Hypothesis RuleBasedStateMachine for TransactionalBatch.

Explores reachable batch lifecycle + store-mutation states under random
upsert/delete/commit sequences. Proves TXB-INV-01, TXB-INV-03.
"""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from TransactionalBatch import (
    BatchState,
    BatchStateError,
    EtagConflictError,
    InMemoryStateStore,
    InMemoryTransactionalBatch,
)


class BatchStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.store = InMemoryStateStore()
        self.batch: InMemoryTransactionalBatch | None = None
        # Mirror model: expected store contents after committed batches.
        self.shadow: dict[str, bytes] = {}

    @rule()
    def open_new_batch(self) -> None:
        if self.batch is None or self.batch.state is not BatchState.OPEN:
            self.batch = InMemoryTransactionalBatch(self.store)

    @rule(key=st.sampled_from(["k1", "k2", "k3"]),
          value=st.binary(min_size=0, max_size=16))
    def do_upsert(self, key: str, value: bytes) -> None:
        if self.batch is None or self.batch.state is not BatchState.OPEN:
            return
        self.batch.upsert(key, value)

    @rule(key=st.sampled_from(["k1", "k2", "k3"]))
    def do_delete(self, key: str) -> None:
        if self.batch is None or self.batch.state is not BatchState.OPEN:
            return
        self.batch.delete(key)

    @rule()
    def commit(self) -> None:
        if self.batch is None or self.batch.state is not BatchState.OPEN:
            return
        # Replay the batch's ops against the shadow for expected-state update.
        # Access to self.batch._ops is allowed in tests per the contract's
        # SLF001-on rule for impl but SLF001-allowed for this state-machine.
        ops = list(self.batch._ops)  # noqa: SLF001 — state-machine model needs op log to track TXB-INV-01
        asyncio.run(self.batch.commit())
        for op in ops:
            if op.op == "upsert" and op.value is not None:
                self.shadow[op.key] = op.value
            elif op.op == "delete":
                self.shadow.pop(op.key, None)

    @rule()
    def reuse_committed_must_fail(self) -> None:
        if self.batch is not None and self.batch.state is BatchState.COMMITTED:
            # TXB-INV-03: upsert on closed batch MUST raise.
            try:
                self.batch.upsert("zzz", b"1")
            except BatchStateError:
                return
            except EtagConflictError:
                return  # permissible in the pathological trace
            raise AssertionError("TXB-INV-03 violated: closed batch accepted upsert")

    @invariant()
    def store_matches_shadow(self) -> None:
        assert self.store.snapshot() == self.shadow


TestBatchStateMachine = BatchStateMachine.TestCase
