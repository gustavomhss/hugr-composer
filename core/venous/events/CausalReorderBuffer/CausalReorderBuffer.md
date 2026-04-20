# CausalReorderBuffer

## What it does (plain language)

Events arrive from transports out of order all the time. Per aggregate
(an account, a chat room, a document), the consumer needs them in the
exact sequence the producer emitted them — otherwise "balance += 10"
applied before "account created" blows up. CausalReorderBuffer is the
shock absorber: it holds out-of-order arrivals until the missing
predecessor shows up, then drains them in strict order. If a predecessor
never arrives before its deadline, the buffer surfaces a single
`gap` signal and then keeps going — a dropped message cannot stall the
aggregate forever.

## Purpose

Buffer incoming events by `(aggregate_id, sequence)`, deliver them in
causal order, and emit a single gap event when a predecessor times out.

## When to use and when NOT to use

- USE: at the consumer edge of an at-least-once transport (Kafka,
  SQS, NATS JetStream) where partial ordering is provided but hops
  reorder within the aggregate.
- USE: event-sourced aggregate rebuild where skipping a sequence is a
  bug you want visible, not silent.
- DO NOT USE: when strict total order across aggregates is required —
  this primitive is per-aggregate; use an EventStream with a partition
  key + single-consumer group instead.
- DO NOT USE: as a durable store — the buffer is in-memory; on restart
  pending events MUST be re-read from the source.

## API surface

`CausalReorderBuffer.contract.json` is the authority. Producers call
`offer(agg, seq, event, deadline_ms)` as events arrive. Consumers pull
ready batches via `next_ready(agg)`; the iterator is drained within the
same thread/coroutine. A scheduler invokes `timed_out(now_ms)` on a
tick (e.g., once a second) to reap expired gaps.

## Invariants

| ID | Rule |
|---|---|
| CRB_INV_01 | Events per `aggregate_id` drain in strictly monotonic sequence order. |
| CRB_INV_02 | An out-of-order event is held until its predecessor arrives OR its `deadline_ms` elapses. |
| CRB_INV_03 | On deadline expiry, `timed_out()` emits `(aggregate_id, missing_sequence)` exactly once. |
| CRB_INV_04 | After a gap is emitted, events at sequences > missing ARE drained — a dropped predecessor cannot block forever. |
| CRB_INV_05 | A duplicate `offer(agg, seq, ...)` is idempotent; the second call is dropped silently. |

## Invariant -> test mapping

Each invariant has at least one test in `test_CausalReorderBuffer.py`
with the name pattern `test_inv_<slug>_{confirms,prevents}`.

## Thread and async safety

- Single-loop / single-thread primitive. Cross-thread use requires an
  external lock around `offer` + `next_ready` + `timed_out`.
- `next_ready` is a generator: drain it fully before the next `offer`
  or accept the invariant that new events land behind the current head.

## Operational characteristics (for SRE)

- `crb.pending_depth` (gauge, labels: aggregate_id) — how many events
  are waiting for a predecessor; sustained growth is an upstream signal.
- `crb.gap_count` (counter) — number of gap events emitted; spikes
  correlate with upstream outages.
- `crb.drain_latency_ms` (histogram) — time between `offer` and the
  matching `next_ready` yield; catches head-of-line stalls.

## Security considerations

- The buffer retains event payloads in memory until drained or expired.
  Callers MUST redact PII upstream if the retention window can exceed
  their data-handling policy.
- `deadline_ms` is caller-supplied — an attacker able to forge events
  with tiny deadlines could force premature gap emissions; gate the
  ingestion endpoint with `RequestGuard`.

## Provenance

- Primary source: Apache Flink out-of-order watermarker —
  https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/
  The watermark idea (advance past missing event-time) is the same; we
  apply it per aggregate instead of per partition.
- Secondary: Kafka Streams out-of-order handling —
  https://kafka.apache.org/documentation/streams/developer-guide/dsl-api.html

## Alternatives considered and rejected

- Strict blocking on head — a single dropped message stops the aggregate
  forever; unacceptable for availability.
- Drop out-of-order events silently — loses recent state and is invisible
  to SRE; incompatible with event-sourced rebuilds.
- Client-side sort buffer per consumer — duplicates logic across every
  consumer and diverges on deadline semantics.

## Extension contract

Adopters MAY override `_AggregateState` to persist pending events to a
local WAL for crash recovery; all five invariants MUST be preserved.
The sequence type is `int` (monotonic per aggregate); a different type
(e.g. Lamport clock tuples) is a different primitive.

## Usage

```python
buf = InMemoryCausalReorderBuffer()
buf.offer("acct-42", sequence=2, event={"kind": "debit", "amount": 10}, deadline_ms=5000)
buf.offer("acct-42", sequence=1, event={"kind": "credit", "amount": 10}, deadline_ms=5000)
buf.offer("acct-42", sequence=0, event={"kind": "opened"}, deadline_ms=5000)

for ev in buf.next_ready("acct-42"):
    apply(ev)  # opened, credit, debit — causal order guaranteed.

for agg_id, missing in buf.timed_out(now_ms=9999):
    alert(f"gap on {agg_id} at {missing}")
```

## Compose with:

- **Exactly-once delivery of drained events** → `IdempotentConsumer`
  The drained iterator feeds an IdempotentConsumer keyed by
  `(aggregate_id, sequence)`; even if the pipeline restarts and re-reads
  the source, each event's effect is applied at most once. Invariant
  gained: causal order AND exactly-once application.

- **Gap events routed to operators** → `DeadLetterRoute`
  `timed_out()` output is published to a DLR topic with the
  `(aggregate_id, missing_sequence)` as the routing key so an operator
  replays the missing event from a recoverable source (source-of-truth
  store, archive). Invariant gained: no silent data loss.

- **Fan-out downstream** → `EventBus`
  Events drained from `next_ready` are published onto an EventBus so
  each consumer receives causally-ordered events; the bus's subscriber
  contract is unchanged. Invariant gained: the reorder step is a drop-in
  middleware, not a per-consumer library.
