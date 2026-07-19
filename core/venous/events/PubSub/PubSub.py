"""PubSub primitive — fanout notifier for real-time streams.

Reference implementation for ``events.PubSub``. Distinct from ``events.TopicBus``:

- ``TopicBus`` is a broker-grade bus (durable append log + ack/nack + DLQ +
  consumer groups) modelled after Kafka/Pulsar.
- ``PubSub`` is a fanout notifier modelled after ``PostgreSQL LISTEN/NOTIFY``,
  ``Redis PUBSUB`` and in-process GraphQL/WebSocket subscription fanout.
  Events are delivered only while a subscriber is active — there is NO
  durable log, NO replay, NO ack/nack, NO DLQ. Consumers that need those
  semantics use ``TopicBus`` (see ``Compose with`` in ``PubSub.md``).

Invariants cited by this module:

- PS_INV_01: **Fanout correctness.** A payload published to topic ``T`` MUST
  reach every subscriber whose ``subscribe(T)`` generator is active at the
  moment ``publish(T, ...)`` is called. A subscriber that joins AFTER the
  publish is not required to observe it (see PS_INV_05).
- PS_INV_02: **Per-subscriber ordering.** For any single subscriber, the
  order in which it observes payloads published to one topic ALWAYS matches
  the publisher's call order. Ordering across topics / across subscribers is
  NOT guaranteed.
- PS_INV_03: **Topic isolation.** A payload published to topic ``A`` MUST
  NEVER reach a subscriber of topic ``B`` when ``A != B``.
- PS_INV_04: **Subscriber cleanup.** When a subscriber's async generator
  runs its ``finally`` block — reached via the close-sentinel (``close()``),
  ``aclose()``, or an uncaught exception during yield handoff — its internal
  queue MUST be removed from the subscriber registry before the finally
  block returns. No background task, no weak references, no later GC.
  Callers are responsible for driving the finally block by either (a)
  consuming until ``close()`` fires the sentinel, (b) wrapping the
  ``async for`` in a try/finally with ``aclose()``, or (c) using
  ``contextlib.aclosing`` — this is the standard Python async-generator
  cleanup contract.
- PS_INV_05: **Active-window delivery.** A subscriber observes ONLY payloads
  whose ``publish`` call happens during the window ``[subscribe-entered,
  subscribe-closed)``. Payloads published before the subscriber entered
  MUST NOT be replayed; payloads published after it closed MUST NOT be
  queued (that queue was removed in PS_INV_04).

This primitive is framework-free. The Redis-backed variant lives in
``core/venous/_adapters/redis/PubSubAdapter.py``.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Sentinel — signals a subscriber to stop iterating. Private to this module.
# ---------------------------------------------------------------------------
_CLOSE_SENTINEL: Final[object] = object()


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------
class PubSubError(Exception):
    """Base class for PubSub-family errors."""


class PubSubClosed(PubSubError):
    """Raised when ``publish`` / ``subscribe`` is called on a closed backend."""


class PubSubInvariantError(RuntimeError):
    """Raised when a PubSub invariant (PS_INV_01..05) is witnessed violated."""


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------
@runtime_checkable
class PubSub(Protocol):
    """The minimum fanout pub/sub surface.

    Backends implementing this Protocol MUST honour PS_INV_01..05. The in-memory
    reference backend ``InMemoryPubSub`` is the canonical implementation; every
    registered adapter (Redis, NATS, etc.) is expected to preserve the same
    observable semantics when given the same call sequence in a single-broker
    configuration.
    """

    async def publish(self, topic: str, payload: Any) -> None:
        """Fan ``payload`` out to every active subscriber of ``topic``."""

    def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Return an async iterator yielding every payload published to ``topic``
        during the iterator's lifetime."""


