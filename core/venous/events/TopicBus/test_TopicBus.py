"""Unit tests for TopicBus — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest

from EventEnvelope import EventEnvelope
from TopicBus import (
    Ack,
    InMemoryTopicBus,
    Nack,
    TopicBusInvariantError,
    partition_key_of,
)


def _env(
    eid: str,
    *,
    src: str = "urn:test",
    etype: str = "t.evt",
    subject: str | None = None,
    partitionkey: str | None = None,
) -> EventEnvelope:
    exts: dict[str, str] | None = None
    if partitionkey is not None:
        exts = {"partitionkey": partitionkey}
    return EventEnvelope(
        id=eid, source=src, type=etype, subject=subject, extensions=exts,
    )


# ---------------------------------------------------------------------------
# TB_INV_01 — at-least-once delivery, no infinite block
# ---------------------------------------------------------------------------
def test_inv_at_least_once_confirms() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        got: list[str] = []

        async def handler(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            got.append(e.id)
            await ack()

        bus.subscribe("t", "g", handler)
        await bus.publish("t", _env("e1"))
        await bus.publish("t", _env("e2"))
        assert got == ["e1", "e2"]

    asyncio.run(run())


def test_inv_at_least_once_prevents() -> None:
    # Infinite ack wait is FORBIDDEN — ack_timeout_s <= 0 must be rejected.
    with pytest.raises(TopicBusInvariantError):
        InMemoryTopicBus(ack_timeout_s=0.0)
    with pytest.raises(TopicBusInvariantError):
        InMemoryTopicBus(ack_timeout_s=-1.0)


def test_inv_at_least_once_under_failure() -> None:
    # A handler that neither acks nor nacks MUST NOT block forever; the
    # bus times out and routes to DLQ (or marks exhausted) within a bounded
    # wall-clock.
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=1, dlq_topic="dlq")
        dlq_got: list[str] = []

        async def silent(_e: EventEnvelope, _a: Ack, _n: Nack) -> None:
            # Never ack, never nack — simulate a stuck consumer.
            return

        async def dlq_handler(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            dlq_got.append(e.id)
            await ack()

        bus.subscribe("t", "g", silent)
        bus.subscribe("dlq", "audit", dlq_handler)
        await bus.publish("t", _env("stuck"))
        assert dlq_got == ["stuck"]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# TB_INV_02 — exclusive dispatch per group
# ---------------------------------------------------------------------------
def test_inv_exclusive_dispatch_confirms() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        inflight = 0
        peak = 0

        async def handler(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.001)
            inflight -= 1
            await ack()

        bus.subscribe("t", "g", handler)
        # Same partition key → serialized.
        await asyncio.gather(
            *(bus.publish("t", _env(f"e{i}", partitionkey="k")) for i in range(10)),
        )
        assert peak == 1

    asyncio.run(run())


def test_inv_exclusive_dispatch_prevents() -> None:
    # The bus MUST refuse an empty group on subscribe (invalid per contract).
    bus = InMemoryTopicBus()

    async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
        await ack()

    with pytest.raises(TopicBusInvariantError):
        bus.subscribe("t", "", h)
    with pytest.raises(TopicBusInvariantError):
        bus.subscribe("", "g", h)


def test_inv_exclusive_dispatch_under_failure() -> None:
    # Even when a handler raises mid-flight, the next delivery to the same
    # (group, key) waits for the current dispatch to drain — no overlap.
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=0, dlq_topic="dlq")
        concurrency: list[int] = [0]
        peak: list[int] = [0]
        seen: list[str] = []

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            # TB_INV_02 exclusive-dispatch observer: the raising branch MUST
            # only fire on the primary topic, NEVER on the DLQ — otherwise
            # the DLQ handler's failure routes right back to the DLQ and
            # creates an infinite redeliver loop (exercised by an older
            # version of this test; fixed by splitting the DLQ ack path).
            concurrency[0] += 1
            peak[0] = max(peak[0], concurrency[0])
            try:
                seen.append(e.id)
                raise RuntimeError("flaky")
            finally:
                concurrency[0] -= 1

        async def dlq_sink(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            # DLQ subscriber MUST ack cleanly so the bus terminates dispatch.
            seen.append(f"dlq:{e.id}")
            await ack()

        bus.subscribe("t", "g", h)
        bus.subscribe("dlq", "audit", dlq_sink)
        await bus.publish("t", _env("bad", partitionkey="k"))
        await bus.publish("t", _env("good", partitionkey="k"))
        assert peak[0] == 1
        assert "bad" in seen and "good" in seen
        assert "dlq:bad" in seen and "dlq:good" in seen

    asyncio.run(run())


# ---------------------------------------------------------------------------
# TB_INV_03 — nack triggers redelivery or DLQ
# ---------------------------------------------------------------------------
def test_inv_nack_redelivery_confirms() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=3)
        attempts: list[int] = [0]

        async def flaky(_e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            attempts[0] += 1
            if attempts[0] < 3:
                await nack("transient")
            else:
                await ack()

        bus.subscribe("t", "g", flaky)
        env = _env("retry")
        await bus.publish("t", env)
        stats = bus.dispatch_stats("t", "g", env)
        assert stats["delivered"] == 3
        assert stats["acks"] == 1
        assert stats["dlq"] == 0

    asyncio.run(run())


def test_inv_nack_redelivery_prevents() -> None:
    # max_redeliveries must be non-negative; negative values FORBIDDEN.
    with pytest.raises(TopicBusInvariantError):
        InMemoryTopicBus(max_redeliveries=-1)


def test_inv_nack_redelivery_under_failure() -> None:
    # After exhausting redeliveries, the envelope MUST land on the DLQ topic.
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=2, dlq_topic="dlq.t")
        dlq_seen: list[str] = []

        async def bad(_e: EventEnvelope, _a: Ack, nack: Nack) -> None:
            await nack("permanent")

        async def audit(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            dlq_seen.append(e.id)
            await ack()

        bus.subscribe("t", "g", bad)
        bus.subscribe("dlq.t", "audit", audit)
        env = _env("dead")
        await bus.publish("t", env)
        assert dlq_seen == ["dead"]
        # DLQ append went through the real log (TB_INV_05): two topics got writes.
        assert bus.log_size() == 2

    asyncio.run(run())


# ---------------------------------------------------------------------------
# TB_INV_04 — per-key order, no global order guarantee
# ---------------------------------------------------------------------------
def test_inv_per_key_order_confirms() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        seen_k1: list[str] = []

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            if partition_key_of(e) == "k1":
                seen_k1.append(e.id)
            await ack()

        bus.subscribe("t", "g", h)
        ids = [f"k1-{i}" for i in range(20)]
        # Fire concurrently; per-key lock must serialize.
        await asyncio.gather(
            *(bus.publish("t", _env(i, partitionkey="k1")) for i in ids),
        )
        assert seen_k1 == ids


    asyncio.run(run())


def test_inv_per_key_order_prevents() -> None:
    # Distinct partition keys MUST NOT block each other — global order is
    # explicitly NOT guaranteed; the test asserts the bus dispatches in
    # parallel across keys.
    async def run() -> None:
        bus = InMemoryTopicBus()
        running: list[int] = [0]
        peak: list[int] = [0]

        async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            await asyncio.sleep(0.01)
            running[0] -= 1
            await ack()

        bus.subscribe("t", "g", h)
        await asyncio.gather(
            bus.publish("t", _env("a", partitionkey="k1")),
            bus.publish("t", _env("b", partitionkey="k2")),
            bus.publish("t", _env("c", partitionkey="k3")),
        )
        # Cross-key parallelism is permitted (global order NOT guaranteed).
        assert peak[0] >= 2

    asyncio.run(run())


def test_inv_per_key_order_under_failure() -> None:
    # Under nack + redelivery, per-key order STILL holds — a retried envelope
    # MUST NOT overtake the next same-key envelope.
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=2)
        seen: list[str] = []
        attempts: dict[str, int] = {}

        async def h(e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            attempts[e.id] = attempts.get(e.id, 0) + 1
            if e.id == "a" and attempts[e.id] == 1:
                await nack("retry")
                return
            seen.append(e.id)
            await ack()

        bus.subscribe("t", "g", h)
        await bus.publish("t", _env("a", partitionkey="k"))
        await bus.publish("t", _env("b", partitionkey="k"))
        assert seen == ["a", "b"]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# TB_INV_05 — publish commits append log atomically
# ---------------------------------------------------------------------------
def test_inv_publish_append_atomic_confirms() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()

        async def h(_e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            await ack()

        bus.subscribe("t", "g", h)
        await bus.publish("t", _env("x", partitionkey="k"))
        snap = bus.log_snapshot("t", "k")
        assert len(snap) == 1
        assert snap[0].envelope.id == "x"
        assert snap[0].seq == 1

    asyncio.run(run())


def test_inv_publish_append_atomic_prevents() -> None:
    # Empty topic is rejected — no silent append.
    async def run() -> None:
        bus = InMemoryTopicBus()
        with pytest.raises(TopicBusInvariantError):
            await bus.publish("", _env("x"))
        assert bus.log_size() == 0

    asyncio.run(run())


def test_inv_publish_append_atomic_under_failure() -> None:
    # After close(), publish is rejected and the log does NOT grow.
    async def run() -> None:
        bus = InMemoryTopicBus()
        bus.close()
        with pytest.raises(TopicBusInvariantError):
            await bus.publish("t", _env("x"))
        assert bus.log_size() == 0

    asyncio.run(run())
