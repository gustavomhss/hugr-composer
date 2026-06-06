# agent session — 03-rate-limited-api

Plan-level transcript for `baseline/04_rate_limited_api.md` (v0.1.0 run, score 100).

## Requirement → kit mapping

1. **Per-plan quotas (free / pro).**
   → `RateLimiter` keyed by `(api_key, window_s)`. Plans resolve via API-key lookup.
2. **429 + `X-RateLimit-Remaining` + `Retry-After`.**
   → Generator emits the headers; `RateLimiter.state()` exposes remaining/reset.
3. **Priority shedding under spike.**
   → `Bulkhead` with two priority lanes; `LoadShedder` drops low-priority first when
     in-flight > 1× capacity.
4. **Accurate end-of-day metering.**
   → `ShardedCounter` (M=32 shards) for per-key increments; sum-on-read is idempotent.

## Tool call sequence

```
1. fastapi_generate_project(name="rl_api")
2. fastapi_add_api_key_auth(plans=["free","pro"])
3. fastapi_add_rate_limiting(per_minute={"free": 60, "pro": 600},
                              per_day={"free": 5000, "pro": 100000})
4. fastapi_add_bulkhead(capacity=100, lanes=["low","high"])
5. fastapi_add_usage_metering(counter="sharded", shards=32)
```

## Benchmark outcome

- Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
