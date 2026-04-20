# EventStream

## What it does (plain language)

EventStream is the primitive that turns a stream of domain events into an
ordered, append-only log partitioned by a caller-supplied key. Producers call
`append(partition_key, event)` and receive back a monotonically-increasing
sequence number for that partition. Consumers call `read_from(partition_key,
offset)` to replay every event whose seq is at or above their offset — any
number of independent consumers can replay the same partition at their own
pace, because consumption is strictly non-destructive. Retention is controlled
by `truncate_before(offset)`, which evicts an event prefix only when the
configured retention floor allows it, and only forward in seq-space.

## Purpose

An ordered, append-only log of events partitioned by key and replayable from
any offset by any number of consumers.

## When to use and when NOT to use

- USE: event-sourcing read-model projections that must be rebuildable from a
  replayable log.
- USE: fan-out of domain events to multiple downstream subsystems (analytics,
  search index, cache warm-up) that each run at their own cadence.
- USE: audit logs where every committed event must be reconstructible later.
- DO NOT USE: for request/response RPC — point-in-time messaging is cheaper
  and does not need the replay machinery.
- DO NOT USE: as a general-purpose task queue with destructive `pop()`
  semantics — that is exactly what EventStream forbids.

## API surface

The catalog `api_signature` in `EventStream.contract.json` is the authority.

```python
class EventStream(Protocol):
    def append(self, partition_key: str, event: Any) -> int: ...
    def read_from(self, partition_key: str, offset: int) -> Iterator[Any]: ...
    def tail(self, partition_key: str) -> int: ...
    def truncate_before(self, offset: int) -> None: ...
```

The reference impl (`InMemoryEventStream`) extends the Protocol with
introspection helpers (`partition_count`, `partition_size`,
`truncated_before_of`, `log_snapshot`) and exposes a retention knob
(`retention_min_entries`) on the constructor. Extension happens via the
`StageAdapter` helper, which threads pure `(partition_key, event) -> event`
stages before the final append — stages are declared in order and CANNOT
reorder or re-partition events (ES-INV-01).

## Invariants

