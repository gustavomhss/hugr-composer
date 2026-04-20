"""Metamorphic + differential tests for TransactionalBatch.

Algebraic properties:
- upsert-then-delete of same key (in SAME batch) == delete (last-write-wins).
- Two commits vs one merged commit produce the same final state.
- Empty commit is identity.
"""

from __future__ import annotations

import asyncio

from TransactionalBatch import (
    InMemoryStateStore,
    InMemoryTransactionalBatch,
)


def test_metamorphic_empty_commit_is_identity() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    before = store.snapshot()
    asyncio.run(batch.commit())
    assert store.snapshot() == before


def test_metamorphic_last_write_wins_within_batch() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"1").upsert("k", b"2").upsert("k", b"3")
    asyncio.run(batch.commit())
    assert store.snapshot()["k"] == b"3"


def test_metamorphic_upsert_then_delete_within_batch() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"1").delete("k")
    asyncio.run(batch.commit())
    assert "k" not in store.snapshot()


def test_differential_two_commits_equal_one_merged() -> None:
    s1 = InMemoryStateStore()
    s2 = InMemoryStateStore()
    # Two separate commits into s1.
    b1 = InMemoryTransactionalBatch(s1)
    b1.upsert("a", b"1")
    asyncio.run(b1.commit())
    b2 = InMemoryTransactionalBatch(s1)
    b2.upsert("b", b"2")
    asyncio.run(b2.commit())
    # One merged commit into s2.
    bm = InMemoryTransactionalBatch(s2)
    bm.upsert("a", b"1").upsert("b", b"2")
    asyncio.run(bm.commit())
    assert s1.snapshot() == s2.snapshot()


def test_metamorphic_idempotent_upsert() -> None:
    store = InMemoryStateStore()
    for _ in range(10):
        batch = InMemoryTransactionalBatch(store)
        batch.upsert("k", b"same")
        asyncio.run(batch.commit())
    assert store.snapshot()["k"] == b"same"
