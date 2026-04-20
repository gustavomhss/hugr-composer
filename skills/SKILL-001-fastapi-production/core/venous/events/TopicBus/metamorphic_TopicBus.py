"""Metamorphic + differential tests for TopicBus.

Algebraic laws:
- publish is monotonic on the append log — N publishes append exactly N records.
- seq is strictly increasing over calls to publish().
- partition_key_of is deterministic (same envelope → same key).
- Same-key publish order is preserved at every group.
- Groups are independent — two groups on the same topic see the same stream.
"""

from __future__ import annotations

import asyncio

from EventEnvelope import EventEnvelope
from TopicBus import Ack, InMemoryTopicBus, Nack, partition_key_of


def _env(eid: str, *, partitionkey: str | None = None) -> EventEnvelope:
    exts: dict[str, str] | None = None
    if partitionkey is not None:
        exts = {"partitionkey": partitionkey}
    return EventEnvelope(id=eid, source="urn:m", type="m.e", extensions=exts)


def test_metamorphic_publish_monotonic_log_growth() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()

        async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            await ack()

        bus.subscribe("t", "g", h)
        for i in range(7):
            await bus.publish("t", _env(f"e{i}", partitionkey="k"))
        assert bus.log_size() == 7

    asyncio.run(run())


def test_metamorphic_seq_strictly_increasing() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()

        async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            await ack()

        bus.subscribe("t", "g", h)
        for i in range(5):
            await bus.publish("t", _env(f"e{i}", partitionkey="k"))
        snap = bus.log_snapshot("t", "k")
        seqs = [r.seq for r in snap]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)

    asyncio.run(run())


def test_metamorphic_partition_key_deterministic() -> None:
    e = _env("id", partitionkey="k42")
    assert partition_key_of(e) == partition_key_of(e) == "k42"


def test_metamorphic_same_key_order_preserved() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        seen: list[str] = []

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            seen.append(e.id)
            await ack()

        bus.subscribe("t", "g", h)
        ids = [f"i{i}" for i in range(15)]
        await asyncio.gather(
            *(bus.publish("t", _env(i, partitionkey="k")) for i in ids),
        )
        assert seen == ids

    asyncio.run(run())


def test_differential_two_groups_same_stream() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        g1: list[str] = []
        g2: list[str] = []

        async def h1(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            g1.append(e.id)
            await ack()

        async def h2(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            g2.append(e.id)
            await ack()

        bus.subscribe("t", "g1", h1)
        bus.subscribe("t", "g2", h2)
        for i in range(4):
            await bus.publish("t", _env(f"x{i}", partitionkey="k"))
        assert g1 == g2

    asyncio.run(run())
