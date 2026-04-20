"""Metamorphic + differential tests for DeadLetterRoute.

Algebraic laws:
- send is monotonic on the parked set — N distinct envelopes yield depth N.
- purge-all is the left-inverse of send-N (depth returns to 0).
- inspect is idempotent — two inspects at rest yield the same snapshot.
- requeue is the right-inverse of send for a single key (DLR_INV_02 identity).
- failure_count is strictly monotonic under repeated same-key send.
- normalize_reason is idempotent.
"""

from __future__ import annotations

import asyncio

from DeadLetterRoute import (
    DeadLetterRoute,
    InMemoryDeadLetterSink,
    normalize_reason,
)
from EventEnvelope import EventEnvelope


def _env(eid: str) -> EventEnvelope:
    return EventEnvelope(id=eid, source="urn:m", type="m.e")


class _Collector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, EventEnvelope]] = []

    async def republish(self, topic: str, envelope: EventEnvelope) -> None:
        self.calls.append((topic, envelope))


def test_metamorphic_send_monotonic_depth() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        for i in range(10):
            await sink.send(route, _env(f"e{i}"), "r", attempt=2)
        assert sink.depth("d") == 10

    asyncio.run(run())


def test_metamorphic_purge_inverts_send() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        for i in range(5):
            await sink.send(route, _env(f"e{i}"), "r", attempt=2)
        evicted = sink.purge("d")
        assert len(evicted) == 5
        assert sink.depth("d") == 0

    asyncio.run(run())


def test_metamorphic_inspect_idempotent() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        for i in range(3):
            await sink.send(route, _env(f"e{i}"), "r", attempt=2)
        a = sink.inspect("d", emit_audit=False)
        b = sink.inspect("d", emit_audit=False)
        assert {r.origin_id for r in a} == {r.origin_id for r in b}
        assert len(a) == len(b) == 3

    asyncio.run(run())


def test_metamorphic_requeue_round_trip_preserves_identity() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="src", destination_topic="dst", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("alpha")
        await sink.send(route, env, "r", attempt=2)
        col = _Collector()
        await sink.requeue("dst", "urn:m", "alpha", col)
        assert col.calls[0][0] == "src"
        assert col.calls[0][1].id == env.id
        assert col.calls[0][1].source == env.source

    asyncio.run(run())


def test_metamorphic_failure_count_monotonic() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("same")
        counts: list[int] = []
        for i in range(6):
            await sink.send(route, env, f"r{i}", attempt=i + 1)
            counts.append(sink.inspect("d", emit_audit=False)[0].failure_count)
        assert counts == [1, 2, 3, 4, 5, 6]

    asyncio.run(run())


def test_metamorphic_normalize_reason_idempotent() -> None:
    for s in ("x", "already", "with spaces", "a" * 20):
        assert normalize_reason(s) == normalize_reason(normalize_reason(s))


def test_differential_inspect_matches_iter_parked() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        for i in range(4):
            await sink.send(route, _env(f"e{i}"), "r", attempt=2)
        ids_a = {r.origin_id for r in sink.inspect("d", emit_audit=False)}
        ids_b = {r.origin_id for r in sink.iter_parked("d")}
        assert ids_a == ids_b

    asyncio.run(run())
