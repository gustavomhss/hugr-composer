"""Behavioral end-to-end scenarios for TopicBus — prove invariants at runtime."""

from __future__ import annotations

import asyncio

from EventEnvelope import EventEnvelope
from TopicBus import Ack, InMemoryTopicBus, Nack


def _env(eid: str, *, partitionkey: str | None = None) -> EventEnvelope:
    exts: dict[str, str] | None = None
    if partitionkey is not None:
        exts = {"partitionkey": partitionkey}
    return EventEnvelope(
        id=eid, source="urn:bh", type="bh.e", extensions=exts,
    )


def test_scenario_orders_pipeline_end_to_end() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.1, max_redeliveries=2, dlq_topic="dlq")
        processed: list[str] = []

        async def on_order(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            processed.append(e.id)
            await ack()

        bus.subscribe("orders", "fulfillment", on_order)
        for i in range(5):
            await bus.publish("orders", _env(f"o{i}", partitionkey="cust-1"))
        assert processed == [f"o{i}" for i in range(5)]

    asyncio.run(run())


def test_scenario_flaky_handler_exhausts_then_dlq() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=1, dlq_topic="dlq")
        dlq: list[str] = []

        async def always_fail(_e: EventEnvelope, _a: Ack, nack: Nack) -> None:
            await nack("always")

        async def audit(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            dlq.append(e.id)
            await ack()

        bus.subscribe("t", "g", always_fail)
        bus.subscribe("dlq", "audit", audit)
        await bus.publish("t", _env("e-dead"))
        assert dlq == ["e-dead"]

    asyncio.run(run())


def test_scenario_two_groups_each_get_every_event() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus()
        group_a: list[str] = []
        group_b: list[str] = []

        async def ha(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            group_a.append(e.id)
            await ack()

        async def hb(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            group_b.append(e.id)
            await ack()

        bus.subscribe("t", "a", ha)
        bus.subscribe("t", "b", hb)
        for i in range(3):
            await bus.publish("t", _env(f"m{i}"))
        assert group_a == group_b == ["m0", "m1", "m2"]

    asyncio.run(run())


def test_scenario_same_key_preserves_order_under_retry() -> None:
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.05, max_redeliveries=5)
        seen: list[str] = []
        fail_once: dict[str, bool] = {}

        async def h(e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            if e.id == "b" and not fail_once.get("b"):
                fail_once["b"] = True
                await nack("flaky")
                return
            seen.append(e.id)
            await ack()

        bus.subscribe("t", "g", h)
        await bus.publish("t", _env("a", partitionkey="k"))
        await bus.publish("t", _env("b", partitionkey="k"))
        await bus.publish("t", _env("c", partitionkey="k"))
        assert seen == ["a", "b", "c"]

    asyncio.run(run())


def test_scenario_publish_commits_before_fanout() -> None:
    # Assert the append log contains the record BEFORE the handler ever runs
    # (the handler queries the log from inside its own body).
    async def run() -> None:
        bus = InMemoryTopicBus()
        witness: list[int] = []

        async def h(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            witness.append(bus.log_size())
            await ack()
            _ = e

        bus.subscribe("t", "g", h)
        await bus.publish("t", _env("only"))
        assert witness == [1]

    asyncio.run(run())


def test_scenario_timeout_rescues_stuck_consumer_without_blocking() -> None:
    # A stuck consumer MUST NOT prevent other work — timeout → DLQ within a
    # bounded wall-clock; the test overall completes quickly.
    async def run() -> None:
        bus = InMemoryTopicBus(ack_timeout_s=0.02, max_redeliveries=0, dlq_topic="dlq")
        dlq: list[str] = []

        async def stuck(_e: EventEnvelope, _a: Ack, _n: Nack) -> None:
            return  # never ack or nack

        async def audit(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            dlq.append(e.id)
            await ack()

        bus.subscribe("t", "g", stuck)
        bus.subscribe("dlq", "audit", audit)
        await bus.publish("t", _env("stuck"))
        assert dlq == ["stuck"]

    asyncio.run(run())
