# agent session — 20-innocent-counter

Plan-level transcript for
`adversarial/05_hidden_scaling_innocent_counter.md`.

## Requirement → kit mapping

1. **Concurrent increments: no lost / duplicate counts.**
   → `ShardedCounter.incr(user, n)` dispatches to `shard = hash(user) % N`;
     each shard is guarded by its own lock.
2. **Read p99 < 50 ms.**
   → `ShardedCounter.value(user)` sums N small integers; O(N) with N=64.
3. **Cold user → 0 fast.**
   → Missing shard entry is treated as 0; no DB round-trip.
4. **Dashboard: per-shard throughput + hot-key id.**
   → Per-shard op counter exposed via a simple snapshot method.

## Tool call sequence

```
1. fastapi_generate_project(name="counter_svc")
2. fastapi_add_event_counter(shards=64)
3. fastapi_add_counter_dashboard()
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
