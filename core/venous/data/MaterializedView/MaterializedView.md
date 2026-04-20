# MaterializedView

## What it does (plain language)

MaterializedView is the pre-computed read-model primitive. It consumes an
ordered event feed and maintains a query-ready projection of the base data so
hot reads never recompute from the system of record. When the source feed is
replayed in the same order, the view converges to the same contents — and a
full `rebuild()` path is always available so the view can be regenerated
from scratch from the source.

## Purpose

Maintain a pre-computed query result kept up to date by an incremental feed
so read queries never recompute from base tables.

## When to use and when NOT to use

- USE: operational read paths that need sub-millisecond latency and tolerate
  a bounded staleness budget (customer dashboard, search index, CQRS read
  model backed by a domain event stream).
- USE: projections whose upstream truth lives in a source-of-record database
  or an event log (CDC → projection is the canonical flow).
- DO NOT USE: read paths that must be linearizable with the base data — use
  the system of record directly.
- DO NOT USE: as the system of record. The view is always derivable; never
  store the only copy of a fact here.

## API surface

The catalog `api_signature` in `MaterializedView.contract.json` is the
authority. Callers:

```python
class MaterializedView(Protocol):
    @property
    def name(self) -> str: ...
    def apply(self, event: Any) -> None: ...
    def rebuild(self, source: Iterable[Any]) -> None: ...
    def query(self, criteria: object) -> Iterable[Any]: ...
```

The reference impl (`InMemoryMaterializedView`) extends the Protocol with an
`on(event_type)` decorator for handler registration, a `register_handler()`
pairing, `staleness_s()` + `is_fresh()` for staleness introspection, and
`evolve_schema(new_version)` for controlled schema evolution.

## Invariants

| ID | Rule |
|---|---|
| MV_INV_01 | `apply` MUST be deterministic. Given the same event stream in the same order, the view state SHALL converge to the same contents. |
| MV_INV_02 | The view CANNOT be the system of record. `rebuild` MUST be able to regenerate state purely from the source feed. |
| MV_INV_03 | Reads against the view MUST tolerate bounded staleness and NEVER claim linearizability with the base data. Staleness is surfaced via `staleness_s()`. |
| MV_INV_04 | Schema evolution SHALL trigger a rebuild path; silent backfill with stale rows is FORBIDDEN. `query()` refuses until `rebuild()` runs at the new version. |
| MV_INV_05 | New projections extend the view by registering handlers per aggregate type. Unknown event types MUST be rejected rather than silently dropped. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemoryMaterializedView` serialises `apply`, `rebuild`, and `query` via
  an internal re-entrant lock. Concurrent readers never see a half-rebuilt
  view: readers observe either the pre-rebuild snapshot or the fully
  completed post-rebuild state, never a torn intermediate.
- `apply` is idempotent against at-least-once redelivery: events with a
  `seq` less than or equal to `last_applied_seq` are dropped so MV-INV-01
  holds under CDC / broker duplicates.

## Operational characteristics (for SRE)

- `staleness_s()` returns seconds since the last successfully applied event,
  or `+inf` if the view has never been applied / just rebuilt-empty.
- `is_fresh()` is `True` iff staleness is within `max_age_s`. Callers MUST
  check before serving consumer-facing reads.
- Self-observability: `view.applied.events` (counter), `view.staleness`
  (gauge, seconds), `view.rebuild.duration` (histogram, ms), `view.rows`
  (gauge).
- Alert primary symptoms: `view_staleness` > max_age (consumer is lagging
  the source), rebuild duration regression (source size or handler cost
  growing unnoticed).

## Source → view convergence

This primitive ships a TLA+ specification (`MaterializedView.tla`) whose
model-checked safety invariants formalise MV_INV_01 / MV_INV_02 / MV_INV_04.
The key property `RebuildIsComplete` states that after a `Rebuild` with no
pending schema evolution, the view equals the full projection of the source
log — i.e. the view is never the system of record.

## Security considerations

- The view stores whatever the source feed publishes. If upstream events
  carry secrets, they will be materialised into the view. Callers MUST
  redact at the source, not at the projection.
- `query()` exposes no authorisation layer; wrap it in an authz-enforcing
  read-facade before serving external consumers.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Kleppmann — *Designing Data-Intensive Applications* (2017), Chapter 11,
    Stream Processing, materialized views, pp. 461–466.
  - Richardson — *Microservices Patterns* (2018), Chapter 7, CQRS and
    materialized views, pp. 253–278.

## Alternatives considered and rejected

- On-demand recomputation — unbounded latency for hot reads.
- Hand-rolled caches with TTL — stale forever on missed invalidations.
- Nightly OLAP cube refresh — too coarse for operational reads.

## Extension contract

New projections extend the primitive by registering event-handler functions
via `view.on("event.type")` per aggregate type. Handlers receive the rows
dict and the event; they MUST mutate deterministically so MV_INV_01 holds.
Re-registration for the same type is refused to prevent handler swaps mid-run.

Storage backends plug in by subclassing `InMemoryMaterializedView` and
overriding the rows dict with a durable adapter (Postgres, Redis, OpenSearch);
the Protocol surface stays stable.

## Usage

```python
view = InMemoryMaterializedView("orders", schema_version=1, max_age_s=30.0)

@view.on("order.placed")
def on_placed(rows, ev):
    rows[ev["aggregate_id"]] = {
        "aggregate_id": ev["aggregate_id"],
        "total": ev["payload"]["total"],
        "status": "pending",
    }

@view.on("order.shipped")
def on_shipped(rows, ev):
    row = rows.get(ev["aggregate_id"], {"aggregate_id": ev["aggregate_id"]})
    row["status"] = "shipped"
    row["ready_to_serve"] = True
    rows[ev["aggregate_id"]] = row

for event in cdc_stream:
    view.apply(event)

if view.is_fresh():
    return list(view.query({"ready_to_serve": True}))
```

## Compose with:

- **CDC-driven rebuild** → `ChangeDataCapture` + `IdempotentConsumer`
  View subscribes to CDC; rebuilds are idempotent — a replay from snapshot produces a byte-identical view without double-applying effects.

- **CQRS read model** → `EventStream` + `Specification`
  Commands mutate aggregates; a projector subscribes to the event stream and maintains the view; Specifications are the only query surface — no SQL leaks.

- **Stale-bounded reads** → `MetricMeter` + `HealthProbe`
  View freshness is a first-class metric; readiness probe goes unhealthy if lag exceeds SLO — stale reads are a visible failure mode.
