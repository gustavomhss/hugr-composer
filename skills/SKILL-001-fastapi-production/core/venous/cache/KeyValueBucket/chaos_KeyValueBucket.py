"""Chaos / fault injection for KeyValueBucket."""

from __future__ import annotations

import asyncio

import pytest

from KeyValueBucket import (
    InMemoryKeyValueBucket,
    KeyValueBucketError,
    RevisionMismatchError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def test_chaos_empty_key_rejected() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        with pytest.raises(KeyValueBucketError):
            await kv.create("", b"v")
    _run(scenario())


def test_chaos_null_byte_key_rejected() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        with pytest.raises(KeyValueBucketError):
            await kv.create("a\x00b", b"v")
    _run(scenario())


def test_chaos_history_zero_rejected() -> None:
    with pytest.raises(ValueError, match="history MUST be"):
        InMemoryKeyValueBucket(history=0)


def test_chaos_negative_revision_rejected() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("k", b"v0")
        with pytest.raises(RevisionMismatchError):
            await kv.update("k", b"v1", revision=-1)
    _run(scenario())


def test_chaos_concurrent_updates_preserve_one_winner() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e = await kv.create("k", b"v0")
        async def worker(i: int) -> bool:
            try:
                await kv.update("k", f"v{i}".encode(), e.revision)
            except RevisionMismatchError:
                return False
            return True
        results = await asyncio.gather(*[worker(i) for i in range(100)])
        assert sum(1 for r in results if r) == 1
    _run(scenario())


def test_chaos_delete_with_wrong_revision_rejected() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e = await kv.create("k", b"v0")
        with pytest.raises(RevisionMismatchError):
            await kv.delete("k", revision=e.revision + 999)
    _run(scenario())


def test_chaos_large_value_roundtrip() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        payload = b"x" * (1 << 20)  # 1 MiB
        e = await kv.create("big", payload)
        read = await kv.get("big")
        assert read is not None
        assert read.value == payload
        assert read.revision == e.revision
    _run(scenario())
