# EventSourcedStore

## What it does (plain language)

EventSourcedStore is the persistence primitive for aggregates whose authority
is the *history of what happened*, not a mutable row. Writers append domain
events; readers recover current state by replaying (folding) those events.
When two writers race, the one with the stale version loses loudly — there is
no last-writer-wins. Snapshots are a caching optimisation; the log is always
the source of truth.

## Purpose

Persists aggregate state as an ordered sequence of domain events and
reconstructs current state by folding them on load.

## When to use and when NOT to use

- USE: audit-critical domains (payments, ledgers, legal-hold), workflows that
  need temporal queries ("what was the cart state last Tuesday?"), systems
  that emit a lot of outbound events.
- DO NOT USE: CRUD-shaped lookups where no one cares about history — use a
  plain repository.
- DO NOT USE: aggregates larger than can be replayed in acceptable latency
  without snapshots — design snapshotting first.

## API surface

The catalog `api_signature` in `EventSourcedStore.contract.json` is the
authority. Callers load the aggregate with `load(aggregate_id)`, fold the
events into state, apply a command, and call `append(aggregate_id,
expected_version, events)` with the version observed at load time. A
mismatching version raises `ConcurrencyError`; the caller MUST reload and
retry. Snapshots are recorded with `snapshot(aggregate_id, version, state)`
and consulted with `latest_snapshot(aggregate_id)`.

## Invariants

| ID | Rule |
|---|---|
| ESS_INV_01 | `append` MUST fail with a concurrency error when `expected_version` does not match the aggregate's current tail; last-writer-wins is FORBIDDEN. |
| ESS_INV_02 | Events already written CANNOT be mutated; corrections SHALL be expressed as new, compensating events. |
| ESS_INV_03 | Snapshots MUST be reproducible from the event log; the store NEVER treats a snapshot as the source of truth. |
| ESS_INV_04 | Replays from zero ALWAYS produce the same logical state given the same event sequence; non-determinism is FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemoryEventSourcedStore` serialises appends through an `RLock` so
  concurrent writers cannot collide on a version number.
- `load()` returns a materialised snapshot iterator taken under the lock so
  consumers never observe a torn event sequence.
- Events are deep-copied on ingress and egress, so neither the writer nor a
  consumer can rewrite history by mutating the reference they passed in or
  received back (ESS-INV-02).
- A store instance is safe to share across threads and across requests. It
  MUST NOT be shared across trust boundaries — use the registry plus an
  adapter for cross-process durability.

## Operational characteristics (for SRE)

- Concurrency conflicts are normal; the primary operational signal is the
  ratio `ess.appends{result="concurrency_conflict"}` vs the total, not the
  absolute count. Sustained ratios above ~5% indicate a hot aggregate that
  needs further splitting.
- Replay latency grows with the log; snapshot once `replay_from_snapshot`
  starts to miss its SLO. The invariant is that snapshot reduces latency —
  it never changes the result.
- Self-observability: `ess.appends` (counter, `result` label),
  `ess.batch.size` (histogram), `ess.replay.duration` (histogram,
  `from_snapshot` label), `ess.aggregate.version` (gauge).

## Security considerations

- The log is immutable (ESS-INV-02); even the in-memory reference
  implementation refuses to rewrite stored events. Sensitive fields must be
  redacted BEFORE the event is appended — rollback is not a privacy control.
- `aggregate_id` is treated as an opaque string. Callers MUST prevent
  collision across tenants (hash with a namespace, or prefix with the tenant
  id) — the store deliberately does not know about tenants.
- `ConcurrencyError` cites the expected and actual versions; it is safe to
  log because neither value reveals aggregate contents.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Fowler — *Patterns of Enterprise Application Architecture* (2002),
    supplementary "Event Sourcing" essay (2005).
  - Vernon — *Implementing Domain-Driven Design* (2013), Appendix A,
    Aggregates and Event Sourcing, pp. 577–595.
  - Richardson — *Microservices Patterns* (2018), Chapter 6, Event
    Sourcing, pp. 181–226.

## Alternatives considered and rejected

- **State-based persistence only** — loses audit, replay, and temporal
  queries.
- **Event log in a sidecar table with overwrites** — gives the illusion of
  sourcing without the guarantees (ESS-INV-02 violated).
- **CRDT-based state** — solves convergence but not intent tracking; events
  carry intent that CRDTs throw away.

## Extension contract

New aggregate types extend `EventSourcedStore` by registering a fold
function and an event serializer with `AggregateTypeRegistry.register(
type_name, fold, serializer)`. Silent re-registration is rejected because
two different folds over the same log would break the replay-determinism
invariant (ESS-INV-04). Storage backends plug in by writing an adapter that
mirrors the `InMemoryEventSourcedStore` contract; the concurrency and
replay semantics MUST remain identical.

## Schema of `EventSourcedStore.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
def apply_deposit(store: InMemoryEventSourcedStore, account_id: str, amount: int) -> None:
    events = list(store.load(account_id))
    version = len(events)
    store.append(
        account_id,
        expected_version=version,
        events=[{"type": "deposited", "amount": amount}],
    )
```

A reader rebuilds the aggregate by folding events:

```python
def rebuild(store: EventSourcedStore, fold, aggregate_id: str):
    events = list(store.load(aggregate_id))
    state = None
    for e in events:
        state = fold(state, e)
    return state, len(events)
```

## Compose with:

- **State-from-events** → `DomainEvent` + `Aggregate`
  Aggregates are rehydrated by replaying their event stream; there is no mutable state of record — the log is authoritative.

- **Snapshotted rebuild** → `EventStream` + `MaterializedView`
  Read models and aggregate snapshots are materialized from the stream; a rebuild from genesis is always a valid recovery path.

- **Temporal queries** → `EventStream` + `Specification`
  Because history is the source of truth, 'state as of time T' is a fold truncated at T — audit queries are a library concern, not a schema migration.
