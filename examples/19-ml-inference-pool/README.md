# Example 19 — Heterogeneous ML inference pool

**Tier:** adversarial · **Benchmark spec:**
`adversarial/04_missing_primitive_ml_inference_pool.md`

Depth-balanced routing across mixed CPU/GPU workers with capability gating,
latency-aware de-prioritization, and session stickiness. Demonstrates the
**`HeterogeneousWorkerPool` + `ModelRegistry`** recipe (Phase-3 primitives
built to close this spec's missing-primitive gap).

## What this example shows

- 500-request burst: no worker's queue exceeds 1.5× median.
- A worker that doubles p50 latency loses ≥ 80% of incoming traffic within 30s.
- Session stickiness: same session → same worker while healthy; fails over on failure.
- A `model_family` supported only on CPU never lands on a GPU worker.

## How to run

```bash
cd examples/19-ml-inference-pool
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_inference_router`       | `model_family`-aware worker router.             |
| `fastapi_add_worker_health_probe`    | Per-worker queue + p50 latency gauge.           |
| `fastapi_add_session_stickiness`     | Cache reuse per user-session.                   |

## Primitives imported

| Primitive                   | Role                                              |
| --------------------------- | ------------------------------------------------- |
| `HeterogeneousWorkerPool`   | Queue-depth + latency-aware routing.              |
| `ModelRegistry`             | `(name, version)` → lazy-loaded worker adapter.   |
| `SessionCache`              | Sticky `(session_id → worker_id)` with TTL.       |
| `CircuitBreaker`            | Fails a degraded worker out within seconds.       |
| `HealthProbe`               | Per-worker liveness + queue-depth readout.        |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
