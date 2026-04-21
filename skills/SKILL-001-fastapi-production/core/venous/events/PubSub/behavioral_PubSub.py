"""Behavioral invariant witnesses for ``PubSub`` (PS_INV_01..05).

Each test names the invariant it witnesses. Together these are the
machine-checked proof that the motor preserves the contract.
"""
from __future__ import annotations

import asyncio

import pytest

from core.venous.events.PubSub import InMemoryPubSub


# ---------------------------------------------------------------------------
# PS_INV_01 — fanout correctness
# ---------------------------------------------------------------------------
def test_inv_01_publish_reaches_every_active_subscriber() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()
        tasks = [
            asyncio.create_task(_collect_n(bus.subscribe("items"), 1))
            for _ in range(3)
        ]
        await asyncio.sleep(0)  # let every subscriber register its queue.
        assert bus.subscriber_count("items") == 3

        await bus.publish("items", {"id": 1})
        results = await asyncio.gather(*tasks)

        assert results == [[{"id": 1}], [{"id": 1}], [{"id": 1}]]

    asyncio.run(_go())


def test_inv_01_publish_with_no_subscribers_is_silent_no_op() -> None:
    # PS_INV_01 speaks of "active" subscribers — publish to empty topic
    # is correct behaviour (no crash, no buffered replay).
    async def _go() -> None:
        bus = InMemoryPubSub()
        await bus.publish("items", 42)
        assert bus.topics() == ()
    asyncio.run(_go())


# ---------------------------------------------------------------------------
# PS_INV_02 — per-subscriber ordering
# ---------------------------------------------------------------------------
def test_inv_02_per_subscriber_ordering_matches_publish_order() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()
        N = 100

        collected: list[int] = []

        async def sub() -> None:
            async for x in bus.subscribe("items"):
                collected.append(x)
                if len(collected) == N:
                    return

        task = asyncio.create_task(sub())
        await asyncio.sleep(0)

        for i in range(N):
            await bus.publish("items", i)

        await task
        assert collected == list(range(N))

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# PS_INV_03 — topic isolation
# ---------------------------------------------------------------------------
def test_inv_03_publish_to_A_never_reaches_subscriber_of_B() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()

        b_items: list[object] = []

        async def sub_b() -> None:
            async for x in bus.subscribe("B"):
                b_items.append(x)
                if x == "stop":
                    return

        task = asyncio.create_task(sub_b())
        await asyncio.sleep(0)

        # Publish a lot to A — none of it should show up in B.
        for i in range(50):
            await bus.publish("A", f"noise-{i}")

        await bus.publish("B", "stop")
        await task

        assert b_items == ["stop"]

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# PS_INV_04 — subscriber cleanup
# ---------------------------------------------------------------------------
def test_inv_04_generator_aclose_removes_queue_synchronously() -> None:
    # PS_INV_04 fires when the generator's finally block runs. Python
    # does not auto-aclose an async generator when the `async for` body
    # returns or raises — the caller is responsible for driving cleanup
    # via aclose(). This test witnesses the synchronous cleanup on aclose.
    async def _go() -> None:
        bus = InMemoryPubSub()

        ait = bus.subscribe("items")

        async def drain_one() -> None:
            # Hold-for-one then close explicitly (the idiomatic pattern the
            # generator code in add_graphql_subscriptions uses).
            try:
                async for _ in ait:
                    return
            finally:
                await ait.aclose()

        task = asyncio.create_task(drain_one())
        await asyncio.sleep(0)
        assert bus.subscriber_count("items") == 1

        await bus.publish("items", 1)
        await task
        # After aclose(), PS_INV_04 guarantees registry is empty.
        assert bus.subscriber_count("items") == 0
        assert bus.topics() == ()

    asyncio.run(_go())


