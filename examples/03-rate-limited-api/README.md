# Example 03 — Rate-limited public API

**Tier:** baseline · **Benchmark spec:** `baseline/04_rate_limited_api.md`

Per-API-key quota with priority-based load shedding. Demonstrates the
canonical **`RateLimiter` + `Bulkhead`** recipe for DoS-resistant public
endpoints.

## What this example shows

- Token-bucket per-minute + per-day quotas (two tiers: free / pro).
- `X-RateLimit-Remaining` + `Retry-After` headers on every response.
- Priority-aware `Bulkhead`: when concurrent in-flight requests saturate
  2× capacity, low-priority requests are shed first.

## How to run

```bash
cd examples/03-rate-limited-api
python3.12 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                             | Role                                              |
| -------------------------------- | ------------------------------------------------- |
| `fastapi_add_api_key_auth`       | Per-caller API key → plan lookup.                 |
| `fastapi_add_rate_limiting`      | Token-bucket with `RateLimiter` primitive.        |
| `fastapi_add_bulkhead`           | Priority-aware concurrency isolation.             |
| `fastapi_add_usage_metering`     | Idempotent end-of-day counter dump.               |

## Primitives imported

| Primitive       | Role                                                         |
| --------------- | ------------------------------------------------------------ |
| `RateLimiter`   | Token-bucket counters per `(api_key, window)`.               |
| `Bulkhead`      | Capacity pool with priority queues.                          |
| `LoadShedder`   | Drops low-priority on sustained pressure (p99 guard).        |
| `ShardedCounter`| High-throughput end-of-day accurate usage counter.           |
| `TimeoutBudget` | Per-request time envelope — prevents head-of-line blocking.  |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
