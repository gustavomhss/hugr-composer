"""Chaos / game-day tests for TopicBus.

Simulates stuck consumers, always-nacking handlers, handler exceptions,
bursts of concurrent publishes, and close-under-load to confirm the bus
never enters an inconsistent state.
"""

from __future__ import annotations

import asyncio

import pytest

from EventEnvelope import EventEnvelope
from TopicBus import Ack, InMemoryTopicBus, Nack, TopicBusInvariantError


def _env(eid: str, *, partitionkey: str | None = None) -> EventEnvelope:
    exts: dict[str, str] | None = None
    if partitionkey is not None:
        exts = {"partitionkey": partitionkey}
    return EventEnvelope(id=eid, source="urn:c", type="c.e", extensions=exts)


def test_chaos_handler_exception_triggers_redelivery_then_dlq() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=2, dlq_topic="dlq")
        dlq: list[str] = []

        async def boom(_e: EventEnvelope, _a: Ack, _n: Nack) -> None:
            raise RuntimeError("explode")

        async def audit(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            dlq.append(e.id)
            await ack()

        bus.subscribe("t", "g", boom)
        bus.subscribe("dlq", "a", audit)
        await bus.publish("t", _env("x"))
        assert dlq == ["x"]

    asyncio.run(run())


def test_chaos_all_nack_no_dlq_marks_exhausted() -> None:
    async def run() -> None:
        # No DLQ configured → exhausted dispatch with dlq_routed=False.
        bus = InMemoryTopicBus(ack_timeout_s=0.02, max_redeliveries=0)

        async def nack_all(_e: EventEnvelope, _a: Ack, nack: Nack) -> None:
            await nack("perma")

        bus.subscribe("t", "g", nack_all)
        env = _env("stuck")
        await bus.publish("t", env)
        stats = bus.dispatch_stats("t", "g", env)
        assert stats["dlq"] == 0
        assert stats["nacks"] >= 1

    asyncio.run(run())


def test_chaos_many_concurrent_publishes_preserve_log_count() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()

        async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            await ack()

        bus.subscribe("t", "g", h)
        n = 200
        await asyncio.gather(
            *(bus.publish("t", _env(f"e{i}", partitionkey=f"k{i % 5}"))
              for i in range(n)),
        )
        assert bus.log_size() == n

    asyncio.run(run())


def test_chaos_close_rejects_publish_and_subscribe() -> None:
    bus = InMemoryTopicBus()
    bus.close()

    async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
        await ack()

    with pytest.raises(TopicBusInvariantError):
        bus.subscribe("t", "g", h)

    async def run() -> None:
        with pytest.raises(TopicBusInvariantError):
            await bus.publish("t", _env("x"))

    asyncio.run(run())


def test_chaos_stuck_then_recovering_consumer() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.02, max_redeliveries=3)
        attempts: list[int] = [0]

        async def recover(_e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            attempts[0] += 1
            if attempts[0] < 3:
                # Simulate a stuck handler on early attempts.
                await nack("stuck")
                return
            await ack()

        bus.subscribe("t", "g", recover)
        env = _env("gotcha")
        await bus.publish("t", env)
        stats = bus.dispatch_stats("t", "g", env)
        assert stats["acks"] == 1

    asyncio.run(run())


def test_chaos_interleaved_keys_never_deadlock() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        seen: list[tuple[str, str]] = []

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            seen.append((e.id, e.extensions["partitionkey"] if e.extensions else ""))
            await ack()

        bus.subscribe("t", "g", h)
        tasks = []
        for i in range(50):
            key = f"k{i % 7}"
            tasks.append(bus.publish("t", _env(f"e{i}", partitionkey=key)))
        await asyncio.gather(*tasks)
        assert len(seen) == 50

    asyncio.run(run())


def test_chaos_empty_topic_is_rejected() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        with pytest.raises(TopicBusInvariantError):
            await bus.publish("", _env("x"))

    asyncio.run(run())
