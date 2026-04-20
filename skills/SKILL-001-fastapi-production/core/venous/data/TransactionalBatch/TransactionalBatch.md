# TransactionalBatch

## What it does (plain language)

A TransactionalBatch is a list-with-a-commit: the application queues
`upsert` and `delete` operations against a single state store, and a single
`commit()` call either applies all of them atomically or applies none of
them. Etag checks turn the commit into optimistic concurrency control — if
the expected version of any key does not match, the whole batch aborts.

## Purpose

Offer cross-key atomicity against ONE state store without application-level
two-phase commit or compensation sagas. Applications express "these writes
must all happen or none do" and the runtime enforces it.

## When to use and when NOT to use

- USE: balance transfers, inventory adjustments, multi-key state updates
  that must stay consistent.
- DO NOT USE: cross-store atomicity (out of scope by TXB-INV-04; prefer a
  saga or the Outbox pattern).
- DO NOT USE: workloads that need read-your-own-writes inside the batch
  (TXB-INV-05 forbids reads).

## API surface

See `TransactionalBatch.contract.json` for the verbatim catalog Protocol.
The implementation `TransactionalBatch.py` provides `InMemoryStateStore`
(thread-safe KV with etags) and `InMemoryTransactionalBatch` (the reference
batch). The batch is a one-shot builder: `upsert` / `delete` return `self`
for chaining; `commit()` is the terminal operation.

## Invariants

| ID | Rule |
|---|---|
| TXB_INV_01 | Commit MUST apply every queued operation atomically or apply none; no partial state. |
| TXB_INV_02 | A conflicting etag on any queued operation MUST abort the entire batch with a conflict error. |
| TXB_INV_03 | After commit the batch MUST NOT be reusable; reuse SHALL raise a state error. |
| TXB_INV_04 | Operations inside one batch ALWAYS target the same store instance. |
| TXB_INV_05 | Read operations are FORBIDDEN inside the batch — absence is the guarantee. |

## Invariant -> test mapping

`invariant_bindings.json` is the authoritative binding; every invariant has
confirms / prevents / under_failure tests.

## Formal model

`TransactionalBatch.tla` is a TLA+ spec (checked with TLC 2.19) that models
batch lifecycle and store atomicity. The model-level safety invariants
`TypeInvariant` and `Inv` cover TXB-INV-01 and TXB-INV-03 — TLC exhaustively
explores the state space for small configurations and reports "No error has
been found" on every run.

## Thread and async safety

- `InMemoryStateStore` protects its internal dict with a `threading.RLock`;
  `apply_transaction` takes the lock once and holds it for the entire
  validate + apply sequence, so every observer sees pre-commit or post-commit
  state — never the middle (TXB-INV-01).
- `InMemoryTransactionalBatch.commit` is `async` for protocol compatibility
  but dispatches synchronously under the store lock.

## Operational characteristics (for SRE)

- `batch.commit.calls` counter labeled by outcome (`ok`, `conflict`, `error`).
- `batch.commit.duration` histogram (ms) — p99 tracks commit latency.
- `batch.op.count` histogram (ops per commit) — tail reveals batch-sizing
  issues.

## Security considerations

- Etag semantics prevent lost updates under concurrent writers (TXB-INV-02)
  — a stale client cannot silently overwrite a newer value.
- TXB-INV-05 (no reads in the batch) prevents the batch from becoming an
  ad-hoc query surface; it also simplifies audit: every batch is a declared
  write intention.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary sources:
  - Dapr 1.14 State Management building-block overview — Transactional API.
  - Confluent Kafka Design: Message Delivery Semantics — Transactional
    Producer paragraph.

## Alternatives considered and rejected

- Two-phase commit coordinator per tool: adds operational cost and rarely
  matches the native store's transaction surface.
- Saga compensation at the application layer: a different tradeoff —
  complements but does not replace local atomicity.

## Extension contract

Backend authors extend the Protocol by implementing a `StateStore` adapter
for their store's native transaction API (Redis MULTI, Postgres BEGIN,
Kafka transactional producer). Composition happens at the runtime: one
adapter per configured store name, bound to a single `TransactionalBatch`
at construction time.

## Usage

```python
async def transfer(batch: TransactionalBatch, src: str, dst: str, amount: int) -> None:
    batch.upsert(src, str(-amount).encode()).upsert(dst, str(amount).encode())
    await batch.commit()
```

## Compose with:

- **All-or-nothing writes** → `KeyValueBucket` + `UnitOfWork`
  Multiple keys commit atomically; optimistic revisions on each key turn conflicts into explicit retries rather than partial application.

- **State + outbox together** → `TransactionalOutbox` + `UnitOfWork`
  The batch includes the outbox row; the downstream event ships if and only if the state change committed — no phantom events.

- **Idempotent retry** → `IdempotentConsumer` + `RetryPolicy`
  Batch ids act as idempotency keys so a retried commit is a no-op on the second apply — safe to retry without bookkeeping.
