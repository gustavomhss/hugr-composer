"""Unit tests for ``core.venous.events.PubSub`` — structural + API surface.

Behavioural invariant coverage (PS_INV_01..05) lives in
``behavioral_PubSub.py`` so the two harnesses stay separable.
"""
from __future__ import annotations

import asyncio

import pytest

from core.venous.events.PubSub import (
    InMemoryPubSub,
    PubSub,
    PubSubClosed,
    PubSubInvariantError,
)


def test_public_surface_matches_contract() -> None:
    # A consumer MUST be able to import these names from the package.
    # The test fails if anything is renamed or dropped.
    from core.venous.events.PubSub import (  # noqa: F401
        InMemoryPubSub,
        PubSub,
        PubSubClosed,
        PubSubError,
        PubSubInvariantError,
    )


def test_protocol_membership() -> None:
    # InMemoryPubSub MUST satisfy the runtime-checkable Protocol.
    assert isinstance(InMemoryPubSub(), PubSub)


def test_closed_backend_rejects_publish_and_subscribe() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()
        assert bus.closed is False
        bus.close()
        assert bus.closed is True

        with pytest.raises(PubSubClosed):
            await bus.publish("t", {"x": 1})

        with pytest.raises(PubSubClosed):
            # subscribe() returns an async generator — the exception fires
            # on first advance, not on call.
            ait = bus.subscribe("t")
            await ait.__anext__()

    asyncio.run(_go())


def test_close_is_idempotent() -> None:
    bus = InMemoryPubSub()
    bus.close()
    bus.close()  # no raise, no state change.
    assert bus.closed is True


def test_invalid_topic_rejected_symmetrically() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()

        for bad in ("", 123, None):
            with pytest.raises(PubSubInvariantError):
                await bus.publish(bad, {"x": 1})  # type: ignore[arg-type]
            with pytest.raises(PubSubInvariantError):
                ait = bus.subscribe(bad)  # type: ignore[arg-type]
                await ait.__anext__()

    asyncio.run(_go())


def test_introspection_reports_live_state() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()
        assert bus.topics() == ()
        assert bus.total_subscribers() == 0
        assert bus.subscriber_count("items") == 0

        ait = bus.subscribe("items")
        # Drive the generator into the loop body so the queue is registered.
        task = asyncio.create_task(_drain_one(ait))
        await asyncio.sleep(0)  # let subscribe() past the setdefault + await
        assert bus.topics() == ("items",)
        assert bus.subscriber_count("items") == 1
        assert bus.total_subscribers() == 1

        await bus.publish("items", "x")
        got = await task
        assert got == "x"

        # Once the generator finishes (StopAsyncIteration via close sentinel
        # would be symmetric; here we aclose explicitly) the registry is empty.
        await ait.aclose()
        assert bus.topics() == ()
        assert bus.total_subscribers() == 0

    asyncio.run(_go())


async def _drain_one(ait) -> object:
    # Yield exactly once from the async iterator — used to let the test thread
    # know the subscriber has been registered before we publish.
    async for item in ait:
        return item
    return None


def test_slots_prevent_accidental_state_keys() -> None:
    # __slots__ is part of the contract — an adapter / test should not be
    # able to monkey-patch hidden fields onto the backend.
    bus = InMemoryPubSub()
    with pytest.raises(AttributeError):
        bus.not_a_field = 1  # type: ignore[attr-defined]
