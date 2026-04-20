# ChangeDataCapture

## What it does (plain language)

ChangeDataCapture (CDC) is the primitive that turns a source database's
committed row-level mutations into an ordered stream of change events for
downstream systems. It replaces the doomed "write to DB then write to broker"
dual-write pattern with a single, atomic boundary: every insert, update, and
delete that successfully commits in the source shows up exactly once on the
stream, in commit order, tagged with a monotonic position so consumers can
resume from a persisted checkpoint without replaying already-acknowledged
events.

## Purpose

Publish an ordered stream of row-level changes from a source database so
downstream systems can consume mutations without dual writes.

## When to use and when NOT to use

- USE: any cross-service flow that would otherwise dual-write to DB and a
  broker (order placement fan-out, search-index population, cache warm-up,
  CQRS read-model updates).
- USE: backfilling a new downstream system from a source-of-record DB — a
  `rebuild`-capable CDC subscriber is strictly better than a migration job.
- DO NOT USE: when you only need an in-process event bus — a `DomainEvent` +
  `EventStream` pair inside a single service is simpler.
- DO NOT USE: for operational reads that must be linearizable with the
  source DB — consumers always trail the source by at least one commit.

## API surface

The catalog `api_signature` in `ChangeDataCapture.contract.json` is the
authority.

```python
class ChangeDataCapture(Protocol):
    def subscribe(self, table: str, from_position: object) -> Iterator[Any]: ...
    def checkpoint(self, position: object) -> None: ...
    def schema(self, table: str) -> dict: ...
```

The reference impl (`InMemoryChangeDataCapture`) extends the Protocol with
transactional staging (`begin_tx`, `stage_change`, `commit_tx`, `rollback_tx`),
schema management (`register_table`, `evolve_schema`, `schema_version`),
per-group checkpoints (`checkpoint_group`, `checkpoint_of`), and introspection
helpers (`log_snapshot`, `next_position`, `committed_event_count`).

## Invariants

