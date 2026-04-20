"""End-to-end behavioral scenarios for DeadLetterRoute.

Each scenario exercises the full park → inspect → requeue / purge state
machine end-to-end and asserts catalog invariants at runtime.
"""

from __future__ import annotations

import asyncio

from DeadLetterRoute import (
    DeadLetterRoute,
    InMemoryDeadLetterSink,
)
from EventEnvelope import EventEnvelope


def _env(eid: str, *, src: str = "urn:bh") -> EventEnvelope:
    return EventEnvelope(id=eid, source=src, type="bh.e")


class _MemoryBus:
    """Collaborator that captures republished events — stands in for TopicBus."""

    def __init__(self) -> None:
        self.published: list[tuple[str, EventEnvelope]] = []

    async def republish(self, topic: str, envelope: EventEnvelope) -> None:
        self.published.append((topic, envelope))


def test_scenario_park_inspect_requeue_round_trip() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="orders",
            destination_topic="orders.dlq",
            max_deliveries=5,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("o-1", src="urn:svc.orders")

        # 1) Park after budget exhaustion (attempt = max + 1).
        await sink.send(route, env, "handler_exception:ValueError", attempt=6)
        assert sink.depth("orders.dlq") == 1

        # 2) Operator inspects.
        parked = sink.inspect("orders.dlq")
        assert len(parked) == 1
        assert parked[0].origin_id == "o-1"
        assert parked[0].last_reason == "handler_exception:ValueError"

        # 3) Operator requeues to the source topic.
        bus = _MemoryBus()
        rec = await sink.requeue("orders.dlq", "urn:svc.orders", "o-1", bus)

        # 4) DLQ is drained; republish hit the SOURCE topic.
        assert sink.depth("orders.dlq") == 0
        assert bus.published == [("orders", env)]
        assert rec.origin_id == "o-1"

        # 5) Audit log has send + requeue.
        names = [a.event_name for a in sink.audit_log()]
        assert "dlq.sent" in names
        assert "dlq.requeued" in names

    asyncio.run(run())


def test_scenario_purge_mass_evict_audits_every_record() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="inv", destination_topic="inv.dlq", max_deliveries=2,
        )
        sink = InMemoryDeadLetterSink()
        for i in range(7):
            await sink.send(route, _env(f"k{i}"), "poison", attempt=3)
        evicted = sink.purge("inv.dlq", reason="dlq_drill")
        assert len(evicted) == 7
        assert sink.depth("inv.dlq") == 0
        purges = [a for a in sink.audit_log() if a.event_name == "dlq.purged"]
        assert len(purges) == 7
        assert all(p.reason == "dlq_drill" for p in purges)

    asyncio.run(run())


def test_scenario_selective_purge_leaves_others_parked() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="x", destination_topic="x.dlq", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        await sink.send(route, _env("a"), "r", attempt=2)
        await sink.send(route, _env("b"), "r", attempt=2)
        await sink.send(route, _env("c"), "r", attempt=2)
        sink.purge(
            "x.dlq", envelope_source="urn:bh", envelope_id="b", reason="fix_applied",
        )
        ids = sorted(r.origin_id for r in sink.inspect("x.dlq"))
        assert ids == ["a", "c"]

    asyncio.run(run())


def test_scenario_repeated_park_monotonic_failure_count() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=3,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("flaky")
        for i in range(4):
            await sink.send(route, env, f"attempt_{i}", attempt=i + 1)
        rec = sink.inspect("d")[0]
        assert rec.failure_count == 4
        # first_failed_at <= last_failed_at.
        assert rec.first_failed_at <= rec.last_failed_at

    asyncio.run(run())


def test_scenario_requeue_preserves_identity_end_to_end() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        env = EventEnvelope(
            id="corr-12", source="urn:payments.svc",
            type="payments.charge.failed",
            subject="acct-42",
        )
        await sink.send(route, env, "stripe_429", attempt=2)
        bus = _MemoryBus()
        await sink.requeue("d", "urn:payments.svc", "corr-12", bus)
        # The republished envelope is BYTE-IDENTICAL to the original.
        assert bus.published[0][1] is env
        assert bus.published[0][1].id == "corr-12"
        assert bus.published[0][1].source == "urn:payments.svc"

    asyncio.run(run())


def test_scenario_dlq_survives_operator_inspection_audit_trail() -> None:
    # Inspect is a read operation that leaves the DLQ unchanged but emits an
    # audit marker so an on-call engineer's investigation is reconstructible.
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        await sink.send(route, _env("e"), "r", attempt=2)
        for _ in range(3):
            sink.inspect("d")
        assert sink.depth("d") == 1
        inspects = [a for a in sink.audit_log() if a.event_name == "dlq.inspected"]
        assert len(inspects) == 3

    asyncio.run(run())
