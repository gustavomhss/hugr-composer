"""Behavioral end-to-end scenarios for TransactionalBatch."""

from __future__ import annotations

import asyncio

import pytest

from TransactionalBatch import (
    BatchState,
    BatchStateError,
    EtagConflictError,
    InMemoryStateStore,
    InMemoryTransactionalBatch,
)


def test_scenario_account_transfer_atomic() -> None:
    store = InMemoryStateStore()
    seed = InMemoryTransactionalBatch(store)
    seed.upsert("src", b"100").upsert("dst", b"0")
    asyncio.run(seed.commit())
    batch = InMemoryTransactionalBatch(store)
    # Both legs commit atomically.
    batch.upsert("src", b"90").upsert("dst", b"10")
    asyncio.run(batch.commit())
    snap = store.snapshot()
    assert snap == {"src": b"90", "dst": b"10"}


def test_scenario_delete_with_matching_etag() -> None:
    store = InMemoryStateStore()
    b0 = InMemoryTransactionalBatch(store)
    b0.upsert("k", b"v")
    asyncio.run(b0.commit())
    etag = store.get_with_etag("k")[1]

    b1 = InMemoryTransactionalBatch(store)
    b1.delete("k", etag=etag)
    asyncio.run(b1.commit())
    assert "k" not in store.snapshot()


def test_scenario_etag_conflict_rolls_back_whole_batch() -> None:
    store = InMemoryStateStore()
    seed = InMemoryTransactionalBatch(store)
    seed.upsert("a", b"1").upsert("b", b"2")
    asyncio.run(seed.commit())
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"X", etag="stale").upsert("b", b"Y")
    with pytest.raises(EtagConflictError):
        asyncio.run(batch.commit())
    assert store.snapshot() == {"a": b"1", "b": b"2"}


def test_scenario_batch_cannot_be_reused() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"v")
    asyncio.run(batch.commit())
    with pytest.raises(BatchStateError):
        asyncio.run(batch.commit())


def test_scenario_concurrent_batches_on_same_store() -> None:
    store = InMemoryStateStore()

    async def many_writes() -> None:
        batches = [InMemoryTransactionalBatch(store) for _ in range(20)]
        for i, b in enumerate(batches):
            b.upsert(f"k{i}", str(i).encode())
        await asyncio.gather(*(b.commit() for b in batches))

    asyncio.run(many_writes())
    assert len(store.snapshot()) == 20


def test_scenario_sequential_upsert_updates_value() -> None:
    store = InMemoryStateStore()
    for v in (b"1", b"2", b"3"):
        batch = InMemoryTransactionalBatch(store)
        batch.upsert("k", v)
        asyncio.run(batch.commit())
        assert batch.state is BatchState.COMMITTED
    assert store.snapshot()["k"] == b"3"
