"""Chaos / fault-injection for TransactionalBatch."""

from __future__ import annotations

import asyncio

import pytest

from TransactionalBatch import (
    MAX_OPS_PER_BATCH,
    EtagConflictError,
    InMemoryStateStore,
    InMemoryTransactionalBatch,
    TransactionalBatchError,
)


def test_chaos_oversize_batch_rejected() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    for i in range(MAX_OPS_PER_BATCH):
        batch.upsert(f"k{i}", b"v")
    with pytest.raises(TransactionalBatchError):
        batch.upsert("overflow", b"v")


def test_chaos_non_bytes_value_rejected() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    with pytest.raises(TransactionalBatchError):
        batch.upsert("k", "not-bytes")  # type: ignore[arg-type]


def test_chaos_empty_key_rejected() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    with pytest.raises(TransactionalBatchError):
        batch.upsert("", b"v")
    with pytest.raises(TransactionalBatchError):
        batch.delete("")


def test_chaos_concurrent_writers_all_serialize() -> None:
    store = InMemoryStateStore()

    async def writer(i: int) -> None:
        b = InMemoryTransactionalBatch(store)
        b.upsert(f"k{i}", str(i).encode())
        await b.commit()

    async def run() -> None:
        await asyncio.gather(*(writer(i) for i in range(200)))

    asyncio.run(run())
    assert len(store.snapshot()) == 200


def test_chaos_aborted_batch_does_not_leak_state() -> None:
    store = InMemoryStateStore()
    pre = InMemoryTransactionalBatch(store)
    pre.upsert("k", b"v0")
    asyncio.run(pre.commit())

    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"XXX", etag="stale").upsert("new", b"YYY")
    with pytest.raises(EtagConflictError):
        asyncio.run(batch.commit())
    # Neither XXX nor YYY visible.
    snap = store.snapshot()
    assert snap["k"] == b"v0"
    assert "new" not in snap


def test_chaos_binary_payload_roundtrip() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    payload = bytes(range(256))
    batch.upsert("bin", payload)
    asyncio.run(batch.commit())
    v, _ = store.get_with_etag("bin")
    assert v == payload


def test_chaos_delete_nonexistent_is_ok() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.delete("never-existed")
    asyncio.run(batch.commit())  # no error; idempotent
    assert "never-existed" not in store.snapshot()
