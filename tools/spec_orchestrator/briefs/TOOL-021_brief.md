## Tool: `add_cache_layer`

### Overview parameters
- Tool name: `fastapi_add_cache_layer`
- Category: EXTEND > Infrastructure
- Complexity: High
- Dependencies: existing FastAPI project with auth, Redis
- Signature: `add_cache_layer(project_dir: str, default_ttl_seconds: int = 300, max_cache_size_mb: int = 256, strategy: Literal["read_through", "cache_aside"] = "cache_aside", invalidation: Literal["ttl", "event", "both"] = "both") -> dict`
- Parameters:
  - `project_dir`: project root path
  - `default_ttl_seconds`: default Redis cache TTL (5 min)
  - `max_cache_size_mb`: Redis maxmemory for cache namespace
  - `strategy`: `cache_aside` (app manages cache explicitly) or `read_through` (cache sits between app and DB)
  - `invalidation`: `ttl` (expire only), `event` (invalidate on mutation), `both` (TTL + event)

### Purpose
Add a Redis-backed caching layer for read-heavy endpoints. Generates a decorator `@cached(ttl=300, key="items:{item_id}")` that caches endpoint responses, a cache key builder with tenant/user scoping, automatic invalidation on CRUD mutations (create/update/delete clear relevant keys), and cache warming utilities. The tool respects multi-tenancy (cache keys include tenant_id to prevent cross-tenant cache poisoning), uses msgpack serialization for compact storage, and provides cache statistics via a `/cache/stats` admin endpoint. Cache-aside is the default strategy — the app checks cache first, falls back to DB, and fills cache on miss.

### Performance SLOs
- Tool execution time < 4s
- Files modified ≤ 5
- Files created ≥ 8 (cache module, decorator, key builder, invalidation listener, stats endpoint, config, tests)
- Cache hit latency p99 < 2 ms (Redis GET + msgpack decode)
- Cache miss penalty < 5 ms overhead vs uncached (key check + fill)
- Cache key generation < 0.1 ms
- Invalidation propagation < 100 ms (Redis DEL + pubsub)
- Memory efficiency: msgpack ~40% smaller than JSON
- No new DB tables (Redis-only)

### Key technical decisions
1. **Redis namespace:** all cache keys prefixed with `cache:` to separate from other Redis usage (sessions, rate limits, etc.)
2. **Key builder:** `cache:{tenant_id}:{resource}:{id}` for entity keys, `cache:{tenant_id}:{resource}:list:{hash(query_params)}` for list keys. Tenant_id included when multi-tenancy is installed.
3. **Decorator:** `@cached(ttl=300, key_pattern="items:{item_id}")` on route handlers. Extracts path/query params to build key. Returns cached response on hit, calls handler on miss, fills cache.
4. **Invalidation:** SQLAlchemy `after_flush` event listener detects mutations and invalidates matching cache keys. Also publishes invalidation to Redis pubsub for multi-worker consistency.
5. **Serialization:** msgpack for compact binary storage. Falls back to JSON if msgpack not installed.
6. **Cache stampede prevention:** uses Redis `SET NX` as a lock when filling cache on miss. Second concurrent request waits briefly, then falls through to DB.
7. **Cache warming:** `warm_cache(model, ids)` utility that pre-fills cache for a list of entity IDs.
8. **Stats endpoint:** `GET /cache/stats` returns hit/miss ratio, memory usage, key count.
9. **Bypass:** `Cache-Control: no-cache` header or `?nocache=1` query param bypasses cache for that request.
10. **Conditional caching:** only cache 200 responses; never cache errors or redirects.

### Key invariants
1. Cache keys ALWAYS include tenant_id when multi-tenancy is installed (prevent cross-tenant poisoning).
2. A mutation (create/update/delete) ALWAYS invalidates related cache keys before the response is sent.
3. Cache NEVER stores non-200 responses.
4. Cache bypass via `Cache-Control: no-cache` ALWAYS works regardless of TTL.
5. Serialization errors NEVER crash the request — fall through to DB.
6. Cache stampede lock ALWAYS expires (SET NX with TTL) — never deadlocks.
7. Stats endpoint ALWAYS requires admin auth.
8. Cache-aside strategy NEVER writes to cache on mutations — only on read misses.

### User story themes
- 9.1 Cache hit/miss (US-01..05): decorator, hit returns cached, miss fetches+fills, TTL expiry
- 9.2 Invalidation (US-06..10): mutation clears cache, pubsub propagates to workers, partial invalidation
- 9.3 Multi-tenancy & security (US-11..15): tenant-scoped keys, cross-tenant isolation, bypass header
- 9.4 Performance & stampede (US-16..20): stampede prevention, msgpack vs JSON size, warm_cache, stats
- 9.5 Integration & edge cases (US-21..25): soft-delete invalidation, RBAC on stats, tool idempotency

### Test plan categories
- 10.1 Hit/miss (T-01..06): cache miss fills, cache hit returns, TTL expires, bypass works
- 10.2 Invalidation (T-07..12): create invalidates list, update invalidates entity, delete clears, pubsub
- 10.3 Tenant isolation (T-13..18): tenant A can't read tenant B's cache, key format correct
- 10.4 Stampede & serialization (T-19..24): concurrent requests, lock timeout, msgpack round-trip
- 10.5 Stats & integration (T-25..30): stats endpoint, admin auth, soft-delete cache clear, tool idempotency

### Edge cases (15)
1. Redis down → all requests fall through to DB (cache layer degrades gracefully)
2. msgpack not installed → falls back to JSON serialization with warning
3. Cache key too long (> 512 bytes) → hash the key with SHA-256
4. Tenant_id missing in context → cache key omits tenant (warning logged)
5. Two workers race to fill same cache key → SET NX lock prevents duplicate work
6. SET NX lock expires during slow DB query → second worker also fills (idempotent)
7. Cache stores stale data after invalidation pubsub is delayed → TTL is safety net
8. Pagination params change cache key → each (skip, limit) combo is a separate key
9. Cache warm for 10K IDs → batched in groups of 100 to avoid Redis pipeline overflow
10. Response body > 1 MB → skip caching (too large), log warning
11. Non-JSON response (binary file) → skip caching
12. Route handler raises exception → no cache fill (only 200s cached)
13. Cache stats endpoint with no data → returns zeroes, not error
14. Tool re-run idempotent → decorator not duplicated
15. Cache namespace collision with other Redis users → `cache:` prefix prevents it

### Anti-patterns
- DO NOT cache non-200 responses
- DO NOT use JSON when msgpack is available (40% larger)
- DO NOT allow cache keys without tenant_id in multi-tenant apps
- DO NOT skip invalidation on mutations ("I'll add it later")
- DO NOT use a global cache lock (per-key locking only)
- DO NOT cache responses larger than 1 MB by default
