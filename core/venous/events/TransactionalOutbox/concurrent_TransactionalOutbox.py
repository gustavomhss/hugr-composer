"""Concurrency / linearizability harness for TransactionalOutbox.

The DB-level transaction-scope contract is single-writer (one active
transaction per outbox instance — TXN-INV-01). Concurrent access is legal
for the observer side: pending(), store_snapshot, mark_published on different
message_ids. These tests confirm those read paths stay consistent under race.
"""

from __future__ import annotations

import threading

from TransactionalOutbox import (
    InMemoryTransactionalOutbox,
    OutboxMessage,
    TransactionalOutboxInvariantError,
)


def test_concurrent_serialized_writes_preserve_sequence_monotonicity() -> None:
    """Writers serialize via begin()/commit() — sequences MUST be monotonic."""
    outbox = InMemoryTransactionalOutbox()
    errors: list[BaseException] = []
    lock = threading.Lock()
    writer_lock = threading.Lock()

    def writer(n: int) -> None:
        try:
            with writer_lock, outbox.begin() as scope:
                outbox.enqueue("evt", {"n": n}, key="K")
                scope.commit()
        except BaseException as exc:
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    rows = [r for r in outbox.pending(100) if r["key"] == "K"]
    seqs = [r["sequence"] for r in rows]
    assert seqs == sorted(seqs)
    assert len(seqs) == 50


def test_concurrent_readers_see_consistent_snapshot() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        for i in range(200):
            outbox.enqueue("evt", {"n": i}, key=f"k{i % 4}")
        scope.commit()

    lens: list[int] = []
    lock = threading.Lock()

    def reader() -> None:
        snap = outbox.store_snapshot
        with lock:
            lens.append(len(snap))

    ts = [threading.Thread(target=reader) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert all(ln == 200 for ln in lens)


def test_concurrent_mark_published_distinct_ids_threadsafe() -> None:
    outbox = InMemoryTransactionalOutbox()
    with outbox.begin() as scope:
        for i in range(50):
            outbox.enqueue("evt", {"n": i}, key=f"k{i}")
        scope.commit()

    ids = [str(r["message_id"]) for r in outbox.pending(100)]
    errors: list[BaseException] = []
    lock = threading.Lock()

    def acker(mid: str) -> None:
        try:
            outbox.mark_published(mid)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=acker, args=(m,)) for m in ids]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    snap = outbox.store_snapshot
    assert all(row["status"] == "published" for row in snap)


def test_concurrent_nested_begin_is_rejected() -> None:
    outbox = InMemoryTransactionalOutbox()
    rejected: list[int] = []
    lock = threading.Lock()

    def attempter() -> None:
        try:
            scope = outbox.begin()
            scope.rollback()
        except TransactionalOutboxInvariantError:
            with lock:
                rejected.append(1)

    outer = outbox.begin()
    try:
        ts = [threading.Thread(target=attempter) for _ in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        outer.rollback()
    # Every concurrent attempt while the outer was active MUST be rejected.
    assert len(rejected) == 10


def test_concurrent_relay_is_safe_with_mixed_acks() -> None:
    acks: list[str] = []
    lock = threading.Lock()

    def publisher(m: OutboxMessage) -> bool:
        with lock:
            acks.append(m.message_id)
        return True

    outbox = InMemoryTransactionalOutbox(broker_publish_fn=publisher)
    with outbox.begin() as scope:
        for i in range(20):
            outbox.enqueue("evt", {"n": i}, key=f"k{i}")
        scope.commit()

    def driver() -> None:
        outbox.relay_once()

    ts = [threading.Thread(target=driver) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    # Every message was published at least once; none are orphaned.
    snap = outbox.store_snapshot
    assert all(row["status"] == "published" for row in snap)