| ID | Rule |
|---|---|
| ES_INV_01 | Events MUST be strictly ordered within a partition; cross-partition ordering is NEVER guaranteed. |
| ES_INV_02 | Appended events CANNOT be mutated or deleted out of retention windows; immutability SHALL be enforced. |
| ES_INV_03 | Consumers MUST be able to start from any valid offset and replay; destructive consumption is FORBIDDEN. |
| ES_INV_04 | `truncate_before` ALWAYS obeys the configured retention policy; arbitrary backdated truncation is FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemoryEventStream` serialises every mutation and every snapshot read via
  an internal re-entrant lock. Concurrent appenders on the same partition get
  contiguous, strictly increasing seqs (1..N); concurrent appenders on
  different partitions never contend for the per-partition seq counter.
- `read_from()` returns a snapshot iterator captured under the lock; events
  appended after the snapshot is captured belong to the consumer's next poll,
  so readers never observe torn state.
- Events are deep-copied on ingress (`append`) AND on egress (`read_from`,
  `log_snapshot`) so a caller mutating a payload either before or after the
  append/read operation cannot corrupt the stored log (ES-INV-02).

## Sequence / position model (ES_INV_01, ES_INV_04)

Each partition owns its own sequence counter, assigned under the lock at
append time. The counter is strictly monotonic and contiguous from 1 upward.
`tail(partition_key)` returns the next-unused seq — the position at which the
*next* append will land. `truncate_before(offset)` advances a per-partition
cursor that (a) is non-decreasing, (b) never exceeds tail, and (c) never
leaves a partition with fewer than `retention_min_entries` retained events.
Reading into a truncated window raises `EventStreamInvariantError` rather
than silently returning a hole-bearing snapshot, so consumers who lost track
of their checkpoint fail loudly instead of silently dropping data.

A companion TLA+ specification (`EventStream.tla`) model-checks the key safety
properties: `PerPartitionStrictlyMonotonic`, `NextSeqAheadOfLog`,
`TruncationBounded`, and `RetentionRespected`. These formally bind the
Python reference implementation's runtime invariants to machine-checked
proofs over the `Init` / `Next` state machine.

## Operational characteristics (for SRE)

- `tail(key)` is the head of the committed log for partition `key`. A
  consumer's lag is `tail(key) - consumer_offset`.
- Self-observability: `event_stream.events.appended` (counter by partition),
  `event_stream.append.duration` (histogram), `event_stream.tail.position`
  (gauge by partition), `event_stream.consumer.lag` (gauge by consumer and
  partition).
- Alert primary symptoms: sustained rise in `event_stream.consumer.lag` (a
  downstream consumer is stuck), rejected-append spikes (producer sending
  malformed partition keys or events), rejected-truncate spikes (operator
  attempting a backdated truncate — usually a retention bug).

## Security considerations

- EventStream publishes whatever the caller wrote. Operators MUST classify
  partitions and filter payloads at a stage before letting untrusted
  consumers attach.
- Consumers MUST persist their own offsets durably; an unacknowledged
  consumer that restarts from offset 0 will replay the entire retained
  window, which may be expensive but is guaranteed-correct (ES-INV-03).
- The retention floor is declared at construction time; operators who need
  "forever" retention simply pass an enormous value and reject any
  `truncate_before` call that would violate it (ES-INV-04).

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Kleppmann — *Designing Data-Intensive Applications* (2017), Chapter 11,
    Partitioned Logs and stream processing, pp. 444–454.
  - Richardson — *Microservices Patterns* (2018), Chapter 3, Messaging and
    event logs, pp. 85–95.

## Alternatives considered and rejected

- Transient queues (e.g. RabbitMQ default): cannot replay, so downstream
  rebuilds require ad-hoc backfill paths.
- Database tables used as queues: awkward partition semantics, poor
  consumer scaling, and cursor-management conflicts between producers and
  consumers.
- File-based archives: lose online read semantics and partition keys, so
  point-in-time consumers (e.g. a CQRS read-model) can't attach cheaply.

## Extension contract

New transports (Kafka, Kinesis, S3-tailed log) extend EventStream by
implementing the Protocol as a thin adapter over the underlying storage and
registering it with the stream registry. Processing topologies compose via
pluggable stages — the reference `StageAdapter` demonstrates the contract.
Each stage is a pure `(partition_key, event) -> event` callable that MUST
NOT break per-partition order: a stage cannot re-partition, reorder, or drop
events. A stage that needs to fan-out to a different partition key must call
`append()` directly on the downstream stream, not return a different key.

Storage backends plug in by subclassing `InMemoryEventStream`; the Protocol
surface stays stable, and the runtime invariant checkers travel with the
base class.

## Usage

```python
es = InMemoryEventStream(retention_min_entries=100)

# Producer side.
seq = es.append("orders", {"id": 1, "total": 100})
assert seq == 1

# Consumer side: replay from a durable checkpoint.
resume = my_checkpoint_store.get("orders", default=0)
for event in es.read_from("orders", resume):
    process(event)
    # Consumer persists its own offset — seq of the event just processed + 1.
    my_checkpoint_store.put("orders", event["__seq"] + 1)

# Ops: truncate ancient history, respecting the retention floor.
es.truncate_before(old_position)
```

## Compose with:

- **Partitioned ordering** → `TopicBus` + `IdempotentConsumer`
  Per-key order is preserved; consumers dedupe by envelope id so a replay never re-applies effects even though it re-reads events.

- **Replay as recovery** → `MaterializedView` + `EventSourcedStore`
  Views and aggregates can be rebuilt from any offset; disaster recovery is 'reset the consumer group' — not 'restore a backup'.

- **CDC ingress** → `ChangeDataCapture` + `EventEnvelope`
  CDC lands directly on an event stream wrapped in envelopes — downstream consumers do not care whether the source was a DB or a producer.
