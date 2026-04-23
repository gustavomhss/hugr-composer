"""MemoryPubSubBackend — in-process asyncio-Queue fanout (legacy entry).

Predates the Wave-1.5 ``events.PubSub`` motor. New code SHOULD prefer
``core.venous.events.PubSub.InMemoryPubSub`` which ships the same
fanout semantics behind the canonical ``PubSub`` Protocol plus five
named invariants (PS_INV_01..05) and a full behavioural-test witness.

Kept registered for backward compatibility with 3 recipe refs that
cite it by name; deletion / demote is a Wave-3 concern. Semantics
below intentionally mirror the InMemoryPubSub motor.

Invariants cited here:

- MP_INV_01 — fanout-to-active: a payload published to topic T
  reaches every subscriber whose generator is currently waiting on
  the queue; late subscribers (registered after the publish loop
  snapshots the queue list) do not receive the in-flight payload.
- MP_INV_02 — topic isolation: publishing to A never leaks to a
  subscriber of B (A != B).
- MP_INV_03 — subscriber cleanup: when a subscriber's generator
  finally-block runs (aclose / exception / close sentinel), its
  queue is removed from the registry.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final

# Private sentinel signals a subscriber to stop iterating without
# yielding the sentinel itself. Object identity is the matching key.
_CLOSE_SENTINEL: Final[object] = object()


class MemoryPubSubBackend:
    """In-process pub/sub using asyncio.Queue per subscriber.

    Suitable for single-worker deployments only. Events are NOT
    shared across processes or workers; use the Redis adapter at
    ``core.venous._adapters.redis.PubSubAdapter.RedisPubSubBackend``
    for multi-worker fanout.
    """

    __slots__ = ("_subscribers",)

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}

    async def publish(self, topic: str, payload: Any) -> None:
        """Broadcast *payload* to all current subscribers of *topic*.

        The subscriber list is snapshotted before any put so late
        subscribers registered during the loop do NOT receive the
        in-flight payload (MP_INV_01).
        """
        queues = tuple(self._subscribers.get(topic, ()))
        for q in queues:
            await q.put(payload)

    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Yield events published to *topic* until the generator is closed.

        Cleanup runs in the finally block (MP_INV_03): the queue is
        removed from the registry even if the caller raises.
        """
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.setdefault(topic, []).append(q)
        try:
            while True:
                item = await q.get()
                if item is _CLOSE_SENTINEL:
                    break
                yield item
        finally:
            subs = self._subscribers.get(topic, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subscribers.pop(topic, None)

    def close(self) -> None:
        """Soft-close: inject the close sentinel into every active queue.

        Idempotent — second call is a no-op because sentinels already
        delivered drive subscribers to their finally block which
        removes their queue from ``self._subscribers``.
        """
        for queues in list(self._subscribers.values()):
            for q in list(queues):
                q.put_nowait(_CLOSE_SENTINEL)


__all__ = ["MemoryPubSubBackend"]
