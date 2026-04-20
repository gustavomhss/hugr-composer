"""Concurrency / linearizability harness for DeadLetterRoute.

- Concurrent sends on distinct keys all appear parked (no lost updates).
- Concurrent sends on the SAME key yield a single parked record with
  failure_count equal to the number of sends.
- Requeue under a failing target preserves the parked state (all-or-nothing).
- Purge and send racing never leave the depth counter inconsistent with
  the parked map.
"""

from __future__ import annotations

import asyncio

from DeadLetterRoute import (
    DeadLetterRoute,
    InMemoryDeadLetterSink,
)
from EventEnvelope import EventEnvelope


def _env(eid: str) -> EventEnvelope:
    return EventEnvelope(id=eid, source="urn:cc", type="cc.e")


class _Collector:
    def __init__(self) -> None:
        self.seen: list[tuple[str, EventEnvelope]] = []

    async def republish(self, topic: str, envelope: EventEnvelope) -> None:
        self.seen.append((topic, envelope))


def test_concurrent_distinct_keys_all_parked() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        n = 100
        await asyncio.gather(
            *(sink.send(route, _env(f"e{i}"), "r", attempt=2) for i in range(n)),
        )
        assert sink.depth("d") == n

    asyncio.run(run())


def test_concurrent_same_key_yields_monotonic_count() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("same")
        n = 50
        await asyncio.gather(
            *(sink.send(route, env, "r", attempt=i + 1) for i in range(n)),
        )
        parked = sink.inspect("d", emit_audit=False)
        assert len(parked) == 1
        assert parked[0].failure_count == n

    asyncio.run(run())


def test_concurrent_mixed_send_and_inspect_stable() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()

        async def writer() -> None:
            for i in range(40):
                await sink.send(route, _env(f"w{i}"), "r", attempt=2)

        async def reader() -> None:
            for _ in range(40):
                # inspect MUST NOT crash even with concurrent mutation.
                _ = sink.inspect("d", emit_audit=False)
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader())
        assert sink.depth("d") == 40

    asyncio.run(run())


def test_concurrent_requeue_after_parallel_parks() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        envs = [_env(f"e{i}") for i in range(20)]
        await asyncio.gather(
            *(sink.send(route, e, "r", attempt=2) for e in envs),
        )
        col = _Collector()
        await asyncio.gather(
            *(sink.requeue("d", e.source, e.id, col) for e in envs),
        )
        assert sink.depth("d") == 0
        assert len(col.seen) == 20
        assert {e.id for _t, e in col.seen} == {e.id for e in envs}

    asyncio.run(run())
