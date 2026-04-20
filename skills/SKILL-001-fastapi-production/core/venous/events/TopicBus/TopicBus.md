# TopicBus

## What it does (plain language)

TopicBus is the one way every worker in SKILL-001 publishes and consumes
domain events. Producers call `publish(topic, envelope)` and the envelope
lands on a durable append log before any subscriber hears about it.
Consumers register a `(topic, group, handler)` and receive every envelope
at least once; they must `ack()` to confirm, or `nack(reason)` to trigger a
bounded redelivery. When redeliveries are exhausted the envelope is routed
to a configured dead-letter topic — never dropped silently.

## Purpose

Publish and subscribe facade over a broker topic that delivers CloudEvents
at least once to named subscriber groups with optional dead-letter routing.

## When to use and when NOT to use

- USE: every cross-aggregate event emission, every fan-out of a domain fact
  to multiple consumer groups, every workflow that must survive a consumer
  crash without data loss.
- DO NOT USE: request/response call graphs — use a direct call or a job
  queue primitive instead. TopicBus semantics are event-shaped, not RPC.
- DO NOT USE: ordered global streams — TopicBus guarantees partition-local
  order ONLY.

## API surface

The catalog `api_signature` in `TopicBus.contract.json` is the authority.
`InMemoryTopicBus` is the reference implementation used by tests. Production
deployments implement the same Protocol against Kafka, NATS JetStream,
Redis Streams or RabbitMQ; the interface surface and invariants do not
change across adapters.

## Invariants

| ID | Rule |
|---|---|
| TB_INV_01 | Delivery to a subscribed handler MUST be at least once by default; handlers SHALL tolerate duplicates and MUST NOT block indefinitely on ack. |
| TB_INV_02 | Inside one consumer group a given message ALWAYS goes to exactly one handler instance at a time; concurrent overlap is FORBIDDEN. |
| TB_INV_03 | Negative acknowledgement MUST cause redelivery until the bound is exhausted, then the envelope MUST route to the configured dead-letter topic; silent drop is FORBIDDEN. |
| TB_INV_04 | Subscribers CANNOT rely on global ordering across topic partitions; same-key envelopes ALWAYS land at a group handler in publish order. |
| TB_INV_05 | Publish NEVER succeeds without the broker confirming the persisted append; fanout to subscribers MUST be strictly downstream of the committed log record. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Ordering and delivery semantics

- **At-least-once**: a published envelope for which at least one group is
  subscribed is delivered at least once to that group's handler OR routed to
  the DLQ. Producers and consumers MUST treat duplicates as normal.
- **Per-key order**: envelopes sharing a `partitionkey` extension (falling
  back to `subject`, then `id`) are dispatched serially to the same group
  handler. Nack + redelivery NEVER overtakes the next same-key envelope.
- **No global order**: distinct keys dispatch in parallel; readers that need
  a total order must project to a single key.
- **Ack timeout**: the reference implementation refuses `ack_timeout_s <= 0`
  at construction so infinite ack-wait is impossible (TB_INV_01).

## Thread and async safety

- `_commit_append` is guarded by a threading.Lock so the sequence counter
  and the partition log grow atomically (TB_INV_05).
- Per-(topic, group, partition_key) `asyncio.Lock` serialises dispatch
  (TB_INV_02 + TB_INV_04).
- Handler exceptions are absorbed as an implicit nack with reason
  `handler_exception:<type>` so a buggy handler cannot silently swallow
  the envelope (TB_INV_03).

## Operational characteristics (for SRE)

- DLQ routing uses the SAME `publish` path — the DLQ append is durably
  committed, not written to a side list. Operators can subscribe a
  dedicated `audit` group to the DLQ topic and reprocess at will.
- `dispatch_stats(topic, group, envelope)` returns the per-envelope
  delivery / ack / nack / dlq counters for diagnostics.
