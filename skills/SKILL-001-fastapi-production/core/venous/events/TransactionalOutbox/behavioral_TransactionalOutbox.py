"""Behavioral end-to-end scenarios for TransactionalOutbox — proves invariants at runtime."""

from __future__ import annotations

import pytest

from TransactionalOutbox import (
    InMemoryTransactionalOutbox,
    OutboxMessage,
    OutboxTransaction,
    TransactionalOutboxInvariantError,
)


def test_scenario_place_order_commits_state_and_outbox_atomically() -> None:
    """place_order flushes the aggregate AND enqueues an event in one transaction."""
    orders: list[dict[str, object]] = []

    def state_flush(_t: OutboxTransaction) -> None:
        orders.append({"status": "persisted"})

    outbox = InMemoryTransactionalOutbox(state_flush_fn=state_flush)
    with outbox.begin() as scope:
        outbox.enqueue("orders.placed", {"id": 42, "total": 100}, key="order-42")
        scope.commit()

    assert orders == [{"status": "persisted"}]
    pending = list(outbox.pending(10))
    assert len(pending) == 1
    assert pending[0]["destination"] == "orders.placed"


def test_scenario_state_flush_failure_discards_outbox() -> None:
    """If the business-state commit fails, the outbox row MUST NOT be visible."""

    def fail(_t: OutboxTransaction) -> None:
        raise RuntimeError("db down")

    outbox = InMemoryTransactionalOutbox(state_flush_fn=fail)
    with pytest.raises(RuntimeError):
        with outbox.begin() as scope:
            outbox.enqueue("orders.placed", {"id": 1}, key="k")
            scope.commit()
    assert list(outbox.pending(10)) == []
    assert outbox.current_transaction is None


def test_scenario_relay_publishes_pending_then_marks_published() -> None:
    """Relay drains pending rows through the broker publisher and marks them published."""
    published: list[str] = []

    def publisher(m: OutboxMessage) -> bool:
        published.append(m.message_id)
        return True

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"a": 1}, key="A")
        outbox.enqueue("evt", {"b": 2}, key="B")
        scope.commit()

    assert len(list(outbox.pending(10))) == 2
    ids = outbox.relay_once()
    assert len(ids) == 2
    assert list(outbox.pending(10)) == []  # none pending after relay
    # Running relay again is a no-op (already-published is idempotent).
    ids2 = outbox.relay_once()
    assert ids2 == []
    assert published == ids  # published exactly once per ack path


def test_scenario_broker_nack_keeps_message_retryable() -> None:
    """Broker NACK marks the row failed but keeps it eligible for retry (TXN-INV-03)."""
    state = {"acks": 0}

    def publisher(_m: OutboxMessage) -> bool:
        state["acks"] += 1
        return state["acks"] > 2  # first two NACK, then ACK

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()

    outbox.relay_once()
    outbox.relay_once()
    outbox.relay_once()
    snap = {m["message_id"]: m for m in outbox.store_snapshot}
    [row] = snap.values()
    assert row["status"] == "published"
    assert row["attempts"] >= 3


def test_scenario_per_key_fifo_order_across_two_commits() -> None:
    """Two successive transactions for the same key preserve per-partition order."""
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"n": 1}, key="K")
        scope.commit()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"n": 2}, key="K")
        scope.commit()

    rows = [r for r in outbox.pending(10) if r["key"] == "K"]
    assert [r["payload"]["n"] for r in rows] == [1, 2]  # type: ignore[index]


def test_scenario_exception_inside_transaction_triggers_rollback() -> None:
    """Raising inside the `with` block rolls back staged outbox rows."""
    outbox = InMemoryTransactionalOutbox()
    with pytest.raises(ZeroDivisionError):
        with outbox.begin() as scope:
            outbox.enqueue("evt", {"v": 1}, key="k")
            _ = 1 / 0
            scope.commit()  # unreachable
    assert list(outbox.pending(10)) == []


def test_scenario_mark_published_is_idempotent() -> None:
    """Repeated mark_published on the same id is a no-op (relay crash-safe)."""
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()
    [msg] = list(outbox.pending(10))
    mid = str(msg["message_id"])
    for _ in range(5):
        outbox.mark_published(mid)
    snap = {m["message_id"]: m for m in outbox.store_snapshot}
    assert snap[mid]["status"] == "published"
