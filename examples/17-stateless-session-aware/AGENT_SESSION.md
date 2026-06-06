# agent session — 17-stateless-session-aware

Plan-level transcript for
`adversarial/02_contradiction_stateless_but_session_aware.md`.

## Requirement → kit mapping

1. **Stateless nodes + per-caller state.**
   → `SessionCache` = read-through to an external `KeyValueBucket`.
2. **Node kill → no lost quota/cursor.**
   → Session state lives in the external store; node is disposable.
3. **Flag flip propagates within 1s.**
   → `FeatureFlagCache` TTL=1s with invalidation broadcast.
4. **Cold cache ≠ reset rate limit.**
   → RateLimiter reads counters from the external store on miss.

## Tool call sequence

```
1. fastapi_generate_project(name="stateless_api")
2. fastapi_add_shared_session(backend="redis")
3. fastapi_add_feature_flags(ttl_s=1)
4. fastapi_add_per_caller_rate_limit(backend="redis")
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
