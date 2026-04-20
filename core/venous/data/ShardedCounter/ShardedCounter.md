# ShardedCounter

## What it does (plain language)

A monotonic per-key counter distributed across N fixed shards. Concurrent
increments on the same hot key land on DIFFERENT shards, so no single
row/partition serializes all the writes. Reads sum across shards.

## Purpose

Absorb hot-key write pressure on counters (likes, views, rate-limit
buckets, daily totals) without hitting a single serialized row.

## When to use and when NOT to use

- USE: per-tenant metrics, per-URL view counts, per-post like counts —
  any counter whose reads are eventual and writes concurrent-heavy.
- USE: anywhere the sum matters more than the shard topology.
- DO NOT USE: when exact, strictly-linearizable reads matter (use an
  OptimisticConcurrency row with a single writer).
- DO NOT USE: for sequence generation — ShardedCounter cannot produce a
  gap-free monotonic integer (the sum can be the same across multiple
  increment orderings).

## API surface

`ShardedCounter.contract.json` is the authority. Callers `increment(key)`
from any number of threads/tasks; occasionally read `value(key)` for a
consistent-at-read sum. `reset(key, token)` requires a `PolicyToken` from
a policy primitive — accidental resets cannot occur.

## Invariants

| ID | Rule |
|---|---|
| SC_INV_01 | Counter MUST NEVER decrement (delta MUST be > 0). |
| SC_INV_02 | Read-after-write within the same session reflects at least the preceding increment (session causality, not global consistency). |
| SC_INV_03 | `value(key)` is the SUM of all shard values — never a single shard. |
| SC_INV_04 | Shard count is fixed at construction; changing it requires a migration primitive. |
| SC_INV_05 | Concurrent increments on the same key hit DIFFERENT shards (hashed modulo shard_count on thread/async-task id). |

## Invariant -> test mapping

Each invariant has `test_inv_<slug>_{confirms,prevents}` coverage in
`test_ShardedCounter.py`.

## Thread and async safety

- Reference impl uses a single `RLock` around the shard table — adequate
  for in-memory; real adapters (Redis INCRBY per shard; Postgres
  UPDATE...WHERE shard=N) drop the lock entirely.
- Routing is per-thread in the reference; an async adapter hashes by
  `asyncio.current_task()` instead.

## Operational characteristics (for SRE)

- `shardcounter.increments` (counter, labels: key, shard) — per-shard
  write rate. Skew here indicates the routing hash is poor.
- `shardcounter.value` (gauge, labels: key) — current sum snapshot.
- `shardcounter.reset` (counter, labels: reason) — always alert on
  nonzero; reset is an administrative action.

## Security considerations

- Reset requires a `PolicyToken`; callers cannot wipe counters by
  accident or by crafting an HTTP request.
- Counters do not accept negative deltas — replay attacks cannot shrink
  a "view count" to zero by sending a giant negative increment.
- Per-shard state is internal; no public enumeration exposes the shard
  layout to callers.

## Provenance

- Primary source: Google Cloud Datastore sharded counter best practice —
  https://cloud.google.com/datastore/docs/best-practices#sharding_counters.
- Reference implementation is stdlib-only; Redis adapter (INCRBY per
  shard) and Postgres adapter (row-per-shard) fit the same Protocol.

## Alternatives considered and rejected

- Single-row counter — serializes every writer on the hot key; dies
  under modest concurrency.
- Approximate counters (HyperLogLog) — solves cardinality, not sum; not
  a drop-in for "this key's count".
- Event-sourced counter (append + fold) — correct but expensive to read
  for latency-sensitive dashboards.

## Extension contract

Adopters pick `shard_count` at construction. The hash used for routing
is sealed; changing it would silently violate SC_INV_05 for historical
data. Adapters MAY substitute `asyncio.current_task()` as the routing
key — the Protocol itself is unchanged.

## Usage

```python
counter = InMemoryShardedCounter(shard_count=16)
counter.increment("post:42", 1)
counter.increment("post:42", 3)
print(counter.value("post:42"))  # 4
```

## Compose with:

- **Hot-key observability** → `MetricMeter` + `CorrelationContext`
  Every `increment` emits a metric tagged with the shard and the
  correlation id from the request context — skew becomes visible on a
  heatmap within minutes. Invariant gained: routing regressions surface
  in dashboards, not in oncall pages.

- **Safe administrative reset** → `DistributedLock` + `CorrelationContext`
  `reset` acquires a distributed lock AND requires a `PolicyToken`,
  preventing two admins from racing to reset the same key. Invariant
  gained: reset is single-writer globally.

- **Bursty write smoothing** → `MetricMeter` + `DistributedLock`
  A global lock wraps the once-per-minute "flush shards to Postgres"
  job; increments continue to fan out to shards without contention.
  Invariant gained: cold-path reads are accurate to within one flush
  interval without hot-path coupling.
