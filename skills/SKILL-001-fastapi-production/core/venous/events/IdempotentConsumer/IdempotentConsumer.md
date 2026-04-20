# IdempotentConsumer

## What it does (plain language)

IdempotentConsumer is the primitive that lets a worker handle the same
message as many times as a broker redelivers it — and still have the
business effect apply exactly once. It combines an `InboxDeduplicator`
(dedupe gate) with a business handler and a `TransactionalOutbox`
(downstream publisher) into one abstraction. Deliver the same order
five times, charge the customer once.

## Purpose

Apply a message's effect at most once per logical key while tolerating
at-least-once delivery from the transport.

## When to use and when NOT to use

- USE: every worker that consumes from an at-least-once broker (Kafka,
  RabbitMQ, SQS, Pub/Sub) and performs any non-compensatable effect
  (charge, ship, email, external API).
- USE: any consumer that must publish downstream events whose own
  consumers need to dedupe.
- DO NOT USE: pure upsert workers whose effects are naturally idempotent
  at the storage layer (though wiring IdempotentConsumer still costs
  almost nothing and buys uniformity).
- DO NOT USE: read-only queries — this primitive carries write intent.

## Cached-retry semantics

The consumer caches the outcome of the FIRST delivery. On redelivery the
cached result is replayed through `on_duplicate` and the business handler
is NOT invoked again. The at-least-once broker redelivery pattern thus
collapses to at-most-once effect + exactly-once observable state.

## API surface

The catalog `api_signature` in `IdempotentConsumer.contract.json` is the
authority. Callers implement a subclass of `BaseIdempotentConsumer` with
`_do_handle(message, enqueue) -> object`. The framework threads every
call through the wired inbox bracket and routes every output through the
wired outbox.

```python
class OrderConsumer(BaseIdempotentConsumer[OrderMessage, OrderResult]):
    def key_for(self, message):
        return message.order_id

    def _do_handle(self, message, enqueue):
        charge_credit_card(message.order_id, message.amount)
        enqueue("orders.charged", {"order_id": message.order_id})
        return {"status": "charged"}
```

## Invariants

| ID | Rule |
|---|---|
| IDC_INV_01 | Two messages with the same idempotency key MUST produce the same observable system state; divergence is FORBIDDEN. |
| IDC_INV_02 | `handle` CANNOT perform non-compensatable side-effects without first consulting an `InboxDeduplicator` or equivalent. |
| IDC_INV_03 | `on_duplicate` MUST NEVER raise as a primary error path; duplicates are an expected steady-state condition. |
| IDC_INV_04 | The consumer SHALL publish its own outputs through a `TransactionalOutbox` so downstream systems can dedupe similarly. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Atomicity model (TLA+)

`IdempotentConsumer.tla` models the cached-retry semantics as a state
machine over five variables:

- `cache` — keys with a cached outcome
- `inbox` — keys durably recorded in the inbox
- `outbox` — keys that have produced a downstream message
- `effect_log` — keys whose handler has actually run
- `duplicates` — bounded redelivery counter per key

Four safety invariants hold for all reachable states: `ExactlyOnceEffect`
(effect_log equals cache), `InboxGatesCache` (cache equals inbox),
`OutboxNeverLeaks` (outbox subset of cache), and `DuplicatesOnlyAfterCache`
(duplicates can only increment for cached keys).

## Thread and async safety

- The consumer's cache and counters are guarded by an `RLock`.
- The underlying `InboxDeduplicator` allows ONE active transaction per
  instance; callers MUST serialize `handle()` invocations that share an
  inbox (a single worker per partition is the canonical wiring).
- `on_duplicate` is steady-state: concurrent duplicate calls never
  corrupt the counter and never raise.

## Operational characteristics (for SRE)

- `consumer.deliveries` (counter, `result=first|duplicate`) —
  steady-state flows as the headline rate.
- `consumer.effect.duration` (histogram, ms) — watch p99 for broker
  poisoning / downstream latency regressions.
- `consumer.cache.size` (gauge) — proportional to unique keys processed
  since worker start; scale with inbox retention.

### Alerts & runbook seeds

- `rate(consumer_deliveries_total{result="duplicate"}[5m]) > 10 *
  rate(consumer_deliveries_total{result="first"}[5m])` is the canonical
  symptom of a broker stuck in redelivery.
- A sustained drop in first deliveries with rising duplicates typically
  means an upstream producer is stuck re-emitting the same key.

## Security considerations

- The cache stores the raw business result and the list of enqueued
  payloads; callers MUST NOT put secrets in either. Rotate / encrypt at
  the outbox boundary.
- `on_duplicate` is deliberately silent by default — subclasses that
  override it for audit MUST NOT raise (IDC-INV-03).
- `_do_handle` is the ONLY sanctioned effect site; the framework does not
  expose the raw inbox or outbox to subclasses, closing the bypass door
  that breaks IDC-INV-02 / IDC-INV-04.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Richardson — *Microservices Patterns* (2018), Chapter 3, Idempotent
    Consumer, pp. 101–104.
  - Kleppmann — *Designing Data-Intensive Applications* (2017),
    Chapter 11, Fault-tolerance of stream processing, pp. 476–479.

## Alternatives considered and rejected

- Exactly-once transport — not achievable end-to-end; only
  'effectively-once' under narrow conditions.
- Manual ad-hoc dedupe per tool — inconsistent and fragile; the
  "forgotten case" always surfaces in production.
- Pure upsert operations — ignores effectful consumers (email, payment,
  webhook) where the effect has no natural idempotency primitive.

## Extension contract

New consumer types extend IdempotentConsumer by subclassing
`BaseIdempotentConsumer` and overriding `key_for` + `_do_handle`.
Pre/post processing plugs in via middleware that MUST preserve the
(inbox-gate → handler → outbox) bracket. The framework never exposes the
raw inbox or outbox to subclasses — the only sanctioned write path is
`enqueue(topic, payload)` from inside `_do_handle`.

## Schema of `IdempotentConsumer.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from IdempotentConsumer import build_echo_consumer, EchoMessage

consumer, inbox, outbox = build_echo_consumer("orders_consumer")
for _ in range(5):
    consumer.handle(EchoMessage(id="order-42", payload={"amount": 100}))
# effect_runs == 1, duplicate_calls == 4
```

## Compose with:

- **Webhook receiver** → `SignatureVerifier` + `InboxDeduplicator`
  Inbound request is verified for authenticity, then dedup'd by event id — replay attacks and duplicate deliveries are both neutralized.

- **Consume-then-publish** → `InboxDeduplicator` + `TransactionalOutbox`
  Inbox dedup gates handle(); handle() writes state + outbox in one tx; downstream consumers dedupe similarly — the whole pipeline is effectively exactly-once.

- **Bounded retries** → `DeadLetterRoute` + `RetryPolicy`
  Budget-bounded retries land on the DLR with full context; manual replay reuses the original idempotency key — zero double-apply risk.

- **Causal-ordered at-most-once** → `CausalReorderBuffer` + `InboxDeduplicator`
  The reorder buffer yields events in causal order per aggregate; each drained event is keyed by `(aggregate_id, sequence)` for exactly-once application — replaying the source is safe.
