# KeyValueBucket

## What it does (plain language)

KeyValueBucket is a named collection of key-value entries that supports
compare-and-swap (CAS) writes and a watch channel for change notifications.
Every successful write advances a monotonic revision number; readers use that
revision to detect lost updates and observers replay changes in revision
order.

## Purpose

Provide one small contract over optimistic concurrency (create/update/delete
with revision) plus a change stream, so feature flags, session data, and
config blobs do not each reinvent their own CAS logic on top of a raw cache.

## When to use and when NOT to use

- USE: feature flags, session tokens, small config blobs, leader elections
  built atop CAS, dynamic routing maps.
- DO NOT USE: general-purpose state with multi-key transactions — that is the
  `TransactionalBatch` primitive.
- DO NOT USE: append-only event logs — see `PartitionLog`.

## API surface

See `KeyValueBucket.contract.json` for the verbatim catalog Protocol. The
reference `InMemoryKeyValueBucket` stores entries with a bounded history
window and a simple watcher fan-out. A production backend implements the
same Protocol over JetStream KV, etcd, or Consul KV.

## Invariants

| ID | Rule |
|---|---|
| KVB_INV_01 | `create` MUST fail when the key already exists; it NEVER overwrites a present value. |
| KVB_INV_02 | `update` MUST fail when the supplied revision does not match the stored revision (compare-and-swap semantics). |
| KVB_INV_03 | Every successful write ALWAYS increases the entry revision monotonically. |
| KVB_INV_04 | Watch channels SHALL emit changes in revision order for a given key and CANNOT skip a revision without a gap signal. |
| KVB_INV_05 | Deleting a key NEVER frees its historical revisions if history retention is configured greater than one. |

## Invariant → test mapping

See `invariant_bindings.json` for the authoritative binding to
`test_inv_<slug>_{confirms,prevents,under_failure}`.

## Thread and async safety

- The reference implementation uses an internal `threading.Lock` around the
  store dict; all mutating methods serialize CAS under that lock.
- Methods are declared `async` to match the Protocol; the reference impl is
  non-blocking (no I/O) but preserves the shape callers need.

## Operational characteristics (for SRE)

- Self-observability: `kv.bucket.writes.total` (labelled by op), 
  `kv.bucket.cas.rejections`, `kv.bucket.revision` gauge, and 
  `kv.bucket.watch.emit`. Full schema in `observability_schema.json`.
- Failure policy: CAS failure raises `RevisionMismatchError`; callers MUST
  decide whether to retry with a fresh `get`.
- History cap: memory grows with `history × number_of_keys`. Operators SHOULD
  choose `history` to match retention budgets.

## Security considerations

- Keys MUST be non-empty and free of null bytes; this blocks header/log
  injection via key namespacing tricks.
- Values are opaque `bytes`; callers responsible for payload hygiene.
- A tombstone retains the key's history; operators who must hard-purge MUST
  re-provision the bucket or call a backend-specific purge API.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary sources:
  - NATS 2.10 JetStream Key Value Store documentation (create, update, watch,
    revisions).

## Alternatives considered and rejected

- Plain string cache with TTL only — rejected because it lacks CAS and change
  notification.
- Full relational row with triggers — rejected because it is far heavier
  than the access pattern needs.

## Extension contract

Backends implement the `KeyValueBucket` Protocol as an adapter over a
compare-and-swap store (JetStream KV, etcd v3, Consul KV) and register per
bucket name. Watchers extend via a decorator that composes filters on key
prefix or revision range.

## Usage

```python
from KeyValueBucket import InMemoryKeyValueBucket

async def ensure_feature(kv, name: str) -> bytes:
    existing = await kv.get(name)
    if existing is not None:
        return existing.value
    entry = await kv.create(name, b"off")
    return entry.value
```

## Compose with:

- **Lost-update prevention** → `DistributedLock` + `AuditEvent`
  Updates carry a revision; on mismatch the caller re-reads instead of overwriting, and the conflict is audited — two writers cannot silently clobber each other.

- **Read-through cache** → `IdentityMap` + `MetricMeter`
  Identity-map-like semantics per process plus bucket-level TTL keep hot keys in memory; cache hit ratio is a first-class metric, not a guess.

- **Graceful degradation** → `CircuitBreaker` + `LoadShedder`
  When the KV backend is unhealthy the bucket returns stale-on-error under a breaker, while the shedder rejects low-priority writes — availability over freshness.

- **Session payload store** → `SessionCache` + `CircuitBreaker`
  SessionCache's external-store loader reads from a KeyValueBucket whose revision guards prevent lost-update races during rolling deploys; the cache layer above stays read-only.
