"""Unit tests for TransactionalOutbox — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from TransactionalOutbox import (
    InMemoryTransactionalOutbox,
    OutboxTransaction,
    TransactionalOutboxInvariantError,
)


# ---------------------------------------------------------------------------
# TXN_INV_01 — enqueue atomic with business transaction
# ---------------------------------------------------------------------------
def test_inv_atomic_enqueue_confirms() -> None:
    flushed: list[int] = []

    def state_flush(_t: OutboxTransaction) -> None:
        flushed.append(1)

    outbox = InMemoryTransactionalOutbox(state_flush_fn=state_flush)
    with outbox.begin() as scope:
        outbox.enqueue("orders.placed", {"id": 1}, key="order-1")
        scope.commit()
    # Business flush and outbox insert happened atomically.
    assert flushed == [1]
    pending = list(outbox.pending(10))
    assert len(pending) == 1
    assert pending[0]["destination"] == "orders.placed"
    assert pending[0]["status"] == "pending"


def test_inv_atomic_enqueue_prevents() -> None:
    outbox = InMemoryTransactionalOutbox()
    # Enqueue without an active transaction MUST be rejected.
    with pytest.raises(TransactionalOutboxInvariantError):
        outbox.enqueue("x", {"a": 1}, key="k1")


def test_inv_atomic_enqueue_under_failure() -> None:
    def boom(_t: OutboxTransaction) -> None:
        raise RuntimeError("state flush failed")

    outbox = InMemoryTransactionalOutbox(state_flush_fn=boom)
    with pytest.raises(RuntimeError), outbox.begin() as scope:
        outbox.enqueue("orders.placed", {"id": 1}, key="order-1")
        scope.commit()
    # Atomicity: state flush failed → outbox row MUST NOT be visible.
    assert list(outbox.pending(10)) == []


# ---------------------------------------------------------------------------
# TXN_INV_02 — no mark_published without broker ack
# ---------------------------------------------------------------------------
def test_inv_ack_before_published_confirms() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()
    [msg] = list(outbox.pending(10))
    # Simulate broker ack then mark_published.
    outbox.mark_published(str(msg["message_id"]))
    snap = {m["message_id"]: m for m in outbox.store_snapshot}
    assert snap[str(msg["message_id"])]["status"] == "published"


def test_inv_ack_before_published_prevents() -> None:
    outbox = InMemoryTransactionalOutbox()
    # mark_published on unknown id MUST raise (caller never had a broker ack
    # for a message that does not exist in this outbox).
    with pytest.raises(TransactionalOutboxInvariantError):
        outbox.mark_published("nonexistent-id")


def test_inv_ack_before_published_under_failure() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()
    [msg] = list(outbox.pending(10))
    mid = str(msg["message_id"])
    outbox.mark_published(mid)
    # After a true broker ack, trying to mark_failed is FORBIDDEN (ack is terminal).
    with pytest.raises(TransactionalOutboxInvariantError):
        outbox.mark_failed(mid, "late-nack")


# ---------------------------------------------------------------------------
# TXN_INV_03 — at-least-once delivery; duplicates allowed
# ---------------------------------------------------------------------------
def test_inv_at_least_once_confirms() -> None:
    attempts: list[str] = []

    def publisher(m: object) -> bool:
        attempts.append(m.message_id)
        return True

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"x": 1}, key="k1")
        scope.commit()
    # Relay publishes.
    outbox.relay_once()
    # Relay may crash and restart → running relay_once again MUST NOT fail.
    outbox.relay_once()
    assert len(attempts) == 1  # already-published is idempotent no-op


def test_inv_at_least_once_prevents() -> None:
    outbox = InMemoryTransactionalOutbox()
    # mark_failed with empty reason MUST be rejected — diagnostics are required
    # so operators can distinguish retry classes.
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()
    [msg] = list(outbox.pending(10))
    with pytest.raises(TransactionalOutboxInvariantError):
        outbox.mark_failed(str(msg["message_id"]), "")


def test_inv_at_least_once_under_failure() -> None:
    calls = {"n": 0}

    def flaky(m: object) -> bool:
        calls["n"] += 1
        return calls["n"] >= 3  # first two fail, third acks

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=flaky)
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()
    outbox.relay_once()
    outbox.relay_once()
    outbox.relay_once()
    # Eventually published → consumers MAY have seen duplicates (at-least-once).
    snap = {m["message_id"]: m for m in outbox.store_snapshot}
    [row] = snap.values()
    assert row["status"] == "published"
    assert row["attempts"] >= 3


# ---------------------------------------------------------------------------
# TXN_INV_04 — per-partition-key ordering follows commit order
# ---------------------------------------------------------------------------
def test_inv_per_key_order_confirms() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"n": 1}, key="A")
        outbox.enqueue("evt", {"n": 2}, key="A")
        outbox.enqueue("evt", {"n": 3}, key="A")
        scope.commit()
    rows = list(outbox.pending(10))
    # Same key → sequence monotonically increasing.
    assert [r["payload"]["n"] for r in rows if r["key"] == "A"] == [1, 2, 3]  # type: ignore[index]


def test_inv_per_key_order_prevents() -> None:
    outbox = InMemoryTransactionalOutbox()
    # Empty key MUST be rejected — unkeyed messages cannot be ordered.
    with outbox.begin() as scope:
        with pytest.raises(TransactionalOutboxInvariantError):
            outbox.enqueue("evt", {"n": 1}, key="")
        scope.rollback()


def test_inv_per_key_order_under_failure() -> None:
    # Concurrent enqueues for the SAME key in sequential transactions MUST
    # preserve per-key monotonic order regardless of thread interleaving.
    outbox = InMemoryTransactionalOutbox()
    lock = threading.Lock()

    def worker(n: int) -> None:
        with lock:  # serialize transactions (one active at a time — TXN-INV-01)
            with outbox.begin() as scope:
                outbox.enqueue("evt", {"n": n}, key="A")
                scope.commit()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = [r for r in outbox.pending(100) if r["key"] == "A"]
    seqs = [r["sequence"] for r in rows]
    assert seqs == sorted(seqs)
    assert len(seqs) == 20
