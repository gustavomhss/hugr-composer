"""Concurrency tests for TransactionalBatch.

Linearizability: concurrent commits MUST produce a serial final state
consistent with some total order. No partial writes visible mid-commit.
"""

from __future__ import annotations

import asyncio

import pytest

from TransactionalBatch import (
    EtagConflictError,
    InMemoryStateStore,
    InMemoryTransactionalBatch,
)


def test_concurrent_commits_serialize_isolated_keys() -> None:
    store = InMemoryStateStore()

    async def one(i: int) -> None:
        b = InMemoryTransactionalBatch(store)
        b.upsert(f"k{i}", str(i).encode())
        await b.commit()

    async def many() -> None:
        await asyncio.gather(*(one(i) for i in range(50)))

    asyncio.run(many())
    snap = store.snapshot()
    assert len(snap) == 50
    for i in range(50):
        assert snap[f"k{i}"] == str(i).encode()


def test_concurrent_etag_races_at_most_one_wins() -> None:
    store = InMemoryStateStore()
    seed = InMemoryTransactionalBatch(store)
    seed.upsert("k", b"v0")
    asyncio.run(seed.commit())
    etag = store.get_with_etag("k")[1]

    results: list[str] = []

    async def racer(tag: str) -> None:
        b = InMemoryTransactionalBatch(store)
        b.upsert("k", tag.encode(), etag=etag)
        try:
            await b.commit()
            results.append(f"ok:{tag}")
        except EtagConflictError:
            results.append(f"conflict:{tag}")

    async def race() -> None:
        await asyncio.gather(*(racer(f"t{i}") for i in range(10)))

    asyncio.run(race())
    oks = [r for r in results if r.startswith("ok:")]
    conflicts = [r for r in results if r.startswith("conflict:")]
    # At most ONE commit wins on the original etag.
    assert len(oks) == 1
    assert len(conflicts) == 9


def test_concurrent_batches_no_torn_reads_in_snapshot() -> None:
    store = InMemoryStateStore()

    async def writer() -> None:
        b = InMemoryTransactionalBatch(store)
        b.upsert("a", b"1").upsert("b", b"2").upsert("c", b"3")
        await b.commit()

    async def reader_sees_all_or_none() -> list[dict[str, bytes]]:
        snaps = []
        for _ in range(20):
            snaps.append(store.snapshot())
            await asyncio.sleep(0)
        return snaps

    async def run() -> None:
        snaps_task = asyncio.create_task(reader_sees_all_or_none())
        await writer()
        snaps = await snaps_task
        # Every snapshot: either 0 (before commit) or 3 keys (after).
        # No partial state with only 'a' or only 'a,b' (TXB-INV-01).
        for s in snaps:
            assert set(s) in (set(), {"a", "b", "c"})

    asyncio.run(run())


def test_concurrent_reuse_after_commit_rejected() -> None:
    store = InMemoryStateStore()
    batch = InMemoryTransactionalBatch(store)
    batch.upsert("k", b"v")

    async def run() -> None:
        await batch.commit()

    asyncio.run(run())
    # Any subsequent op on the closed batch MUST fail regardless of timing.
    with pytest.raises(Exception):  # noqa: BLE001 — accepts BatchStateError or subclass
        batch.upsert("k2", b"v2")
