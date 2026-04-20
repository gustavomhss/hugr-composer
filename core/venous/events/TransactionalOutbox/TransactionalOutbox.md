# TransactionalOutbox

## What it does (plain language)

TransactionalOutbox is the primitive that stops dual-write bugs. When a
service saves business state AND wants to publish an event about it, the
outbox stages the event inside the SAME database transaction as the state
change. A background relay later reads those rows and publishes them to the
broker. Either both happen or neither happens — no more "DB saved, event
lost" or "event sent, DB rolled back".

## Purpose

Store outgoing messages in the same local transaction as the state change so
a relay can publish them atomically with the commit.

## When to use and when NOT to use

- USE: any service that updates its DB and must publish a domain event about
  the update (order placed, payment captured, user created).
- USE: any integration where a crash between "DB write" and "broker publish"
  would cause silent data divergence across services.
- DO NOT USE: pure fire-and-forget notifications with no business-state link
  — a direct broker call is simpler.
- DO NOT USE: exactly-once delivery guarantees to the broker — the outbox
  guarantees at-least-once; consumers MUST be idempotent.

## API surface

The catalog `api_signature` in `TransactionalOutbox.contract.json` is the
authority. Callers open a transaction with `begin()` (context-manager),
enqueue messages with `enqueue(destination, payload, key)`, and commit. A
relay drives `pending(limit)` → broker → `mark_published(id)` (or
`mark_failed(id, reason)` on NACK).

```python
from TransactionalOutbox import InMemoryTransactionalOutbox

outbox = InMemoryTransactionalOutbox(state_flush_fn=save_order_to_db)
with outbox.begin() as tx:
    outbox.enqueue("orders.placed", order.to_event(), key=order.id)
    tx.commit()
```

## Invariants

| ID | Rule |
|---|---|
| TXN_INV_01 | `enqueue` MUST write the outbox row inside the same DB transaction as the originating state change; cross-transaction writes are FORBIDDEN. |
| TXN_INV_02 | A message MUST NOT be marked `published` until the broker has acknowledged it. |
| TXN_INV_03 | The relay SHALL deliver at-least-once; consumers MUST be idempotent and duplicate suppression CANNOT be assumed. |
| TXN_INV_04 | Ordering per partition key ALWAYS follows transaction commit order; reordering across commits is FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`.

## Lifecycle states

```
          begin()                        commit()
   none  ────────►  active  ───────────────────────►  committed ──► none
                      │
                      │ rollback() / exception / exit-without-commit
                      ▼
                 rolled_back ────────────────────────────────────► none
```

Per-message status transitions inside the store:

```
   pending ───► published   (mark_published on broker ack — terminal)
     │
     ▼
   failed  ───► published   (retry succeeds — terminal)
     │
     └─► failed (retry still nacks — stays retryable)
```

## Thread and async safety

- One outbox instance allows ONE active transaction at a time
  (TXN-INV-01). Nested `begin()` on the same instance is rejected.
- Concurrent readers (`pending`, `store_snapshot`) and id-disjoint ackers
  (`mark_published`, `mark_failed`) are thread-safe via an internal RLock.
- Multiple writer threads MUST serialize around `begin()` externally (e.g.
  each request gets its own outbox-bound transaction, or a lock wraps the
  begin→commit window).

## Operational characteristics (for SRE)

- `uow.commits` style metrics are named `outbox.commits{result=...}`,
  `outbox.publish.duration`, `outbox.pending.depth{destination=...}`. See
  `observability_schema.json`.
- The PRIMARY symptom of a broker outage is a rising
  `outbox.pending.depth` — a healthy relay drains it within seconds.
- If relay crashes mid-batch, messages that were mid-publish are re-tried
  on the next pass (TXN-INV-03). Consumers MUST be idempotent.
- A sustained rise in `outbox.message.failed` means broker unavailability
  or a malformed payload — inspect `failed_reason` on the row.

## Security considerations

- Payloads are persisted as-is in the outbox table. Callers MUST NOT
  enqueue secrets or PII unless the column is encrypted at rest.
- The relay runs with broker-publish credentials — scope them to the
  topics this service owns; an outbox compromise would allow forged events
  otherwise.
- `mark_published` is idempotent but does NOT authenticate the ack —
  callers MUST only invoke it after a genuine broker confirmation.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Richardson — *Microservices Patterns* (2018), Chapter 3, Transactional
    Outbox pattern, pp. 97–99.
  - Kleppmann — *Designing Data-Intensive Applications* (2017), Chapter 11,
    Idempotence and at-least-once delivery, pp. 478–483.

## Alternatives considered and rejected

- Two-phase commit (XA) across DB and broker — high latency, limited broker
  support, operational complexity.
- Publish-then-save — loses the DB write on crash between publish and save,
  corrupts state.
- Save-then-publish — loses the message on crash after save but before
  publish, breaks downstream state.

## Extension contract

New brokers plug in via `broker_publish_fn: Callable[[OutboxMessage], bool]`.
New storage backends replace `InMemoryTransactionalOutbox` with an
alternative that implements the same Protocol — atomicity with the domain
transaction MUST remain invariant.

## Schema of `TransactionalOutbox.contract.json`

Verbatim copy of the `PrimitiveSpec` from the research catalog. Fields:
`name`, `namespace`, `purpose`, `api_signature`, `invariants[]`,
`extension_contract`, `consumption_example`, `sources[]`, `why_essential`,
`alternatives_considered[]`, `maturity`.

## Usage

```python
def place_order(outbox: InMemoryTransactionalOutbox, order: Order) -> None:
    with outbox.begin() as tx:
        outbox.enqueue("orders.placed", order.to_event(), key=order.id)
        tx.commit()
```

## Compose with:

- **Dual-write elimination** → `UnitOfWork` + `DomainEvent`
  State change + event row commit together; a crash between the two is impossible — the relay republishes what the DB already saw.

- **End-to-end idempotency** → `IdempotentConsumer` + `InboxDeduplicator`
  Outbox rows carry stable ids; downstream consumers dedupe — a relay retry never re-applies an effect.

- **Stream-bridged integration** → `EventStream` + `ChangeDataCapture`
  The relay is the outbox tailer or CDC; either way, the stream sees exactly the events the database committed.
