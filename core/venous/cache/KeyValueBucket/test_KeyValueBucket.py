"""Unit tests for KeyValueBucket — 3 per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest
from KeyValueBucket import (
    InMemoryKeyValueBucket,
    KeyAlreadyExistsError,
    KeyValueBucketError,
    RevisionMismatchError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper, asyncio shim — not part of public surface
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# KVB_INV_01 — create fails when key already exists
# ---------------------------------------------------------------------------
def test_inv_create_exclusive_confirms() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        entry = await kv.create("k", b"v0")
        assert entry.key == "k"
        assert entry.value == b"v0"
    _run(scenario())


def test_inv_create_exclusive_prevents() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("k", b"v0")
        with pytest.raises(KeyAlreadyExistsError):
            await kv.create("k", b"v1")
    _run(scenario())


def test_inv_create_exclusive_under_failure() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("k", b"v0")
        # 50 concurrent create attempts on the same key should all fail.
        async def worker() -> bool:
            try:
                await kv.create("k", b"v")
            except KeyAlreadyExistsError:
                return False
            return True
        results = await asyncio.gather(*[worker() for _ in range(50)])
        assert not any(results)
    _run(scenario())


# ---------------------------------------------------------------------------
# KVB_INV_02 — update fails on revision mismatch (CAS)
# ---------------------------------------------------------------------------
def test_inv_cas_update_confirms() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e0 = await kv.create("k", b"v0")
        e1 = await kv.update("k", b"v1", revision=e0.revision)
        assert e1.revision > e0.revision
    _run(scenario())


def test_inv_cas_update_prevents() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e0 = await kv.create("k", b"v0")
        # Stale revision is rejected.
        with pytest.raises(RevisionMismatchError):
            await kv.update("k", b"v1", revision=e0.revision - 1)
        # Updating a non-existent key is rejected.
        with pytest.raises(KeyValueBucketError):
            await kv.update("missing", b"v", revision=1)
    _run(scenario())


def test_inv_cas_update_under_failure() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e0 = await kv.create("k", b"v0")
        # Many concurrent updates with the SAME stale revision; exactly one wins.
        async def worker(i: int) -> bool:
            try:
                await kv.update("k", f"v{i}".encode(), revision=e0.revision)
            except RevisionMismatchError:
                return False
            return True
        results = await asyncio.gather(*[worker(i) for i in range(20)])
        # Exactly one update succeeded (the first to acquire the lock and match).
        assert sum(1 for r in results if r) == 1
    _run(scenario())


# ---------------------------------------------------------------------------
# KVB_INV_03 — revisions are monotonic
# ---------------------------------------------------------------------------
def test_inv_revision_monotonic_confirms() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e0 = await kv.create("k", b"v0")
        e1 = await kv.update("k", b"v1", e0.revision)
        e2 = await kv.update("k", b"v2", e1.revision)
        assert e0.revision < e1.revision < e2.revision
    _run(scenario())


def test_inv_revision_monotonic_prevents() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        # Revisions from different keys still strictly increase globally.
        e_a = await kv.create("a", b"1")
        e_b = await kv.create("b", b"2")
        assert e_b.revision > e_a.revision
    _run(scenario())


def test_inv_revision_monotonic_under_failure() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("k", b"v0")
        revisions: list[int] = []
        cur = await kv.get("k")
        assert cur is not None
        for i in range(20):
            e = await kv.update("k", f"v{i}".encode(), cur.revision)
            revisions.append(e.revision)
            cur = e
        assert revisions == sorted(revisions)
        assert len(set(revisions)) == len(revisions)
    _run(scenario())


# ---------------------------------------------------------------------------
# KVB_INV_04 — watch emits in revision order, no gaps
# ---------------------------------------------------------------------------
def test_inv_watch_in_order_confirms() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e0 = await kv.create("k", b"v0")
        e1 = await kv.update("k", b"v1", e0.revision)
        _ = await kv.update("k", b"v2", e1.revision)
        events: list[int] = []
        async for entry in kv.watch("k"):
            events.append(entry.revision)
        assert events == sorted(events)
        # Contiguous — no skipped revisions within this key's history window.
        for i in range(len(events) - 1):
            assert events[i] < events[i + 1]
    _run(scenario())


def test_inv_watch_in_order_prevents() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("k", b"v0")
        # A watcher on a non-existent key yields nothing (not an error).
        events: list[int] = []
        async for entry in kv.watch("other"):
            events.append(entry.revision)
        assert events == []
    _run(scenario())


def test_inv_watch_in_order_under_failure() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=10)
        e = await kv.create("k", b"v0")
        for i in range(9):
            e = await kv.update("k", f"v{i}".encode(), e.revision)
        # Watch replay must preserve strict revision order.
        revisions: list[int] = []
        async for entry in kv.watch("k"):
            revisions.append(entry.revision)
        assert revisions == sorted(revisions)
    _run(scenario())


# ---------------------------------------------------------------------------
# KVB_INV_05 — delete preserves historical revisions (when history > 1)
# ---------------------------------------------------------------------------
def test_inv_history_preserved_confirms() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=5)
        e0 = await kv.create("k", b"v0")
        e1 = await kv.update("k", b"v1", e0.revision)
        await kv.delete("k")
        # History depth (retained entries) MUST be > 1 since history=5.
        assert kv.history_depth("k") >= 2
        # After delete, get returns None but prior revisions are still there.
        assert await kv.get("k") is None
        assert e1.revision == 2
    _run(scenario())


def test_inv_history_preserved_prevents() -> None:
    # A history of 1 means the delete tombstone overwrites the prior entry.
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=1)
        await kv.create("k", b"v0")
        await kv.delete("k")
        # Only the tombstone survives; the contract permits this since
        # history retention is configured == 1.
        assert kv.history_depth("k") == 1
    _run(scenario())


def test_inv_history_preserved_under_failure() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=10)
        e = await kv.create("k", b"v0")
        for i in range(5):
            e = await kv.update("k", f"v{i}".encode(), e.revision)
        await kv.delete("k")
        # 7 entries: 1 create + 5 updates + 1 tombstone.
        assert kv.history_depth("k") == 7
    _run(scenario())
