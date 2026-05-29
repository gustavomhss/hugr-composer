# agent session — 11-mobile-backend

Plan-level transcript for `mid/06_mobile_backend.md`.

## Requirement → kit mapping

1. **Conflicting updates — server wins, both converge.**
   → `OptimisticConcurrency.write(key, expected_rev, value)` rejects the
     loser; client re-syncs from the new revision.
2. **Push fan-out, prune stale tokens.**
   → `OutboundBinding` returns per-token status; 410/404 → registry drops it.
3. **Monotonic sync cursor.**
   → Cursor is server-assigned `rev` — always increasing per record.
4. **Batch atomicity + per-item errors.**
   → `TransactionalBatch` rolls back on any hard failure; per-item errors
     returned alongside the ok/err map.

## Tool call sequence

```
1. fastapi_generate_project(name="mbaas")
2. fastapi_add_sync_cursor()
3. fastapi_add_device_registry(push_provider="fcm")
4. fastapi_add_batch_mutations(isolation="all_or_nothing")
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
