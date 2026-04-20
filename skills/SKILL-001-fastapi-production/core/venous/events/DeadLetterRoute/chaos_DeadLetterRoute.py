"""Chaos / game-day tests for DeadLetterRoute.

Failure injection: requeue target raises; malformed inputs; recursive
parking; bursts of concurrent parks; selective-purge key mismatches.
"""

from __future__ import annotations

import asyncio

import pytest

from DeadLetterRoute import (
    DeadLetterRoute,
    DeadLetterRouteInvariantError,
    InMemoryDeadLetterSink,
)
from EventEnvelope import EventEnvelope


def _env(eid: str) -> EventEnvelope:
    return EventEnvelope(id=eid, source="urn:c", type="c.e")


class _FailingBus:
    async def republish(self, topic: str, envelope: EventEnvelope) -> None:
        _ = topic, envelope
        raise RuntimeError("bus_down")


def test_chaos_requeue_failure_keeps_record_parked() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        await sink.send(route, _env("e"), "r", attempt=2)
        with pytest.raises(RuntimeError, match="bus_down"):
            await sink.requeue("d", "urn:c", "e", _FailingBus())
        # Still parked — requeue did NOT silently drop the envelope.
        assert sink.depth("d") == 1

    asyncio.run(run())


def test_chaos_burst_of_parks_all_accounted() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        n = 200
        await asyncio.gather(
            *(sink.send(route, _env(f"e{i}"), "r", attempt=2) for i in range(n)),
        )
        assert sink.depth("d") == n
        sends = [a for a in sink.audit_log() if a.event_name == "dlq.sent"]
        assert len(sends) == n

    asyncio.run(run())


def test_chaos_recursive_dlq_rejected() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        env = EventEnvelope(
            id="z", source="urn:c", type="c.e",
            extensions={"dlqparked": "d", "dlqdest": "d"},
        )
        with pytest.raises(DeadLetterRouteInvariantError):
            await sink.send(route, env, "r", attempt=2)

    asyncio.run(run())


def test_chaos_purge_half_parameters_rejected() -> None:
    route = DeadLetterRoute(
        source_topic="s", destination_topic="d", max_deliveries=1,
    )
    sink = InMemoryDeadLetterSink()
    with pytest.raises(DeadLetterRouteInvariantError):
        sink.purge("d", envelope_source="x", envelope_id=None)
    with pytest.raises(DeadLetterRouteInvariantError):
        sink.purge("d", envelope_source=None, envelope_id="y")
    _ = route  # constructed to assert the code path, keep lint happy


def test_chaos_attempt_must_be_positive_int() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        for bad in (0, -1):
            with pytest.raises(DeadLetterRouteInvariantError):
                await sink.send(route, _env("x"), "r", attempt=bad)

    asyncio.run(run())


def test_chaos_selective_purge_miss_is_noop() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        await sink.send(route, _env("present"), "r", attempt=2)
        evicted = sink.purge("d", envelope_source="urn:c", envelope_id="absent")
        assert evicted == ()
        assert sink.depth("d") == 1

    asyncio.run(run())


def test_chaos_reason_truncation_does_not_crash() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        huge = "x" * 10_000
        await sink.send(route, _env("x"), huge, attempt=2)
        rec = sink.inspect("d")[0]
        assert len(rec.last_reason) <= 512

    asyncio.run(run())
