"""Concurrency / linearizability harness for TopicBus.

Confirms that:
- Concurrent publishes on the same key are serialized at the handler.
- Concurrent publishes on distinct keys can overlap (global order is NOT
  required — per-key order IS).
- Nack + redelivery does not reorder same-key envelopes.
"""

from __future__ import annotations

import asyncio

from EventEnvelope import EventEnvelope
from TopicBus import Ack, InMemoryTopicBus, Nack


def _env(eid: str, key: str) -> EventEnvelope:
    return EventEnvelope(
        id=eid, source="urn:cc", type="cc.e", extensions={"partitionkey": key},
    )


def test_concurrent_same_key_serialized_in_order() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        seen: list[str] = []
        inflight: list[int] = [0]
        peak: list[int] = [0]

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            inflight[0] += 1
            peak[0] = max(peak[0], inflight[0])
            await asyncio.sleep(0.001)
            seen.append(e.id)
            inflight[0] -= 1
            await ack()

        bus.subscribe("t", "g", h)
        ids = [f"e{i:02d}" for i in range(30)]
        await asyncio.gather(*(bus.publish("t", _env(i, "k")) for i in ids))
        assert seen == ids
        assert peak[0] == 1

    asyncio.run(run())


def test_concurrent_distinct_keys_can_overlap() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        running: list[int] = [0]
        peak: list[int] = [0]

        async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            await asyncio.sleep(0.005)
            running[0] -= 1
            await ack()

        bus.subscribe("t", "g", h)
        await asyncio.gather(
            *(bus.publish("t", _env(f"e{i}", f"k{i}")) for i in range(6)),
        )
        assert peak[0] >= 2

    asyncio.run(run())


def test_concurrent_nack_redelivery_preserves_same_key_order() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.02, max_redeliveries=3)
        seen: list[str] = []
        fail_once: dict[str, bool] = {}

        async def h(e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            if e.id.endswith("1") and not fail_once.get(e.id):
                fail_once[e.id] = True
                await nack("retry")
                return
            seen.append(e.id)
            await ack()

        bus.subscribe("t", "g", h)
        for i in range(5):
            await bus.publish("t", _env(f"i{i}", "k"))
        assert seen == [f"i{i}" for i in range(5)]

    asyncio.run(run())


def test_concurrent_burst_publishes_all_arrive() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        seen: list[str] = []

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            seen.append(e.id)
            await ack()

        bus.subscribe("t", "g", h)
        n = 100
        await asyncio.gather(
            *(bus.publish("t", _env(f"e{i}", f"k{i % 10}")) for i in range(n)),
        )
        assert len(seen) == n
        assert len({s for s in seen}) == n

    asyncio.run(run())
