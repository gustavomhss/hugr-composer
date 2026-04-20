# Example 15 — BI export service

**Tier:** mid · **Benchmark spec:** `mid/10_bi_export_service.md`

Daily snapshot exports that never block OLTP, are idempotent per day, and
surface progress + last-success on health. Demonstrates the **`WorkflowRun`
+ `MaterializedView` + `HealthProbe`** recipe.

## What this example shows

- Running today's export twice in the same hour produces byte-identical output.
- Readers operate on a snapshot — OLTP writes see zero export-lock contention.
- Third-retry failure: health reports `last_success=<yesterday>`, one page.
- Ad-hoc export for an older date does not block the scheduled one.

## How to run

```bash
cd examples/15-bi-export-service
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_daily_snapshot`         | Snapshot-view export with versioned output.     |
| `fastapi_add_export_retry`           | 3× retry + paging on exhaustion.                |
| `fastapi_add_health_probe`           | `/health` with `last_success` field.            |

## Primitives imported

| Primitive                | Role                                                |
| ------------------------ | --------------------------------------------------- |
| `MaterializedView`       | Pre-computed read surface decoupled from OLTP.      |
| `WorkflowRun`            | Export job as a durable step sequence.              |
| `RetryPolicy`            | Exponential backoff, max 3 attempts.                |
| `HealthProbe`            | Liveness/readiness with `last_success`.             |
| `IdempotentConsumer`     | Same-day re-export is a no-op-in-effect.            |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
