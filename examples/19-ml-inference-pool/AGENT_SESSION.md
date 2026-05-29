# agent session — 19-ml-inference-pool

Plan-level transcript for
`adversarial/04_missing_primitive_ml_inference_pool.md`.

## Requirement → kit mapping

1. **Depth-balanced routing.**
   → `HeterogeneousWorkerPool.route(task)` picks the worker with the
     shallowest weighted queue, gated by `model_family` capability.
2. **Latency-aware de-prioritization.**
   → Per-worker p50 latency is the weight; 2× latency ⇒ weight 0.2.
3. **Session stickiness.**
   → `SessionCache` maps `session_id → worker_id`; on failure the
     binding is invalidated and the next request fails over.
4. **CPU-only family never on GPU.**
   → `ModelRegistry` advertises capability list per worker; router filters.

## Tool call sequence

```
1. fastapi_generate_project(name="inference_svc")
2. fastapi_add_inference_router()
3. fastapi_add_worker_health_probe()
4. fastapi_add_session_stickiness(ttl_s=300)
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
