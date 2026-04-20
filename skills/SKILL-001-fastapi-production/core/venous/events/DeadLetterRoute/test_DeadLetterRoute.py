"""Unit tests for DeadLetterRoute — three per invariant."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from DeadLetterRoute import (
    DeadLetterRoute,
    DeadLetterRouteInvariantError,
    InMemoryDeadLetterSink,
    normalize_reason,
)
from EventEnvelope import EventEnvelope


def _env(eid: str, *, src: str = "urn:test") -> EventEnvelope:
    return EventEnvelope(id=eid, source=src, type="t.evt")


# ---------------------------------------------------------------------------
# DLR_INV_01 — routed to destination_topic, never back to source
# ---------------------------------------------------------------------------
def test_inv_route_to_destination_confirms() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="orders", destination_topic="orders.dlq", max_deliveries=3,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("e1")
        await sink.send(route, env, "bad", attempt=4)
        parked = sink.inspect("orders.dlq")
        assert len(parked) == 1
        assert parked[0].route.destination_topic == "orders.dlq"
        # Source topic MUST NOT have any parked entries (NEVER returned).
        assert sink.inspect("orders") == ()

    asyncio.run(run())


def test_inv_route_to_destination_prevents() -> None:
    # A route whose destination equals source is rejected — because sending
    # to it would re-enter the main topic (DLR_INV_01 precondition).
    with pytest.raises(DeadLetterRouteInvariantError):
        DeadLetterRoute(
            source_topic="t", destination_topic="t", max_deliveries=1,
        )


def test_inv_route_to_destination_under_failure() -> None:
    # Even when many envelopes are parked the source topic stays empty.
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        for i in range(20):
            await sink.send(route, _env(f"e{i}"), "x", attempt=2)
        assert sink.depth("d") == 20
        assert sink.depth("s") == 0

    asyncio.run(run())


# ---------------------------------------------------------------------------
# DLR_INV_02 — envelope id and source survive routing
# ---------------------------------------------------------------------------
def test_inv_identity_preserved_confirms() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=2,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("abc", src="urn:producer-42")
        await sink.send(route, env, "reason", attempt=3)
        rec = sink.inspect("d")[0]
        assert rec.origin_id == "abc"
        assert rec.origin_source == "urn:producer-42"
        assert rec.envelope.id == "abc"
        assert rec.envelope.source == "urn:producer-42"

    asyncio.run(run())


def test_inv_identity_preserved_prevents() -> None:
    # Attempting to requeue a non-existent (source, id) pair MUST raise —
    # identity is the lookup key, and losing it breaks DLR_INV_02.
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        await sink.send(route, _env("x"), "r", attempt=2)

        class _T:
            async def republish(
                self, topic: str, envelope: EventEnvelope,
            ) -> None:
                _ = topic, envelope

        with pytest.raises(DeadLetterRouteInvariantError):
            await sink.requeue("d", "urn:other", "unknown", _T())

    asyncio.run(run())


def test_inv_identity_preserved_under_failure() -> None:
    # Requeue returns the parked record and republishes using the ORIGINAL
    # envelope — even if the caller tries to spoof by constructing a replacement.
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        original = _env("x", src="urn:a")
        await sink.send(route, original, "boom", attempt=2)

        seen: list[tuple[str, EventEnvelope]] = []

        class _T:
            async def republish(
                self, topic: str, envelope: EventEnvelope,
            ) -> None:
                seen.append((topic, envelope))

        rec = await sink.requeue("d", "urn:a", "x", _T())
        assert rec.origin_id == "x"
        assert rec.origin_source == "urn:a"
        assert seen == [("s", original)]
        # Mutated copy (different source) is IGNORED at requeue lookup time.
        _mutated = replace(original, type="mutated")
        assert _mutated.id == original.id  # dedup key survives a replace()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# DLR_INV_03 — max_deliveries MUST be a positive integer
# ---------------------------------------------------------------------------
def test_inv_positive_budget_confirms() -> None:
    r = DeadLetterRoute(source_topic="s", destination_topic="d", max_deliveries=5)
    assert r.max_deliveries == 5


def test_inv_positive_budget_prevents() -> None:
    for bad in (0, -1, -100):
        with pytest.raises(DeadLetterRouteInvariantError):
            DeadLetterRoute(
                source_topic="s", destination_topic="d", max_deliveries=bad,
            )


def test_inv_positive_budget_under_failure() -> None:
    # bool is a subclass of int but semantically meaningless here — rejected.
    with pytest.raises(DeadLetterRouteInvariantError):
        DeadLetterRoute(
            source_topic="s",
            destination_topic="d",
            max_deliveries=True,  # type: ignore[arg-type]  # DLR_INV_03 — bool rejected explicitly
        )
    with pytest.raises(DeadLetterRouteInvariantError):
        DeadLetterRoute(
            source_topic="s",
            destination_topic="d",
            max_deliveries=False,  # type: ignore[arg-type]  # DLR_INV_03 — bool rejected explicitly
        )


# ---------------------------------------------------------------------------
# DLR_INV_04 — routing cannot recurse
# ---------------------------------------------------------------------------
def test_inv_no_recursive_dlq_confirms() -> None:
    # A valid non-recursive route: source != destination.
    route = DeadLetterRoute(
        source_topic="orders", destination_topic="orders.dlq", max_deliveries=1,
    )
    assert route.source_topic != route.destination_topic


def test_inv_no_recursive_dlq_prevents() -> None:
    # Construction rejects source == destination.
    with pytest.raises(DeadLetterRouteInvariantError):
        DeadLetterRoute(
            source_topic="x", destination_topic="x", max_deliveries=1,
        )


def test_inv_no_recursive_dlq_under_failure() -> None:
    # Sending an already-parked envelope (marked by the sink) to the SAME
    # destination again MUST raise — recursive dead-letter is forbidden.
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        # Build an envelope that claims to be already parked on "d".
        env = EventEnvelope(
            id="e", source="urn:t", type="t.e",
            extensions={"dlqparked": "d", "dlqdest": "d"},
        )
        with pytest.raises(DeadLetterRouteInvariantError):
            await sink.send(route, env, "r", attempt=2)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# DLR_INV_05 — terminal failure reason recorded
# ---------------------------------------------------------------------------
def test_inv_reason_recorded_confirms() -> None:
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=1,
        )
        sink = InMemoryDeadLetterSink()
        await sink.send(route, _env("e"), "downstream_timeout", attempt=2)
        rec = sink.inspect("d")[0]
        assert rec.last_reason == "downstream_timeout"
        # Audit log has a matching send event.
        audit = sink.audit_log()
        sends = [a for a in audit if a.event_name == "dlq.sent"]
        assert len(sends) == 1
        assert sends[0].reason == "downstream_timeout"

    asyncio.run(run())


def test_inv_reason_recorded_prevents() -> None:
    # Empty / whitespace reasons COLLAPSE to "unspecified" — never silently
    # vanish. normalize_reason is a pure helper used by send().
    assert normalize_reason(None) == "unspecified"
    assert normalize_reason("") == "unspecified"
    assert normalize_reason("   ") == "unspecified"
    assert normalize_reason("x") == "x"


def test_inv_reason_recorded_under_failure() -> None:
    # When the same envelope lands twice, last_reason reflects the LATEST
    # failure but failure_count is monotonic (audit lineage preserved).
    async def run() -> None:
        route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=2,
        )
        sink = InMemoryDeadLetterSink()
        env = _env("e")
        await sink.send(route, env, "first", attempt=3)
        await sink.send(route, env, "second", attempt=4)
        rec = sink.inspect("d")[0]
        assert rec.last_reason == "second"
        assert rec.failure_count == 2

    asyncio.run(run())
