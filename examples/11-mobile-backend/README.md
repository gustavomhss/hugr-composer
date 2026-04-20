# Example 11 — Mobile backend as a service

**Tier:** mid · **Benchmark spec:** `mid/06_mobile_backend.md`

Sync cursor, push-token registry, offline batch mutations with server-wins
conflict resolution. Demonstrates the **`OptimisticConcurrency` +
`TransactionalBatch` + `OutboundBinding`** recipe.

## What this example shows

- Two clients pushing conflicting updates: one wins, both told to converge.
- Push notifications reach all active devices; stale tokens are pruned.
- Sync cursor is monotonic per caller — never moves backward.
- A 100-item batch is atomic or reports precise per-item failures.

## How to run

```bash
cd examples/11-mobile-backend
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_sync_cursor`            | Monotonic `since` endpoint.                     |
| `fastapi_add_device_registry`        | Push token add / drop-on-logout.                |
| `fastapi_add_batch_mutations`        | All-or-nothing batch with per-item errors.      |
| `fastapi_add_push_dispatcher`        | Fan-out with stale-token pruning.               |

## Primitives imported

| Primitive              | Role                                                |
| ---------------------- | --------------------------------------------------- |
| `OptimisticConcurrency`| CAS on record revision; loser gets `conflict`.      |
| `TransactionalBatch`   | All-or-nothing mutation batch.                      |
| `OutboundBinding`      | Push-provider adapter (typed response).             |
| `CurrentPrincipal`     | Per-caller identity for sync cursor.                |
| `IdempotentConsumer`   | Safe retry on batch re-send.                        |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
