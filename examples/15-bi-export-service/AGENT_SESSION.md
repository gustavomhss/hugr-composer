# agent session — 15-bi-export-service

Plan-level transcript for `mid/10_bi_export_service.md`.

## Requirement → kit mapping

1. **Idempotent per day.**
   → Snapshot key is `(table, yyyy-mm-dd)`; re-running rewrites the same bytes.
2. **Zero OLTP lock contention.**
   → `MaterializedView` computes over a snapshot view, not live rows.
3. **3-retry cap + single page.**
   → `RetryPolicy(max_attempts=3)`; page emitted once per run, not per attempt.
4. **Health surfaces last success.**
   → `HealthProbe` stores `last_success_ts` per table.
5. **Ad-hoc old date does not block scheduled.**
   → Each export is an independent `WorkflowRun`.

## Tool call sequence

```
1. fastapi_generate_project(name="bi_export")
2. fastapi_add_daily_snapshot(tables=["orders","users"])
3. fastapi_add_export_retry(max_attempts=3, backoff_s=[1,2,4])
4. fastapi_add_health_probe()
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