- Self-observability: `bus.publish.total` (counter), `bus.delivery.attempts`
  (histogram), `bus.dlq.total` (counter), `bus.handler.duration`
  (histogram). See `observability_schema.json`.
- `close()` is a soft shutdown — new publishes and subscriptions are
  rejected; inflight dispatch finishes.

### Capacity and failure modes

| Failure mode | Detection | Mitigation |
|---|---|---|
| Stuck consumer (never acks or nacks) | `bus.delivery.attempts` > 1 with no `bus.acked`; `bus.dlq.routed{reason="ack_timeout"}` rises | `ack_timeout_s` bounds exposure; DLQ absorbs the envelope |
| Permanent handler failure | `bus.dlq.routed{reason=...}` rising | Drain DLQ via audit group; patch handler; reprocess |
| Handler exception storm | `bus.nacked{reason=~"handler_exception.*"}` rising | Circuit-break at the middleware layer; TB_INV_03 ensures no silent drop |
| Producer flood | `bus.publish.total` rising; log size growing faster than drain rate | Shard partition keys; add consumer group instances; raise redeliveries only after root-cause review |
| Subscriber registration after close | `TopicBusInvariantError` raised on `subscribe` / `publish` | `close()` is intentional shutdown; callers MUST rebind a fresh bus |

### SLOs (reference impl)

- `publish` p99: < 1 ms under 10k msgs/s per partition (in-memory ref impl).
- `ack_timeout_s` SHOULD be set to 3x the p99 handler duration to avoid
  false-positive DLQ routing.
- `max_redeliveries` SHOULD be ≥ 1 in production — zero is only safe when
  the DLQ pipeline is the authoritative retry surface.

## Security considerations

- Envelopes routed to the DLQ carry a `dlqreason` extension capped at 20
  chars; reasons MUST NOT include secrets or PII.
- Duplicates are expected — consumers MUST dedup on `envelope.dedup_key()`
  (see EventEnvelope TB_INV_01 sibling) before taking non-idempotent
  side effects.
- Handler timeouts bound exposure of a stuck consumer to `ack_timeout_s`;
  reviewers MUST reject configurations where `ack_timeout_s` exceeds the
  upstream SLO by more than 3x.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary sources:
  - Dapr 1.14 Publish and Subscribe building block overview — delivery
    guarantees and dead-letter topics sections.
  - Confluent Kafka Design: Message Delivery Semantics — at-least-once
    section.

## Alternatives considered and rejected

- Direct broker SDK in each tool — couples business logic to Kafka / NATS
  APIs and breaks the worker-portability story.
- HTTP webhooks only — lose ordering and consumer-group semantics; no
  durable replay path.

## Extension contract

Downstream tools extend TopicBus by:

- implementing the Protocol against a real broker and registering it as a
  pubsub component;
- wrapping handlers with `with_middleware(...)` for tracing / audit / retry
  overlays without changing the handler body;
- subscribing an `audit` group to the DLQ topic to reprocess failures.

The existing ack/nack/redelivery/DLQ order MUST remain intact; middleware
CANNOT reorder dispatch.

## Usage

```python
async def on_order(e: EventEnvelope, ack: Ack, nack: Nack) -> None:
    try:
        await process(e)
        await ack()
    except Exception:
        await nack("transient")

def wire(bus: TopicBus) -> None:
    bus.subscribe("orders", "fulfillment", on_order)
```

## Compose with:

- **Published-language fabric** → `EventEnvelope` + `StreamSubject`
  Bus speaks only envelopes routed by subject; producers and consumers never care which broker implements the topic.

- **Safe fan-out** → `IdempotentConsumer` + `DeadLetterRoute`
  Each subscriber dedupes by envelope id and shunts poison messages to the DLR; one bad consumer does not stall the fleet.

- **Cross-context integration** → `ContextMap` + `AntiCorruptionLayer`
  Context boundaries publish through the bus; consumers translate via their own ACL — no synchronous coupling across contexts.
