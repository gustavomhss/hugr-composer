# Heterogeneous ML inference pool

## Requirements

- Serve an inference endpoint that routes requests across a mixed pool of CPU-only and GPU-backed workers.
- Requests carry a `model_family`; the router must prefer GPU workers when available, fall back to CPU.
- Each worker advertises its current queue depth; the router load-balances on depth, not round-robin.
- When a GPU worker silently degrades (latency inflates but it still answers), the router must de-prioritize it.
- Stickiness: for a given user session, keep them on the same worker while it is healthy, for cache reuse.

## Acceptance criteria

- A burst of 500 requests distributes across workers such that no worker's queue exceeds 1.5× the median.
- A worker that doubles its p50 latency loses ≥ 80% of incoming traffic within 30 seconds.
- Session stickiness is respected when a worker is healthy; when it fails, the session fails over to another worker within one request.
- A request for a `model_family` supported only on CPU never lands on a GPU worker.

## Non-requirements

- No model training or fine-tuning in the service.
- No auth — internal service.
- No multi-region routing.
- No UI.
