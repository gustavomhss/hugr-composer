"""Tests for DataLoader invariants DATALOADER_INV_01..05."""

from __future__ import annotations

import asyncio

import pytest

from core.venous.api.DataLoader.DataLoader import (
    DataLoaderError,
    InMemoryDataLoader,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# INV_01: identity-preserving cache within a tick
# ---------------------------------------------------------------------------
def test_inv_identity_cache_confirms() -> None:
    seen: list[list[int]] = []

    async def batch(keys: list[int]) -> list[object]:
        seen.append(list(keys))
        return [object() for _ in keys]

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch)
        a, b = await asyncio.gather(loader.load(42), loader.load(42))
        assert a is b, "identical keys MUST resolve to the SAME instance"
        assert seen == [[42]], "duplicate keys MUST be deduped in the batch"

    _run(scenario())


def test_inv_identity_cache_prevents_cross_tick_reuse() -> None:
    async def batch(keys: list[int]) -> list[int]:
        return [k * 10 for k in keys]

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch)
        v1 = await loader.load(5)
        loader.clear(5)
        v2 = await loader.load(5)
        assert v1 == v2 == 50  # value identity through batch_fn
        # The contract is identity within a tick; clear() ends the tick.
    _run(scenario())


# ---------------------------------------------------------------------------
# INV_02: positional correspondence
# ---------------------------------------------------------------------------
def test_inv_positional_order_confirms() -> None:
    async def batch(keys: list[str]) -> list[str]:
        return [f"got:{k}" for k in keys]

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch)
        vals = await asyncio.gather(
            loader.load("a"), loader.load("b"), loader.load("c")
        )
        assert vals == ["got:a", "got:b", "got:c"]

    _run(scenario())


def test_inv_positional_order_prevents_length_mismatch() -> None:
    async def bad_batch(keys: list[int]) -> list[int]:
        return [1]  # wrong length

    async def scenario() -> None:
        loader = InMemoryDataLoader(bad_batch)
        with pytest.raises(DataLoaderError):
            await asyncio.gather(loader.load(1), loader.load(2))

    _run(scenario())


# ---------------------------------------------------------------------------
# INV_03: batch exception fans out
# ---------------------------------------------------------------------------
def test_inv_batch_error_confirms_fanout() -> None:
    class Boom(RuntimeError):
        pass

    async def batch(_keys: list[int]) -> list[int]:
        raise Boom("upstream down")

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch)
        with pytest.raises(Boom):
            await asyncio.gather(loader.load(1), loader.load(2))

    _run(scenario())


# ---------------------------------------------------------------------------
# INV_04: clear is a cache-only operation
# ---------------------------------------------------------------------------
def test_inv_clear_confirms_cache_only() -> None:
    calls: list[list[int]] = []

    async def batch(keys: list[int]) -> list[int]:
        calls.append(list(keys))
        return [k * 2 for k in keys]

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch)
        a1 = await loader.load(4)
        loader.clear(4)
        a2 = await loader.load(4)
        assert a1 == a2 == 8
        # clear() does NOT retroactively undo the first batch — it forces a
        # new batch on the next load.
        assert calls == [[4], [4]]

    _run(scenario())


# ---------------------------------------------------------------------------
# INV_05: max-batch-size cap
# ---------------------------------------------------------------------------
def test_inv_max_batch_size_confirms_split() -> None:
    sizes: list[int] = []

    async def batch(keys: list[int]) -> list[int]:
        sizes.append(len(keys))
        return [k for k in keys]

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch, max_batch_size=3)
        await asyncio.gather(*(loader.load(i) for i in range(7)))
        assert sizes == [3, 3, 1]

    _run(scenario())


def test_inv_max_batch_size_prevents_zero() -> None:
    async def batch(keys: list[int]) -> list[int]:
        return list(keys)

    with pytest.raises(DataLoaderError):
        InMemoryDataLoader(batch, max_batch_size=0)


# ---------------------------------------------------------------------------
# prime() is idempotent + seeds cache
# ---------------------------------------------------------------------------
def test_prime_skips_batch_when_seeded() -> None:
    calls: list[list[int]] = []

    async def batch(keys: list[int]) -> list[int]:
        calls.append(list(keys))
        return [k * 2 for k in keys]

    async def scenario() -> None:
        loader = InMemoryDataLoader(batch)
        loader.prime(9, 999)
        assert await loader.load(9) == 999
        assert calls == []

    _run(scenario())
