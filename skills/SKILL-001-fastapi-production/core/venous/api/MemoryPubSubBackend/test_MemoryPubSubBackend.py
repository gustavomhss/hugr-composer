"""Unit tests for MemoryPubSubBackend (MP_INV_01..03).

These cover the same behavioural contract as the Wave-1.5
``events.PubSub.InMemoryPubSub`` motor but kept here for
compatibility with the 3 recipe refs that still cite
``MemoryPubSubBackend`` by name. New code should prefer the motor.
"""
from __future__ import annotations

import asyncio

import pytest

from MemoryPubSubBackend import MemoryPubSubBackend


# ---------------------------------------------------------------------------
# MP_INV_01 — fanout-to-active + MP_INV_02 — topic isolation
# ---------------------------------------------------------------------------
def test_inv_publish_confirms() -> None:
    """One publish reaches every active subscriber on the topic."""
    async def _go() -> None:
        bus = MemoryPubSubBackend()

        async def collect_one(topic: str) -> object:
            async for item in bus.subscribe(topic):
                return item
            return None

        tasks = [asyncio.create_task(collect_one("items")) for _ in range(3)]
        await asyncio.sleep(0)  # let subscribers register

        await bus.publish("items", {"id": 1})
        results = await asyncio.gather(*tasks)
        assert results == [{"id": 1}, {"id": 1}, {"id": 1}]

    asyncio.run(_go())


def test_inv_publish_prevents() -> None:
    """Publish to A never reaches subscribers of B (topic isolation)."""
    async def _go() -> None:
        bus = MemoryPubSubBackend()
        seen_b: list[object] = []

        async def b_sub() -> None:
            async for item in bus.subscribe("B"):
                seen_b.append(item)
                if item == "stop":
                    return

        task = asyncio.create_task(b_sub())
        await asyncio.sleep(0)

        for i in range(10):
            await bus.publish("A", f"noise-{i}")

        await bus.publish("B", "stop")
        await task
        assert seen_b == ["stop"]

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# MP_INV_03 — subscriber cleanup on aclose + close()
# ---------------------------------------------------------------------------
def test_inv_publish_under_failure() -> None:
    """Closing the backend drains every active subscriber and clears
    the registry (MP_INV_03)."""
    async def _go() -> None:
        bus = MemoryPubSubBackend()
        collected: list[object] = []

        async def sub() -> None:
            async for item in bus.subscribe("items"):
                collected.append(item)

        task = asyncio.create_task(sub())
        await asyncio.sleep(0)
        # Internal dict shows one registered subscriber
        assert len(bus._subscribers["items"]) == 1  # type: ignore[attr-defined]

        await bus.publish("items", "hello")
        bus.close()  # inject sentinel into every active queue
        await task

        # After close, subscriber's finally block removed its queue
        # AND the empty list pruned the topic key entirely.
        assert "items" not in bus._subscribers  # type: ignore[attr-defined]

    asyncio.run(_go())


def test_per_subscriber_ordering_preserved() -> None:
    """For one subscriber, publish order is the observed order."""
    async def _go() -> None:
        bus = MemoryPubSubBackend()
        got: list[int] = []

        async def sub() -> None:
            async for item in bus.subscribe("items"):
                got.append(item)
                if len(got) == 50:
                    return

        task = asyncio.create_task(sub())
        await asyncio.sleep(0)

        for i in range(50):
            await bus.publish("items", i)
        await task
        assert got == list(range(50))

    asyncio.run(_go())


def test_slots_prevent_accidental_state() -> None:
    bus = MemoryPubSubBackend()
    with pytest.raises(AttributeError):
        bus.extra = 1  # type: ignore[attr-defined]