# ---------------------------------------------------------------------------
# Reference implementation — InMemoryPubSub
# ---------------------------------------------------------------------------
class InMemoryPubSub:
    """In-process fanout pub/sub — one ``asyncio.Queue`` per active subscriber.

    Semantics (honouring PS_INV_01..05):

    - ``subscribe(topic)`` enters: a new ``asyncio.Queue`` is appended to
      ``self._subscribers[topic]`` and held by the generator frame.
    - ``publish(topic, payload)`` iterates a *snapshot* of the current
      queues and puts ``payload`` into each — new subscribers appended during
      the fanout loop do NOT receive the in-flight payload (PS_INV_05).
    - The async generator's ``finally`` block removes its queue from the
      registry (PS_INV_04). If the registry list becomes empty we drop the
      topic key entirely so ``topics()`` reflects only live topics.
    - ``close()`` flips a closed flag, injects the close sentinel into every
      active queue so subscribers drop out of their ``await q.get()`` loop,
      and rejects every subsequent ``publish`` / ``subscribe`` call.

    Thread-safety: all state is mutated from the caller's event loop.
    Multi-loop setups must use one backend per loop — ``asyncio.Queue`` is
    tied to the loop that created it.
    """

    __slots__ = ("_subscribers", "_closed")

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}
        self._closed: bool = False

    # ---- lifecycle --------------------------------------------------------
    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Soft-close: inject close sentinel into every active subscriber's
        queue and reject further ``publish`` / ``subscribe`` calls.

        Idempotent. Returns immediately — the sentinel drains asynchronously
        as subscribers pick it up.
        """
        if self._closed:
            return
        self._closed = True
        for queues in self._subscribers.values():
            for q in queues:
                q.put_nowait(_CLOSE_SENTINEL)

    # ---- publish ----------------------------------------------------------
    async def publish(self, topic: str, payload: Any) -> None:
        """Fan ``payload`` out to every subscriber of ``topic`` (PS_INV_01/03).

        Raises:
            PubSubClosed: the backend has been closed.
            PubSubInvariantError: ``topic`` is not a non-empty str.
        """
        if self._closed:
            raise PubSubClosed(
                "PS_INV_01: backend is closed; publish rejected to avoid "
                "silently dropping payloads.",
            )
        if not isinstance(topic, str) or topic == "":
            raise PubSubInvariantError(
                "PS_INV_03: topic MUST be a non-empty str to preserve isolation; "
                f"got {topic!r}.",
            )
        # Snapshot the current subscribers for this topic so late arrivals
        # during the fanout loop are NOT queued the in-flight payload
        # (PS_INV_05). An absent topic key means zero subscribers — silent
        # no-op is correct per PS_INV_01 (fanout correctness speaks of
        # *active* subscribers).
        queues = tuple(self._subscribers.get(topic, ()))
        for q in queues:
            await q.put(payload)

    # ---- subscribe --------------------------------------------------------
    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Async-iterate every payload published to ``topic`` while active
        (PS_INV_02/04/05).

        Raises:
            PubSubClosed: the backend has been closed.
            PubSubInvariantError: ``topic`` is not a non-empty str.
        """
        if self._closed:
            raise PubSubClosed(
                "PS_INV_01: backend is closed; subscribe rejected to avoid "
                "building a queue that would never drain.",
            )
        if not isinstance(topic, str) or topic == "":
            raise PubSubInvariantError(
                "PS_INV_03: topic MUST be a non-empty str to preserve isolation; "
                f"got {topic!r}.",
            )
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.setdefault(topic, []).append(q)
        try:
            while True:
                item = await q.get()
                if item is _CLOSE_SENTINEL:
                    # PS_INV_01: graceful exit on close(); queue still removed
                    # in the finally block below (PS_INV_04).
                    break
                yield item
        finally:
            # PS_INV_04: subscriber cleanup MUST happen synchronously — if the
            # registry still held a dangling queue after the generator closed,
            # future publishes would fill an orphan queue (memory leak) and
            # PS_INV_05 would be violated (payload queued for a closed sub).
            subs = self._subscribers.get(topic)
            if subs is not None:
                try:
                    subs.remove(q)
                except ValueError:
                    # Already removed (e.g. concurrent close()); not an error.
                    pass
                if not subs:
                    self._subscribers.pop(topic, None)

    # ---- introspection ----------------------------------------------------
    def topics(self) -> tuple[str, ...]:
        """Tuple of topics with at least one active subscriber."""
        return tuple(sorted(self._subscribers))

    def subscriber_count(self, topic: str) -> int:
        """Number of active subscribers for ``topic`` (0 if none / unknown)."""
        return len(self._subscribers.get(topic, ()))

    def total_subscribers(self) -> int:
        """Sum of active subscribers across every topic (PS_INV_04 witness)."""
        return sum(len(v) for v in self._subscribers.values())


__all__ = [
    "InMemoryPubSub",
    "PubSub",
    "PubSubClosed",
    "PubSubError",
    "PubSubInvariantError",
]
