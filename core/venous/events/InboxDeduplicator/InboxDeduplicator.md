# InboxDeduplicator

## What it does (plain language)

InboxDeduplicator is the primitive that turns "at-least-once" transport into
"exactly-once effect". When a consumer receives a message, the inbox answers
one question deterministically: "have I already processed this
(message_id, consumer) pair?". If yes, the side-effect is skipped. If no,
the side-effect runs AND the dedupe record is written — both in the same
transaction, so a crash in the middle leaves the system in a state where
the next redelivery retries cleanly.

This is the consumer-side companion to `TransactionalOutbox`: the outbox
stops dual-write bugs on the producer; the inbox stops double-apply bugs
on the consumer.

## Purpose

Record processed message identifiers in the consumer's database so
redelivered messages are detected and skipped — exactly once.

## When to use and when NOT to use

- USE: any consumer whose side-effect is NOT naturally idempotent
  (sending email, charging a card, emitting a webhook).
- USE: any flow where at-least-once broker delivery (Kafka, RabbitMQ, SQS)
  can legally redeliver a message minutes, hours, or days later.
- DO NOT USE: pure upsert operations where duplicate writes are harmless
  (e.g. "set user.last_seen = now()"). Broker-only dedupe is fine there.
- DO NOT USE: as a replacement for business-level idempotency keys that
  originate from the CALLER (e.g. Stripe-style idempotency-key headers) —
  the inbox is keyed on the transport's message_id, which callers may not
  control.

## API surface

The catalog `api_signature` in `InboxDeduplicator.contract.json` is the
authority. Callers bracket a message delivery with `begin()` (context
manager), gate on `seen(message_id, consumer)`, apply the side-effect,
then call `record(message_id, consumer)` — all inside one transaction.

```python
from InboxDeduplicator import InMemoryInboxDeduplicator

inbox = InMemoryInboxDeduplicator()

# Option A: explicit transaction
with inbox.begin() as scope:
    if not inbox.seen(msg.id, "orders_consumer"):
        charge_card(msg.amount)
        inbox.record(msg.id, "orders_consumer")
    scope.commit()

# Option B: the bundled `handle` helper enforces the sequence
with inbox.handle(msg.id, "orders_consumer", lambda: charge_card(msg.amount)) as first_delivery:
    if first_delivery:
        log.info("charge applied")
```

## Invariants

| ID | Rule |
|---|---|
| INBOX_INV_01 | `record` MUST be written in the SAME transaction as the consumer's side-effect; writing after the side-effect is FORBIDDEN. |
| INBOX_INV_02 | Given the same `(message_id, consumer)`, `seen` MUST be deterministic; the consumer CANNOT double-apply the effect. |
| INBOX_INV_03 | Retention policy SHALL cover at least the broker's maximum redelivery window; premature purging is NEVER allowed. |
| INBOX_INV_04 | The deduplicator NEVER silently reclassifies unseen messages as duplicates; a missing record ALWAYS means first delivery. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`.

## Lifecycle states

```
           begin()                     commit()
    none  ────────►  active  ──────────────────────►  committed ──► none
                       │
                       │ rollback() / exception / exit-without-commit
                       ▼
                 rolled_back ────────────────────────────────────► none
```

A single delivery flows through the scope as:

```
  begin  →  seen?  ──False──►  effect()  →  record()  →  commit
              │
              └──True──►  skip effect, commit (no-op record)
