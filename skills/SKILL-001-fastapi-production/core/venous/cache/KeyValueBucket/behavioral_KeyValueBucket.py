"""Behavioral end-to-end scenarios for KeyValueBucket."""

from __future__ import annotations

import asyncio

import pytest

from KeyValueBucket import (
    InMemoryKeyValueBucket,
    KeyAlreadyExistsError,
    RevisionMismatchError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper, asyncio shim
    return asyncio.run(coro)


def test_scenario_feature_flag_bootstrap() -> None:
    """Create-or-read pattern: first caller creates 'off'; subsequent readers observe."""
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        entry = await kv.create("feature.new_checkout", b"off")
        read = await kv.get("feature.new_checkout")
        assert read is not None
        assert read.value == b"off"
        assert read.revision == entry.revision
    _run(scenario())


def test_scenario_cas_update_flow() -> None:
    """Typical CAS workflow: read current, update with its revision."""
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("session", b"{}")
        current = await kv.get("session")
        assert current is not None
        updated = await kv.update("session", b"{\"user\":1}", current.revision)
        assert updated.revision > current.revision
    _run(scenario())


def test_scenario_competing_writers_one_wins() -> None:
    """Two clients holding the same stale revision: only one update succeeds."""
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        e = await kv.create("shared", b"v0")
        async def client(i: int) -> bool:
            try:
                await kv.update("shared", f"v{i}".encode(), revision=e.revision)
            except RevisionMismatchError:
                return False
            return True
        results = await asyncio.gather(client(1), client(2), client(3))
        assert sum(1 for r in results if r) == 1
    _run(scenario())


def test_scenario_delete_then_recreate() -> None:
    """Delete clears the active value; create after delete is permitted."""
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=3)
        await kv.create("k", b"v0")
        await kv.delete("k")
        assert await kv.get("k") is None
        # Re-create after delete is allowed.
        entry = await kv.create("k", b"v-reborn")
        assert entry.value == b"v-reborn"
    _run(scenario())


def test_scenario_watch_replay_preserves_order() -> None:
    """Watch on an existing key replays history in revision order."""
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket(history=10)
        e = await kv.create("k", b"v0")
        for i in range(4):
            e = await kv.update("k", f"v{i}".encode(), e.revision)
        revisions: list[int] = []
        async for entry in kv.watch("k"):
            revisions.append(entry.revision)
        assert revisions == sorted(revisions)
        assert len(revisions) == 5
    _run(scenario())


def test_scenario_create_twice_rejected() -> None:
    """Create on an existing key MUST fail."""
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        await kv.create("k", b"v")
        with pytest.raises(KeyAlreadyExistsError):
            await kv.create("k", b"w")
    _run(scenario())
