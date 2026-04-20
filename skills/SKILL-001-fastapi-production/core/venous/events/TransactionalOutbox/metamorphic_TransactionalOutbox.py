"""Metamorphic + differential tests for TransactionalOutbox.

Algebraic properties:
- rollback is idempotent (no-op after terminal)
- relay_once is idempotent for already-published rows
- enqueue order per key == pending() order for that key
- commit → mark_published → mark_failed transitions are monotonic forward
- empty commit leaves the outbox unchanged
"""

from __future__ import annotations

from TransactionalOutbox import (
    InMemoryTransactionalOutbox,
    OutboxMessage,
    OutboxTransaction,
)


def test_metamorphic_rollback_idempotent() -> None:
    outbox = InMemoryTransactionalOutbox()
    scope = outbox.begin()
    outbox.enqueue("evt", {"v": 1}, key="k")
    scope.rollback()
    for _ in range(10):
        scope.rollback()  # must not raise; further rollbacks are no-ops
    assert list(outbox.pending(10)) == []


def test_metamorphic_relay_idempotent_for_published() -> None:
    calls = {"n": 0}

    def publisher(_m: OutboxMessage) -> bool:
        calls["n"] += 1
        return True

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()

    outbox.relay_once()
    assert calls["n"] == 1
    # Re-running relay MUST NOT re-publish already-published rows.
    for _ in range(5):
        outbox.relay_once()
    assert calls["n"] == 1


def test_metamorphic_enqueue_order_equals_pending_order_per_key() -> None:
    outbox = InMemoryTransactionalOutbox()
    expected = []
    with outbox.begin() as scope:
        for i in range(8):
            outbox.enqueue("evt", {"n": i}, key="KEY")
            expected.append(i)
        scope.commit()
    rows = [r for r in outbox.pending(100) if r["key"] == "KEY"]
    assert [r["payload"]["n"] for r in rows] == expected  # type: ignore[index]


def test_metamorphic_status_transition_monotonic() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        outbox.enqueue("evt", {"v": 1}, key="k")
        scope.commit()
    [msg] = list(outbox.pending(10))
    mid = str(msg["message_id"])
    # pending → failed → pending? No — once failed, mark_published is allowed
    # (retry ACK) but reverting published back to pending is forbidden.
    outbox.mark_failed(mid, "transient")
    outbox.mark_published(mid)
    snap = {m["message_id"]: m for m in outbox.store_snapshot}
    assert snap[mid]["status"] == "published"


def test_metamorphic_empty_commit_is_noop() -> None:
    flushed: list[int] = []

    def state_flush(_t: OutboxTransaction) -> None:
        flushed.append(1)

    outbox = InMemoryTransactionalOutbox(state_flush_fn=state_flush)
    with outbox.begin() as scope:
        scope.commit()  # zero enqueues
    assert flushed == [1]
    assert list(outbox.pending(10)) == []


def test_differential_commit_vs_rollback() -> None:
    """Committed rows are visible; rolled-back rows are invisible. Symmetry check."""
    o1 = InMemoryTransactionalOutbox()
    o2 = InMemoryTransactionalOutbox()
    with o1.begin() as s1:
        o1.enqueue("evt", {"n": 1}, key="k")
        s1.commit()
    with o2.begin() as s2:
        o2.enqueue("evt", {"n": 1}, key="k")
        s2.rollback()
    assert len(list(o1.pending(10))) == 1
    assert list(o2.pending(10)) == []
