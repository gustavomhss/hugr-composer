# MemoryPubSubBackend

`MemoryPubSubBackend` is an in-process, single-worker fan-out pub/sub:
`publish(topic, payload)` iterates every `asyncio.Queue` registered for that
topic and enqueues the payload on each (`MEMORY_PUB_SUB_BACKEND_INV_01`);
`subscribe(topic)` creates a private queue, appends it to the topic's
subscriber list, and yields items FIFO (`MEMORY_PUB_SUB_BACKEND_INV_04`) until
a sentinel closes the stream or the generator is collected. The backend is
deliberately stateless between the topic registry and the per-subscriber
queues — there is no replay buffer, so a subscriber that registers after a
publish never sees the earlier payload (`MEMORY_PUB_SUB_BACKEND_INV_02`).

Cleanup is the subtle invariant: when the async generator exits (cancellation,
break, or `GeneratorExit`), its `finally` block removes the queue from the
topic's subscriber list so subsequent `publish()` calls don't accumulate work
on a dead consumer (`MEMORY_PUB_SUB_BACKEND_INV_03`). This backend is the
default behind a tool-specific PubSubManager selector; production deployments
swap in a Redis or NATS backend with the same two-verb surface. Extracted from
`adapt/extend/api_design/add_graphql_subscriptions.py` (lines 269–311).

## Compose with:

- **In-process event bus** → `EventBus` + `LifecycleHook`
  Single-worker fan-out for intra-process events; shutdown hooks drain queues before SIGKILL — no dropped events on graceful exit.

- **Test-friendly TopicBus** → `TopicBus` + `EventEnvelope`
  Conforms to the TopicBus contract with CloudEvents envelopes; tests run the pubsub layer without a broker.

- **FIFO per subscriber** → `StreamSubject` + `CardinalityGuard`
  Subjects drive routing; per-topic cardinality is bounded — a typo cannot spawn unlimited queues.
