"""Metamorphic + differential tests for KeyValueBucket."""

from __future__ import annotations

import asyncio

from KeyValueBucket import InMemoryKeyValueBucket


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def test_metamorphic_revision_strictly_increases() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e = await kv.create("k", b"v0")
        prev = e.revision
        for i in range(20):
            e = await kv.update("k", f"v{i}".encode(), prev)
            assert e.revision > prev
            prev = e.revision
    _run(scenario())


def test_metamorphic_independent_keys_share_monotonic_counter() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e_a = await kv.create("a", b"1")
        e_b = await kv.create("b", b"2")
        e_c = await kv.create("c", b"3")
        assert e_a.revision < e_b.revision < e_c.revision
    _run(scenario())


def test_differential_value_roundtrip_preserved() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        payloads = [b"", b"x", b"\x00\x01\x02", b"a" * 1024]
        for i, p in enumerate(payloads):
            e = await kv.create(f"k{i}", p)
            read = await kv.get(f"k{i}")
            assert read is not None
            assert read.value == p
            assert read.revision == e.revision
    _run(scenario())


def test_metamorphic_watch_replay_matches_update_history() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=20)
        values: list[bytes] = []
        e = await kv.create("k", b"v0")
        values.append(b"v0")
        for i in range(10):
            payload = f"v{i}".encode()
            e = await kv.update("k", payload, e.revision)
            values.append(payload)
        replayed: list[bytes] = []
        async for entry in kv.watch("k"):
            replayed.append(entry.value)
        assert replayed == values
    _run(scenario())


def test_metamorphic_delete_then_get_is_none() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=5)
        await kv.create("k", b"v0")
        await kv.delete("k")
        assert await kv.get("k") is None
    _run(scenario())


def test_metamorphic_idempotent_delete_on_missing_key() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.delete("never-existed")
        await kv.delete("never-existed")
        assert await kv.get("never-existed") is None
    _run(scenario())
