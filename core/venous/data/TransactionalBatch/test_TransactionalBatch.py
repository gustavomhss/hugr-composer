"""Unit tests for TransactionalBatch — three per invariant."""

from __future__ import annotations

import asyncio

import pytest
from TransactionalBatch import (
    BatchState,
    BatchStateError,
    EtagConflictError,
    InMemoryStateStore,
    InMemoryTransactionalBatch,
    TransactionalBatchError,
)


# ---------------------------------------------------------------------------
# TXB_INV_01 — atomic all-or-nothing commit
# ---------------------------------------------------------------------------
def test_inv_atomic_commit_confirms() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"1").upsert("b", b"2")
    asyncio.run(batch.commit())
    snap = store.snapshot()
    assert snap == {"a": b"1", "b": b"2"}


def test_inv_atomic_commit_prevents() -> None:
    # If any op fails validation, nothing is applied.
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    with pytest.raises(TransactionalBatchError):
        batch.upsert("", b"x")  # empty key rejected at queue time
    # Store remains empty.
    assert store.snapshot() == {}


def test_inv_atomic_commit_under_failure() -> None:
    # Pre-seed and then fail on etag inside commit — store MUST remain unchanged.
    store = InMemoryStateStore()
    pre = InMemoryTransactionalBatch(store)
    pre.upsert("a", b"initial")
    asyncio.run(pre.commit())
    real_etag = store.get_with_etag("a")[1]
    assert real_etag is not None

    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"new", etag=real_etag)
    batch.upsert("b", b"ok", etag="WRONG")
    with pytest.raises(EtagConflictError):
        asyncio.run(batch.commit())
    # The pre-existing value is preserved; 'b' never appeared.
    snap = store.snapshot()
    assert snap == {"a": b"initial"}


# ---------------------------------------------------------------------------
# TXB_INV_02 — etag conflict aborts entire batch
# ---------------------------------------------------------------------------
def test_inv_etag_conflict_aborts_confirms() -> None:
    store = InMemoryStateStore()
    pre = InMemoryTransactionalBatch(store)
    pre.upsert("k", b"v1")
    asyncio.run(pre.commit())
    etag = store.get_with_etag("k")[1]
    # Correct etag — succeeds.
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"v2", etag=etag)
    asyncio.run(batch.commit())
    assert store.snapshot()["k"] == b"v2"


def test_inv_etag_conflict_aborts_prevents() -> None:
    store = InMemoryStateStore()
    pre = InMemoryTransactionalBatch(store)
    pre.upsert("k", b"v1")
    asyncio.run(pre.commit())

    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"v2", etag="wrong-etag")
    with pytest.raises(EtagConflictError):
        asyncio.run(batch.commit())
    # Value unchanged.
    assert store.snapshot()["k"] == b"v1"


def test_inv_etag_conflict_aborts_under_failure() -> None:
    store = InMemoryStateStore()
    pre = InMemoryTransactionalBatch(store)
    pre.upsert("a", b"1").upsert("b", b"2")
    asyncio.run(pre.commit())
    etag_a = store.get_with_etag("a")[1]
    # Concurrent-style: build a multi-op batch where ONE op has a wrong etag.
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"new", etag=etag_a).delete("b", etag="stale")
    with pytest.raises(EtagConflictError):
        asyncio.run(batch.commit())
    # NOTHING applied.
    snap = store.snapshot()
    assert snap == {"a": b"1", "b": b"2"}
    assert batch.state is BatchState.ABORTED


# ---------------------------------------------------------------------------
# TXB_INV_03 — no reuse after commit/abort
# ---------------------------------------------------------------------------
def test_inv_no_reuse_confirms() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"1")
    asyncio.run(batch.commit())
    assert batch.state is BatchState.COMMITTED


def test_inv_no_reuse_prevents() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"1")
    asyncio.run(batch.commit())
    with pytest.raises(BatchStateError, match="TXB-INV-03"):
        batch.upsert("b", b"2")
    with pytest.raises(BatchStateError, match="TXB-INV-03"):
        batch.delete("a")
    with pytest.raises(BatchStateError, match="TXB-INV-03"):
        asyncio.run(batch.commit())


def test_inv_no_reuse_under_failure() -> None:
    # After an aborted commit, the batch is still closed.
    store = InMemoryStateStore()
    pre = InMemoryTransactionalBatch(store)
    pre.upsert("k", b"v1")
    asyncio.run(pre.commit())

    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"v2", etag="wrong")
    with pytest.raises(EtagConflictError):
        asyncio.run(batch.commit())
    assert batch.state is BatchState.ABORTED
    with pytest.raises(BatchStateError):
        batch.upsert("z", b"x")


# ---------------------------------------------------------------------------
# TXB_INV_04 — same store throughout the batch
# ---------------------------------------------------------------------------
def test_inv_single_store_boundary_confirms() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("a", b"1").delete("b")
    asyncio.run(batch.commit())
    # All ops went to the single store.
    assert "a" in store.snapshot()


def test_inv_single_store_boundary_prevents() -> None:
    # There is NO rebind-to-another-store API by design; the constructor binds
    # the batch to one store. The absence IS the guarantee.
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    public = {m for m in dir(batch) if not m.startswith("_")}
    for forbidden in ("set_store", "rebind", "switch_store"):
        assert forbidden not in public


def test_inv_single_store_boundary_under_failure() -> None:
    # Two batches on two stores remain isolated even under concurrent commit.
    s1 = InMemoryStateStore()
    s2 = InMemoryStateStore()
    b1 = InMemoryTransactionalBatch(s1)
    b2 = InMemoryTransactionalBatch(s2)
    b1.upsert("x", b"1")
    b2.upsert("x", b"2")
    asyncio.run(b1.commit())
    asyncio.run(b2.commit())
    assert s1.snapshot()["x"] == b"1"
    assert s2.snapshot()["x"] == b"2"


# ---------------------------------------------------------------------------
# TXB_INV_05 — read operations FORBIDDEN inside the batch
# ---------------------------------------------------------------------------
def test_inv_no_reads_in_batch_confirms() -> None:
    # The batch Protocol exposes only upsert / delete / commit — no read.
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    public = {m for m in dir(batch) if not m.startswith("_")}
    assert "upsert" in public
    assert "delete" in public
    assert "commit" in public


def test_inv_no_reads_in_batch_prevents() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    public = {m for m in dir(batch) if not m.startswith("_")}
    for forbidden in ("get", "read", "fetch", "scan", "query", "list"):
        assert forbidden not in public


def test_inv_no_reads_in_batch_under_failure() -> None:
    # Even inspecting `state` / `op_count` does not reveal the store values.
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("secret-key", b"secret-value")
    # Only queue-length exposed, never the value.
    assert batch.op_count == 1
    # state is an enum, not data.
    assert batch.state is BatchState.OPEN
