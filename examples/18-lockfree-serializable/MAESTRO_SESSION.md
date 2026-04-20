# Maestro session — 18-lockfree-serializable

Plan-level transcript for
`adversarial/03_conflicting_primitives_lockfree_serializable.md`.

## Requirement → kit mapping

1. **Lock-free reads.**
   → Store immutable record snapshots; reader grabs a pointer, never a lock.
2. **Strictly serializable writes.**
   → `OptimisticConcurrency.cas(expected_rev, new_record)` serializes
     conflicts; loser receives `409` + retry hint.
3. **No torn reads.**
   → Each record is a fully-formed immutable tuple; swaps are pointer swaps.
4. **Fresh reads within 100 ms.**
   → Writer publishes the new pointer before returning; readers observe it.

## Tool call sequence

```
1. fastapi_generate_project(name="lockfree_svc")
2. fastapi_add_cas_record_store()
3. fastapi_add_snapshot_read()
4. fastapi_add_writer_retry_hint(status=409)
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
