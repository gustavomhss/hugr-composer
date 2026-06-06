# agent session — 14-workflow-orchestrator

Plan-level transcript for `mid/09_workflow_orchestrator.md`.

## Requirement → kit mapping

1. **Resume from last completed step after crash.**
   → `WorkflowRun` persists `completed_steps`; replay starts at N+1.
2. **Lost-response retry without double side effect.**
   → `ActivityCall` has an `idempotency_key`; `IdempotentConsumer` dedups.
3. **Timeout → reverse compensation.**
   → `SagaOrchestrator.compensate()` walks the completed log backwards.
4. **One instance per workflow id.**
   → `DistributedLock` keyed by `workflow_id`.

## Tool call sequence

```
1. fastapi_generate_project(name="wf_svc")
2. fastapi_add_workflow_runtime()
3. fastapi_add_activity_retry(max_attempts=3)
4. fastapi_add_saga_compensation()
5. fastapi_add_workflow_singleton()
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
