# Heterogeneous inference pool with per-model SLA

## Background

An ML gateway routes inference requests across a pool of **simulated**
workers. There are two worker classes:

- `cpu` — cheap but slow (simulated latency 80ms); capacity 3 in-flight.
- `gpu` — fast (simulated latency 15ms); capacity 1 in-flight.

The service MUST route each request to a worker that can satisfy the
per-request latency SLA declared in the body. Request deadlines are
expressed in `deadline_ms` from receipt.

Sessions are sticky: requests carrying `session_id` that have been
seen recently (≤500ms) should prefer the same worker class when that
worker's health is good.

The pool is healthy iff its rolling 5-request latency average stays
≤ 1.5× its advertised latency. An unhealthy worker is skipped.

## Requirements

1. `POST /infer` — body `{"session_id": "<string>", "deadline_ms":
   <int>, "prompt": "<string>"}`.
   - Must respond within `deadline_ms`.
   - If no worker can meet the SLA → HTTP 503
     `{"error": "sla_infeasible"}`.
   - Otherwise 200 `{"worker": "<cpu|gpu>", "result": "<string>",
     "latency_ms": <int>, "session_id": "<same>"}`.
2. The server MUST NOT oversubscribe a worker class beyond its
   capacity. Excess concurrent requests over capacity queue until a
   slot frees OR the request's deadline expires (→ 503).
3. `GET /pool` — returns `{"cpu": {"in_flight": N, "latency_p50_ms":
   ..., "healthy": <bool>}, "gpu": {...}}`.
4. `GET /health` → 200.

## Acceptance criteria

- A request with `deadline_ms=30` must be routed to `gpu` (cpu can't
  meet SLA).
- A request with `deadline_ms=200` is routable to either.
- 100 concurrent `deadline_ms=50` requests: at most 1 of them sees
  `worker: gpu` concurrent in-flight (respect capacity), and none
  return 500.
- If a stream of 10 sequential requests all pick the same session_id
  and `deadline_ms=200`, at least 7 of them land on the same worker
  class (stickiness).
- Under a load burst, the reported p50 latency stays within 5× the
  class's advertised latency.

## Non-requirements

- No real ML model — "result" is a string echo.
- No GPU drivers.
- No persistence.