def test_inv_04_exception_then_aclose_cleans_up() -> None:
    # Caller raises inside the async-for body, then explicitly closes the
    # iterator. PS_INV_04 still fires — finally block runs on aclose().
    async def _go() -> None:
        bus = InMemoryPubSub()
        ait = bus.subscribe("items")

        async def angry() -> None:
            try:
                async for _ in ait:
                    raise RuntimeError("boom")
            finally:
                await ait.aclose()

        task = asyncio.create_task(angry())
        await asyncio.sleep(0)

        await bus.publish("items", "x")
        with pytest.raises(RuntimeError, match="boom"):
            await task

        assert bus.subscriber_count("items") == 0

    asyncio.run(_go())


def test_inv_04_close_sentinel_also_cleans_up() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()

        async def quiet() -> list[object]:
            out: list[object] = []
            async for x in bus.subscribe("items"):
                out.append(x)
            return out

        task = asyncio.create_task(quiet())
        await asyncio.sleep(0)
        assert bus.subscriber_count("items") == 1

        bus.close()
        got = await task
        assert got == []
        assert bus.topics() == ()  # PS_INV_04 via close path.

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# PS_INV_05 — active-window delivery
# ---------------------------------------------------------------------------
def test_inv_05_publish_before_subscribe_not_replayed() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()
        # Pre-subscribe: publish is a silent no-op (no retention).
        await bus.publish("items", "lost")

        got: list[object] = []

        async def sub() -> None:
            async for x in bus.subscribe("items"):
                got.append(x)
                if x == "stop":
                    return

        task = asyncio.create_task(sub())
        await asyncio.sleep(0)
        await bus.publish("items", "stop")
        await task

        # Only the publish that happened while we were active is observed.
        assert got == ["stop"]

    asyncio.run(_go())


def test_inv_05_late_subscriber_during_fanout_skips_in_flight_payload() -> None:
    # When publish() is iterating its snapshot of subscribers, a new subscriber
    # appended DURING that loop MUST NOT receive the in-flight payload. This
    # test witnesses the snapshot semantics explicitly.
    async def _go() -> None:
        bus = InMemoryPubSub()

        early_got: list[object] = []
        late_got: list[object] = []

        async def early() -> None:
            async for x in bus.subscribe("items"):
                early_got.append(x)
                return  # one-shot

        early_task = asyncio.create_task(early())
        await asyncio.sleep(0)

        # Kick off a publish, which snapshots subscribers BEFORE any queue put
        # resolves. Then immediately register a late subscriber.
        pub_task = asyncio.create_task(bus.publish("items", "first"))

        async def late() -> None:
            async for x in bus.subscribe("items"):
                late_got.append(x)
                return

        late_task = asyncio.create_task(late())
        await pub_task  # first fanout completes — only "early" sees it.

        # Second publish — both "late" was registered before; both alive.
        # But "early" has already drained its one payload and exited, so
        # only "late" sees "second".
        await asyncio.sleep(0)  # ensure late_task is past subscribe() setup
        await bus.publish("items", "second")
        await late_task
        await early_task

        assert early_got == ["first"]
        assert late_got == ["second"]

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# Multi-subscriber ordering (stronger per-topic property)
# ---------------------------------------------------------------------------
def test_multi_subscriber_each_sees_same_order_and_same_payloads() -> None:
    async def _go() -> None:
        bus = InMemoryPubSub()
        N = 30
        K = 4

        collected: list[list[int]] = [[] for _ in range(K)]

        async def sub(idx: int) -> None:
            async for x in bus.subscribe("items"):
                collected[idx].append(x)
                if len(collected[idx]) == N:
                    return

        tasks = [asyncio.create_task(sub(i)) for i in range(K)]
        await asyncio.sleep(0)
        assert bus.subscriber_count("items") == K

        for i in range(N):
            await bus.publish("items", i)

        await asyncio.gather(*tasks)
        for one in collected:
            assert one == list(range(N))  # PS_INV_01 + PS_INV_02 jointly.

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
async def _collect_n(ait, n: int) -> list[object]:
    out: list[object] = []
    async for x in ait:
        out.append(x)
        if len(out) == n:
            return out
    return out