```

If `effect()` raises, the transaction rolls back and `seen` returns False
again so the next broker redelivery retries cleanly (INBOX-INV-01 +
INBOX-INV-04).

## Retention (INBOX-INV-03)

Records are kept at least `min_retention` long (default 7 days). A
`purge_older_than(iso_timestamp)` call whose cutoff is closer to *now* than
`min_retention` is rejected with `InboxDeduplicatorInvariantError`. This
protects against a misconfigured cron job eating records while the broker
still has them in its redelivery buffer.

Pick `min_retention` per transport:
- Kafka / log-based brokers: the larger of `log.retention` and any
  consumer-group lag budget.
- SQS: 14 days (maximum visibility timeout ceiling).
- RabbitMQ with DLX: the DLX replay window plus the longest business retry.

## Thread and async safety

- One inbox instance allows ONE active transaction at a time
  (INBOX-INV-01). Nested `begin()` on the same instance is rejected.
- `seen`, `store_snapshot`, and `purge_older_than` are thread-safe via an
  internal RLock.
- Multiple writer threads MUST serialize around `begin()` externally
  (each request gets its own inbox-bound transaction, or a lock wraps the
  begin→commit window). The concurrent test suite asserts this behaviour.

## Operational characteristics (for SRE)

- Metric names:
  `inbox.deliveries{result=first|duplicate,consumer=...}`,
  `inbox.effect.duration{consumer=...,result=ok|error}`,
  `inbox.store.size{consumer=...}`,
  `inbox.purge.evicted`. See `observability_schema.json`.
- Healthy system: `inbox.deliveries{result=duplicate}` / first ratio
  reflects broker redelivery rate. A sudden spike suggests broker misbehaviour.
- A sustained rise in `inbox.effect.duration{result=error}` means the
  side-effect is failing — redeliveries will keep retrying; escalate.
- `inbox.store.size` grows unboundedly without a purge cron. Schedule
  `purge_older_than` on a `min_retention + safety_margin` cadence.

## Security considerations

- `message_id` and `consumer` are stored in plaintext — treat as PII if
  the transport's message ids are user-derived.
- An attacker who can forge a `record` call with a crafted `message_id`
  before the genuine delivery arrives can DoS the consumer (the real
  message appears "already seen"). Callers MUST authenticate the source
  of the `message_id` — never accept it from untrusted request paths.
- Clock skew between producer and consumer does not affect correctness:
  retention math uses the CONSUMER's clock, and `seen` is a pure set
  lookup independent of timestamps.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Richardson — *Microservices Patterns* (2018), Chapter 3, Idempotent
    Consumer pattern, pp. 101–104.
  - Kleppmann — *Designing Data-Intensive Applications* (2017),
    Chapter 11, Exactly-once processing via idempotent writes, pp. 476–479.

## Alternatives considered and rejected

- Broker-only dedupe — broker windows are short; late redelivery slips
  through.
- Consumer-side idempotent operations only — works for upserts but not
  for effects like sending email or charging a card.
- Monotonic offset tracking — loses per-message granularity and cannot
  recover from poisonous messages (a bad message blocks the entire
  offset advance).

## Extension contract

New storage backends implement the `InboxDeduplicator` Protocol and
register with the inbox factory, preserving the redelivery window
guarantee. Eviction policies plug in through `min_retention` and a
pluggable clock; advanced backends can add an LRU or bloom-filter layer
in front of the durable store without altering the Protocol.

## Schema of `InboxDeduplicator.contract.json`

Verbatim copy of the `PrimitiveSpec` from the research catalog. Fields:
`name`, `namespace`, `purpose`, `api_signature`, `invariants[]`,
`extension_contract`, `consumption_example`, `sources[]`, `why_essential`,
`alternatives_considered[]`, `maturity`.

## Usage with a UnitOfWork / TransactionalOutbox

The recommended end-to-end consumer loop pairs InboxDeduplicator with a
UnitOfWork so dedupe, state mutation, and outbound events all commit
together:

```python
def handle(msg, inbox, uow, outbox, apply_effect):
    with uow:
        if inbox.seen(msg.id, "orders_consumer"):
            return
        apply_effect(msg)
        inbox.record(msg.id, "orders_consumer")
        outbox.enqueue("orders.settled", msg.to_ack(), key=msg.id)
        uow.commit()
```

## Compose with:

- **Local dedup gate** → `IdempotentConsumer` + `UnitOfWork`
  The inbox row is inserted in the same transaction as the business effect; a duplicate redelivery fails on PK and the handler is skipped.

- **Effectively-once downstream** → `TransactionalOutbox` + `IdempotentConsumer`
  Combined with an outbox, the consumer's own emitted events carry stable ids — the next hop in the pipeline dedupes the same way.

- **Replay-safe recovery** → `EventStream` + `DeadLetterRoute`
  Replaying from the stream or from the DLR never double-applies; the inbox is the single source of truth for 'have I already done this?'.
