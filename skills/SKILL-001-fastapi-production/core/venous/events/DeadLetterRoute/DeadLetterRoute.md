# DeadLetterRoute

## What it does (plain language)

DeadLetterRoute is the single, shared contract for what happens when an
event cannot be delivered. When a `TopicBus` consumer has nacked an
envelope `max_deliveries` times, the runtime hands the envelope to a
`DeadLetterSink.send(route, envelope, reason, attempt)` — the envelope is
parked on `destination_topic` with its identity (id + source), the
terminal failure reason, the number of failures, and the timestamps of
the first and last park. Operators later `inspect`, `requeue`, or
`purge` the DLQ; every transition is audited.

## Purpose

Named destination where undeliverable or repeatedly failed messages are
routed after the redelivery budget is exhausted so they can be inspected
or replayed.

## When to use and when NOT to use

- USE: every TopicBus subscriber that MUST survive permanent handler
  failures without losing the envelope; any pipeline that needs an
  operator-driven replay path.
- DO NOT USE: as a retry queue (redelivery budgets belong to the bus);
  as a log sink (audit-log primitives own that);
  as a side-buffer for throttling (use a flow-control primitive).

## API surface

The catalog `api_signature` in `DeadLetterRoute.contract.json` is the
authority. The reference implementation `InMemoryDeadLetterSink` exposes
`send` (the Protocol) plus the operator surface: `inspect`, `requeue`,
`purge`, `depth`, `audit_log`, `iter_parked`. Production deployments
implement the same `DeadLetterSink` Protocol against the broker's native
DLQ mechanism (Dapr `deadLetterTopic`, Kafka DLT, NATS dedicated
stream).

## Invariants

| ID | Rule |
|---|---|
| DLR_INV_01 | A message delivered more than `max_deliveries` times MUST be routed to `destination_topic` and NEVER returned to the main topic (except via an explicit operator requeue). |
| DLR_INV_02 | The original EventEnvelope id and source ALWAYS survive routing so downstream audit can correlate. |
| DLR_INV_03 | `max_deliveries` MUST be a positive integer; zero or negative values SHALL raise a configuration error. |
| DLR_INV_04 | Routing to the dead letter destination CANNOT itself dead-letter recursively in the same route. |
| DLR_INV_05 | The sink MUST record the terminal failure reason so operators can decide whether to replay. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the full binding.

## State machine

```
UNKNOWN --send--> PARKED --requeue--> REPUBLISHED
                       \
                        --purge----> EVICTED
```

`send` is monotonic on `failure_count` for a given (destination_topic,
source, id) key — `first_failed_at` is immutable, `last_failed_at`
advances. `requeue` hands the ORIGINAL envelope (not a copy) to a
`RequeueTarget.republish(source_topic, envelope)` — DLR_INV_02 in action.
`purge` evicts the record with an audited reason. `inspect` is read-only
but emits an audit marker so operator reads are reconstructible.

The TLA+ spec in `DeadLetterRoute.tla` checks four safety invariants:
`NoReturnToSourceExceptViaRequeue` (DLR_INV_01),
`RequeuedImpliesPreviouslyParked` (DLR_INV_02),
`TerminalImpliesPreviouslyParked` (DLR_INV_04), and `ParkedHasFailureRecord`
(DLR_INV_05). Model checking completes with no error under
`MaxDeliveries = 1`, `Envelopes = {e1, e2}`.

## Composition with TopicBus

TopicBus exhausts its redelivery budget and calls `sink.send(route,
envelope, reason, attempt=max+1)`. Operators later drain the DLQ via
`sink.requeue(...)`, which uses the TopicBus's own `publish` / republish
path — DLQ data returns to the source topic ONLY through this controlled
hand-off, never as an implicit bus side-effect. This is the joint
guarantee of DLR_INV_01 and TB_INV_03.

## Operational characteristics (for SRE)

- `depth(destination_topic)` is the canonical backlog gauge.
- `audit_log()` is append-only; filter by `event_name` for timeline
  reconstruction. Events: `dlq.sent`, `dlq.inspected`, `dlq.requeued`,
  `dlq.purged` (dotted, lowercase — see `observability_schema.json`).
- Self-observability metrics: `dlq.parked.depth` (gauge),
  `dlq.sent.total` (counter), `dlq.requeued.total` (counter),
  `dlq.purged.total` (counter), `dlq.age.seconds` (histogram).
- Failure modes:
  - **Requeue target failing** — `requeue` re-raises; record stays
    parked so the operator can retry.
  - **Mass poison event** — `purge(destination_topic)` drains the DLQ
    with a caller-supplied reason captured per eviction.
  - **Operator slip** — selective `purge(destination_topic,
    envelope_source, envelope_id)` MUST receive BOTH keys; a half-keyed
    call raises `DeadLetterRouteInvariantError`.

### SLOs (reference impl)

- `send` p99: < 100 µs under 10k parks/s in-memory.
- DLQ backlog SLO: depth SHOULD NOT exceed 1% of upstream publish rate
  per 5 min; alert on `dlq_age_seconds > 3600` (1h) for production.

## Security considerations

- Reasons are bounded to 512 chars; operators MUST NOT include secrets
  or PII in the reason string.
- `audit_log()` is in-memory only in the reference implementation —
  production sinks SHOULD persist audit events to a durable sink.
- `purge` without key arguments drains the WHOLE destination; wrap the
  call in an operator-approval workflow for production systems.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary sources:
  - Dapr 1.14 Publish and Subscribe — Dead letter topics feature.
  - Apache Kafka 3.x concepts — retry topics and DLT pattern.

## Alternatives considered and rejected

- Logging failed messages to stdout only — not replayable.
- Parking-lot queues coded per tool — diverge in schema and ownership.

## Extension contract

- Implement `DeadLetterSink.send` against a backend (Dapr `deadLetterTopic`,
  Kafka DLT, NATS stream). The Protocol is byte-compatible with the
  catalog `api_signature` — runtime checkable via `isinstance`.
- Wrap `send` with a decorator to choose destinations by failure type
  (e.g., `TimeoutError` -> `orders.dlq.timeout`, anything else ->
  `orders.dlq`).
- Compose `DlqObservabilitySink` onto the send path to emit metrics or
  spans without modifying the base sink.

## Usage

```python
async def park(sink: DeadLetterSink, envelope: EventEnvelope, err: str) -> None:
    route = DeadLetterRoute(
        source_topic="orders", destination_topic="orders.dlq", max_deliveries=5,
    )
    await sink.send(route, envelope, err, attempt=route.max_deliveries + 1)
```

## Compose with:

- **Budget-exhausted routing** → `RetryPolicy` + `IdempotentConsumer`
  When the retry budget burns down, the message lands on the DLR with its full failure history — no infinite redelivery storm.

- **Poison-pill quarantine** → `TopicBus` + `AuditEvent`
  Malformed messages are quarantined out of the primary topic and audited; operators can replay after fix without crashing the consumer fleet.

- **Reprocess with dedupe** → `IdempotentConsumer` + `InboxDeduplicator`
  Replaying from DLR preserves original idempotency keys; already-applied effects stay applied once — replay is safe by construction.

- **Missing-event surface** → `CausalReorderBuffer` + `IdempotentConsumer`
  Gap events from `timed_out()` route to the DLR with `(aggregate_id, missing_sequence)` so an operator replays the missing predecessor without silent data loss.