| ID | Rule |
|---|---|
| CDC_INV_01 | Every committed row change MUST appear in the stream exactly once in commit order; reordering across transactions is FORBIDDEN. |
| CDC_INV_02 | Consumers MUST be able to resume from a persisted checkpoint; stream positions SHALL be monotonically increasing. |
| CDC_INV_03 | CDC events NEVER include uncommitted changes; dirty reads are FORBIDDEN on the downstream side. |
| CDC_INV_04 | Schema changes at the source MUST surface as schema events so consumers CANNOT silently parse new columns with the old parser. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemoryChangeDataCapture` serialises every mutation and snapshot read
  via an internal re-entrant lock. Concurrent writers get unique,
  monotonically increasing positions assigned at commit time.
- `subscribe()` returns a snapshot iterator taken under the lock; events
  appended after the snapshot is captured belong to the consumer's next
  poll, so readers never observe torn or half-committed events.
- Within a single transaction, staged events are flushed to the committed
  log contiguously so per-tx ordering holds under arbitrary concurrent
  interleavings of other transactions.

## LSN / position model (CDC_INV_02)

Positions are plain non-negative ints assigned under the lock at commit
time. They are strictly monotonic, unique, and dense relative to commits
(no gaps between successive committed events). The consumer's checkpoint
API enforces non-decreasing progress — a rewind attempt is rejected rather
than silently permitted, which prevents at-least-once redelivery from
degrading into replay storms of already-acknowledged work.

A companion TLA+ specification (`ChangeDataCapture.tla`) model-checks the
key safety properties: `LogIsMonotonic`, `NextPosAheadOfLog`,
`CheckpointBounded`, and `CommittedAbortedDisjoint`. These formally bind
the reference implementation's Python invariants to machine-checked proofs.

## Operational characteristics (for SRE)

- `next_position` is the head of the committed log; `checkpoint_of(group)`
  is the consumer group's ack'd position. Consumer lag = head − checkpoint.
- Self-observability: `cdc.events.published` (counter by table/op),
  `cdc.tx.commit.duration` (histogram), `cdc.last.position` (gauge),
  `cdc.consumer.lag` (gauge by group).
- Alert primary symptoms: sustained rise in `cdc.consumer.lag` (a downstream
  consumer is stuck), rejected-commit spikes (duplicate txid or schema
  mismatch upstream), rejected-checkpoint spikes (consumer is attempting
  rewinds — usually a bug in the consumer's own offset management).

## Security considerations

- CDC publishes whatever the source DB committed, including PII. Operators
  MUST classify tables and filter columns at the connector or a
  transformation stage before exposing events to downstream systems.
- Consumers MUST store their own checkpoints durably; an unsynchronised
  `checkpoint()` call loses progress tracking across restarts. The
  reference impl stores checkpoints in memory only — production deployments
  wire `checkpoint_group()` to the consumer's local transactional store
  together with its side-effect.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Kleppmann — *Designing Data-Intensive Applications* (2017), Chapter 11,
    Change Data Capture, pp. 454–461.
  - Richardson — *Microservices Patterns* (2018), Chapter 3, Transactional
    messaging, CDC section, pp. 96–102.

## Alternatives considered and rejected

- Application-level dual writes — non-atomic; either DB or broker writes
  fail independently, silently corrupting downstream state.
- Polling a `last_modified` column — misses deletes, adds read load,
  and cannot recover commit order under concurrent writers.
- Trigger-based outbox inside the DB — works, but constrains schema and
  complicates migrations (the same trigger has to evolve in lockstep with
  every table it covers).

## Extension contract

New sources extend ChangeDataCapture by implementing a connector plugin
that stages per-transaction row events and atomically commits them through
`commit_tx()`. The reference `Connector` helper demonstrates the contract:
it wraps an iterable of `(table, op, key, before, after)` tuples into a
single commit boundary and rolls back on any exception so CDC_INV_03
(no dirty reads) holds even when upstream crashes mid-transaction.

Transformation / filter stages plug in as composed callables — they run
before `commit_tx()` so the invariant "no reordering inside a transaction"
(CDC_INV_01) is trivially preserved; a stage that wanted to reorder would
have to cross the commit boundary, which the Protocol forbids.

Storage backends (replacing `_log` with an on-disk WAL or a Kafka topic)
plug in by subclassing `InMemoryChangeDataCapture`; the Protocol surface
stays stable.

## Usage

```python
cdc = InMemoryChangeDataCapture()
cdc.register_table("orders", ["id", "total", "status"])

# Source side: publish a transaction atomically.
cdc.begin_tx("tx-42")
cdc.stage_change("tx-42", "orders", "insert", 1, None, {"id": 1, "total": 100, "status": "pending"})
cdc.stage_change("tx-42", "orders", "update", 1,
                 {"id": 1, "total": 100}, {"id": 1, "total": 100, "status": "paid"})
cdc.commit_tx("tx-42")

# Consumer side: resume from checkpoint.
resume = cdc.checkpoint_of()
for change in cdc.subscribe("orders", resume):
    if change["op"] == "schema":
        reload_parser(change["schema_version"])
        continue
    downstream.publish("order.changes", change)
    cdc.checkpoint(int(change["pos"]))
```

## Compose with:

- **Log-based outbox alternative** → `TransactionalOutbox` + `EventStream`
  CDC reads the DB commit log as the single source of truth; downstream consumers see the same order as the database — no application-level outbox poller.

- **Derived read model** → `MaterializedView` + `IdempotentConsumer`
  A view subscribes to CDC and rebuilds itself idempotently from a snapshot + ongoing stream; reprocessing never produces drift.

- **Cross-store replication** → `EventStream` + `AntiCorruptionLayer`
  CDC feeds a downstream context through its ACL so the target schema never has to mirror the source schema.
