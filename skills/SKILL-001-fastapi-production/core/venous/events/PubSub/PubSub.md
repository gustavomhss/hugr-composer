# PubSub

> In-process fanout pub/sub for real-time streams — **not** a broker.

## Purpose

Deliver a payload published to a topic to every subscriber whose async
iterator is active at the moment of publish. Models the ``LISTEN/NOTIFY``
semantic (PostgreSQL), ``PUBSUB`` (Redis) and the fanout layer that backs
GraphQL / WebSocket real-time subscriptions in a FastAPI app.

``PubSub`` is **distinct from** ``TopicBus``:

| Concern                  | ``PubSub``            | ``TopicBus``                |
|--------------------------|-----------------------|-----------------------------|
| Durability               | none                  | append log + dedup key      |
| Ack / nack / redelivery  | none                  | required                    |
| Dead-letter routing      | n/a                   | required                    |
| Replay / offsets         | no                    | via ``log_snapshot``        |
| Late-subscriber delivery | ignored               | replayable from log         |
| Typical use              | real-time WebSocket / | domain events, outbox,      |
|                          | in-process fanout     | saga orchestration          |

Choose ``PubSub`` when losing a payload to a transiently-disconnected client
is acceptable (GraphQL subscriptions, live dashboards). Choose ``TopicBus``
when every event must be persisted and acknowledged.

## Invariants

- **PS_INV_01 — Fanout correctness.** A payload published to topic ``T`` MUST
  reach every subscriber whose ``subscribe(T)`` generator is active at the
  moment ``publish(T, ...)`` is called.
- **PS_INV_02 — Per-subscriber ordering.** For any single subscriber, the
  order in which it observes payloads on one topic ALWAYS matches the
  publisher's call order on that topic.
- **PS_INV_03 — Topic isolation.** A payload published to topic ``A`` MUST
  NEVER reach a subscriber of topic ``B`` when ``A != B``.
- **PS_INV_04 — Subscriber cleanup.** When the subscriber's generator
  ``finally`` block runs (reached via ``aclose()``, the ``close()`` sentinel,
  or uncaught exception during yield handoff) its queue MUST be removed
  from the registry before the finally block returns — no leak, no
  background task, no later GC. Callers drive cleanup the standard way:
  consume until ``close()``, wrap in try/finally with ``aclose()``, or use
  ``contextlib.aclosing``.
- **PS_INV_05 — Active-window delivery.** A subscriber observes ONLY payloads
  whose publish happens during ``[subscribe-entered, subscribe-closed)``.

## Reference implementation

``InMemoryPubSub`` — one ``asyncio.Queue`` per active subscriber.
Backends wiring an external broker (Redis, NATS, …) live under
``core/venous/_adapters/<framework>/``; this primitive is framework-free.

## Public surface

```python
from core.venous.events.PubSub import (
    InMemoryPubSub,      # reference backend
    PubSub,              # Protocol surface
    PubSubClosed,        # raised by publish/subscribe on closed backend
    PubSubInvariantError,  # invariant witness
    PubSubError,         # common base
)

bus = InMemoryPubSub()

async def reader():
    async for payload in bus.subscribe("items"):
        print(payload)

await bus.publish("items", {"id": 1})
```

## Compose with

- ``TopicBus`` — when durability / ack / replay are required; PubSub is for
  live fanout, TopicBus is for durable event flow.
- ``IdempotentConsumer`` — downstream of a PubSub fanout when the same
  payload might arrive through multiple paths (e.g. Redis + in-process
  fallback) and the handler must still run only once per key.
- ``EventEnvelope`` — the canonical payload shape when PubSub carries
  domain events (CloudEvents-compatible). Keeps payload discovery uniform
  across PubSub and TopicBus callers.
- ``RequestContext`` — subscribers often need the originating request's
  correlation id / principal; ``RequestContext`` is the single source of
  truth for those fields when crossing a PubSub boundary.

## Not in scope

- Retention / replay: deliberately absent. Use ``TopicBus`` or
  ``TransactionalOutbox`` if you need those.
- Pattern-based subscribe (``items.*``): neither Redis PUBSUB's ``psubscribe``
  nor an in-memory equivalent is modelled; the primitive intentionally keeps
  the surface minimal.
- Broker-grade delivery guarantees (at-least-once, exactly-once).
