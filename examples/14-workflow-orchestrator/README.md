# Example 14 — Durable workflow orchestrator

**Tier:** mid · **Benchmark spec:** `mid/09_workflow_orchestrator.md`

Replay-safe multi-step workflows with retry, compensation, and single-instance
guarantees. Demonstrates the **`WorkflowRun` + `SagaOrchestrator` +
`IdempotentConsumer`** recipe.

## What this example shows

- Killing the orchestrator mid-workflow resumes from last completed step.
- An activity whose response was lost is retried idempotently (no double effect).
- Timeout on step 3 of 5 fires compensations for steps 1 + 2, reverse order.
- Two concurrent runs of the same workflow id are rejected; one per id.

## How to run

```bash
cd examples/14-workflow-orchestrator
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_workflow_runtime`       | Persistent step log + replay engine.            |
| `fastapi_add_activity_retry`         | Retry policy with exponential backoff.          |
| `fastapi_add_saga_compensation`      | Reverse-order compensation on timeout.          |
| `fastapi_add_workflow_singleton`     | One-instance-per-id enforcement.                |

## Primitives imported

| Primitive                | Role                                               |
| ------------------------ | -------------------------------------------------- |
| `WorkflowRun`            | Persistent run record + step log.                  |
| `ActivityCall`           | Pinned retry/timeout/idempotency contract.         |
| `SagaOrchestrator`       | Forward/compensate coordination.                   |
| `IdempotentConsumer`     | Safe retry of activity calls.                      |
| `DistributedLock`        | Single-instance-per-workflow-id.                   |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
