# DataLoader

## What it does (plain language)

DataLoader is the per-request coalescer. Inside one request, dozens of
resolvers may independently ask "give me user 42", "give me user 7",
"give me user 42 again". DataLoader buffers those calls, dedupes, fires
one bulk fetch at the end of the current event-loop tick, and hands each
caller its answer. Identical keys in the same tick receive the SAME value
instance — caching is identity-preserving within the request.

## Purpose

Batch and dedupe per-request loads from N-per-resolver patterns into one
bulk fetch per key-type per tick.

## When to use and when NOT to use

- USE: GraphQL resolvers, nested DTO serializers, anywhere N+1 query
  patterns appear per-request.
- USE: when the underlying store has a cheap bulk API (`WHERE id IN (...)`).
- DO NOT USE: as a long-lived application-wide cache — DataLoader is
  request-scoped by design; use a proper cache primitive for global reuse.
- DO NOT USE: when keys are not hashable or when batch semantics violate
  isolation (e.g. each load must carry its own transaction).

## API surface

`DataLoader.contract.json` is the authority. Callers await `load(k)` freely
from multiple coroutines; within one tick, the first invocation queues the
key, subsequent duplicates attach to the same awaited future. A
`batch_fn(keys) -> list[values]` is passed at construction; it receives
keys in insertion order and MUST return values positionally aligned.

## Invariants

| ID | Rule |
|---|---|
| DATALOADER_INV_01 | Within one tick, identical keys resolve to the SAME result instance (identity-preserving cache). |
| DATALOADER_INV_02 | Batch fn receives keys in caller-insertion order; returned values correspond positionally. |
| DATALOADER_INV_03 | If batch fn raises, ALL waiting loaders for that tick receive that exception. |
| DATALOADER_INV_04 | `clear(k)` removes the cache entry and does NOT cancel an in-flight batch containing `k`. |
| DATALOADER_INV_05 | Max-batch-size cap honored; overflow splits into next batch. |

## Invariant -> test mapping

Each invariant has at least one test in `test_DataLoader.py` with the name
`test_inv_<slug>_{confirms,prevents}`.

## Thread and async safety

- Single-loop, single-request primitive. Not safe to share across
  concurrent requests — by design; request-scoped.
- Enqueue + dispatch happen on the same event loop; there is no thread
  locking — if you need cross-thread batching, wrap each thread with its
  own DataLoader instance.

## Operational characteristics (for SRE)

- `dataloader.batch_size` (histogram) — actual batch sizes observed;
  steadily-1 batches mean no coalescing is happening.
- `dataloader.queue_depth` (gauge) — the count of buffered keys awaiting
  dispatch; large values suggest upstream back-pressure.
- `dataloader.cache_hit_rate` (counter) — ratio of duplicate key requests
  within a tick.

## Security considerations

- The cache holds only keys and returned values for the lifetime of one
  request — no cross-request leak.
- `batch_fn` is caller-provided; callers MUST ensure authorization is
  enforced INSIDE the batch fetch, not after. Otherwise a single request
  could enumerate keys it has no right to see.

## Provenance

- Primary source: https://github.com/syrusakbary/aiodataloader (MIT,
  ~300 LoC). The pattern itself originates from Facebook's `dataloader`
  package (https://github.com/graphql/dataloader, Lee Byron, 2015).
- Reference implementation here is a stdlib-only rewrite (~120 LoC) that
  drops the npm-style API conventions but preserves the Protocol shape.

## Alternatives considered and rejected

- Manual bulk-fetch at the top of each resolver — works for a handful of
  endpoints, unmaintainable beyond 5+ resolvers sharing a key.
- Request-level memoization decorator — dedupes but does not batch; leaves
  N+1 fan-out untouched.
- A global cache (Redis/LRU) — solves a different problem (cross-request
  reuse); does not batch and will leak per-tenant data unless partitioned
  manually.

## Extension contract

Adopters pass a `batch_fn` and an optional `max_batch_size`. Subclasses
MAY override `_schedule_dispatch` for non-event-loop schedulers, but MUST
preserve invariants 01-05. No primitive currently depends on overriding
the cache map — if caching policy needs to change, use the `prime` /
`clear` hooks.

## Usage

```python
async def batch_users(ids: list[int]) -> list[User]:
    rows = await conn.fetch("SELECT * FROM users WHERE id = ANY($1)", ids)
    by_id = {r["id"]: User(**r) for r in rows}
    return [by_id[i] for i in ids]  # positional alignment is the caller's duty

loader = InMemoryDataLoader(batch_users, max_batch_size=500)
u1, u2 = await asyncio.gather(loader.load(42), loader.load(7))
```

## Compose with:

- **Per-request scope** → `RouterPipeline` + `RequestContext`
  A fresh DataLoader is constructed by the middleware layer at the start
  of each request, attached to `RequestContext`, and discarded at the end.
  Invariant gained: zero cross-request cache leaks.

- **Bounded batch deadline** → `TimeoutBudget` + `RequestContext`
  The dispatcher honors the request's remaining deadline; if time runs
  out, the awaiting loaders receive a deadline exception instead of
  hanging. Invariant gained: one slow bulk fetch cannot exceed the
  caller's deadline.

- **Authorization before fetch** → `RequestContext` + `RouterPipeline`
  The batch fn consults `RequestContext.principal` inside its SQL — e.g.
  `WHERE owner_id = $tenant AND id = ANY($1)` — so keys that the caller
  cannot see simply miss the result list. Invariant gained: DataLoader
  cannot be used to leak resources across tenants.
