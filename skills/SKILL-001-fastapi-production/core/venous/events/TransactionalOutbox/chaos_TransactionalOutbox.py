"""Chaos / game-day tests for TransactionalOutbox.

Simulates broker outages, partial failures, relay crashes, and concurrent
transactions to confirm the outbox never enters an inconsistent state.
"""

from __future__ import annotations

import threading

import pytest

from TransactionalOutbox import (
    InMemoryTransactionalOutbox,
    OutboxMessage,
    OutboxTransaction,
    TransactionalOutboxInvariantError,
)


def test_chaos_broker_always_nacks_keeps_retryable() -> None:
    """Broker NACKs every message → all rows remain in `failed` (retryable)."""

    def nacker(_m: OutboxMessage) -> bool:
        return False

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=nacker)
    with outbox.begin() as scope:
        for i in range(5):
            outbox.enqueue("evt", {"n": i}, key=f"k{i}")
        scope.commit()

    for _ in range(10):
        outbox.relay_once()
    snap = outbox.store_snapshot
    assert all(row["status"] == "failed" for row in snap)
    # All rows are still retryable by a future relay pass.
    assert all(row["attempts"] >= 10 for row in snap)


def test_chaos_publisher_raises_is_captured_as_failure() -> None:
    def angry(_m: OutboxMessage) -> bool:
        raise RuntimeError("broker unreachable")

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=angry)
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()

    outbox.relay_once()
    [row] = outbox.store_snapshot
    assert row["status"] == "failed"
    assert "broker unreachable" in str(row["failed_reason"])


def test_chaos_state_flush_failure_discards_staged_rows() -> None:
    def fail(_t: OutboxTransaction) -> None:
        raise OSError("disk full")

    outbox = InMemoryTransactionalOutbox(state_flush_fn=fail)
    with pytest.raises(OSError):
        with outbox.begin() as scope:
            outbox.enqueue("evt", {"v": 1}, key="k")
            outbox.enqueue("evt", {"v": 2}, key="k")
            scope.commit()
    # Nothing visible after failed state flush.
    assert list(outbox.pending(10)) == []
    assert outbox.store_snapshot == ()


def test_chaos_nested_transactions_rejected() -> None:
    outbox = InMemoryTransactionalOutbox()
    outer = outbox.begin()
    try:
        with pytest.raises(TransactionalOutboxInvariantError):
            outbox.begin()
    finally:
        outer.rollback()


def test_chaos_concurrent_serialized_transactions_preserve_order() -> None:
    outbox = InMemoryTransactionalOutbox()
    lock = threading.Lock()
    results: list[int] = []

    def worker(n: int) -> None:
        with lock:
            with outbox.begin() as scope:
                outbox.enqueue("evt", {"n": n}, key="P")
                scope.commit()
                results.append(n)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    rows = [r for r in outbox.pending(100) if r["key"] == "P"]
    seqs = [r["sequence"] for r in rows]
    assert seqs == sorted(seqs)
    assert len(seqs) == 30


def test_chaos_relay_crash_mid_batch_retried() -> None:
    """Simulate a relay crash by raising on the 2nd publish; a retry picks it up."""
    state = {"calls": 0, "crash_at": 2}

    def publisher(_m: OutboxMessage) -> bool:
        state["calls"] += 1
        if state["calls"] == state["crash_at"]:
            raise RuntimeError("relay crash")
        return True

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        for i in range(4):
            outbox.enqueue("evt", {"n": i}, key=f"k{i}")
        scope.commit()

    outbox.relay_once()  # 1 ACK, 1 crash (recorded as failed), 2 more ACKed
    outbox.relay_once()  # retry the failed one
    snap = outbox.store_snapshot
    assert all(row["status"] == "published" for row in snap)


def test_chaos_large_batch_preserves_atomicity() -> None:
    outbox = InMemoryTransactionalOutbox()
    N = 5000
    with outbox.begin() as scope:
        for i in range(N):
            outbox.enqueue("evt", {"n": i}, key="batch")
        scope.commit()
    rows = list(outbox.pending(N + 10))
    assert len(rows) == N
    seqs = [r["sequence"] for r in rows]
    assert seqs == sorted(seqs)


def test_chaos_empty_key_rejected_even_inside_transaction() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        with pytest.raises(TransactionalOutboxInvariantError):
            outbox.enqueue("evt", {"v": 1}, key="")
        scope.rollback()
