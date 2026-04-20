# IdempotencyStore

`IdempotencyStore` is a narrow, thread-safe in-memory key-to-result cache used
to deduplicate retried writes: when a client presents the same idempotency
key twice (e.g. after a network timeout and retry), the handler consults
`seen(key)` and, on hit, returns the cached result from `get(key)` without
re-executing any side effects. `put(key, result)` is the only writer and is
last-writer-wins (`IDEMPOTENCY_STORE_INV_04`); `get` returns the exact object
previously stored or `None` for an unknown key (`IDEMPOTENCY_STORE_INV_01`),
and `seen` distinguishes "not stored" from "stored as None"
(`IDEMPOTENCY_STORE_INV_02`).

All three operations hold the same `threading.Lock` for their full body so
concurrent threads never observe a half-written entry
(`IDEMPOTENCY_STORE_INV_03`). The store is process-local by design — for
multi-worker deployments it must be wrapped with a Redis-backed implementation
of the same three-verb surface; the invariants above constrain any such
replacement. Extracted from
`adapt/extend/api_design/add_batch_endpoint.py` (lines 499–524).

## Compose with:

- **Retried-write dedup** → `CommandBus` + `BatchCore`
  Handlers stash results keyed by the client's idempotency key; a retried request returns the stored result and never re-invokes the side effect.

- **Inbox-style dedup at the edge** → `InboundVerifier` + `IdempotentConsumer`
  Inbound webhook verifier produces a stable event id; the store refuses replays with the same id — webhook at-least-once becomes effectively-once.

- **Bounded memory budget** → `CardinalityGuard` + `MetricMeter`
  Store size is bounded and metered; an abusive client cannot exhaust memory by flooding unique keys.
